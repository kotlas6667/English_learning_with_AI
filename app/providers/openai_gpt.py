from __future__ import annotations

from openai import AsyncOpenAI

from app.providers.base import LLMProvider


class OpenAIGPTProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self.model = model

    async def chat(self, messages: list[dict[str, str]], *, system: str | None = None) -> str:
        payload: list[dict[str, str]] = []
        if system:
            payload.append({"role": "system", "content": system})
        payload.extend(messages)
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=payload,  # type: ignore[arg-type]
            temperature=0.7,
        )
        return (response.choices[0].message.content or "").strip()
