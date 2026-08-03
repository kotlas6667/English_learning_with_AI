from __future__ import annotations

import io
import re

from openai import AsyncOpenAI

# Whisper often invents short phrases from silence / near-silence.
# Keep this list conservative — real learner answers like "yes"/"no"/"ok" must pass.
_SILENCE_HALLUCINATIONS = frozenset(
    {
        "you",
        "uh",
        "um",
        "hmm",
        "mm",
        "mhm",
        "ah",
        "oh",
        "thank you for watching",
        "thanks for watching",
        "thanks for watching everybody",
        "subtitles by the amara.org community",
        "字幕",
        "ご視聴ありがとうございました",
    }
)

_PUNCT_RE = re.compile(r"^[\W_]+$", re.UNICODE)


def normalize_transcript(text: str) -> str:
    """Strip Whisper silence hallucinations; empty means 'no speech'."""
    raw = (text or "").strip()
    if not raw:
        return ""
    if _PUNCT_RE.match(raw):
        return ""
    normalized = re.sub(r"\s+", " ", raw).strip().lower()
    normalized = normalized.strip(" .!?,;:\"'`…")
    if not normalized:
        return ""
    if normalized in _SILENCE_HALLUCINATIONS:
        return ""
    tokens = normalized.split()
    if len(tokens) == 1 and tokens[0] in _SILENCE_HALLUCINATIONS:
        return ""
    return raw


class WhisperSTT:
    def __init__(self, api_key: str, model: str = "whisper-1") -> None:
        if not api_key.strip():
            raise ValueError(
                "Chýba OPENAI_API_KEY pre Whisper STT. "
                "STT potrebuje OpenAI kľúč (hlas tutora ostáva ElevenLabs)."
            )
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def transcribe(self, audio_bytes: bytes, filename: str = "audio.webm") -> str:
        buffer = io.BytesIO(audio_bytes)
        buffer.name = filename
        result = await self._client.audio.transcriptions.create(
            model=self._model,
            file=buffer,
            language="en",
            temperature=0,
        )
        return normalize_transcript(result.text or "")
