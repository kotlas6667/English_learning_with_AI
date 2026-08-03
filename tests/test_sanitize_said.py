from app.learning_store import parse_said_tag, parse_unclear_tag, sanitize_said


def test_sanitize_said_rejects_context_fill_in():
    raw = "I don't know"
    invented = "I don't know the error in my Python code"
    assert sanitize_said(raw, invented) is None


def test_sanitize_said_keeps_light_cleanup():
    raw = "I dont know"
    cleaned = "I don't know"
    assert sanitize_said(raw, cleaned) == cleaned


def test_sanitize_said_keeps_identical():
    raw = "Yes, please"
    assert sanitize_said(raw, "Yes, please") == "Yes, please"


def test_parse_unclear_tag():
    cleaned, reason = parse_unclear_tag(
        "Sorry, could you say that again? [[unclear:garbled audio]] [[ask]]"
    )
    assert reason == "garbled audio"
    assert "[[unclear:" not in cleaned
    assert "say that again" in cleaned


def test_said_and_unclear_together():
    reply = (
        "Hmm. [[said:I don't know the error in my Python code]] "
        "[[unclear:too short / uncertain]] "
        "Could you repeat that?"
    )
    cleaned, said = parse_said_tag(reply)
    cleaned, unclear = parse_unclear_tag(cleaned)
    assert said == "I don't know the error in my Python code"
    assert sanitize_said("I don't know", said) is None
    assert unclear == "too short / uncertain"
    assert "[[said:" not in cleaned
    assert "[[unclear:" not in cleaned
