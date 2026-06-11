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
"""
import time
import logging
from app.core.config import CONFIG

_img_log = logging.getLogger("pipeline")


def _is_rate_limit(exc: Exception) -> bool:
    s = str(exc).lower()
    return "429" in s or "resource_exhausted" in s or "quota" in s


# ── Adaptive image pacer ──────────────────────────────────────────────
# A module-level cooldown timestamp. After a 429 we "trip" it forward; before
# every image send we wait for it to clear. This is the check-before-send the
# pipeline uses to pace sequential image generation under a low quota.
_image_cooldown_until: float = 0.0


def image_cooldown_remaining() -> float:
    """Seconds left on the current 429 cooldown (0 if clear)."""
    return max(0.0, _image_cooldown_until - time.time())


def _image_wait_if_cooling():
    """Block until any active 429 cooldown clears — only send when quota is free."""
    remaining = image_cooldown_remaining()
    if remaining > 0:
        _img_log.info("Image pacer: in quota cooldown, waiting %.1fs before next send", remaining)
        time.sleep(remaining)


def _image_trip_cooldown(seconds: float):
    global _image_cooldown_until
    _image_cooldown_until = max(_image_cooldown_until, time.time() + seconds)


def _build(provider: str, model: str, temperature: float):
    if provider == "google":
        if CONFIG.keys.google:
            # API key path (AI Studio key)
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(
                model=model,
                temperature=temperature,
                google_api_key=CONFIG.keys.google,
            )
        else:
            # ADC path — uses GCP free credits via Vertex AI
            from langchain_google_vertexai import ChatVertexAI
            return ChatVertexAI(
                model_name=model,
                temperature=temperature,
                project=CONFIG.keys.gcp_project,
                location=CONFIG.keys.gcp_location,
            )
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model, temperature=temperature,
            anthropic_api_key=CONFIG.keys.anthropic,
        )
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model, temperature=temperature,
            openai_api_key=CONFIG.keys.openai,
        )
    if provider == "bedrock":
        # Amazon Bedrock via the Converse API (required by Nova models).
        # Auth priority:
        #   1. Bedrock API key (bearer token) -> AWS_BEARER_TOKEN_BEDROCK
        #   2. Explicit access-key/secret in CONFIG
        #   3. Standard AWS chain (~/.aws/credentials, IAM role, etc.)
        import os as _os
        from langchain_aws import ChatBedrockConverse
        import boto3
        k = CONFIG.keys
        # botocore reads the bearer token from this env var automatically.
        if k.aws_bedrock_token:
            _os.environ["AWS_BEARER_TOKEN_BEDROCK"] = k.aws_bedrock_token
        session_kwargs = {"region_name": k.aws_region}
        if k.aws_access_key_id and k.aws_secret_access_key:
            session_kwargs["aws_access_key_id"] = k.aws_access_key_id
            session_kwargs["aws_secret_access_key"] = k.aws_secret_access_key
            if k.aws_session_token:
                session_kwargs["aws_session_token"] = k.aws_session_token
        client = boto3.Session(**session_kwargs).client("bedrock-runtime")
        return ChatBedrockConverse(
            model=model,
            temperature=temperature,
            client=client,
        )
    raise ValueError(f"Unknown provider: {provider}")


def get_generator():
    m = CONFIG.models
    return _build(m.generator_provider, m.generator_model, m.generator_temperature)


def get_judge():
    m = CONFIG.models
    return _build(m.judge_provider, m.judge_model, m.judge_temperature)


def get_vision_judge():
    m = CONFIG.models
    return _build(m.vision_provider, m.vision_model, m.vision_temperature)


def get_image_client():
    """Image generation via the google-genai SDK (separate from langchain)."""
    from google.genai import Client
    if CONFIG.keys.google:
        return Client(api_key=CONFIG.keys.google)
    # ADC path — Vertex AI with GCP free credits
    return Client(
        vertexai=True,
        project=CONFIG.keys.gcp_project,
        location=CONFIG.keys.gcp_location,
    )


def _render_once(prompt: str) -> bytes:
    """Single image-generation call, dispatched by model family."""
    from google.genai import types
    client = get_image_client()
    model = CONFIG.models.image_model

    if model.startswith("imagen"):
        result = client.models.generate_images(
            model=model, prompt=prompt,
            config=dict(number_of_images=1, output_mime_type="image/png",
                        aspect_ratio="1:1"),
        )
        if not result.generated_images:
            return b""
        return result.generated_images[0].image.image_bytes

    # Gemini-native image generation (e.g. gemini-2.5-flash-image)
    result = client.models.generate_content(
        model=model, contents=prompt,
        config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
    )
    for cand in (result.candidates or []):
        for part in (cand.content.parts or []):
            inline = getattr(part, "inline_data", None)
            if inline and inline.data:
                return inline.data
    return b""


def render_image_bytes(prompt: str, max_attempts: int = 4) -> bytes:
    """Generate one PNG image and return its raw bytes, with backoff-retry.

    Model-agnostic ('imagen-*' or 'gemini-*'). A 429 on Vertex AI is usually a
    *per-minute* rate limit, not a hard cap — so we wait and retry (like rerunning
    a Colab cell) before surfacing the error. Only a persistent 429 (e.g. a real
    daily/project cap) propagates, letting the caller defer the asset.
    """
    last_exc = None
    for attempt in range(max_attempts):
        _image_wait_if_cooling()   # check-before-send: wait out any 429 cooldown
        try:
            return _render_once(prompt)
        except Exception as e:
            last_exc = e
            if _is_rate_limit(e) and attempt < max_attempts - 1:
                wait = CONFIG.image_backoff_base_s * (attempt + 1)
                _image_trip_cooldown(wait)   # so the NEXT send paces itself too
                _img_log.warning(
                    "Image rate-limited (429) — cooldown %ds, retry %d/%d",
                    wait, attempt + 1, max_attempts - 1)
                continue
            raise
    raise last_exc
