from __future__ import annotations

from app.config import Settings
from app.providers.base import LLMProvider
from app.providers.gemini import GeminiProvider
from app.providers.mistral import MistralProvider
from app.providers.openai_gpt import OpenAIGPTProvider

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
    "mistral": "mistral-small-latest",
}

MODEL_OPTIONS: dict[str, list[dict[str, str]]] = {
    "openai": [
        {"id": "gpt-4o-mini", "label": "gpt-4o-mini — rýchly / lacný"},
        {"id": "gpt-4o", "label": "gpt-4o — silnejší"},
        {"id": "gpt-4.1-mini", "label": "gpt-4.1-mini"},
        {"id": "gpt-4.1", "label": "gpt-4.1"},
        {"id": "o4-mini", "label": "o4-mini — reasoning"},
    ],
    "gemini": [
        {"id": "gemini-2.0-flash", "label": "gemini-2.0-flash — rýchly"},
        {"id": "gemini-2.5-flash", "label": "gemini-2.5-flash"},
        {"id": "gemini-2.0-pro", "label": "gemini-2.0-pro"},
    ],
    "mistral": [
        {"id": "mistral-small-latest", "label": "mistral-small-latest"},
        {"id": "mistral-medium-latest", "label": "mistral-medium-latest"},
        {"id": "mistral-large-latest", "label": "mistral-large-latest"},
    ],
}


def normalize_provider_name(name: str | None, settings: Settings) -> str:
    provider_name = (name or settings.default_llm_provider or "openai").lower()
    if provider_name == "gpt":
        provider_name = "openai"
    available = settings.available_llm_providers()
    if provider_name not in available:
        if not available:
            raise ValueError(
                "Žiadny LLM kľúč. Nastav OPENAI_API_KEY, GEMINI_API_KEY alebo MISTRAL_API_KEY."
            )
        provider_name = available[0]
    return provider_name


def resolve_model_id(settings: Settings, provider_name: str, model: str | None = None) -> str:
    configured = {
        "openai": settings.openai_model,
        "gemini": settings.gemini_model,
        "mistral": settings.mistral_model,
    }.get(provider_name, "")
    model_id = (model or configured or DEFAULT_MODELS.get(provider_name) or "").strip()
    allowed = {m["id"] for m in MODEL_OPTIONS.get(provider_name, [])}
    if allowed and model_id not in allowed:
        # Povoľ aj custom z .env, aj keď nie je v zozname UI.
        if model_id == (configured or "").strip():
            return model_id
        return DEFAULT_MODELS.get(provider_name, model_id)
    return model_id or DEFAULT_MODELS[provider_name]


def get_provider(
    settings: Settings,
    name: str | None = None,
    model: str | None = None,
) -> LLMProvider:
    provider_name = normalize_provider_name(name, settings)
    model_id = resolve_model_id(settings, provider_name, model)
    if provider_name == "openai":
        return OpenAIGPTProvider(settings.openai_api_key, model=model_id)
    if provider_name == "gemini":
        return GeminiProvider(settings.gemini_api_key, model=model_id)
    if provider_name == "mistral":
        return MistralProvider(settings.mistral_api_key, model=model_id)
    raise ValueError(f"Neznámy LLM provider: {provider_name}")
