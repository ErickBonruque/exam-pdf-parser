"""Repair fonts whose ``ToUnicode`` table covers only part of the codes.

Some booklets (ENEM 2021, for example) embed font subsets with a ``ToUnicode``
table only for glyphs that have standard names (``A``, ``space``). The other
glyphs are named ``gNN`` in the ``Encoding /Differences`` array, where ``NN``
is the glyph index in the original TrueType font. For those codes ``pdfminer``
either writes ``(cid:N)`` or, worse, falls back to the base encoding and
returns a wrong letter (code 0x21 draws an ``L`` but is read as ``!``). Up to
three quarters of the text of a 2021 booklet is lost or wrong this way.

For Arial the glyph index can be turned back into a character. Arial's first
glyphs follow Apple's standard order of 258 glyph names (the ``post`` table),
except that Arial has no ``nonbreakingspace`` (index 172) and no ``apple``
logo (index 210), so every glyph after each of them moves back by one. This
was checked against the text itself: with this order the 2021 booklets read
"CARTÃO", "QUESTÕES", "África", "Óleo", "conflito", "OH⁻" and "7,0 × 10⁻³";
with plain Apple order they read "CARTÀO", "QUESTÃES", "Êfrica", "Ìleo".

Other fonts with ``gNN`` names (SymbolMT, Cambria) use their own orders, so
their unmapped codes become U+FFFD (the replacement character) instead of a
wrong letter. The question then gets a warning.

``pdfplumber`` keeps one font object per PDF object in its resource manager,
so fixing that object before the pages are read fixes the extracted text.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fontTools.agl import toUnicode
from fontTools.ttLib.standardGlyphOrder import standardGlyphOrder
from pdfminer.pdffont import PDFFont
from pdfminer.pdfinterp import PDFResourceManager
from pdfminer.pdftypes import PDFObjRef, resolve1
from pdfminer.psparser import PSLiteral, literal_name

log = logging.getLogger(__name__)

REPLACEMENT = "�"
ARIAL_GLYPH_ORDER: tuple[str, ...] = tuple(
    name for name in standardGlyphOrder if name not in {"nonbreakingspace", "apple"}
)
GLYPH_ORDERS: dict[str, tuple[str, ...]] = {"Arial": ARIAL_GLYPH_ORDER}
LIGATURES = {"ﬁ": "fi", "ﬂ": "fl"}  # keep words searchable

_GID_NAME = re.compile(r"^g(\d+)$")


def family(base_font: str) -> str:
    """``EOIEPB+Arial-BoldMT`` -> ``Arial``."""
    name = base_font.split("+", 1)[-1]
    return re.split(r"[-,]", name, maxsplit=1)[0].removesuffix("MT")


def char_for_glyph(name: str, order: tuple[str, ...] | None) -> str | None:
    """Character for a glyph name.

    ``gNN`` names need the font's glyph ``order``; without one, or with an
    index past its end, the result is None.
    """
    m = _GID_NAME.match(name)
    if m:
        gid = int(m.group(1))
        if order is None or gid >= len(order):
            return None
        name = order[gid]
    if name.startswith(".") or name in {"nonmarkingreturn", "nonbreakingspace"}:
        return None
    char = toUnicode(name)
    return LIGATURES.get(char, char) or None


def differences(encoding: Any) -> dict[int, str]:
    """``[2 /g70 /g82 32 /space]`` -> {2: "g70", 3: "g82", 32: "space"}."""
    out: dict[int, str] = {}
    if not isinstance(encoding, dict):
        return out
    code = 0
    for item in resolve1(encoding.get("Differences", [])):
        item = resolve1(item)
        if isinstance(item, int):
            code = item
        elif isinstance(item, PSLiteral):
            out[code] = literal_name(item)
            code += 1
    return out


def missing_codes(
    diffs: dict[int, str], to_unicode: dict[int, str], base_font: str
) -> dict[int, str]:
    """Characters for the ``gNN`` codes that ``to_unicode`` does not map.

    Codes of a font with a known glyph order get their character; the others
    get U+FFFD.
    """
    order = GLYPH_ORDERS.get(family(base_font))
    return {
        code: char_for_glyph(name, order) or REPLACEMENT
        for code, name in diffs.items()
        if code not in to_unicode and _GID_NAME.match(name)
    }


def repair_font(font: PDFFont, spec: dict[str, Any]) -> int:
    """Fix one simple font in place. Return the number of codes changed."""
    if "DescendantFonts" in spec or not hasattr(font, "cid2unicode"):
        return 0  # composite (CID) fonts are not handled
    unicode_map = getattr(font, "unicode_map", None)
    to_unicode: dict[int, str] = dict(unicode_map.cid2unichr) if unicode_map is not None else {}
    base = spec.get("BaseFont")
    base_name = literal_name(base) if isinstance(base, PSLiteral) else str(base)
    fixed = missing_codes(differences(resolve1(spec.get("Encoding"))), to_unicode, base_name)
    if fixed:
        font.cid2unicode.update(fixed)
        log.info("font %s: %d codes repaired", base_name, len(fixed))
    return len(fixed)


def repair_fonts(pdf: Any) -> int:
    """Repair the fonts of every page of a ``pdfplumber.PDF`` before reading it."""
    rsrcmgr: PDFResourceManager = pdf.rsrcmgr
    done: set[int] = set()
    fixed = 0
    for page in pdf.pages:
        resources = resolve1(page.page_obj.resources) or {}
        for ref in (resolve1(resources.get("Font", {})) or {}).values():
            if not isinstance(ref, PDFObjRef) or ref.objid in done:
                continue  # only shared, cached font objects can be fixed
            done.add(ref.objid)
            spec = resolve1(ref)
            if not isinstance(spec, dict) or not isinstance(resolve1(spec.get("Encoding")), dict):
                continue  # no /Differences array, nothing to read glyph names from
            try:
                font = rsrcmgr.get_font(ref.objid, spec)
            except Exception:
                log.debug("cannot load font %s", spec.get("BaseFont"), exc_info=True)
                continue
            fixed += repair_font(font, spec)
    return fixed
