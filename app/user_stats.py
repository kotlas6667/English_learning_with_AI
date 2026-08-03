from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

RECENT_MAX = 20


def _default_conversation() -> dict[str, Any]:
    return {
        "total": 0,
        "completed": 0,
        "total_seconds": 0,
        "total_questions": 0,
        "total_wrongs": 0,
        "streak_days": 0,
        "best_streak_days": 0,
        "last_date": "",
        "recent": [],
    }


def empty_stats() -> dict[str, Any]:
    return {"conversation": _default_conversation()}


def _parse_day(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def compute_success_rate(*, questions: int, wrongs: int) -> float:
    if questions <= 0:
        return 0.0
    ok = max(0, questions - max(0, wrongs))
    return round(100.0 * ok / questions, 1)


def _clamp_skill(value: float) -> int:
    return max(0, min(100, int(round(value))))


def compute_skills(
    *,
    total_seconds: int,
    total_questions: int,
    total_wrongs: int,
) -> dict[str, int]:
    """Simple 0–100 heuristics from conversation aggregates."""
    minutes = max(0.0, total_seconds / 60.0)
    questions = max(0, total_questions)
    wrongs = max(0, total_wrongs)
    success = compute_success_rate(questions=questions, wrongs=wrongs)
    # Speaking: more talk time + more answered questions → higher (soft ramp).
    speaking = _clamp_skill(minutes * 4.0 + questions * 1.5) if (minutes or questions) else 0
    accuracy = _clamp_skill(success)
    if questions <= 0:
        vocabulary = 50
    else:
        # Inverse of wrong rate; empty practice stays at neutral 50.
        vocabulary = _clamp_skill(100.0 * (1.0 - (wrongs / questions)))
    return {
        "speaking": speaking,
        "vocabulary": vocabulary,
        "accuracy": accuracy,
    }


def apply_streak(conv: dict[str, Any], day: date) -> None:
    last = _parse_day(str(conv.get("last_date") or ""))
    if last == day:
        if int(conv.get("streak_days") or 0) <= 0:
            conv["streak_days"] = 1
    elif last == day - timedelta(days=1):
        conv["streak_days"] = int(conv.get("streak_days") or 0) + 1
    else:
        conv["streak_days"] = 1
    conv["best_streak_days"] = max(
        int(conv.get("best_streak_days") or 0),
        int(conv.get("streak_days") or 0),
    )
    conv["last_date"] = day.isoformat()


def compute_today_minutes(recent: list[Any], *, today: date | None = None) -> float:
    """Sum duration of sessions that ended on the given local calendar day."""
    day = today or date.today()
    total_sec = 0
    for entry in recent or []:
        if not isinstance(entry, dict):
            continue
        ended = _parse_day(str(entry.get("ended_at") or ""))
        if ended != day:
            continue
        total_sec += max(0, int(entry.get("duration_sec") or 0))
    return round(total_sec / 60.0, 1)


class UserStatsStore:
    """Per-user aggregate lesson statistics in stats.json."""

    def __init__(self, user_dir: Path) -> None:
        self.user_dir = Path(user_dir)
        self.path = self.user_dir / "stats.json"
        self.user_dir.mkdir(parents=True, exist_ok=True)

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return empty_stats()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return empty_stats()
        if not isinstance(data, dict):
            return empty_stats()
        conv = data.get("conversation")
        if not isinstance(conv, dict):
            data["conversation"] = _default_conversation()
        else:
            base = _default_conversation()
            base.update(conv)
            if not isinstance(base.get("recent"), list):
                base["recent"] = []
            data["conversation"] = base
        return data

    def write(self, data: dict[str, Any]) -> dict[str, Any]:
        clean = data if isinstance(data, dict) else empty_stats()
        self.path.write_text(
            json.dumps(clean, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return clean

    def summary(self) -> dict[str, Any]:
        data = self.read()
        conv = data["conversation"]
        questions = int(conv.get("total_questions") or 0)
        wrongs = int(conv.get("total_wrongs") or 0)
        seconds = int(conv.get("total_seconds") or 0)
        return {
            "conversation": {
                **conv,
                "success_rate": compute_success_rate(questions=questions, wrongs=wrongs),
                "total_minutes": round(seconds / 60.0, 1),
                "today_minutes": compute_today_minutes(list(conv.get("recent") or [])),
            },
            "skills": compute_skills(
                total_seconds=seconds,
                total_questions=questions,
                total_wrongs=wrongs,
            ),
        }

    def record_conversation(
        self,
        *,
        duration_sec: int,
        questions: int,
        wrongs: int,
        completed: bool,
        continued: bool,
        topic: str,
        level: str,
        free_debate: bool,
        ended_at: datetime | None = None,
    ) -> dict[str, Any]:
        data = self.read()
        conv = data["conversation"]
        ended = ended_at or datetime.now()
        duration_sec = max(0, int(duration_sec))
        questions = max(0, int(questions))
        wrongs = max(0, int(wrongs))

        conv["total"] = int(conv.get("total") or 0) + 1
        if completed:
            conv["completed"] = int(conv.get("completed") or 0) + 1
        conv["total_seconds"] = int(conv.get("total_seconds") or 0) + duration_sec
        conv["total_questions"] = int(conv.get("total_questions") or 0) + questions
        conv["total_wrongs"] = int(conv.get("total_wrongs") or 0) + wrongs
        apply_streak(conv, ended.date())

        entry = {
            "ended_at": ended.isoformat(timespec="seconds"),
            "duration_sec": duration_sec,
            "questions": questions,
            "wrongs": wrongs,
            "success_rate": compute_success_rate(questions=questions, wrongs=wrongs),
            "completed": completed,
            "continued": continued,
            "topic": (topic or "")[:80],
            "level": (level or "")[:8],
            "free_debate": bool(free_debate),
        }
        recent = list(conv.get("recent") or [])
        recent.insert(0, entry)
        conv["recent"] = recent[:RECENT_MAX]
        data["conversation"] = conv
        self.write(data)
        return self.summary()
