from __future__ import annotations

import re

from conftest import TEST_PROFILE, line
from exam_pdf_parser.layout import ImageBox, LayoutProfile, PageContent
from exam_pdf_parser.segment import (
    ExamProfile,
    RawQuestion,
    find_alternative_starts,
    has_image,
    join_lines,
    reorder_grid,
    segment,
    split_parts,
)

# A layout without a marker font: alternatives look like "(A) text".
PLAIN = ExamProfile(
    name="plain",
    layout=LayoutProfile(),
    question_header=re.compile(r"^Quest[aã]o\s+(\d+)"),
)


def alts(top: float = 200, x0: float = 40) -> list:
    return [
        line(t, top=top + 12 * i, x0=x0, marker=letter)
        for i, (letter, t) in enumerate(
            zip("ABCDE", ["one", "two", "three", "four", "five"], strict=True)
        )
    ]


def test_segment_sets_context_and_splits_questions() -> None:
    page = PageContent(
        lines=[
            line("cover text before any question", top=50),
            line("LANGUAGES", top=60, bold=True),
            line("Questions 1 to 2 (option: English)", top=70, bold=True),
            line("QUESTION 1", top=80, bold=True),
            line("stem one", top=92),
            line("QUESTION 2", top=120, bold=True),
            line("stem two", top=132),
            line("MATHEMATICS", top=400, bold=True),
            line("QUESTION 3", top=420, bold=True),
            line("stem three", top=432),
            line("END OF EXAM", top=600, bold=True),
            line("back cover text", top=620),
        ]
    )
    questions, _ = segment([page], TEST_PROFILE)
    assert [(q.number, q.context) for q in questions] == [
        (1, {"area": "LC", "language": "en"}),
        (2, {"area": "LC", "language": "en"}),
        (3, {"area": "MT", "language": None}),
    ]
    assert [ln.text for ln in questions[2].lines] == ["stem three"]  # stop line ends it


def test_header_must_be_bold_by_default() -> None:
    page = PageContent(lines=[line("QUESTION 1", bold=False)])
    questions, _ = segment([page], TEST_PROFILE)
    assert questions == []


def test_header_hidden_under_an_image_is_ignored() -> None:
    page = PageContent(
        lines=[
            line("QUESTION 5", top=80, bold=True),
            line("QUESTION 6", top=300, bold=True),  # inside the image below
            line("command of question 5", top=420),
        ],
        images=[ImageBox(page=1, column=0, top=150, bottom=400, x0=30, x1=280)],
    )
    questions, _ = segment([page], TEST_PROFILE)
    assert [q.number for q in questions] == [5]
    assert [ln.text for ln in questions[0].lines] == ["command of question 5"]


def test_margin_strip_does_not_hide_headers() -> None:
    page = PageContent(
        lines=[line("QUESTION 1", top=80, x0=66, bold=True)],
        images=[ImageBox(page=1, column=0, top=20, bottom=820, x0=24, x1=46)],
    )
    questions, _ = segment([page], TEST_PROFILE)
    assert [q.number for q in questions] == [1]


def test_text_after_header_number_goes_to_stem() -> None:
    page = PageContent(lines=[line("QUESTION 7 Read the text.", bold=True)])
    questions, _ = segment([page], TEST_PROFILE)
    assert questions[0].number == 7
    assert questions[0].lines[0].text == "Read the text."


def test_question_continues_across_columns_and_pages() -> None:
    pages = [
        PageContent(lines=[line("QUESTION 1", bold=True), line("part one", top=700)]),
        PageContent(lines=[line("part two", page=2, top=80)]),
    ]
    (q,), _ = segment(pages, TEST_PROFILE)
    assert [ln.text for ln in q.lines] == ["part one", "part two"]


def test_marker_font_ignores_prose_that_starts_with_a_letter() -> None:
    lines = [line("A letter was sent to the author.", top=100), *alts()]
    starts = find_alternative_starts(lines, TEST_PROFILE)
    assert starts == {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}


def test_plain_layout_uses_the_pattern_and_the_last_ordered_run() -> None:
    lines = [
        line("(A) looks like an alternative inside the stem"),
        line("command"),
        *[line(f"({c}) option {c}") for c in "ABCDE"],
    ]
    starts = find_alternative_starts(lines, PLAIN)
    assert starts == {"A": 2, "B": 3, "C": 4, "D": 5, "E": 6}


def test_missing_letter_gives_none() -> None:
    lines = [line(f"({c}) option") for c in "ABCE"]
    assert find_alternative_starts(lines, PLAIN) is None


def test_split_parts_stem_and_multiline_alternative() -> None:
    raw = RawQuestion(
        1,
        {},
        line("QUESTION 1", bold=True),
        [
            line("First paragraph", top=90),
            line("continues here.", top=102),
            line("Second paragraph.", top=114, x0=55),
            *alts(top=140),
            line("five continues", top=200, x0=54),
        ],
    )
    parts = split_parts(raw, TEST_PROFILE)
    assert parts.stem == "First paragraph continues here.\nSecond paragraph."
    assert parts.alternatives == {
        "A": "one",
        "B": "two",
        "C": "three",
        "D": "four",
        "E": "five five continues",
    }
    assert parts.warnings == ()


def test_split_parts_warns_when_no_alternatives() -> None:
    raw = RawQuestion(1, {}, line("QUESTION 1"), [line("only text")])
    parts = split_parts(raw, TEST_PROFILE)
    assert parts.alternatives == {}
    assert parts.warnings == ("alternatives not found",)


def test_reorder_grid_reads_down_each_sub_column() -> None:
    # A | D
    # B | E
    # C
    grid = [
        line("10", top=200, x0=40, marker="A"),
        line("40", top=200, x0=200, marker="D"),
        line("20", top=230, x0=40, marker="B"),
        line("50", top=230, x0=200, marker="E"),
        line("30", top=260, x0=40, marker="C"),
    ]
    ordered = reorder_grid([line("stem", top=150), *grid], TEST_PROFILE)
    assert [ln.marker for ln in ordered] == [None, "A", "B", "C", "D", "E"]


def test_reorder_grid_reads_across_rows_when_letters_go_across() -> None:
    # A B C
    # D E
    grid = [
        line("", top=534, x0=371, marker="C"),
        line("", top=539, x0=31, marker="A"),
        line("", top=539, x0=202, marker="B"),
        line("", top=668, x0=31, marker="D"),
        line("", top=668, x0=202, marker="E"),
    ]
    ordered = reorder_grid([line("stem", top=400), *grid], TEST_PROFILE)
    assert [ln.marker for ln in ordered] == [None, "A", "B", "C", "D", "E"]


def test_reorder_grid_keeps_a_single_list() -> None:
    lines = [line("stem"), *alts()]
    assert reorder_grid(lines, TEST_PROFILE) == lines


def test_join_lines_breaks_paragraph_on_smaller_type() -> None:
    lines = [
        line("Body text.", size=10),
        line("SOURCE, A. Book. 2020.", size=8),
        line("Command of the question", size=10),
    ]
    assert join_lines(lines, indent=8) == (
        "Body text.\nSOURCE, A. Book. 2020.\nCommand of the question"
    )


def test_join_lines_keeps_hyphen_at_line_end() -> None:
    assert join_lines([line("well-"), line("known")], indent=8) == "well-known"


def test_has_image_uses_question_span_in_the_same_column() -> None:
    raw = RawQuestion(
        1,
        {},
        line("QUESTION 1", top=100, bold=True),
        [line("text", top=400)],
    )
    inside = ImageBox(page=1, column=0, top=150, bottom=350)
    other_column = ImageBox(page=1, column=1, top=150, bottom=350)
    below = ImageBox(page=1, column=0, top=500, bottom=600)
    assert has_image(raw, [inside])
    assert not has_image(raw, [other_column, below])
