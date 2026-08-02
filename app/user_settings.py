from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Keys match frontend DOM ids / localStorage shape.
ALLOWED_KEYS = frozenset(
    {
        "mode",
        "level",
        "topic",
        "subtopic",
        "minQuestions",
        "sentenceCount",
        "llm",
        "llmModel",
        "ttsProvider",
        "voice",
        "speechRate",
        "silenceTimeout",
    }
)

MAX_VALUE_LEN = 200


def sanitize_settings(raw: Any) -> dict[str, str]:
    """Keep only known string settings with bounded length."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        if key not in ALLOWED_KEYS:
            continue
        if value is None:
            continue
        text = str(value).strip()
        if not text or len(text) > MAX_VALUE_LEN:
            continue
        out[key] = text
    return out


class UserSettingsStore:
    """Per-user lesson UI preferences in settings.json."""

    def __init__(self, user_dir: Path) -> None:
        self.user_dir = Path(user_dir)
        self.path = self.user_dir / "settings.json"
        self.user_dir.mkdir(parents=True, exist_ok=True)

    def read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return sanitize_settings(data)

    def write(self, settings: dict[str, Any]) -> dict[str, str]:
        clean = sanitize_settings(settings)
        self.path.write_text(
            json.dumps(clean, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return clean

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
