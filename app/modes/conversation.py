from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from app.learning_store import (
    LearningItem,
    LearningStore,
    parse_confused_tags,
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
    restart: bool = False
    free_debate: bool = False
    suggested_topic: str = ""
    user_context: str = ""
    scenario: str = ""
    history: list[dict[str, str]] = field(default_factory=list)
    due_words: list[str] = field(default_factory=list)
    opening: str = ""
    learned_facts: list[str] = field(default_factory=list)


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
        # Jedna aktívna konverzácia na používateľa — staré in-memory sessiony zmaž.
        for sid, old in list(self.sessions.items()):
            if old.user_id == user_id:
                self.sessions.pop(sid, None)
                self._stores.pop(sid, None)
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
            restart=restart and not free_debate,
            free_debate=free_debate,
            user_context=user_context,
            scenario=scenario if not free_debate else "Open free debate",
            due_words=due_words,
        )
        self.sessions[session.id] = session
        self.bind_store(session.id, store)
        return session

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
        if topic and not session.suggested_topic:
            session.suggested_topic = topic
            session.topic = topic
        cleaned, asked = self._consume_ask_marker(cleaned)
        if asked:
            session.questions_asked += 1
        self._store_unknowns(session, unknowns)
        self._store_confused(session, confused)
        self._store_wrongs(session, wrongs)
        if facts:
            session.learned_facts.extend(facts)
        return cleaned.strip(), unknowns, facts, confused, said, wrongs

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
            remaining = max(0, session.min_questions - session.questions_asked)
            hint = (
                "\n(System note: Stay IN CHARACTER in the agreed scenario."
                f"{stt_note} "
                "Always mark [[said:cleaned English of what they meant]]. "
                "If answer content is clearly wrong (not STT noise), mark "
                "[[wrong:summary|Slovak tip]] and briefly correct in parentheses. "
                "Do NOT meta-teach phrases ('you can say…', 'try saying…'). "
                "React as your role and push the scene forward with one question. "
                "If the learner does not understand your question, mark "
                "[[confused:summary|note]], rephrase more simply IN CHARACTER, and ask again. "
                "End question turns with [[ask]]."
            )
            if remaining > 0:
                hint += f" About {remaining} more in-character questions still needed before wrapping up.)"
            else:
                hint += ")"
        session.history.append({"role": "user", "content": user_text + hint})
        session.history = trim_chat_history(
            session.history, max_messages=CHAT_HISTORY_MESSAGES_MAX
        )
        reply = await llm.chat(
            [{"role": m["role"], "content": m["content"]} for m in session.history],
            system=system,
        )
        cleaned, unknowns, facts, confused, said, wrongs = self._process_reply(session, reply)
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
            "questions_asked": session.questions_asked,
            "min_questions": session.min_questions,
            "free_debate": session.free_debate,
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
