"""Write questions to JSON Lines or Parquet."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from exam_pdf_parser.models import Question

SCHEMA = pa.schema(
    [
        pa.field("exam_id", pa.string(), nullable=False),
        pa.field("number", pa.int16(), nullable=False),
        pa.field("language", pa.string()),
        pa.field("area", pa.string()),
        pa.field("stem", pa.string(), nullable=False),
        pa.field(
            "alternatives",
            pa.list_(pa.struct([pa.field("letter", pa.string()), pa.field("text", pa.string())])),
            nullable=False,
        ),
        pa.field("answer", pa.string()),
        pa.field("annulled", pa.bool_(), nullable=False),
        pa.field("pages", pa.list_(pa.int16()), nullable=False),
        pa.field("has_image", pa.bool_(), nullable=False),
        pa.field("warnings", pa.list_(pa.string()), nullable=False),
    ]
)


def to_jsonl(questions: Iterable[Question], path: Path) -> int:
    n = 0
    with path.open("w", encoding="utf-8") as fh:
        for q in questions:
            fh.write(json.dumps(q.model_dump(), ensure_ascii=False) + "\n")
            n += 1
    return n


def to_parquet(questions: Iterable[Question], path: Path) -> int:
    rows = [q.model_dump() for q in questions]
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), path)
    return len(rows)


def write(questions: Iterable[Question], path: Path) -> int:
    """Write by file extension: ``.jsonl`` or ``.parquet``."""
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        return to_jsonl(questions, path)
    if suffix == ".parquet":
        return to_parquet(questions, path)
    raise ValueError(f"unknown output format {suffix!r}; use .jsonl or .parquet")
