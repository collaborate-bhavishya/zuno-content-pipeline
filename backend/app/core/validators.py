"""
Deterministic (non-LLM) validation gates.

Cheap checks run before the LLM judge. `validate_matrix` now enforces most of
the SpeakX pedagogical rules: column schema, age-gated template restrictions,
image-filename format, STT hygiene, vocab-before-sentence interleaving, and
the speaking-urgency deadlines from skill_v6.md.
"""
import re
from typing import List, Optional, Tuple

from app.core.config import CONFIG, DEFAULT_MATRIX_COLUMNS, TEMPLATE_COLUMN_RULES

# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

UNSAFE_LEXICON = ["blood", "scary", "bite", "kill", "dead", "monster",
                  "ghost", "hunt", "hurt", "attack", "abuse", "horror"]

FORBIDDEN_VOCAB = ["carnivorous", "mammal", "reptile", "feline", "enormous"]

# Child-facing matrix columns — the text a child actually sees or hears.
# Safety/vocab gates are enforced HERE (where it matters), not on the blueprint,
# which is an internal reasoning artifact the child never sees.
_CHILD_FACING_COLS = [
    "Instruction Text", "Instruction VO",
    "Text in Question", "Audio in Question", "VO for Question",
    "Correct Answer", "Other Options",
]


def _whole_word_hits(text: str, lexicon: list) -> list:
    """Return lexicon words that appear as whole words in text (case-insensitive)."""
    low = text.lower()
    return [w for w in lexicon if re.search(rf"\b{re.escape(w)}\b", low)]


def scan_for_unsafe_content(blueprint_text: str) -> list:
    """Scan for unsafe words in actual lesson content.

    Skips meta-instruction blocks (safety protocols, forbidden-word lists,
    'do not use' examples) that legitimately mention unsafe words as negative
    examples rather than as lesson content. Uses whole-word matching to avoid
    false positives (e.g. 'skill' must not match 'kill').
    """
    content = blueprint_text
    content = re.sub(
        r"(?si)🚨\s*ABSOLUTE CONTENT SAFETY PROTOCOL.*?(?=\n🔤|\n💡|\n🗣|\n##|\n🎯|\n🎮|\Z)",
        "", content,
    )
    content = re.sub(
        r"(?i)^.*(?:DO NOT USE|strictly prohibited|forbidden|no words like|must not contain|e\.g\.,?\s*no\b).*$",
        "", content, flags=re.MULTILINE,
    )
    content = re.sub(
        r"(?i)^.*(?:Horror|fear|scary elements|dark themes).*$",
        "", content, flags=re.MULTILINE,
    )
    return _whole_word_hits(content, UNSAFE_LEXICON)


def scan_matrix_safety(rows: List[dict]) -> Optional[str]:
    """Enforce child-safety + age-vocab on the CHILD-FACING matrix columns.

    Returns an error string on the first violation, else None. Whole-word
    matching keeps it precise. This is the authoritative safety gate — the
    blueprint phase relies on the context-aware LLM judge instead.
    """
    for idx, row in enumerate(rows):
        qnum = idx + 1
        seen = " ".join(str(row.get(c, "")) for c in _CHILD_FACING_COLS)
        unsafe = _whole_word_hits(seen, UNSAFE_LEXICON)
        if unsafe:
            return (f"Q{qnum}: child-facing text contains unsafe word(s) {unsafe}. "
                    f"Replace with gentle, positive language.")
        vocab = _whole_word_hits(seen, FORBIDDEN_VOCAB)
        if vocab:
            return (f"Q{qnum}: child-facing text uses too-academic word(s) {vocab}. "
                    f"Use simple preschool words a child this age would know.")
    return None


# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------

def validate_blueprint(text: str, age: int) -> Tuple[bool, Optional[str]]:
    # NOTE: forbidden-vocabulary and unsafe-word enforcement moved to the matrix
    # phase (scan_matrix_safety) — the blueprint is internal reasoning the child
    # never sees, so academic/critique terms there are not violations. The
    # context-aware LLM judge still gates blueprint quality + safety.
    if age in (3, 4):
        t5_mentions = re.findall(r'\bT5\b', text)
        t5_exclusions = re.findall(
            r'(?:no |excluded|forbidden|skip|without )T5|T5\s*(?:excluded|forbidden|is not|not used)',
            text, re.IGNORECASE,
        )
        if len(t5_mentions) > len(t5_exclusions):
            return False, "Template T5 is forbidden for ages 3-4 (pre-literacy)."
    if len(text.strip()) < 100:
        return False, "Blueprint too short; expand the lesson plan."
    return True, None


# ---------------------------------------------------------------------------
# Matrix  — comprehensive SpeakX validation
# ---------------------------------------------------------------------------

# Template → layer mapping
_TEMPLATE_LAYER = {
    "T4": "1 - Vocabulary", "T1": "1 - Vocabulary", "T2": "1 - Vocabulary",
    "T3": "1 - Vocabulary", "T5": "1 - Vocabulary",
    "F1": "2 - Concept Builder", "F2": "2 - Concept Builder",
    "F3": "2 - Concept Builder", "T7": "2 - Concept Builder",
    "T7.1": "2 - Concept Builder",
    "T9": "2.5 - Sentence Comprehension",
    "D1": "3 - Sentence Formation", "T6.1": "3 - Sentence Formation",
    "T6.2": "3 - Sentence Formation", "T6.3": "3 - Sentence Formation",
    "T8": "4 - Guided Speaking", "T8.2": "4 - Guided Speaking",
    "C1": "5 - Independent Speaking",
}

# Templates that REQUIRE a non-empty STT Expectation (voice input)
_VOICE_TEMPLATES = {"T3", "T6.2", "T6.3", "T8", "T8.2", "C1"}

# Templates that must NOT have STT (tap-only)
_TAP_TEMPLATES = {"T4", "T1", "T2", "T5", "F1", "F2", "F3", "T7", "T7.1",
                  "T9", "D1", "T6.1"}

# File columns that mirror a content column (content → file)
_FILE_MIRRORS = {
    "Instruction VO": "Instruction VO — File",
    "Audio in Question": "Audio in Question — File",
    "VO for Question": "VO for Question — File",
    "Correct Answer": "Correct Answer VO — File",
    "Other Options": "Other Options VO — File",
}

# All known template codes
_ALL_TEMPLATES = set(_TEMPLATE_LAYER.keys())

# Vocab layer templates (must appear before sentence layer for each word)
_VOCAB_TEMPLATES = {"T4", "T1", "T2", "T3", "T5"}
_SENTENCE_TEMPLATES = {"D1", "T6.1", "T6.2", "T6.3"}

# Em-dash used as "not applicable"
_DASH = "—"


def _is_empty(val: str) -> bool:
    """Check if a cell value is empty / dash / not applicable."""
    v = str(val).strip()
    return v in ("", _DASH, "-", "—", "N/A", "n/a", "none", "None")


def _is_valid_png(val: str) -> bool:
    """Check that a filename looks like a valid snake_case .png."""
    v = val.strip()
    if not v.endswith(".png"):
        return False
    name = v[:-4]
    # Allow lowercase letters, digits, underscores
    return bool(re.match(r'^[a-z0-9_]+$', name))


# Cap only as a prompt-size guard — high enough that a normal run reports
# everything in one pass. Truncating lower caused whack-a-mole: the fabricator
# fixed the reported errors, regenerated the whole (80+ row) matrix, and the
# validator surfaced the NEXT batch — burning a full LLM call per 3 fixes and
# exhausting both retries and API quota without ever converging.
_MAX_REPORTED_ERRORS = 60


def _format_errors(errors: List[str]) -> str:
    """Numbered list of EVERY violation, so one repair pass can fix them all."""
    shown = errors[:_MAX_REPORTED_ERRORS]
    out = "\n".join(f"{i}. {e}" for i, e in enumerate(shown, 1))
    if len(errors) > len(shown):
        out += f"\n(+{len(errors) - len(shown)} more — fix these first.)"
    return out


def validate_matrix(rows: List[dict], age: int = None) -> Tuple[bool, Optional[str]]:
    """Comprehensive SpeakX matrix validation.

    Returns (True, None) on success, or (False, "<numbered list of every
    violation>"). Reporting all errors at once is deliberate — see
    _MAX_REPORTED_ERRORS.
    """
    if not rows:
        return False, "Matrix is empty — no question rows generated."

    # Resolve age guidelines
    if age is None:
        age = 5  # fallback
    guidelines = CONFIG.output.age_guidelines.get(age, {})
    allowed = set(guidelines.get("allowed_templates", _ALL_TEMPLATES))
    forbidden = set(guidelines.get("forbidden_templates", []))
    max_words = guidelines.get("max_words_per_sentence", 99)

    errors: List[str] = []

    # ── 1. Schema: every row must have all 15 required columns ──
    required_cols = set(CONFIG.output.matrix_columns)
    for idx, row in enumerate(rows):
        missing = required_cols - set(row.keys())
        if missing:
            errors.append(f"Row {idx+1} (Q{idx+1}): missing columns {sorted(missing)}.")

    if errors:
        # Schema errors are fatal — return immediately so fabricator fixes structure
        return False, _format_errors(errors)

    # ── 1b. Child-facing safety + age-vocab gate (authoritative) ──
    safety_err = scan_matrix_safety(rows)
    if safety_err:
        return False, safety_err

    # ── 2. Per-row field-level checks ──
    vocab_introduced: set = set()   # words that have been introduced via T4
    vocab_drilled: set = set()      # words that have cleared T1/T2 + T3
    first_voice_q = None            # first T6.2+ question number
    first_guided_q = None           # first T8/T8.2 question number
    seen_templates: List[str] = []

    for idx, row in enumerate(rows):
        qnum = idx + 1
        template = str(row.get("Template", "")).strip()
        screen = str(row.get("Instruction Text", "")).strip()
        audio = str(row.get("Instruction VO", "")).strip()
        stt = str(row.get("STT Expectation", "")).strip()
        img_q = str(row.get("Image in Question — Name", "")).strip()
        correct_img = str(row.get("Correct Answer — Image", "")).strip()
        other_img = str(row.get("Other Options — Image", "")).strip()
        layer = str(row.get("Layer", "")).strip()
        correct_ans = str(row.get("Correct Answer", "")).strip()
        other_opts = str(row.get("Other Options", "")).strip()

        # ── 2a. Template code must be valid ──
        if template not in _ALL_TEMPLATES:
            errors.append(f"Q{qnum}: unknown template '{template}'. Valid: {sorted(_ALL_TEMPLATES)}.")
            continue

        seen_templates.append(template)

        # ── 2b. Age-gated template restrictions ──
        if forbidden and template in forbidden:
            errors.append(f"Q{qnum}: template {template} is FORBIDDEN for age {age}.")
        if allowed and template not in allowed:
            errors.append(f"Q{qnum}: template {template} is not in the allowed list for age {age}.")

        # ── 2c. STT Expectation hygiene ──
        if template in _VOICE_TEMPLATES:
            if _is_empty(stt):
                errors.append(
                    f"Q{qnum}: {template} requires speech input — STT Expectation must not be empty/dash."
                )
            elif any(c in stt for c in ".!?,;:"):
                errors.append(
                    f"Q{qnum}: STT Expectation must be clean lowercase, no punctuation. Got: '{stt}'."
                )
            elif stt != stt.lower():
                errors.append(
                    f"Q{qnum}: STT Expectation must be lowercase. Got: '{stt}'."
                )
        if template in _TAP_TEMPLATES:
            if not _is_empty(stt):
                errors.append(
                    f"Q{qnum}: {template} is tap-only — STT Expectation should be '—', not '{stt}'."
                )

        # ── 2d. Instruction Text & Instruction VO must not be empty ──
        if _is_empty(screen) and template not in ("T8.2",):
            errors.append(f"Q{qnum}: Instruction Text is empty for {template}.")
        if _is_empty(audio):
            errors.append(f"Q{qnum}: Instruction VO is empty for {template}.")

        # ── 2e. T1 alignment law: instruction text ≠ instruction VO ──
        if template == "T1":
            if screen.lower() == audio.lower():
                errors.append(
                    f"Q{qnum}: T1 requires Instruction Text (directive) ≠ Instruction VO (isolated word)."
                )

        # ── 2f. Per-template column rules (Required Matrix enforcement) ──
        tpl_rules = TEMPLATE_COLUMN_RULES.get(template, {})
        for col, rule in tpl_rules.items():
            val = str(row.get(col, "")).strip()
            if rule == "Yes" and _is_empty(val):
                errors.append(
                    f"Q{qnum}: {template} requires '{col}' but it is empty/dash."
                )
            elif rule == "No" and not _is_empty(val):
                errors.append(
                    f"Q{qnum}: {template} must NOT have '{col}' — should be '—'. Got: '{val[:40]}'."
                )

        # ── 2f2. File columns must mirror their content columns ──
        for content_col, file_col in _FILE_MIRRORS.items():
            content_val = str(row.get(content_col, "")).strip()
            file_val = str(row.get(file_col, "")).strip()
            if not _is_empty(content_val) and _is_empty(file_val):
                errors.append(
                    f"Q{qnum}: '{content_col}' has content but '{file_col}' is empty — must provide filename."
                )
            elif _is_empty(content_val) and not _is_empty(file_val):
                errors.append(
                    f"Q{qnum}: '{file_col}' has a filename but '{content_col}' is empty — remove file or add content."
                )

        # ── 2g. Image filename format (.png, snake_case) ──
        for col_name, val in [("Image in Question — Name", img_q),
                              ("Correct Answer — Image", correct_img)]:
            if not _is_empty(val):
                for fn in [f.strip() for f in val.split(",")]:
                    if fn and not _is_valid_png(fn):
                        errors.append(
                            f"Q{qnum}: '{col_name}' has invalid filename '{fn}'. "
                            f"Must be lowercase snake_case ending in .png."
                        )
        if not _is_empty(other_img) and other_img != _DASH:
            for fn in [f.strip() for f in other_img.split(",")]:
                if fn and not _is_valid_png(fn):
                    errors.append(
                        f"Q{qnum}: 'Other Options — Image' has invalid filename '{fn}'. "
                        f"Must be lowercase snake_case ending in .png."
                    )

        # ── 2h. (Covered by 2f per-template rules above) ──

        # ── 2i. Correct Answer must not be empty (except T4, T3 which are intro/repeat) ──
        if template not in ("T4", "T3", "T8", "T8.2", "C1"):
            if _is_empty(correct_ans) and _is_empty(correct_img):
                errors.append(f"Q{qnum}: {template} needs a Correct Answer (text or image).")

        # ── 2j. Options required for multi-choice templates ──
        if template in ("T1", "T2", "T5", "F2", "F3", "T7", "T9", "T6.1"):
            if _is_empty(other_opts) and _is_empty(other_img):
                errors.append(f"Q{qnum}: {template} requires Other Options (distractors).")

        # ── 2k. D1 must have scrambled tiles in Other Options ──
        if template == "D1":
            if _is_empty(other_opts):
                errors.append(f"Q{qnum}: D1 requires word tiles in 'Other Options'.")

        # ── 2l. Word count check for sentence templates ──
        if template in ("D1", "T6.1", "T6.2", "T6.3", "T8"):
            # Count words in the target sentence (Text in Question > Instruction VO > Instruction Text)
            text_q = str(row.get("Text in Question", "")).strip()
            text_to_check = text_q if not _is_empty(text_q) else (audio if not _is_empty(audio) else screen)
            word_count = len(text_to_check.split())
            if word_count > max_words + 4:  # allow some slack for framing
                errors.append(
                    f"Q{qnum}: sentence has {word_count} words but age {age} max is {max_words}."
                )

        # ── 2m. Em-dash consistency: empty cells should use — not hyphen or blank ──
        for col in CONFIG.output.matrix_columns:
            val = str(row.get(col, "")).strip()
            if val == "-":
                errors.append(
                    f"Q{qnum}: column '{col}' uses hyphen '-' — use em-dash '—' for empty cells."
                )

        # ── Track vocab introduction for interleaving check ──
        if template == "T4":
            # T4 introduces a word — extract from Instruction Text
            word = screen.lower().strip().rstrip(".")
            vocab_introduced.add(word)
        if template in ("T1", "T2"):
            # Extract target word from audio (isolated word)
            word = audio.lower().strip().rstrip("!.").strip()
            vocab_introduced.add(word)  # also counts as introduced
        if template == "T3":
            word = stt.lower().strip() if not _is_empty(stt) else ""
            if word:
                vocab_drilled.add(word)

        # ── Track speaking urgency ──
        if template in ("T6.2", "T6.3") and first_voice_q is None:
            first_voice_q = qnum
        if template in ("T8", "T8.2") and first_guided_q is None:
            first_guided_q = qnum

    # ── 3. Structural / ordering checks ──

    # ── 3a. First template should be T4 (word introduction) ──
    if seen_templates and seen_templates[0] != "T4":
        errors.append(
            f"First question should be T4 (word intro) but got {seen_templates[0]}. "
            f"Every new word must enter through T4."
        )

    # ── 3b. T4 must appear before T1/T2/T3 for same word ──
    # (Simplified: at least one T4 must appear before any T1)
    if seen_templates:
        first_t4 = next((i for i, t in enumerate(seen_templates) if t == "T4"), None)
        first_t1 = next((i for i, t in enumerate(seen_templates) if t in ("T1", "T2")), None)
        if first_t4 is not None and first_t1 is not None and first_t1 < first_t4:
            errors.append("T1/T2 appears before any T4. Words must be introduced via T4 first.")

    # ── 3c. Vocab layer must appear before sentence layer ──
    first_vocab = next((i for i, t in enumerate(seen_templates) if t in _VOCAB_TEMPLATES), None)
    first_sentence = next((i for i, t in enumerate(seen_templates) if t in _SENTENCE_TEMPLATES), None)
    if first_sentence is not None and first_vocab is not None and first_sentence < first_vocab:
        errors.append("Sentence formation templates appear before vocabulary templates. Vocab must come first.")

    # ── 3d. Concept layer should appear before sentence layer ──
    concept_templates = {"F1", "F2", "F3", "T7", "T7.1"}
    first_concept = next((i for i, t in enumerate(seen_templates) if t in concept_templates), None)
    if first_sentence is not None and (first_concept is None or first_sentence < first_concept):
        errors.append(
            "Sentence formation starts before any concept-builder (F1/F2/F3). "
            "Layer 2 concepts must be checked before Layer 3 sentence building."
        )

    # ── 3e. T9 comprehension must appear before D1/T6.x ──
    first_t9 = next((i for i, t in enumerate(seen_templates) if t == "T9"), None)
    if first_sentence is not None and (first_t9 is None or first_sentence < first_t9):
        errors.append(
            "D1/T6.x appears before T9 comprehension check. "
            "T9 must gate sentence formation (T9 → D1 → T6.1 → T6.2 → T6.3)."
        )

    # ── 3f. Within sentence block: D1 before T6.1 before T6.2 before T6.3 ──
    sentence_order = ["D1", "T6.1", "T6.2", "T6.3"]
    sentence_positions = {}
    for i, t in enumerate(seen_templates):
        if t in sentence_order and t not in sentence_positions:
            sentence_positions[t] = i
    for a, b in zip(sentence_order, sentence_order[1:]):
        if a in sentence_positions and b in sentence_positions:
            if sentence_positions[a] > sentence_positions[b]:
                errors.append(
                    f"Sentence scaffold order violated: {b} appears before {a}. "
                    f"Required order: D1 → T6.1 → T6.2 → T6.3."
                )

    # ── 3g. Speaking urgency thresholds (only check for longer matrices) ──
    total_qs = len(rows)
    if total_qs >= 14:
        if first_voice_q is None or first_voice_q > 14:
            errors.append(
                f"Speaking urgency violated: first oral production (T6.2/T6.3) "
                f"{'not found' if first_voice_q is None else f'at Q{first_voice_q}'}. "
                f"Must occur by Q14."
            )
    if total_qs >= 18:
        if first_guided_q is None or first_guided_q > 18:
            errors.append(
                f"Speaking urgency violated: first guided speaking (T8/T8.2) "
                f"{'not found' if first_guided_q is None else f'at Q{first_guided_q}'}. "
                f"Must occur by Q18."
            )

    # ── 3h. F1 should come before F2, F2 before F3, F3 before T7 ──
    concept_order = ["F1", "F2", "F3", "T7", "T7.1"]
    concept_positions = {}
    for i, t in enumerate(seen_templates):
        if t in concept_order and t not in concept_positions:
            concept_positions[t] = i
    for a, b in zip(concept_order, concept_order[1:]):
        if a in concept_positions and b in concept_positions:
            if concept_positions[a] > concept_positions[b]:
                errors.append(
                    f"Concept builder order violated: {b} appears before {a}. "
                    f"Required: F1 → F2 → F3 → T7 → T7.1."
                )

    # ── 3i. No emoji in any cell ──
    emoji_re = re.compile(
        r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
        r"\U0001F900-\U0001F9FF\U00002702-\U000027B0\U0001FA00-\U0001FA6F]"
    )
    for idx, row in enumerate(rows):
        for col in ("Instruction Text", "Instruction VO", "Text in Question", "STT Expectation"):
            val = str(row.get(col, ""))
            if emoji_re.search(val):
                errors.append(f"Q{idx+1}: emoji found in '{col}'. Emojis are banned.")
                break

    # ── Return ──
    if errors:
        return False, _format_errors(errors)
    return True, None
