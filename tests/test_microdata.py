from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from exam_pdf_parser.microdata import (
    booklet_codes,
    find_items_file,
    normalize_color,
    read_items,
)

HEADER = (
    "CO_POSICAO;SG_AREA;CO_ITEM;TX_GABARITO;CO_HABILIDADE;IN_ITEM_ABAN;"
    "TX_MOTIVO_ABAN;TX_COR;CO_PROVA;TP_LINGUA\n"
)
ROWS = [
    "1;LC;10;C;1;0;;AZUL;100;0",
    "1;LC;11;A;1;0;;AZUL;100;1",
    "6;LC;12;B;1;1;Não convergiu;AZUL;100;",  # left out of the score, answer still valid
    "7;LC;13;X;1;1;Anulado;AZUL;100;",  # annulled
]


@pytest.fixture
def items_csv(tmp_path: Path) -> Path:
    path = tmp_path / "ITENS_PROVA_2099.csv"
    path.write_bytes((HEADER + "\n".join(ROWS) + "\n").encode("cp1252"))
    return path


def test_read_items_languages_and_annulled(items_csv: Path) -> None:
    items = {(i.position, i.language): i for i in read_items(items_csv)}
    assert items[(1, "en")].answer == "C"
    assert items[(1, "es")].answer == "A"
    excluded = items[(6, None)]
    assert excluded.answer == "B"
    assert excluded.excluded_from_score and not excluded.annulled
    annulled = items[(7, None)]
    assert annulled.annulled and annulled.answer is None


def test_read_items_from_zip(tmp_path: Path, items_csv: Path) -> None:
    archive = tmp_path / "microdados_enem_2099.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(items_csv, "DADOS/ITENS_PROVA_2099.csv")
        zf.writestr("DADOS/MICRODADOS_ENEM_2099.csv", "big file")
    assert len(read_items(archive)) == len(ROWS)


def test_unexpected_answer_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "ITENS_PROVA_2099.csv"
    path.write_text(HEADER + "1;LC;10;Z;1;0;;AZUL;100;\n", encoding="cp1252")
    with pytest.raises(ValueError, match="TX_GABARITO"):
        read_items(path)


def test_find_items_file_prefers_csv(tmp_path: Path, items_csv: Path) -> None:
    (tmp_path / "microdados_enem_2099.zip").write_bytes(b"")
    assert find_items_file(tmp_path, 2099) == items_csv
    with pytest.raises(FileNotFoundError):
        find_items_file(tmp_path, 1990)


@pytest.mark.parametrize(
    ("a", "b"), [("Amarelo", "Amarela"), ("Branco", "BRANCA"), ("Azul", "azul")]
)
def test_normalize_color(a: str, b: str) -> None:
    assert normalize_color(a) == normalize_color(b)


def test_booklet_codes_keep_only_regular_printed_booklets() -> None:
    codes = booklet_codes()
    assert codes[(2024, "LC", normalize_color("Azul"))] == 1395
    assert all(year >= 2020 for year, _, _ in codes)
    # 2024 has four regular colors per area; adapted and second-application booklets are out.
    assert len([k for k in codes if k[0] == 2024 and k[1] == "MT"]) == 4
