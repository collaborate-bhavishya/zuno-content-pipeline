"""
The graph nodes. Each is `state -> partial_state`. Generators read the previous
error log and inject it into their prompt (the self-healing mechanism). Evaluators
write a decision + critique back into state for the routers to act on.

LLM clients are fetched fresh from the factory each call so admin edits take effect
on the next run. Each LLM call is instrumented with the MetricsCollector for
token/cost/latency tracking.
"""
import io
import json
import time
import base64
import logging
from PIL import Image

log = logging.getLogger("pipeline")

from app.core.config import CONFIG, TEMPLATE_COLUMN_RULES
from app.core.llm import (get_generator, get_judge, get_vision_judge,
                          get_image_client, render_image_bytes, image_cooldown_remaining)
from app.core.storage import STORAGE
from app.core.validators import scan_for_unsafe_content, validate_blueprint, validate_matrix
from app.core.metrics import get_collector
from app.core.scorer import score_run as _score_run
from app.core.db import lookup_existing, upsert_pending, mark_generated, mark_wrong_generation

LIVING_KEYWORDS = ["cat", "dog", "lion", "monkey", "bear", "bird", "fish",
                   "tiger", "boy", "girl", "cow", "duck", "frog"]

# Known INANIMATE objects → rendered with NO face. Everything else (animals,
# people, characters, or anything ambiguous) defaults to friendly eyes — because
# in these themes an unknown subject is almost always a living creature, and
# wrongly forbidding a face causes false rejections (e.g. an elephant with eyes).
INANIMATE_WORDS = {
    "ball", "block", "blocks", "cube", "cup", "mug", "plate", "bowl", "spoon",
    "fork", "knife", "box", "bag", "basket", "bottle", "jar", "can",
    "car", "truck", "bus", "train", "plane", "boat", "ship", "bike", "cycle",
    "apple", "banana", "orange", "grape", "grapes", "fruit", "mango", "pear",
    "carrot", "tomato", "potato", "corn", "vegetable", "cake", "bread", "egg",
    "book", "pen", "pencil", "crayon", "paper", "bag",
    "cap", "hat", "shoe", "shoes", "sock", "socks", "shirt", "dress", "coat",
    "star", "moon", "sun", "cloud", "circle", "square", "triangle", "heart",
    "tree", "leaf", "leaves", "flower", "plant", "grass", "rock", "stone",
    "house", "home", "door", "window", "wall", "roof",
    "key", "drum", "bell", "kite", "balloon", "clock", "lamp", "light",
    "chair", "table", "bed", "sofa", "brush", "comb", "umbrella", "ring",
    "coin", "phone", "tv", "guitar", "flag", "wheel", "button",
}


def _extract_tokens(resp) -> tuple:
    """Extract (input_tokens, output_tokens) from a LangChain response."""
    um = getattr(resp, 'usage_metadata', None)
    if um and isinstance(um, dict):
        return um.get('input_tokens', 0), um.get('output_tokens', 0)
    # Fallback: check response_metadata
    rm = getattr(resp, 'response_metadata', None) or {}
    um2 = rm.get('usage_metadata', {})
    if um2:
        return um2.get('prompt_token_count', 0), um2.get('candidates_token_count', 0)
    return 0, 0


def _get_model_name(resp) -> str:
    """Extract actual model name from a LangChain response."""
    rm = getattr(resp, 'response_metadata', None) or {}
    return rm.get('model_name', '') or ''


def _tracked_invoke(llm, messages, node: str, role: str):
    """Invoke an LLM and record metrics. Returns the response."""
    t0 = time.time()
    resp = llm.invoke(messages)
    elapsed_ms = int((time.time() - t0) * 1000)

    mc = get_collector()
    if mc:
        inp, out = _extract_tokens(resp)
        model = _get_model_name(resp) or getattr(llm, 'model_name', '') or getattr(llm, 'model', '') or '?'
        mc.record_llm_call(
            node=node, role=role, model=str(model),
            input_tokens=inp, output_tokens=out, latency_ms=elapsed_ms,
        )
    return resp


# ===================== PHASE 1: BLUEPRINT =====================

def planner_node(state: dict) -> dict:
    retry = state.get("blueprint_retry_count", 0)
    err = state.get("blueprint_error_log", "")
    age = state.get("target_age", 5)
    guidelines = CONFIG.output.age_guidelines.get(age, CONFIG.output.age_guidelines.get(5, {}))
    # Incremental repair: hand the model its OWN previous blueprint and fix ONLY the
    # flagged issue, keeping everything else intact.
    prev_bp = state.get("blueprint_text", "")
    if not err:
        correction = ""
    elif err.startswith("Safety:"):
        # SAFETY: we deliberately do NOT echo the flagged words (otherwise the model
        # parrots them and the filter trips harder). Still incremental — keep the
        # structure, only swap the unsafe language.
        correction = (
            f"\n\n=== REPAIR PASS — fix ONLY what is flagged ===\n"
            f"Here is your PREVIOUS blueprint:\n\n{prev_bp}\n\n"
            f"A few words in it tripped the child-safety filter. Return the SAME "
            f"blueprint with ONLY those scary/violent/dark words swapped for gentle, "
            f"positive, preschool-friendly alternatives. Keep all structure, sections, "
            f"and other wording EXACTLY as-is. Do NOT restate or list any blocked words, "
            f"and do NOT add any safety/content-warning commentary."
        )
    else:
        correction = (
            f"\n\n=== REPAIR PASS — fix ONLY what is flagged ===\n"
            f"Here is your PREVIOUS blueprint:\n\n{prev_bp}\n\n"
            f"The reviewer flagged ONLY this issue:\n{err}\n\n"
            f"Return the SAME blueprint with ONLY that issue fixed. Keep all other "
            f"sections, wording, and structure EXACTLY as-is — change nothing that was "
            f"not flagged."
        )

    age_context = ""
    if guidelines:
        forbidden = guidelines.get('forbidden_templates', [])
        forbidden_str = ', '.join(forbidden) if forbidden else 'none'
        age_context = (
            f"\n\nAGE {age} GUIDELINES:\n"
            f"- Max words per sentence: {guidelines.get('max_words_per_sentence', 'N/A')}\n"
            f"- Vocabulary level: {guidelines.get('vocabulary_level', 'N/A')}\n"
            f"- Text complexity: {guidelines.get('text_complexity', 'N/A')}\n"
            f"- Tone: {guidelines.get('tone', 'N/A')}\n"
            f"- Allowed templates: {', '.join(guidelines.get('allowed_templates', []))}\n"
            f"- FORBIDDEN templates (NEVER use): {forbidden_str}\n"
            f"- Vocab gate (order): {guidelines.get('vocab_gate', 'N/A')}\n"
            f"- Concept gate (order): {guidelines.get('concept_gate', 'N/A')}\n"
            f"- Sentence gate (order): {guidelines.get('sentence_gate', 'N/A')}\n"
            f"- Forbidden structures: {guidelines.get('forbidden_structures', 'none')}\n"
            f"- Notes: {guidelines.get('notes', '')}\n"
        )
    user = (f"Build a lesson blueprint for Theme: {state['theme']}, "
            f"Age: {age}. Obey all rules. "
            f"Output ONLY the lesson blueprint (theme intro, vocabulary, playable steps). "
            f"Do NOT include any safety checklist, content-warning, 'words to avoid' list, "
            f"or any HALT / gate / approval / automation notice — those are not part of the "
            f"blueprint. Never write scary/violent words even as negative examples; keep all "
            f"language gentle and positive."
            f"{age_context}{correction}")
    llm = get_generator()
    resp = _tracked_invoke(llm, [("system", CONFIG.prompts.generator_system), ("user", user)],
                           node="planner", role="generator")
    log.info("Planner produced %d chars (attempt %d)", len(resp.content), retry + 1)
    return {"blueprint_text": resp.content, "blueprint_retry_count": retry + 1}


def blueprint_evaluator_node(state: dict) -> dict:
    bp = state.get("blueprint_text", "")
    history = list(state.get("evaluator_history", []))
    decision, err = "proceed_to_questions", ""

    # Structural checks only (length, age-gated template rules). Unsafe-word and
    # forbidden-vocab enforcement happens on the child-facing matrix, not on this
    # internal reasoning artifact — the LLM judge below covers blueprint safety
    # with full context.
    ok, msg = validate_blueprint(bp, state["target_age"])
    if not ok:
        decision, err = "fail", msg
    if decision != "fail":
        judge = get_judge()
        r = _tracked_invoke(judge,
                            [("system", CONFIG.prompts.blueprint_judge_system),
                             ("user", f"Review this draft:\n\n{bp}")],
                            node="blueprint_evaluator", role="judge")
        clean = r.content.replace("```json", "").replace("```", "").strip()
        try:
            data = json.loads(clean)
            if data.get("verdict") == "FAIL":
                decision, err = "fail", data.get("critique", "Quality fail.")
        except Exception as e:
            decision, err = "fail", f"Judge JSON parse error: {e}"

    if err:
        history.append(f"Blueprint cycle {state.get('blueprint_retry_count')}: {err}")
    return {"blueprint_error_log": err, "gate_decision": decision,
            "evaluator_history": history}


def route_blueprint(state: dict) -> str:
    if state.get("gate_decision") == "proceed_to_questions":
        return "proceed_to_questions"
    if state.get("blueprint_retry_count", 0) >= CONFIG.max_retries:
        return "hard_fail"
    return "regenerate"


# ===================== PHASE 2: QUESTION MATRIX =====================

def _format_template_rules() -> str:
    """Format TEMPLATE_COLUMN_RULES into a compact string for the fabricator prompt."""
    lines = []
    for tpl, rules in TEMPLATE_COLUMN_RULES.items():
        yes_cols = [c for c, v in rules.items() if v == "Yes"]
        no_cols = [c for c, v in rules.items() if v == "No"]
        lines.append(f"  {tpl}: YES → {', '.join(yes_cols)}  |  NO (use —) → {', '.join(no_cols)}")
    return "\n".join(lines)


def fabricator_node(state: dict) -> dict:
    retry = state.get("matrix_retry_count", 0)
    err = state.get("matrix_error_log", "")
    prev_matrix = state.get("raw_question_matrix")
    # Incremental repair: on a retry, hand the model its OWN previous matrix and
    # tell it to change ONLY the flagged cells — not regenerate from scratch (which
    # caused errors to shuffle around / "whack-a-mole").
    if err and prev_matrix:
        correction = (
            f"\n\n=== REPAIR PASS — fix ONLY what is flagged ===\n"
            f"Here is the EXACT matrix you produced last time (JSON):\n"
            f"{json.dumps(prev_matrix, ensure_ascii=False)}\n\n"
            f"The validator flagged ONLY these problems:\n{err}\n\n"
            f"Return the SAME matrix with ONLY those specific cells corrected. "
            f"Keep every other row, column, and value EXACTLY as-is — do not change, "
            f"re-order, rename, or regenerate anything that was not flagged. "
            f"Output the complete corrected JSON array."
        )
    elif err:
        correction = f"\n\nCORRECTION: previous output failed. Fix: {err}"
    else:
        correction = ""
    columns = CONFIG.output.matrix_columns
    age = state.get("target_age", 5)
    milestone_code = state.get("milestone_code", "AG05")
    theme_code = state.get("theme_code", "T01")
    guidelines = CONFIG.output.age_guidelines.get(age, CONFIG.output.age_guidelines.get(5, {}))

    age_block = ""
    if guidelines:
        forbidden = guidelines.get('forbidden_templates', [])
        forbidden_str = ', '.join(forbidden) if forbidden else 'none'
        age_block = (
            f"\n\nAGE {age} GUIDELINES (MUST follow):\n"
            f"- Max words per sentence: {guidelines.get('max_words_per_sentence', 'N/A')}\n"
            f"- Vocabulary level: {guidelines.get('vocabulary_level', 'N/A')}\n"
            f"- Text complexity: {guidelines.get('text_complexity', 'N/A')}\n"
            f"- Tone: {guidelines.get('tone', 'N/A')}\n"
            f"- STT expectation format: {guidelines.get('stt_expectation', 'N/A')}\n"
            f"- Allowed templates: {', '.join(guidelines.get('allowed_templates', []))}\n"
            f"- FORBIDDEN templates (NEVER use): {forbidden_str}\n"
            f"- Vocab gate (template order): {guidelines.get('vocab_gate', 'N/A')}\n"
            f"- Concept gate (template order): {guidelines.get('concept_gate', 'N/A')}\n"
            f"- Sentence gate (template order): {guidelines.get('sentence_gate', 'N/A')}\n"
            f"- Forbidden structures: {guidelines.get('forbidden_structures', 'none')}\n"
            f"- Notes: {guidelines.get('notes', '')}\n"
        )

    user = (f"Convert this blueprint into a structured JSON array with as many rows as "
            f"the lesson requires (follow the blueprint's playable steps). "
            f"Maximum {CONFIG.effective_max_questions} rows. Each row MUST have ALL of these 26 keys:\n"
            f"  {', '.join(columns)}\n\n"
            f"COLUMN GUIDE (26-column schema):\n"
            f"Group 1 — Identity & Instruction:\n"
            f"  - 'Playable Code': Unique playable identifier. Format: {{milestone}}{{theme_code}}P{{nn}}. "
            f"    Milestone code = '{milestone_code}', Theme code = '{theme_code}'. "
            f"    Example: {milestone_code}{theme_code}P01, {milestone_code}{theme_code}P02. "
            f"    Multiple rows share the same playable code (a playable = 5-7 questions).\n"
            f"  - 'Playable Name': Human-readable name like 'Meet the Lion & Monkey'\n"
            f"  - 'Layer': e.g. '1 - Vocabulary', '2 - Concept Builder', etc.\n"
            f"  - 'Template': T4, T1, F1, D1, etc.\n"
            f"  - 'Instruction Text': The on-screen directive telling the child what to do. "
            f"    E.g. 'Find the girl!', 'Read with me', 'Put the words in order'\n"
            f"  - 'Instruction VO': Voice-over narration the child hears when question loads. "
            f"    E.g. 'Can you find the girl?'\n"
            f"  - 'Instruction VO — File': .mp3 filename. Format: {{playable_code}}Q{{nn}}_inst.mp3. "
            f"    E.g. '{milestone_code}{theme_code}P01Q01_inst.mp3'\n"
            f"\n"
            f"Group 2 — Question (use '—' if not needed for this template):\n"
            f"  - 'Text in Question': The actual text content the child reads/speaks/interacts with. "
            f"    E.g. 'I am a girl' for reading, '—' for image-tap templates.\n"
            f"  - 'Audio in Question': Audio played as part of the question (word pronunciation, etc.)\n"
            f"  - 'Audio in Question — File': .mp3 filename for the audio in question. "
            f"    Format: {{playable_code}}Q{{nn}}_aud.mp3. '—' if no audio.\n"
            f"  - 'VO for Question': Voice-over to read/explain the question content aloud.\n"
            f"  - 'VO for Question — File': .mp3 filename. Format: {{playable_code}}Q{{nn}}_qvo.mp3\n"
            f"  - 'Image in Question — Detail': Brief description of WHAT the image should show (subject, "
            f"    pose, emotion). Do NOT include art style — art guidelines are applied separately. "
            f"    MUST match the filename's specificity: a generic name like 'ball.png' gets a neutral "
            f"    description ('a simple ball'), while 'red_ball.png' gets 'a bright red ball'. The SAME "
            f"    filename must ALWAYS use the SAME description (so reused images stay consistent). "
            f"    E.g. 'a simple ball' or 'a happy brown dog sitting'\n"
            f"  - 'Image in Question — Name': Reusable .png filename. "
            f"    DEFAULT to the bare object: '{{object}}.png' (e.g. 'ball.png', 'dog.png', 'lion.png'). "
            f"    ONLY add an attribute (color/size/action) when that attribute is what the question "
            f"    actually tests — i.e. the child must SEE it to answer. E.g. use 'red_ball.png' only "
            f"    for a question about the color red; otherwise 'ball.png'. Use 'dog_running.png' only "
            f"    if the action is the answer; otherwise 'dog.png'. This MAXIMIZES reuse: the same "
            f"    'ball.png' should be reused across every question where color/size is irrelevant.\n"
            f"\n"
            f"Group 3 — Answer:\n"
            f"  - 'Correct Answer': Text of correct option\n"
            f"  - 'Correct Answer VO — File': .mp3 filename. Format: {{playable_code}}Q{{nn}}_ans.mp3\n"
            f"  - 'Correct Answer — Image': .png filename for correct answer image\n"
            f"  - 'Correct Answer — Image Detail': Subject description for correct answer image (no art style)\n"
            f"  - 'Other Options': Distractor text(s), comma-separated\n"
            f"  - 'Other Options VO — File': Distractor .mp3 filenames, comma-separated. "
            f"    Format: {{playable_code}}Q{{nn}}_opt1.mp3, ...opt2.mp3\n"
            f"  - 'Other Options — Image': Distractor .png filenames, comma-separated\n"
            f"  - 'Other Options — Image Detail': Subject descriptions for distractor images, comma-separated (no art style)\n"
            f"\n"
            f"Group 4 — Speech:\n"
            f"  - 'STT Expectation': Clean lowercase text child is expected to say. '—' for tap templates.\n"
            f"\n"
            f"Group 5 — Meta:\n"
            f"  - 'Concept (bucket / skill)': e.g. 'animals', 'size & quantity'\n"
            f"  - 'Pattern': p1, p2, etc. or '—'\n"
            f"  - 'Notes': One-line pedagogical purpose\n"
            f"\n"
            f"NAMING CONVENTIONS:\n"
            f"- Image filenames: lowercase, underscores. DEFAULT to the bare object '{{object}}.png' "
            f"  (e.g. ball.png, dog.png) to MAXIMIZE reuse. Add an attribute ONLY when it is core to "
            f"  answering the question (the child must see it to choose correctly): e.g. red_ball.png "
            f"  for a color question, big_dog.png for a size question, dog_running.png for an action "
            f"  question. If color/size/action is irrelevant to the answer, omit it. Reuse the exact "
            f"  same filename across every row that needs the same image.\n"
            f"- VO/Audio filenames: {{playable_code}}Q{{nn}}_{{type}}.mp3 — types: inst, aud, qvo, ans, opt1/opt2/opt3\n"
            f"- Use '—' (em-dash) for any column that doesn't apply to this template\n"
            f"- File-name columns: whenever a content column is filled, its paired file column MUST also be filled. "
            f"  When content is '—', file must also be '—'.\n"
            f"\n"
            f"PER-TEMPLATE COLUMN RULES (Yes = must have content, No = must be '—'):\n"
            f"{_format_template_rules()}\n"
            f"{age_block}\n"
            f"Output ONLY a raw JSON array, no markdown.\n\n"
            f"Blueprint:\n{state.get('blueprint_text','')}{correction}")
    llm = get_generator()
    resp = _tracked_invoke(llm, [("system", CONFIG.prompts.generator_system), ("user", user)],
                           node="fabricator", role="generator")
    clean = resp.content.replace("```json", "").replace("```", "").strip()
    try:
        rows = json.loads(clean)[: CONFIG.effective_max_questions]
    except Exception as e:
        rows = []
        err = f"JSON parse failed: {e}"
    out = {"raw_question_matrix": rows, "matrix_retry_count": retry + 1}
    if not rows:
        out["matrix_error_log"] = err or "Empty matrix."
        log.warning("Fabricator produced no rows: %s", err)
    else:
        img_cols = [r.get("Image in Question — Name", "") for r in rows]
        log.info("Fabricator produced %d rows. Image columns: %s", len(rows), img_cols)
    return out


def matrix_evaluator_node(state: dict) -> dict:
    rows = state.get("raw_question_matrix") or []
    history = list(state.get("evaluator_history", []))
    if not rows:
        history.append(f"Matrix cycle {state.get('matrix_retry_count')}: empty")
        return {"matrix_gate_decision": "fail",
                "matrix_error_log": state.get("matrix_error_log", "Empty matrix."),
                "evaluator_history": history}
    age = state.get("target_age", 5)
    ok, msg = validate_matrix(rows, age=age)
    if ok:
        log.info("Matrix validation PASSED (%d rows, age %d)", len(rows), age)
        return {"matrix_gate_decision": "trigger_assets", "matrix_error_log": "",
                "evaluator_history": history}
    log.warning("Matrix validation FAILED (age %d): %s", age, msg)
    history.append(f"Matrix cycle {state.get('matrix_retry_count')}: {msg}")
    return {"matrix_gate_decision": "fail", "matrix_error_log": msg,
            "evaluator_history": history}


def route_matrix(state: dict) -> str:
    if state.get("matrix_gate_decision") == "trigger_assets":
        return "trigger_assets"
    if state.get("matrix_retry_count", 0) >= CONFIG.max_retries:
        # Retries exhausted. Rather than dead-stop the whole run, proceed with the
        # best matrix we have so the user still gets questions + images + an eval
        # that flags the remaining rule violations. Only a truly empty matrix
        # hard-fails (nothing usable downstream).
        if state.get("raw_question_matrix"):
            log.warning("Matrix still imperfect after %d retries — proceeding to "
                        "eval/images anyway; eval will flag remaining issues.",
                        CONFIG.max_retries)
            return "trigger_assets"
        return "hard_fail"
    return "regenerate"


# ===================== PHASE 3: IMAGES =====================

def asset_planner_node(state: dict) -> dict:
    matrix = state.get("raw_question_matrix") or []
    existing_local = STORAGE.list_images()
    milestone = state.get("milestone_code", "")
    theme = state.get("theme_code", "")

    # Collect all candidate images first. EVERY image column may hold multiple
    # comma-separated filenames (e.g. distractors 'a.png,b.png', or T7/F2 multi-
    # select). Split each so every image becomes its own asset — and therefore its
    # own row in Supabase — rather than one row holding a comma-joined string.
    candidates, seen = [], set()
    for row in matrix:
        ctx = str(row.get("Concept (bucket / skill)", "")).strip()
        pc = str(row.get("Playable Code", "")).strip()
        for name_col, detail_col, tag in [
            ("Image in Question — Name", "Image in Question — Detail", "Question object"),
            ("Correct Answer — Image", "Correct Answer — Image Detail", "Correct option"),
            ("Other Options — Image", "Other Options — Image Detail", "Distractor"),
        ]:
            names_raw = str(row.get(name_col, "")).strip()
            if not names_raw or names_raw == "—":
                continue
            details_raw = str(row.get(detail_col, "")).strip()
            detail_list = ([d.strip() for d in details_raw.split(",")]
                           if details_raw and details_raw != "—" else [])
            for j, tok in enumerate(t.strip() for t in names_raw.split(",")):
                if not tok.endswith(".png") or tok in seen:
                    continue
                seen.add(tok)
                d = detail_list[j] if j < len(detail_list) else ""
                candidates.append({
                    "filename": tok,
                    "object_name": tok[:-4].replace("_", " "),
                    "detail": d if d and d != "—" else "",
                    "tag": tag, "context": ctx,
                    "milestone_code": milestone, "theme_code": theme,
                    "playable_code": pc,
                })

    # ── Check Supabase DB for already-generated images ──
    all_names = [c["filename"] for c in candidates]
    try:
        db_existing = lookup_existing(all_names)
    except Exception as e:
        log.warning("DB lookup failed, falling back to local-only: %s", e)
        db_existing = {}

    # Filter out images that exist locally OR in DB with status=1
    queue = [
        c for c in candidates
        if c["filename"] not in existing_local and c["filename"] not in db_existing
    ]
    queue = queue[: CONFIG.effective_max_images]

    # Register EVERY distinct image (one row per split filename) in Supabase —
    # idempotent: won't overwrite rows already marked generated.
    try:
        upsert_pending(candidates)
    except Exception as e:
        log.warning("DB upsert_pending failed (non-fatal): %s", e)

    # Print which images are NEEDED (to generate) vs which ALREADY EXIST.
    need = [c["filename"] for c in queue]
    have = sorted({n for n in all_names if n in existing_local or n in db_existing})
    log.info("Asset planner: %d total images — %d to generate, %d already exist",
             len(candidates), len(need), len(have))
    log.info("  NEEDED  (generate now): %s", ", ".join(need) if need else "(none)")
    log.info("  EXISTING (reused/skip):  %s", ", ".join(have) if have else "(none)")
    return {"asset_queue": queue, "current_asset_index": 0,
            "image_retry_count": 0, "completed_assets": [], "failed_assets": [],
            "wrong_generations": []}


def eval_node(state: dict) -> dict:
    """Run the two-lane eval scorer on the final question matrix.
    Placed after asset_planner so the matrix is finalized, and before
    image generation so we don't waste image quota on bad content."""
    matrix = state.get("raw_question_matrix") or []
    theme = state.get("theme", "")
    age = state.get("target_age", 5)
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
        "theme_concepts": [],
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
        eval_result = result.to_dict()
    except Exception as e:
        log.warning("Eval node failed: %s", e)
        eval_result = {"total_score": 0, "grade": "?", "error": str(e),
                       "dimensions": [], "llm_calls": 0}

    log.info("Eval: grade=%s score=%s", eval_result.get("grade"), eval_result.get("total_score"))
    return {"eval_result": eval_result}


def _eye_rule(object_name: str) -> str:
    # Whole-word match against the inanimate list (so 'starfish' isn't caught by
    # 'star', 'cowboy' isn't a 'cow', etc.). Only explicit objects get no face;
    # animals/people/characters and anything ambiguous default to friendly eyes.
    words = set(object_name.lower().replace("_", " ").split())
    if words & INANIMATE_WORDS:
        return "no eyes and no face"
    return "two simple black circle eyes with a white glimmer"


def _is_quota_error(exc: Exception) -> bool:
    """Detect Imagen 429 / RESOURCE_EXHAUSTED quota errors."""
    msg = str(exc).lower()
    return "429" in msg or "resource_exhausted" in msg or "quota" in msg


def build_image_prompt(asset: dict, eye_rule: str, prev_feedback: str = "") -> str:
    """Construct the image-generation prompt for one asset.

    Resolves the common conflict where the matrix's image DESCRIPTION mentions a
    setting (e.g. "a cow standing in a sunny farm field") while the app requires a
    single isolated object on white. The description is used for the subject's
    APPEARANCE only; setting words are treated as context, not things to draw. If
    description and composition still seem to conflict, the model is told to use
    its own judgment and depict whatever best answers the learning goal.
    """
    core = asset.get("object_name", "")
    detail = (asset.get("detail", "") or "").strip()
    context = (asset.get("context", "") or "").strip()
    appearance = detail if detail and detail != "—" else core

    art_style = (
        "Flat 2D cartoon vector illustration for a preschool learning app. "
        "Soft rounded shapes, 100% flat vector, NO outlines, bright pastel tones. "
        f"Face rule: {eye_rule}. No shadows, no gradients, no 3D effects."
    )
    composition = (
        "COMPOSITION: show ONLY the single core subject as one centered, isolated "
        "object on a solid 100% white background. Any setting words in the "
        "description (e.g. 'farm', 'field', 'sky', 'grass', 'on the farm') are "
        "CONTEXT ONLY — do not draw scenery, ground, or background elements."
    )
    judgment = (
        "If the description and this single-isolated-subject rule seem to conflict, "
        "use your own judgment and depict whatever best answers the learning goal"
        + (f" ('{context}')" if context else "")
        + " as one clear, identifiable subject on white."
    )
    prompt = (
        f"{art_style} Core subject: {core}. "
        f"Use this description for the subject's appearance only "
        f"(color, pose, expression): {appearance}. "
        f"{composition} {judgment}"
    )
    if prev_feedback:
        prompt += (f" REPAIR — the previous attempt was rejected by the vision critic "
                   f"for ONLY this reason: \"{prev_feedback}\". Regenerate the SAME "
                   f"subject in the SAME pose, colors, and composition, changing ONLY "
                   f"what is needed to fix that one issue — keep everything else identical.")
    return prompt


def image_factory_node(state: dict) -> dict:
    queue = state.get("asset_queue", [])
    idx = state.get("current_asset_index", 0)
    retry = state.get("image_retry_count", 0)
    loop_iter = state.get("image_loop_iterations", 0) + 1

    # ── Hard cutoff: prevent infinite image loops ──
    if loop_iter > CONFIG.max_image_loop_iterations:
        pending = queue[idx:]
        log.error("Image factory: HARD CUTOFF at %d iterations, queuing %d remaining", loop_iter, len(pending))
        return {"image_gate_decision": "all_done",
                "image_loop_iterations": loop_iter,
                "pending_assets": state.get("pending_assets", []) + pending}

    # If quota was already hit, skip straight to done with pending queue
    if state.get("quota_exhausted"):
        pending = queue[idx:]
        log.warning("Image factory: quota exhausted, queuing %d remaining assets", len(pending))
        return {"image_gate_decision": "all_done",
                "image_loop_iterations": loop_iter,
                "pending_assets": state.get("pending_assets", []) + pending}

    if idx >= len(queue):
        return {"image_gate_decision": "all_done", "image_loop_iterations": loop_iter}
    asset = queue[idx]
    eye = _eye_rule(asset["object_name"])
    prev_feedback = state.get("image_error_log", "") if retry > 0 else ""
    prompt = build_image_prompt(asset, eye, prev_feedback)
    log.info("Image factory: rendering '%s' (idx=%d, attempt=%d)", asset["object_name"], idx, retry + 1)
    # Small pause to space out calls so we don't burst past the per-minute image
    # rate limit (the main reason Vertex 429s where a slow Colab loop would not).
    if CONFIG.image_throttle_s:
        time.sleep(CONFIG.image_throttle_s)
    try:
        t0 = time.time()
        raw = render_image_bytes(prompt)
        elapsed_ms = int((time.time() - t0) * 1000)

        # Record image generation call
        mc = get_collector()
        if mc:
            mc.record_image_call()
            mc.record_llm_call(
                node="image_factory", role="image_gen",
                model=CONFIG.models.image_model,
                input_tokens=0, output_tokens=0, latency_ms=elapsed_ms,
            )

        if not raw:
            return {"current_image": None, "image_error_log": "no image returned",
                    "image_retry_count": retry + 1, "current_eye_rule": eye,
                    "image_loop_iterations": loop_iter}
        pil = Image.open(io.BytesIO(raw))
        return {"current_image": pil, "image_retry_count": retry + 1, "current_eye_rule": eye,
                "image_loop_iterations": loop_iter,
                "image_quota_wait": image_cooldown_remaining() > 0}
    except Exception as e:
        if _is_quota_error(e):
            pending = queue[idx:]
            log.warning("Image factory: QUOTA EXHAUSTED at idx=%d, queuing %d assets for retry", idx, len(pending))
            return {"current_image": None, "quota_exhausted": True,
                    "pending_assets": state.get("pending_assets", []) + pending,
                    "image_error_log": f"Image quota exhausted (429). {len(pending)} images queued for retry.",
                    "image_gate_decision": "all_done",
                    "image_loop_iterations": loop_iter}
        return {"current_image": None, "image_error_log": f"render error: {e}",
                "image_retry_count": retry + 1, "current_eye_rule": eye,
                "image_loop_iterations": loop_iter}


def vision_critic_node(state: dict) -> dict:
    """Multimodal audit — the actual PNG bytes are sent to the judge."""
    queue = state.get("asset_queue", [])
    idx = state.get("current_asset_index", 0)
    retry = state.get("image_retry_count", 0)
    if idx >= len(queue):
        return {"image_gate_decision": "all_done"}
    asset = queue[idx]
    pil = state.get("current_image")

    if pil is None:  # render failed
        if retry >= CONFIG.max_retries:
            return {"current_asset_index": idx + 1, "image_retry_count": 0,
                    "failed_assets": state.get("failed_assets", []) + [asset["filename"]],
                    "image_gate_decision": "advance"}
        return {"image_gate_decision": "retry"}

    buf = io.BytesIO(); pil.save(buf, format="PNG")
    data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    sys_prompt = CONFIG.prompts.vision_critic_system.format(
        object_name=asset["object_name"], eye_rule=state.get("current_eye_rule", ""))
    user_msg = {"role": "user", "content": [
        {"type": "text", "text": f"Audit this {asset['object_name']} asset."},
        {"type": "image_url", "image_url": {"url": data_uri}}]}
    try:
        judge = get_vision_judge()
        r = _tracked_invoke(judge, [("system", sys_prompt), user_msg],
                            node="vision_critic", role="vision_judge")
        clean = r.content.replace("```json", "").replace("```", "").strip()
        try:
            verdict = json.loads(clean)
        except Exception:
            verdict = {"pass": "true" in clean.lower(), "reason": clean[:200]}
    except Exception as e:
        # The audit model failed (e.g. quota/429). The image itself rendered fine,
        # so ACCEPT it rather than crash the whole run — quality control degrades
        # gracefully instead of losing the asset.
        log.warning("Vision critic unavailable (%s) — accepting image '%s' unaudited",
                    type(e).__name__, asset["filename"])
        verdict = {"pass": True, "reason": "auto-accepted (vision critic unavailable)"}

    if verdict.get("pass"):
        url = STORAGE.save_image(pil, asset["filename"])
        # Mark as generated in Supabase DB
        try:
            mark_generated(asset["filename"], image_url=url)
        except Exception as e:
            log.warning("DB mark_generated failed (non-fatal): %s", e)
        return {"current_asset_index": idx + 1, "image_retry_count": 0,
                "completed_assets": state.get("completed_assets", [])
                + [{"filename": asset["filename"], "url": url,
                    "object_name": asset["object_name"]}],
                "image_gate_decision": "advance"}
    if retry >= CONFIG.max_retries:
        # Generation failed evaluation after all retries. Keep the last (rejected)
        # image for review: store it under a 'wrong_' name (so it doesn't shadow the
        # real asset) and tag it in Supabase as wrong_generation (status = 2).
        wrong_name = f"wrong_{asset['filename']}"
        wrong_url = ""
        try:
            wrong_url = STORAGE.save_image(pil, wrong_name)
        except Exception as e:
            log.warning("Failed to store rejected image %s: %s", wrong_name, e)
        try:
            mark_wrong_generation(asset["filename"], image_url=wrong_url)
        except Exception as e:
            log.warning("DB mark_wrong_generation failed (non-fatal): %s", e)
        log.info("Image '%s' rejected by critic after %d tries — stored as '%s', status=2 (wrong_generation)",
                 asset["filename"], retry + 1, wrong_name)
        return {"current_asset_index": idx + 1, "image_retry_count": 0,
                "failed_assets": state.get("failed_assets", []) + [asset["filename"]],
                "wrong_generations": state.get("wrong_generations", [])
                + [{"filename": asset["filename"], "wrong_image": wrong_name,
                    "url": wrong_url, "reason": verdict.get("reason", ""),
                    "tag": "wrong_generation"}],
                "image_gate_decision": "advance"}
    return {"image_error_log": verdict.get("reason", ""), "image_gate_decision": "retry"}


def route_after_factory(state: dict) -> str:
    """Decide whether to run the vision critic or exit straight to END.

    The image factory short-circuits (quota exhausted, hard cutoff, or empty
    queue) by setting image_gate_decision='all_done'. The edge to the vision
    critic is therefore CONDITIONAL — otherwise the critic would run on a null
    image, overwrite the decision, and the graph would loop until the recursion
    limit is hit.
    """
    if state.get("image_gate_decision") == "all_done":
        return "all_done"
    return "critic"


def route_image(state: dict) -> str:
    decision = state.get("image_gate_decision")
    if decision == "all_done":
        return "all_done"
    if decision == "advance":
        if state.get("current_asset_index", 0) >= len(state.get("asset_queue", [])):
            return "all_done"
        return "next"
    return "retry"
