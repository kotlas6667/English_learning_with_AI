from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def hash_password(password: str, *, salt: str | None = None) -> str:
    salt_hex = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_hex.encode("utf-8"),
        120_000,
    )
    return f"pbkdf2_sha256${salt_hex}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algo, salt, _digest = password_hash.split("$", 2)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    check = hash_password(password, salt=salt)
    return hmac.compare_digest(check, password_hash)


class SessionStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / "sessions.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"sessions": {}})

    def _read(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"sessions": {}}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def create(self, user_id: str, *, hours: int = 72) -> str:
        token = secrets.token_urlsafe(32)
        data = self._read()
        sessions = data.setdefault("sessions", {})
        now = datetime.utcnow()
        fresh = {}
        for t, meta in sessions.items():
            try:
                exp = datetime.fromisoformat(meta["expires_at"])
            except (KeyError, ValueError):
                continue
            if exp > now:
                fresh[t] = meta
        fresh[token] = {
            "user_id": user_id,
            "expires_at": (now + timedelta(hours=hours)).isoformat(),
        }
        data["sessions"] = fresh
        self._write(data)
        return token

    def resolve(self, token: str | None) -> str | None:
        if not token:
            return None
        data = self._read()
        meta = (data.get("sessions") or {}).get(token)
        if not meta:
            return None
        try:
            exp = datetime.fromisoformat(meta["expires_at"])
        except (KeyError, ValueError):
            return None
        if exp <= datetime.utcnow():
            return None
        return meta.get("user_id")

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        data = self._read()
        sessions = data.get("sessions") or {}
        if token in sessions:
            del sessions[token]
            data["sessions"] = sessions
            self._write(data)

    def revoke_user(self, user_id: str) -> None:
        data = self._read()
        sessions = data.get("sessions") or {}
        data["sessions"] = {
            t: m for t, m in sessions.items() if m.get("user_id") != user_id
        }
        self._write(data)
