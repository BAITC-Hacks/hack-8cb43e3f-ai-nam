"""Общие помощники для выгрузок Excel."""
from __future__ import annotations

from openpyxl import Workbook


def literal_cells(wb: Workbook) -> Workbook:
    """Записывает все значения как текст: openpyxl превращает строку, начинающуюся с «=», в формулу.

    Тексты в выгрузках берутся из загруженных документов, поэтому формула из документа не должна
    выполняться при открытии файла. Собственных формул выгрузки не содержат.
    """
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.data_type == "f":
                    c.data_type = "s"
    return wb
