from app.voice.stt import normalize_transcript


def test_normalize_keeps_real_answers():
    assert normalize_transcript("Yes, I have two bags.") == "Yes, I have two bags."
    assert normalize_transcript("No") == "No"
    assert normalize_transcript("OK") == "OK"
    assert normalize_transcript("Hello") == "Hello"


def test_normalize_strips_silence_hallucinations():
    assert normalize_transcript("you") == ""
    assert normalize_transcript("You.") == ""
    assert normalize_transcript("  YOU  ") == ""
    assert normalize_transcript("Thanks for watching.") == ""
    assert normalize_transcript("...") == ""
    assert normalize_transcript(".") == ""
    assert normalize_transcript("") == ""
    assert normalize_transcript("   ") == ""
    assert normalize_transcript("um") == ""
    assert normalize_transcript("uh") == ""


def test_normalize_keeps_thank_you_as_possible_speech():
    # Conservative: plain "thank you" can be real learner speech.
    assert normalize_transcript("Thank you") == "Thank you"
