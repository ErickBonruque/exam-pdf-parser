"""Split the lines of an exam into questions, and each question into parts.

The input is the list of lines from :mod:`exam_pdf_parser.layout`, already in
reading order. A question starts at a header line (for example
``QUESTÃO 12``) and ends at the next header or at a stop line. Section
headers (area, language option) set context that applies to the questions
that follow them.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from exam_pdf_parser.layout import ImageBox, LayoutProfile, Line, PageContent

LETTERS = "ABCDE"


@dataclass(frozen=True, slots=True)
class SectionRule:
    """When a header line matches ``pattern``, update the context with ``sets``."""

    pattern: re.Pattern[str]
    sets: Mapping[str, str | None]


@dataclass(frozen=True, slots=True)
class ExamProfile:
    """Everything that is specific to one exam layout."""

    name: str
    layout: LayoutProfile
    question_header: re.Pattern[str]  # group 1 is the question number
    section_rules: tuple[SectionRule, ...] = ()
    stop_patterns: tuple[re.Pattern[str], ...] = ()
    alternative_pattern: re.Pattern[str] = re.compile(r"^\(?([A-E])[).]\s+")
    headers_bold: bool = True
    paragraph_indent: float = 8.0


@dataclass(slots=True)
class RawQuestion:
    number: int
    context: dict[str, str | None]
    header: Line
    lines: list[Line] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Parts:
    stem: str
    alternatives: dict[str, str]
    warnings: tuple[str, ...]


def _is_header_candidate(line: Line, profile: ExamProfile) -> bool:
    return line.bold or not profile.headers_bold


def _under_image(line: Line, images: Iterable[ImageBox]) -> bool:
    """True if the start of the line lies inside an image."""
    return any(
        img.page == line.page
        and img.column == line.column
        and img.top <= line.top < img.bottom
        and img.x0 <= line.x0 < img.x1
        for img in images
    )


def segment(
    pages: Iterable[PageContent], profile: ExamProfile
) -> tuple[list[RawQuestion], list[ImageBox]]:
    """Return the questions in reading order and all images found."""
    questions: list[RawQuestion] = []
    images: list[ImageBox] = []
    context: dict[str, str | None] = {}
    current: RawQuestion | None = None

    for page in pages:
        images.extend(page.images)
        for line in page.lines:
            header = _is_header_candidate(line, profile)
            if header and (m := profile.question_header.match(line.text)):
                if _under_image(line, page.images):
                    # One 2022 booklet has a stray "QUESTÃO 06" left in the text
                    # layer under a comic strip: invisible on paper. Drop it.
                    continue
                current = RawQuestion(int(m.group(1)), dict(context), line)
                questions.append(current)
                rest = line.text[m.end() :].strip()
                if rest:
                    current.lines.append(_replace_text(line, rest))
                continue
            if header and (rule := _match_section(line.text, profile.section_rules)):
                context.update(rule.sets)
                current = None
                continue
            if any(p.search(line.text) for p in profile.stop_patterns):
                current = None
                continue
            if current is not None:
                current.lines.append(line)
    return questions, images


def _match_section(text: str, rules: Iterable[SectionRule]) -> SectionRule | None:
    return next((r for r in rules if r.pattern.search(text)), None)


def _replace_text(line: Line, text: str) -> Line:
    return Line(
        line.page,
        line.column,
        line.top,
        line.bottom,
        line.x0,
        text,
        line.size,
        line.bold,
        line.marker,
    )


def _marker_of(line: Line, profile: ExamProfile) -> tuple[str, str] | None:
    """Return (letter, text after the letter) if the line opens an alternative."""
    if line.marker is not None:
        return line.marker, line.text
    if profile.layout.marker_font is not None:
        return None  # the layout draws letters in a marker font; text "A ..." is prose
    m = profile.alternative_pattern.match(line.text)
    if m and m.group(1) in LETTERS:
        return m.group(1), line.text[m.end() :]
    return None


def reorder_grid(lines: list[Line], profile: ExamProfile, gap: float = 20.0) -> list[Line]:
    """Put alternatives set in a grid in reading order.

    Grids come in two orders. Down each sub-column (A, B, C | D, E) or
    across each row (A B C / D E). Plain top-to-bottom order breaks both. When
    the marker letters start at two or more x positions, try both orders from
    the first marker on and keep the one that reads A, B, C, D, E.
    """
    marker_idx = [i for i, ln in enumerate(lines) if _marker_of(ln, profile)]
    if not marker_idx:
        return lines
    xs = sorted({round(lines[i].x0) for i in marker_idx})
    col_starts = [xs[0]] + [b for a, b in itertools.pairwise(xs) if b - a > gap]
    if len(col_starts) < 2:
        return lines
    first = marker_idx[0]
    region = lines[first:]
    row_tops = sorted({lines[i].top for i in marker_idx})

    def sub_column(ln: Line) -> int:
        return max((k for k, x in enumerate(col_starts) if ln.x0 >= x - 2), default=0)

    def row(ln: Line) -> int:
        return max((k for k, t in enumerate(row_tops) if ln.top >= t - 8), default=0)

    by_column = sorted(region, key=lambda ln: (ln.page, ln.column, sub_column(ln), ln.top))
    by_row = sorted(region, key=lambda ln: (ln.page, ln.column, row(ln), sub_column(ln), ln.top))
    for order in (by_column, by_row):
        letters = [m[0] for ln in order if (m := _marker_of(ln, profile))]
        if letters == sorted(letters) and len(set(letters)) == len(letters):
            return lines[:first] + order
    return lines


def find_alternative_starts(
    lines: list[Line], profile: ExamProfile, letters: str = LETTERS
) -> dict[str, int] | None:
    """Index of the line that opens each alternative, or ``None`` if not all are found.

    Search from the end: the last E, then the last D before it, and so on.
    This ignores a line in the stem that only looks like an alternative.
    """
    starts: dict[str, int] = {}
    end = len(lines)
    for letter in reversed(letters):
        for i in range(end - 1, -1, -1):
            found = _marker_of(lines[i], profile)
            if found and found[0] == letter:
                starts[letter] = i
                end = i
                break
        else:
            return None
    return starts


def join_lines(lines: list[Line], indent: float, size_step: float = 1.0) -> str:
    """Join lines into text.

    A new paragraph starts when a line is indented past the block's left edge
    by ``indent`` points, or when the font size changes by ``size_step`` or
    more (for example, a source reference set in smaller type).
    """
    if not lines:
        return ""
    left: dict[tuple[int, int], float] = {}
    for ln in lines:
        key = (ln.page, ln.column)
        left[key] = min(left.get(key, ln.x0), ln.x0)
    out: list[str] = []
    prev_size = lines[0].size
    for ln in lines:
        text = ln.text.strip()
        if not text:
            continue
        new_size, prev_size = abs(ln.size - prev_size) >= size_step, ln.size
        if not out:
            out.append(text)
        elif new_size or ln.x0 - left[(ln.page, ln.column)] >= indent:
            out.append("\n" + text)
        elif out[-1].endswith("-"):
            out.append(text)
        else:
            out.append(" " + text)
    return "".join(out).strip()


def split_parts(raw: RawQuestion, profile: ExamProfile, letters: str = LETTERS) -> Parts:
    """Split a question into stem and alternatives."""
    lines = reorder_grid(raw.lines, profile)
    starts = find_alternative_starts(lines, profile, letters)
    if starts is None:
        return Parts(join_lines(lines, profile.paragraph_indent), {}, ("alternatives not found",))

    warnings: list[str] = []
    stem = join_lines(lines[: starts[letters[0]]], profile.paragraph_indent)
    if not stem:
        warnings.append("empty stem")
    alternatives: dict[str, str] = {}
    bounds = [starts[c] for c in letters] + [len(lines)]
    for letter, lo, hi in zip(letters, bounds, bounds[1:], strict=False):
        first = lines[lo]
        found = _marker_of(first, profile)
        assert found is not None
        body = [_replace_text(first, found[1]), *lines[lo + 1 : hi]]
        # Inside an alternative every line is a continuation: no paragraphs.
        text = join_lines(body, indent=float("inf"), size_step=float("inf"))
        if not text:
            warnings.append(f"alternative {letter} is empty (image?)")
        alternatives[letter] = text
    return Parts(stem, alternatives, tuple(warnings))


def has_image(raw: RawQuestion, images: Iterable[ImageBox]) -> bool:
    """True if an image sits inside the vertical span of the question in some column."""
    spans: dict[tuple[int, int], tuple[float, float]] = {}
    for ln in [raw.header, *raw.lines]:
        key = (ln.page, ln.column)
        lo, hi = spans.get(key, (ln.top, ln.bottom))
        spans[key] = (min(lo, ln.top), max(hi, ln.bottom))
    for img in images:
        span = spans.get((img.page, img.column))
        if span and img.bottom > span[0] - 5 and img.top < span[1] + 5:
            return True
    return False
