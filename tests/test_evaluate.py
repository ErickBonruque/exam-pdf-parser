from __future__ import annotations

from exam_pdf_parser.enem import Booklet
from exam_pdf_parser.evaluate import (
    expected_items,
    group_by_code,
    score_booklet,
    text_consistency,
)
from exam_pdf_parser.microdata import Item
from exam_pdf_parser.models import Alternative, Question

FIVE = [Alternative(letter=c, text=c.lower()) for c in "ABCDE"]  # type: ignore[arg-type]


def item(pos: int, answer: str | None, *, lang: str | None = None, area: str = "CN") -> Item:
    return Item(1, pos, area, answer, answer is None, answer is None, lang)


def question(n: int, answer: str | None, *, annulled: bool = False, area: str = "CN") -> Question:
    return Question(
        exam_id="t",
        number=n,
        area=area,
        stem="s",
        alternatives=FIVE,
        answer=answer,
        annulled=annulled,
        pages=[1],
    )


def test_score_counts_found_answers_and_annulled() -> None:
    expected = {
        (91, None): item(91, "A"),
        (92, None): item(92, "B"),
        (93, None): item(93, None),
        (94, None): item(94, "D"),
    }
    questions = [
        question(91, "A"),
        question(92, "C"),  # wrong answer
        question(93, None, annulled=True),
        question(95, "E"),  # not in the microdata
    ]
    s = score_booklet(Booklet(2099, 2, 5), questions, "Azul", expected)
    assert (s.expected, s.found, s.extra) == (4, 3, 1)
    assert (s.answers_compared, s.answers_equal) == (2, 1)
    assert (s.annulled_expected, s.annulled_equal) == (1, 1)
    assert s.alternatives_found == s.alternatives_with_text == 3
    assert "missing question (94, None)" in s.problems
    assert any(p.startswith("answer (92, None)") for p in s.problems)


def test_expected_items_uses_both_areas_of_the_day() -> None:
    codes = {(2099, "CN", "azul"): 1, (2099, "MT", "azul"): 2}
    items = [
        Item(1, 91, "CN", "A", False, False, None),
        Item(2, 136, "MT", "B", False, False, None),
    ]
    got = expected_items(Booklet(2099, 2, 7), "Azul", group_by_code(items), codes)
    assert set(got) == {(91, None), (136, None)}


def test_text_consistency_counts_items_seen_in_two_or_more_booklets() -> None:
    texts = [
        ((2099, 1, None), "same"),
        ((2099, 1, None), "same"),
        ((2099, 2, None), "one"),
        ((2099, 2, None), "other"),
        ((2099, 3, None), "only one booklet"),
    ]
    assert text_consistency(texts) == (1, 2)
