from __future__ import annotations

import io

from openai import AsyncOpenAI


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
        )
        return (result.text or "").strip()
