from __future__ import annotations

from typing import Any

from app.analysis.align import align_transcript
from app.analysis.significance import clamp_significance, estimate_significance


def merge_feedback(
    original: str,
    transcript: str,
    llm_errors: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Combine alignment diffs with optional LLM expression errors for UI spans."""
    align_errors = align_transcript(original, transcript)
    merged: list[dict[str, Any]] = [
        {
            "expected": e.expected,
            "heard": e.heard,
            "start": e.start,
            "end": e.end,
            "tip": e.tip,
            "source": "align",
            "significance": estimate_significance(e.expected, e.heard),
        }
        for e in align_errors
    ]

    for err in llm_errors or []:
        expected = str(err.get("expected") or "").strip()
        if not expected:
            continue
        heard = str(err.get("heard") or "")
        start = int(err.get("start") or -1)
        end = int(err.get("end") or -1)
        if start < 0 or end <= start or end > len(original):
            idx = original.lower().find(expected.lower())
            if idx >= 0:
                start, end = idx, idx + len(expected)
            else:
                continue
        sig = (
            clamp_significance(err["significance"])
            if err.get("significance") is not None
            else estimate_significance(expected, heard)
        )
        # skip near-duplicates
        if any(abs(m["start"] - start) < 2 and abs(m["end"] - end) < 2 for m in merged):
            for m in merged:
                if abs(m["start"] - start) < 2:
                    m["tip"] = err.get("tip") or m["tip"]
                    m["source"] = "both"
                    m["significance"] = max(int(m.get("significance") or 1), sig)
            continue
        merged.append(
            {
                "expected": expected,
                "heard": heard,
                "start": start,
                "end": end,
                "tip": str(err.get("tip") or ""),
                "source": "llm",
                "significance": sig,
            }
        )

    merged.sort(key=lambda x: (-int(x.get("significance") or 0), x["start"]))
    return merged


def build_highlighted_html(original: str, errors: list[dict[str, Any]]) -> str:
    if not errors:
        return _escape(original)
    parts: list[str] = []
    cursor = 0
    for err in errors:
        start = max(0, min(int(err["start"]), len(original)))
        end = max(start, min(int(err["end"]), len(original)))
        if start < cursor:
            continue
        parts.append(_escape(original[cursor:start]))
        tip = _escape(err.get("tip") or "")
        heard = _escape(err.get("heard") or "")
        span = _escape(original[start:end] or err.get("expected") or "")
        parts.append(
            f'<mark class="err" title="{tip} (heard: {heard})">{span}</mark>'
        )
        cursor = end
    parts.append(_escape(original[cursor:]))
    return "".join(parts)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
