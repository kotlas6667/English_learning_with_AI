from __future__ import annotations

from mistralai import Mistral

from app.providers.base import LLMProvider


class MistralProvider(LLMProvider):
    name = "mistral"

    def __init__(self, api_key: str, model: str = "mistral-small-latest") -> None:
        self._client = Mistral(api_key=api_key)
        self._model = model
        self.model = model

    async def chat(self, messages: list[dict[str, str]], *, system: str | None = None) -> str:
        payload: list[dict[str, str]] = []
        if system:
            payload.append({"role": "system", "content": system})
        payload.extend(messages)
        response = await self._client.chat.complete_async(
            model=self._model,
            messages=payload,  # type: ignore[arg-type]
            temperature=0.7,
        )
        content = response.choices[0].message.content
        if isinstance(content, list):
            return "".join(str(part) for part in content).strip()
        return (content or "").strip()
