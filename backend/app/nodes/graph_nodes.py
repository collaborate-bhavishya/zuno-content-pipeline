"""
The graph nodes. Each is `state -> partial_state`. Generators read the previous
error log and inject it into their prompt (the self-healing mechanism). Evaluators
write a decision + critique back into state for the routers to act on.

LLM clients are fetched fresh from the factory each call so admin edits take effect
on the next run. Each LLM call is instrumented with the MetricsCollector for
token/cost/latency tracking.
"""
import json
import re
import time
import logging

log = logging.getLogger("pipeline")

from app.core.config import CONFIG, TEMPLATE_COLUMN_RULES
from app.core.llm import get_generator, get_judge
from app.core.storage import STORAGE
from app.core.validators import scan_for_unsafe_content, validate_blueprint, validate_matrix
from app.core.metrics import get_collector
from app.core.scorer import score_run as _score_run
from app.core.db import (lookup_existing, upsert_pending,
                         lookup_existing_audio, upsert_pending_audio)


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
    # Critiques from EARLIER cycles (already addressed) — reminded so the model
    # doesn't reintroduce a fixed problem while repairing the current one.
    # Safety-cycle entries are excluded: they may quote the flagged words, which
    # must never be echoed back into the prompt.
    prior = [h for h in state.get("evaluator_history", [])
             if h.startswith("Blueprint cycle") and "Safety:" not in h]
    prior_block = ""
    if len(prior) > 1:
        prior_block = (
            "\n\nIssues flagged and FIXED in earlier review cycles — do NOT "
            "reintroduce any of these:\n" + "\n".join(prior[:-1])
        )
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
            f"The reviewer flagged these issues:\n{err}\n\n"
            f"Return the SAME blueprint with ALL of those issues fixed (and nothing "
            f"else changed). Keep all other sections, wording, and structure EXACTLY "
            f"as-is — change nothing that was not flagged.{prior_block}"
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


def _critique_to_text(critique) -> str:
    """The judge is told to return critique as a string, but structured output
    sometimes comes back as a list/dict of issues (e.g. [{number, issue,
    technical_fix_instructions}]). Flatten anything non-string to numbered
    lines so downstream consumers (repair prompt, feed, UI) always get text."""
    if isinstance(critique, str):
        return critique
    if isinstance(critique, list):
        lines = []
        for i, item in enumerate(critique, 1):
            if isinstance(item, dict):
                n = item.get("number", i)
                issue = str(item.get("issue", "")).strip()
                fix = str(item.get("technical_fix_instructions",
                                   item.get("fix", ""))).strip()
                lines.append(f"{n}. {issue}" + (f" — FIX: {fix}" if fix else ""))
            else:
                lines.append(f"{i}. {item}")
        return "\n".join(lines)
    try:
        return json.dumps(critique, ensure_ascii=False)
    except Exception:
        return str(critique)


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
                decision = "fail"
                err = _critique_to_text(data.get("critique", "Quality fail."))
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


def _flagged_row_indices(err: str, n_rows: int) -> set:
    """0-based row indices named in a validator error log.

    Validator messages start with 'Q<n>:' or 'Row <n> (Q<n>):'. If nothing
    parses (e.g. a global error like a bad JSON shape), fall back to every row
    so the repair still has the full picture.
    """
    idx = {int(m) - 1 for m in re.findall(r"\bQ(\d+)\b", err)}
    idx = {i for i in idx if 0 <= i < n_rows}
    return idx or set(range(n_rows))


def fabricator_node(state: dict) -> dict:
    retry = state.get("matrix_retry_count", 0)
    err = state.get("matrix_error_log", "")
    prev_matrix = state.get("raw_question_matrix")
    # Incremental repair: on a retry, hand the model its OWN previous matrix and
    # tell it to change ONLY the flagged cells — not regenerate from scratch (which
    # caused errors to shuffle around / "whack-a-mole").
    if err and prev_matrix:
        # Only the FLAGGED rows go to the model, and only those come back —
        # regenerating all 80+ rows to fix a handful of cells burned enough
        # output tokens per retry to exhaust the API quota mid-run.
        flagged = _flagged_row_indices(err, len(prev_matrix))
        subset = {str(i + 1): prev_matrix[i] for i in sorted(flagged)}
        correction = (
            f"\n\n=== REPAIR PASS — fix ONLY what is flagged ===\n"
            f"Below are ONLY the rows the validator flagged, keyed by question "
            f"number, exactly as you produced them:\n"
            f"{json.dumps(subset, ensure_ascii=False)}\n\n"
            f"Every problem found:\n{err}\n\n"
            f"Fix EVERY listed problem. Return ONLY these same rows as a JSON "
            f"object keyed by the SAME question numbers — do not return the "
            f"other rows, do not renumber, and change nothing that was not "
            f"flagged. Output raw JSON only."
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
            f"Maximum {CONFIG.max_questions} rows. Each row MUST have ALL of these 26 keys:\n"
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
    is_repair = bool(err and prev_matrix)
    llm = get_generator()
    resp = _tracked_invoke(llm, [("system", CONFIG.prompts.generator_system), ("user", user)],
                           node="fabricator", role="generator")
    clean = resp.content.replace("```json", "").replace("```", "").strip()
    try:
        parsed = json.loads(clean)
        if is_repair:
            # Repair returns ONLY the flagged rows, keyed by question number —
            # splice them back over the previous matrix.
            rows = [dict(r) for r in prev_matrix]
            if isinstance(parsed, dict):
                patched = 0
                for key, row in parsed.items():
                    i = int(re.sub(r"\D", "", str(key)) or -1) - 1
                    if 0 <= i < len(rows) and isinstance(row, dict):
                        rows[i] = row
                        patched += 1
                log.info("Fabricator repair: patched %d/%d flagged rows (matrix stays %d rows)",
                         patched, len(parsed), len(rows))
            elif isinstance(parsed, list):
                # Model ignored the keyed-object instruction and returned the
                # whole array anyway — accept it rather than fail the run.
                rows = parsed[: CONFIG.max_questions]
                log.info("Fabricator repair returned a full array (%d rows)", len(rows))
        else:
            rows = parsed[: CONFIG.max_questions]
    except Exception as e:
        rows = []
        err = f"JSON parse failed: {e}"
    out = {"raw_question_matrix": rows, "matrix_retry_count": retry + 1}
    if not rows:
        out["matrix_error_log"] = err or "Empty matrix."
        log.warning("Fabricator produced no rows: %s", err)
    else:
        log.info("Fabricator matrix now %d rows", len(rows))
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


# ===================== PHASE 3: IMAGE PLANNING =====================
# Images are NOT generated here — the planner just extracts every distinct
# image the matrix needs and registers new ones as pending (status=0) in
# Supabase for a separate generation process to pick up.

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
    queue = queue[: CONFIG.max_images]

    # Register EVERY distinct image (one row per split filename) in Supabase —
    # idempotent: won't overwrite rows already marked generated.
    try:
        upsert_pending(candidates)
    except Exception as e:
        log.warning("DB upsert_pending failed (non-fatal): %s", e)

    # Print which images are NEEDED (registered as pending) vs already existing.
    need = [c["filename"] for c in queue]
    have = sorted({n for n in all_names if n in existing_local or n in db_existing})
    log.info("Asset planner: %d total images — %d newly pending, %d already exist",
             len(candidates), len(need), len(have))
    log.info("  PENDING  (registered):  %s", ", ".join(need) if need else "(none)")
    log.info("  EXISTING (reused/skip): %s", ", ".join(have) if have else "(none)")
    return {"asset_queue": queue, "completed_assets": [], "failed_assets": []}


# ===================== PHASE 3b: AUDIO PLANNING =====================
# Same idea as image planning, for voice lines. Every dialogue↔file column
# pair in the matrix is deduplicated against the Supabase audio_assets ledger
# (exact text match, stripped): a dialogue already in the ledger gets its
# EXISTING audio_code written back into the sheet's file cell; a new dialogue
# keeps the fabricator-assigned filename and is registered as pending
# (status=0) for the external TTS process. No audio is generated here.

# (dialogue column, file column, is comma-separated multi-value)
AUDIO_PAIRS = [
    ("Instruction VO", "Instruction VO — File", False),
    ("Audio in Question", "Audio in Question — File", False),
    ("VO for Question", "VO for Question — File", False),
    ("Correct Answer", "Correct Answer VO — File", False),
    ("Other Options", "Other Options VO — File", True),
]

_DASH = "—"


def audio_planner_node(state: dict) -> dict:
    matrix = state.get("raw_question_matrix") or []
    milestone = state.get("milestone_code", "")
    theme = state.get("theme_code", "")

    def _cells(row, content_col, file_col, multi):
        """Yield (dialogue, file_token) pairs from one row's column pair."""
        content = str(row.get(content_col, "")).strip()
        files = str(row.get(file_col, "")).strip()
        if not content or content == _DASH:
            return []
        if not multi:
            return [(content, files)]
        # Other Options: pairwise split. Distractor text itself never contains
        # commas (single words/short phrases per the template rules).
        dialogues = [d.strip() for d in content.split(",")]
        file_list = ([f.strip() for f in files.split(",")]
                     if files and files != _DASH else [])
        return [(d, file_list[i] if i < len(file_list) else "")
                for i, d in enumerate(dialogues) if d and d != _DASH]

    # ── One batched ledger lookup for every dialogue in the matrix ──
    all_dialogues = []
    for row in matrix:
        for content_col, file_col, multi in AUDIO_PAIRS:
            all_dialogues += [d for d, _ in _cells(row, content_col, file_col, multi)]
    try:
        code_by_dialogue = lookup_existing_audio(sorted(set(all_dialogues)))
    except Exception as e:
        log.warning("Audio ledger lookup failed, treating all as new: %s", e)
        code_by_dialogue = {}
    reused_from_db = set(code_by_dialogue)

    # ── Rewrite file cells + collect new dialogues ──
    new_entries = []
    rewrites = 0
    for row in matrix:
        pc = str(row.get("Playable Code", "")).strip()
        for content_col, file_col, multi in AUDIO_PAIRS:
            pairs = _cells(row, content_col, file_col, multi)
            if not pairs:
                continue
            out_tokens = []
            for dialogue, token in pairs:
                known = code_by_dialogue.get(dialogue)
                if known:
                    if token != known:
                        rewrites += 1
                    out_tokens.append(known)
                    continue
                # First sighting: keep the fabricator-assigned filename as the
                # canonical code (existing naming scheme) and register it.
                if not token or token == _DASH:
                    out_tokens.append(token)   # nothing to register without a name
                    continue
                code_by_dialogue[dialogue] = token
                new_entries.append({
                    "audio_code": token, "dialogue_text": dialogue,
                    "milestone_code": milestone, "theme_code": theme,
                    "playable_code": pc,
                })
                out_tokens.append(token)
            row[file_col] = ", ".join(out_tokens) if multi else out_tokens[0]

    try:
        upsert_pending_audio(new_entries)
    except Exception as e:
        log.warning("DB upsert_pending_audio failed (non-fatal): %s", e)

    log.info("Audio planner: %d distinct lines — %d new (registered pending), "
             "%d reused from ledger, %d file cells rewritten",
             len(code_by_dialogue), len(new_entries), len(reused_from_db), rewrites)
    return {"raw_question_matrix": matrix,
            "pending_audio": new_entries,
            "audio_reused": len(reused_from_db)}


def eval_node(state: dict) -> dict:
    """Run the two-lane eval scorer on the final question matrix.
    Placed after asset_planner so the matrix (and its image plan) is final."""
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
