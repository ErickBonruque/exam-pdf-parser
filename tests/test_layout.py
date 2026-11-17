from __future__ import annotations

from conftest import Block
from exam_pdf_parser.layout import (
    LayoutProfile,
    Line,
    PageContent,
    drop_running_footers,
    find_gutter,
    group_lines,
    keep_word,
    read_pdf,
)


def word(text: str, x0: float, top: float, *, size: float = 10, font: str = "Arial") -> dict:
    width = 6 * len(text)
    return {
        "text": text,
        "x0": x0,
        "x1": x0 + width,
        "top": top,
        "bottom": top + size,
        "size": size,
        "fontname": font,
    }


def two_columns(n: int = 40) -> list[dict]:
    left = [word("left", 40 + 30 * (i % 6), 100 + 12 * (i // 6)) for i in range(n)]
    right = [word("right", 320 + 30 * (i % 6), 100 + 12 * (i // 6)) for i in range(n)]
    return left + right


def test_find_gutter_between_two_columns() -> None:
    gutter = find_gutter(two_columns(), width=600)
    assert gutter is not None
    assert 220 < gutter <= 320


def test_find_gutter_ignores_wide_gap_inside_a_column() -> None:
    # Left column ends at x=214. The right column has short labels at x=300 and
    # a caption at x=420, so the strip 306-420 is wider than the gutter 214-300.
    words = [word("left", 40 + 30 * (i % 6), 100 + 12 * (i // 6)) for i in range(60)]
    words += [word("A", 300, 100 + 40 * i) for i in range(10)]
    words += [word("label", 420, 100 + 40 * i) for i in range(10)]
    gutter = find_gutter(words, width=600)
    assert gutter is not None
    assert 214 < gutter < 300


def test_find_gutter_none_for_one_column_of_full_lines() -> None:
    words = [word("x" * 80, 40, 100 + 12 * i) for i in range(30)]  # each word crosses the middle
    assert find_gutter(words, width=600) is None


def test_find_gutter_none_when_one_side_is_almost_empty() -> None:
    words = [word("left", 40 + 30 * (i % 6), 100 + 12 * (i // 6)) for i in range(60)]
    words.append(word("note", 400, 500))
    assert find_gutter(words, width=600) is None


def test_keep_word_drops_watermark_barcode_and_bands() -> None:
    profile = LayoutProfile(
        min_font_size=4, ignore_fonts=("C39",), header_band=0.1, footer_band=0.1
    )
    assert keep_word(word("ok", 40, 300), 1000, profile)
    assert not keep_word(word("tiny", 40, 300, size=1.5), 1000, profile)
    assert not keep_word(word("*123*", 40, 300, font="ABCDEF+C39HrP36DlTt"), 1000, profile)
    assert not keep_word(word("head", 40, 50), 1000, profile)
    assert not keep_word(word("foot", 40, 950), 1000, profile)


def test_group_lines_merges_words_within_tolerance_and_marks_letters() -> None:
    profile = LayoutProfile(marker_font="Pi")
    words = [
        word("A", 40, 300, font="XYZ+PiFont"),
        word("first", 55, 301),
        word("answer", 90, 301),
        word("next", 55, 312),
    ]
    lines = group_lines(words, page=1, column=0, profile=profile)
    assert [ln.text for ln in lines] == ["first answer", "next"]
    assert lines[0].marker == "A"
    assert lines[1].marker is None


def test_group_lines_splits_grid_alternatives_on_one_row() -> None:
    profile = LayoutProfile(marker_font="Pi")
    words = [
        word("A", 40, 300, font="Pi"),
        word("10", 55, 300),
        word("D", 200, 300, font="Pi"),
        word("40", 215, 300),
    ]
    lines = group_lines(words, page=1, column=0, profile=profile)
    assert [(ln.marker, ln.text) for ln in lines] == [("A", "10"), ("D", "40")]


def test_letter_in_body_font_is_not_a_marker() -> None:
    profile = LayoutProfile(marker_font="Pi")
    lines = group_lines([word("A", 40, 300), word("house", 55, 300)], 1, 0, profile)
    assert lines[0].marker is None
    assert lines[0].text == "A house"


def test_read_pdf_reads_left_column_before_right(make_pdf, profile) -> None:
    pdf = make_pdf(
        [(Block().text("left one").text("left two"), Block().text("right one"))], watermark=True
    )
    (page,) = list(read_pdf(pdf, profile.layout))
    assert [(ln.column, ln.text) for ln in page.lines] == [
        (0, "left one"),
        (0, "left two"),
        (1, "right one"),
    ]
    # The watermark and the page header were dropped.
    assert all(ln.size == 10 for ln in page.lines)


def page_with(*lines: tuple[float, float, str], marker: str | None = None) -> PageContent:
    return PageContent(
        lines=[
            Line(1, 0, top, top + size, 31, text, size, False, marker) for top, size, text in lines
        ],
        height=800,
    )


def test_drop_running_footers_by_repetition() -> None:
    profile = LayoutProfile(footer_zone=0.12, footer_max_size=8.5)
    pages = [
        page_with((400, 10, "body"), (744, 7, f"{n} CN • CADERNO 5"), (760, 7, f"{n}"))
        for n in range(1, 9)
    ]
    # Only on one page: a source reference and a numeric alternative at the bottom.
    pages[3].lines.append(Line(4, 0, 726, 732, 31, "Disponível em: x.org.", 6, False))
    pages[5].lines.append(Line(6, 0, 735, 745, 31, "360", 9.8, False))
    removed = drop_running_footers(pages, profile)
    assert removed == 16
    assert [ln.text for ln in pages[3].lines] == ["body", "Disponível em: x.org."]
    assert [ln.text for ln in pages[5].lines] == ["body", "360"]


def test_footer_one_point_lower_on_some_pages_is_still_found() -> None:
    profile = LayoutProfile(footer_zone=0.12, footer_max_size=8.5)
    pages = [page_with((743 + n % 2, 7, "CN • CADERNO 5")) for n in range(6)]
    assert drop_running_footers(pages, profile) == 6


def test_alternative_line_is_never_a_footer() -> None:
    profile = LayoutProfile(footer_zone=0.12, footer_max_size=8.5)
    pages = [page_with((744, 7.8, "2 HO CHO"), marker="B") for _ in range(6)]
    assert drop_running_footers(pages, profile) == 0
