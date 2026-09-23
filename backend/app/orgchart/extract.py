"""Распознавание схемы оргструктуры с изображения или PDF.

Классический конвейер компьютерного зрения (работает без ИИ-модели):
  1. поиск прямоугольных блоков (OpenCV: контуры + аппроксимация многоугольником);
  2. текст блока — из текстового слоя PDF или OCR (Tesseract rus+kaz+eng);
  3. связи — компоненты связности «линий» после удаления блоков: в каждой группе
     блоков, соединённых одной линией, верхний блок — руководитель, остальные — подчинённые;
  4. если линии не найдены — геометрическая эвристика (ближайший блок уровнем выше).
При подключённой vision-модели можно использовать её (см. extract_with_vision).
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from ..parsing.ocr import ocr_text, prepare_image, tesseract_available


def _load_image(path: Path, is_pdf: bool) -> tuple[np.ndarray, list[tuple[float, float, float, float, str]], float]:
    """Возвращает (BGR-изображение, слова PDF в координатах изображения, масштаб)."""
    if is_pdf:
        import fitz

        doc = fitz.open(str(path))
        page = doc[0]
        zoom = 2.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR if pix.n == 3 else cv2.COLOR_RGBA2BGR)
        words = [(w[0] * zoom, w[1] * zoom, w[2] * zoom, w[3] * zoom, w[4]) for w in page.get_text("words")]
        doc.close()
        return img, words, zoom
    pil = Image.open(path)
    pil = pil.convert("RGB")
    img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    return img, [], 1.0


def _find_boxes(img: np.ndarray) -> list[tuple[int, int, int, int]]:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    # границы блоков (тёмные линии) и заливки (цветные прямоугольники)
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    fill = cv2.inRange(hsv, (0, 25, 60), (180, 255, 255))
    edges = cv2.Canny(gray, 50, 150)
    mask = cv2.bitwise_or(cv2.bitwise_or(ink, fill), edges)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    min_area, max_area = w * h * 0.0015, w * h * 0.35
    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        area = bw * bh
        if area < min_area or area > max_area or bw < 50 or bh < 22:
            continue
        if bw / max(bh, 1) > 14 or bh / max(bw, 1) > 4:
            continue
        rect_fill = cv2.contourArea(c) / area
        approx = cv2.approxPolyDP(c, 0.03 * cv2.arcLength(c, True), True)
        if rect_fill < 0.75 or not (4 <= len(approx) <= 8):
            continue
        boxes.append((x, y, bw, bh))
    # удаляем дубликаты (внешний/внутренний контур одной рамки) и вложенные элементы
    boxes.sort(key=lambda b: b[2] * b[3], reverse=True)
    kept: list[tuple[int, int, int, int]] = []
    for b in boxes:
        x, y, bw, bh = b
        dup = False
        for k in kept:
            kx, ky, kw, kh = k
            inside = x >= kx - 4 and y >= ky - 4 and x + bw <= kx + kw + 4 and y + bh <= ky + kh + 4
            if inside:
                dup = True
                break
        if not dup:
            kept.append(b)
    return kept


def _box_text(img: np.ndarray, box: tuple[int, int, int, int], words: list) -> str:
    x, y, bw, bh = box
    if words:
        inside = [wd for wd in words if wd[0] >= x - 2 and wd[2] <= x + bw + 2 and wd[1] >= y - 2 and wd[3] <= y + bh + 2]
        inside.sort(key=lambda wd: (round(wd[1] / 8), wd[0]))
        text = " ".join(wd[4] for wd in inside)
        if text.strip():
            return _clean(text)
    if not tesseract_available():
        return ""
    m = 4
    crop = img[y + m: y + bh - m, x + m: x + bw - m]
    if crop.size == 0:
        return ""
    pil = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
    pil = prepare_image(pil, min_width=900)
    # белые поля вокруг текста заметно повышают качество распознавания Tesseract
    bg = int(np.median(np.array(pil)))
    framed = Image.new("L", (pil.width + 60, pil.height + 60), bg)
    framed.paste(pil, (30, 30))
    return _clean(ocr_text(framed, psm=6))


def _clean(text: str) -> str:
    text = text.replace("\n", " ").replace("|", " ")
    text = re.sub(r"-\s+(?=[а-яё])", "", text)
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" -–—_.,;:")
    # сокращения в скобках пишутся заглавными: (дит) -> (ДИТ)
    text = re.sub(r"\(([а-яёa-z]{2,10})\)", lambda m: f"({m.group(1).upper()})", text)
    return text[:1].upper() + text[1:]


def _connect(img: np.ndarray, boxes: list[tuple[int, int, int, int]]) -> dict[int, int]:
    """Связи по линиям: {индекс_дочернего: индекс_родителя}."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    lines = ink.copy()
    for (x, y, bw, bh) in boxes:
        cv2.rectangle(lines, (x - 2, y - 2), (x + bw + 2, y + bh + 2), 0, thickness=-1)
    # оставляем только протяжённые горизонтальные/вертикальные штрихи
    horiz = cv2.morphologyEx(lines, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 1)))
    vert = cv2.morphologyEx(lines, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 15)))
    conn = cv2.bitwise_or(horiz, vert)
    conn = cv2.dilate(conn, np.ones((3, 3), np.uint8), iterations=2)
    n, labels = cv2.connectedComponents(conn)
    groups: dict[int, set[int]] = {}
    for i, (x, y, bw, bh) in enumerate(boxes):
        pad = 10
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(labels.shape[1], x + bw + pad), min(labels.shape[0], y + bh + pad)
        ring = labels[y0:y1, x0:x1].copy()
        ring[pad:-pad or None, pad:-pad or None] = 0
        for lab in np.unique(ring):
            if lab:
                groups.setdefault(int(lab), set()).add(i)
    parent: dict[int, int] = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        ordered = sorted(members, key=lambda i: boxes[i][1])
        top = ordered[0]
        top_bottom = boxes[top][1] + boxes[top][3]
        for i in ordered[1:]:
            if boxes[i][1] >= top_bottom - 5 and i not in parent:
                parent[i] = top
    return parent


def _geometric_parents(boxes: list[tuple[int, int, int, int]], known: dict[int, int]) -> dict[int, int]:
    """Для блоков без найденных связей — ближайший блок предыдущего уровня."""
    if not boxes:
        return known
    rows: list[list[int]] = []
    for i in sorted(range(len(boxes)), key=lambda i: boxes[i][1]):
        cy = boxes[i][1] + boxes[i][3] / 2
        if rows and abs((boxes[rows[-1][0]][1] + boxes[rows[-1][0]][3] / 2) - cy) < boxes[i][3] * 0.6:
            rows[-1].append(i)
        else:
            rows.append([i])
    level = {i: r for r, row in enumerate(rows) for i in row}
    result = dict(known)
    for i in range(len(boxes)):
        if i in result or level[i] == 0:
            continue
        cx = boxes[i][0] + boxes[i][2] / 2
        best, best_d = None, None
        for r in range(level[i] - 1, -1, -1):
            for j in rows[r]:
                jx0, jx1 = boxes[j][0], boxes[j][0] + boxes[j][2]
                d = 0 if jx0 <= cx <= jx1 else min(abs(cx - jx0), abs(cx - jx1))
                d += (level[i] - r - 1) * 1000
                if best_d is None or d < best_d:
                    best, best_d = j, d
            if best is not None:
                break
        if best is not None:
            result[i] = best
    return result


def extract_orgchart_from_file(path: Path, is_pdf: bool = False) -> dict[str, Any]:
    img, words, _ = _load_image(path, is_pdf)
    boxes = _find_boxes(img)
    warnings: list[str] = []
    if len(boxes) < 2:
        return {"units": [], "method": "cv", "warnings": ["Блоки схемы не найдены"], "image_size": img.shape[1::-1]}
    texts = [_box_text(img, b, words) for b in boxes]
    keep = [i for i, t in enumerate(texts) if len(t) >= 2]
    if not keep:
        return {"units": [], "method": "cv", "warnings": ["Не удалось распознать текст в блоках (нужен OCR)"],
                "image_size": img.shape[1::-1]}
    boxes = [boxes[i] for i in keep]
    texts = [texts[i] for i in keep]
    parents = _connect(img, boxes)
    linked = len(parents)
    parents = _geometric_parents(boxes, parents)
    if linked == 0:
        warnings.append("Линии связей не распознаны — подчинённость определена по расположению блоков")
    order = sorted(range(len(boxes)), key=lambda i: (boxes[i][1], boxes[i][0]))
    ids = {i: str(n + 1) for n, i in enumerate(order)}
    units = []
    for i in order:
        x, y, bw, bh = boxes[i]
        units.append({"id": ids[i], "name": texts[i], "parent_id": ids.get(parents[i]) if i in parents else None,
                      "bbox": [int(x), int(y), int(bw), int(bh)]})
    return {"units": units, "method": "pdf_text" if words else "ocr", "warnings": warnings,
            "image_size": [int(img.shape[1]), int(img.shape[0])], "links_detected": linked}


def extract_with_vision(llm, path: Path, is_pdf: bool) -> dict[str, Any]:
    """Распознавание схемы vision-моделью (qwen2.5-vl, llava, gpt-4o и т.п.)."""
    from ..analysis import prompts

    img, _, _ = _load_image(path, is_pdf)
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    if pil.width > 2000:
        pil = pil.resize((2000, int(pil.height * 2000 / pil.width)))
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    data = llm.vision_json(buf.getvalue(), prompts.ORGCHART_VISION)
    units = []
    raw = data.get("units", []) if isinstance(data, dict) else data
    for i, u in enumerate(raw or []):
        name = str(u.get("name", "")).strip()
        if not name:
            continue
        units.append({"id": str(u.get("id") or i + 1), "name": name,
                      "parent_id": str(u["parent_id"]) if u.get("parent_id") not in (None, "", "null") else None})
    ids = {u["id"] for u in units}
    for u in units:
        if u["parent_id"] not in ids:
            u["parent_id"] = None
    return {"units": units, "method": "vision", "warnings": [], "image_size": [pil.width, pil.height]}
