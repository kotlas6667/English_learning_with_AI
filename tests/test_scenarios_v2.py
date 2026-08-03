from app.scenarios import get_scenario, list_scenarios
from app.user_stats import compute_skills, compute_today_minutes


def test_list_scenarios_all():
    items = list_scenarios()
    assert len(items) >= 6
    assert all("id" in s and "title" in s for s in items)


def test_list_scenarios_filter_travel():
    items = list_scenarios(topic_id="travel")
    assert items
    assert all(s["topic_id"] == "travel" for s in items)


def test_get_scenario():
    sc = get_scenario("airport_checkin")
    assert sc is not None
    assert sc["topic"] == "travel"
    assert sc["subtopic"] == "airport"
    assert "check-in" in sc["scenario_en"].lower() or "airport" in sc["scenario_en"].lower()
    assert get_scenario("missing_xyz") is None
    assert get_scenario(None) is None


def test_compute_skills():
    skills = compute_skills(total_seconds=600, total_questions=20, total_wrongs=4)
    assert skills["speaking"] > 0
    assert skills["accuracy"] == 80
    assert 0 <= skills["vocabulary"] <= 100


def test_compute_today_minutes():
    from datetime import date

    today = date(2026, 8, 3)
    recent = [
        {"ended_at": "2026-08-03T10:00:00", "duration_sec": 600},
        {"ended_at": "2026-08-03T18:00:00", "duration_sec": 300},
        {"ended_at": "2026-08-02T10:00:00", "duration_sec": 900},
    ]
    assert compute_today_minutes(recent, today=today) == 15.0
    assert compute_today_minutes([], today=today) == 0.0
