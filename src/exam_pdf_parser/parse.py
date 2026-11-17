"""High-level API: one PDF in, validated questions out."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from exam_pdf_parser.layout import read_pdf
from exam_pdf_parser.models import Alternative, AnswerKeyEntry, Question
from exam_pdf_parser.segment import ExamProfile, has_image, segment, split_parts

# pdfminer writes "(cid:N)" for a glyph it cannot map to a character;
# glyphs.repair_fonts writes U+FFFD for glyphs it cannot recover.
UNMAPPED_GLYPHS = ("(cid:", "\ufffd")


def parse_exam(
    pdf_path: Path,
    profile: ExamProfile,
    exam_id: str,
    answer_key: Mapping[tuple[int, str | None], AnswerKeyEntry] | None = None,
) -> list[Question]:
    """Extract every question of ``pdf_path``.

    ``answer_key`` maps ``(number, language)`` to the official answer. A
    question without a language-specific entry falls back to ``(number, None)``.
    """
    raw_questions, images = segment(read_pdf(pdf_path, profile.layout), profile)
    questions: list[Question] = []
    for raw in raw_questions:
        parts = split_parts(raw, profile)
        language = raw.context.get("language")
        entry = None
        if answer_key is not None:
            entry = answer_key.get((raw.number, language)) or answer_key.get((raw.number, None))
        warnings = list(parts.warnings)
        texts = [parts.stem, *parts.alternatives.values()]
        if any(g in t for t in texts for g in UNMAPPED_GLYPHS):
            warnings.append("unmapped glyphs: the PDF font has no Unicode map")
        if answer_key is not None and entry is None:
            warnings.append("not in answer key")
        answer = entry.answer if entry else None
        if answer is not None and parts.alternatives and answer not in parts.alternatives:
            warnings.append(f"answer {answer} has no matching alternative")
            answer = None
        questions.append(
            Question(
                exam_id=exam_id,
                number=raw.number,
                language=language,
                area=raw.context.get("area"),
                stem=parts.stem,
                alternatives=[Alternative(letter=k, text=v) for k, v in parts.alternatives.items()],  # type: ignore[arg-type]
                answer=answer,
                annulled=bool(entry and entry.annulled),
                pages=sorted({raw.header.page, *(ln.page for ln in raw.lines)}),
                has_image=has_image(raw, images),
                warnings=warnings,
            )
        )
    return questions
