from __future__ import annotations

import pytest

from exam_pdf_parser import enem

# Same shape as the text of a real answer-key PDF (values made up).
DAY1_KEY = """\
1º DIA - CADERNO 1
Azul
Gabarito 2099
LINGUAGENS, CÓDIGOS CIÊNCIAS HUMANAS
QUESTÃO QUESTÃO GABARITO
INGLÊS ESPANHOL
1 C A 46 B
2 A D 47 Anulada
5 E B 50 C
6 B 51 D
"""

DAY2_KEY = """\
Amarelo
Gabarito 2099
2º DIA - CADERNO 5
133 E 178 anulada
134 D 179 ANULADO
"""


def test_language_rows_give_english_then_spanish() -> None:
    key = enem.parse_answer_key_text(DAY1_KEY)
    found = {(e.number, e.language): e.answer for e in key.entries}
    assert found[(1, "en")] == "C"
    assert found[(1, "es")] == "A"
    assert found[(46, None)] == "B"
    assert found[(6, None)] == "B"
    assert key.color == "Azul"


def test_annulled_spellings() -> None:
    day1 = enem.parse_answer_key_text(DAY1_KEY).lookup()
    day2 = enem.parse_answer_key_text(DAY2_KEY).lookup()
    for entry in (day1[(47, None)], day2[(178, None)], day2[(179, None)]):
        assert entry.annulled
        assert entry.answer is None
    assert enem.parse_answer_key_text(DAY2_KEY).color == "Amarelo"


def test_color_word_inside_a_sentence_is_not_the_color() -> None:
    key = enem.parse_answer_key_text("Caderno Azul claro\n1 A 46 B\n")
    assert key.color is None


def test_repeated_question_is_an_error() -> None:
    with pytest.raises(ValueError, match="repeated"):
        enem.parse_answer_key_text("1 A 46 B\n1 C 47 D\n")


def test_booklet_names_and_urls() -> None:
    b = enem.Booklet(2024, 2, 5)
    assert b.exam_id == "enem-2024-d2-cd5"
    assert b.file_name("GB") == "2024_GB_impresso_D2_CD5.pdf"
    assert b.url("PV").endswith("/enem/provas_e_gabaritos/2024_PV_impresso_D2_CD5.pdf")


@pytest.mark.parametrize(("day", "number", "kind"), [(3, 1, "PV"), (1, 0, "PV"), (1, 1, "XX")])
def test_booklet_rejects_bad_values(day: int, number: int, kind: str) -> None:
    with pytest.raises(ValueError):
        enem.Booklet(2024, day, number).file_name(kind)


def test_regular_booklets_cover_two_days() -> None:
    booklets = enem.regular_booklets(2024)
    assert len(booklets) == 8
    assert {b.day for b in booklets} == {1, 2}


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("Questões de 01 a 05 (opção inglês)", "en"),
        ("Questões de 01 a 05 (opção: espanhol)", "es"),  # 2022 adds a colon
    ],
)
def test_language_section_headers(text: str, language: str) -> None:
    rule = next(r for r in enem.PROFILE.section_rules if r.pattern.search(text))
    assert rule.sets == {"language": language}


@pytest.mark.parametrize("text", ["QUESTÃO 01", "Questão 3", "QUESTAO 136"])
def test_question_header_variants(text: str) -> None:
    assert enem.PROFILE.question_header.match(text)
