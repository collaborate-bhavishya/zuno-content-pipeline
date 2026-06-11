"""
FastAPI backend.

  POST /api/generate    -> SSE stream of pipeline events (the "watch it run" feed)
  POST /api/feedback    -> approve / reject-with-feedback / rerun a finished run
  GET  /api/admin/config (password) -> current models, masked keys, prompts
  POST /api/admin/config (password) -> hot-edit config in memory
  GET  /files/...       -> serves locally stored images
"""
import json
import asyncio
import os
import io
import re
import logging
from datetime import datetime, timezone
from typing import Optional
from PIL import Image

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)-12s %(levelname)s  %(message)s")

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.core.config import CONFIG, ADMIN_PASSWORD, persist_keys_to_env
from app.core.graph import build_graph
from app.core.scorer import score_run as _score_run
from app.core.metrics import init_collector, get_collector, clear_collector

RUNS_FILE = os.path.join(os.path.dirname(__file__), "..", "storage", "runs.json")
RUNS_FILE = os.path.normpath(RUNS_FILE)
# Per-run JSON files live here, named by milestone + skill (theme).
RUNS_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "storage", "runs"))

log = logging.getLogger("main")


def _auto_score(theme: str, age: int, matrix: list) -> dict:
    """Build eval spec from current config and score the matrix. Returns dict."""
    guidelines = CONFIG.output.age_guidelines.get(age, {})
    expected = {
        "allowed_templates": guidelines.get("allowed_templates", []),
        "forbidden_templates": guidelines.get("forbidden_templates", []),
        "max_words_per_sentence": guidelines.get("max_words_per_sentence", 99),
        "must_start_with": "T4",
        "vocab_before_sentence": True,
        "concept_before_sentence": True,
        "t9_before_d1": True,
        "required_columns": 26,
        "no_emoji": True,
        "image_filenames_snake_case": True,
        "stt_clean_lowercase": True,
        "theme_concepts": [],          # auto-runs don't have gold keywords
        "forbidden_themes": ["violence", "injury", "fear", "death",
                             "dark_themes", "body_horror", "weapons", "abuse"],
    }
    try:
        result = _score_run(
            case_id=f"auto_{theme}_{age}",
            theme=theme, age=age,
            matrix_rows=matrix,
            expected=expected,
            use_llm_tone=True,
        )
        return result.to_dict()
    except Exception as e:
        log.warning("Auto-score failed: %s", e)
        return {"total_score": 0, "grade": "?", "error": str(e),
                "dimensions": [], "llm_calls": 0}


def _load_runs() -> list:
    try:
        with open(RUNS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _slug(s: str) -> str:
    """Filesystem-safe lowercase slug (letters/digits/underscores)."""
    s = re.sub(r"[^a-zA-Z0-9]+", "_", str(s or "")).strip("_").lower()
    return s or "untitled"


def _run_base_name(run: dict) -> str:
    """Shared base filename for a run: {milestone}_{theme_code}_{skill}_{run_id}."""
    milestone = _slug(run.get("milestone_code", "AG00"))
    theme_code = _slug(run.get("theme_code", "T00"))
    skill = _slug(run.get("theme", "lesson"))
    run_id = run.get("id", datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"))
    return f"{milestone}_{theme_code}_{skill}_{run_id}"


def _save_run_file(run: dict) -> str:
    """Write the full self-contained run JSON locally (named by milestone + skill)."""
    os.makedirs(RUNS_DIR, exist_ok=True)
    path = os.path.join(RUNS_DIR, _run_base_name(run) + ".json")
    with open(path, "w") as f:
        json.dump(run, f, indent=2, default=str, ensure_ascii=False)
    return path


# ── S3-format transform ───────────────────────────────────────────────
# Maps our internal 26-column matrix → the flat S3 question schema
# (see Downloads/test_data.json). Most fields are 1:1; two collapse
# (priorities confirmed by product):
#   Screen Text  = Instruction Text, else Text in Question
#   Audio Script = Instruction VO, else VO for Question, else Audio in Question
_S3_DASH = "—"


def _s3_val(*vals) -> str:
    """First non-empty / non-dash value, else the em-dash placeholder."""
    for v in vals:
        s = str(v if v is not None else "").strip()
        if s and s != _S3_DASH:
            return s
    return _S3_DASH


def _to_s3_questions(run: dict) -> list:
    rows = run.get("matrix") or []
    fallback_pcode = (f"{str(run.get('milestone_code','')).strip()}"
                      f"{str(run.get('theme_code','')).strip()}P1")
    out = []
    for i, r in enumerate(rows):
        qnum = str(r.get("Q#", "")).strip() or f"Q{i+1}"
        pcode = str(r.get("Playable Code", "")).strip() or fallback_pcode
        out.append({
            "Q#": qnum,
            "Playable Code": pcode,
            "Playable": _s3_val(r.get("Playable Name"), r.get("Playable")),
            "Layer": _s3_val(r.get("Layer")),
            "Template": _s3_val(r.get("Template")),
            # ── collapsed fields (priorities confirmed by product) ──
            "Screen Text": _s3_val(r.get("Instruction Text"), r.get("Text in Question"), r.get("Screen Text")),
            "Audio Script": _s3_val(r.get("Instruction VO"), r.get("VO for Question"),
                                    r.get("Audio in Question"), r.get("Audio Script")),
            "STT Expectation": _s3_val(r.get("STT Expectation")),
            "Image in Question": _s3_val(r.get("Image in Question — Name"), r.get("Image in Question")),
            "Correct Answer": _s3_val(r.get("Correct Answer")),
            "Correct Answer — Image": _s3_val(r.get("Correct Answer — Image")),
            "Other Options": _s3_val(r.get("Other Options")),
            "Other Options — Image": _s3_val(r.get("Other Options — Image")),
            "Concept (bucket / skill)": _s3_val(r.get("Concept (bucket / skill)")),
            "Pattern": _s3_val(r.get("Pattern")),
            "Notes": _s3_val(r.get("Notes")),
            "": "",
            "Audio file Name": f"{pcode.lower()}_{qnum.lower()}",
        })
    return out


def _save_s3_file(run: dict):
    """Write the transformed `_s3` JSON (flat question array) locally. Returns (path, filename)."""
    os.makedirs(RUNS_DIR, exist_ok=True)
    fname = _run_base_name(run) + "_s3.json"
    path = os.path.join(RUNS_DIR, fname)
    with open(path, "w") as f:
        json.dump(_to_s3_questions(run), f, indent=2, ensure_ascii=False)
    return path, fname


def _upload_json_to_s3(local_path: str, filename: str):
    """Upload a per-run JSON file to S3 if S3_BUCKET is configured.

    Env: S3_BUCKET (required to enable), S3_PREFIX (default 'runs'),
    AWS_REGION, AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (or the standard
    AWS credential chain). Returns the s3:// URI or None.
    """
    bucket = os.getenv("S3_BUCKET")
    if not bucket:
        return None
    import boto3
    # Default to bucket root ("") so the player's ?id={name} → {name}.json resolves.
    prefix = os.getenv("S3_PREFIX", "").strip("/")
    region = os.getenv("AWS_REGION", "ap-south-1")
    key = f"{prefix}/{filename}" if prefix else filename
    session_kwargs = {"region_name": region}
    ak, sk = os.getenv("AWS_ACCESS_KEY_ID"), os.getenv("AWS_SECRET_ACCESS_KEY")
    if ak and sk:
        session_kwargs["aws_access_key_id"] = ak
        session_kwargs["aws_secret_access_key"] = sk
        if os.getenv("AWS_SESSION_TOKEN"):
            session_kwargs["aws_session_token"] = os.getenv("AWS_SESSION_TOKEN")
    s3 = boto3.session.Session(**session_kwargs).client("s3")
    s3.upload_file(local_path, bucket, key,
                   ExtraArgs={"ContentType": "application/json"})
    return f"s3://{bucket}/{key}"


def _play_url_for(run: dict) -> str:
    """Player URL for the run's S3 JSON: {PLAY_URL_BASE}{s3_filename_without_.json}.
    e.g. https://speak.zunolearn.com/?id=ag05_t01_jungle_20260611_094523_s3
    """
    base = os.getenv("PLAY_URL_BASE", "https://speak.zunolearn.com/?id=")
    s3_id = _run_base_name(run) + "_s3"   # the S3 file name, sans .json
    return f"{base}{s3_id}"


def _save_run(run: dict):
    # Deterministic player URL for this run's S3 JSON (set before saving so it
    # is persisted in every copy: full file, _s3 metadata, and runs.json).
    run["play_url"] = _play_url_for(run)

    # 1) Full per-run JSON file (local only — named by milestone + skill).
    try:
        log.info("Saved run file: %s", _save_run_file(run))
    except Exception as e:
        log.warning("Failed to write per-run file: %s", e)
    # 2) S3-format `_s3` file (local copy) — this is the ONLY file pushed to S3.
    try:
        s3_path, s3_name = _save_s3_file(run)
        log.info("Saved S3-format file: %s", s3_path)
        try:
            uri = _upload_json_to_s3(s3_path, s3_name)
            if uri:
                run["s3_uri"] = uri
                log.info("Uploaded to S3: %s", uri)
                log.info("Play URL: %s", run["play_url"])
        except Exception as e:
            log.warning("S3 upload failed (file still saved locally): %s", e)
    except Exception as e:
        log.warning("Failed to write _s3 file: %s", e)
    # 2) Append to the aggregate runs.json (powers the history list).
    runs = _load_runs()
    runs.insert(0, run)
    os.makedirs(os.path.dirname(RUNS_FILE), exist_ok=True)
    with open(RUNS_FILE, "w") as f:
        json.dump(runs, f, indent=2, default=str)

app = FastAPI(title="Zuno SpeakX Pipeline")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for production
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve locally stored images (no-op effect if using GCS)
app.mount("/files", StaticFiles(directory="storage"), name="files")


# Friendly labels for each graph node, shown in the live feed
NODE_LABELS = {
    "planner": ("Planner agent", "Writing the lesson blueprint"),
    "blueprint_evaluator": ("Blueprint evaluator", "Auditing tone, safety, pedagogy"),
    "fabricator": ("Fabricator agent", "Building the question matrix"),
    "matrix_evaluator": ("Matrix evaluator", "Validating structure"),
    "asset_planner": ("Asset planner", "Listing images to generate"),
    "image_factory": ("Image factory", "Rendering an illustration"),
    "vision_critic": ("Vision critic", "Auditing the image pixels"),
    "eval": ("Eval scorer", "Scoring output against SpeakX rubric"),
}


class GenerateRequest(BaseModel):
    theme: str
    age: int
    milestone_code: str = "AG05"    # e.g. "AG03", "AG05"
    theme_code: str = "T01"         # e.g. "T01", "T02"


def _event(kind: str, **data) -> str:
    return f"data: {json.dumps({'kind': kind, **data})}\n\n"


def _summarize(node: str, update: dict) -> dict:
    """Turn a node's state delta into a compact, JSON-safe feed payload."""
    safe = {}
    if "blueprint_text" in update:
        bp = update["blueprint_text"]
        safe["preview"] = bp[:240] + ("…" if len(bp) > 240 else "")
    if "gate_decision" in update:
        safe["decision"] = update["gate_decision"]
    if "matrix_gate_decision" in update:
        safe["decision"] = update["matrix_gate_decision"]
    if "image_gate_decision" in update:
        safe["decision"] = update["image_gate_decision"]
    if update.get("blueprint_error_log"):
        safe["critique"] = update["blueprint_error_log"]
    if update.get("matrix_error_log"):
        safe["critique"] = update["matrix_error_log"]
    if update.get("image_error_log"):
        safe["critique"] = update["image_error_log"]
    if "raw_question_matrix" in update and update["raw_question_matrix"] is not None:
        safe["rows"] = len(update["raw_question_matrix"])
    if "completed_assets" in update:
        safe["completed"] = update["completed_assets"]
    if update.get("quota_exhausted"):
        pending = update.get("pending_assets", [])
        safe["quota_exhausted"] = True
        safe["pending_count"] = len(pending)
    if update.get("image_quota_wait"):
        safe["quota_wait"] = True
    if "eval_result" in update:
        ev = update["eval_result"]
        safe["decision"] = f"grade {ev.get('grade', '?')} — {ev.get('total_score', 0)}/100"
    # Attach per-node metrics from collector
    mc = get_collector()
    if mc:
        node_metrics = mc.get_node_metrics(node)
        if node_metrics:
            safe["metrics"] = node_metrics
    return safe


async def run_stream(theme: str, age: int, milestone_code: str = "AG05", theme_code: str = "T01"):
    mc = init_collector()
    graph = build_graph()
    inputs = {"theme": theme, "target_age": age,
              "milestone_code": milestone_code, "theme_code": theme_code}
    final_state = {}

    yield _event("start", theme=theme, age=age)

    sent_questions = False
    feed = []  # accumulate the process log so it can be replayed for past runs
    try:
        # LangGraph streams one item per node execution as {node_name: state_delta}
        for step in graph.stream(inputs, {"recursion_limit": 100}, stream_mode="updates"):
            for node, update in step.items():
                label, action = NODE_LABELS.get(node, (node, ""))
                detail = _summarize(node, update)
                feed.append({"node": node, "label": label, "action": action, "detail": detail})
                yield _event("node", node=node, label=label, action=action, detail=detail)
                final_state.update(update)
                # Emit the question matrix once Phase 2 has proceeded (asset_planner
                # only runs after the matrix is accepted — clean pass OR graceful
                # degrade), so the user can review questions while images — which are
                # quota-limited and slow — keep generating in the background.
                if not sent_questions and node == "asset_planner":
                    sent_questions = True
                    yield _event("questions_ready",
                                 blueprint=final_state.get("blueprint_text", ""),
                                 matrix=final_state.get("raw_question_matrix", []) or [])
                await asyncio.sleep(0)  # let the event flush
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        log.error("run_stream failed: %s\n%s", e, tb)
        clear_collector()
        # Persist whatever partial output we have so the run isn't lost
        try:
            partial = {
                "id": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "theme": theme, "age": age,
                "milestone_code": final_state.get("milestone_code", milestone_code),
                "theme_code": final_state.get("theme_code", theme_code),
                "blueprint": final_state.get("blueprint_text", ""),
                "matrix": final_state.get("raw_question_matrix", []) or [],
                "images": final_state.get("completed_assets", []),
                "failed": final_state.get("failed_assets", []),
                "pending_images": final_state.get("pending_assets", []),
                "history": final_state.get("evaluator_history", []),
                "eval": final_state.get("eval_result") or {},
                "metrics": None,
                "error": str(e),
            }
            _save_run(partial)
        except Exception:
            pass
        yield _event("error", message=str(e),
                     detail=f"{type(e).__name__}: {e}",
                     last_node=list(final_state.keys())[-5:] if final_state else [])
        return

    # Final consolidated output for the right-hand panel
    matrix = final_state.get("raw_question_matrix", [])
    eval_result = final_state.get("eval_result") or {}

    # Finalize metrics
    retries = {
        "blueprint": max(0, final_state.get("blueprint_retry_count", 1) - 1),
        "matrix": max(0, final_state.get("matrix_retry_count", 1) - 1),
        "image": final_state.get("image_retry_count", 0),
    }
    metrics = mc.finalize(retries).to_dict()
    clear_collector()

    run_data = {
        "id": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "theme": theme,
        "age": age,
        "milestone_code": final_state.get("milestone_code", milestone_code),
        "theme_code": final_state.get("theme_code", theme_code),
        "blueprint": final_state.get("blueprint_text", ""),
        "matrix": matrix,
        "images": final_state.get("completed_assets", []),
        "failed": final_state.get("failed_assets", []),
        "wrong_generations": final_state.get("wrong_generations", []),
        "pending_images": final_state.get("pending_assets", []),
        "history": final_state.get("evaluator_history", []),
        "eval": eval_result,
        "metrics": metrics,
        "feed": feed,
    }
    _save_run(run_data)

    yield _event("complete", **{k: v for k, v in run_data.items()
                                if k not in ("id", "timestamp", "feed")})


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    return StreamingResponse(
        run_stream(req.theme, req.age, req.milestone_code, req.theme_code),
        media_type="text/event-stream",
    )


class FeedbackRequest(BaseModel):
    action: str               # "approve" | "feedback" | "rerun"
    theme: str
    age: int
    feedback: Optional[str] = None
    phase: Optional[str] = None       # "all" | "blueprint" | "questions" | "images"
    run_id: Optional[str] = None      # needed for partial re-runs
    milestone_code: str = "AG05"
    theme_code: str = "T01"


@app.post("/api/feedback")
async def feedback(req: FeedbackRequest):
    """
    Approve just records acceptance. Feedback/rerun re-invoke the pipeline.
    Partial re-runs skip completed phases by seeding state from the previous run.
    """
    if req.action == "approve":
        return {"status": "approved"}

    phase = req.phase or "all"

    # For partial re-runs, load previous run data to seed state
    prev_run = None
    if phase != "all" and req.run_id:
        runs = _load_runs()
        prev_run = next((r for r in runs if r["id"] == req.run_id), None)

    seed: dict = {"theme": req.theme, "target_age": req.age,
                  "milestone_code": req.milestone_code, "theme_code": req.theme_code}

    if phase == "questions" and prev_run:
        # Keep existing blueprint, re-run from fabricator
        seed["blueprint_text"] = prev_run.get("blueprint", "")
        seed["blueprint_retry_count"] = 1
        seed["gate_decision"] = "proceed_to_questions"
        if req.feedback:
            seed["matrix_error_log"] = f"Human reviewer feedback: {req.feedback}"
    elif phase == "images" and prev_run:
        # Keep blueprint + matrix, re-run only images
        seed["blueprint_text"] = prev_run.get("blueprint", "")
        seed["blueprint_retry_count"] = 1
        seed["gate_decision"] = "proceed_to_questions"
        seed["raw_question_matrix"] = prev_run.get("matrix", [])
        seed["matrix_retry_count"] = 1
        seed["matrix_gate_decision"] = "trigger_assets"
    else:
        # Full re-run
        if req.feedback:
            seed["blueprint_error_log"] = f"Human reviewer feedback: {req.feedback}"

    # Pick the right entry point based on phase
    entry_node = {
        "all": "planner",
        "blueprint": "planner",
        "questions": "fabricator",
        "images": "asset_planner",
    }.get(phase, "planner")

    async def rerun():
        mc = init_collector()

        if entry_node == "planner":
            # Full pipeline
            graph = build_graph()
            final = {}
            yield _event("start", theme=req.theme, age=req.age, rerun=True,
                         phase=phase)
            for step in graph.stream(seed, {"recursion_limit": 100}, stream_mode="updates"):
                for node, update in step.items():
                    label, action = NODE_LABELS.get(node, (node, ""))
                    yield _event("node", node=node, label=label, action=action,
                                 detail=_summarize(node, update))
                    final.update(update)
                    await asyncio.sleep(0)
        else:
            # Partial pipeline — build a sub-graph starting from the entry node
            from langgraph.graph import StateGraph, END
            from app.core.state import LessonState
            from app.nodes.graph_nodes import (
                fabricator_node, matrix_evaluator_node, route_matrix,
                asset_planner_node, eval_node,
                image_factory_node, vision_critic_node, route_image,
                route_after_factory,
            )
            wf = StateGraph(LessonState)
            final = dict(seed)

            if entry_node == "fabricator":
                wf.add_node("fabricator", fabricator_node)
                wf.add_node("matrix_evaluator", matrix_evaluator_node)
                wf.add_node("asset_planner", asset_planner_node)
                wf.add_node("eval", eval_node)
                wf.add_node("image_factory", image_factory_node)
                wf.add_node("vision_critic", vision_critic_node)
                wf.set_entry_point("fabricator")
                wf.add_edge("fabricator", "matrix_evaluator")
                wf.add_conditional_edges("matrix_evaluator", route_matrix, {
                    "regenerate": "fabricator",
                    "hard_fail": END,
                    "trigger_assets": "asset_planner",
                })
                wf.add_edge("asset_planner", "eval")
                wf.add_edge("eval", "image_factory")
                wf.add_conditional_edges("image_factory", route_after_factory, {
                    "critic": "vision_critic",
                    "all_done": END,
                })
                wf.add_conditional_edges("vision_critic", route_image, {
                    "retry": "image_factory",
                    "next": "image_factory",
                    "all_done": END,
                })
            elif entry_node == "asset_planner":
                wf.add_node("asset_planner", asset_planner_node)
                wf.add_node("eval", eval_node)
                wf.add_node("image_factory", image_factory_node)
                wf.add_node("vision_critic", vision_critic_node)
                wf.set_entry_point("asset_planner")
                wf.add_edge("asset_planner", "eval")
                wf.add_edge("eval", "image_factory")
                wf.add_conditional_edges("image_factory", route_after_factory, {
                    "critic": "vision_critic",
                    "all_done": END,
                })
                wf.add_conditional_edges("vision_critic", route_image, {
                    "retry": "image_factory",
                    "next": "image_factory",
                    "all_done": END,
                })

            graph = wf.compile()
            yield _event("start", theme=req.theme, age=req.age, rerun=True,
                         phase=phase)
            for step in graph.stream(seed, {"recursion_limit": 100}, stream_mode="updates"):
                for node, update in step.items():
                    label, action = NODE_LABELS.get(node, (node, ""))
                    yield _event("node", node=node, label=label, action=action,
                                 detail=_summarize(node, update))
                    final.update(update)
                    await asyncio.sleep(0)

        matrix = final.get("raw_question_matrix", [])
        eval_result = final.get("eval_result") or {}

        retries = {
            "blueprint": max(0, final.get("blueprint_retry_count", 1) - 1),
            "matrix": max(0, final.get("matrix_retry_count", 1) - 1),
            "image": final.get("image_retry_count", 0),
        }
        metrics = mc.finalize(retries).to_dict()
        clear_collector()

        run_data = {
            "id": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "theme": req.theme,
            "age": req.age,
            "milestone_code": req.milestone_code,
            "theme_code": req.theme_code,
            "blueprint": final.get("blueprint_text", ""),
            "matrix": matrix,
            "images": final.get("completed_assets", []),
            "failed": final.get("failed_assets", []),
            "pending_images": final.get("pending_assets", []),
            "history": final.get("evaluator_history", []),
            "eval": eval_result,
            "metrics": metrics,
        }
        _save_run(run_data)

        yield _event("complete", **{k: v for k, v in run_data.items()
                                    if k not in ("id", "timestamp")})

    return StreamingResponse(rerun(), media_type="text/event-stream")


# ===================== RETRY IMAGES =====================

@app.post("/api/retry-images/{run_id}")
async def retry_images(run_id: str):
    """Retry pending images for a run whose image quota was exhausted."""
    runs = _load_runs()
    run = next((r for r in runs if r["id"] == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    pending = run.get("pending_images", [])
    if not pending:
        raise HTTPException(status_code=400, detail="No pending images to retry")

    async def stream():
        from app.core.llm import render_image_bytes, get_vision_judge
        from app.core.storage import STORAGE
        from app.nodes.graph_nodes import _eye_rule, LIVING_KEYWORDS, build_image_prompt

        completed = list(run.get("images", []))
        failed = list(run.get("failed", []))
        remaining = list(pending)
        quota_hit = False

        yield _event("start", theme=run["theme"], age=run["age"],
                     retry_images=True, pending=len(pending))

        for i, asset in enumerate(pending):
            if quota_hit:
                break

            obj_name = asset["object_name"]
            eye = _eye_rule(obj_name)
            prompt = build_image_prompt(asset, eye)

            yield _event("node", node="image_factory", label="Image factory",
                         action=f"Rendering '{obj_name}' ({i+1}/{len(pending)})",
                         detail={})

            for attempt in range(CONFIG.max_retries):
                try:
                    raw = render_image_bytes(prompt)
                    if not raw:
                        continue
                    pil = Image.open(io.BytesIO(raw))

                    # Quick vision check
                    import base64 as b64mod
                    buf = io.BytesIO(); pil.save(buf, format="PNG")
                    data_uri = "data:image/png;base64," + b64mod.b64encode(buf.getvalue()).decode()
                    judge = get_vision_judge()
                    sys_p = CONFIG.prompts.vision_critic_system.format(
                        object_name=obj_name, eye_rule=eye)
                    r = judge.invoke([
                        ("system", sys_p),
                        {"role": "user", "content": [
                            {"type": "text", "text": f"Audit this {obj_name} asset."},
                            {"type": "image_url", "image_url": {"url": data_uri}}]}
                    ])
                    clean = r.content.replace("```json", "").replace("```", "").strip()
                    try:
                        verdict = json.loads(clean)
                    except Exception:
                        verdict = {"pass": "true" in clean.lower()}

                    if verdict.get("pass"):
                        url = STORAGE.save_image(pil, asset["filename"])
                        # Mark as generated in Supabase DB
                        try:
                            from app.core.db import mark_generated as _db_mark
                            _db_mark(asset["filename"], image_url=url)
                        except Exception:
                            pass
                        completed.append({"filename": asset["filename"], "url": url,
                                          "object_name": obj_name})
                        remaining.remove(asset)
                        yield _event("node", node="vision_critic", label="Vision critic",
                                     action=f"Approved '{obj_name}'",
                                     detail={"decision": "advance",
                                             "completed": [{"filename": asset["filename"],
                                                           "url": url, "object_name": obj_name}]})
                        break
                    else:
                        reason = verdict.get("reason", "rejected")
                        prompt += f" Fix: {reason}"
                        if attempt == CONFIG.max_retries - 1:
                            failed.append(asset["filename"])
                            remaining.remove(asset)

                except Exception as e:
                    if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e).upper() or "quota" in str(e).lower():
                        log.warning("Retry images: quota exhausted again at asset '%s'", obj_name)
                        quota_hit = True
                        yield _event("node", node="image_factory",
                                     label="Image factory",
                                     action=f"Quota exhausted — {len(remaining)} images still pending",
                                     detail={"quota_exhausted": True,
                                             "pending_count": len(remaining)})
                        break
                    if attempt == CONFIG.max_retries - 1:
                        failed.append(asset["filename"])
                        remaining.remove(asset)

                await asyncio.sleep(0)

        # Update the run record
        run["images"] = completed
        run["failed"] = failed
        run["pending_images"] = remaining
        _save_runs(runs)

        yield _event("complete", theme=run["theme"], age=run["age"],
                     images=completed, failed=failed,
                     pending_images=remaining,
                     blueprint=run.get("blueprint", ""),
                     matrix=run.get("matrix", []),
                     history=run.get("history", []),
                     eval=run.get("eval"))

    return StreamingResponse(stream(), media_type="text/event-stream")


def _save_runs(runs: list):
    """Save the full runs list to disk."""
    os.makedirs(os.path.dirname(RUNS_FILE), exist_ok=True)
    with open(RUNS_FILE, "w") as f:
        json.dump(runs, f, indent=2, default=str)


class ImageReviewRequest(BaseModel):
    filename: str
    action: str   # "use" | "reject"


@app.post("/api/image-review/{run_id}")
async def image_review(run_id: str, body: ImageReviewRequest):
    """Manually resolve a vision-critic-rejected image: 'use' promotes it to the
    real asset (Supabase status -> 1), 'reject' discards it."""
    from app.core.storage import STORAGE
    from app.core.db import mark_generated
    runs = _load_runs()
    run = next((r for r in runs if r["id"] == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    wrong = run.get("wrong_generations", [])
    entry = next((w for w in wrong if w.get("filename") == body.filename), None)
    if not entry:
        raise HTTPException(status_code=404, detail="No image pending review with that filename")
    wrong_name = entry.get("wrong_image") or f"wrong_{body.filename}"

    if body.action == "use":
        url = entry.get("url", "")
        try:
            url = STORAGE.copy_image(wrong_name, body.filename)   # promote to real filename
        except Exception as e:
            log.warning("image-review copy failed (%s); falling back to stored url", e)
        try:
            mark_generated(body.filename, image_url=url)          # Supabase status -> 1
        except Exception as e:
            log.warning("image-review mark_generated failed: %s", e)
        obj = body.filename[:-4].replace("_", " ") if body.filename.endswith(".png") else body.filename
        run["images"] = run.get("images", []) + [
            {"filename": body.filename, "url": url, "object_name": obj}]
        run["wrong_generations"] = [w for w in wrong if w.get("filename") != body.filename]
    elif body.action == "reject":
        run["wrong_generations"] = [w for w in wrong if w.get("filename") != body.filename]
        try:
            STORAGE.delete_image(wrong_name)
        except Exception:
            pass
    else:
        raise HTTPException(status_code=400, detail="action must be 'use' or 'reject'")

    _save_runs(runs)
    return {"images": run.get("images", []),
            "wrong_generations": run.get("wrong_generations", [])}


# ===================== ADMIN =====================

def _check_admin(pw: Optional[str]):
    if pw != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Bad admin password")


@app.get("/api/admin/config")
async def get_config(x_admin_password: Optional[str] = Header(None)):
    _check_admin(x_admin_password)
    return CONFIG.public_dict()


@app.get("/api/run-mode")
async def get_run_mode():
    """Public (no-auth) trial-mode status, so the UI can warn before a run."""
    return {
        "trial_mode": bool(CONFIG.trial_mode),
        "max_questions": CONFIG.effective_max_questions,
        "max_images": CONFIG.effective_max_images,
    }


class AdminUpdate(BaseModel):
    models: Optional[dict] = None
    prompts: Optional[dict] = None
    keys: Optional[dict] = None          # only non-empty values applied
    limits: Optional[dict] = None
    output: Optional[dict] = None


@app.post("/api/admin/config")
async def update_config(body: AdminUpdate,
                        x_admin_password: Optional[str] = Header(None)):
    _check_admin(x_admin_password)
    if body.models:
        for k, v in body.models.items():
            if hasattr(CONFIG.models, k):
                setattr(CONFIG.models, k, v)
    if body.prompts:
        for k, v in body.prompts.items():
            if hasattr(CONFIG.prompts, k):
                setattr(CONFIG.prompts, k, v)
    if body.keys:
        for k, v in body.keys.items():
            if v and hasattr(CONFIG.keys, k):   # ignore blanks / masked values
                setattr(CONFIG.keys, k, v)
        persist_keys_to_env(body.keys)          # write non-empty keys to .env
    if body.limits:
        for k, v in body.limits.items():
            if hasattr(CONFIG, k):
                if k == "trial_mode":
                    setattr(CONFIG, k, bool(v))
                else:
                    setattr(CONFIG, k, v)
    if body.output:
        if "matrix_columns" in body.output:
            CONFIG.output.matrix_columns = body.output["matrix_columns"]
        if "age_guidelines" in body.output:
            CONFIG.output.age_guidelines = {
                int(k): v for k, v in body.output["age_guidelines"].items()
            }
    return CONFIG.public_dict()


@app.get("/api/runs")
async def get_runs():
    return _load_runs()


# ===================== EVALS =====================

class EvalRequest(BaseModel):
    case_ids: Optional[list] = None     # null = run all
    prompt_version: str = "default"
    skip_images: bool = True            # faster evals by default

class ScoreRequest(BaseModel):
    """Score an existing run's matrix against the eval rubric."""
    run_index: int = 0                  # index into runs.json
    case_id: str = "adhoc"


@app.post("/api/eval/run")
async def run_eval_endpoint(req: EvalRequest):
    """Run the eval suite. This is synchronous and may take minutes."""
    from app.core.eval_runner import run_eval
    result = run_eval(
        case_ids=req.case_ids,
        prompt_version=req.prompt_version,
        skip_images=req.skip_images,
    )
    return result.to_dict()


@app.post("/api/eval/run/stream")
async def run_eval_stream(req: EvalRequest):
    """Run the eval suite with SSE progress updates."""
    from app.core.eval_runner import load_dataset, _run_single_case, _save_eval_result, EvalRunResult
    import time as _time

    cases = load_dataset(req.case_ids)
    original_max_images = CONFIG.max_images
    if req.skip_images:
        CONFIG.max_images = 0

    async def _stream():
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        yield _event("eval_start", run_id=run_id, total_cases=len(cases))
        start = _time.time()
        scores = []

        for i, case in enumerate(cases):
            yield _event("eval_case_start", index=i, case_id=case["id"],
                         theme=case["theme"], age=case["age"])
            result = _run_single_case(case)
            scores.append(result)
            yield _event("eval_case_done", index=i, case_id=case["id"],
                         score=result.get("total_score", 0),
                         grade=result.get("grade", "F"),
                         duration=result.get("duration_seconds", 0))
            await asyncio.sleep(0)

        if req.skip_images:
            CONFIG.max_images = original_max_images

        duration = round(_time.time() - start, 2)
        avg = round(sum(s.get("total_score", 0) for s in scores) / len(scores), 1) if scores else 0
        grades = {}
        for s in scores:
            g = s.get("grade", "F")
            grades[g] = grades.get(g, 0) + 1

        run_result = EvalRunResult(
            id=run_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            prompt_version=req.prompt_version,
            model=CONFIG.models.generator_model,
            total_cases=len(cases),
            completed_cases=len([s for s in scores if not s.get("error")]),
            avg_score=avg,
            grade_distribution=grades,
            scores=scores,
            config_snapshot={
                "generator_model": CONFIG.models.generator_model,
                "max_questions": CONFIG.max_questions,
                "max_retries": CONFIG.max_retries,
            },
            duration_seconds=duration,
        )
        _save_eval_result(run_result)
        yield _event("eval_complete", run_id=run_id, avg_score=avg,
                      grades=grades, duration=duration, scores=scores)

    return StreamingResponse(_stream(), media_type="text/event-stream")


@app.post("/api/eval/score")
async def score_existing_run(req: ScoreRequest):
    """Score an already-completed pipeline run against the eval rubric."""
    from app.core.scorer import score_run
    runs = _load_runs()
    if req.run_index >= len(runs):
        raise HTTPException(404, "Run not found")
    run = runs[req.run_index]
    matrix = run.get("matrix", [])
    age = run.get("age", 5)
    theme = run.get("theme", "unknown")

    # Build expected spec from current age guidelines
    guidelines = CONFIG.output.age_guidelines.get(age, {})
    expected = {
        "allowed_templates": guidelines.get("allowed_templates", []),
        "forbidden_templates": guidelines.get("forbidden_templates", []),
        "max_words_per_sentence": guidelines.get("max_words_per_sentence", 99),
        "must_start_with": "T4",
        "vocab_before_sentence": True,
        "concept_before_sentence": True,
        "t9_before_d1": True,
        "required_columns": 26,
        "no_emoji": True,
        "image_filenames_snake_case": True,
        "stt_clean_lowercase": True,
        "tone_keywords": [],
        "forbidden_content": [],
    }

    result = score_run(
        case_id=req.case_id, theme=theme, age=age,
        matrix_rows=matrix, expected=expected, use_llm_tone=True,
    )
    return result.to_dict()


@app.get("/api/eval/results")
async def list_eval_results():
    from app.core.eval_runner import list_eval_results as _list
    return _list()


@app.get("/api/eval/results/{run_id}")
async def get_eval_result(run_id: str):
    from app.core.eval_runner import get_eval_result as _get
    result = _get(run_id)
    if not result:
        raise HTTPException(404, "Eval run not found")
    return result


@app.get("/api/eval/dataset")
async def get_eval_dataset():
    """Return the eval dataset for the frontend to display."""
    from app.core.eval_runner import load_dataset
    return load_dataset()


@app.get("/api/health")
async def health():
    return {"status": "ok"}
