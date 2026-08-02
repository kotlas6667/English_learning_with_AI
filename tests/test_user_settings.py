from pathlib import Path

from app.user_settings import ALLOWED_KEYS, UserSettingsStore, sanitize_settings


def test_sanitize_keeps_only_allowed_keys():
    raw = {
        "level": "B1",
        "topic": "travel",
        "evil": "<script>",
        "voice": "en-US-JennyNeural",
        "silenceTimeout": "2",
        "llm": None,
        "speechRate": "x" * 300,
    }
    clean = sanitize_settings(raw)
    assert clean == {
        "level": "B1",
        "topic": "travel",
        "voice": "en-US-JennyNeural",
        "silenceTimeout": "2",
    }
    assert "evil" not in clean
    assert set(clean).issubset(ALLOWED_KEYS)


def test_settings_store_roundtrip(tmp_path: Path):
    store = UserSettingsStore(tmp_path / "u1")
    assert store.read() == {}
    saved = store.write(
        {
            "level": "A2",
            "topic": "travel",
            "subtopic": "airport_checkin",
            "minQuestions": "20",
            "llm": "openai",
            "llmModel": "gpt-4o-mini",
            "ttsProvider": "edge",
            "voice": "en-US-JennyNeural",
            "speechRate": "0.85",
            "silenceTimeout": "2",
            "mode": "conversation",
            "ignore_me": "nope",
        }
    )
    assert saved["level"] == "A2"
    assert saved["silenceTimeout"] == "2"
    assert "ignore_me" not in saved
    assert store.path.exists()
    assert store.read() == saved


def test_settings_store_corrupt_json(tmp_path: Path):
    store = UserSettingsStore(tmp_path / "u2")
    store.path.write_text("{not-json", encoding="utf-8")
    assert store.read() == {}
