from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    elevenlabs_model_id: str = "eleven_multilingual_v2"

    # edge | elevenlabs — Edge-TTS needs no API key
    tts_provider: str = "edge"
    edge_tts_voice: str = "en-US-JennyNeural"
    speech_rate: float = 1.0

    openai_api_key: str = ""
    gemini_api_key: str = ""
    mistral_api_key: str = ""

    openai_model: str = "gpt-4o-mini"
    gemini_model: str = "gemini-2.0-flash"
    mistral_model: str = "mistral-small-latest"

    default_llm_provider: str = "openai"
    default_level: str = "A2"
    data_dir: Path = Path("data")
    host: str = "0.0.0.0"
    port: int = 8080

    def require_elevenlabs(self) -> None:
        if not self.elevenlabs_api_key.strip():
            raise ValueError(
                "Chýba ELEVENLABS_API_KEY. Nastav ho v .env, alebo prepnite TTS na Edge-TTS."
            )

    def available_llm_providers(self) -> list[str]:
        providers: list[str] = []
        if self.openai_api_key.strip():
            providers.append("openai")
        if self.gemini_api_key.strip():
            providers.append("gemini")
        if self.mistral_api_key.strip():
            providers.append("mistral")
        return providers

    def llm_provider_options(self) -> list[dict[str, str]]:
        options: list[dict[str, str]] = []
        if self.openai_api_key.strip():
            options.append({"id": "openai", "label": f"GPT (OpenAI) · {self.openai_model}"})
        if self.gemini_api_key.strip():
            options.append({"id": "gemini", "label": f"Gemini · {self.gemini_model}"})
        if self.mistral_api_key.strip():
            options.append({"id": "mistral", "label": f"Mistral · {self.mistral_model}"})
        return options

    def default_model_for(self, provider: str) -> str:
        name = "openai" if provider == "gpt" else provider
        if name == "openai":
            return self.openai_model or "gpt-4o-mini"
        if name == "gemini":
            return self.gemini_model or "gemini-2.0-flash"
        if name == "mistral":
            return self.mistral_model or "mistral-small-latest"
        return ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
