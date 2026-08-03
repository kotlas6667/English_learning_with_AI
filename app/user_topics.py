from __future__ import annotations

import copy
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from app.topics import TOPICS


def slug_id(text: str) -> str:
    base = unicodedata.normalize("NFKD", text.strip())
    base = "".join(c for c in base if not unicodedata.combining(c))
    base = re.sub(r"[^a-zA-Z0-9_-]+", "_", base.lower())
    base = re.sub(r"_+", "_", base).strip("_") or "topic"
    return base[:48]


def normalize_text(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.strip().lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9\s]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def catalog_to_list(catalog: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for key, meta in catalog.items():
        result.append(
            {
                "id": key,
                "label": meta.get("label") or key,
                "custom": bool(meta.get("custom")),
                "subtopics": [
                    {
                        "id": sid,
                        "label": label if isinstance(label, str) else str(label),
                        "custom": bool((meta.get("subtopic_meta") or {}).get(sid, {}).get("custom")),
                    }
                    for sid, label in (meta.get("subtopics") or {}).items()
                ],
            }
        )
    return result


def default_catalog() -> dict[str, dict[str, Any]]:
    return copy.deepcopy(TOPICS)


class UserTopicsStore:
    """Per-user topic/subtopic catalog with duplicate meaning checks."""

    def __init__(self, user_dir: Path) -> None:
        self.user_dir = Path(user_dir)
        self.path = self.user_dir / "topics.json"
        self.user_dir.mkdir(parents=True, exist_ok=True)

    def _read_custom(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"topics": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"topics": {}}
        if not isinstance(data.get("topics"), dict):
            data["topics"] = {}
        return data

    def _write_custom(self, data: dict[str, Any]) -> None:
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_catalog(self) -> dict[str, dict[str, Any]]:
        catalog = default_catalog()
        custom = self._read_custom().get("topics") or {}
        for tid, meta in custom.items():
            if tid in catalog:
                # merge subtopics into existing topic
                subs = dict(catalog[tid].get("subtopics") or {})
                for sid, label in (meta.get("subtopics") or {}).items():
                    subs[sid] = label
                catalog[tid]["subtopics"] = subs
                catalog[tid]["custom"] = catalog[tid].get("custom") or bool(meta.get("custom"))
            else:
                catalog[tid] = {
                    "label": meta.get("label") or tid,
                    "subtopics": dict(meta.get("subtopics") or {}),
                    "custom": True,
                }
        return catalog

    def list_topics(self) -> list[dict[str, Any]]:
        return catalog_to_list(self.get_catalog())

    def resolve_scenario(self, topic: str, subtopic: str | None) -> str:
        catalog = self.get_catalog()
        topic_meta = catalog.get(topic)
        if not topic_meta:
            return "Everyday practical English conversation"
        subs = topic_meta.get("subtopics") or {}
        if subtopic and subtopic in subs:
            return str(subs[subtopic])
        if subs:
            return str(next(iter(subs.values())))
        return str(topic_meta.get("label") or topic)

    def find_similar_topics(
        self, label: str, *, description: str = "", threshold: float = 0.72
    ) -> list[dict[str, Any]]:
        catalog = self.get_catalog()
        needle = normalize_text(f"{label} {description}".strip())
        matches: list[dict[str, Any]] = []
        for tid, meta in catalog.items():
            cand_label = str(meta.get("label") or tid)
            blob = normalize_text(
                cand_label
                + " "
                + " ".join(str(v) for v in (meta.get("subtopics") or {}).values())
            )
            ratio = SequenceMatcher(None, needle, blob).ratio()
            label_ratio = SequenceMatcher(None, normalize_text(label), normalize_text(cand_label)).ratio()
            # substring / shared significant token
            tokens_n = set(needle.split())
            tokens_c = set(blob.split())
            overlap = len(tokens_n & tokens_c) / max(1, min(len(tokens_n), len(tokens_c)))
            score = max(ratio, label_ratio, overlap if overlap >= 0.6 else 0.0)
            exact = normalize_text(label) == normalize_text(cand_label)
            if exact or score >= threshold:
                matches.append(
                    {
                        "id": tid,
                        "label": cand_label,
                        "score": round(1.0 if exact else score, 3),
                        "exact": exact,
                        "reason": "exact name" if exact else "similar meaning/name",
                    }
                )
        matches.sort(key=lambda m: (-m["exact"], -m["score"]))
        return matches

    def find_similar_subtopics(
        self, topic_id: str, label: str, *, threshold: float = 0.72
    ) -> list[dict[str, Any]]:
        catalog = self.get_catalog()
        topic = catalog.get(topic_id)
        if not topic:
            raise KeyError(f"Téma neexistuje: {topic_id}")
        needle = normalize_text(label)
        matches: list[dict[str, Any]] = []
        for sid, sub_label in (topic.get("subtopics") or {}).items():
            cand = normalize_text(str(sub_label))
            score = SequenceMatcher(None, needle, cand).ratio()
            exact = needle == normalize_text(str(sub_label).split("—")[0] if "—" in str(sub_label) else str(sub_label))
            # also compare against id-like short names
            id_score = SequenceMatcher(None, needle, normalize_text(sid.replace("_", " "))).ratio()
            score = max(score, id_score)
            if exact or score >= threshold or needle in cand or cand in needle:
                matches.append(
                    {
                        "id": sid,
                        "label": str(sub_label),
                        "score": round(1.0 if exact else score, 3),
                        "exact": exact or needle == cand,
                        "reason": "exact/similar subtopic",
                    }
                )
        matches.sort(key=lambda m: (-m["exact"], -m["score"]))
        return matches

    def add_topic(self, label: str, *, description: str = "", force: bool = False) -> dict[str, Any]:
        clean = label.strip()
        if not clean:
            raise ValueError("Názov témy nemôže byť prázdny.")
        similar = self.find_similar_topics(clean, description=description)
        strong = [m for m in similar if m["exact"] or m["score"] >= 0.85]
        if strong and not force:
            raise TopicDuplicateError(strong)
        data = self._read_custom()
        topics = data.setdefault("topics", {})
        tid = slug_id(clean)
        base = tid
        n = 2
        catalog = self.get_catalog()
        while tid in catalog or tid in topics:
            tid = f"{base}_{n}"
            n += 1
        desc = description.strip() or f"Practical English conversations about {clean}"
        topics[tid] = {
            "label": clean,
            "custom": True,
            "subtopics": {
                "general": desc,
            },
        }
        self._write_custom(data)
        return {"id": tid, "label": clean, "subtopics": [{"id": "general", "label": desc}], "similar": similar}

    def add_subtopic(
        self,
        topic_id: str,
        label: str,
        *,
        description: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        clean = label.strip()
        if not clean:
            raise ValueError("Názov podtémy nemôže byť prázdny.")
        catalog = self.get_catalog()
        if topic_id not in catalog:
            raise KeyError(f"Téma neexistuje: {topic_id}")
        similar = self.find_similar_subtopics(topic_id, clean)
        strong = [m for m in similar if m["exact"] or m["score"] >= 0.85]
        if strong and not force:
            raise TopicDuplicateError(strong)

        data = self._read_custom()
        topics = data.setdefault("topics", {})
        # Ensure topic entry exists in custom file (even for built-in topics)
        if topic_id not in topics:
            base = catalog[topic_id]
            topics[topic_id] = {
                "label": base.get("label") or topic_id,
                "custom": bool(base.get("custom")),
                "subtopics": {},
            }
        subs = topics[topic_id].setdefault("subtopics", {})
        sid = slug_id(clean)
        base = sid
        n = 2
        existing = set((catalog[topic_id].get("subtopics") or {}).keys()) | set(subs.keys())
        while sid in existing:
            sid = f"{base}_{n}"
            n += 1
        text = description.strip() or clean
        # Prefer "Title — description" for clarity in UI
        if description.strip() and description.strip().lower() != clean.lower():
            text = f"{clean} — {description.strip()}"
        elif not description.strip():
            text = clean
        subs[sid] = text
        self._write_custom(data)
        return {
            "topic_id": topic_id,
            "id": sid,
            "label": text,
            "similar": similar,
        }


class TopicDuplicateError(ValueError):
    def __init__(self, matches: list[dict[str, Any]]) -> None:
        self.matches = matches
        labels = ", ".join(m["label"] for m in matches[:3])
        super().__init__(f"Podobná téma/podtéma už existuje: {labels}")
