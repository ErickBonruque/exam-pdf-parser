"""Synthetic exam PDFs for the tests.

No real exam text is stored in this repository. The tests draw small PDFs
with reportlab that copy the parts of a real layout that matter: two
columns, bold question headers, alternative letters in their own font,
section headers, a header band and a watermark.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from exam_pdf_parser.layout import LayoutProfile, Line
from exam_pdf_parser.segment import ExamProfile, SectionRule

PAGE_W, PAGE_H = A4  # 595 x 842 points
LEFT_X, RIGHT_X = 40.0, 315.0
TOP_Y = 80.0  # distance from the top of the page to the first line

BODY_FONT, BOLD_FONT, MARKER_FONT = "Helvetica", "Helvetica-Bold", "Courier-Bold"


@dataclass
class Block:
    """Text drawn in one column, line by line, from top to bottom."""

    rows: list[tuple[str, str, float]] = field(default_factory=list)  # (font, text, x offset)

    def header(self, text: str) -> Block:
        self.rows.append((BOLD_FONT, text, 0))
        return self

    def text(self, text: str, indent: float = 0) -> Block:
        self.rows.append((BODY_FONT, text, indent))
        return self

    def alt(self, letter: str, text: str) -> Block:
        self.rows.append((MARKER_FONT, letter, 0))
        self.rows.append((BODY_FONT + "@same", text, 14))
        return self


def draw_pdf(path: Path, pages: list[tuple[Block, Block | None]], watermark: bool = True) -> Path:
    """Draw ``pages``; each page has a left and an optional right column."""
    c = Canvas(str(path), pagesize=A4)
    for left, right in pages:
        if watermark:
            c.setFont(BODY_FONT, 1.5)
            c.drawString(40, PAGE_H - 20, "WATERMARK" * 40)
        c.setFont(BOLD_FONT, 10)
        c.drawString(40, PAGE_H - 30, "PAGE HEADER THAT MUST BE IGNORED")
        for x, block in ((LEFT_X, left), (RIGHT_X, right)):
            if block is None:
                continue
            y = PAGE_H - TOP_Y
            for font, text, dx in block.rows:
                same_line = font.endswith("@same")
                if same_line:
                    font = font.removesuffix("@same")
                    y += 14  # draw on the line of the marker letter
                c.setFont(font, 10)
                c.drawString(x + dx, y, text)
                y -= 14
        c.showPage()
    c.save()
    return path


TEST_PROFILE = ExamProfile(
    name="test",
    layout=LayoutProfile(header_band=0.05, marker_font="Courier"),
    question_header=re.compile(r"^QUESTION\s+(\d+)\b"),
    section_rules=(
        SectionRule(re.compile(r"^MATHEMATICS$"), {"area": "MT", "language": None}),
        SectionRule(re.compile(r"^LANGUAGES$"), {"area": "LC", "language": None}),
        SectionRule(re.compile(r"\(option: English\)"), {"language": "en"}),
    ),
    stop_patterns=(re.compile(r"^END OF EXAM$"),),
)


@pytest.fixture
def profile() -> ExamProfile:
    return TEST_PROFILE


@pytest.fixture
def make_pdf(tmp_path: Path) -> Callable[..., Path]:
    def _make(pages: list[tuple[Block, Block | None]], name: str = "exam.pdf", **kw: bool) -> Path:
        return draw_pdf(tmp_path / name, pages, **kw)

    return _make


def line(
    text: str,
    *,
    top: float = 100,
    x0: float = 40,
    page: int = 1,
    column: int = 0,
    size: float = 10,
    bold: bool = False,
    marker: str | None = None,
) -> Line:
    """A :class:`Line` with sensible defaults, for unit tests of the segmenter."""
    return Line(page, column, top, top + size, x0, text, size, bold, marker)
