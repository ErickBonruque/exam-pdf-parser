"""Measure the parser against the official item data of the ENEM microdata.

For each booklet, the expected questions are the items of its ``CO_PROVA``
codes (one per area). A question is *found* when its ``(number, language)``
pair exists in the parsed output. The answer check compares the answer the
parser attached to each question (read from the answer-key PDF) with the
answer in the microdata, so it tests numbering, language sections and the
answer-key reader together.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from exam_pdf_parser import enem
from exam_pdf_parser.microdata import Item, normalize_color
from exam_pdf_parser.models import Question
from exam_pdf_parser.parse import parse_exam

Key = tuple[int, str | None]


@dataclass(slots=True)
class BookletScore:
    exam_id: str
    color: str | None
    expected: int = 0
    found: int = 0
    extra: int = 0
    area_ok: int = 0
    alternatives_found: int = 0  # all five letters located
    alternatives_with_text: int = 0  # all five have text (not only an image)
    readable_text: int = 0  # no unmapped glyphs in stem or alternatives
    answers_compared: int = 0
    answers_equal: int = 0
    annulled_expected: int = 0
    annulled_equal: int = 0
    problems: list[str] = field(default_factory=list)


def expected_items(
    booklet: enem.Booklet,
    color: str,
    items_by_code: dict[int, list[Item]],
    codes: dict[tuple[int, str, str], int],
) -> dict[Key, Item]:
    expected: dict[Key, Item] = {}
    for area in enem.AREAS_BY_DAY[booklet.day]:
        code = codes.get((booklet.year, area, normalize_color(color)))
        if code is None:
            raise KeyError(f"no booklet code for {booklet.year} {area} {color}")
        for item in items_by_code.get(code, []):
            expected[(item.position, item.language)] = item
    return expected


def score_booklet(
    booklet: enem.Booklet,
    questions: list[Question],
    color: str,
    expected: dict[Key, Item],
) -> BookletScore:
    score = BookletScore(booklet.exam_id, color, expected=len(expected))
    parsed = {q.key: q for q in questions}
    if len(parsed) != len(questions):
        score.problems.append("repeated (number, language) in parsed output")
    score.extra = len(parsed.keys() - expected.keys())
    for key, item in expected.items():
        q = parsed.get(key)
        if q is None:
            score.problems.append(f"missing question {key}")
            continue
        score.found += 1
        score.area_ok += q.area == item.area
        score.readable_text += not any(w.startswith("unmapped glyphs") for w in q.warnings)
        if len(q.alternatives) == 5:
            score.alternatives_found += 1
            score.alternatives_with_text += all(a.text for a in q.alternatives)
        if item.annulled:
            score.annulled_expected += 1
            score.annulled_equal += q.annulled
            if not q.annulled:
                score.problems.append(f"annulled {key}: parsed answer {q.answer}")
        else:
            score.answers_compared += 1
            if q.answer == item.answer:
                score.answers_equal += 1
            else:
                score.problems.append(f"answer {key}: parsed {q.answer}, official {item.answer}")
    return score


def evaluate_booklet(
    booklet: enem.Booklet,
    pdf_dir: Path,
    items_by_code: dict[int, list[Item]],
    codes: dict[tuple[int, str, str], int],
) -> tuple[BookletScore, list[Question], dict[Key, Item]]:
    key = enem.parse_answer_key(pdf_dir / booklet.file_name("GB"))
    if key.color is None:
        raise ValueError(f"{booklet.exam_id}: booklet color not found in the answer key")
    questions = parse_exam(
        pdf_dir / booklet.file_name("PV"), enem.PROFILE, booklet.exam_id, key.lookup()
    )
    expected = expected_items(booklet, key.color, items_by_code, codes)
    return score_booklet(booklet, questions, key.color, expected), questions, expected


def group_by_code(items: list[Item]) -> dict[int, list[Item]]:
    grouped: dict[int, list[Item]] = defaultdict(list)
    for item in items:
        grouped[item.co_prova].append(item)
    return dict(grouped)


TextKey = tuple[int, int, str | None]  # (year, item id, language)


def item_texts(
    booklet: enem.Booklet, questions: list[Question], expected: dict[Key, Item]
) -> list[tuple[TextKey, str]]:
    """Text of each parsed question, keyed by the item it prints.

    The four colors of a day print the same items in a different order, with
    the alternatives in the same order. A good parser reads the same text for
    one item in every color, whatever its position on the page.
    """
    parsed = {q.key: q for q in questions}
    out = []
    for key, item in expected.items():
        q = parsed.get(key)
        if q is not None:
            parts = [q.stem, *(f"{a.letter}) {a.text}" for a in q.alternatives)]
            text = " ".join(" ".join(parts).split())
            out.append(((booklet.year, item.item_id, item.language), text))
    return out


def text_consistency(texts: list[tuple[TextKey, str]]) -> tuple[int, int]:
    """(items read the same in every booklet, items found in two or more booklets)."""
    by_item: dict[TextKey, list[str]] = defaultdict(list)
    for key, text in texts:
        by_item[key].append(text)
    shared = [v for v in by_item.values() if len(v) > 1]
    return sum(len(set(v)) == 1 for v in shared), len(shared)
