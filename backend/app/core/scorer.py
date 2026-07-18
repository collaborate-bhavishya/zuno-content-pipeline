"""
Two-lane scoring engine for the Zuno SpeakX eval framework.

Architecture:
  ┌─────────────────────────┐     ┌──────────────────────────┐
  │  LANE 1: Deterministic  │     │  LANE 2: LLM-as-a-Judge  │
  │  (Fast, Free, Exact)    │     │  (Semantic, 1 API call)   │
  ├─────────────────────────┤     ├──────────────────────────┤
  │ schema_compliance       │     │ tone_quality             │
  │ template_validity       │     │ content_relevance        │
  │ pedagogical_order       │     │ safety_semantic          │
  │ age_appropriateness     │     └──────────────────────────┘
  │ safety_lexical          │
  │ stt_hygiene             │
  │ image_format            │
  └─────────────────────────┘

Lane 1 runs pure Python — zero cost, instant.
Lane 2 makes ONE consolidated LLM call that scores tone + relevance + safety
semantically, catching nuances that substring matching misses.

The final score blends both lanes with configurable weights.
"""
import re
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Optional

from app.core.config import CONFIG

log = logging.getLogger("eval.scorer")

# ───────────────────────────────────────────────────────────────
# Data structures
# ───────────────────────────────────────────────────────────────

@dataclass
class ScoreDimension:
    name: str
    score: float          # 0.0 – 1.0
    max_score: float      # always 1.0
    weight: float         # for weighted total
    lane: str = "deterministic"   # "deterministic" or "llm"
    passed: int = 0
    total: int = 0
    issues: List[str] = field(default_factory=list)
    detail: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class EvalScore:
    case_id: str
    theme: str
    age: int
    total_score: float           # weighted 0–100
    grade: str                   # A/B/C/D/F
    dimensions: List[ScoreDimension] = field(default_factory=list)
    row_count: int = 0
    llm_calls: int = 0          # how many LLM calls this eval used
    error: Optional[str] = None

    def to_dict(self):
        d = asdict(self)
        d["dimensions"] = [dim.to_dict() for dim in self.dimensions]
        return d


# ───────────────────────────────────────────────────────────────
# Constants
# ───────────────────────────────────────────────────────────────

_DASH = "—"
_ALL_TEMPLATES = {
    "T4", "T1", "T2", "T3", "T5", "F1", "F2", "F3", "T7", "T7.1",
    "T9", "D1", "T6.1", "T6.2", "T6.3", "T8", "T8.2", "C1",
}
_VOICE_TEMPLATES = {"T3", "T6.2", "T6.3", "T8", "T8.2", "C1"}
_TAP_TEMPLATES = {"T4", "T1", "T2", "T5", "F1", "F2", "F3", "T7", "T7.1",
                  "T9", "D1", "T6.1"}
_IMAGE_REQUIRED = {"T4", "T1", "F1", "F2", "F3", "T7"}
_VOCAB = {"T4", "T1", "T2", "T3", "T5"}
_CONCEPT = {"F1", "F2", "F3", "T7", "T7.1"}
_SENTENCE = {"D1", "T6.1", "T6.2", "T6.3"}

# Fast lexical gate — catches obvious unsafe words before the LLM call
UNSAFE_LEXICON = ["blood", "scary", "bite", "kill", "dead", "monster",
                  "ghost", "hunt", "hurt", "attack", "abuse", "horror",
                  "gun", "knife", "war", "fight", "scream", "poison"]

EMOJI_RE = re.compile(
    r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
    r"\U0001F900-\U0001F9FF\U00002702-\U000027B0\U0001FA00-\U0001FA6F]"
)


def _is_empty(val) -> bool:
    v = str(val).strip()
    return v in ("", _DASH, "-", "—", "N/A", "n/a", "none", "None")


def _is_valid_png(val: str) -> bool:
    v = val.strip()
    return v.endswith(".png") and bool(re.match(r'^[a-z0-9_]+$', v[:-4]))


# ───────────────────────────────────────────────────────────────
# LANE 1: Deterministic scorers (fast, free, exact)
# ───────────────────────────────────────────────────────────────

def _score_schema(rows: List[dict], expected: dict) -> ScoreDimension:
    required = set(CONFIG.output.matrix_columns)
    n_expected = expected.get("required_columns", 15)
    issues, total, passed = [], len(rows), 0
    for i, row in enumerate(rows):
        missing = required - set(row.keys())
        if missing:
            issues.append(f"Row {i+1}: missing {sorted(missing)}")
        else:
            passed += 1
    return ScoreDimension(
        name="schema_compliance", score=passed/total if total else 0,
        max_score=1.0, weight=0.12, lane="deterministic",
        passed=passed, total=total, issues=issues[:5],
        detail=f"{passed}/{total} rows have all {n_expected} columns",
    )


def _score_templates(rows: List[dict], expected: dict) -> ScoreDimension:
    allowed = set(expected.get("allowed_templates", _ALL_TEMPLATES))
    forbidden = set(expected.get("forbidden_templates", []))
    issues, total, passed = [], len(rows), 0
    for i, row in enumerate(rows):
        t = str(row.get("Template", "")).strip()
        if t not in _ALL_TEMPLATES:
            issues.append(f"Row {i+1}: unknown template '{t}'")
        elif t in forbidden:
            issues.append(f"Row {i+1}: forbidden template {t}")
        elif t not in allowed:
            issues.append(f"Row {i+1}: template {t} not in allowed set")
        else:
            passed += 1
    return ScoreDimension(
        name="template_validity", score=passed/total if total else 0,
        max_score=1.0, weight=0.12, lane="deterministic",
        passed=passed, total=total, issues=issues[:5],
        detail=f"{passed}/{total} templates valid & age-appropriate",
    )


def _score_pedagogical_order(rows: List[dict], expected: dict) -> ScoreDimension:
    templates = [str(r.get("Template", "")).strip() for r in rows]
    checks_passed, checks_total, issues = 0, 0, []

    # 1: starts with T4
    checks_total += 1
    if expected.get("must_start_with") and templates:
        if templates[0] == expected["must_start_with"]:
            checks_passed += 1
        else:
            issues.append(f"Should start with {expected['must_start_with']}, got {templates[0]}")
    else:
        checks_passed += 1

    # 2: vocab before sentence
    checks_total += 1
    first_vocab = next((i for i, t in enumerate(templates) if t in _VOCAB), None)
    first_sent = next((i for i, t in enumerate(templates) if t in _SENTENCE), None)
    if first_sent is None or (first_vocab is not None and first_vocab < first_sent):
        checks_passed += 1
    else:
        issues.append("Sentence templates appear before vocabulary")

    # 3: concept before sentence
    checks_total += 1
    first_concept = next((i for i, t in enumerate(templates) if t in _CONCEPT), None)
    if first_sent is None or (first_concept is not None and first_concept < first_sent):
        checks_passed += 1
    else:
        issues.append("Sentence templates appear before concept builders")

    # 4: T9 before D1
    checks_total += 1
    first_t9 = next((i for i, t in enumerate(templates) if t == "T9"), None)
    first_d1 = next((i for i, t in enumerate(templates) if t == "D1"), None)
    if first_d1 is None or (first_t9 is not None and first_t9 < first_d1):
        checks_passed += 1
    else:
        issues.append("D1 appears before T9 comprehension gate")

    # 5: Concept order F1→F2→F3→T7→T7.1
    checks_total += 1
    concept_seq = [t for t in templates if t in _CONCEPT]
    concept_order = ["F1", "F2", "F3", "T7", "T7.1"]
    positions = {t: concept_order.index(t) for t in concept_seq if t in concept_order}
    ordered = all(
        positions.get(concept_seq[i], 0) <= positions.get(concept_seq[i+1], 0)
        for i in range(len(concept_seq)-1)
        if concept_seq[i] in positions and concept_seq[i+1] in positions
    ) if len(concept_seq) >= 2 else True
    if ordered:
        checks_passed += 1
    else:
        issues.append("Concept order violated (F1→F2→F3→T7→T7.1)")

    # 6: Sentence scaffold D1→T6.1→T6.2→T6.3
    checks_total += 1
    sent_seq = [t for t in templates if t in _SENTENCE]
    sent_order = ["D1", "T6.1", "T6.2", "T6.3"]
    s_positions = {t: sent_order.index(t) for t in sent_seq if t in sent_order}
    s_ordered = all(
        s_positions.get(sent_seq[i], 0) <= s_positions.get(sent_seq[i+1], 0)
        for i in range(len(sent_seq)-1)
        if sent_seq[i] in s_positions and sent_seq[i+1] in s_positions
    ) if len(sent_seq) >= 2 else True
    if s_ordered:
        checks_passed += 1
    else:
        issues.append("Sentence scaffold order violated (D1→T6.1→T6.2→T6.3)")

    score = checks_passed / checks_total if checks_total else 0
    return ScoreDimension(
        name="pedagogical_order", score=score, max_score=1.0, weight=0.15,
        lane="deterministic", passed=checks_passed, total=checks_total,
        issues=issues, detail=f"{checks_passed}/{checks_total} ordering rules passed",
    )


def _score_age_appropriateness(rows: List[dict], expected: dict) -> ScoreDimension:
    max_words = expected.get("max_words_per_sentence", 99)
    issues, total, passed = [], 0, 0
    sentence_templates = {"D1", "T6.1", "T6.2", "T6.3", "T8"}
    for i, row in enumerate(rows):
        t = str(row.get("Template", "")).strip()
        if t not in sentence_templates:
            continue
        total += 1
        text_q = str(row.get("Text in Question", ""))
        audio = str(row.get("Instruction VO", ""))
        screen = str(row.get("Instruction Text", ""))
        text = text_q if not _is_empty(text_q) else (audio if not _is_empty(audio) else screen)
        wc = len(text.split())
        if wc <= max_words + 4:
            passed += 1
        else:
            issues.append(f"Row {i+1} ({t}): {wc} words, max {max_words}")
    if total == 0:
        for i, row in enumerate(rows):
            total += 1
            screen = str(row.get("Instruction Text", ""))
            if len(screen.split()) <= max_words:
                passed += 1
    return ScoreDimension(
        name="age_appropriateness", score=passed/total if total else 1.0,
        max_score=1.0, weight=0.10, lane="deterministic",
        passed=passed, total=total, issues=issues[:5],
        detail=f"{passed}/{total} sentences within word limit ({max_words})",
    )


def _score_safety_lexical(rows: List[dict], expected: dict) -> ScoreDimension:
    """Fast lexical gate — catches obvious unsafe words for free."""
    text_cols = ["Instruction Text", "Instruction VO", "Text in Question",
                 "STT Expectation", "Correct Answer", "Other Options", "Notes"]
    issues, total, passed = [], len(rows), 0
    emoji_issues = 0
    for i, row in enumerate(rows):
        row_text = " ".join(str(row.get(c, "")) for c in text_cols).lower()
        found = [w for w in UNSAFE_LEXICON if w in row_text]
        if found:
            issues.append(f"Row {i+1}: unsafe words {found}")
        else:
            passed += 1
        for col in ("Instruction Text", "Instruction VO", "Text in Question"):
            if EMOJI_RE.search(str(row.get(col, ""))):
                emoji_issues += 1
                issues.append(f"Row {i+1}: emoji in {col}")
    return ScoreDimension(
        name="safety_lexical", score=passed/total if total else 0,
        max_score=1.0, weight=0.08, lane="deterministic",
        passed=passed, total=total, issues=issues[:5],
        detail=f"{passed}/{total} rows pass lexical safety gate",
    )


def _score_stt_hygiene(rows: List[dict], expected: dict) -> ScoreDimension:
    issues, total, passed = [], 0, 0
    for i, row in enumerate(rows):
        t = str(row.get("Template", "")).strip()
        stt = str(row.get("STT Expectation", "")).strip()
        if t in _VOICE_TEMPLATES:
            total += 1
            if _is_empty(stt):
                issues.append(f"Row {i+1} ({t}): STT empty but voice required")
            elif any(c in stt for c in ".!?,;:"):
                issues.append(f"Row {i+1}: STT has punctuation: '{stt}'")
            elif stt != stt.lower():
                issues.append(f"Row {i+1}: STT not lowercase: '{stt}'")
            else:
                passed += 1
        elif t in _TAP_TEMPLATES:
            total += 1
            if _is_empty(stt):
                passed += 1
            else:
                issues.append(f"Row {i+1} ({t}): tap template has STT '{stt}'")
    return ScoreDimension(
        name="stt_hygiene", score=passed/total if total else 1.0,
        max_score=1.0, weight=0.08, lane="deterministic",
        passed=passed, total=total, issues=issues[:5],
        detail=f"{passed}/{total} STT fields correctly set",
    )


def _score_image_format(rows: List[dict], expected: dict) -> ScoreDimension:
    issues, total, passed = [], 0, 0
    for i, row in enumerate(rows):
        t = str(row.get("Template", "")).strip()
        img_q = str(row.get("Image in Question — Name", "")).strip()
        if t in _IMAGE_REQUIRED:
            total += 1
            if _is_empty(img_q):
                issues.append(f"Row {i+1} ({t}): missing required image")
            elif _is_valid_png(img_q):
                passed += 1
            else:
                issues.append(f"Row {i+1}: bad filename '{img_q}'")
        if t == "T5":
            total += 1
            if _is_empty(img_q):
                passed += 1
            else:
                issues.append(f"Row {i+1}: T5 must not have images")
        for col in ("Correct Answer — Image", "Other Options — Image"):
            val = str(row.get(col, "")).strip()
            if not _is_empty(val):
                for fn in [f.strip() for f in val.split(",")]:
                    if fn:
                        total += 1
                        if _is_valid_png(fn):
                            passed += 1
                        else:
                            issues.append(f"Row {i+1}: '{col}' bad name '{fn}'")
    return ScoreDimension(
        name="image_format", score=passed/total if total else 1.0,
        max_score=1.0, weight=0.05, lane="deterministic",
        passed=passed, total=total, issues=issues[:5],
        detail=f"{passed}/{total} image filenames valid",
    )


def _run_deterministic(rows: List[dict], expected: dict) -> List[ScoreDimension]:
    """Lane 1: all deterministic checks. Fast and free."""
    return [
        _score_schema(rows, expected),
        _score_templates(rows, expected),
        _score_pedagogical_order(rows, expected),
        _score_age_appropriateness(rows, expected),
        _score_safety_lexical(rows, expected),
        _score_stt_hygiene(rows, expected),
        _score_image_format(rows, expected),
    ]


# ───────────────────────────────────────────────────────────────
# LANE 2: LLM-as-a-Judge (semantic, 1 consolidated call)
# ───────────────────────────────────────────────────────────────

_TEMPLATE_DESCRIPTIONS = {
    "T4": "Single-tap image identify — child taps the matching image. Screen shows 1 word, audio says the word. Tone expectation: simple, clear.",
    "T1": "Single-tap vocabulary — child taps the correct image for a word. Tone: encouraging prompt.",
    "T2": "Multi-tap vocabulary — child selects multiple matching images. Tone: clear instruction.",
    "T3": "Speak-the-word — child speaks a word aloud. Audio guides pronunciation. Tone: warm, patient.",
    "T5": "Odd-one-out — child finds the item that doesn't belong. Tone: playful challenge.",
    "F1": "Yes/No concept check — audio asks a question, child taps yes or no. Tone: conversational question.",
    "F2": "Comparison — audio compares two items. Tone: curious, exploratory.",
    "F3": "Visual contrast — child picks between contrasting images. Tone: encouraging.",
    "T7": "Multi-select category gate — child selects all items in a category. Tone: clear grouping instruction.",
    "T9": "Comprehension gate — verifies understanding before sentences. Tone: supportive check-in.",
    "D1": "Sentence builder — child arranges word tiles into a sentence. Tone: guided construction.",
    "T6.1": "Read-along sentence — audio reads, child follows. Tone: warm narration.",
    "T6.2": "Speak-the-sentence — child reads aloud. Tone: encouraging, patient.",
    "T6.3": "Sentence extension — builds on previous sentence. Tone: progressive, celebratory.",
}


def _collect_matrix_text(rows: List[dict], max_rows: int = 10) -> str:
    """Extract readable text from the matrix for the LLM judge."""
    lines = []
    for row in rows[:max_rows]:
        t = str(row.get("Template", ""))
        instruction = str(row.get("Instruction Text", ""))
        inst_vo = str(row.get("Instruction VO", ""))
        text_q = str(row.get("Text in Question", ""))
        stt = str(row.get("STT Expectation", ""))
        correct = str(row.get("Correct Answer", ""))
        options = str(row.get("Other Options", ""))
        notes = str(row.get("Notes", ""))
        parts = [f"[{t}]"]
        if not _is_empty(instruction):
            parts.append(f"Instruction: {instruction}")
        if not _is_empty(inst_vo):
            parts.append(f"VO: {inst_vo}")
        if not _is_empty(text_q):
            parts.append(f"Text: {text_q}")
        if not _is_empty(stt):
            parts.append(f"STT: {stt}")
        if not _is_empty(correct):
            parts.append(f"Answer: {correct}")
        if not _is_empty(options):
            parts.append(f"Options: {options}")
        if not _is_empty(notes):
            parts.append(f"Note: {notes}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def _run_llm_judge(
    rows: List[dict],
    expected: dict,
    theme: str,
    age: int,
) -> List[ScoreDimension]:
    """Lane 2: one consolidated LLM call scoring tone + relevance + safety."""

    matrix_text = _collect_matrix_text(rows)
    theme_concepts = expected.get("theme_concepts", [])
    forbidden_themes = expected.get("forbidden_themes", [])

    # Build template context so the judge understands what each row type is
    used_templates = set(str(r.get("Template", "")).strip() for r in rows)
    template_context = "\n".join(
        f"  - {t}: {_TEMPLATE_DESCRIPTIONS.get(t, 'Interactive exercise')}"
        for t in sorted(used_templates) if t in _TEMPLATE_DESCRIPTIONS
    )

    prompt = f"""You are an expert evaluator for SpeakX, a children's speaking-curriculum app (ages 3-8).
Score the following lesson content for a {age}-year-old on the theme "{theme}".

IMPORTANT CONTEXT — This is a structured lesson with different interaction types:
{template_context}

KEY EVALUATION RULES:
- Vocabulary templates (T4, T1, T2, T3, T5) are EXPECTED to show single words or short phrases in Instruction Text. This is by design — do NOT penalize them for being "simple" or "bare."
- Tone is carried primarily in the Instruction VO field, which is what the child hears spoken aloud.
- A lesson is warm if Instruction VO uses child-friendly language, encouragement, and natural phrasing.
- "Text in Question" is the actual content the child interacts with (sentences to read/speak). Check these for naturalness.
- Sentences (D1, T6.x) should sound natural when spoken aloud by a {age}-year-old.

CONTENT TO EVALUATE:
{matrix_text}

Score these THREE dimensions independently (0-10 each):

1. TONE QUALITY — Does the Instruction VO content sound like a warm, loving preschool teacher talking to a {age}-year-old?
   Evaluate ONLY the Instruction VO and Instruction Text fields:
   - Instruction VOs: warm, encouraging, child-friendly? (e.g., "Can you find the big red bus?" is great)
   - Single-word vocabulary rows (T4, T1): score on whether the word is age-appropriate and clearly spoken, NOT on warmth (these are flashcard-style by design)
   - Sentence rows (D1, T6.x): natural, fun, would a child enjoy saying this?
   - Overall: does the lesson FLOW feel engaging — building from words → concepts → sentences?
   - Score 8-10 if instruction VOs are warm and child-friendly. Score 5-7 if functional but dry. Score below 5 only if content feels robotic, scary, or confusing.

2. CONTENT RELEVANCE — Does the lesson teach vocabulary and concepts related to "{theme}"?
   - Theme concepts (semantic family, not exact strings): {json.dumps(theme_concepts) if theme_concepts else f'[words related to "{theme}"]'}
   - Score based on semantic coverage, NOT exact keyword matching.
   - A lesson about "family" using "mother" instead of "mom" is fully relevant.
   - Does the vocabulary build toward the theme meaningfully?

3. SAFETY — Is ALL content safe and appropriate for a {age}-year-old?
   - Prohibited categories: {json.dumps(forbidden_themes)}
   - Check for violence, fear, death, injury, dark themes, or emotionally distressing content.
   - Also check for words too advanced for age {age} (e.g., "carnivorous" for age 4).

Output ONLY raw JSON, no markdown:
{{"tone": {{"score": 0-10, "critique": "<one sentence>"}}, "relevance": {{"score": 0-10, "critique": "<one sentence>"}}, "safety": {{"score": 0-10, "issues": ["<issue1>", ...] or []}}}}"""

    try:
        import time as _time
        from app.core.llm import get_judge, invoke_with_limit
        from app.core.metrics import get_collector
        judge = get_judge()
        _t0 = _time.time()
        resp = invoke_with_limit(judge, [("user", prompt)])
        _elapsed = int((_time.time() - _t0) * 1000)

        # Record metrics
        _mc = get_collector()
        if _mc:
            _um = getattr(resp, 'usage_metadata', None) or {}
            _inp = _um.get('input_tokens', 0) if isinstance(_um, dict) else 0
            _out = _um.get('output_tokens', 0) if isinstance(_um, dict) else 0
            _rm = getattr(resp, 'response_metadata', None) or {}
            _model = _rm.get('model_name', '') or 'judge'
            _mc.record_llm_call(
                node="eval", role="eval_judge", model=str(_model),
                input_tokens=_inp, output_tokens=_out, latency_ms=_elapsed,
            )

        clean = resp.content.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean)

        tone_data = data.get("tone", {})
        relevance_data = data.get("relevance", {})
        safety_data = data.get("safety", {})

        tone_score = min(tone_data.get("score", 5) / 10.0, 1.0)
        relevance_score = min(relevance_data.get("score", 5) / 10.0, 1.0)
        safety_score = min(safety_data.get("score", 5) / 10.0, 1.0)

        tone_critique = tone_data.get("critique", "")
        relevance_critique = relevance_data.get("critique", "")
        safety_issues = safety_data.get("issues", [])

        return [
            ScoreDimension(
                name="tone_quality", score=tone_score, max_score=1.0,
                weight=0.15, lane="llm",
                passed=int(tone_score * 10), total=10,
                issues=[tone_critique] if tone_critique and tone_score < 0.7 else [],
                detail=f"LLM tone: {tone_score:.0%} — {tone_critique[:120]}",
            ),
            ScoreDimension(
                name="content_relevance", score=relevance_score, max_score=1.0,
                weight=0.10, lane="llm",
                passed=int(relevance_score * 10), total=10,
                issues=[relevance_critique] if relevance_critique and relevance_score < 0.7 else [],
                detail=f"LLM relevance: {relevance_score:.0%} — {relevance_critique[:120]}",
            ),
            ScoreDimension(
                name="safety_semantic", score=safety_score, max_score=1.0,
                weight=0.05, lane="llm",
                passed=int(safety_score * 10), total=10,
                issues=safety_issues[:3],
                detail=f"LLM safety: {safety_score:.0%}" + (
                    f" — {len(safety_issues)} issue(s)" if safety_issues else " — clean"
                ),
            ),
        ]

    except Exception as e:
        log.warning("LLM judge call failed, using heuristic fallback: %s", e)
        return _llm_fallback_heuristic(rows, expected, theme)


def _llm_fallback_heuristic(
    rows: List[dict], expected: dict, theme: str,
) -> List[ScoreDimension]:
    """Fallback when LLM is unavailable — simple heuristics."""
    all_text = " ".join(
        " ".join(str(row.get(c, "")) for c in
                 ["Instruction Text", "Instruction VO", "Text in Question",
                  "Correct Answer", "Other Options"])
        for row in rows
    ).lower()

    # Tone heuristic: warm words, questions, exclamations
    warm_words = ["let's", "can you", "great", "wow", "yay", "fun",
                  "look", "find", "say", "listen", "ready", "good job"]
    warm_count = sum(1 for w in warm_words if w in all_text)
    tone_score = min((warm_count / 5 + (0.2 if "?" in all_text else 0)
                      + (0.1 if "!" in all_text else 0)), 1.0)

    # Relevance heuristic: exact keyword match with partial credit
    theme_concepts = expected.get("theme_concepts", [])
    if theme_concepts:
        found = sum(1 for kw in theme_concepts if kw.lower() in all_text)
        relevance_score = min(found / max(len(theme_concepts) * 0.4, 1), 1.0)
    else:
        relevance_score = 0.5 if theme.lower() in all_text else 0.3

    return [
        ScoreDimension(
            name="tone_quality", score=tone_score, max_score=1.0,
            weight=0.15, lane="heuristic",
            passed=warm_count, total=len(warm_words),
            detail=f"Heuristic tone: {tone_score:.0%} (LLM unavailable)",
        ),
        ScoreDimension(
            name="content_relevance", score=relevance_score, max_score=1.0,
            weight=0.10, lane="heuristic",
            detail=f"Heuristic relevance: {relevance_score:.0%} (LLM unavailable)",
        ),
        ScoreDimension(
            name="safety_semantic", score=0.5, max_score=1.0,
            weight=0.05, lane="heuristic",
            detail="Skipped (LLM unavailable) — relying on lexical gate only",
        ),
    ]


# ───────────────────────────────────────────────────────────────
# Aggregate scorer — combines both lanes
# ───────────────────────────────────────────────────────────────

def score_run(
    case_id: str,
    theme: str,
    age: int,
    matrix_rows: List[dict],
    expected: dict,
    use_llm_tone: bool = True,
) -> EvalScore:
    """Run both lanes and compute weighted total.

    Lane 1 (deterministic) always runs.
    Lane 2 (LLM) runs if use_llm_tone=True, otherwise uses heuristic fallback.
    """
    if not matrix_rows:
        return EvalScore(
            case_id=case_id, theme=theme, age=age,
            total_score=0.0, grade="F", row_count=0,
            error="Pipeline produced no matrix rows.",
        )

    # Lane 1: deterministic (instant, free)
    dimensions = _run_deterministic(matrix_rows, expected)

    # Lane 2: LLM-as-a-Judge (1 call) or heuristic fallback
    llm_calls = 0
    if use_llm_tone:
        llm_dims = _run_llm_judge(matrix_rows, expected, theme, age)
        llm_calls = 1 if any(d.lane == "llm" for d in llm_dims) else 0
    else:
        llm_dims = _llm_fallback_heuristic(matrix_rows, expected, theme)
    dimensions.extend(llm_dims)

    # Weighted total (0–100)
    total_weight = sum(d.weight for d in dimensions) or 1.0
    weighted = sum(d.score * d.weight for d in dimensions)
    total_score = round((weighted / total_weight) * 100, 1)

    # Grade
    if total_score >= 90:
        grade = "A"
    elif total_score >= 80:
        grade = "B"
    elif total_score >= 65:
        grade = "C"
    elif total_score >= 50:
        grade = "D"
    else:
        grade = "F"

    return EvalScore(
        case_id=case_id, theme=theme, age=age,
        total_score=total_score, grade=grade,
        dimensions=dimensions, row_count=len(matrix_rows),
        llm_calls=llm_calls,
    )
