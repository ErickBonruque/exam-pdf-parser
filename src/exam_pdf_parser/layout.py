"""Turn the words of a PDF page into text lines in reading order.

Exam PDFs are usually set in two columns. ``pdfplumber`` gives each word
with its position and font. This module:

1. drops words that are not content (tiny watermark text, barcodes, page
   header and footer bands);
2. finds the gap between the columns (the "gutter");
3. groups the words of each column into lines, top to bottom;
4. marks lines that start with an alternative letter (A-E) drawn in a
   special marker font, when the layout uses one.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any

import pdfplumber
from pdfplumber.utils.text import extract_words

from exam_pdf_parser.glyphs import repair_fonts

Word = dict[str, Any]


@dataclass(frozen=True, slots=True)
class LayoutProfile:
    """What to keep from a page and how to read it.

    Attributes:
        min_font_size: Words smaller than this are dropped (watermarks).
        ignore_fonts: Words whose font name contains one of these are dropped.
        header_band: Fraction of the page height at the top to ignore.
        footer_band: Fraction of the page height at the bottom to ignore.
        footer_zone: Fraction of the page height at the bottom where running
            footers are looked for (see :func:`drop_running_footers`).
        footer_max_size: Running footers are set in this size or smaller.
        footer_min_share: A footer sits at the same height on at least this
            share of the pages.
        x_tolerance: Max gap (points) between two characters of one word.
        marker_font: Font used to draw alternative letters, if any.
        line_tolerance: Max vertical distance (points) between words of one line.
    """

    min_font_size: float = 4.0
    ignore_fonts: tuple[str, ...] = ()
    header_band: float = 0.0
    footer_band: float = 0.0
    footer_zone: float = 0.0
    footer_max_size: float = 0.0
    footer_min_share: float = 0.3
    x_tolerance: float = 3.0
    marker_font: str | None = None
    line_tolerance: float = 3.0


@dataclass(frozen=True, slots=True)
class Line:
    """One line of text in one column of one page."""

    page: int  # 1-based
    column: int  # 0 = left (or only) column, 1 = right column
    top: float
    bottom: float
    x0: float
    text: str
    size: float
    bold: bool
    marker: str | None = None  # alternative letter drawn in the marker font


@dataclass(frozen=True, slots=True)
class ImageBox:
    """Position of an image on a page, used to flag questions with figures."""

    page: int
    column: int
    top: float
    bottom: float
    x0: float = 0.0
    x1: float = float("inf")


@dataclass(slots=True)
class PageContent:
    lines: list[Line] = field(default_factory=list)
    images: list[ImageBox] = field(default_factory=list)
    height: float = 0.0


_MARKER_TEXT = re.compile(r"^[A-E]$")


def find_gutter(words: Sequence[Word], width: float, *, max_crossing: float = 0.01) -> float | None:
    """Return the x position that splits two columns, or ``None`` for one column.

    Looks at the middle 30% of the page for the x positions crossed by the
    fewest words. Of the runs of such positions, it takes the one closest to
    the page center (a wide empty strip next to a figure inside one column
    is not the gutter) and returns its middle. If more
    than ``max_crossing`` of the words cross even there, or one side is
    almost empty, the page is treated as one column.
    """
    if not words:
        return None
    xs = range(int(width * 0.35), int(width * 0.65) + 1)
    counts = [sum(1 for w in words if w["x0"] < x < w["x1"]) for x in xs]
    best = min(counts)
    if best > max_crossing * len(words):
        return None
    runs: list[tuple[int, int]] = []  # (start, end) indexes of runs at the minimum
    for i, c in enumerate(counts):
        if c != best:
            continue
        if runs and runs[-1][1] == i - 1:
            runs[-1] = (runs[-1][0], i)
        else:
            runs.append((i, i))
    center = width / 2
    lo, hi = min(runs, key=lambda r: abs((xs[r[0]] + xs[r[1]]) / 2 - center))
    gutter = float(xs[(lo + hi) // 2])
    left = sum(1 for w in words if w["x1"] <= gutter)
    right = sum(1 for w in words if w["x0"] >= gutter)
    if min(left, right) < 0.05 * len(words):
        return None
    return gutter


def dedupe_chars(chars: Iterable[Word]) -> list[Word]:
    """Drop a character drawn again at the same spot with the same font.

    Some booklets draw each alternative letter twice, so "A" reads as "AA".
    ``pdfplumber`` has ``Page.dedupe_chars``, but it sorts all characters and
    was most of the run time on pages with a watermark.
    """
    seen: set[tuple[str, str, float, float]] = set()
    out: list[Word] = []
    for c in chars:
        key = (c["text"], c["fontname"], round(c["x0"], 1), round(c["top"], 1))
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def keep_word(word: Word, page_height: float, profile: LayoutProfile) -> bool:
    if word["size"] < profile.min_font_size:
        return False
    font = word.get("fontname", "")
    if any(name in font for name in profile.ignore_fonts):
        return False
    if word["top"] < page_height * profile.header_band:
        return False
    return bool(word["bottom"] <= page_height * (1 - profile.footer_band))


def group_lines(
    words: Iterable[Word], page: int, column: int, profile: LayoutProfile
) -> list[Line]:
    """Group the words of one column into lines, top to bottom."""
    rows: list[list[Word]] = []
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if rows and abs(word["top"] - rows[-1][0]["top"]) <= profile.line_tolerance:
            rows[-1].append(word)
        else:
            rows.append([word])
    return [
        _make_line(part, page, column, profile) for row in rows for part in _split_row(row, profile)
    ]


def _is_marker(word: Word, profile: LayoutProfile) -> bool:
    return bool(
        profile.marker_font
        and profile.marker_font in word.get("fontname", "")
        and _MARKER_TEXT.match(word["text"])
    )


def _split_row(row: list[Word], profile: LayoutProfile) -> list[list[Word]]:
    """Split a row before each marker letter that is not its first word.

    Alternatives set in a grid (A next to D) share one row; each one must
    become its own line.
    """
    parts: list[list[Word]] = []
    for word in sorted(row, key=lambda w: w["x0"]):
        if not parts or _is_marker(word, profile):
            parts.append([word])
        else:
            parts[-1].append(word)
    return parts


def _make_line(row: list[Word], page: int, column: int, profile: LayoutProfile) -> Line:
    row = sorted(row, key=lambda w: w["x0"])
    marker = None
    first = row[0]
    if _is_marker(first, profile):
        marker = first["text"]
        text_words = row[1:]
    else:
        text_words = row
    bold_chars = sum(len(w["text"]) for w in row if "Bold" in w.get("fontname", ""))
    total_chars = sum(len(w["text"]) for w in row)
    return Line(
        page=page,
        column=column,
        top=min(w["top"] for w in row),
        bottom=max(w["bottom"] for w in row),
        x0=first["x0"],
        text=" ".join(w["text"] for w in text_words),
        size=median(w["size"] for w in row),
        bold=bold_chars * 2 > total_chars,
        marker=marker,
    )


def read_page(page: Any, number: int, profile: LayoutProfile) -> PageContent:
    """Lines (left column first) and images of one ``pdfplumber`` page."""
    chars = dedupe_chars(c for c in page.chars if c["size"] >= profile.min_font_size)
    words = [
        w
        for w in extract_words(
            chars, x_tolerance=profile.x_tolerance, extra_attrs=["size", "fontname"]
        )
        if keep_word(w, page.height, profile)
    ]
    gutter = find_gutter(words, page.width)
    columns: list[list[Word]] = [[], []]
    for w in words:
        columns[1 if gutter is not None and w["x0"] >= gutter else 0].append(w)

    content = PageContent(height=page.height)
    for col, col_words in enumerate(columns):
        content.lines.extend(group_lines(col_words, number, col, profile))

    for img in page.images:
        w, h = img["x1"] - img["x0"], img["bottom"] - img["top"]
        if w < 20 or h < 20 or (w > 0.9 * page.width and h > 0.9 * page.height):
            continue  # icons, bullets and full-page backgrounds
        if min(w, h) < 0.05 * max(w, h):
            continue  # thin decorative strips along a margin
        col = 1 if gutter is not None and img["x0"] >= gutter else 0
        content.images.append(
            ImageBox(number, col, img["top"], img["bottom"], img["x0"], img["x1"])
        )
    return content


def drop_running_footers(pages: list[PageContent], profile: LayoutProfile) -> int:
    """Remove running footers from ``pages`` in place. Return how many lines went.

    A running footer ("CN • 2º DIA • CADERNO 5 • AMARELO", a page number) is
    in small type near the bottom and sits at the same height on most pages.
    Rules about its text break easily: the gutter cuts it into pieces that
    change from booklet to booklet. Repetition does not depend on the text,
    and it leaves alone what only some pages have at the bottom, such as a
    source reference in small type or a numeric alternative.
    """
    if profile.footer_zone <= 0 or not pages:
        return 0

    def candidate(ln: Line, page: PageContent) -> bool:
        return (
            ln.top >= page.height * (1 - profile.footer_zone)
            and ln.size <= profile.footer_max_size
            and ln.marker is None
        )

    heights: Counter[int] = Counter()
    for page in pages:
        heights.update({round(ln.top) for ln in page.lines if candidate(ln, page)})
    needed = max(2, profile.footer_min_share * len(pages))
    repeated = {y for y in heights if heights[y - 1] + heights[y] + heights[y + 1] >= needed}
    removed = 0
    for page in pages:
        keep = [ln for ln in page.lines if not (candidate(ln, page) and round(ln.top) in repeated)]
        removed += len(page.lines) - len(keep)
        page.lines = keep
    return removed


def read_pdf(path: Path, profile: LayoutProfile) -> Iterator[PageContent]:
    """Yield the content of each page of ``path``, without running footers."""
    with pdfplumber.open(path) as pdf:
        repair_fonts(pdf)
        pages = []
        for i, page in enumerate(pdf.pages, start=1):
            pages.append(read_page(page, i, profile))
            page.flush_cache()
    drop_running_footers(pages, profile)
    yield from pages
