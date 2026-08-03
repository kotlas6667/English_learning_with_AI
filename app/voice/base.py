from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class TTSProvider(ABC):
    """Natural English neural TTS — never LLM robotic voice."""

    name: str

    @abstractmethod
    async def synthesize(
        self, text: str, *, voice_id: str | None = None, rate: float = 1.0
    ) -> bytes:
        raise NotImplementedError

    @abstractmethod
    async def list_voices(self) -> list[dict[str, Any]]:
        raise NotImplementedError
