"""Limity kontextu posielaného do LLM — šetria tokeny a držia fokus AI."""

from __future__ import annotations

import re

# Soft limity do promptu (znaky ≈ tokeny/4 v angličtine; SK/EN mix ~3–4).
PROFILE_AI_MAX_CHARS = 2000
HISTORY_AI_MAX_CHARS = 2500
TUTOR_CONTEXT_MAX_CHARS = 4800
DUE_ITEMS_AI_MAX = 10
WEAK_AREAS_AI_MAX = 15
PRACTICE_TARGETS_MAX = 15
CHAT_HISTORY_MESSAGES_MAX = 16  # ~8 turnov user+assistant

# Na disku: história môže byť väčšia, ale periodicky orezávame.
HISTORY_FILE_MAX_CHARS = 40_000


def clip_chars(text: str, max_chars: int, *, from_end: bool = False) -> str:
    raw = text or ""
    if max_chars <= 0 or len(raw) <= max_chars:
        return raw
    if from_end:
        return "…\n" + raw[-max_chars:]
    return raw[:max_chars] + "\n…"


def profile_for_ai(profile: str, *, max_chars: int = PROFILE_AI_MAX_CHARS) -> str:
    """Priorita: About + Weak areas + začiatok profilu; zvyšok orez."""
    text = (profile or "").strip()
    if not text:
        return "(empty profile)"
    if len(text) <= max_chars:
        return text

    parts = re.split(r"(?m)^(## .+)$", text)
    # parts: [preamble, ## Title, body, ## Title, body, ...]
    preamble = (parts[0] if parts else "").strip()
    sections: dict[str, str] = {}
    order: list[str] = []
    i = 1
    while i + 1 < len(parts):
        title = parts[i].strip()
        body = parts[i + 1].strip()
        sections[title] = body
        order.append(title)
        i += 2

    preferred = [
        "## About the learner",
        "## Weak areas",
        "## Goals",
        "## Preferences",
        "## Level",
    ]
    chunks: list[str] = []
    budget = max_chars

    head = clip_chars(preamble, min(450, budget))
    if head:
        chunks.append(head)
        budget -= len(head) + 2

    used: set[str] = set()
    for title in preferred + [t for t in order if t not in preferred]:
        if title in used or title not in sections:
            continue
        used.add(title)
        body = sections[title]
        # Weak / About — viac priestoru
        cap = 700 if "Weak" in title or "About" in title else 350
        piece = f"{title}\n\n{clip_chars(body, min(cap, max(80, budget - 20)))}"
        if len(piece) + 2 > budget:
            piece = clip_chars(piece, max(0, budget - 2))
        if not piece.strip():
            break
        chunks.append(piece)
        budget -= len(piece) + 2
        if budget < 80:
            break

    out = "\n\n".join(chunks).strip()
    return clip_chars(out, max_chars) if len(out) > max_chars else out


def trim_chat_history(
    history: list[dict[str, str]],
    *,
    max_messages: int = CHAT_HISTORY_MESSAGES_MAX,
) -> list[dict[str, str]]:
    if max_messages <= 0 or len(history) <= max_messages:
        return history
    return history[-max_messages:]
