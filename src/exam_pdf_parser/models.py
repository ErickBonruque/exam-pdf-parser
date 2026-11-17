"""Output schema. Every question is validated before it is written."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Letter = Literal["A", "B", "C", "D", "E"]


class Alternative(BaseModel):
    model_config = ConfigDict(frozen=True)

    letter: Letter
    text: str


class Question(BaseModel):
    """One multiple-choice question as printed in the exam booklet."""

    model_config = ConfigDict(frozen=True)

    exam_id: str = Field(min_length=1, description="Booklet id, e.g. enem-2024-d1-cd1")
    number: int = Field(ge=1, le=999)
    language: str | None = Field(default=None, description="Foreign language option, e.g. en, es")
    area: str | None = Field(default=None, description="Subject area from the section headers")
    stem: str = Field(description="Text before the alternatives (support text + command)")
    alternatives: list[Alternative]
    answer: Letter | None = Field(default=None, description="Official answer; None if unknown")
    annulled: bool = False
    pages: list[int] = Field(min_length=1)
    has_image: bool = False
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_letters(self) -> Question:
        letters = [a.letter for a in self.alternatives]
        if letters != sorted(set(letters)):
            raise ValueError(f"alternatives out of order or repeated: {letters}")
        if self.answer is not None and letters and self.answer not in letters:
            raise ValueError(f"answer {self.answer} is not one of the alternatives {letters}")
        if self.annulled and self.answer is not None:
            raise ValueError("an annulled question has no answer")
        return self

    @property
    def key(self) -> tuple[int, str | None]:
        return (self.number, self.language)


class AnswerKeyEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    number: int = Field(ge=1, le=999)
    language: str | None = None
    answer: Letter | None
    annulled: bool = False

    @model_validator(mode="after")
    def _check(self) -> AnswerKeyEntry:
        if self.annulled == (self.answer is not None):
            raise ValueError("an entry has either an answer or is annulled")
        return self
