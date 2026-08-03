from __future__ import annotations

from app.config import Settings
from app.voice.base import TTSProvider
from app.voice.tts_edge import DEFAULT_EDGE_VOICE, EdgeTTS
from app.voice.tts_elevenlabs import ElevenLabsTTS


def normalize_tts_provider(name: str | None) -> str:
    value = (name or "edge").strip().lower()
    if value in {"edge", "edge-tts", "edge_tts", "microsoft", "msedge"}:
        return "edge"
    if value in {"elevenlabs", "eleven", "11labs"}:
        return "elevenlabs"
    raise ValueError(f"Neznámy TTS provider: {name}. Použi 'edge' alebo 'elevenlabs'.")


def default_voice_for(settings: Settings, provider: str) -> str:
    if provider == "edge":
        return settings.edge_tts_voice or DEFAULT_EDGE_VOICE
    return settings.elevenlabs_voice_id


def get_tts(
    settings: Settings,
    provider: str | None = None,
    voice_id: str | None = None,
) -> TTSProvider:
    name = normalize_tts_provider(provider or settings.tts_provider)
    if name == "edge":
        return EdgeTTS(voice_id=voice_id or default_voice_for(settings, "edge"))
    settings.require_elevenlabs()
    return ElevenLabsTTS(
        api_key=settings.elevenlabs_api_key,
        voice_id=voice_id or default_voice_for(settings, "elevenlabs"),
        model_id=settings.elevenlabs_model_id,
    )


def tts_provider_options(settings: Settings) -> list[dict[str, str]]:
    options = [
        {"id": "edge", "label": "Edge-TTS (Microsoft)"},
    ]
    if settings.elevenlabs_api_key.strip():
        options.append({"id": "elevenlabs", "label": "ElevenLabs"})
    else:
        options.append({"id": "elevenlabs", "label": "ElevenLabs (vyžaduje API kľúč)"})
    return options
