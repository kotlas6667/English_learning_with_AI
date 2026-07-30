from __future__ import annotations

from typing import Any

import edge_tts

from app.voice.base import TTSProvider
from app.voice.rate import rate_to_edge_percent

# Popular natural English neural voices (Microsoft Edge)
DEFAULT_EDGE_VOICE = "en-US-JennyNeural"

PREFERRED_EDGE = (
    "en-US-JennyNeural",
    "en-US-GuyNeural",
    "en-US-AriaNeural",
    "en-US-ChristopherNeural",
    "en-GB-SoniaNeural",
    "en-GB-RyanNeural",
    "en-GB-LibbyNeural",
    "en-AU-NatashaNeural",
    "en-AU-WilliamNeural",
    "en-IE-ConnorNeural",
    "en-IE-EmilyNeural",
)


class EdgeTTS(TTSProvider):
    """Microsoft Edge neural voices via edge-tts (no API key)."""

    name = "edge"

    def __init__(self, voice_id: str = DEFAULT_EDGE_VOICE) -> None:
        self.voice_id = voice_id or DEFAULT_EDGE_VOICE

    async def synthesize(
        self, text: str, *, voice_id: str | None = None, rate: float = 1.0
    ) -> bytes:
        voice = voice_id or self.voice_id
        communicate = edge_tts.Communicate(text, voice, rate=rate_to_edge_percent(rate))
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        audio = b"".join(chunks)
        if not audio:
            raise RuntimeError("Edge-TTS nevrátilo žiadne audio.")
        return audio

    async def list_voices(self) -> list[dict[str, Any]]:
        raw = await edge_tts.list_voices()
        voices: list[dict[str, Any]] = []
        for v in raw:
            short = v.get("ShortName") or ""
            locale = (v.get("Locale") or "").lower()
            if not locale.startswith("en-"):
                continue
            voices.append(
                {
                    "voice_id": short,
                    "name": f"{v.get('FriendlyName') or short}",
                    "preview_url": "",
                    "labels": f"locale={v.get('Locale')}, gender={v.get('Gender')}",
                    "likely_english": True,
                }
            )

        def sort_key(item: dict[str, Any]) -> tuple[int, str]:
            vid = item["voice_id"]
            try:
                pref = PREFERRED_EDGE.index(vid)
            except ValueError:
                pref = len(PREFERRED_EDGE)
            return (pref, item["name"].lower())

        voices.sort(key=sort_key)
        return voices
