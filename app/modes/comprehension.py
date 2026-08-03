from __future__ import annotations

from typing import Any

from app.learning_store import LearningItem, LearningStore
from app.modes.reading import ReadingEngine, ReadingSession
from app.prompts import comprehension_judge_prompt
from app.providers.base import LLMProvider


class ComprehensionEngine:
    def __init__(self, reading_engine: ReadingEngine) -> None:
        self.reading_engine = reading_engine

    def _store(self, session: ReadingSession) -> LearningStore:
        store = self.reading_engine._stores.get(session.id)
        if not store:
            raise RuntimeError("Learning store nie je naviazaný na reading session.")
        return store

    async def answer(
        self,
        session: ReadingSession,
        llm: LLMProvider,
        answer_text: str,
    ) -> dict[str, Any]:
        if session.phase not in ("comprehension", "debate"):
            raise ValueError("Session nie je vo fáze debaty / porozumenia.")
        if session.question_index >= len(session.questions):
            session.phase = "done"
            return {"phase": "done", "done": True}

        q = session.questions[session.question_index]
        expected = [str(p) for p in q.get("expected_points") or []]
        result = await llm.chat_json(
            [
                {
                    "role": "user",
                    "content": comprehension_judge_prompt(
                        passage=session.text,
                        question=str(q.get("question") or ""),
                        expected_points=expected,
                        answer=answer_text,
                        level=session.level,
                    ),
                }
            ],
            system="Return JSON only for comprehension judgement.",
        )
        correct = bool(result.get("correct"))
        feedback = str(result.get("feedback") or "")
        missing = [str(m) for m in result.get("missing_points") or []]

        store = self._store(session)
        word_key = f"{session.title}::{q.get('id') or session.question_index}"
        if not correct:
            store.upsert(
                LearningItem(
                    kind="comprehension",
                    word=word_key,
                    tip=feedback,
                    context=str(q.get("question") or ""),
                    level=session.level,
                    topic=session.topic,
                    translation_sk="; ".join(missing),
                    significance=8,
                )
            )
        else:
            store.mark_review(word_key, kind="comprehension", success=True)

        session.question_index += 1
        done = session.question_index >= len(session.questions)
        next_q = None
        if done:
            session.phase = "done"
        else:
            next_q = session.questions[session.question_index]

        return {
            "correct": correct,
            "feedback": feedback,
            "missing_points": missing,
            "done": done,
            "phase": session.phase,
            "next_question": next_q,
            "question_index": session.question_index,
            "total": len(session.questions),
        }
