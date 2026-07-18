"""
Builds LLM clients from the runtime CONFIG. Because clients are constructed
on demand from CONFIG, the admin panel can swap a model or provider mid-session
and the very next graph run uses the new settings.

Cross-family judging (e.g. Gemini generator + Claude judge) is supported by
setting judge_provider in the admin panel. The relevant langchain package must
be installed and the matching API key present.

Auth priority for Google:
  1. GOOGLE_API_KEY in .env / admin panel  -> API key auth
  2. No key set                            -> ADC (gcloud auth application-default login)

Rate limiting
-------------
Vertex's default gemini-2.5-flash quota is ~10 requests/minute (measured with
probe_rate.py). A lesson fires calls back-to-back, so without pacing it trips a
429 within ~10 calls. Two defenses, both here:

  * _rate_gate(): a process-wide minimum interval between the START of any two
    LLM calls (CONFIG.llm_min_interval_s). Spacing calls ~7s apart keeps us at
    ~8.5/min, safely under the ceiling — this alone should prevent 429s.
  * invoke_with_limit(): if one slips through anyway, sleep long enough to clear
    the per-minute window and retry, instead of the library's blind 4s retries
    (which hammer the API DURING the cooldown and waste quota — so we disable
    those with max_retries=0 on the client).
"""
import logging
import threading
import time

from app.core.config import CONFIG

log = logging.getLogger("pipeline")

_gate_lock = threading.Lock()
_last_call_ts = 0.0


def _rate_gate():
    """Block until at least CONFIG.llm_min_interval_s has passed since the last
    call started. Serializes call *starts* across the whole process."""
    global _last_call_ts
    interval = getattr(CONFIG, "llm_min_interval_s", 7.0)
    with _gate_lock:
        wait = _last_call_ts + interval - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_call_ts = time.time()


def _is_429(exc: Exception) -> bool:
    s = str(exc).lower()
    return "429" in s or "resource_exhausted" in s or "quota" in s


def invoke_with_limit(llm, messages):
    """Rate-gated llm.invoke with proper per-minute 429 backoff. Use this for
    EVERY text LLM call so pacing is enforced in one place."""
    attempts = getattr(CONFIG, "llm_max_429_retries", 4)
    backoff = getattr(CONFIG, "llm_429_backoff_s", 35)
    for attempt in range(1, attempts + 1):
        _rate_gate()
        try:
            return llm.invoke(messages)
        except Exception as e:
            if _is_429(e) and attempt < attempts:
                wait = backoff * attempt   # 35, 70, 105… — long enough to clear the window
                log.warning("LLM 429 (attempt %d/%d) — sleeping %ds to clear the rate window",
                            attempt, attempts, wait)
                time.sleep(wait)
                continue
            raise


def _build(provider: str, model: str, temperature: float):
    if provider == "google":
        if CONFIG.keys.google:
            # API key path (AI Studio key)
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(
                model=model,
                temperature=temperature,
                google_api_key=CONFIG.keys.google,
                max_retries=0,   # we do our own paced backoff in invoke_with_limit
            )
        else:
            # ADC path — uses GCP free credits via Vertex AI
            from langchain_google_vertexai import ChatVertexAI
            return ChatVertexAI(
                model_name=model,
                temperature=temperature,
                project=CONFIG.keys.gcp_project,
                location=CONFIG.keys.gcp_location,
                max_retries=0,   # disable blind 4s retries that hammer during cooldown
            )
    if provider == "anthropic":
        # Requires: pip install langchain-anthropic (optional, see requirements.txt)
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model, temperature=temperature,
            anthropic_api_key=CONFIG.keys.anthropic,
        )
    if provider == "openai":
        # Requires: pip install langchain-openai (optional, see requirements.txt)
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model, temperature=temperature,
            openai_api_key=CONFIG.keys.openai,
        )
    raise ValueError(f"Unknown provider: {provider}")


def get_generator():
    m = CONFIG.models
    return _build(m.generator_provider, m.generator_model, m.generator_temperature)


def get_judge():
    m = CONFIG.models
    return _build(m.judge_provider, m.judge_model, m.judge_temperature)
