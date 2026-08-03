from app.learning_store import parse_better_tag, parse_score_tag, parse_said_tag, parse_tip_tag


def test_parse_better_tag():
    cleaned, better = parse_better_tag(
        "Sure. [[better:I would like a window seat, please.]] Anything else?"
    )
    assert better == "I would like a window seat, please."
    assert "[[better:" not in cleaned
    assert "Sure." in cleaned
    assert "Anything else?" in cleaned


def test_parse_tip_tag():
    cleaned, tip = parse_tip_tag(
        "Okay. [[tip:Použi would like namiesto I want.]] Gate is B12."
    )
    assert tip == "Použi would like namiesto I want."
    assert "[[tip:" not in cleaned
    assert "Gate is B12." in cleaned


def test_parse_score_tag():
    cleaned, score = parse_score_tag("Nice try. [[score:72]] Next question?")
    assert score == 72
    assert "[[score:" not in cleaned
    assert "Nice try." in cleaned

    cleaned2, score2 = parse_score_tag("[[score:150]] out of range ignored")
    assert score2 is None
    assert "out of range" in cleaned2


def test_feedback_tags_together_with_said():
    reply = (
        "Got it. [[said:I need a window seat.]] "
        "[[better:I would like a window seat, please.]] "
        "[[tip:Zdvorilejšie znie would like.]] "
        "[[score:81]] "
        "Here is your boarding pass. [[ask]]"
    )
    cleaned, said = parse_said_tag(reply)
    cleaned, better = parse_better_tag(cleaned)
    cleaned, tip = parse_tip_tag(cleaned)
    cleaned, score = parse_score_tag(cleaned)
    assert said == "I need a window seat."
    assert better == "I would like a window seat, please."
    assert tip == "Zdvorilejšie znie would like."
    assert score == 81
    assert "[[said:" not in cleaned
    assert "[[better:" not in cleaned
    assert "[[tip:" not in cleaned
    assert "[[score:" not in cleaned
    assert "boarding pass" in cleaned
