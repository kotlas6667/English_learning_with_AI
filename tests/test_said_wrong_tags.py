from pathlib import Path

from app.learning_store import (
    LearningItem,
    MarkdownLearningStore,
    parse_said_tag,
    parse_wrong_tags,
)


def test_parse_said_tag():
    cleaned, said = parse_said_tag(
        "Thanks. [[said:I do not need a meal on a two-hour flight.]] Any bags?"
    )
    assert said == "I do not need a meal on a two-hour flight."
    assert "[[said:" not in cleaned
    assert "Thanks." in cleaned
    assert "Any bags?" in cleaned


def test_parse_wrong_tags():
    cleaned, items = parse_wrong_tags(
        "Okay. [[wrong:no special meal request|stačí povedať no special requests]] "
        "Can I see your passport?"
    )
    assert items == [("no special meal request", "stačí povedať no special requests")]
    assert "[[wrong:" not in cleaned
    assert "Can I see your passport?" in cleaned


def test_wrong_tag_upserts_comprehension(tmp_path: Path):
    store = MarkdownLearningStore(tmp_path)
    reply = (
        "Fine. [[said:No, I do not need food or drink.]] "
        "[[wrong:special requests / meal preference|žiadne špeciálne požiadavky]] "
        "Passport please?"
    )
    cleaned, said = parse_said_tag(reply)
    cleaned, wrongs = parse_wrong_tags(cleaned)
    assert said == "No, I do not need food or drink."
    assert wrongs == [("special requests / meal preference", "žiadne špeciálne požiadavky")]
    assert "[[said:" not in cleaned
    assert "[[wrong:" not in cleaned

    for summary, note in wrongs:
        store.upsert(
            LearningItem(
                kind="comprehension",
                word=summary[:120],
                translation_sk=note,
                tip=note,
                context=summary,
                significance=8,
            )
        )
    items = [i for i in store.all_items() if i.kind == "comprehension"]
    assert len(items) == 1
    assert "special requests" in items[0].word
