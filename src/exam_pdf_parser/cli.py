"""Command line: ``exam-pdf parse``, ``exam-pdf enem download`` and ``exam-pdf enem evaluate``."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

from exam_pdf_parser import enem, export
from exam_pdf_parser.evaluate import (
    BookletScore,
    TextKey,
    evaluate_booklet,
    group_by_code,
    item_texts,
    text_consistency,
)
from exam_pdf_parser.microdata import Item, booklet_codes, find_items_file, read_items
from exam_pdf_parser.parse import parse_exam
from exam_pdf_parser.segment import ExamProfile

PROFILES: dict[str, ExamProfile] = {"enem": enem.PROFILE}


def parse_years(text: str) -> list[int]:
    """``2024`` -> [2024]; ``2020-2022`` -> [2020, 2021, 2022]; ``2020,2023`` -> [2020, 2023]."""
    years: list[int] = []
    for part in text.split(","):
        lo, _, hi = part.strip().partition("-")
        years.extend(range(int(lo), int(hi or lo) + 1))
    return years


def cmd_parse(args: argparse.Namespace) -> int:
    key = enem.parse_answer_key(args.answer_key).lookup() if args.answer_key else None
    questions = parse_exam(args.pdf, PROFILES[args.profile], args.exam_id or args.pdf.stem, key)
    n = export.write(questions, args.output)
    warned = sum(1 for q in questions if q.warnings)
    print(f"{n} questions -> {args.output} ({warned} with warnings)")
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    from exam_pdf_parser.download import fetch_booklets

    booklets = [b for y in parse_years(args.years) for b in enem.regular_booklets(y)]
    paths = fetch_booklets(booklets, args.dest)
    print(f"{len(paths)} files in {args.dest}")
    return 0


def _pct(num: int, den: int) -> str:
    return f"{100 * num / den:.2f}%" if den else "-"


def _evaluate_one(
    booklet: enem.Booklet,
    args: argparse.Namespace,
    items: dict[int, list[Item]],
    codes: dict[tuple[int, str, str], int],
) -> tuple[BookletScore, list[tuple[TextKey, str]]]:
    score, questions, expected = evaluate_booklet(booklet, args.pdf_dir, items, codes)
    if args.out_dir:
        export.write(questions, args.out_dir / f"{booklet.exam_id}.parquet")
    return score, item_texts(booklet, questions, expected)


def cmd_evaluate(args: argparse.Namespace) -> int:
    codes = booklet_codes()
    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    scores: list[BookletScore] = []
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futures = []
        for year in parse_years(args.years):
            items = group_by_code(read_items(find_items_file(args.microdata_dir, year)))
            futures += [
                pool.submit(_evaluate_one, b, args, items, codes)
                for b in enem.regular_booklets(year)
            ]
        texts: list[tuple[TextKey, str]] = []
        for future in futures:
            score, booklet_texts = future.result()
            scores.append(score)
            texts += booklet_texts
            print(
                f"{score.exam_id:<22} {score.color or '?':<8} found {score.found}/{score.expected}"
                f"  answers {score.answers_equal}/{score.answers_compared}"
                f"  problems {len(score.problems)}",
                file=sys.stderr,
            )
    elapsed = time.perf_counter() - started
    print(summary(scores, elapsed, text_consistency(texts)))
    if args.report:
        args.report.write_text(
            json.dumps([asdict(s) for s in scores], ensure_ascii=False, indent=1), encoding="utf-8"
        )
    return 0 if all(not s.problems for s in scores) else 1


def summary(scores: list[BookletScore], elapsed: float, consistency: tuple[int, int]) -> str:
    def total(name: str) -> int:
        return sum(getattr(s, name) for s in scores)

    found = total("found")
    rows = [
        ("booklets", f"{len(scores)} in {elapsed:.0f} s"),
        ("questions found", f"{found}/{total('expected')} ({_pct(found, total('expected'))})"),
        ("extra questions", str(total("extra"))),
        ("area correct", _pct(total("area_ok"), found)),
        ("5 alternatives located", _pct(total("alternatives_found"), found)),
        ("5 alternatives with text", _pct(total("alternatives_with_text"), found)),
        ("readable text", _pct(total("readable_text"), found)),
        (
            "same text in all colors",
            f"{consistency[0]}/{consistency[1]} items ({_pct(*consistency)})",
        ),
        (
            "answer = official",
            f"{total('answers_equal')}/{total('answers_compared')}"
            f" ({_pct(total('answers_equal'), total('answers_compared'))})",
        ),
        ("annulled detected", f"{total('annulled_equal')}/{total('annulled_expected')}"),
    ]
    return "\n".join(f"{name + ':':<26} {value}" for name, value in rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="exam-pdf", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("parse", help="extract the questions of one PDF")
    p.add_argument("pdf", type=Path)
    p.add_argument("-o", "--output", type=Path, required=True, help=".jsonl or .parquet")
    p.add_argument("--profile", choices=sorted(PROFILES), default="enem")
    p.add_argument("--answer-key", type=Path, help="answer-key PDF (ENEM format)")
    p.add_argument("--exam-id", help="id written in every row (default: file name)")
    p.set_defaults(func=cmd_parse)

    e = sub.add_parser("enem", help="ENEM helpers").add_subparsers(
        dest="enem_command", required=True
    )
    d = e.add_parser("download", help="download booklets and answer keys from INEP")
    d.add_argument("--years", required=True, help="e.g. 2024 or 2020-2024")
    d.add_argument("--dest", type=Path, default=Path("data/enem"))
    d.set_defaults(func=cmd_download)

    v = e.add_parser("evaluate", help="compare parsed booklets with the official microdata")
    v.add_argument("--years", required=True)
    v.add_argument("--pdf-dir", type=Path, default=Path("data/enem"))
    v.add_argument(
        "--microdata-dir",
        type=Path,
        required=True,
        help="folder with ITENS_PROVA_<year>.csv or microdados_enem_<year>.zip",
    )
    v.add_argument("--out-dir", type=Path, help="also write one Parquet file per booklet")
    v.add_argument("--report", type=Path, help="write per-booklet scores as JSON")
    v.add_argument("--jobs", type=int, default=None, help="parallel processes (default: CPUs)")
    v.set_defaults(func=cmd_evaluate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING, format="%(message)s"
    )
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
