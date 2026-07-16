"""
Central runtime configuration.

Everything the admin panel manages lives here as a single in-memory object.
The admin endpoints read and mutate `CONFIG` at runtime, so you can change a
prompt or swap a model mid-demo without restarting the server. Values seed from
environment variables on boot; edits are session-scoped (not persisted to disk).
"""
import os
from dataclasses import dataclass, field, asdict
from typing import Optional
from dotenv import load_dotenv

# Load .env from the backend root (two levels up from this file)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))


@dataclass
class ModelConfig:
    # Text generator (blueprint + question matrix)
    generator_provider: str = "google"
    generator_model: str = "gemini-2.5-flash"
    generator_temperature: float = 0.2

    # Blueprint quality judge — same family as the generator for now.
    # Swap provider to "anthropic" or "openai" if you have those keys.
    judge_provider: str = "google"
    judge_model: str = "gemini-2.5-flash"
    judge_temperature: float = 0.0


@dataclass
class ApiKeys:
    google: Optional[str] = field(default_factory=lambda: os.getenv("GOOGLE_API_KEY"))
    anthropic: Optional[str] = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY"))
    openai: Optional[str] = field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    # Vertex AI (used when google api key is not set)
    gcp_project: Optional[str] = field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_PROJECT"))
    gcp_location: str = field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"))

    def masked(self) -> dict:
        """Return keys with all but the last 4 chars hidden, for the admin UI."""
        def mask(v):
            if not v:
                return None
            return ("•" * max(0, len(v) - 4)) + v[-4:]
        return {"google": mask(self.google), "anthropic": mask(self.anthropic),
                "openai": mask(self.openai)}


# ---------------------------------------------------------------------------
# Prompts — editable from the admin panel
# ---------------------------------------------------------------------------

# Load the full SpeakX framework from skill_v6.md
_SKILL_FILE = os.path.join(os.path.dirname(__file__), "skill_v6.md")
try:
    with open(_SKILL_FILE, "r") as _f:
        _SKILL_V6_CONTENT = _f.read()
except FileNotFoundError:
    _SKILL_V6_CONTENT = ""

DEFAULT_GENERATOR_SYSTEM = f"""You are an early-childhood speaking-curriculum
designer for the Zuno SpeakX framework (ages 3-8). Follow the SpeakX pedagogical
ladder and template definitions EXACTLY as defined below. Produce warm, spoken,
preschool-teacher tone. Never use academic or sterile phrasing. Keep all content
child-safe.

{_SKILL_V6_CONTENT}"""

DEFAULT_BLUEPRINT_JUDGE_SYSTEM = """You are a Lead QA Engineer and Pediatric
Neuro-Linguist specialized in early language acquisition for children ages 3-8.
Audit the generated LESSON BLUEPRINT against the SpeakX framework.

Evaluate:
1. PRESCHOOL TEACHER SPOKEN TONE — warm, engaging, age-appropriate; catch any
   sterile dictionary definitions.
2. PEDAGOGICAL STAIRCASE — does difficulty climb naturally (F1 -> F2 -> F3 -> T7)?
3. ANTONYM / NEGATION INTERFERENCE — no competing binary opposites.
4. CONTENT SAFETY — absolutely no scary/dark/violent words.

IMPORTANT — audit exhaustively in ONE pass: the generator gets a limited number
of repair attempts, so your critique MUST list EVERY issue you can find in this
draft (numbered), not just the first one. Never hold an issue back for a later
review. FAIL only on clear violations of the four criteria above — do not fail
for stylistic preferences or hypothetical improvements.

Output ONLY raw JSON, no markdown:
{"verdict": "PASS" | "FAIL", "critique": "<numbered list of ALL issues + technical fix instructions if FAIL>"}"""

DEFAULT_MATRIX_COLUMNS = [
    # Group 1: Identity & Instruction
    "Playable Code",
    "Playable Name",
    "Layer",
    "Template",
    "Instruction Text",
    "Instruction VO",
    "Instruction VO — File",
    # Group 2: Question
    "Text in Question",
    "Audio in Question",
    "Audio in Question — File",
    "VO for Question",
    "VO for Question — File",
    "Image in Question — Detail",
    "Image in Question — Name",
    # Group 3: Answer
    "Correct Answer",
    "Correct Answer VO — File",
    "Correct Answer — Image",
    "Correct Answer — Image Detail",
    "Other Options",
    "Other Options VO — File",
    "Other Options — Image",
    "Other Options — Image Detail",
    # Group 4: Speech
    "STT Expectation",
    # Group 5: Meta
    "Concept (bucket / skill)",
    "Pattern",
    "Notes",
]

# Per-template column requirements from the Required Matrix.
# Yes = always required, No = must be '—'.
# Identity columns (Playable Code/Name, Layer, Template) + Meta (Concept, Pattern, Notes)
# are always Yes for all templates and omitted from this dict.
# File-name columns mirror their parent content column automatically.
TEMPLATE_COLUMN_RULES: dict[str, dict[str, str]] = {
    "T4": {
        "Instruction Text": "Yes", "Instruction VO": "Yes",
        "Text in Question": "Yes", "Audio in Question": "Yes",
        "VO for Question": "Yes",
        "Image in Question — Detail": "Yes", "Image in Question — Name": "Yes",
        "Correct Answer": "No", "Correct Answer — Image": "No", "Correct Answer — Image Detail": "No",
        "Other Options": "No", "Other Options — Image": "No", "Other Options — Image Detail": "No",
        "STT Expectation": "No",
    },
    "T1": {
        "Instruction Text": "Yes", "Instruction VO": "Yes",
        "Text in Question": "No", "Audio in Question": "Yes",
        "VO for Question": "Yes",
        "Image in Question — Detail": "No", "Image in Question — Name": "No",
        "Correct Answer": "Yes", "Correct Answer — Image": "Yes", "Correct Answer — Image Detail": "Yes",
        "Other Options": "Yes", "Other Options — Image": "Yes", "Other Options — Image Detail": "Yes",
        "STT Expectation": "No",
    },
    "T2": {
        "Instruction Text": "Yes", "Instruction VO": "Yes",
        "Text in Question": "No", "Audio in Question": "Yes",
        "VO for Question": "Yes",
        "Image in Question — Detail": "No", "Image in Question — Name": "No",
        "Correct Answer": "Yes", "Correct Answer — Image": "No", "Correct Answer — Image Detail": "No",
        "Other Options": "Yes", "Other Options — Image": "No", "Other Options — Image Detail": "No",
        "STT Expectation": "No",
    },
    "T3": {
        "Instruction Text": "Yes", "Instruction VO": "Yes",
        "Text in Question": "Yes", "Audio in Question": "Yes",
        "VO for Question": "Yes",
        "Image in Question — Detail": "Yes", "Image in Question — Name": "Yes",
        "Correct Answer": "No", "Correct Answer — Image": "No", "Correct Answer — Image Detail": "No",
        "Other Options": "No", "Other Options — Image": "No", "Other Options — Image Detail": "No",
        "STT Expectation": "Yes",
    },
    "T5": {
        "Instruction Text": "Yes", "Instruction VO": "Yes",
        "Text in Question": "Yes", "Audio in Question": "No",
        "VO for Question": "Yes",
        "Image in Question — Detail": "Yes", "Image in Question — Name": "Yes",
        "Correct Answer": "Yes", "Correct Answer — Image": "No", "Correct Answer — Image Detail": "No",
        "Other Options": "Yes", "Other Options — Image": "No", "Other Options — Image Detail": "No",
        "STT Expectation": "No",
    },
    "F1": {
        "Instruction Text": "Yes", "Instruction VO": "Yes",
        "Text in Question": "Yes", "Audio in Question": "No",
        "VO for Question": "Yes",
        "Image in Question — Detail": "Yes", "Image in Question — Name": "Yes",
        "Correct Answer": "Yes", "Correct Answer — Image": "No", "Correct Answer — Image Detail": "No",
        "Other Options": "Yes", "Other Options — Image": "No", "Other Options — Image Detail": "No",
        "STT Expectation": "No",
    },
    "F2": {
        "Instruction Text": "Yes", "Instruction VO": "Yes",
        "Text in Question": "Yes", "Audio in Question": "No",
        "VO for Question": "Yes",
        "Image in Question — Detail": "No", "Image in Question — Name": "No",
        "Correct Answer": "Yes", "Correct Answer — Image": "Yes", "Correct Answer — Image Detail": "Yes",
        "Other Options": "Yes", "Other Options — Image": "Yes", "Other Options — Image Detail": "Yes",
        "STT Expectation": "No",
    },
    "F3": {
        "Instruction Text": "Yes", "Instruction VO": "Yes",
        "Text in Question": "Yes", "Audio in Question": "No",
        "VO for Question": "Yes",
        "Image in Question — Detail": "No", "Image in Question — Name": "No",
        "Correct Answer": "Yes", "Correct Answer — Image": "Yes", "Correct Answer — Image Detail": "Yes",
        "Other Options": "Yes", "Other Options — Image": "Yes", "Other Options — Image Detail": "Yes",
        "STT Expectation": "No",
    },
    "T7": {
        "Instruction Text": "Yes", "Instruction VO": "Yes",
        "Text in Question": "No", "Audio in Question": "No",
        "VO for Question": "No",
        "Image in Question — Detail": "No", "Image in Question — Name": "No",
        "Correct Answer": "Yes", "Correct Answer — Image": "Yes", "Correct Answer — Image Detail": "Yes",
        "Other Options": "Yes", "Other Options — Image": "Yes", "Other Options — Image Detail": "Yes",
        "STT Expectation": "No",
    },
    "T7.1": {
        "Instruction Text": "Yes", "Instruction VO": "Yes",
        "Text in Question": "Yes", "Audio in Question": "No",
        "VO for Question": "Yes",
        "Image in Question — Detail": "Yes", "Image in Question — Name": "Yes",
        "Correct Answer": "Yes", "Correct Answer — Image": "No", "Correct Answer — Image Detail": "No",
        "Other Options": "Yes", "Other Options — Image": "No", "Other Options — Image Detail": "No",
        "STT Expectation": "No",
    },
    "T9": {
        "Instruction Text": "Yes", "Instruction VO": "Yes",
        "Text in Question": "No", "Audio in Question": "Yes",
        "VO for Question": "No",
        "Image in Question — Detail": "No", "Image in Question — Name": "No",
        "Correct Answer": "Yes", "Correct Answer — Image": "Yes", "Correct Answer — Image Detail": "Yes",
        "Other Options": "Yes", "Other Options — Image": "Yes", "Other Options — Image Detail": "Yes",
        "STT Expectation": "No",
    },
    "D1": {
        "Instruction Text": "Yes", "Instruction VO": "Yes",
        "Text in Question": "No", "Audio in Question": "Yes",
        "VO for Question": "No",
        "Image in Question — Detail": "No", "Image in Question — Name": "No",
        "Correct Answer": "Yes", "Correct Answer — Image": "No", "Correct Answer — Image Detail": "No",
        "Other Options": "Yes", "Other Options — Image": "No", "Other Options — Image Detail": "No",
        "STT Expectation": "No",
    },
    "T6.1": {
        "Instruction Text": "Yes", "Instruction VO": "Yes",
        "Text in Question": "Yes", "Audio in Question": "No",
        "VO for Question": "Yes",
        "Image in Question — Detail": "Yes", "Image in Question — Name": "Yes",
        "Correct Answer": "Yes", "Correct Answer — Image": "No", "Correct Answer — Image Detail": "No",
        "Other Options": "Yes", "Other Options — Image": "No", "Other Options — Image Detail": "No",
        "STT Expectation": "No",
    },
    "T6.2": {
        "Instruction Text": "Yes", "Instruction VO": "Yes",
        "Text in Question": "Yes", "Audio in Question": "No",
        "VO for Question": "Yes",
        "Image in Question — Detail": "Yes", "Image in Question — Name": "Yes",
        "Correct Answer": "Yes", "Correct Answer — Image": "No", "Correct Answer — Image Detail": "No",
        "Other Options": "No", "Other Options — Image": "No", "Other Options — Image Detail": "No",
        "STT Expectation": "Yes",
    },
    "T6.3": {
        "Instruction Text": "Yes", "Instruction VO": "Yes",
        "Text in Question": "Yes", "Audio in Question": "No",
        "VO for Question": "Yes",
        "Image in Question — Detail": "Yes", "Image in Question — Name": "Yes",
        "Correct Answer": "Yes", "Correct Answer — Image": "No", "Correct Answer — Image Detail": "No",
        "Other Options": "No", "Other Options — Image": "No", "Other Options — Image Detail": "No",
        "STT Expectation": "Yes",
    },
    "T8": {
        "Instruction Text": "Yes", "Instruction VO": "Yes",
        "Text in Question": "Yes", "Audio in Question": "No",
        "VO for Question": "Yes",
        "Image in Question — Detail": "Yes", "Image in Question — Name": "Yes",
        "Correct Answer": "No", "Correct Answer — Image": "No", "Correct Answer — Image Detail": "No",
        "Other Options": "No", "Other Options — Image": "No", "Other Options — Image Detail": "No",
        "STT Expectation": "Yes",
    },
    "T8.2": {
        "Instruction Text": "Yes", "Instruction VO": "Yes",
        "Text in Question": "No", "Audio in Question": "No",
        "VO for Question": "No",
        "Image in Question — Detail": "Yes", "Image in Question — Name": "Yes",
        "Correct Answer": "No", "Correct Answer — Image": "No", "Correct Answer — Image Detail": "No",
        "Other Options": "No", "Other Options — Image": "No", "Other Options — Image Detail": "No",
        "STT Expectation": "Yes",
    },
    "C1": {
        "Instruction Text": "Yes", "Instruction VO": "Yes",
        "Text in Question": "No", "Audio in Question": "No",
        "VO for Question": "No",
        "Image in Question — Detail": "Yes", "Image in Question — Name": "Yes",
        "Correct Answer": "No", "Correct Answer — Image": "No", "Correct Answer — Image Detail": "No",
        "Other Options": "No", "Other Options — Image": "No", "Other Options — Image Detail": "No",
        "STT Expectation": "Yes",
    },
}

DEFAULT_AGE_GUIDELINES = {
    3: {
        "max_words_per_sentence": 4,
        "vocabulary_level": "basic sight words, single-syllable nouns, no formal/academic terms",
        "text_complexity": "2–4 word sentences only",
        "tone": "very playful, sing-song, lots of repetition",
        "stt_expectation": "single word only",
        "allowed_templates": ["T4", "T1", "T3", "F1", "F2", "F3", "T9", "D1", "T6.1", "T6.2", "T8", "T8.2", "C1"],
        "forbidden_templates": ["T2", "T5", "T7", "T7.1", "T6.3"],
        "vocab_gate": "T4 -> T1 -> T3 (no T5)",
        "concept_gate": "F1 -> F2 -> F3 (no T7)",
        "sentence_gate": "T9 (yes/no only) -> D1 (tap_to_place) -> T6.1 (with images) -> T6.2 -> T8 -> T8.2",
        "forbidden_structures": "no 'because', no complex clauses",
        "notes": "No reading expected. All audio+image. D1 uses tap_to_place. T9 must use confirming yes/no only. C1 accepts single-word responses.",
    },
    4: {
        "max_words_per_sentence": 6,
        "vocabulary_level": "common nouns, basic verbs, primary colours, no formal/academic terms",
        "text_complexity": "4–6 word sentences",
        "tone": "warm, encouraging, gentle repetition",
        "stt_expectation": "1–2 words",
        "allowed_templates": ["T4", "T1", "T3", "F1", "F2", "F3", "T7", "T7.1", "T9", "D1", "T6.1", "T6.2", "T6.3", "T8", "T8.2", "C1"],
        "forbidden_templates": ["T2", "T5"],
        "vocab_gate": "T4 -> T1 -> T3 (no T5)",
        "concept_gate": "F1 -> F2 -> F3 -> T7 -> T7.1",
        "sentence_gate": "T9 (wh- questions + image choices) -> D1 (drag_and_drop) -> T6.1 -> T6.2 -> T6.3 (2 blanks) -> T8 -> T8.2",
        "forbidden_structures": "no 'if-then', limited connectors",
        "notes": "Minimal on-screen text. T9 uses wh-extraction with image-only choices. T6.3 max 2 blanks.",
    },
    5: {
        "max_words_per_sentence": 10,
        "vocabulary_level": "everyday nouns, action verbs, adjectives, prepositions. No formal words (carnivorous, mammal, etc.)",
        "text_complexity": "6–10 word sentences",
        "tone": "enthusiastic preschool teacher, uses questions",
        "stt_expectation": "2–3 word phrases",
        "allowed_templates": ["T4", "T1", "T2", "T3", "T5", "F1", "F2", "F3", "T7", "T7.1", "T9", "D1", "T6.1", "T6.2", "T6.3", "T8", "T8.2", "C1"],
        "forbidden_templates": [],
        "vocab_gate": "T4 -> T1 (3 exposures) -> T2 (short words) -> T3 -> T5 (age-appropriate text)",
        "concept_gate": "F1 -> F2 (comparative adj) -> F3 -> T7 -> T7.1",
        "sentence_gate": "T9 (wh- questions + text choices) -> D1 -> T6.1 -> T6.2 -> T6.3 (2–3 blanks) -> T8 -> T8.2",
        "forbidden_structures": "none",
        "notes": "First age with T2 and T5. T5 meanings must sound like a preschool teacher, not dictionary. Short on-screen labels OK.",
    },
    6: {
        "max_words_per_sentence": 12,
        "vocabulary_level": "expanded vocabulary, synonyms, comparative/superlative adjectives",
        "text_complexity": "8–12 word sentences, compound structures OK",
        "tone": "supportive, slightly more instructional",
        "stt_expectation": "short sentences",
        "allowed_templates": ["T4", "T2", "T3", "T5", "F1", "F2", "F3", "T7", "T7.1", "T9", "D1", "T6.1", "T6.2", "T6.3", "T8", "T8.2", "C1"],
        "forbidden_templates": [],
        "vocab_gate": "T4 -> T2 (default over T1) -> T3 -> T5",
        "concept_gate": "F1 -> F2 -> F3 -> T7 -> T7.1",
        "sentence_gate": "T9 -> D1 -> T6.1 -> T6.2 -> T6.3 (3–4 blanks, scale up) -> T8 -> T8.2",
        "forbidden_structures": "none",
        "notes": "T2 is default over T1. T6.3 scales to 3–4 blanks. Beginning reader.",
    },
    7: {
        "max_words_per_sentence": 18,
        "vocabulary_level": "rich vocabulary, descriptive language, cause-effect words, time words",
        "text_complexity": "12–18 word sentences, multi-clause OK",
        "tone": "encouraging, more conversational",
        "stt_expectation": "full sentences with correct grammar",
        "allowed_templates": ["T4", "T2", "T3", "T5", "F1", "F2", "F3", "T7", "T7.1", "T9", "D1", "T6.1", "T6.2", "T6.3", "T8", "T8.2", "C1"],
        "forbidden_templates": [],
        "vocab_gate": "T4 -> T2 (default over T1) -> T3 -> T5",
        "concept_gate": "F1 -> F2 -> F3 -> T7 -> T7.1",
        "sentence_gate": "T9 -> D1 -> T6.1 -> T6.2 -> T6.3 (3–4 blanks, scale up) -> T8 -> T8.2",
        "forbidden_structures": "none",
        "notes": "T6.3 must scale incrementally (2-blank first, then 3-4 blank). Can read short paragraphs.",
    },
}


@dataclass
class OutputConfig:
    matrix_columns: list = field(default_factory=lambda: list(DEFAULT_MATRIX_COLUMNS))
    age_guidelines: dict = field(default_factory=lambda: {k: dict(v) for k, v in DEFAULT_AGE_GUIDELINES.items()})


@dataclass
class Prompts:
    generator_system: str = DEFAULT_GENERATOR_SYSTEM
    blueprint_judge_system: str = DEFAULT_BLUEPRINT_JUDGE_SYSTEM


@dataclass
class RuntimeConfig:
    models: ModelConfig = field(default_factory=ModelConfig)
    keys: ApiKeys = field(default_factory=ApiKeys)
    prompts: Prompts = field(default_factory=Prompts)
    output: OutputConfig = field(default_factory=OutputConfig)

    # Caps (system decides count, these are upper bounds)
    max_questions: int = 100
    max_images: int = 100
    max_retries: int = 5

    # Hard stop: max full pipeline runs allowed per (UTC) day. Editable in admin.
    max_runs_per_day: int = 10

    def public_dict(self) -> dict:
        """Serializable view for the admin UI (keys masked)."""
        return {
            "models": asdict(self.models),
            "keys": self.keys.masked(),
            "prompts": asdict(self.prompts),
            "output": {
                "matrix_columns": self.output.matrix_columns,
                "age_guidelines": {str(k): v for k, v in self.output.age_guidelines.items()},
            },
            "limits": {"max_questions": self.max_questions,
                       "max_images": self.max_images,
                       "max_retries": self.max_retries,
                       "max_runs_per_day": self.max_runs_per_day},
        }


# The single global config object the whole app reads from.
CONFIG = RuntimeConfig()

# Admin password (set ADMIN_PASSWORD in env; defaults to a demo value)
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "zuno-demo")

# Path to the .env file so we can persist key changes across restarts.
_ENV_FILE = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
_ENV_FILE = os.path.normpath(_ENV_FILE)

_KEY_TO_ENV_VAR = {
    "google": "GOOGLE_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def persist_keys_to_env(keys: dict) -> None:
    """Write non-empty key values back to the .env file on disk."""
    if not keys:
        return

    # Read existing lines
    try:
        with open(_ENV_FILE, "r") as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []

    for provider, value in keys.items():
        if not value:
            continue
        env_var = _KEY_TO_ENV_VAR.get(provider)
        if not env_var:
            continue

        # Replace existing line or append
        replaced = False
        for i, line in enumerate(lines):
            if line.startswith(f"{env_var}=") or line.startswith(f"# {env_var}="):
                lines[i] = f"{env_var}={value}\n"
                replaced = True
                break
        if not replaced:
            lines.append(f"{env_var}={value}\n")

    with open(_ENV_FILE, "w") as f:
        f.writelines(lines)
