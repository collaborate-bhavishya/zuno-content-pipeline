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
from app.core.config import CONFIG


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
