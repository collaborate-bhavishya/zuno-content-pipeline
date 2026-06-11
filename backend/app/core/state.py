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

    # Phase 3: image assets
    asset_queue: list
    current_asset_index: int
    current_image: object        # PIL image held in memory between factory + critic
    current_eye_rule: str
    image_error_log: str
    image_retry_count: int
    image_loop_iterations: int   # total image_factory calls — hard cutoff guard
    image_quota_wait: bool       # True when paced/cooling down on image 429s
    image_gate_decision: str
    completed_assets: list       # [{filename, url}]
    failed_assets: list
    wrong_generations: list      # critic-rejected images kept for review (status=2)
    pending_assets: list         # assets queued for retry (quota exhausted)
    quota_exhausted: bool        # True if image API returned 429

    # Eval (runs after asset_planner, before image generation)
    eval_result: Optional[dict]

    # shared
    evaluator_history: list
