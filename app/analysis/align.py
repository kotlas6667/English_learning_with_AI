from __future__ import annotations

import difflib
import re
from dataclasses import dataclass


_WORD_RE = re.compile(r"\S+")


@dataclass
class AlignError:
    expected: str
    heard: str
    start: int
    end: int
    tip: str = ""


def _tokens(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(0), m.start(), m.end()) for m in _WORD_RE.finditer(text)]


def align_transcript(original: str, transcript: str) -> list[AlignError]:
    """Word-level diff between expected text and STT transcript."""
    orig_tokens = _tokens(original)
    heard_tokens = _tokens(transcript)
    orig_words = [t[0].lower().strip(".,!?;:\"'") for t in orig_tokens]
    heard_words = [t[0].lower().strip(".,!?;:\"'") for t in heard_tokens]

    matcher = difflib.SequenceMatcher(a=orig_words, b=heard_words, autojunk=False)
    errors: list[AlignError] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        expected = " ".join(t[0] for t in orig_tokens[i1:i2]) or "(missing)"
        heard = " ".join(t[0] for t in heard_tokens[j1:j2]) or "(missing)"
        if i1 < len(orig_tokens):
            start = orig_tokens[i1][1]
            end = orig_tokens[i2 - 1][2] if i2 > i1 else start
        elif orig_tokens:
            start = orig_tokens[-1][2]
            end = start
        else:
            start, end = 0, 0
        tip = {
            "replace": f'Say "{expected}" instead of "{heard}".',
            "delete": f'Do not skip: "{expected}".',
            "insert": f'Extra words heard: "{heard}".',
        }.get(tag, "Check this part.")
        errors.append(
            AlignError(expected=expected, heard=heard, start=start, end=end, tip=tip)
        )
    return errors
