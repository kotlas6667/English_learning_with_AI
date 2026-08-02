from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.learning_store import (
    LearningItem,
    LearningStore,
    parse_ask_continue_tag,
    parse_confused_tags,
    parse_continue_decision_tag,
    parse_learn_tags,
    parse_said_tag,
    parse_topic_tag,
    parse_unknown_tags,
    parse_wrong_tags,
)
from app.context_limits import CHAT_HISTORY_MESSAGES_MAX, trim_chat_history
from app.prompts import conversation_system_prompt, free_debate_system_prompt
from app.providers.base import LLMProvider


@dataclass
class ConversationSession:
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
    questions_asked: int = 0
    question_batch: int = 20
    question_target: int = 20
    awaiting_continue: bool = False
    phase: str = "active"  # active | awaiting_continue | done
    restart: bool = False
    free_debate: bool = False
    suggested_topic: str = ""
    user_context: str = ""
    scenario: str = ""
    history: list[dict[str, str]] = field(default_factory=list)
    due_words: list[str] = field(default_factory=list)
    opening: str = ""
    learned_facts: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.now)
    wrongs_count: int = 0
    unknowns_count: int = 0
    confused_count: int = 0
    continued_once: bool = False
    stats_recorded: bool = False


class ConversationEngine:
    def __init__(self) -> None:
        self.sessions: dict[str, ConversationSession] = {}
        self._stores: dict[str, LearningStore] = {}

    def bind_store(self, session_id: str, store: LearningStore) -> None:
        self._stores[session_id] = store

    def _store(self, session: ConversationSession) -> LearningStore:
        store = self._stores.get(session.id)
        if not store:
            raise RuntimeError("Learning store nie je naviazaný na session.")
        return store

    def start(
        self,
        *,
        store: LearningStore,
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
        restart: bool = False,
        free_debate: bool = False,
        user_context: str = "",
        scenario: str = "",
    ) -> ConversationSession:
        due = store.list_due(limit=8, kinds=["vocabulary", "reading_error"])
        due_words = [i.word for i in due]
        session = ConversationSession(
            id=str(uuid4()),
            user_id=user_id,
            level=level,
            topic="free_debate" if free_debate else topic,
            subtopic=None if free_debate else subtopic,
            provider_name=provider_name,
            llm_model=llm_model,
            voice_id=voice_id,
            tts_provider=tts_provider,
            speech_rate=speech_rate,
            min_questions=max(2, min(80, int(min_questions))),
            question_batch=max(2, min(80, int(min_questions))),
            question_target=max(2, min(80, int(min_questions))),
            awaiting_continue=False,
            phase="active",
            restart=restart and not free_debate,
            free_debate=free_debate,
            user_context=user_context,
            scenario=scenario if not free_debate else "Open free debate",
            due_words=due_words,
            started_at=datetime.now(),
        )
        self.sessions[session.id] = session
        self.bind_store(session.id, store)
        return session

    def close_user_sessions(self, user_id: str) -> list[ConversationSession]:
        """Remove in-memory sessions for user and return them (for stats finalize)."""
        closed: list[ConversationSession] = []
        for sid, old in list(self.sessions.items()):
            if old.user_id == user_id:
                closed.append(old)
                self.sessions.pop(sid, None)
                self._stores.pop(sid, None)
        return closed

    def abandon_session(self, session_id: str) -> ConversationSession | None:
        """Drop session without counting it in stats (discard / cancel)."""
        session = self.sessions.pop(session_id, None)
        self._stores.pop(session_id, None)
        if not session:
            return None
        session.stats_recorded = True  # skip future finalize
        session.phase = "abandoned"
        return session

    def conversation_stats_entry(self, session: ConversationSession) -> dict[str, Any] | None:
        """Build a stats record if the session had real practice."""
        if session.stats_recorded or session.phase == "abandoned":
            return None
        user_turns = sum(1 for m in session.history if m.get("role") == "user")
        if user_turns <= 0 and session.questions_asked <= 0:
            return None
        ended = datetime.now()
        duration = max(0, int((ended - session.started_at).total_seconds()))
        completed = session.phase == "done" or session.questions_asked >= session.question_batch
        return {
            "duration_sec": duration,
            "questions": session.questions_asked,
            "wrongs": session.wrongs_count,
            "completed": completed,
            "continued": session.continued_once,
            "topic": session.suggested_topic or session.topic,
            "level": session.level,
            "free_debate": session.free_debate,
            "ended_at": ended,
        }

    def _system(self, session: ConversationSession) -> str:
        if session.free_debate:
            return free_debate_system_prompt(
                level=session.level,
                due_items=session.due_words,
                user_context=session.user_context,
            )
        return conversation_system_prompt(
            level=session.level,
            topic=session.topic,
            subtopic=session.subtopic,
            due_items=session.due_words,
            min_questions=session.min_questions,
            user_context=session.user_context,
            restart_review=session.restart,
            scenario=session.scenario,
        )

    def _process_reply(
        self, session: ConversationSession, reply: str
    ) -> tuple[str, list[tuple[str, str]], list[str], list[tuple[str, str]], str | None, list[tuple[str, str]]]:
        cleaned, unknowns = parse_unknown_tags(reply)
        cleaned, facts = parse_learn_tags(cleaned)
        cleaned, topic = parse_topic_tag(cleaned)
        cleaned, confused = parse_confused_tags(cleaned)
        cleaned, said = parse_said_tag(cleaned)
        cleaned, wrongs = parse_wrong_tags(cleaned)
        cleaned, offered_continue = parse_ask_continue_tag(cleaned)
        cleaned, continue_decision = parse_continue_decision_tag(cleaned)
        if topic and not session.suggested_topic:
            session.suggested_topic = topic
            session.topic = topic
        cleaned, asked = self._consume_ask_marker(cleaned)
        # Continue-offer / goodbye questions do not count toward the quota.
        if asked and not offered_continue and continue_decision != "no":
            session.questions_asked += 1
        if offered_continue and not session.free_debate:
            session.awaiting_continue = True
            session.phase = "awaiting_continue"
        if continue_decision == "yes" and not session.free_debate:
            session.awaiting_continue = False
            session.phase = "active"
            session.continued_once = True
            session.question_target = session.questions_asked + session.question_batch
        elif continue_decision == "no" and not session.free_debate:
            session.awaiting_continue = False
            session.phase = "done"
        self._store_unknowns(session, unknowns)
        self._store_confused(session, confused)
        self._store_wrongs(session, wrongs)
        session.unknowns_count += len(unknowns)
        session.confused_count += len(confused)
        session.wrongs_count += len(wrongs)
        if facts:
            session.learned_facts.extend(facts)
        return cleaned.strip(), unknowns, facts, confused, said, wrongs

    def _progress_payload(self, session: ConversationSession) -> dict[str, Any]:
        return {
            "questions_asked": session.questions_asked,
            "min_questions": session.min_questions,
            "question_batch": session.question_batch,
            "question_target": session.question_target,
            "awaiting_continue": session.awaiting_continue,
            "phase": session.phase,
        }

    async def opening_message(self, session: ConversationSession, llm: LLMProvider) -> str:
        system = self._system(session)
        if session.free_debate:
            starter = (
                "Start a free debate. Using the learner profile/history/learning store, "
                "suggest ONE suitable topic, greet briefly, propose the topic, and invite "
                "the learner to talk about that OR anything else they prefer. "
                "Mark [[topic:...]] once. Ask the first open question and end with [[ask]]."
            )
        elif session.restart and session.due_words:
            starter = "Start the restart review: greet briefly, then quiz the first unknown phrase."
        else:
            starter = (
                "Start an immersive role-play for this topic/subtopic. "
                "In 1–2 short sentences: name the concrete situation and assign roles "
                "(who the learner is, who you are). Then IMMEDIATELY speak IN CHARACTER "
                "as your role (e.g. IT support answering the phone). "
                "Do NOT teach phrases or ask them to 'try saying' something. "
                "Ask one in-character question and end with [[ask]]."
            )
        reply = await llm.chat([{"role": "user", "content": starter}], system=system)
        cleaned, _u, _f, _c, _said, _w = self._process_reply(session, reply)
        session.history.append({"role": "assistant", "content": cleaned})
        session.opening = cleaned
        return cleaned

    def _roleplay_hint(self, session: ConversationSession, *, from_stt: bool) -> str:
        stt_note = ""
        if from_stt:
            stt_note = (
                " The user text is a Whisper transcript — fix STT nonsense via [[said:...]] "
                "and answer the intended meaning."
            )
        base = (
            "\n(System note: Stay IN CHARACTER in the agreed scenario."
            f"{stt_note} "
            "Always mark [[said:cleaned English of what they meant]]. "
            "If answer content is clearly wrong (not STT noise), mark "
            "[[wrong:summary|Slovak tip]] and briefly correct in parentheses. "
            "Do NOT meta-teach phrases ('you can say…', 'try saying…'). "
            "If the learner does not understand your question, mark "
            "[[confused:summary|note]], rephrase more simply IN CHARACTER, and ask again."
        )
        if session.phase == "done":
            return (
                base
                + " The lesson already ended. Thank them briefly IN CHARACTER and tell them "
                "they can start a new lesson. Do NOT ask new scenario questions. "
                "Do NOT mark [[ask]] or [[ask_continue]].)"
            )
        if session.awaiting_continue or session.phase == "awaiting_continue":
            return (
                base
                + " You already asked whether they want to CONTINUE practicing. "
                "Interpret their answer. If YES/continue/áno: mark [[continue:yes]], "
                "then ask ONE fresh in-character question that advances the scene "
                "(do not repeat earlier questions) and end with [[ask]]. "
                "If NO/stop/nie/enough: mark [[continue:no]], thank them briefly IN CHARACTER, "
                "and end the scene — no more questions. Do NOT invent repeated check-in loops.)"
            )
        remaining = max(0, session.question_target - session.questions_asked)
        if remaining <= 0:
            return (
                base
                + f" Question quota reached ({session.questions_asked}/"
                f"{session.question_target}). This turn: briefly wrap the current beat "
                "IN CHARACTER, then ask if they want to CONTINUE practicing this conversation "
                "or STOP. Speak the continue question in simple English. "
                "Mark [[ask_continue]] (and you may also mark [[ask]]). "
                "Do NOT ask another passport/ticket/boarding loop question. "
                "Do NOT invent new repeated tasks.)"
            )
        return (
            base
            + " React as your role and push the scene forward with ONE new question "
            f"(about {remaining} more before the continue checkpoint). "
            "Do not repeat earlier questions. End question turns with [[ask]].)"
        )

    async def user_turn(
        self,
        session: ConversationSession,
        llm: LLMProvider,
        user_text: str,
        *,
        from_stt: bool = False,
    ) -> dict[str, Any]:
        system = self._system(session)
        stt_note = ""
        if from_stt:
            stt_note = (
                " The user text is a Whisper transcript — fix STT nonsense via [[said:...]] "
                "and answer the intended meaning."
            )
        if session.free_debate:
            hint = (
                "\n(System note: continue the free debate. Follow the learner's interest."
                f"{stt_note} "
                "Always mark [[said:cleaned English]]. "
                "If the answer content is clearly wrong, mark [[wrong:summary|Slovak tip]]. "
                "Mark new personal facts with [[learn:...]] and unknown words with "
                "[[unknown:word|Slovak]]. If they do not understand your question, mark "
                "[[confused:summary|note]], rephrase simply, and ask again. "
                "End questions with [[ask]].)"
            )
        else:
            hint = self._roleplay_hint(session, from_stt=from_stt)
        session.history.append({"role": "user", "content": user_text + hint})
        session.history = trim_chat_history(
            session.history, max_messages=CHAT_HISTORY_MESSAGES_MAX
        )
        reply = await llm.chat(
            [{"role": m["role"], "content": m["content"]} for m in session.history],
            system=system,
        )
        cleaned, unknowns, facts, confused, said, wrongs = self._process_reply(session, reply)
        # If quota just hit and model forgot to offer continue, keep phase active until next turn
        # but force awaiting via soft flag when asked count crossed target without offer.
        if (
            not session.free_debate
            and session.phase == "active"
            and not session.awaiting_continue
            and session.questions_asked >= session.question_target
        ):
            # Next user_turn hint will force [[ask_continue]].
            pass
        display_user = (said or user_text).strip() or user_text
        session.history[-1] = {"role": "user", "content": display_user}
        session.history.append({"role": "assistant", "content": cleaned})
        session.history = trim_chat_history(
            session.history, max_messages=CHAT_HISTORY_MESSAGES_MAX
        )

        lower = display_user.lower()
        store = self._store(session)
        for word in list(session.due_words):
            if word.lower() in lower:
                store.mark_review(word, kind="vocabulary", success=True)

        return {
            "reply": cleaned,
            "said": said,
            "transcript_raw": user_text,
            "transcript_display": display_user,
            "unknowns": [{"word": w, "translation": t} for w, t in unknowns],
            "confused": [{"summary": s, "note": n} for s, n in confused],
            "wrongs": [{"summary": s, "note": n} for s, n in wrongs],
            "learned_facts": facts,
            "suggested_topic": session.suggested_topic,
            "free_debate": session.free_debate,
            **self._progress_payload(session),
        }

    def get(self, session_id: str) -> ConversationSession:
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError("Conversation session not found")
        return session

    def _store_unknowns(
        self, session: ConversationSession, unknowns: list[tuple[str, str]]
    ) -> None:
        store = self._store(session)
        for word, translation in unknowns:
            store.upsert(
                LearningItem(
                    kind="vocabulary",
                    word=word,
                    translation_sk=translation,
                    level=session.level,
                    topic=session.topic or "free_debate",
                    significance=6,
                )
            )

    def _store_confused(
        self, session: ConversationSession, confused: list[tuple[str, str]]
    ) -> None:
        store = self._store(session)
        for summary, note in confused:
            store.upsert(
                LearningItem(
                    kind="question_gap",
                    word=summary[:120],
                    translation_sk=note[:200] if note else "Nerozumel otázke",
                    level=session.level,
                    topic=session.topic or ("free_debate" if session.free_debate else ""),
                    tip="Learner did not understand the question — rephrase next time.",
                    context=summary,
                    significance=7,
                )
            )

    def _store_wrongs(
        self, session: ConversationSession, wrongs: list[tuple[str, str]]
    ) -> None:
        store = self._store(session)
        for summary, note in wrongs:
            store.upsert(
                LearningItem(
                    kind="comprehension",
                    word=summary[:120],
                    translation_sk=note[:200] if note else "Zlá odpoveď v konverzácii",
                    level=session.level,
                    topic=session.topic or ("free_debate" if session.free_debate else ""),
                    tip=note[:200] if note else "Oprav obsah odpovede pri ďalšom opakovaní.",
                    context=summary,
                    significance=8,
                )
            )

    @staticmethod
    def _consume_ask_marker(text: str) -> tuple[str, bool]:
        marker = "[[ask]]"
        if marker in text.lower():
            idx = text.lower().rfind(marker)
            cleaned = (text[:idx] + text[idx + len(marker) :]).strip()
            return cleaned, True
        return text, text.strip().endswith("?")
