from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from app.analysis.feedback import build_highlighted_html, merge_feedback
from app.analysis.significance import clamp_significance, estimate_significance
from app.context_limits import PRACTICE_TARGETS_MAX
from app.learning_store import LearningItem, LearningStore
from app.prompts import (
    explanation_judge_prompt,
    expression_feedback_prompt,
    practice_reading_prompt,
    reading_generation_prompt,
)
from app.providers.base import LLMProvider


def _norm_word(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _words_match(a: str, b: str) -> bool:
    """Prísne párovanie — krátke slová (a/at/the) len exact match."""
    na, nb = _norm_word(a), _norm_word(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # Krátke tokeny nikdy nerobíme substring (inak "a" trafí všetko).
    if len(na) <= 3 or len(nb) <= 3:
        return False
    return na in nb or nb in na


def _error_significance(err: dict[str, Any]) -> int:
    expected = str(err.get("expected") or "").strip()
    return clamp_significance(
        err.get("significance"),
        default=estimate_significance(expected, str(err.get("heard") or "")),
    )


def _target_still_wrong(
    target: str,
    *,
    wrong_words: list[str],
    errors: list[dict[str, Any]],
    min_significance: int = 3,
) -> bool:
    """True ak cieľové slovo stále vyšlo ako významná chyba."""
    for err in errors:
        expected = str(err.get("expected") or "").strip()
        if not expected or expected == "(missing)":
            continue
        if not _words_match(target, expected):
            continue
        if _error_significance(err) >= min_significance:
            return True
    if not errors:
        for w in wrong_words:
            if _words_match(target, w):
                return True
    return False


@dataclass
class ReadingSession:
    id: str
    user_id: str
    level: str
    topic: str
    subtopic: str | None
    provider_name: str
    voice_id: str | None
    llm_model: str = ""
    tts_provider: str = "edge"
    speech_rate: float = 1.0
    min_questions: int = 20
    sentence_count: int = 20
    restart: bool = False
    user_context: str = ""
    scenario: str = ""
    title: str = ""
    text: str = ""
    key_phrases: list[str] = field(default_factory=list)
    questions: list[dict[str, Any]] = field(default_factory=list)
    phase: str = "ready"  # ready | reading | reading_done | explain | debate | done
    last_transcript: str = ""
    last_errors: list[dict[str, Any]] = field(default_factory=list)
    highlighted_html: str = ""
    question_index: int = 0
    overall_feedback: str = ""
    wrong_words: list[str] = field(default_factory=list)
    explanation_feedback: str = ""
    practice_kind: str | None = None
    practice_targets: list[str] = field(default_factory=list)


class ReadingEngine:
    def __init__(self) -> None:
        self.sessions: dict[str, ReadingSession] = {}
        self._stores: dict[str, LearningStore] = {}

    def _store(self, session: ReadingSession) -> LearningStore:
        store = self._stores.get(session.id)
        if not store:
            raise RuntimeError("Learning store nie je naviazaný na session.")
        return store

    async def start(
        self,
        *,
        store: LearningStore,
        llm: LLMProvider,
        user_id: str,
        level: str,
        topic: str,
        subtopic: str | None,
        provider_name: str,
        llm_model: str = "",
        voice_id: str | None,
        tts_provider: str = "edge",
        speech_rate: float = 1.0,
        min_questions: int = 20,
        sentence_count: int = 20,
        restart: bool = False,
        user_context: str = "",
        scenario: str = "",
    ) -> ReadingSession:
        due = store.list_due(limit=8)
        due_words = [i.word for i in due]
        qcount = max(2, min(80, int(min_questions)))
        scount = max(2, min(100, int(sentence_count or 20)))
        prompt = reading_generation_prompt(
            level=level,
            topic=topic,
            subtopic=subtopic,
            due_items=due_words,
            question_count=qcount,
            sentence_count=scount,
            user_context=user_context,
            restart_review=restart,
            scenario=scenario,
        )
        data = await llm.chat_json(
            [{"role": "user", "content": prompt}],
            system="You generate CEFR-appropriate reading lessons as JSON only.",
        )
        session = ReadingSession(
            id=str(uuid4()),
            user_id=user_id,
            level=level,
            topic=topic,
            subtopic=subtopic,
            provider_name=provider_name,
            llm_model=llm_model or getattr(llm, "model", ""),
            voice_id=voice_id,
            tts_provider=tts_provider,
            speech_rate=speech_rate,
            min_questions=qcount,
            sentence_count=scount,
            restart=restart,
            user_context=user_context,
            scenario=scenario,
            title=str(data.get("title") or "Reading passage"),
            text=str(data.get("text") or "").strip(),
            key_phrases=[str(p) for p in data.get("key_phrases") or []],
            questions=list(data.get("comprehension_questions") or []),
            highlighted_html="",
            phase="ready",
        )
        if not session.text:
            raise RuntimeError("LLM nevrátilo čítací text.")
        session.questions = session.questions[:qcount]
        session.highlighted_html = build_highlighted_html(session.text, [])
        self.sessions[session.id] = session
        self._stores[session.id] = store
        return session

    async def start_practice(
        self,
        *,
        store: LearningStore,
        llm: LLMProvider,
        user_id: str,
        level: str,
        provider_name: str,
        llm_model: str = "",
        voice_id: str | None,
        tts_provider: str = "edge",
        speech_rate: float = 1.0,
        sentence_count: int = 20,
        practice_kind: str = "reading_error",
    ) -> ReadingSession:
        if practice_kind not in ("reading_error", "vocabulary"):
            raise ValueError("Precvičovanie podporuje typy: reading_error, vocabulary.")
        items = [
            i
            for i in store.all_items()
            if i.kind == practice_kind
            and i.status != "known"
            and int(i.significance or 0) >= 3
        ]
        if not items:
            raise ValueError(
                f"V learning store nie sú vhodné položky typu „{practice_kind}“ "
                "(skóre aspoň 3/10)."
            )
        # Preferuj vyššie skóre; limituj počet slov (token budget).
        scount = max(2, min(100, int(sentence_count or 20)))
        max_words = max(4, min(PRACTICE_TARGETS_MAX, scount))
        targets = [i.word for i in items[:max_words]]
        prompt = practice_reading_prompt(
            level=level,
            practice_words=targets,
            sentence_count=scount,
            kind=practice_kind,
        )
        data = await llm.chat_json(
            [{"role": "user", "content": prompt}],
            system="You generate CEFR practice reading stories as JSON only.",
        )
        session = ReadingSession(
            id=str(uuid4()),
            user_id=user_id,
            level=level,
            topic="practice",
            subtopic=practice_kind,
            provider_name=provider_name,
            llm_model=llm_model or getattr(llm, "model", ""),
            voice_id=voice_id,
            tts_provider=tts_provider,
            speech_rate=speech_rate,
            min_questions=0,
            sentence_count=scount,
            title=str(data.get("title") or "Practice reading"),
            text=str(data.get("text") or "").strip(),
            key_phrases=[str(p) for p in data.get("key_phrases") or []] or targets[:8],
            questions=[],
            highlighted_html="",
            phase="ready",
            practice_kind=practice_kind,
            practice_targets=targets,
        )
        if not session.text:
            raise RuntimeError("LLM nevrátilo precvičovací text.")
        session.highlighted_html = build_highlighted_html(session.text, [])
        self.sessions[session.id] = session
        self._stores[session.id] = store
        return session

    def begin_reading(self, session: ReadingSession) -> dict[str, Any]:
        session.phase = "reading"
        session.last_errors = []
        session.wrong_words = []
        session.overall_feedback = ""
        session.highlighted_html = build_highlighted_html(session.text, [])
        return {"phase": session.phase, "text": session.text}

    async def evaluate_reading(
        self, session: ReadingSession, llm: LLMProvider, transcript: str
    ) -> dict[str, Any]:
        session.last_transcript = transcript
        llm_payload = await llm.chat_json(
            [
                {
                    "role": "user",
                    "content": expression_feedback_prompt(
                        original=session.text,
                        transcript=transcript,
                        level=session.level,
                    ),
                }
            ],
            system="Return JSON only with reading error spans.",
        )
        llm_errors = list(llm_payload.get("errors") or [])
        merged = merge_feedback(session.text, transcript, llm_errors)
        session.last_errors = merged
        session.highlighted_html = build_highlighted_html(session.text, merged)
        session.overall_feedback = str(llm_payload.get("overall_feedback") or "")
        ranked: list[tuple[int, str]] = []
        seen: set[str] = set()
        for err in merged:
            expected = str(err.get("expected") or "").strip()
            if not expected or expected == "(missing)" or expected in seen:
                continue
            seen.add(expected)
            sig = clamp_significance(
                err.get("significance"),
                default=estimate_significance(expected, str(err.get("heard") or "")),
            )
            ranked.append((sig, expected))
        ranked.sort(key=lambda x: (-x[0], x[1].lower()))
        session.wrong_words = [w for _, w in ranked]
        session.phase = "reading_done"

        store = self._store(session)
        cleared: list[str] = []
        kept: list[str] = []

        # Všetky položky zo „Zle prečítané“ → zapíš / aktualizuj skóre v store.
        for err in merged:
            expected = str(err.get("expected") or "").strip()
            if not expected or expected == "(missing)":
                continue
            sig = _error_significance(err)
            store.upsert(
                LearningItem(
                    kind="reading_error",
                    word=expected,
                    tip=str(err.get("tip") or ""),
                    context=str(err.get("heard") or ""),
                    level=session.level,
                    topic=session.topic,
                    significance=sig,
                ),
                significance_mode="replace",
            )

        if session.practice_kind and session.practice_targets:
            for target in session.practice_targets:
                if _target_still_wrong(
                    target,
                    wrong_words=session.wrong_words,
                    errors=merged,
                ):
                    kept.append(target)
                else:
                    # Správne precvičené (a aj falošné krátke ciele) zmiznú.
                    if store.delete_item(target, kind=session.practice_kind):
                        cleared.append(target)
                    # Ak cieľ bol reading_error a zároveň sa zobrazil pod iným wordingom,
                    # nechávame ten wording zo sync vyššie.
            if cleared and not kept:
                session.overall_feedback = (
                    session.overall_feedback
                    or "Great job — practice items cleared from your learning store."
                )
            elif cleared:
                session.overall_feedback = (
                    (session.overall_feedback + " " if session.overall_feedback else "")
                    + f"Cleared: {', '.join(cleared)}. Still practice: {', '.join(kept)}."
                ).strip()
            elif kept:
                session.overall_feedback = (
                    (session.overall_feedback + " " if session.overall_feedback else "")
                    + f"Still need practice: {', '.join(kept)}."
                ).strip()

        return {
            "transcript": transcript,
            "errors": merged,
            "wrong_words": session.wrong_words,
            "highlighted_html": session.highlighted_html,
            "overall_feedback": session.overall_feedback,
            "phase": session.phase,
            "practice": bool(session.practice_kind),
            "practice_kind": session.practice_kind,
            "practice_cleared": cleared,
            "practice_kept": kept,
            "practice_targets": list(session.practice_targets),
        }

    async def evaluate_explanation(
        self, session: ReadingSession, llm: LLMProvider, transcript: str
    ) -> dict[str, Any]:
        session.phase = "explain"
        payload = await llm.chat_json(
            [
                {
                    "role": "user",
                    "content": explanation_judge_prompt(
                        passage=session.text,
                        explanation=transcript,
                        level=session.level,
                    ),
                }
            ],
            system="Return JSON only for explanation judgement.",
        )
        correct = bool(payload.get("correct"))
        feedback = str(payload.get("feedback") or "")
        missing = [str(m) for m in payload.get("missing_points") or []]
        understood = [str(u) for u in payload.get("understood_points") or []]
        score = float(payload.get("score") or (1.0 if correct else 0.4))
        session.explanation_feedback = feedback

        store = self._store(session)
        key = f"{session.title}::explanation"
        if not correct:
            store.upsert(
                LearningItem(
                    kind="explanation",
                    word=key,
                    tip=feedback,
                    context="; ".join(missing),
                    level=session.level,
                    topic=session.topic,
                    translation_sk="; ".join(missing),
                )
            )
        else:
            store.mark_review(key, kind="explanation", success=True)

        return {
            "phase": "explain",
            "correct": correct,
            "score": score,
            "feedback": feedback,
            "missing_points": missing,
            "understood_points": understood,
            "transcript": transcript,
        }

    def begin_debate(self, session: ReadingSession) -> dict[str, Any]:
        """Debate = guided Q&A about the passage (comprehension questions)."""
        if not session.questions:
            session.phase = "done"
            return {"phase": "done", "question": None}
        session.phase = "debate"
        session.question_index = 0
        q = session.questions[0]
        return {
            "phase": "debate",
            "question_index": 0,
            "total": len(session.questions),
            "question": q,
        }

    def begin_comprehension(self, session: ReadingSession) -> dict[str, Any]:
        """Alias for debate (backward compatible)."""
        return self.begin_debate(session)

    def get(self, session_id: str) -> ReadingSession:
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError("Reading session not found")
        return session
