from __future__ import annotations

import httpx

from app.voice.base import TTSProvider
from app.voice.rate import rate_to_elevenlabs


class ElevenLabsTTS(TTSProvider):
    """Natural English neural voice via ElevenLabs — not LLM/robotic TTS."""

    name = "elevenlabs"

    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model_id: str = "eleven_multilingual_v2",
    ) -> None:
        if not api_key.strip():
            raise ValueError(
                "Chýba ELEVENLABS_API_KEY. Nastav ho v .env, alebo prepnite TTS na Edge-TTS."
            )
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self._base = "https://api.elevenlabs.io/v1"

    async def synthesize(
        self, text: str, *, voice_id: str | None = None, rate: float = 1.0
    ) -> bytes:
        vid = voice_id or self.voice_id
        url = f"{self._base}/text-to-speech/{vid}"
        headers = {
            "xi-api-key": self.api_key,
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "model_id": self.model_id,
            "speed": rate_to_elevenlabs(rate),
            "voice_settings": {
                "stability": 0.45,
                "similarity_boost": 0.75,
                "style": 0.35,
                "use_speaker_boost": True,
            },
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code >= 400:
                raise RuntimeError(
                    f"ElevenLabs TTS zlyhalo ({response.status_code}): {response.text[:300]}"
                )
            return response.content

    async def list_voices(self) -> list[dict]:
        headers = {"xi-api-key": self.api_key}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{self._base}/voices", headers=headers)
            response.raise_for_status()
            data = response.json()
        voices = []
        for v in data.get("voices", []):
            labels = v.get("labels") or {}
            lang = (labels.get("language") or labels.get("accent") or "").lower()
            voices.append(
                {
                    "voice_id": v.get("voice_id", ""),
                    "name": v.get("name", "Unknown"),
                    "preview_url": v.get("preview_url") or "",
                    "labels": ", ".join(f"{k}={val}" for k, val in labels.items()),
                    "likely_english": "en" in lang or "english" in lang or not lang,
                }
            )
        voices.sort(key=lambda x: (not x["likely_english"], x["name"].lower()))
        return voices
