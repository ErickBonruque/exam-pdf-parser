"""Build ``enem_booklets.csv`` from the data dictionaries of the ENEM microdata.

The dictionary (an .xlsx inside each microdata ZIP) lists, for every area,
the code of each booklet (``CO_PROVA``) and its label, such as ``Azul`` or
``Verde - Ampliada (Reaplicação)``. The evaluation needs this to find the
official answers of the booklet that was parsed.

Usage: uv run --with openpyxl scripts/build_booklet_table.py DICT.xlsx [...] > out.csv
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import openpyxl

AREA_VARS = {"CO_PROVA_CN": "CN", "CO_PROVA_CH": "CH", "CO_PROVA_LC": "LC", "CO_PROVA_MT": "MT"}


def rows(path: Path) -> list[tuple[int, str, int, str]]:
    year = int(re.search(r"(20\d\d)", path.name).group(1))  # type: ignore[union-attr]
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        area = None
        for row in ws.iter_rows(values_only=True):
            cells = list(row[:4]) + [None] * (4 - len(row[:4]))
            name, _, code, label = cells
            if isinstance(name, str) and name.strip():
                area = AREA_VARS.get(name.strip())
            if area and code is not None and label:
                try:
                    out.append((year, area, int(code), str(label).strip()))
                except ValueError:
                    continue
    return out


def main(paths: list[str]) -> None:
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(["year", "area", "co_prova", "label"])
    for p in paths:
        for r in sorted(set(rows(Path(p)))):
            writer.writerow(r)


if __name__ == "__main__":
    main(sys.argv[1:])
