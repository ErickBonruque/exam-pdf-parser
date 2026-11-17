"""From a synthetic PDF to validated rows on disk."""

from __future__ import annotations

import json

import pyarrow.parquet as pq
import pytest

from conftest import TEST_PROFILE, Block
from exam_pdf_parser import cli, export
from exam_pdf_parser.models import AnswerKeyEntry
from exam_pdf_parser.parse import parse_exam


def exam_pages() -> list:
    left = (
        Block()
        .header("LANGUAGES")
        .header("Questions 1 to 1 (option: English)")
        .header("QUESTION 1")
        .text("A sentence that starts with the letter A.")
        .text("Choose the best option.")
        .alt("A", "first")
        .alt("B", "second")
        .alt("C", "third")
        .alt("D", "fourth")
        .alt("E", "fifth")
    )
    right = (
        Block()
        .header("MATHEMATICS")
        .header("QUESTION 2")
        .text("How much is 2 + 2?")
        .alt("A", "1")
        .alt("B", "2")
        .alt("C", "3")
        .alt("D", "4")
        .alt("E", "5")
        .header("END OF EXAM")
        .text("Back cover text that is not part of question 2.")
    )
    return [(left, right)]


KEY = {
    (1, "en"): AnswerKeyEntry(number=1, language="en", answer="E"),
    (2, None): AnswerKeyEntry(number=2, answer=None, annulled=True),
}


def test_parse_synthetic_exam(make_pdf) -> None:
    pdf = make_pdf(exam_pages())
    q1, q2 = parse_exam(pdf, TEST_PROFILE, "synthetic", KEY)

    assert (q1.number, q1.language, q1.area) == (1, "en", "LC")
    assert q1.stem == "A sentence that starts with the letter A. Choose the best option."
    assert [a.text for a in q1.alternatives] == ["first", "second", "third", "fourth", "fifth"]
    assert q1.answer == "E"
    assert q1.warnings == []

    assert (q2.number, q2.language, q2.area) == (2, None, "MT")
    assert q2.alternatives[-1].text == "5"  # the back cover text was not glued to E
    assert q2.annulled and q2.answer is None
    assert q2.pages == [1]


def test_question_missing_from_key_gets_a_warning(make_pdf) -> None:
    pdf = make_pdf(exam_pages())
    _, q2 = parse_exam(pdf, TEST_PROFILE, "synthetic", {})
    assert "not in answer key" in q2.warnings


@pytest.mark.parametrize("suffix", [".parquet", ".jsonl"])
def test_export_round_trip(make_pdf, tmp_path, suffix: str) -> None:
    questions = parse_exam(make_pdf(exam_pages()), TEST_PROFILE, "synthetic", KEY)
    out = tmp_path / f"out{suffix}"
    assert export.write(questions, out) == 2
    if suffix == ".parquet":
        rows = pq.read_table(out).to_pylist()
        assert pq.read_schema(out).equals(export.SCHEMA, check_metadata=False)
    else:
        rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["alternatives"][4] == {"letter": "E", "text": "fifth"}
    assert rows[1]["annulled"] is True


def test_export_rejects_unknown_format(tmp_path) -> None:
    with pytest.raises(ValueError, match="unknown output format"):
        export.write([], tmp_path / "out.csv")


def test_cli_parse(make_pdf, tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setitem(cli.PROFILES, "test", TEST_PROFILE)
    out = tmp_path / "q.jsonl"
    code = cli.main(["parse", str(make_pdf(exam_pages())), "--profile", "test", "-o", str(out)])
    assert code == 0
    assert "2 questions" in capsys.readouterr().out
    assert len(out.read_text(encoding="utf-8").splitlines()) == 2


@pytest.mark.parametrize(
    ("text", "years"),
    [("2024", [2024]), ("2020-2022", [2020, 2021, 2022]), ("2020,2023", [2020, 2023])],
)
def test_parse_years(text: str, years: list[int]) -> None:
    assert cli.parse_years(text) == years
