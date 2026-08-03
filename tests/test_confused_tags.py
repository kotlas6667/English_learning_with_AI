from app.learning_store import parse_confused_tags


def test_parse_confused_with_note():
    text = "Sure. [[confused:put luggage on the scale|nevedel čo je scale]] Can you put it here?"
    cleaned, items = parse_confused_tags(text)
    assert "[[confused:" not in cleaned
    assert "Can you put it here?" in cleaned
    assert items == [("put luggage on the scale", "nevedel čo je scale")]


def test_parse_confused_summary_only():
    cleaned, items = parse_confused_tags(
        "No problem. [[confused:How many bags do you have?]] One bag?"
    )
    assert items == [("How many bags do you have?", "")]
    assert "One bag?" in cleaned
    assert "[[confused" not in cleaned


def test_parse_confused_none():
    cleaned, items = parse_confused_tags("Hello there.")
    assert cleaned == "Hello there."
    assert items == []
