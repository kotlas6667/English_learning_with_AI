from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any


_JSON_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def extract_json(text: str) -> Any:
    text = text.strip()
    match = _JSON_BLOCK.search(text)
    if match:
        text = match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def chat(self, messages: list[dict[str, str]], *, system: str | None = None) -> str:
        raise NotImplementedError

    async def chat_json(
        self, messages: list[dict[str, str]], *, system: str | None = None
    ) -> Any:
        raw = await self.chat(messages, system=system)
        return extract_json(raw)
