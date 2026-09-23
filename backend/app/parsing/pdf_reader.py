"""Чтение PDF: текстовый слой (PyMuPDF) с распознаванием сканированных страниц (OCR)."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

from .ocr import ocr_lines, prepare_image, tesseract_available
from .segment import BULLET_RE, LETTER_RE, NUM_RE, PAREN_NUM_RE, RawPara


@dataclass
class _Line:
    text: str
    page: int
    y0: float
    y1: float
    x0: float
    size: float
    bold: bool
    page_h: float


def _norm_hf(text: str) -> str:
    return re.sub(r"\d+", "#", text.strip().lower())


def _starts_item(text: str) -> bool:
    return bool(
        (NUM_RE.match(text) and re.match(r"^\s*\d{1,2}(\.\d{1,3})*\.", text))
        or LETTER_RE.match(text)
        or PAREN_NUM_RE.match(text)
        or BULLET_RE.match(text)
    )


def _page_lines(page: fitz.Page, page_no: int) -> list[_Line]:
    out: list[_Line] = []
    d = page.get_text("dict")
    h = page.rect.height
    for block in d.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            text = "".join(s["text"] for s in line["spans"]).strip()
            bold = all((s.get("flags", 0) & 16) or "bold" in s.get("font", "").lower() for s in spans)
            size = max(s.get("size", 0) for s in spans)
            x0, y0, _, y1 = line["bbox"]
            out.append(_Line(text, page_no, y0, y1, x0, size, bold, h))
    out.sort(key=lambda ln: (round(ln.y0, 1), ln.x0))
    return out


def _ocr_page(page: fitz.Page, page_no: int) -> list[_Line]:
    pix = page.get_pixmap(dpi=300)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    img = prepare_image(img)
    scale = page.rect.height / img.height
    lines = ocr_lines(img)
    return [
        _Line(ln.text, page_no, ln.y * scale, (ln.y + ln.h) * scale, ln.x * scale, ln.h * scale * 0.8, False,
              page.rect.height)
        for ln in lines
        if ln.conf > 20 or len(ln.text) > 3
    ]


def _assemble(lines: list[_Line]) -> list[RawPara]:
    if not lines:
        return []
    sizes = Counter(round(ln.size) for ln in lines)
    body_size = sizes.most_common(1)[0][0]
    paras: list[RawPara] = []
    cur: list[_Line] = []

    def flush() -> None:
        if not cur:
            return
        text = ""
        for ln in cur:
            t = ln.text
            if text.endswith("-") and t[:1].islower():
                text = text[:-1] + t
            elif text:
                text += " " + t
            else:
                text = t
        first = cur[0]
        heading = all(ln.bold for ln in cur) or first.size >= body_size + 1.5
        paras.append(RawPara(text=text, page=first.page, is_heading=heading and len(text) < 200,
                             bold=all(ln.bold for ln in cur)))
        cur.clear()

    for ln in lines:
        if cur:
            prev = cur[-1]
            gap = ln.y0 - prev.y1
            line_h = max(prev.y1 - prev.y0, 1)
            new_para = (
                ln.page != prev.page and _starts_item(ln.text)
                or _starts_item(ln.text)
                or (ln.page == prev.page and gap > line_h * 0.9)
                or (prev.text.rstrip().endswith((".", ";", ":")) and ln.text[:1].isupper())
                or prev.bold != ln.bold
                or abs(ln.size - prev.size) > 1.5
            )
            if new_para:
                flush()
        cur.append(ln)
    flush()
    return paras


def read_pdf(path: Path) -> tuple[list[RawPara], dict]:
    doc = fitz.open(str(path))
    all_lines: list[_Line] = []
    ocr_pages = 0
    warnings: list[str] = []
    for i, page in enumerate(doc, start=1):
        lines = _page_lines(page, i)
        chars = sum(len(ln.text) for ln in lines)
        if chars < 40:
            if tesseract_available():
                lines = _ocr_page(page, i)
                ocr_pages += 1
            elif page.get_images():
                warnings.append(f"Страница {i}: скан без текстового слоя, OCR недоступен")
        all_lines.extend(lines)

    # удаляем колонтитулы и номера страниц
    n_pages = len(doc)
    if n_pages >= 3:
        edge = [
            _norm_hf(ln.text)
            for ln in all_lines
            if ln.y0 < ln.page_h * 0.08 or ln.y1 > ln.page_h * 0.92
        ]
        repeated = {t for t, c in Counter(edge).items() if c >= max(2, n_pages // 2)}
    else:
        repeated = set()
    cleaned = [
        ln for ln in all_lines
        if not (
            (ln.y0 < ln.page_h * 0.08 or ln.y1 > ln.page_h * 0.92)
            and (_norm_hf(ln.text) in repeated or re.fullmatch(r"[-–\s]*\d{1,4}[-–\s]*|стр\.?\s*\d+.*", ln.text.strip(), re.I))
        )
    ]
    paras = _assemble(cleaned)
    meta = {
        "pages": n_pages,
        "ocr_pages": ocr_pages,
        "method": "pdf_ocr" if ocr_pages and ocr_pages == n_pages else ("pdf_mixed" if ocr_pages else "pdf_text"),
        "warnings": warnings,
    }
    doc.close()
    return paras, meta
