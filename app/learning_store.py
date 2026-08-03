from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

Status = Literal["learning", "review", "known"]

INTERVALS_DAYS = (1, 3, 7, 14)

_UNKNOWN_TAG = re.compile(
    r"\[\[unknown:(?P<word>[^|\]]+)\|(?P<translation>[^\]]+)\]\]",
    re.IGNORECASE,
)
_LEARN_TAG = re.compile(r"\[\[learn:(?P<fact>[^\]]+)\]\]", re.IGNORECASE)
_TOPIC_TAG = re.compile(r"\[\[topic:(?P<topic>[^\]]+)\]\]", re.IGNORECASE)
# Learner did not understand the tutor's question → store + rephrase.
_CONFUSED_TAG = re.compile(
    r"\[\[confused:(?P<summary>[^|\]]+)(?:\|(?P<note>[^\]]+))?\]\]",
    re.IGNORECASE,
)
# Cleaned interpretation of learner speech (esp. after Whisper STT).
_SAID_TAG = re.compile(
    r"\[\[said:(?P<said>[^\]]+)\]\]",
    re.IGNORECASE,
)
# Pedagogically wrong answer in conversation → comprehension store.
_WRONG_TAG = re.compile(
    r"\[\[wrong:(?P<summary>[^|\]]+)(?:\|(?P<note>[^\]]+))?\]\]",
    re.IGNORECASE,
)
# Conversation milestone: offer more practice / accept / end.
_ASK_CONTINUE_TAG = re.compile(r"\[\[ask_continue\]\]", re.IGNORECASE)
_CONTINUE_DECISION_TAG = re.compile(
    r"\[\[continue:(?P<decision>yes|no)\]\]",
    re.IGNORECASE,
)
# Suggested better phrasing for the learner turn (hidden metadata).
_BETTER_TAG = re.compile(
    r"\[\[better:(?P<better>[^\]]+)\]\]",
    re.IGNORECASE,
)
# Short Slovak tip for the learner (hidden metadata).
_TIP_TAG = re.compile(
    r"\[\[tip:(?P<tip>[^\]]+)\]\]",
    re.IGNORECASE,
)
# Speaking quality score 0–100 (hidden metadata).
_SCORE_TAG = re.compile(
    r"\[\[score:(?P<score>\d{1,3})\]\]",
    re.IGNORECASE,
)


@dataclass
class LearningItem:
    kind: str  # vocabulary | reading_error | comprehension | question_gap
    word: str
    translation_sk: str = ""
    level: str = "A2"
    topic: str = ""
    tip: str = ""
    context: str = ""
    times_seen: int = 1
    times_correct: int = 0
    next_review: str = field(default_factory=lambda: date.today().isoformat())
    status: Status = "learning"
    # 1 = kozmetika/STT (Tomas≈Tomáš, chýbajúce "a"); 10 = mení význam
    significance: int = 5

    def key(self) -> str:
        return self.word.strip().lower()


def _clamp_sig(value: object, default: int = 5) -> int:
    try:
        n = int(round(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = default
    return max(1, min(10, n))


class LearningStore(ABC):
    @abstractmethod
    def list_due(self, *, limit: int = 5, kinds: list[str] | None = None) -> list[LearningItem]:
        raise NotImplementedError

    @abstractmethod
    def upsert(self, item: LearningItem) -> LearningItem:
        raise NotImplementedError

    @abstractmethod
    def mark_review(self, word: str, *, kind: str, success: bool) -> None:
        raise NotImplementedError

    @abstractmethod
    def all_items(self) -> list[LearningItem]:
        raise NotImplementedError

    @abstractmethod
    def delete_item(self, word: str, *, kind: str) -> bool:
        raise NotImplementedError


def parse_unknown_tags(text: str) -> tuple[str, list[tuple[str, str]]]:
    found: list[tuple[str, str]] = []

    def _repl(match: re.Match[str]) -> str:
        word = match.group("word").strip()
        translation = match.group("translation").strip()
        found.append((word, translation))
        return word

    cleaned = _UNKNOWN_TAG.sub(_repl, text)
    return cleaned, found


def parse_learn_tags(text: str) -> tuple[str, list[str]]:
    facts: list[str] = []

    def _repl(match: re.Match[str]) -> str:
        fact = match.group("fact").strip()
        if fact:
            facts.append(fact)
        return ""

    cleaned = _LEARN_TAG.sub(_repl, text)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip(), facts


def parse_topic_tag(text: str) -> tuple[str, str | None]:
    topic: str | None = None

    def _repl(match: re.Match[str]) -> str:
        nonlocal topic
        topic = match.group("topic").strip() or topic
        return ""

    cleaned = _TOPIC_TAG.sub(_repl, text)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip(), topic


def parse_confused_tags(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Extract [[confused:question summary|optional note]] markers."""
    found: list[tuple[str, str]] = []

    def _repl(match: re.Match[str]) -> str:
        summary = (match.group("summary") or "").strip()
        note = (match.group("note") or "").strip()
        if summary:
            found.append((summary, note))
        return ""

    cleaned = _CONFUSED_TAG.sub(_repl, text)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip(), found


def parse_said_tag(text: str) -> tuple[str, str | None]:
    """Extract [[said:cleaned learner utterance]] (last tag wins)."""
    said: str | None = None

    def _repl(match: re.Match[str]) -> str:
        nonlocal said
        value = (match.group("said") or "").strip()
        if value:
            said = value
        return ""

    cleaned = _SAID_TAG.sub(_repl, text)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip(), said


def parse_better_tag(text: str) -> tuple[str, str | None]:
    """Extract [[better:improved English phrasing]] (last tag wins)."""
    better: str | None = None

    def _repl(match: re.Match[str]) -> str:
        nonlocal better
        value = (match.group("better") or "").strip()
        if value:
            better = value
        return ""

    cleaned = _BETTER_TAG.sub(_repl, text)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip(), better


def parse_tip_tag(text: str) -> tuple[str, str | None]:
    """Extract [[tip:short Slovak tip]] (last tag wins)."""
    tip: str | None = None

    def _repl(match: re.Match[str]) -> str:
        nonlocal tip
        value = (match.group("tip") or "").strip()
        if value:
            tip = value
        return ""

    cleaned = _TIP_TAG.sub(_repl, text)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip(), tip


def parse_score_tag(text: str) -> tuple[str, int | None]:
    """Extract [[score:0-100]] speaking score (last valid tag wins)."""
    score: int | None = None

    def _repl(match: re.Match[str]) -> str:
        nonlocal score
        raw = (match.group("score") or "").strip()
        try:
            value = int(raw)
        except ValueError:
            return ""
        if 0 <= value <= 100:
            score = value
        return ""

    cleaned = _SCORE_TAG.sub(_repl, text)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip(), score


def parse_wrong_tags(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Extract [[wrong:expected/summary|optional Slovak tip]] markers."""
    found: list[tuple[str, str]] = []

    def _repl(match: re.Match[str]) -> str:
        summary = (match.group("summary") or "").strip()
        note = (match.group("note") or "").strip()
        if summary:
            found.append((summary, note))
        return ""

    cleaned = _WRONG_TAG.sub(_repl, text)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip(), found


def parse_ask_continue_tag(text: str) -> tuple[str, bool]:
    found = bool(_ASK_CONTINUE_TAG.search(text))
    cleaned = _ASK_CONTINUE_TAG.sub("", text)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip(), found


def parse_continue_decision_tag(text: str) -> tuple[str, str | None]:
    """Extract [[continue:yes]] / [[continue:no]] (last tag wins)."""
    decision: str | None = None

    def _repl(match: re.Match[str]) -> str:
        nonlocal decision
        decision = (match.group("decision") or "").strip().lower() or decision
        return ""

    cleaned = _CONTINUE_DECISION_TAG.sub(_repl, text)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip(), decision


def _next_interval(times_correct: int) -> int:
    idx = min(max(times_correct, 0), len(INTERVALS_DAYS) - 1)
    return INTERVALS_DAYS[idx]


class MarkdownLearningStore(LearningStore):
    """Persists learning items as Markdown tables. Swap later for DatabaseLearningStore."""

    FILES = {
        "vocabulary": "vocabulary.md",
        "reading_error": "reading_errors.md",
        "comprehension": "comprehension.md",
        "question_gap": "question_gaps.md",
    }

    HEADERS = [
        "word",
        "translation_sk",
        "level",
        "topic",
        "tip",
        "context",
        "times_seen",
        "times_correct",
        "next_review",
        "status",
        "significance",
    ]

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for kind, filename in self.FILES.items():
            path = self.data_dir / filename
            if not path.exists():
                self._write_table(path, kind, [])

    def list_due(self, *, limit: int = 5, kinds: list[str] | None = None) -> list[LearningItem]:
        today = date.today()
        items = self.all_items()
        due = []
        for item in items:
            if kinds and item.kind not in kinds:
                continue
            if item.status == "known":
                continue
            try:
                review = date.fromisoformat(item.next_review)
            except ValueError:
                review = today
            if review <= today:
                due.append(item)
        due.sort(key=lambda i: (-_clamp_sig(i.significance), i.next_review))
        return due[:limit]

    def upsert(
        self,
        item: LearningItem,
        *,
        significance_mode: str = "max",
    ) -> LearningItem:
        item.significance = _clamp_sig(item.significance)
        items = self._load_kind(item.kind)
        existing = next((i for i in items if i.key() == item.key()), None)
        if existing:
            existing.times_seen += 1
            existing.translation_sk = item.translation_sk or existing.translation_sk
            existing.tip = item.tip or existing.tip
            existing.context = item.context or existing.context
            existing.level = item.level or existing.level
            existing.topic = item.topic or existing.topic
            if significance_mode == "replace":
                existing.significance = _clamp_sig(item.significance)
            else:
                existing.significance = max(
                    _clamp_sig(existing.significance),
                    _clamp_sig(item.significance),
                )
            if existing.status == "known":
                existing.status = "review"
                existing.next_review = date.today().isoformat()
            self._save_kind(item.kind, items)
            return existing
        items.append(item)
        self._save_kind(item.kind, items)
        return item

    def mark_review(self, word: str, *, kind: str, success: bool) -> None:
        items = self._load_kind(kind)
        key = word.strip().lower()
        for item in items:
            if item.key() != key:
                continue
            item.times_seen += 1
            if success:
                item.times_correct += 1
                days = _next_interval(item.times_correct)
                item.next_review = (date.today() + timedelta(days=days)).isoformat()
                if item.times_correct >= len(INTERVALS_DAYS):
                    item.status = "known"
                else:
                    item.status = "review"
            else:
                item.times_correct = max(0, item.times_correct - 1)
                item.next_review = date.today().isoformat()
                item.status = "learning"
            break
        self._save_kind(kind, items)

    def delete_item(self, word: str, *, kind: str) -> bool:
        if kind not in self.FILES:
            return False
        items = self._load_kind(kind)
        key = word.strip().lower()
        kept = [i for i in items if i.key() != key]
        if len(kept) == len(items):
            return False
        self._save_kind(kind, kept)
        return True

    def all_items(self) -> list[LearningItem]:
        items: list[LearningItem] = []
        for kind in self.FILES:
            items.extend(self._load_kind(kind))
        items.sort(key=lambda i: (-_clamp_sig(i.significance), i.next_review, i.word.lower()))
        return items

    def _load_kind(self, kind: str) -> list[LearningItem]:
        path = self.data_dir / self.FILES[kind]
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        rows: list[LearningItem] = []
        for line in lines:
            line = line.strip()
            if not line.startswith("|") or line.startswith("| word") or re.match(r"^\|\s*-+", line):
                continue
            parts = [p.strip() for p in line.strip("|").split("|")]
            # Staršie tabuľky bez stĺpca significance — doplň default.
            if len(parts) < 10:
                continue
            while len(parts) < len(self.HEADERS):
                parts.append("")
            data = dict(zip(self.HEADERS, parts, strict=False))
            try:
                rows.append(
                    LearningItem(
                        kind=kind,
                        word=data["word"],
                        translation_sk=data.get("translation_sk", ""),
                        level=data.get("level", "A2"),
                        topic=data.get("topic", ""),
                        tip=data.get("tip", ""),
                        context=data.get("context", ""),
                        times_seen=int(data.get("times_seen") or 1),
                        times_correct=int(data.get("times_correct") or 0),
                        next_review=data.get("next_review") or date.today().isoformat(),
                        status=data.get("status") or "learning",  # type: ignore[arg-type]
                        significance=_clamp_sig(data.get("significance") or 5),
                    )
                )
            except (ValueError, KeyError):
                continue
        return rows

    def _save_kind(self, kind: str, items: list[LearningItem]) -> None:
        path = self.data_dir / self.FILES[kind]
        self._write_table(path, kind, items)

    def _write_table(self, path: Path, kind: str, items: list[LearningItem]) -> None:
        title = {
            "vocabulary": "Unknown vocabulary",
            "reading_error": "Reading / expression errors",
            "comprehension": "Comprehension gaps",
            "question_gap": "Did not understand the question",
        }.get(kind, kind)
        lines = [
            f"# {title}",
            "",
            f"_Updated: {datetime.now().isoformat(timespec='seconds')}_",
            "",
            "| " + " | ".join(self.HEADERS) + " |",
            "| " + " | ".join("---" for _ in self.HEADERS) + " |",
        ]
        for item in items:
            data = asdict(item)
            row = [str(data.get(h, "")).replace("|", "/") for h in self.HEADERS]
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")


class DatabaseLearningStore(LearningStore):
    """Placeholder for a future SQL-backed store used in mastery testing."""

    def __init__(self, *_args, **_kwargs) -> None:
        raise NotImplementedError("DatabaseLearningStore bude doplnený neskôr.")
