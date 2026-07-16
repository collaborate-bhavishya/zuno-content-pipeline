"""
Eval runner — executes the pipeline against the eval dataset and scores results.

Usage:
  POST /api/eval/run          — run full eval suite (or subset)
  GET  /api/eval/results      — list past eval runs
  GET  /api/eval/results/:id  — single eval run detail

Each eval run produces an EvalRunResult saved to storage/evals/<id>.json.
"""
import json
import os
import time
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import List, Optional

from app.core.config import CONFIG
from app.core.graph import build_graph
from app.core.scorer import score_run, EvalScore

log = logging.getLogger("eval.runner")

EVAL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "storage", "evals")
DATASET_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "evals", "dataset.json")


@dataclass
class EvalRunResult:
    id: str
    timestamp: str
    prompt_version: str          # identifies which prompt/config was used
    model: str
    total_cases: int
    completed_cases: int
    avg_score: float
    grade_distribution: dict     # {"A": 2, "B": 3, ...}
    scores: List[dict] = field(default_factory=list)
    config_snapshot: dict = field(default_factory=dict)
    duration_seconds: float = 0
    error: Optional[str] = None

    def to_dict(self):
        return asdict(self)


def load_dataset(case_ids: Optional[List[str]] = None) -> List[dict]:
    """Load eval cases from dataset.json. Optionally filter by case IDs."""
    with open(DATASET_PATH, "r") as f:
        data = json.load(f)
    cases = data.get("cases", [])
    if case_ids:
        cases = [c for c in cases if c["id"] in case_ids]
    return cases


def _run_single_case(case: dict) -> dict:
    """Run the pipeline for a single eval case and return scored result."""
    theme = case["theme"]
    age = case["age"]
    expected = case["expected"]
    case_id = case["id"]

    log.info("Eval case '%s': theme=%s, age=%d", case_id, theme, age)
    start = time.time()

    try:
        graph = build_graph()
        inputs = {"theme": theme, "target_age": age}
        final_state = {}

        for step in graph.stream(inputs, stream_mode="updates"):
            for node, update in step.items():
                final_state.update(update)

        matrix = final_state.get("raw_question_matrix", [])
        blueprint = final_state.get("blueprint_text", "")
        images = final_state.get("completed_assets", [])
        retries = {
            "blueprint": final_state.get("blueprint_retry_count", 0),
            "matrix": final_state.get("matrix_retry_count", 0),
        }
        history = final_state.get("evaluator_history", [])

        elapsed = round(time.time() - start, 2)
        log.info("Eval case '%s': %d rows, %d images, %.1fs",
                 case_id, len(matrix), len(images), elapsed)

        # Score the output
        eval_score = score_run(
            case_id=case_id, theme=theme, age=age,
            matrix_rows=matrix, expected=expected,
            use_llm_tone=True,
        )

        result = eval_score.to_dict()
        result["duration_seconds"] = elapsed
        result["retries"] = retries
        result["image_count"] = len(images)
        result["evaluator_history"] = history
        result["blueprint_length"] = len(blueprint)
        return result

    except Exception as e:
        elapsed = round(time.time() - start, 2)
        log.error("Eval case '%s' failed: %s", case_id, e)
        return {
            "case_id": case_id, "theme": theme, "age": age,
            "total_score": 0, "grade": "F", "row_count": 0,
            "error": str(e), "duration_seconds": elapsed,
            "dimensions": [], "retries": {}, "image_count": 0,
        }


def run_eval(
    case_ids: Optional[List[str]] = None,
    prompt_version: str = "default",
    skip_images: bool = False,
) -> EvalRunResult:
    """Run the full eval suite (or a subset) and return aggregated results.

    Args:
        case_ids: optional list of case IDs to run (default: all)
        prompt_version: label for this eval run's prompt config
        skip_images: if True, set max_images=0 to speed up eval
    """
    cases = load_dataset(case_ids)
    if not cases:
        return EvalRunResult(
            id="empty", timestamp=datetime.now(timezone.utc).isoformat(),
            prompt_version=prompt_version,
            model=CONFIG.models.generator_model,
            total_cases=0, completed_cases=0,
            avg_score=0, grade_distribution={},
            error="No eval cases found.",
        )

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log.info("Starting eval run '%s' with %d cases (prompt_version=%s)",
             run_id, len(cases), prompt_version)

    # Optionally skip images to speed up evals
    original_max_images = CONFIG.max_images
    if skip_images:
        CONFIG.max_images = 0

    start = time.time()
    scores = []

    for case in cases:
        result = _run_single_case(case)
        scores.append(result)

    # Restore image config
    if skip_images:
        CONFIG.max_images = original_max_images

    duration = round(time.time() - start, 2)
    completed = [s for s in scores if s.get("total_score", 0) > 0 or not s.get("error")]
    avg_score = round(
        sum(s.get("total_score", 0) for s in scores) / len(scores), 1
    ) if scores else 0

    grades = {}
    for s in scores:
        g = s.get("grade", "F")
        grades[g] = grades.get(g, 0) + 1

    # Snapshot the config used for this eval
    config_snapshot = {
        "generator_model": CONFIG.models.generator_model,
        "judge_model": CONFIG.models.judge_model,
        "generator_temperature": CONFIG.models.generator_temperature,
        "max_questions": CONFIG.max_questions,
        "max_images": original_max_images,
        "max_retries": CONFIG.max_retries,
        "prompt_hash": hash(CONFIG.prompts.generator_system[:200]),
    }

    result = EvalRunResult(
        id=run_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        prompt_version=prompt_version,
        model=CONFIG.models.generator_model,
        total_cases=len(cases),
        completed_cases=len(completed),
        avg_score=avg_score,
        grade_distribution=grades,
        scores=scores,
        config_snapshot=config_snapshot,
        duration_seconds=duration,
    )

    # Save to disk
    _save_eval_result(result)
    log.info("Eval run '%s' complete: avg=%.1f, grades=%s, %.1fs",
             run_id, avg_score, grades, duration)

    return result


def _save_eval_result(result: EvalRunResult):
    """Persist eval run to storage/evals/<id>.json."""
    os.makedirs(EVAL_DIR, exist_ok=True)
    path = os.path.join(EVAL_DIR, f"{result.id}.json")
    with open(path, "w") as f:
        json.dump(result.to_dict(), f, indent=2, default=str)


def list_eval_results() -> List[dict]:
    """List all saved eval runs (summary only)."""
    os.makedirs(EVAL_DIR, exist_ok=True)
    results = []
    for fname in sorted(os.listdir(EVAL_DIR), reverse=True):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(EVAL_DIR, fname)
        try:
            with open(path, "r") as f:
                data = json.load(f)
            results.append({
                "id": data.get("id"),
                "timestamp": data.get("timestamp"),
                "prompt_version": data.get("prompt_version"),
                "model": data.get("model"),
                "total_cases": data.get("total_cases"),
                "completed_cases": data.get("completed_cases"),
                "avg_score": data.get("avg_score"),
                "grade_distribution": data.get("grade_distribution"),
                "duration_seconds": data.get("duration_seconds"),
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return results


def get_eval_result(run_id: str) -> Optional[dict]:
    """Load a single eval run by ID."""
    path = os.path.join(EVAL_DIR, f"{run_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)
