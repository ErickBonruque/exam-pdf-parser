"""ENEM: booklet layout, official file names and the answer-key PDF.

INEP publishes each booklet (``PV``) and its answer key (``GB``) as PDF at
predictable addresses. Day 1 has Languages (LC) and Human Sciences (CH);
day 2 has Natural Sciences (CN) and Mathematics (MT). In LC, questions 1 to 5
are printed twice: one set for English and one for Spanish.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

from exam_pdf_parser.layout import LayoutProfile
from exam_pdf_parser.models import AnswerKeyEntry
from exam_pdf_parser.segment import ExamProfile, SectionRule

BASE_URL = "https://download.inep.gov.br/enem/provas_e_gabaritos"
REGULAR_BOOKLETS = {1: (1, 2, 3, 4), 2: (5, 6, 7, 8)}  # day -> printed booklet numbers
AREAS_BY_DAY = {1: ("LC", "CH"), 2: ("CN", "MT")}

PROFILE = ExamProfile(
    name="enem",
    layout=LayoutProfile(
        min_font_size=4.0,  # the "ENEM2024ENEM2024..." watermark is 1-1.5 pt
        ignore_fonts=("C39",),  # barcode font
        header_band=0.06,
        # Footers move between editions (from 93% to 97% of the page height),
        # so a fixed band would cut the last alternative in some years. The
        # running footer is found by repetition instead (layout.drop_running_footers).
        footer_band=0.035,
        footer_zone=0.12,
        footer_max_size=8.5,
        marker_font="BundesbahnPi",  # A-E are drawn as glyphs in this font
        # Justified lines leave narrow spaces; 2.0 read the same item the same
        # way in all four booklet colors more often than 1.5 or 3.0.
        x_tolerance=2.0,
    ),
    question_header=re.compile(r"^QUEST[ÃA]O\s+(\d{1,3})\b", re.IGNORECASE),
    section_rules=(
        SectionRule(re.compile(r"^LINGUAGENS,\s+C[ÓO]DIGOS"), {"area": "LC", "language": None}),
        SectionRule(re.compile(r"^CI[ÊE]NCIAS\s+HUMANAS"), {"area": "CH", "language": None}),
        SectionRule(re.compile(r"^CI[ÊE]NCIAS\s+DA\s+NATUREZA"), {"area": "CN", "language": None}),
        SectionRule(re.compile(r"^MATEM[ÁA]TICA\s+E\s+SUAS"), {"area": "MT", "language": None}),
        SectionRule(re.compile(r"\(op[çc][ãa]o:?\s+ingl[êe]s\)", re.I), {"language": "en"}),
        SectionRule(re.compile(r"\(op[çc][ãa]o:?\s+espanhol\)", re.I), {"language": "es"}),
        SectionRule(re.compile(r"^Quest[õo]es\s+de\s+\d+\s+a\s+\d+\s*$"), {"language": None}),
    ),
    stop_patterns=(
        re.compile(r"PROPOSTA\s+DE\s+REDA[ÇC][ÃA]O"),
        re.compile(r"INSTRU[ÇC][ÕO]ES\s+PARA\s+A\s+REDA[ÇC][ÃA]O"),
        re.compile(r"Transcreva\s+a\s+sua\s+Reda[çc][ãa]o"),
        # Color table on the back cover: "1 Dia", "1°Capa", "Azul 1", ...
        re.compile(r"^\d\s*°\s*Capa\b"),
        re.compile(r"^\d\s+Dia(\s+\d\s+Dia)?$"),
    ),
)


@dataclass(frozen=True, slots=True)
class Booklet:
    """One printed booklet of one ENEM edition."""

    year: int
    day: int
    number: int

    def __post_init__(self) -> None:
        if self.day not in REGULAR_BOOKLETS:
            raise ValueError(f"day must be 1 or 2, got {self.day}")
        if self.number < 1:
            raise ValueError(f"booklet number must be positive, got {self.number}")

    @property
    def exam_id(self) -> str:
        return f"enem-{self.year}-d{self.day}-cd{self.number}"

    def file_name(self, kind: str) -> str:
        """``kind`` is ``PV`` (booklet) or ``GB`` (answer key)."""
        if kind not in ("PV", "GB"):
            raise ValueError(f"kind must be PV or GB, got {kind!r}")
        return f"{self.year}_{kind}_impresso_D{self.day}_CD{self.number}.pdf"

    def url(self, kind: str) -> str:
        return f"{BASE_URL}/{self.file_name(kind)}"


def regular_booklets(year: int) -> list[Booklet]:
    """The eight booklets of the regular application (four colors per day)."""
    return [Booklet(year, day, n) for day, numbers in REGULAR_BOOKLETS.items() for n in numbers]


_ANSWER = r"(?:[A-E]|(?i:anulad[ao]))"
_ENTRY = re.compile(rf"\b(\d{{1,3}})((?:\s+{_ANSWER}\b)+)")
_COLOR = re.compile(
    r"^\s*(Azul|Amarel[ao]|Branc[ao]|Rosa|Cinza|Verde|Laranja|Rox[ao])\s*$",
    re.MULTILINE | re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class AnswerKey:
    color: str | None
    entries: tuple[AnswerKeyEntry, ...]

    def lookup(self) -> dict[tuple[int, str | None], AnswerKeyEntry]:
        return {(e.number, e.language): e for e in self.entries}


def parse_answer_key_text(text: str) -> AnswerKey:
    """Parse the text of an ENEM answer-key PDF.

    Each row holds one or two questions: ``1 C C 46 C``. A number followed by
    two answers is a language question (English first, then Spanish, as in
    the column headers). An annulled question shows "Anulada" (any case)
    instead of a letter.
    """
    entries: list[AnswerKeyEntry] = []
    for line in text.splitlines():
        for number, answers in _ENTRY.findall(line):
            values = answers.split()
            languages: tuple[str | None, ...] = ("en", "es") if len(values) == 2 else (None,)
            if len(values) > 2:
                raise ValueError(f"unexpected answer-key row: {line!r}")
            for lang, value in zip(languages, values, strict=True):
                letter = value if len(value) == 1 and value in "ABCDE" else None
                entries.append(
                    AnswerKeyEntry(
                        number=int(number), language=lang, answer=letter, annulled=letter is None
                    )
                )
    color = m.group(1).capitalize() if (m := _COLOR.search(text)) else None
    keys = [(e.number, e.language) for e in entries]
    if len(keys) != len(set(keys)):
        raise ValueError("answer key has repeated questions")
    return AnswerKey(color, tuple(sorted(entries, key=lambda e: (e.number, e.language or ""))))


def parse_answer_key(path: Path) -> AnswerKey:
    with pdfplumber.open(path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    return parse_answer_key_text(text)
