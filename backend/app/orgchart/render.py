"""Отрисовка схемы оргструктуры в PNG (для документов, отчётов и демонстрационных примеров)."""
from __future__ import annotations

import io
import shutil
import subprocess
from functools import lru_cache
from typing import Any

from PIL import Image, ImageDraw, ImageFont

STATUS_COLORS = {
    "created": ("#E8F8EF", "#1E8449"),
    "merged": ("#E8F8EF", "#1E8449"),
    "abolished": ("#FDEDEC", "#C0392B"),
    "reorganized": ("#FEF5E7", "#CA6F1E"),
    "split": ("#FEF5E7", "#CA6F1E"),
    "renamed": ("#EBF5FB", "#2874A6"),
    "preserved": ("#FFFFFF", "#34495E"),
    None: ("#FFFFFF", "#34495E"),
}

BOX_W, BOX_H, H_GAP, V_GAP, PAD = 240, 84, 36, 70, 40


@lru_cache
def _font_path(bold: bool = False) -> str | None:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    for c in candidates:
        try:
            ImageFont.truetype(c, 12)
            return c
        except OSError:
            continue
    if shutil.which("fc-match"):
        try:
            out = subprocess.run(["fc-match", "-f", "%{file}", "DejaVu Sans" + (":bold" if bold else "")],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
            if out:
                return out
        except (subprocess.SubprocessError, OSError):
            pass
    return None


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    path = _font_path(bold)
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _layout(units: list[dict[str, Any]]) -> tuple[dict[str, tuple[float, float]], int, int]:
    ids = {u["id"] for u in units}
    children: dict[str | None, list[str]] = {}
    for u in units:
        p = u.get("parent_id") if u.get("parent_id") in ids else None
        children.setdefault(p, []).append(u["id"])
    width: dict[str, float] = {}

    def measure(uid: str) -> float:
        kids = children.get(uid, [])
        w = sum(measure(k) for k in kids) + H_GAP * max(0, len(kids) - 1) if kids else BOX_W
        width[uid] = max(BOX_W, w)
        return width[uid]

    roots = children.get(None, [])
    total = sum(measure(r) for r in roots) + H_GAP * max(0, len(roots) - 1)
    pos: dict[str, tuple[float, float]] = {}
    depth_max = 0

    def place(uid: str, x0: float, depth: int) -> None:
        nonlocal depth_max
        depth_max = max(depth_max, depth)
        w = width[uid]
        pos[uid] = (x0 + w / 2 - BOX_W / 2, PAD + depth * (BOX_H + V_GAP))
        kids = children.get(uid, [])
        kw = sum(width[k] for k in kids) + H_GAP * max(0, len(kids) - 1)
        x = x0 + (w - kw) / 2
        for k in kids:
            place(k, x, depth + 1)
            x += width[k] + H_GAP

    x = PAD
    for r in roots:
        place(r, x, 0)
        x += width[r] + H_GAP
    return pos, int(total + 2 * PAD), int(PAD * 2 + (depth_max + 1) * (BOX_H + V_GAP) - V_GAP)


def _wrap(d: ImageDraw.ImageDraw, text: str, fnt: ImageFont.ImageFont, max_w: int) -> list[str]:
    lines: list[str] = []
    cur = ""
    for word in text.split():
        cand = f"{cur} {word}".strip()
        if d.textlength(cand, font=fnt) <= max_w or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def render_chart(units: list[dict[str, Any]], title: str = "", statuses: dict[str, str] | None = None,
                 scale: float = 1.0) -> bytes:
    """units: [{id, name, parent_id, short?, head_title?}] → PNG."""
    statuses = statuses or {}
    pos, w, h = _layout(units)
    title_h = 50 if title else 0
    img = Image.new("RGB", (max(w, 400), h + title_h), "white")
    d = ImageDraw.Draw(img)
    f_name = font(14, bold=True)
    f_small = font(12)
    if title:
        d.text((PAD, 14), title, fill="#1B2631", font=font(20, bold=True))
    ids = {u["id"] for u in units}
    by_id = {u["id"]: u for u in units}
    # связи
    for u in units:
        pid = u.get("parent_id")
        if pid not in ids or u["id"] not in pos or pid not in pos:
            continue
        px, py = pos[pid]
        cx, cy = pos[u["id"]]
        x1, y1 = px + BOX_W / 2, py + BOX_H + title_h
        x2, y2 = cx + BOX_W / 2, cy + title_h
        ym = y1 + V_GAP / 2
        dashed = statuses.get(u["id"]) == "abolished"
        color = "#566573"
        d.line([(x1, y1), (x1, ym)], fill=color, width=2)
        d.line([(x1, ym), (x2, ym)], fill=color, width=2)
        if dashed:
            for yy in range(int(ym), int(y2), 8):
                d.line([(x2, yy), (x2, min(yy + 4, y2))], fill="#C0392B", width=2)
        else:
            d.line([(x2, ym), (x2, y2)], fill=color, width=2)
    # блоки
    for uid, (x, y) in pos.items():
        u = by_id[uid]
        fill, border = STATUS_COLORS.get(statuses.get(uid), STATUS_COLORS[None])
        y += title_h
        d.rectangle([x, y, x + BOX_W, y + BOX_H], fill=fill, outline=border, width=3)
        name = u.get("name", "")
        lines = _wrap(d, name, f_name, BOX_W - 24)[:3]
        if u.get("short") and len(lines) < 3:
            lines.append(f"({u['short']})")
        ty = y + (BOX_H - len(lines) * 18) / 2
        for ln in lines:
            tw = d.textlength(ln, font=f_name)
            d.text((x + (BOX_W - tw) / 2, ty), ln, fill="#17202A", font=f_name)
            ty += 18
        if statuses.get(uid):
            label = {"created": "создано", "abolished": "упразднено", "reorganized": "реорганизовано",
                     "split": "разделено", "renamed": "переименовано", "merged": "слияние"}.get(statuses[uid])
            if label:
                d.text((x + 6, y + BOX_H - 16), label, fill=border, font=f_small)
    if scale != 1.0:
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
