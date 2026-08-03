from __future__ import annotations

from typing import Any

# Curated role-play scenarios for v2 onboarding / quick start.
# topic_id aligns with learningGoal settings: travel | work | daily
# topic / subtopic align with the topic catalog (app/topics.py).

SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "airport_checkin",
        "title": "Airport check-in",
        "topic_id": "travel",
        "topic": "travel",
        "subtopic": "airport",
        "level": "A2",
        "blurb_sk": "Odovzdáš batožinu a odpovieš na otázky na check-ine.",
        "scenario_en": (
            "Airport check-in desk: the learner is a passenger checking in for a flight; "
            "you are the airline agent. Ask about passport, bags, and seat preference."
        ),
        "min_questions": 8,
    },
    {
        "id": "hotel_reception",
        "title": "Hotel reception",
        "topic_id": "travel",
        "topic": "travel",
        "subtopic": "hotel",
        "level": "A2",
        "blurb_sk": "Prihlásenie do hotela, izba a jednoduché požiadavky.",
        "scenario_en": (
            "Hotel reception: the learner is a guest checking in; you are the receptionist. "
            "Confirm booking, room type, Wi‑Fi, and breakfast."
        ),
        "min_questions": 8,
    },
    {
        "id": "asking_directions",
        "title": "Asking for directions",
        "topic_id": "travel",
        "topic": "travel",
        "subtopic": "directions",
        "level": "A2",
        "blurb_sk": "Opýtaš sa na cestu a overíš, či rozumieš pokynom.",
        "scenario_en": (
            "City street: the learner asks for directions to a landmark; you are a helpful local. "
            "Give clear directions and check understanding."
        ),
        "min_questions": 8,
    },
    {
        "id": "office_small_talk",
        "title": "Office small talk",
        "topic_id": "work",
        "topic": "work",
        "subtopic": "small_talk",
        "level": "A2",
        "blurb_sk": "Krátky rozhovor s kolegom o práci a víkende.",
        "scenario_en": (
            "Office kitchen / corridor: the learner is a colleague; you are another colleague. "
            "Chat about the weekend, projects, and coffee."
        ),
        "min_questions": 8,
    },
    {
        "id": "meeting_update",
        "title": "Meeting update",
        "topic_id": "work",
        "topic": "work",
        "subtopic": "meetings",
        "level": "B1",
        "blurb_sk": "Na porade povieš krátky update a odpovieš na otázky.",
        "scenario_en": (
            "Team meeting: the learner gives a short project update; you are the meeting lead. "
            "Ask clarifying questions about status, blockers, and next steps."
        ),
        "min_questions": 8,
    },
    {
        "id": "work_phone_call",
        "title": "Work phone call",
        "topic_id": "work",
        "topic": "work",
        "subtopic": "phone_calls",
        "level": "B1",
        "blurb_sk": "Zavoláš kolegovi alebo IT a vyriešiš jednoduchý problém.",
        "scenario_en": (
            "Work phone call: the learner calls IT support because their PC will not start; "
            "you are IT support answering the phone. Troubleshoot step by step."
        ),
        "min_questions": 8,
    },
    {
        "id": "cafe_order",
        "title": "Ordering at a café",
        "topic_id": "daily",
        "topic": "restaurant",
        "subtopic": "ordering",
        "level": "A2",
        "blurb_sk": "Objednáš si kávu a jedlo, požiadaš o účet.",
        "scenario_en": (
            "Café counter: the learner is a customer ordering coffee and a snack; "
            "you are the barista. Take the order, offer options, and handle the bill."
        ),
        "min_questions": 8,
    },
    {
        "id": "neighbour_chat",
        "title": "Chat with a neighbour",
        "topic_id": "daily",
        "topic": "small_talk",
        "subtopic": "neighbours",
        "level": "A2",
        "blurb_sk": "Pozdravíš suseda a krátko pokecáš o bežných veciach.",
        "scenario_en": (
            "Apartment hallway: the learner meets a neighbour; you are the neighbour. "
            "Greet, chat about weather, building news, and weekend plans."
        ),
        "min_questions": 8,
    },
]


def list_scenarios(*, topic_id: str | None = None) -> list[dict[str, Any]]:
    """Return curated scenarios, optionally filtered by learning-goal topic_id."""
    if not topic_id:
        return [dict(s) for s in SCENARIOS]
    key = topic_id.strip().lower()
    return [dict(s) for s in SCENARIOS if str(s.get("topic_id", "")).lower() == key]


def get_scenario(scenario_id: str | None) -> dict[str, Any] | None:
    """Return one curated scenario by id, or None."""
    if not scenario_id:
        return None
    key = scenario_id.strip().lower()
    for item in SCENARIOS:
        if str(item.get("id", "")).lower() == key:
            return dict(item)
    return None
