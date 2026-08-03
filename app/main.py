from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.auth import SessionStore
from app.config import Settings, get_settings
from app.learning_store import MarkdownLearningStore
from app.modes.comprehension import ComprehensionEngine
from app.modes.conversation import ConversationEngine
from app.modes.reading import ReadingEngine
from app.providers import MODEL_OPTIONS, get_provider
from app.scenarios import get_scenario, list_scenarios
from app.topics import LEVELS
from app.user_topics import TopicDuplicateError
from app.users import UserManager
from app.voice.factory import (
    default_voice_for,
    get_tts,
    normalize_tts_provider,
    tts_provider_options,
)
from app.voice.rate import SPEECH_RATE_OPTIONS, clamp_speech_rate
from app.voice.stt import WhisperSTT

STATIC_DIR = Path(__file__).parent / "static"
QUESTION_OPTIONS = [20, 50, 80]
SENTENCE_OPTIONS = [20, 50, 100]
SILENCE_TIMEOUT_OPTIONS = [2, 3, 4, 5]
IDLE_LISTEN_TIMEOUT_OPTIONS = [15, 30, 45, 60]

app = FastAPI(title="EngLearning", version="1.2.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

settings = get_settings()
users = UserManager(settings.data_dir)
sessions = SessionStore(settings.data_dir)
conversation_engine = ConversationEngine()
reading_engine = ReadingEngine()
comprehension_engine = ComprehensionEngine(reading_engine)


class StartRequest(BaseModel):
    mode: Literal["conversation", "reading", "free_debate"] = "conversation"
    level: str = "A2"
    topic: str = "travel"
    subtopic: str | None = None
    scenario_id: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    tts_provider: str | None = None
    voice_id: str | None = None
    speech_rate: float | None = None
    user_id: str | None = None
    min_questions: int = 20
    sentence_count: int = 20
    restart: bool = False


class TextTurnRequest(BaseModel):
    session_id: str
    text: str = Field(min_length=1)
    speech_rate: float | None = None


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1)
    tts_provider: str | None = None
    voice_id: str | None = None
    speech_rate: float | None = None


class AuthRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    user_id: str | None = None
    name: str | None = Field(default=None, max_length=80)


class CreateUserRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=4, max_length=128)
    preferred_level: str = "A2"


class RenameUserRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class DeleteUserRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class DeleteLearningRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    word: str = Field(min_length=1, max_length=300)
    user_id: str | None = None


class LessonSettingsRequest(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    user_id: str | None = None


class PracticeLearningRequest(BaseModel):
    kind: Literal["reading_error", "vocabulary"] = "reading_error"
    user_id: str | None = None
    level: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    tts_provider: str | None = None
    voice_id: str | None = None
    speech_rate: float | None = None
    sentence_count: int | None = None


class SessionIdBody(BaseModel):
    session_id: str


class AddTopicRequest(BaseModel):
    user_id: str | None = None
    label: str = Field(min_length=1, max_length=80)
    description: str = ""
    force: bool = False


class AddSubtopicRequest(BaseModel):
    user_id: str | None = None
    topic_id: str
    label: str = Field(min_length=1, max_length=120)
    description: str = ""
    force: bool = False


class CheckTopicRequest(BaseModel):
    user_id: str | None = None
    label: str = Field(min_length=1, max_length=80)
    description: str = ""
    kind: Literal["topic", "subtopic"] = "topic"
    topic_id: str | None = None


def _stt(cfg: Settings) -> WhisperSTT:
    return WhisperSTT(api_key=cfg.openai_api_key)


def _token_from_headers(
    authorization: str | None = None,
    x_session_token: str | None = None,
) -> str | None:
    if x_session_token and x_session_token.strip():
        return x_session_token.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def _require_user(
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> str:
    token = _token_from_headers(authorization, x_session_token)
    uid = sessions.resolve(token)
    if not uid:
        raise HTTPException(status_code=401, detail="Nie si prihlásený. Prihlás sa alebo vytvor účet.")
    try:
        users.get_user(uid)
    except KeyError as exc:
        sessions.revoke(token)
        raise HTTPException(status_code=401, detail="Session je neplatná.") from exc
    return uid


def _optional_user(
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> str | None:
    token = _token_from_headers(authorization, x_session_token)
    return sessions.resolve(token)


def _resolve_user_id(user_id: str | None, *, auth_uid: str) -> str:
    """Bežný používateľ len svoj účet; admin môže spravovať hociktorý."""
    if not user_id or user_id == auth_uid:
        return auth_uid
    actor = users.get_user(auth_uid)
    if not actor.is_admin():
        raise HTTPException(status_code=403, detail="Môžeš spravovať len svoj prihlásený účet.")
    try:
        users.get_user(user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return user_id


def _require_admin(auth_uid: str):
    actor = users.get_user(auth_uid)
    if not actor.is_admin():
        raise HTTPException(status_code=403, detail="Len Administrator má toto právo.")
    return actor


def _auth_payload(user, token: str) -> dict[str, Any]:
    store = users.store(user.id)
    return {
        "token": token,
        "user": user.public_dict(),
        "active_user_id": user.id,
        "learning_due": [i.word for i in store.list_due(limit=10)],
        "learning_count": len(store.all_items()),
    }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "llm_providers": settings.available_llm_providers(),
        "tts_providers": ["edge", "elevenlabs"],
        "default_tts": settings.tts_provider,
        "elevenlabs_configured": bool(settings.elevenlabs_api_key.strip()),
        "edge_tts_available": True,
        "whisper_configured": bool(settings.openai_api_key.strip()),
    }


@app.get("/api/meta")
async def meta(
    user_id: str | None = None,
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    options = settings.llm_provider_options()
    default_tts = normalize_tts_provider(settings.tts_provider)
    auth_uid = _optional_user(authorization, x_session_token)
    topics: list[dict[str, Any]] = []
    lesson_settings: dict[str, str] = {}
    uid = auth_uid
    is_admin = False
    if auth_uid:
        try:
            actor = users.get_user(auth_uid)
            is_admin = actor.is_admin()
            uid = _resolve_user_id(user_id, auth_uid=auth_uid) if user_id else auth_uid
            topics = users.topics(uid).list_topics()
            lesson_settings = users.settings(uid).read()
            users.set_active_user(uid)
        except (KeyError, HTTPException):
            uid = auth_uid
            try:
                topics = users.topics(auth_uid).list_topics()
                lesson_settings = users.settings(auth_uid).read()
            except KeyError:
                topics = []
                lesson_settings = {}
    return {
        "topics": topics,
        "lesson_settings": lesson_settings,
        "levels": list(LEVELS),
        "llm_providers": settings.available_llm_providers(),
        "llm_options": options,
        "default_llm": settings.default_llm_provider,
        "llm_model_options": MODEL_OPTIONS,
        "default_llm_models": {
            "openai": settings.openai_model,
            "gemini": settings.gemini_model,
            "mistral": settings.mistral_model,
        },
        "default_llm_model": settings.default_model_for(settings.default_llm_provider),
        "tts_options": tts_provider_options(settings),
        "default_tts_provider": default_tts,
        "default_voice_id": default_voice_for(settings, default_tts),
        "speech_rate_options": SPEECH_RATE_OPTIONS,
        "default_speech_rate": clamp_speech_rate(settings.speech_rate),
        "default_level": settings.default_level,
        "min_questions_options": QUESTION_OPTIONS,
        "default_min_questions": 20,
        "sentence_count_options": SENTENCE_OPTIONS,
        "default_sentence_count": 20,
        "silence_timeout_options": SILENCE_TIMEOUT_OPTIONS,
        "default_silence_timeout": 3,
        "idle_listen_timeout_options": IDLE_LISTEN_TIMEOUT_OPTIONS,
        "default_idle_listen_timeout": 30,
        "active_user_id": uid,
        "authenticated": bool(auth_uid),
        "is_admin": is_admin,
    }


@app.get("/api/auth/users")
async def auth_user_directory() -> dict[str, Any]:
    """Verejný zoznam mien na prihlasovaciu obrazovku (bez hesiel)."""
    users._ensure_administrator()
    items = sorted(users.list_users(), key=lambda u: (0 if u.is_admin() else 1, u.name.casefold()))
    return {
        "users": [
            {"id": u.id, "name": u.name, "role": u.role, "is_admin": u.is_admin()}
            for u in items
        ]
    }


@app.post("/api/auth/login")
async def auth_login(body: AuthRequest) -> dict[str, Any]:
    try:
        if body.user_id:
            user = users.authenticate_by_id(body.user_id, body.password)
        elif body.name:
            user = users.authenticate(body.name, body.password)
        else:
            raise HTTPException(status_code=400, detail="Vyber používateľa.")
        users.set_active_user(user.id)
        token = sessions.create(user.id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return _auth_payload(user, token)


@app.post("/api/auth/register")
async def auth_register(body: CreateUserRequest) -> dict[str, Any]:
    """Verejné vytvorenie bežného účtu + okamžité prihlásenie."""
    level = body.preferred_level if body.preferred_level in LEVELS else "A2"
    name = body.name.strip()
    if name.casefold() == UserManager.ADMIN_NAME.casefold():
        raise HTTPException(status_code=409, detail="Meno Administrator je rezervované.")
    try:
        user = users.create_user(name, preferred_level=level, password=body.password, role="user")
        users.set_active_user(user.id)
        token = sessions.create(user.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _auth_payload(user, token)


@app.post("/api/users")
async def create_user(
    body: CreateUserRequest,
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    """Admin môže vytvoriť účet bez prepnutia session; inak rovnaké ako register."""
    auth_uid = _optional_user(authorization, x_session_token)
    if auth_uid:
        actor = users.get_user(auth_uid)
        if actor.is_admin():
            level = body.preferred_level if body.preferred_level in LEVELS else "A2"
            name = body.name.strip()
            if name.casefold() == UserManager.ADMIN_NAME.casefold():
                raise HTTPException(status_code=409, detail="Meno Administrator je rezervované.")
            try:
                user = users.create_user(
                    name, preferred_level=level, password=body.password, role="user"
                )
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            return {"user": user.public_dict(), "created_by": auth_uid}
    return await auth_register(body)


@app.post("/api/auth/logout")
async def auth_logout(
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    sessions.revoke(_token_from_headers(authorization, x_session_token))
    return {"ok": True}


@app.get("/api/auth/me")
async def auth_me(
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    uid = _require_user(authorization, x_session_token)
    user = users.get_user(uid)
    store = users.store(uid)
    return {
        "user": user.public_dict(),
        "active_user_id": uid,
        "learning_count": len(store.all_items()),
    }


@app.get("/api/topics")
async def get_topics(
    user_id: str | None = None,
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    auth_uid = _require_user(authorization, x_session_token)
    uid = _resolve_user_id(user_id, auth_uid=auth_uid)
    return {"user_id": uid, "topics": users.topics(uid).list_topics()}


@app.get("/api/settings")
async def get_lesson_settings(
    user_id: str | None = None,
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    auth_uid = _require_user(authorization, x_session_token)
    uid = _resolve_user_id(user_id, auth_uid=auth_uid)
    return {"user_id": uid, "settings": users.settings(uid).read()}


@app.put("/api/settings")
async def put_lesson_settings(
    body: LessonSettingsRequest,
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    auth_uid = _require_user(authorization, x_session_token)
    uid = _resolve_user_id(body.user_id, auth_uid=auth_uid)
    saved = users.settings(uid).write(body.settings or {})
    return {"user_id": uid, "settings": saved}


@app.get("/api/stats")
async def get_user_stats(
    user_id: str | None = None,
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    auth_uid = _require_user(authorization, x_session_token)
    uid = _resolve_user_id(user_id, auth_uid=auth_uid)
    payload = {"user_id": uid, **users.stats(uid).summary()}
    # Enrich vocabulary skill from known learning-store items when available.
    try:
        items = users.store(uid).all_items()
        if items:
            known = sum(1 for i in items if i.status == "known")
            skills = dict(payload.get("skills") or {})
            skills["vocabulary"] = max(
                0, min(100, int(round(100.0 * known / len(items))))
            )
            payload["skills"] = skills
    except Exception:  # noqa: BLE001
        pass
    return payload


@app.get("/api/scenarios")
async def get_scenarios(topic_id: str | None = None) -> dict[str, Any]:
    """Curated role-play scenarios for quick start (travel / work / daily)."""
    return {"scenarios": list_scenarios(topic_id=topic_id)}


async def _llm_semantic_topic_check(
    *,
    label: str,
    description: str,
    existing: list[dict[str, Any]],
    kind: str,
) -> dict[str, Any] | None:
    """Optional LLM meaning check. Returns match info or None if unavailable/no dup."""
    if not settings.available_llm_providers():
        return None
    try:
        llm = get_provider(settings, settings.default_llm_provider)
    except ValueError:
        return None
    catalog = "\n".join(
        f"- id={t['id']}; label={t['label']}; subs={[s['label'] for s in t.get('subtopics', [])]}"
        for t in existing
    )
    prompt = (
        f"You check if a new English-learning {kind} already exists by meaning.\n"
        f"New {kind} label: {label}\n"
        f"Description: {description or '(none)'}\n"
        f"Existing catalog:\n{catalog}\n\n"
        "Mark duplicate=true ONLY if the new item is essentially the SAME lesson "
        "(same meaning / same scenario), not merely related or under the same broad theme.\n"
        "Example: 'Opening a bank account' is NOT a duplicate of 'bank accounts' general overview.\n"
        "Example: 'Airport check-in' IS a duplicate of 'Checking in at the airport'.\n"
        "Return ONLY JSON: "
        '{"duplicate": true/false, "match_id": "id or null", "match_label": "...", "reason": "short"}'
    )
    try:
        data = await llm.chat_json(
            [{"role": "user", "content": prompt}],
            system="Return JSON only. Prefer duplicate=true for same meaning even if wording differs.",
        )
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    if not data.get("duplicate"):
        return None
    return {
        "id": data.get("match_id"),
        "label": data.get("match_label") or data.get("match_id"),
        "score": 0.9,
        "exact": False,
        "reason": data.get("reason") or "LLM: similar meaning",
    }


def _strong_duplicates(local: list[dict], llm_match: dict | None) -> list[dict]:
    """Block only clear duplicates; LLM alone is not enough without local support."""
    strong = [m for m in local if m.get("exact") or float(m.get("score") or 0) >= 0.85]
    best_local = max((float(m.get("score") or 0) for m in local), default=0.0)
    if llm_match and (best_local >= 0.62 or any(m.get("exact") for m in local)):
        if not any(m.get("id") and m.get("id") == llm_match.get("id") for m in strong):
            strong.insert(0, llm_match)
    return strong


@app.post("/api/topics/check")
async def check_topic(
    body: CheckTopicRequest,
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    auth_uid = _require_user(authorization, x_session_token)
    uid = _resolve_user_id(body.user_id, auth_uid=auth_uid)
    store = users.topics(uid)

    if body.kind == "subtopic":
        if not body.topic_id:
            raise HTTPException(status_code=400, detail="topic_id je povinné pre podtému")
        try:
            local = store.find_similar_subtopics(body.topic_id, body.label)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        existing = store.list_topics()
        topic = next((t for t in existing if t["id"] == body.topic_id), None)
        llm_match = None
        if topic:
            llm_match = await _llm_semantic_topic_check(
                label=body.label,
                description=body.description,
                existing=[{"id": s["id"], "label": s["label"], "subtopics": []} for s in topic["subtopics"]],
                kind="subtopic",
            )
    else:
        local = store.find_similar_topics(body.label, description=body.description)
        llm_match = await _llm_semantic_topic_check(
            label=body.label,
            description=body.description,
            existing=store.list_topics(),
            kind="topic",
        )

    matches = list(local)
    if llm_match and not any(m.get("id") == llm_match.get("id") for m in matches):
        matches.insert(0, llm_match)
    strong = _strong_duplicates(local, llm_match)
    return {"ok": not bool(strong), "matches": matches, "user_id": uid}


@app.post("/api/topics")
async def add_topic(
    body: AddTopicRequest,
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    auth_uid = _require_user(authorization, x_session_token)
    uid = _resolve_user_id(body.user_id, auth_uid=auth_uid)
    users.set_active_user(uid)
    store = users.topics(uid)

    if not body.force:
        local = store.find_similar_topics(body.label, description=body.description)
        llm_match = await _llm_semantic_topic_check(
            label=body.label,
            description=body.description,
            existing=store.list_topics(),
            kind="topic",
        )
        strong = _strong_duplicates(local, llm_match)
        if strong:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Podobná téma už existuje.",
                    "matches": strong,
                },
            )
    try:
        created = store.add_topic(body.label, description=body.description, force=body.force)
    except TopicDuplicateError as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": str(exc), "matches": exc.matches},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"user_id": uid, "topic": created, "topics": store.list_topics()}


@app.post("/api/topics/subtopics")
async def add_subtopic(
    body: AddSubtopicRequest,
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    auth_uid = _require_user(authorization, x_session_token)
    uid = _resolve_user_id(body.user_id, auth_uid=auth_uid)
    users.set_active_user(uid)
    store = users.topics(uid)

    if not body.force:
        try:
            local = store.find_similar_subtopics(body.topic_id, body.label)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        topic = next((t for t in store.list_topics() if t["id"] == body.topic_id), None)
        llm_match = None
        if topic:
            llm_match = await _llm_semantic_topic_check(
                label=body.label,
                description=body.description,
                existing=[{"id": s["id"], "label": s["label"], "subtopics": []} for s in topic["subtopics"]],
                kind="subtopic",
            )
        strong = _strong_duplicates(local, llm_match)
        if strong:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Podobná podtéma už existuje.",
                    "matches": strong,
                },
            )
    try:
        created = store.add_subtopic(
            body.topic_id,
            body.label,
            description=body.description,
            force=body.force,
        )
    except TopicDuplicateError as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": str(exc), "matches": exc.matches},
        ) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"user_id": uid, "subtopic": created, "topics": store.list_topics()}


@app.get("/api/users")
async def list_users(
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    uid = _require_user(authorization, x_session_token)
    me = users.get_user(uid)
    if me.is_admin():
        listed = [u.public_dict() for u in users.list_users()]
    else:
        listed = [me.public_dict()]
    return {
        "active_user_id": uid,
        "users": listed,
        "is_admin": me.is_admin(),
    }


@app.patch("/api/users/{user_id}")
async def rename_user(
    user_id: str,
    body: RenameUserRequest,
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    auth_uid = _require_user(authorization, x_session_token)
    actor = users.get_user(auth_uid)
    if user_id != auth_uid and not actor.is_admin():
        raise HTTPException(status_code=403, detail="Môžeš premenovať len svoj účet.")
    try:
        user = users.rename_user(user_id, body.name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"user": user.public_dict()}


@app.delete("/api/users/{user_id}")
async def delete_user(
    user_id: str,
    body: DeleteUserRequest,
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    auth_uid = _require_user(authorization, x_session_token)
    token = _token_from_headers(authorization, x_session_token)
    actor = users.get_user(auth_uid)
    if user_id != auth_uid and not actor.is_admin():
        raise HTTPException(status_code=403, detail="Môžeš zmazať len svoj účet.")
    try:
        users.delete_user(user_id, password=body.password, actor_id=auth_uid)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if user_id == auth_uid:
        sessions.revoke(token)
    sessions.revoke_user(user_id)
    for sid, sess in list(reading_engine.sessions.items()):
        if getattr(sess, "user_id", None) == user_id:
            reading_engine.sessions.pop(sid, None)
    for sid, sess in list(conversation_engine.sessions.items()):
        if getattr(sess, "user_id", None) == user_id:
            conversation_engine.sessions.pop(sid, None)
    return {"ok": True}


@app.get("/api/users/{user_id}/profile")
async def user_profile(
    user_id: str,
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    auth_uid = _require_user(authorization, x_session_token)
    actor = users.get_user(auth_uid)
    if user_id != auth_uid and not actor.is_admin():
        raise HTTPException(status_code=403, detail="Môžeš vidieť len svoj profil.")
    return {
        "profile": users.read_profile(user_id),
        "history_tail": users.read_history(user_id),
    }


@app.get("/api/voices")
async def voices(provider: str | None = None) -> dict[str, Any]:
    try:
        name = normalize_tts_provider(provider or settings.tts_provider)
        engine = get_tts(settings, name)
        items = await engine.list_voices()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"TTS voices: {exc}") from exc
    return {"provider": name, "voices": items}


@app.get("/api/learning")
async def learning_items(
    user_id: str | None = None,
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    auth_uid = _require_user(authorization, x_session_token)
    uid = _resolve_user_id(user_id, auth_uid=auth_uid)
    store = users.store(uid)
    items = [
        {
            "kind": i.kind,
            "word": i.word,
            "translation_sk": i.translation_sk,
            "level": i.level,
            "topic": i.topic,
            "tip": i.tip,
            "times_seen": i.times_seen,
            "times_correct": i.times_correct,
            "next_review": i.next_review,
            "status": i.status,
            "significance": i.significance,
        }
        for i in store.all_items()
    ]
    return {
        "user_id": uid,
        "items": items,
        "due": [
            {"word": i.word, "significance": i.significance, "kind": i.kind}
            for i in store.list_due(limit=10)
        ],
    }


@app.delete("/api/learning")
async def delete_learning_item(
    body: DeleteLearningRequest,
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    auth_uid = _require_user(authorization, x_session_token)
    uid = _resolve_user_id(body.user_id, auth_uid=auth_uid)
    kind = (body.kind or "").strip()
    word = (body.word or "").strip()
    if kind not in MarkdownLearningStore.FILES:
        raise HTTPException(status_code=400, detail="Neplatný typ položky.")
    store = users.store(uid)
    deleted = store.delete_item(word, kind=kind)
    if not deleted:
        raise HTTPException(status_code=404, detail="Položka sa nenašla.")
    users.sync_weak_areas_from_store(uid)
    return {"ok": True, "user_id": uid, "kind": kind, "word": word}


@app.post("/api/learning/practice")
async def practice_learning(
    body: PracticeLearningRequest,
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    auth_uid = _require_user(authorization, x_session_token)
    try:
        uid = _resolve_user_id(body.user_id, auth_uid=auth_uid)
        users.set_active_user(uid)
        level = body.level or settings.default_level
        if level not in LEVELS:
            raise HTTPException(status_code=400, detail="Neplatná úroveň.")
        llm = get_provider(settings, body.llm_provider, body.llm_model)
        tts_name = normalize_tts_provider(body.tts_provider or settings.tts_provider)
    except (ValueError, KeyError, HTTPException) as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    voice_id = body.voice_id or default_voice_for(settings, tts_name)
    speech_rate = clamp_speech_rate(
        body.speech_rate if body.speech_rate is not None else settings.speech_rate
    )
    sentence_count = max(2, min(100, int(body.sentence_count or 20)))
    store = users.store(uid)
    try:
        session = await reading_engine.start_practice(
            store=store,
            llm=llm,
            user_id=uid,
            level=level,
            provider_name=llm.name,
            llm_model=getattr(llm, "model", "") or body.llm_model or "",
            voice_id=voice_id,
            tts_provider=tts_name,
            speech_rate=speech_rate,
            sentence_count=sentence_count,
            practice_kind=body.kind,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    users.append_history(
        uid,
        f"**Practice reading** ({body.kind})\n"
        f"Targets: {', '.join(session.practice_targets)}\n"
        f"Title: {session.title}",
    )
    return {
        "mode": "reading",
        "practice": True,
        "practice_kind": session.practice_kind,
        "practice_targets": session.practice_targets,
        "session_id": session.id,
        "user_id": uid,
        "title": session.title,
        "text": session.text,
        "highlighted_html": session.highlighted_html,
        "phase": session.phase,
        "sentence_count": session.sentence_count,
        "tts_provider": tts_name,
        "speech_rate": speech_rate,
        "key_phrases": session.key_phrases,
    }


def _finish_previous_session_notes(
    *,
    user_id: str,
    mode: str,
    topic: str,
    level: str,
    due_words: list[str],
    restart: bool,
) -> None:
    users.sync_weak_areas_from_store(user_id)
    flag = "RESTART" if restart else "START"
    users.append_history(
        user_id,
        f"**{flag} {mode}** · level={level} · topic={topic}\n"
        f"Due review: {', '.join(due_words) if due_words else '(none)'}",
    )


def _record_conversation_stats(session) -> dict[str, Any] | None:
    """Persist one conversation into users/<id>/stats.json (once)."""
    entry = conversation_engine.conversation_stats_entry(session)
    if not entry:
        return None
    ended_at = entry.pop("ended_at", None)
    summary = users.stats(session.user_id).record_conversation(
        ended_at=ended_at,
        **entry,
    )
    session.stats_recorded = True
    mins = max(1, int(round(entry["duration_sec"] / 60))) if entry["duration_sec"] else 0
    users.append_history(
        session.user_id,
        f"**END conversation** · {entry.get('topic')} · "
        f"questions={entry['questions']} · wrongs={entry['wrongs']} · "
        f"~{mins} min · continued={entry['continued']} · completed={entry['completed']}",
    )
    return summary


def _finalize_closed_conversations(user_id: str) -> None:
    for old in conversation_engine.close_user_sessions(user_id):
        try:
            _record_conversation_stats(old)
        except Exception:  # noqa: BLE001
            pass


@app.post("/api/session/abandon")
async def session_abandon(
    body: SessionIdBody,
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    """Zruší lekciu bez zápisu do štatistík a bez návratu."""
    auth_uid = _require_user(authorization, x_session_token)
    sid = (body.session_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="Chýba session_id.")

    mode = "conversation"
    try:
        existing = conversation_engine.get(sid)
    except KeyError:
        try:
            existing = reading_engine.get(sid)
            mode = "reading"
        except KeyError:
            return {"ok": True, "abandoned": True, "session_id": sid, "mode": None}

    _assert_session_owner(existing.user_id, auth_uid)
    if mode == "conversation":
        conversation_engine.abandon_session(sid)
    else:
        reading_engine.abandon_session(sid)
    users.append_history(
        existing.user_id,
        f"**ABANDONED {mode}** · session zrušená bez štatistík",
    )
    return {"ok": True, "abandoned": True, "session_id": sid, "mode": mode}


@app.post("/api/session/start")
async def session_start(
    body: StartRequest,
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    if body.level not in LEVELS:
        raise HTTPException(status_code=400, detail="Neplatná úroveň. Použi A2, B1 alebo B2.")
    auth_uid = _require_user(authorization, x_session_token)
    try:
        uid = _resolve_user_id(body.user_id, auth_uid=auth_uid)
        users.set_active_user(uid)
        llm = get_provider(settings, body.llm_provider, body.llm_model)
        tts_name = normalize_tts_provider(body.tts_provider or settings.tts_provider)
    except (ValueError, KeyError, HTTPException) as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    voice_id = body.voice_id or default_voice_for(settings, tts_name)
    speech_rate = clamp_speech_rate(
        body.speech_rate if body.speech_rate is not None else settings.speech_rate
    )
    min_q = max(2, min(80, int(body.min_questions or 20)))
    sentence_count = max(2, min(100, int(body.sentence_count or 20)))
    store = users.store(uid)
    user_context = users.tutor_context(uid)
    curated = get_scenario(body.scenario_id)
    topic = body.topic
    subtopic = body.subtopic
    if curated and body.mode != "free_debate":
        topic = str(curated.get("topic") or topic)
        subtopic = curated.get("subtopic") or subtopic
        scenario = str(
            curated.get("scenario_en")
            or curated.get("blurb_sk")
            or curated.get("title")
            or ""
        )
        if curated.get("min_questions") and not body.restart:
            min_q = max(2, min(80, int(curated.get("min_questions") or min_q)))
    else:
        scenario = users.topics(uid).resolve_scenario(topic, subtopic)

    if body.mode in ("conversation", "free_debate"):
        free = body.mode == "free_debate"
        _finalize_closed_conversations(uid)
        session = conversation_engine.start(
            store=store,
            user_id=uid,
            level=body.level,
            topic=topic,
            subtopic=subtopic,
            provider_name=llm.name,
            llm_model=getattr(llm, "model", "") or body.llm_model or "",
            voice_id=voice_id,
            tts_provider=tts_name,
            speech_rate=speech_rate,
            min_questions=min_q,
            restart=body.restart,
            free_debate=free,
            user_context=user_context,
            scenario=scenario,
            scenario_id=(curated or {}).get("id") if curated and not free else None,
        )
        reply = await conversation_engine.opening_message(session, llm)
        added_facts = users.append_about_learner(uid, list(session.learned_facts))
        audio_b64 = await _speak_required(reply, voice_id, tts_name, speech_rate)
        mode_name = "free_debate" if free else "conversation"
        topic_label = session.suggested_topic or topic
        if curated and not free:
            topic_label = str(curated.get("title") or topic_label)
        _finish_previous_session_notes(
            user_id=uid,
            mode=mode_name,
            topic=topic_label,
            level=body.level,
            due_words=session.due_words,
            restart=body.restart and not free,
        )
        users.append_profile_note(
            uid,
            f"{'Free debate' if free else ('Restart' if body.restart else 'Lesson')} "
            f"{mode_name}/{topic_label} at {body.level}; "
            f"review={', '.join(session.due_words[:5]) or 'none'}",
        )
        return {
            "mode": mode_name,
            "session_id": session.id,
            "user_id": uid,
            "reply": reply,
            "audio_base64": audio_b64,
            "due_words": session.due_words,
            "suggested_topic": session.suggested_topic,
            "learned_facts": added_facts,
            "phase": "free_debate"
            if free
            else ("review" if body.restart and session.due_words else "conversation"),
            "tts_provider": tts_name,
            "speech_rate": speech_rate,
            "min_questions": session.min_questions,
            "questions_asked": session.questions_asked,
            "question_batch": session.question_batch,
            "question_target": session.question_target,
            "awaiting_continue": session.awaiting_continue,
            "conversation_phase": session.phase,
            "restart": body.restart and not free,
            "free_debate": free,
            "scenario_id": getattr(session, "scenario_id", None) or None,
            "scenario_title": (curated or {}).get("title") if curated and not free else None,
        }

    session = await reading_engine.start(
        store=store,
        llm=llm,
        user_id=uid,
        level=body.level,
        topic=topic,
        subtopic=subtopic,
        provider_name=llm.name,
        llm_model=getattr(llm, "model", "") or body.llm_model or "",
        voice_id=voice_id,
        tts_provider=tts_name,
        speech_rate=speech_rate,
        min_questions=min_q,
        sentence_count=sentence_count,
        restart=body.restart,
        user_context=user_context,
        scenario=scenario,
    )
    # Pri generovaní textu neprehrávame TTS — používateľ stlačí Prehrať vzor / Štart čítania
    due_words = [i.word for i in store.list_due(limit=8)]
    _finish_previous_session_notes(
        user_id=uid,
        mode="reading",
        topic=topic,
        level=body.level,
        due_words=due_words,
        restart=body.restart,
    )
    users.append_profile_note(
        uid,
        f"{'Restart' if body.restart else 'Generate'} reading/{topic} "
        f"at {body.level}; sentences~{sentence_count}; questions={len(session.questions)}",
    )
    return {
        "mode": "reading",
        "session_id": session.id,
        "user_id": uid,
        "title": session.title,
        "text": session.text,
        "highlighted_html": session.highlighted_html,
        "key_phrases": session.key_phrases,
        "audio_base64": None,
        "phase": session.phase,
        "questions_count": len(session.questions),
        "sentence_count": session.sentence_count,
        "tts_provider": tts_name,
        "speech_rate": speech_rate,
        "min_questions": session.min_questions,
        "restart": body.restart,
        "due_words": due_words,
    }


async def _speak_required(
    text: str,
    voice_id: str | None,
    tts_provider: str | None = None,
    speech_rate: float = 1.0,
) -> str:
    try:
        engine = get_tts(settings, tts_provider, voice_id)
        # Rýchlosť riadi frontend cez HTMLAudioElement.playbackRate
        # (spoľahlivejšie než Edge prosody %, ktoré často znie rovnako).
        # speech_rate ostáva v session / API pre kompatibilitu a ukážky.
        _ = clamp_speech_rate(speech_rate)
        audio = await engine.synthesize(text, voice_id=voice_id, rate=1.0)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"TTS: {exc}") from exc
    return base64.b64encode(audio).decode("ascii")


@app.post("/api/speak")
async def speak(body: SpeakRequest) -> Response:
    try:
        tts_name = normalize_tts_provider(body.tts_provider or settings.tts_provider)
        # Prehrávanie v UI nastaví playbackRate; tu necháme normálne tempo.
        engine = get_tts(settings, tts_name, body.voice_id)
        audio = await engine.synthesize(body.text, voice_id=body.voice_id, rate=1.0)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=audio, media_type="audio/mpeg")


def _assert_session_owner(session_user_id: str, auth_uid: str) -> None:
    if session_user_id != auth_uid:
        raise HTTPException(status_code=403, detail="Táto lekcia nepatrí tvojmu účtu.")


def _session_speech_rate(session: Any, rate: float | None = None) -> float:
    """Aktualizuj rýchlosť reči v session (UI môže meniť mid-session)."""
    if rate is not None:
        session.speech_rate = clamp_speech_rate(rate)
    return clamp_speech_rate(getattr(session, "speech_rate", None), default=1.0)


def _log_conversation_turn(
    session, user_text: str, reply: str, *, facts: list[str] | None = None
) -> list[str]:
    users.append_history(
        session.user_id,
        f"**User:** {user_text}\n\n**Tutor:** {reply}",
    )
    added: list[str] = []
    if facts:
        added = users.append_about_learner(session.user_id, facts)
        if added:
            users.append_history(
                session.user_id,
                "**Learned about user:** " + "; ".join(added),
            )
    users.sync_weak_areas_from_store(session.user_id)
    return added


@app.post("/api/conversation/turn")
async def conversation_turn(
    body: TextTurnRequest,
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    auth_uid = _require_user(authorization, x_session_token)
    try:
        session = conversation_engine.get(body.session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _assert_session_owner(session.user_id, auth_uid)
    speech_rate = _session_speech_rate(session, body.speech_rate)
    llm = get_provider(settings, session.provider_name, getattr(session, "llm_model", None) or None)
    raw_text = body.text.strip()
    result = await conversation_engine.user_turn(session, llm, raw_text, from_stt=False)
    facts = list(result.get("learned_facts") or [])
    display = (result.get("transcript_display") or result.get("said") or raw_text).strip()
    added = _log_conversation_turn(session, display, result["reply"], facts=facts)
    stats_summary = None
    if result.get("phase") == "done":
        stats_summary = _record_conversation_stats(session)
    audio_b64 = await _speak_required(
        result["reply"], session.voice_id, session.tts_provider, speech_rate
    )
    out = {**result, "audio_base64": audio_b64, "learned_facts": added, "speech_rate": speech_rate}
    if stats_summary:
        out["stats"] = stats_summary
    return out


@app.post("/api/conversation/utterance")
async def conversation_utterance(
    session_id: str = Form(...),
    audio: UploadFile = File(...),
    speech_rate: float | None = Form(None),
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    auth_uid = _require_user(authorization, x_session_token)
    try:
        session = conversation_engine.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _assert_session_owner(session.user_id, auth_uid)
    rate = _session_speech_rate(session, speech_rate)
    raw = await audio.read()
    try:
        transcript = await _stt(settings).transcribe(raw, filename=audio.filename or "audio.webm")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Whisper STT: {exc}") from exc
    if not transcript:
        # Whisper often invents words from silence; treat as no speech (not a hard failure).
        return {
            "transcript": "",
            "reply": "",
            "audio_base64": None,
            "no_speech": True,
            "detail": "Nepočul som ťa — skús znova držať mikrofón a hovoriť jasnejšie.",
            "speech_rate": rate,
        }
    llm = get_provider(settings, session.provider_name, getattr(session, "llm_model", None) or None)
    result = await conversation_engine.user_turn(session, llm, transcript, from_stt=True)
    facts = list(result.get("learned_facts") or [])
    display = (result.get("transcript_display") or result.get("said") or transcript).strip()
    added = _log_conversation_turn(session, display, result["reply"], facts=facts)
    stats_summary = None
    if result.get("phase") == "done":
        stats_summary = _record_conversation_stats(session)
    audio_b64 = await _speak_required(
        result["reply"], session.voice_id, session.tts_provider, rate
    )
    out = {
        **result,
        "transcript": display,
        "transcript_raw": transcript,
        "audio_base64": audio_b64,
        "learned_facts": added,
        "speech_rate": rate,
        "no_speech": False,
    }
    if stats_summary:
        out["stats"] = stats_summary
    return out


@app.post("/api/reading/begin")
async def reading_begin(
    body: SessionIdBody,
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    auth_uid = _require_user(authorization, x_session_token)
    try:
        session = reading_engine.get(body.session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _assert_session_owner(session.user_id, auth_uid)
    return reading_engine.begin_reading(session)


@app.post("/api/reading/evaluate")
async def reading_evaluate(
    session_id: str = Form(...),
    audio: UploadFile | None = File(None),
    transcript: str | None = Form(None),
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    auth_uid = _require_user(authorization, x_session_token)
    try:
        session = reading_engine.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _assert_session_owner(session.user_id, auth_uid)

    text = (transcript or "").strip()
    if audio is not None:
        raw = await audio.read()
        if raw:
            try:
                text = await _stt(settings).transcribe(raw, filename=audio.filename or "audio.webm")
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=502, detail=f"Whisper STT: {exc}") from exc
    if not text:
        raise HTTPException(status_code=400, detail="Chýba transcript alebo audio.")

    llm = get_provider(settings, session.provider_name, getattr(session, "llm_model", None) or None)
    result = await reading_engine.evaluate_reading(session, llm, text)
    users.append_history(
        session.user_id,
        f"**Reading attempt** ({session.title})\nHeard: {text}\n"
        f"Wrong words: {', '.join(result.get('wrong_words') or []) or '(none)'}",
    )
    users.sync_weak_areas_from_store(session.user_id)
    feedback_audio = None
    if result.get("overall_feedback"):
        feedback_audio = await _speak_required(
            result["overall_feedback"],
            session.voice_id,
            session.tts_provider,
            session.speech_rate,
        )
    return {**result, "feedback_audio_base64": feedback_audio}


@app.post("/api/reading/explain")
async def reading_explain(
    session_id: str = Form(...),
    audio: UploadFile | None = File(None),
    text: str | None = Form(None),
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    auth_uid = _require_user(authorization, x_session_token)
    try:
        session = reading_engine.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _assert_session_owner(session.user_id, auth_uid)

    answer = (text or "").strip()
    if audio is not None:
        raw = await audio.read()
        if raw:
            try:
                answer = await _stt(settings).transcribe(raw, filename=audio.filename or "audio.webm")
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=502, detail=f"Whisper STT: {exc}") from exc
    if not answer:
        raise HTTPException(status_code=400, detail="Chýba vysvetlenie.")

    llm = get_provider(settings, session.provider_name, getattr(session, "llm_model", None) or None)
    result = await reading_engine.evaluate_explanation(session, llm, answer)
    users.append_history(
        session.user_id,
        f"**Explanation** ({session.title}): "
        f"{'OK' if result.get('correct') else 'MISS'} — {answer}",
    )
    users.sync_weak_areas_from_store(session.user_id)
    audio_b64 = None
    if result.get("feedback"):
        audio_b64 = await _speak_required(
            result["feedback"], session.voice_id, session.tts_provider, session.speech_rate
        )
    return {**result, "audio_base64": audio_b64}


@app.post("/api/reading/start-debate")
@app.post("/api/reading/start-comprehension")
async def reading_start_debate(
    body: SessionIdBody,
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    auth_uid = _require_user(authorization, x_session_token)
    try:
        session = reading_engine.get(body.session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _assert_session_owner(session.user_id, auth_uid)
    payload = reading_engine.begin_debate(session)
    audio_b64 = None
    q = payload.get("question")
    if q and q.get("question"):
        audio_b64 = await _speak_required(
            str(q["question"]), session.voice_id, session.tts_provider, session.speech_rate
        )
    return {**payload, "audio_base64": audio_b64}


@app.post("/api/reading/comprehension")
@app.post("/api/reading/debate")
async def reading_debate(
    session_id: str = Form(...),
    audio: UploadFile | None = File(None),
    text: str | None = Form(None),
    authorization: str | None = Header(None),
    x_session_token: str | None = Header(None),
) -> dict[str, Any]:
    auth_uid = _require_user(authorization, x_session_token)
    try:
        session = reading_engine.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _assert_session_owner(session.user_id, auth_uid)

    answer = (text or "").strip()
    if audio is not None:
        raw = await audio.read()
        if raw:
            try:
                answer = await _stt(settings).transcribe(raw, filename=audio.filename or "audio.webm")
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=502, detail=f"Whisper STT: {exc}") from exc
    if not answer:
        raise HTTPException(status_code=400, detail="Chýba odpoveď.")

    llm = get_provider(settings, session.provider_name, getattr(session, "llm_model", None) or None)
    result = await comprehension_engine.answer(session, llm, answer)
    users.append_history(
        session.user_id,
        f"**Debate** Q{result.get('question_index')}/{result.get('total')}: "
        f"{'OK' if result.get('correct') else 'MISS'} — {answer}",
    )
    users.sync_weak_areas_from_store(session.user_id)
    speak_text = result.get("feedback") or ""
    next_q = result.get("next_question")
    if next_q and next_q.get("question"):
        speak_text = f"{speak_text} Next question: {next_q['question']}"
    audio_b64 = (
        await _speak_required(
            speak_text, session.voice_id, session.tts_provider, session.speech_rate
        )
        if speak_text
        else None
    )
    return {**result, "answer_transcript": answer, "audio_base64": audio_b64}
