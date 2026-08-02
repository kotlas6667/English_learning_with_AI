from datetime import date, datetime, timedelta
from pathlib import Path

from app.user_stats import (
    UserStatsStore,
    apply_streak,
    compute_success_rate,
    empty_stats,
)


def test_success_rate():
    assert compute_success_rate(questions=0, wrongs=0) == 0.0
    assert compute_success_rate(questions=10, wrongs=2) == 80.0
    assert compute_success_rate(questions=5, wrongs=5) == 0.0


def test_streak_consecutive_days():
    conv = empty_stats()["conversation"]
    d0 = date(2026, 8, 1)
    apply_streak(conv, d0)
    assert conv["streak_days"] == 1
    apply_streak(conv, d0 + timedelta(days=1))
    assert conv["streak_days"] == 2
    apply_streak(conv, d0 + timedelta(days=1))  # same day
    assert conv["streak_days"] == 2
    apply_streak(conv, d0 + timedelta(days=3))  # gap
    assert conv["streak_days"] == 1
    assert conv["best_streak_days"] == 2


def test_record_conversation_aggregates(tmp_path: Path):
    store = UserStatsStore(tmp_path / "u1")
    summary = store.record_conversation(
        duration_sec=600,
        questions=20,
        wrongs=4,
        completed=True,
        continued=False,
        topic="travel",
        level="A2",
        free_debate=False,
        ended_at=datetime(2026, 8, 2, 12, 0, 0),
    )
    c = summary["conversation"]
    assert c["total"] == 1
    assert c["completed"] == 1
    assert c["total_seconds"] == 600
    assert c["total_minutes"] == 10.0
    assert c["total_questions"] == 20
    assert c["total_wrongs"] == 4
    assert c["success_rate"] == 80.0
    assert c["streak_days"] == 1
    assert len(c["recent"]) == 1
    assert c["recent"][0]["topic"] == "travel"
