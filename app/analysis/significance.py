from __future__ import annotations

import re
import unicodedata

# Funkčné slová / články — chyba zvyčajne nemení význam vety.
_MINOR_WORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "of",
    "to",
    "in",
    "on",
    "at",
    "for",
    "with",
    "from",
    "by",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "am",
    "do",
    "does",
    "did",
    "has",
    "have",
    "had",
    "that",
    "this",
    "these",
    "those",
    "it",
    "its",
    "he",
    "she",
    "they",
    "we",
    "you",
    "i",
    "my",
    "your",
    "his",
    "her",
    "our",
    "their",
}


def clamp_significance(value: object, default: int = 5) -> int:
    try:
        n = int(round(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = default
    return max(1, min(10, n))


def _strip_diacritics(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text)
    return "".join(c for c in norm if not unicodedata.combining(c))


def _norm_token(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _strip_diacritics(text).lower())


def estimate_significance(expected: str, heard: str = "") -> int:
    """Odhad 1–10: nízke = kozmetika/STT, vysoké = mení význam."""
    exp = (expected or "").strip()
    hrd = (heard or "").strip()
    if not exp or exp == "(missing)":
        return 1

    exp_n = _norm_token(exp)
    hrd_n = _norm_token(hrd)
    exp_words = [w for w in re.findall(r"[A-Za-zÀ-ÿ0-9']+", exp) if w]
    single = exp_words[0].lower() if len(exp_words) == 1 else ""

    # Len diakritika / veľké písmená (Tomas vs Tomáš).
    if exp_n and exp_n == hrd_n:
        return 1

    # Články a krátke funkčné slová.
    if single in _MINOR_WORDS:
        return 2

    # Chýbajúce malé slovo.
    if not hrd and single and len(single) <= 3:
        return 2

    # STT odpad / fragment vs dlhšie slovo (ort, ks, …).
    if hrd_n and exp_n:
        if len(hrd_n) <= 3 and len(exp_n) >= 4 and (hrd_n in exp_n or exp_n.startswith(hrd_n) or exp_n.endswith(hrd_n)):
            return 2
        if len(exp_n) <= 3 and len(hrd_n) >= 4 and (exp_n in hrd_n):
            return 2
        if len(hrd_n) <= 2 and len(exp_n) >= 4:
            return 2
        if len(exp_n) <= 2 and len(hrd_n) >= 4:
            return 2

    # Blízka výslovnosť / preklep (Levenshtein-ish ratio).
    if exp_n and hrd_n:
        longer = max(len(exp_n), len(hrd_n))
        dist = _edit_distance(exp_n, hrd_n)
        if longer and dist / longer <= 0.25:
            return 3
        if longer and dist / longer <= 0.4:
            return 4

    # Viacslovná fráza / úplne iný obsah.
    if len(exp_words) >= 3:
        return 8
    if single and single not in _MINOR_WORDS:
        if not hrd or (hrd_n and exp_n and hrd_n[:1] != exp_n[:1]):
            return 7
        return 6

    return 5


def _edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]
