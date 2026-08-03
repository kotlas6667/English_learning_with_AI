from __future__ import annotations

from typing import Any


TOPICS: dict[str, dict[str, Any]] = {
    "travel": {
        "label": "Travel",
        "subtopics": {
            "airport": "Checking in, security, boarding at the airport",
            "hotel": "Hotel check-in, room problems, checkout",
            "directions": "Asking for and giving directions in a city",
        },
    },
    "restaurant": {
        "label": "Restaurant",
        "subtopics": {
            "ordering": "Ordering food and drinks politely",
            "complaints": "Complaining about a meal or service",
            "paying": "Asking for the bill and paying",
        },
    },
    "work": {
        "label": "Work",
        "subtopics": {
            "small_talk": "Office small talk with colleagues",
            "meetings": "Simple meeting participation",
            "phone_calls": "Basic work phone calls",
        },
    },
    "shopping": {
        "label": "Shopping",
        "subtopics": {
            "clothes": "Buying clothes, sizes, fitting room",
            "returns": "Returning or exchanging a product",
        },
    },
    "health": {
        "label": "Health",
        "subtopics": {
            "pharmacy": "Buying medicine at a pharmacy",
            "doctor": "Describing symptoms to a doctor",
        },
    },
    "small_talk": {
        "label": "Daily life / Small talk",
        "subtopics": {
            "neighbours": "Talking with neighbours",
            "hobbies": "Talking about hobbies and free time",
        },
    },
}

LEVELS = ("A2", "B1", "B2")

LEVEL_GUIDANCE = {
    "A2": (
        "Use short, clear sentences. Common vocabulary only. "
        "Speak slowly and encourage the learner. Avoid idioms."
    ),
    "B1": (
        "Use natural everyday English with some linking words. "
        "Introduce useful phrases. Correct major mistakes briefly."
    ),
    "B2": (
        "Use richer vocabulary and natural expressions. "
        "Challenge the learner gently. Discuss opinions and details."
    ),
}

READING_LENGTH = {
    "A2": "80-120 words, 2 short paragraphs",
    "B1": "120-180 words, 2-3 paragraphs",
    "B2": "180-250 words, 3 paragraphs",
}


def list_topics() -> list[dict[str, Any]]:
    result = []
    for key, meta in TOPICS.items():
        result.append(
            {
                "id": key,
                "label": meta["label"],
                "subtopics": [
                    {"id": sid, "label": label}
                    for sid, label in meta["subtopics"].items()
                ],
            }
        )
    return result


def resolve_scenario(topic: str, subtopic: str | None) -> str:
    topic_meta = TOPICS.get(topic)
    if not topic_meta:
        return "Everyday practical English conversation"
    subs = topic_meta["subtopics"]
    if subtopic and subtopic in subs:
        return subs[subtopic]
    # default first subtopic
    first = next(iter(subs.values()))
    return first
