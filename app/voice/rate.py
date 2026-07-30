from __future__ import annotations


def clamp_speech_rate(rate: float | None, default: float = 1.0) -> float:
    value = default if rate is None else float(rate)
    return max(0.7, min(1.5, round(value, 2)))


def rate_to_edge_percent(rate: float) -> str:
    """Edge-TTS expects e.g. '+20%' or '-10%'."""
    pct = int(round((clamp_speech_rate(rate) - 1.0) * 100))
    pct = max(-50, min(50, pct))
    return f"{pct:+d}%"


def rate_to_elevenlabs(rate: float) -> float:
    """ElevenLabs speed is typically 0.7–1.2."""
    return max(0.7, min(1.2, clamp_speech_rate(rate)))


SPEECH_RATE_OPTIONS = [
    {"id": "0.75", "value": 0.75, "label": "Veľmi pomaly"},
    {"id": "0.85", "value": 0.85, "label": "Pomaly"},
    {"id": "1", "value": 1.0, "label": "Normálne"},
    {"id": "1.15", "value": 1.15, "label": "Rýchlo"},
    {"id": "1.3", "value": 1.3, "label": "Veľmi rýchlo"},
]
