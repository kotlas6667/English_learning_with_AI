from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.auth import hash_password, verify_password
from app.context_limits import (
    DUE_ITEMS_AI_MAX,
    HISTORY_AI_MAX_CHARS,
    HISTORY_FILE_MAX_CHARS,
    PROFILE_AI_MAX_CHARS,
    TUTOR_CONTEXT_MAX_CHARS,
    WEAK_AREAS_AI_MAX,
    clip_chars,
    profile_for_ai,
)
from app.learning_store import MarkdownLearningStore


def _slug(name: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9áäčďéíľňóôŕšťúýžÁÄČĎÉÍĽŇÓÔŔŠŤÚÝŽ_-]+", "-", name.strip())
    base = re.sub(r"-+", "-", base).strip("-").lower() or "user"
    return base[:48]


@dataclass
class User:
    id: str
    name: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    preferred_level: str = "A2"
    notes: str = ""
    password_hash: str = ""
    role: str = "user"  # user | admin

    def is_admin(self) -> bool:
        return self.role == "admin"

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "preferred_level": self.preferred_level,
            "has_password": bool(self.password_hash),
            "role": self.role,
            "is_admin": self.is_admin(),
        }


class UserManager:
    """Multi-user profiles, history, and per-user learning stores (Markdown files)."""

    ADMIN_NAME = "Administrator"
    ADMIN_PASSWORD = "admin"

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.users_root = self.data_dir / "users"
        self.users_root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.data_dir / "users.json"
        self._stores: dict[str, MarkdownLearningStore] = {}
        self._ensure_index()

    def _ensure_index(self) -> None:
        if not self.index_path.exists():
            student = self._create_user_files("Študent", preferred_level="A2", password="student", role="user")
            admin = self._create_user_files(
                self.ADMIN_NAME, preferred_level="B2", password=self.ADMIN_PASSWORD, role="admin"
            )
            self._write_index({"active_user_id": student.id, "users": [asdict(admin), asdict(student)]})
            return
        data = self._read_index()
        if not data.get("users"):
            student = self._create_user_files("Študent", preferred_level="A2", password="student", role="user")
            admin = self._create_user_files(
                self.ADMIN_NAME, preferred_level="B2", password=self.ADMIN_PASSWORD, role="admin"
            )
            self._write_index({"active_user_id": student.id, "users": [asdict(admin), asdict(student)]})
            return
        self._ensure_administrator()

    def _ensure_administrator(self) -> None:
        data = self._read_index()
        users_raw = data.setdefault("users", [])
        admin_raw = next(
            (u for u in users_raw if str(u.get("name", "")).strip().casefold() == self.ADMIN_NAME.casefold()),
            None,
        )
        if admin_raw is None:
            admin = self._create_user_files(
                self.ADMIN_NAME, preferred_level="B2", password=self.ADMIN_PASSWORD, role="admin"
            )
            users_raw.insert(0, asdict(admin))
            self._write_index(data)
            return
        changed = False
        if admin_raw.get("role") != "admin":
            admin_raw["role"] = "admin"
            changed = True
        if not admin_raw.get("password_hash"):
            admin_raw["password_hash"] = hash_password(self.ADMIN_PASSWORD)
            changed = True
        if changed:
            self._write_index(data)

    def _read_index(self) -> dict[str, Any]:
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def _write_index(self, data: dict[str, Any]) -> None:
        self.index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _user_dir(self, user_id: str) -> Path:
        path = self.users_root / user_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _user_from_dict(self, raw: dict[str, Any]) -> User:
        return User(
            id=raw["id"],
            name=raw["name"],
            created_at=raw.get("created_at") or datetime.now().isoformat(timespec="seconds"),
            preferred_level=raw.get("preferred_level") or "A2",
            notes=raw.get("notes") or "",
            password_hash=raw.get("password_hash") or "",
            role=raw.get("role") or "user",
        )

    def _create_user_files(
        self,
        name: str,
        preferred_level: str = "A2",
        password: str = "",
        role: str = "user",
    ) -> User:
        user_id = f"{_slug(name)}-{uuid.uuid4().hex[:6]}"
        user = User(
            id=user_id,
            name=name.strip() or "Študent",
            preferred_level=preferred_level,
            password_hash=hash_password(password) if password else "",
            role="admin" if role == "admin" else "user",
        )
        udir = self._user_dir(user_id)
        (udir / "profile.md").write_text(self._default_profile(user), encoding="utf-8")
        (udir / "history.md").write_text(
            f"# History: {user.name}\n\n_Created: {user.created_at}_\n\n",
            encoding="utf-8",
        )
        MarkdownLearningStore(udir)
        (udir / "topics.json").write_text(
            json.dumps({"topics": {}}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (udir / "settings.json").write_text(
            json.dumps({}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return user

    def _default_profile(self, user: User) -> str:
        return (
            f"# Profile: {user.name}\n\n"
            f"- User ID: `{user.id}`\n"
            f"- Preferred level: {user.preferred_level}\n"
            f"- Created: {user.created_at}\n\n"
            "## Weak areas\n\n_Zatiaľ prázdne — AI doplní z konverzácií a chýb._\n\n"
            "## Strengths\n\n_Zatiaľ prázdne._\n\n"
            "## About the learner\n\n"
            "_AI tu dopĺňa fakty, ktoré sa o tebe dozvie počas voľnej debaty._\n\n"
            "## Notes for the tutor (AI)\n\n"
            "- Be patient and keep turns short.\n"
            "- Revisit weak phrases before starting new topics.\n\n"
            "## Recent session notes\n\n"
        )

    def list_users(self) -> list[User]:
        return [self._user_from_dict(u) for u in self._read_index().get("users", [])]

    def get_active_user_id(self) -> str:
        data = self._read_index()
        active = data.get("active_user_id")
        users = data.get("users") or []
        if active and any(u["id"] == active for u in users):
            return active
        if users:
            data["active_user_id"] = users[0]["id"]
            self._write_index(data)
            return users[0]["id"]
        return self.create_user("Študent", password="student").id

    def set_active_user(self, user_id: str) -> User:
        data = self._read_index()
        raw = next((u for u in data["users"] if u["id"] == user_id), None)
        if not raw:
            raise KeyError(f"Používateľ neexistuje: {user_id}")
        data["active_user_id"] = user_id
        self._write_index(data)
        return self._user_from_dict(raw)

    def get_user(self, user_id: str) -> User:
        for u in self._read_index().get("users", []):
            if u["id"] == user_id:
                return self._user_from_dict(u)
        raise KeyError(f"Používateľ neexistuje: {user_id}")

    def find_by_name(self, name: str) -> User | None:
        needle = name.strip().casefold()
        for u in self.list_users():
            if u.name.strip().casefold() == needle:
                return u
        return None

    def name_exists(self, name: str, *, exclude_user_id: str | None = None) -> bool:
        needle = name.strip().casefold()
        if not needle:
            return False
        for u in self.list_users():
            if exclude_user_id and u.id == exclude_user_id:
                continue
            if u.name.strip().casefold() == needle:
                return True
        return False

    def create_user(
        self,
        name: str,
        preferred_level: str = "A2",
        *,
        password: str,
        role: str = "user",
    ) -> User:
        clean = name.strip()
        if not clean:
            raise ValueError("Meno používateľa nemôže byť prázdne.")
        if len(password or "") < 4:
            raise ValueError("Heslo musí mať aspoň 4 znaky.")
        if self.name_exists(clean):
            raise ValueError(f"Používateľ s menom „{clean}“ už existuje.")
        if role == "admin" and clean.casefold() != self.ADMIN_NAME.casefold():
            # Extra admins allowed, but name Administrator is reserved for the bootstrap admin
            pass
        user = self._create_user_files(
            clean, preferred_level=preferred_level, password=password, role=role
        )
        data = self._read_index()
        data.setdefault("users", []).append(asdict(user))
        data["active_user_id"] = user.id
        self._write_index(data)
        self.store(user.id)
        self.read_profile(user.id)
        return user

    def authenticate(self, name: str, password: str) -> User:
        user = self.find_by_name(name)
        if not user:
            raise ValueError("Nesprávne meno alebo heslo.")
        return self._check_password(user, password)

    def authenticate_by_id(self, user_id: str, password: str) -> User:
        try:
            user = self.get_user(user_id)
        except KeyError as exc:
            raise ValueError("Nesprávny používateľ alebo heslo.") from exc
        return self._check_password(user, password)

    def _check_password(self, user: User, password: str) -> User:
        if not user.password_hash:
            if len(password) < 4:
                raise ValueError("Účet ešte nemá heslo. Zadaj nové heslo (min. 4 znaky).")
            self.set_password(user.id, password)
            return self.get_user(user.id)
        if not verify_password(password, user.password_hash):
            raise ValueError("Nesprávne meno alebo heslo.")
        return user

    def count_admins(self) -> int:
        return sum(1 for u in self.list_users() if u.is_admin())

    def set_password(self, user_id: str, password: str) -> None:
        if len(password) < 4:
            raise ValueError("Heslo musí mať aspoň 4 znaky.")
        data = self._read_index()
        for u in data["users"]:
            if u["id"] == user_id:
                u["password_hash"] = hash_password(password)
                self._write_index(data)
                return
        raise KeyError(f"Používateľ neexistuje: {user_id}")

    def verify_user_password(self, user_id: str, password: str) -> bool:
        user = self.get_user(user_id)
        return bool(user.password_hash) and verify_password(password, user.password_hash)

    def rename_user(self, user_id: str, name: str) -> User:
        clean = name.strip()
        if not clean:
            raise ValueError("Meno používateľa nemôže byť prázdne.")
        target = self.get_user(user_id)
        if target.is_admin() and target.name.casefold() == self.ADMIN_NAME.casefold():
            if clean.casefold() != self.ADMIN_NAME.casefold():
                raise ValueError("Účet Administrator sa nedá premenovať.")
        if self.name_exists(clean, exclude_user_id=user_id):
            raise ValueError(f"Používateľ s menom „{clean}“ už existuje.")
        data = self._read_index()
        for u in data["users"]:
            if u["id"] == user_id:
                u["name"] = clean
                self._write_index(data)
                return self._user_from_dict(u)
        raise KeyError(f"Používateľ neexistuje: {user_id}")

    def delete_user(
        self,
        user_id: str,
        *,
        password: str,
        actor_id: str | None = None,
    ) -> None:
        target = self.get_user(user_id)
        actor = self.get_user(actor_id) if actor_id else target

        if actor.is_admin() and actor.id != user_id:
            if not self.verify_user_password(actor.id, password):
                raise ValueError("Nesprávne admin heslo — účet nebol zmazaný.")
        else:
            if actor.id != user_id:
                raise ValueError("Nemáš právo zmazať cudzí účet.")
            if not self.verify_user_password(user_id, password):
                raise ValueError("Nesprávne heslo — účet nebol zmazaný.")

        if target.is_admin() and self.count_admins() <= 1:
            raise ValueError("Nemôžeš zmazať posledného administrátora.")

        data = self._read_index()
        users_list = [u for u in data.get("users", []) if u["id"] != user_id]
        if len(users_list) == len(data.get("users", [])):
            raise KeyError(f"Používateľ neexistuje: {user_id}")
        if not users_list:
            raise ValueError("Nemôžeš zmazať posledného používateľa.")
        data["users"] = users_list
        if data.get("active_user_id") == user_id:
            data["active_user_id"] = users_list[0]["id"]
        self._write_index(data)
        self._stores.pop(user_id, None)
        user_dir = self.users_root / user_id
        if user_dir.exists():
            shutil.rmtree(user_dir, ignore_errors=True)

    def store(self, user_id: str) -> MarkdownLearningStore:
        self.get_user(user_id)
        if user_id not in self._stores:
            self._stores[user_id] = MarkdownLearningStore(self._user_dir(user_id))
        return self._stores[user_id]

    def profile_path(self, user_id: str) -> Path:
        return self._user_dir(user_id) / "profile.md"

    def history_path(self, user_id: str) -> Path:
        return self._user_dir(user_id) / "history.md"

    def read_profile(self, user_id: str) -> str:
        path = self.profile_path(user_id)
        if not path.exists():
            path.write_text(self._default_profile(self.get_user(user_id)), encoding="utf-8")
        return path.read_text(encoding="utf-8")

    def read_history(self, user_id: str, *, max_chars: int = HISTORY_AI_MAX_CHARS) -> str:
        path = self.history_path(user_id)
        if not path.exists():
            return ""
        text = path.read_text(encoding="utf-8")
        return clip_chars(text, max_chars, from_end=True) if len(text) > max_chars else text

    def append_history(self, user_id: str, entry: str) -> None:
        path = self.history_path(user_id)
        stamp = datetime.now().isoformat(timespec="seconds")
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"\n### {stamp}\n\n{entry.strip()}\n")
        # Orezanie na disku — AI aj tak berie len chvost.
        try:
            text = path.read_text(encoding="utf-8")
            if len(text) > HISTORY_FILE_MAX_CHARS:
                trimmed = clip_chars(text, HISTORY_FILE_MAX_CHARS, from_end=True)
                if trimmed.startswith("…\n"):
                    trimmed = "# History (trimmed)\n\n" + trimmed[2:]
                path.write_text(trimmed, encoding="utf-8")
        except OSError:
            pass

    def append_profile_note(self, user_id: str, note: str) -> None:
        path = self.profile_path(user_id)
        stamp = datetime.now().isoformat(timespec="seconds")
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"- [{stamp}] {note.strip()}\n")

    def append_about_learner(self, user_id: str, facts: list[str]) -> list[str]:
        """Append newly learned facts into the profile section About the learner."""
        clean = [f.strip() for f in facts if f and f.strip()]
        if not clean:
            return []
        path = self.profile_path(user_id)
        profile = self.read_profile(user_id)
        existing = profile.casefold()
        added: list[str] = []
        for fact in clean:
            if fact.casefold() in existing:
                continue
            added.append(fact)
            existing += "\n" + fact.casefold()
        if not added:
            return []

        stamp = datetime.now().isoformat(timespec="seconds")
        bullets = "\n".join(f"- [{stamp}] {f}" for f in added) + "\n"
        section_header = "## About the learner"
        if section_header in profile:
            # Insert after header / placeholder
            profile = re.sub(
                rf"({re.escape(section_header)}\n\n)",
                r"\1" + bullets,
                profile,
                count=1,
            )
            # Remove empty placeholder once we have real facts
            profile = profile.replace(
                "_AI tu dopĺňa fakty, ktoré sa o tebe dozvie počas voľnej debaty._\n\n",
                "",
            )
        else:
            profile += f"\n{section_header}\n\n{bullets}"
        path.write_text(profile, encoding="utf-8")
        return added

    def sync_weak_areas_from_store(self, user_id: str) -> None:
        store = self.store(user_id)
        items = [i for i in store.all_items() if i.status != "known"]
        # all_items už je zoradené podľa significance desc
        weak_lines = []
        for item in items[:WEAK_AREAS_AI_MAX]:
            tip = item.translation_sk or item.tip or ""
            weak_lines.append(
                f"- [{item.significance}/10] {item.word}"
                + (f" — {tip}" if tip else f" ({item.kind})")
            )
        if not weak_lines:
            weak_lines = ["_Zatiaľ prázdne — AI doplní z konverzácií a chýb._"]
        profile = self.read_profile(user_id)
        section = "## Weak areas\n\n" + "\n".join(weak_lines) + "\n"
        if "## Weak areas" in profile:
            profile = re.sub(
                r"## Weak areas\n\n.*?(?=\n## |\Z)",
                section + "\n",
                profile,
                count=1,
                flags=re.DOTALL,
            )
        else:
            profile += "\n" + section
        self.profile_path(user_id).write_text(profile, encoding="utf-8")

    def tutor_context(self, user_id: str) -> str:
        self.sync_weak_areas_from_store(user_id)
        due = self.store(user_id).list_due(limit=DUE_ITEMS_AI_MAX)
        due_list = ", ".join(i.word for i in due) if due else "(none)"
        profile = profile_for_ai(self.read_profile(user_id), max_chars=PROFILE_AI_MAX_CHARS)
        history = self.read_history(user_id, max_chars=HISTORY_AI_MAX_CHARS) or "(empty)"
        ctx = (
            f"LEARNER PROFILE FILE:\n{profile}\n\n"
            f"DUE REVIEW ITEMS NOW: {due_list}\n\n"
            f"RECENT HISTORY (tail):\n{history}\n"
        )
        return clip_chars(ctx, TUTOR_CONTEXT_MAX_CHARS, from_end=False)

    def topics(self, user_id: str):
        from app.user_topics import UserTopicsStore

        self.get_user(user_id)
        return UserTopicsStore(self._user_dir(user_id))

    def settings(self, user_id: str):
        from app.user_settings import UserSettingsStore

        self.get_user(user_id)
        return UserSettingsStore(self._user_dir(user_id))
