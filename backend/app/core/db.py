"""Supabase image-asset DB layer.

Tracks every image the pipeline has ever generated so repeat requests
skip already-generated assets.  Table: `image_assets`.

Columns:
  image_name      TEXT UNIQUE   — canonical filename (e.g. red_apple.png)
  image_detail    TEXT           — generation prompt / subject description
  image_url       TEXT           — public URL or local path after generation
  status          SMALLINT       — 0 = pending, 1 = generated
  milestone_code  TEXT
  theme_code      TEXT
  playable_code   TEXT
"""

import os, logging
from typing import Optional
from supabase import create_client, Client

log = logging.getLogger(__name__)

_client: Optional[Client] = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_KEY", "")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in .env")
        _client = create_client(url, key)
    return _client


# ── queries ──────────────────────────────────────────────────────────

def lookup_existing(image_names: list[str]) -> dict[str, dict]:
    """Return {image_name: row_dict} for every name already in the DB with status=1."""
    if not image_names:
        return {}
    client = get_client()
    # Supabase 'in' filter
    result = client.table("image_assets").select("*").in_("image_name", image_names).eq("status", 1).execute()
    return {row["image_name"]: row for row in (result.data or [])}


def upsert_pending(assets: list[dict]):
    """Insert new image rows as status=0 (pending).  Skip if name already exists."""
    if not assets:
        return
    client = get_client()
    rows = [
        {
            "image_name": a["filename"],
            "image_detail": a.get("detail", ""),
            "status": 0,
            "milestone_code": a.get("milestone_code", ""),
            "theme_code": a.get("theme_code", ""),
            "playable_code": a.get("playable_code", ""),
        }
        for a in assets
    ]
    # on_conflict: if image_name already exists, don't overwrite
    try:
        client.table("image_assets").upsert(
            rows, on_conflict="image_name", ignore_duplicates=True
        ).execute()
    except Exception as e:
        log.warning("upsert_pending: %s", e)


def mark_generated(image_name: str, image_url: str = ""):
    """Set status=1 and optionally store the URL/path.

    No in-repo callers: this is the ledger's write-back hook for the external
    image-generation process that renders pending (status=0) assets."""
    client = get_client()
    try:
        client.table("image_assets").update(
            {"status": 1, "image_url": image_url}
        ).eq("image_name", image_name).execute()
    except Exception as e:
        log.warning("mark_generated(%s): %s", image_name, e)


def get_all_assets(milestone_code: str = "", theme_code: str = "") -> list[dict]:
    """Fetch all rows, optionally filtered by milestone/theme."""
    client = get_client()
    q = client.table("image_assets").select("*")
    if milestone_code:
        q = q.eq("milestone_code", milestone_code)
    if theme_code:
        q = q.eq("theme_code", theme_code)
    result = q.order("created_at").execute()
    return result.data or []


# ── question storage (runs + questions tables) ─────────────────────────
# See backend/supabase/schema_questions.sql for DDL.

def save_run(run: dict) -> None:
    """Upsert a run's metadata row into `runs`. Safe to call more than once for
    the same id (e.g. a partial/error save followed by a full completion)."""
    client = get_client()
    eval_result = run.get("eval") or {}
    row = {
        "id": run["id"],
        "theme": run.get("theme", ""),
        "target_age": run.get("age", 0),
        "milestone_code": run.get("milestone_code", ""),
        "theme_code": run.get("theme_code", ""),
        "status": "failed" if run.get("error") else "completed",
        "blueprint_text": run.get("blueprint", ""),
        "eval_grade": eval_result.get("grade"),
        "eval_score": eval_result.get("total_score"),
        "eval_result": eval_result,
        "metrics": run.get("metrics"),
        "evaluator_history": run.get("history", []),
        "play_url": run.get("play_url", ""),
        "s3_uri": run.get("s3_uri", ""),
        "error": run.get("error"),
    }
    client.table("runs").upsert(row, on_conflict="id").execute()


def _clean(value) -> Optional[str]:
    """'—' and blank strings mean 'not applicable' upstream — store as NULL."""
    s = str(value if value is not None else "").strip()
    return None if (not s or s == "—") else s


def _split(value) -> list[str]:
    """Comma-joined matrix cell (e.g. distractor text/files) -> string array."""
    s = _clean(value)
    return [t.strip() for t in s.split(",")] if s else []


def save_questions(run_id: str, matrix: list[dict]) -> None:
    """Replace this run's question rows with the current matrix (handles reruns)."""
    if not matrix:
        return
    client = get_client()
    rows = [
        {
            "run_id": run_id,
            "row_index": i,
            "playable_code": _clean(r.get("Playable Code")) or "",
            "playable_name": _clean(r.get("Playable Name")),
            "layer": _clean(r.get("Layer")),
            "template": _clean(r.get("Template")),
            "instruction_text": _clean(r.get("Instruction Text")),
            "instruction_vo": _clean(r.get("Instruction VO")),
            "instruction_vo_file": _clean(r.get("Instruction VO — File")),
            "text_in_question": _clean(r.get("Text in Question")),
            "audio_in_question": _clean(r.get("Audio in Question")),
            "audio_in_question_file": _clean(r.get("Audio in Question — File")),
            "vo_for_question": _clean(r.get("VO for Question")),
            "vo_for_question_file": _clean(r.get("VO for Question — File")),
            "image_in_question_detail": _clean(r.get("Image in Question — Detail")),
            "image_in_question_name": _clean(r.get("Image in Question — Name")),
            "correct_answer": _clean(r.get("Correct Answer")),
            "correct_answer_vo_file": _clean(r.get("Correct Answer VO — File")),
            "correct_answer_image": _clean(r.get("Correct Answer — Image")),
            "correct_answer_image_detail": _clean(r.get("Correct Answer — Image Detail")),
            "other_options": _split(r.get("Other Options")),
            "other_options_vo_file": _split(r.get("Other Options VO — File")),
            "other_options_image": _split(r.get("Other Options — Image")),
            "other_options_image_detail": _split(r.get("Other Options — Image Detail")),
            "stt_expectation": _clean(r.get("STT Expectation")),
            "concept": _clean(r.get("Concept (bucket / skill)")),
            "pattern": _clean(r.get("Pattern")),
            "notes": _clean(r.get("Notes")),
        }
        for i, r in enumerate(matrix)
    ]
    # Replace-on-save so re-runs/partial re-saves don't leave stale rows behind.
    client.table("questions").delete().eq("run_id", run_id).execute()
    client.table("questions").insert(rows).execute()
