English | [Português](README.pt-BR.md)

# exam-pdf-parser

[![CI](https://github.com/ErickBonruque/exam-pdf-parser/actions/workflows/ci.yml/badge.svg)](https://github.com/ErickBonruque/exam-pdf-parser/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Extracts multiple-choice questions from exam PDFs (stem, alternatives A–E, subject area, official
answer) into Parquet or JSONL with a validated schema. Measured against official data: 3,700
questions of ENEM, the Brazilian national high-school exam, from 2020 to 2024.

## Result

40 ENEM booklets (5 years × 8 regular booklets), compared with the INEP microdata (`ITENS_PROVA`),
a source that does not come from the PDF:

| Measure | Result |
|---|---|
| Questions found (number + language) | 3,700 / 3,700 (100%) |
| Extra questions | 0 |
| Correct area (LC, CH, CN, MT) | 100% |
| All 5 alternatives located | 100% |
| Answer equal to the official answer | 3,676 / 3,676 (100%) |
| Annulled questions detected | 24 / 24 |
| Readable text (no lost glyph) | 95.6% |
| Same item text in the 4 booklet colors | 875 / 925 items (94.6%) |
| Time / peak memory | 93 s with 4 processes / 320 MB |

The last row measures text quality without a text answer key: each item is printed in 4 booklet
colors, at a different place on the page. A good extractor reads the same text in all 4.

With the Parquet output, one DuckDB query shows that no answer letter is favored:

```sql
SELECT substr(exam_id, 6, 4) AS year, count(*) AS questions,
       round(100 * avg((answer = 'A')::int), 1) AS "A", ...
FROM 'data/out/*.parquet' GROUP BY 1 ORDER BY 1;
```

| Year | Questions | A % | B % | C % | D % | E % |
|---|---|---|---|---|---|---|
| 2020 | 740 | 19.1 | 18.0 | 23.5 | 22.4 | 16.9 |
| 2021 | 740 | 18.5 | 25.0 | 19.6 | 20.1 | 16.8 |
| 2022 | 740 | 21.2 | 20.1 | 21.2 | 17.9 | 19.6 |
| 2023 | 740 | 25.0 | 19.0 | 20.7 | 19.0 | 16.3 |
| 2024 | 740 | 17.4 | 19.6 | 21.2 | 22.8 | 19.0 |

## Why

Exams and answer keys are published as two-column PDFs made for printing. To study topic
frequency, build a question bank or train a model, you need a table, and you need to know that the
extraction is correct.

## How to run

Needs Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run exam-pdf enem download --years 2024 --dest data/enem
uv run exam-pdf parse data/enem/2024_PV_impresso_D1_CD1.pdf \
    --answer-key data/enem/2024_GB_impresso_D1_CD1.pdf -o questions.parquet
```

To reproduce the table above, download the ENEM microdata from the
[INEP portal](https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos/microdados/enem)
(the ZIP is enough; the `ITENS_PROVA` file is read from inside it) and run:

```bash
uv run exam-pdf enem download --years 2020-2024 --dest data/enem
uv run exam-pdf enem evaluate --years 2020-2024 --pdf-dir data/enem \
    --microdata-dir path/to/microdata --out-dir data/out
```

## How it works

```
PDF ─► layout ─────────► segment ───────────► parse ─────────► export
       words, fonts       "QUESTÃO" headers     + answer key     Parquet / JSONL
       gutter, lines      sections (area, lang) pydantic check
       running footer     alternatives A–E
                                                 evaluate ◄── INEP microdata
```

- **`layout`** reads the words with position and font (`pdfplumber`), drops the watermark (1 pt
  text) and the barcode, finds the gutter between the columns and builds the lines in reading
  order. It finds the running footer by repetition (same height on most pages), not by its text.
- **`segment`** splits the questions at their headers and keeps the section context (area, English
  or Spanish option). It knows the letters A–E by the special font they are drawn in, so a stem that
  starts with the word "A" does not become an alternative. It puts alternatives set in a grid
  (A B C / D E) back in order.
- **`glyphs`**: in the 2021 PDFs the embedded font has no Unicode map for 1/3 to 3/4 of the
  characters, so the text comes out as `(cid:12)` or with wrong letters. This module reads the name
  of each glyph (`g68`) and turns the index into a character with the Arial glyph order. The order
  was checked on the text itself ("CARTÃO", "África", "conflito"). For fonts with an unknown order
  (Symbol, Cambria) it writes `�` and the question gets a warning, instead of a wrong letter.
- **`evaluate`** finds the booklet code (`CO_PROVA`) from the color printed on the answer key and the
  microdata dictionary, then compares question by question.

Decisions:
- `pdfplumber` (MIT), not PyMuPDF (AGPL), so that this project can be MIT.
- Each question goes through a `pydantic` model before it is written (letters in order, answer
  among the alternatives, no answer when annulled). What cannot be extracted goes to `warnings`; the
  run does not stop.
- No PDF, answer key or output is stored in the repository. The tests draw synthetic PDFs with
  `reportlab`.

## Output

One row per question:

| Column | Type | Example |
|---|---|---|
| `exam_id` | string | `enem-2024-d2-cd5` |
| `number` | int16 | `136` |
| `language` | string | `en`, `es` or null |
| `area` | string | `MT` |
| `stem` | string | support text + command |
| `alternatives` | list<struct<letter, text>> | `[{A, "2 400,00."}, …]` |
| `answer` | string | `C` |
| `annulled` | bool | `false` |
| `pages` | list<int16> | `[16]` |
| `has_image` | bool | raster image inside the question |
| `warnings` | list<string> | `["alternative A is empty (image?)"]` |

## Limitations

- Text inside figures and formulas is not reliable: chart labels mix, `√` and fractions lose their
  structure. 2.2% of the questions have alternatives that are only an image (empty text, with a
  warning).
- `has_image` sees raster images only; vector figures do not count.
- Only the ENEM profile is ready and measured. Exams from other boards (FGV, Cebraspe) need their own
  profile and PDFs downloaded by hand: the FGV terms of use do not allow automated access, and this
  project downloads nothing from those sites.
- 164 questions (4.4%) still have a lost glyph: 108 from 2021, the others mostly formula symbols in
  Symbol or Cambria fonts.

## License

MIT. INEP publishes the PDFs and the microdata; this repository does not redistribute them.
