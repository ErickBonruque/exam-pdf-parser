"""Official item data from the ENEM microdata (``ITENS_PROVA_<year>.csv``).

For every booklet code (``CO_PROVA``) and position, INEP publishes the
correct answer. This is an independent source to check the parser against.

Two different things are easy to mix up:

* ``TX_GABARITO = "X"``: the question was annulled. The printed answer key
  shows it as annulled too.
* ``IN_ITEM_ABAN = 1`` with a letter in ``TX_GABARITO``: the item was left
  out of the IRT (TRI) score for a statistical reason, for example "the
  estimation did not converge". The question still has an official answer.
"""

from __future__ import annotations

import csv
import io
import unicodedata
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import IO

SOURCE_ENCODING = "cp1252"  # INEP says "latin-1"; the files use Windows-1252
LANGUAGES = {"0": "en", "1": "es"}


@dataclass(frozen=True, slots=True)
class Item:
    co_prova: int
    position: int
    area: str
    answer: str | None  # None when annulled
    annulled: bool  # TX_GABARITO is "X"
    excluded_from_score: bool  # IN_ITEM_ABAN is 1 (annulled or statistical reason)
    language: str | None
    item_id: int = 0  # CO_ITEM: the same item in every booklet color


def _rows(fh: IO[bytes]) -> Iterator[Item]:
    text = io.TextIOWrapper(fh, encoding=SOURCE_ENCODING, newline="")
    for row in csv.DictReader(text, delimiter=";"):
        answer = row["TX_GABARITO"].strip().upper()
        if answer not in {"A", "B", "C", "D", "E", "X"}:
            raise ValueError(f"unexpected TX_GABARITO {answer!r} in row {row}")
        yield Item(
            co_prova=int(row["CO_PROVA"]),
            position=int(row["CO_POSICAO"]),
            area=row["SG_AREA"].strip(),
            answer=None if answer == "X" else answer,
            annulled=answer == "X",
            excluded_from_score=row["IN_ITEM_ABAN"].strip() == "1",
            language=LANGUAGES.get(row.get("TP_LINGUA", "").strip()),
            item_id=int(row["CO_ITEM"]),
        )


def read_items(path: Path) -> list[Item]:
    """Read the item file from a CSV or straight from the microdata ZIP."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            members = [
                n
                for n in zf.namelist()
                if PurePosixPath(n).name.upper().startswith("ITENS_PROVA_")
                and n.lower().endswith(".csv")
            ]
            if len(members) != 1:
                raise ValueError(f"{path.name}: expected one ITENS_PROVA csv, found {members}")
            with zf.open(members[0]) as fh:
                return list(_rows(fh))
    with path.open("rb") as fh:
        return list(_rows(fh))


def find_items_file(root: Path, year: int) -> Path:
    """Find ``ITENS_PROVA_<year>.csv`` or ``microdados_enem_<year>.zip`` under ``root``."""
    for pattern in (f"ITENS_PROVA_{year}.csv", f"microdados_enem_{year}.zip"):
        found = sorted(root.rglob(pattern))
        if found:
            return found[0]
    raise FileNotFoundError(f"no ITENS_PROVA_{year}.csv or microdados_enem_{year}.zip under {root}")


def normalize_color(name: str) -> str:
    """``Amarelo`` and ``Amarela`` name the same booklet; compare without gender or accents."""
    s = unicodedata.normalize("NFKD", name.strip().lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s[:-1] if s.endswith(("a", "o")) else s


def booklet_codes() -> dict[tuple[int, str, str], int]:
    """Map ``(year, area, color)`` to ``CO_PROVA`` for the regular printed booklets."""
    table = resources.files("exam_pdf_parser").joinpath("data/enem_booklets.csv")
    codes: dict[tuple[int, str, str], int] = {}
    with table.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            label = row["label"]
            if any(c in label for c in "-()"):
                continue  # adapted, digital or second application
            codes[(int(row["year"]), row["area"], normalize_color(label))] = int(row["co_prova"])
    return codes
