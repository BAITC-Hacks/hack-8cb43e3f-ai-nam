"""Чтение DOCX: абзацы и таблицы в порядке следования + восстановление автонумерации Word.

python-docx не возвращает номера автосписков («5.3.1.», «а)»), поэтому
нумерация восстанавливается по numbering.xml: для каждого numId/ilvl
ведутся счётчики, а шаблон lvlText («%1.%2.») форматируется по numFmt.
"""
from __future__ import annotations

from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from .segment import RawPara
from .tables import _detect_header

RU_LOWER = "абвгдежзиклмнопрстуфхцчшщэюя"


def _roman(n: int) -> str:
    vals = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
            (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
    out = ""
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out


def _fmt(n: int, fmt: str) -> str:
    if fmt in ("decimal", "decimalZero", ""):
        return str(n)
    if fmt == "lowerLetter":
        return chr(ord("a") + (n - 1) % 26)
    if fmt == "upperLetter":
        return chr(ord("A") + (n - 1) % 26)
    if fmt == "lowerRoman":
        return _roman(n)
    if fmt == "upperRoman":
        return _roman(n).upper()
    if fmt in ("russianLower",):
        return RU_LOWER[(n - 1) % len(RU_LOWER)]
    if fmt in ("russianUpper",):
        return RU_LOWER[(n - 1) % len(RU_LOWER)].upper()
    if fmt in ("bullet", "none"):
        return ""
    return str(n)


class _Numbering:
    def __init__(self, document: docx.document.Document) -> None:
        self.levels: dict[str, dict[int, dict]] = {}  # abstractId -> ilvl -> {start, fmt, text}
        self.num_to_abs: dict[str, str] = {}
        self.overrides: dict[str, dict[int, int]] = {}
        self.counters: dict[str, dict[int, int]] = {}
        try:
            part = document.part.numbering_part
        except (KeyError, NotImplementedError, AttributeError):
            return
        root = part.element
        for absn in root.findall(qn("w:abstractNum")):
            aid = absn.get(qn("w:abstractNumId"))
            lv: dict[int, dict] = {}
            for lvl in absn.findall(qn("w:lvl")):
                ilvl = int(lvl.get(qn("w:ilvl")))
                start_el = lvl.find(qn("w:start"))
                fmt_el = lvl.find(qn("w:numFmt"))
                text_el = lvl.find(qn("w:lvlText"))
                is_lgl = lvl.find(qn("w:isLgl")) is not None
                lv[ilvl] = {
                    "start": int(start_el.get(qn("w:val"))) if start_el is not None else 1,
                    "fmt": fmt_el.get(qn("w:val")) if fmt_el is not None else "decimal",
                    "text": text_el.get(qn("w:val")) if text_el is not None else "",
                    "lgl": is_lgl,
                }
            self.levels[aid] = lv
        for num in root.findall(qn("w:num")):
            nid = num.get(qn("w:numId"))
            abs_el = num.find(qn("w:abstractNumId"))
            if abs_el is None:
                continue
            self.num_to_abs[nid] = abs_el.get(qn("w:val"))
            for ov in num.findall(qn("w:lvlOverride")):
                so = ov.find(qn("w:startOverride"))
                if so is not None:
                    self.overrides.setdefault(nid, {})[int(ov.get(qn("w:ilvl")))] = int(so.get(qn("w:val")))

    def label(self, num_id: str, ilvl: int) -> str:
        aid = self.num_to_abs.get(num_id)
        if aid is None or aid not in self.levels:
            return ""
        levels = self.levels[aid]
        if ilvl not in levels:
            return ""
        # счётчики общие для abstractNum (как ведёт себя Word для продолжающихся списков)
        counters = self.counters.setdefault(aid, {})
        start = self.overrides.get(num_id, {}).get(ilvl, levels[ilvl]["start"])
        counters[ilvl] = counters.get(ilvl, start - 1) + 1
        for deeper in [k for k in counters if k > ilvl]:
            del counters[deeper]
        lvl = levels[ilvl]
        if lvl["fmt"] in ("bullet",):
            return "•"
        text = lvl["text"]
        for i in range(ilvl + 1):
            li = levels.get(i, {"fmt": "decimal", "start": 1})
            val = counters.get(i, li.get("start", 1))
            fmt = "decimal" if lvl.get("lgl") else li["fmt"]
            text = text.replace(f"%{i + 1}", _fmt(val, fmt))
        return text.strip()


def _num_props(p: Paragraph) -> tuple[str, int] | None:
    ppr = p._p.pPr
    num_pr = ppr.numPr if ppr is not None else None
    if num_pr is None:
        # нумерация может задаваться стилем
        style = p.style
        while style is not None:
            s_ppr = style.element.pPr
            if s_ppr is not None and s_ppr.numPr is not None:
                num_pr = s_ppr.numPr
                break
            style = style.base_style
    if num_pr is None or num_pr.numId is None:
        return None
    num_id = str(num_pr.numId.val)
    if num_id == "0":
        return None
    ilvl = int(num_pr.ilvl.val) if num_pr.ilvl is not None else 0
    return num_id, ilvl


def _heading_level(p: Paragraph) -> int | None:
    name = (p.style.name or "").lower() if p.style is not None else ""
    for key in ("heading ", "заголовок "):
        if name.startswith(key):
            try:
                return int(name.split()[-1])
            except ValueError:
                return 1
    if name in ("title", "название"):
        return 0
    ppr = p._p.pPr
    if ppr is not None:
        ol = ppr.find(qn("w:outlineLvl"))
        if ol is not None:
            return int(ol.get(qn("w:val"))) + 1
    return None


def _is_bold(p: Paragraph) -> bool:
    runs = [r for r in p.runs if r.text.strip()]
    return bool(runs) and all(r.bold for r in runs)


def read_docx(path: Path) -> tuple[list[RawPara], dict]:
    document = docx.Document(str(path))
    numbering = _Numbering(document)
    paras: list[RawPara] = []
    data_tables: list[tuple[str, list[list[str]]]] = []
    tables = 0
    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            p = Paragraph(child, document)
            text = p.text
            if not text.strip():
                continue
            label = ""
            np_ = _num_props(p)
            if np_:
                label = numbering.label(*np_)
            hl = _heading_level(p)
            style = p.style.name if p.style is not None else ""
            paras.append(
                RawPara(
                    text=text,
                    style=style,
                    label=label if label != "•" else "",
                    is_heading=hl is not None and hl <= 3 and len(text) < 300,
                    heading_level=hl,
                    bold=_is_bold(p),
                )
                if label != "•"
                else RawPara(text="• " + text, style=style)
            )
        elif child.tag == qn("w:tbl"):
            tables += 1
            table = Table(child, document)
            rows: list[list[str]] = []
            for row in table.rows:
                cells: list[str] = []
                prev_tc = None
                for c in row.cells:
                    if c._tc is prev_tc:  # объединённые ячейки python-docx повторяет
                        continue
                    prev_tc = c._tc
                    cells.append(c.text.strip().replace("\n", " "))
                rows.append(cells)
            if _detect_header(rows):
                # таблица-реестр (функции / штатная структура) — разбирается как записи
                data_tables.append((f"Таблица {tables}", rows))
                continue
            for r_idx, cells in enumerate(rows, start=1):
                cells = [c for c in cells if c]
                if cells:
                    paras.append(RawPara(text=" | ".join(cells), style="table",
                                         source=f"Таблица {tables}, строка {r_idx}"))
    meta = {"tables": tables, "sections": len(document.sections), "data_tables": data_tables}
    return paras, meta
