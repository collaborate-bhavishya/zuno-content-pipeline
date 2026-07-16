"""Shared graph state. Every node receives this dict and returns a partial dict."""
from typing import Optional, TypedDict


class LessonState(TypedDict, total=False):
    theme: str
    target_age: int
    milestone_code: str          # e.g. "AG03" — provided by user
    theme_code: str              # e.g. "T01" — provided by user

    # Phase 1: blueprint
    blueprint_text: str
    blueprint_retry_count: int
    blueprint_error_log: str
    gate_decision: str

    # Phase 2: question matrix
    raw_question_matrix: Optional[list]
    matrix_retry_count: int
    matrix_error_log: str
    matrix_gate_decision: str

    # Phase 3: image planning (no generation — the planner registers each
    # needed image as pending in Supabase for a separate process to render)
    asset_queue: list            # images the matrix needs that don't exist yet
    completed_assets: list       # kept for output-shape compat (always [] now)
    failed_assets: list          # kept for output-shape compat (always [] now)

    # Phase 3b: audio planning (dedupe voice lines against the audio_assets
    # ledger; file cells in the matrix are rewritten to reused codes)
    pending_audio: list          # new dialogues registered this run
    audio_reused: int            # dialogues that matched an existing ledger row

    # Eval (runs after asset_planner)
    eval_result: Optional[dict]

    # shared
    evaluator_history: list
