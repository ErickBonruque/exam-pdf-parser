from __future__ import annotations

from types import SimpleNamespace

import pytest
from pdfminer.psparser import LIT

from exam_pdf_parser.glyphs import (
    ARIAL_GLYPH_ORDER,
    REPLACEMENT,
    char_for_glyph,
    differences,
    family,
    missing_codes,
    repair_font,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("g3", " "),
        ("g36", "A"),
        ("g68", "a"),
        ("g109", "ã"),  # before index 172 Arial matches Apple's order
        ("g171", "…"),  # same index in both orders
        ("g173", "Ã"),  # Apple 172 is nonbreakingspace, absent in Arial: shift by one
        ("g174", "Õ"),
        ("g191", "fi"),  # ligature, written as two letters
        ("g192", "fl"),
        ("g200", "Á"),
        ("g207", "Ó"),  # Apple 210 is the apple logo, absent in Arial
        ("g237", "−"),  # minus sign
        ("g238", "×"),
    ],
)
def test_arial_glyph_index_to_char(name: str, expected: str) -> None:
    assert char_for_glyph(name, ARIAL_GLYPH_ORDER) == expected


def test_arial_order_drops_two_apple_only_glyphs() -> None:
    assert "nonbreakingspace" not in ARIAL_GLYPH_ORDER
    assert "apple" not in ARIAL_GLYPH_ORDER
    assert len(ARIAL_GLYPH_ORDER) == 256


def test_standard_names_need_no_order() -> None:
    assert char_for_glyph("ccedilla", None) == "ç"
    assert char_for_glyph("g70", None) is None
    assert char_for_glyph("g9999", ARIAL_GLYPH_ORDER) is None
    assert char_for_glyph(".notdef", None) is None


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        ("EOIEPB+ArialMT", "Arial"),
        ("EOIEOA+Arial-BoldMT", "Arial"),
        ("ABCDEF+SymbolMT", "Symbol"),
        ("CambriaMath", "CambriaMath"),
        ("Arial,Bold", "Arial"),
    ],
)
def test_family(base: str, expected: str) -> None:
    assert family(base) == expected


def test_differences_counts_codes_after_each_number() -> None:
    enc = {"Differences": [2, LIT("g70"), LIT("g82"), 32, LIT("space")]}
    assert differences(enc) == {2: "g70", 3: "g82", 32: "space"}
    assert differences(LIT("WinAnsiEncoding")) == {}


def test_missing_codes_only_touches_unmapped_gid_names() -> None:
    diffs = {2: "g70", 3: "g82", 32: "space", 65: "A", 66: "g37"}
    to_unicode = {32: " ", 65: "A", 66: "B"}
    assert missing_codes(diffs, to_unicode, "XYZ+ArialMT") == {2: "c", 3: "o"}


def test_missing_codes_unknown_font_gets_replacement_char() -> None:
    assert missing_codes({5: "g152"}, {}, "XYZ+SymbolMT") == {5: REPLACEMENT}


def test_repair_font_updates_the_font_table() -> None:
    font = SimpleNamespace(
        cid2unicode={2: "\x02", 33: "!"},  # what pdfminer guessed from the base encoding
        unicode_map=SimpleNamespace(cid2unichr={32: " "}),
    )
    spec = {
        "BaseFont": LIT("EOIEPB+ArialMT"),
        "Encoding": {"Differences": [2, LIT("g70"), 32, LIT("space"), LIT("g47")]},
    }
    assert repair_font(font, spec) == 2  # type: ignore[arg-type]
    assert font.cid2unicode == {2: "c", 33: "L"}


def test_repair_font_skips_composite_fonts() -> None:
    font = SimpleNamespace(cid2unicode={})
    assert repair_font(font, {"DescendantFonts": []}) == 0  # type: ignore[arg-type]
