"""OCR через Tesseract (rus+kaz+eng). Используется для фото документов и сканов PDF."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from functools import lru_cache

from PIL import Image, ImageOps

from ..config import get_settings


@dataclass
class OcrLine:
    text: str
    x: int
    y: int
    w: int
    h: int
    conf: float
    block: int
    par: int


@lru_cache
def tesseract_available() -> bool:
    try:
        import pytesseract

        cmd = get_settings().tesseract_cmd
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd
        elif not shutil.which("tesseract"):
            return False
        pytesseract.get_tesseract_version()
        return True
    except Exception:  # noqa: BLE001
        return False


@lru_cache
def available_langs() -> str:
    """Оставляет только установленные языковые пакеты из OCR_LANGS."""
    import pytesseract

    wanted = [x for x in get_settings().ocr_langs.split("+") if x]
    try:
        have = set(pytesseract.get_languages(config=""))
    except Exception:  # noqa: BLE001
        return "+".join(wanted) or "eng"
    langs = [x for x in wanted if x in have]
    return "+".join(langs) or ("eng" if "eng" in have else wanted[0])


def prepare_image(img: Image.Image, min_width: int = 1800) -> Image.Image:
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("L", "RGB"):
        img = img.convert("RGB")
    gray = ImageOps.grayscale(img)
    if gray.width < min_width:
        scale = min_width / gray.width
        gray = gray.resize((int(gray.width * scale), int(gray.height * scale)), Image.LANCZOS)
    return ImageOps.autocontrast(gray)


def ocr_lines(img: Image.Image, psm: int = 3) -> list[OcrLine]:
    import pytesseract

    if not tesseract_available():
        raise RuntimeError(
            "Tesseract OCR не установлен. Установите tesseract-ocr (+ языки rus, kaz) "
            "или используйте Docker-образ проекта, либо подключите vision-модель."
        )
    data = pytesseract.image_to_data(
        img, lang=available_langs(), config=f"--psm {psm}", output_type=pytesseract.Output.DICT
    )
    groups: dict[tuple[int, int, int], list[int]] = {}
    for i, word in enumerate(data["text"]):
        if not word or not word.strip():
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        groups.setdefault(key, []).append(i)
    lines: list[OcrLine] = []
    for (block, par, _), idxs in groups.items():
        words = [data["text"][i] for i in idxs]
        xs = [data["left"][i] for i in idxs]
        ys = [data["top"][i] for i in idxs]
        x2 = [data["left"][i] + data["width"][i] for i in idxs]
        y2 = [data["top"][i] + data["height"][i] for i in idxs]
        confs = [float(data["conf"][i]) for i in idxs if float(data["conf"][i]) >= 0]
        lines.append(
            OcrLine(
                text=" ".join(words),
                x=min(xs), y=min(ys), w=max(x2) - min(xs), h=max(y2) - min(ys),
                conf=sum(confs) / len(confs) if confs else 0.0,
                block=block, par=par,
            )
        )
    lines.sort(key=lambda ln: (ln.y, ln.x))
    return lines


def ocr_text(img: Image.Image, psm: int = 6) -> str:
    import pytesseract

    if not tesseract_available():
        return ""
    return pytesseract.image_to_string(img, lang=available_langs(), config=f"--psm {psm}").strip()
