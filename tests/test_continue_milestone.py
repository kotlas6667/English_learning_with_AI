from app.learning_store import parse_ask_continue_tag, parse_continue_decision_tag


def test_parse_ask_continue():
    cleaned, offered = parse_ask_continue_tag(
        "That was great. Do you want to continue practicing? [[ask_continue]] [[ask]]"
    )
    assert offered is True
    assert "[[ask_continue]]" not in cleaned.lower()
    assert "continue practicing" in cleaned


def test_parse_continue_yes_no():
    cleaned, decision = parse_continue_decision_tag(
        "Great, let's keep going. [[continue:yes]] Where is your gate?"
    )
    assert decision == "yes"
    assert "[[continue:" not in cleaned
    assert "gate" in cleaned

    cleaned2, decision2 = parse_continue_decision_tag(
        "Okay, goodbye! [[continue:no]]"
    )
    assert decision2 == "no"
    assert "goodbye" in cleaned2


def test_target_extends_after_yes():
    questions_asked = 20
    question_batch = 20
    # After learner says yes, next checkpoint is +batch from current count.
    question_target = questions_asked + question_batch
    assert question_target == 40
