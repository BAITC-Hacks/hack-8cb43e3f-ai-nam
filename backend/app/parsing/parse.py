"""Единая точка входа разбора документа любого поддерживаемого формата."""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

from .docx_reader import read_docx
from .ocr import ocr_lines, prepare_image, tesseract_available
from .pdf_reader import read_pdf
from .segment import Clause, RawPara, clean_text, detect_doc_kind, segment
from .tables import read_csv, read_xlsx, rows_to_clauses

SUPPORTED = {".docx", ".doc", ".rtf", ".odt", ".pdf", ".xlsx", ".xlsm", ".csv", ".txt", ".md",
             ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}

UNIT_WORDS = {
    "блок": "Блок", "блока": "Блок",
    "департамент": "Департамент", "департамента": "Департамент",
    "управление": "Управление", "управления": "Управление",
    "отдел": "Отдел", "отдела": "Отдел",
    "служба": "Служба", "службы": "Служба",
    "центр": "Центр", "центра": "Центр",
    "сектор": "Сектор", "сектора": "Сектор",
    "группа": "Группа", "группы": "Группа",
    "дирекция": "Дирекция", "дирекции": "Дирекция",
    "комитет": "Комитет", "комитета": "Комитет",
    "лаборатория": "Лаборатория", "лаборатории": "Лаборатория",
    "филиал": "Филиал", "филиала": "Филиал",
    "подразделение": "Подразделение", "подразделения": "Подразделение",
    "направление": "Направление", "направления": "Направление",
}
ABBR_RE = re.compile(r"\((?:далее\s*[-–—]?\s*)?[«\"]?(?P<abbr>[А-ЯЁӘҒҚҢӨҰҮҺІA-Z]{2,12})[»\"]?\)")
TRAILING_FILLER = re.compile(r"\s+(Общества|Компании|АО\s*«[^»]+»|Холдинга|организации)$", re.I)


def _convert_with_soffice(path: Path, target: str) -> Path | None:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None
    out_dir = Path(tempfile.mkdtemp(prefix="conv_"))
    try:
        subprocess.run([soffice, "--headless", "--convert-to", target, "--outdir", str(out_dir), str(path)],
                       check=True, timeout=180, capture_output=True)
    except (subprocess.SubprocessError, OSError):
        return None
    produced = list(out_dir.glob(f"*.{target}"))
    return produced[0] if produced else None


def extract_abbreviations(texts: list[str]) -> dict[str, dict[str, Any]]:
    """Находит расшифровки сокращений: «Департамент … (ДНМ)», «Блока … (далее - БВА)»."""
    found: dict[str, dict[str, Any]] = {}
    for text in texts:
        for m in ABBR_RE.finditer(text):
            abbr = m.group("abbr")
            if abbr in found and found[abbr].get("is_unit"):
                continue
            before = text[max(0, m.start() - 220): m.start()].rstrip()
            words = before.split()
            full, is_unit = "", False
            # 1) ищем ближайшее слово-тип подразделения
            for i in range(len(words) - 1, max(-1, len(words) - 16), -1):
                raw = re.sub(r"[^\wЁё-]", "", words[i])
                w = raw.lower()
                # название подразделения пишется с заглавной: «Департамент …», «Блока …»
                if w in UNIT_WORDS and raw[:1].isupper():
                    tail = " ".join(words[i + 1:])
                    full = f"{UNIT_WORDS[w]} {tail}".strip()
                    is_unit = True
                    break
            # 2) иначе — аббревиатура по первым буквам последних слов
            if not full:
                letters = abbr.lower()
                for n in range(len(letters), min(len(words), len(letters) * 2) + 1):
                    cand = words[-n:]
                    initials = "".join(w[0].lower() for w in cand if w and w[0].isalpha())
                    it = iter(initials)
                    if all(ch in it for ch in letters) and initials[:1] == letters[:1]:
                        full = " ".join(cand)
                        break
            if full and not is_unit:
                # «Юридический департамент (ЮД)», «Кадровая служба (КС)»
                lw = [re.sub(r"[^\wЁё-]", "", w).lower() for w in full.split()]
                if any(w in UNIT_WORDS for w in lw[:3]) and full[:1].isupper():
                    is_unit = True
            full = TRAILING_FILLER.sub("", full.strip(" ,;:–—-«»\""))
            full = re.sub(r"\s+", " ", full)
            if full and len(full) > len(abbr):
                found[abbr] = {"abbr": abbr, "full": full, "is_unit": is_unit}
    return found


def _image_paras(path: Path) -> tuple[list[RawPara], dict]:
    img = Image.open(path)
    img = prepare_image(img)
    lines = ocr_lines(img)
    paras: list[RawPara] = []
    cur_key = None
    buf: list[str] = []
    for ln in lines:
        key = (ln.block, ln.par)
        if key != cur_key and buf:
            paras.append(RawPara(text=" ".join(buf), page=1))
            buf = []
        cur_key = key
        buf.append(ln.text)
    if buf:
        paras.append(RawPara(text=" ".join(buf), page=1))
    return paras, {"pages": 1, "method": "image_ocr"}


def parse_file(path: Path, filename: str | None = None) -> dict[str, Any]:
    """Разбирает файл и возвращает словарь с пунктами, метаданными и предупреждениями."""
    filename = filename or path.name
    ext = Path(filename).suffix.lower()
    warnings: list[str] = []
    records: list[dict[str, Any]] = []
    clauses: list[Clause]
    meta: dict[str, Any] = {"title": "", "edition": "", "approval": ""}
    method = ext.lstrip(".")
    pages = 0
    orgchart: dict[str, Any] | None = None

    if ext in (".doc", ".rtf", ".odt"):
        converted = _convert_with_soffice(path, "docx")
        if not converted:
            raise ValueError(f"Формат {ext} требует LibreOffice для конвертации. Сохраните файл как DOCX или PDF.")
        path, ext = converted, ".docx"

    if ext == ".docx":
        paras, dmeta = read_docx(path)
        clauses, meta = segment(paras)
        for name, rows in dmeta.get("data_tables", []):
            cl, rec = rows_to_clauses(rows, name, start_id=len(clauses) + 1)
            clauses.extend(cl)
            records.extend(rec)
        method = "docx"
    elif ext == ".pdf":
        paras, pmeta = read_pdf(path)
        clauses, meta = segment(paras)
        pages = pmeta["pages"]
        method = pmeta["method"]
        warnings.extend(pmeta["warnings"])
        if len(clauses) < 3:
            orgchart = _try_orgchart(path, is_pdf=True)
    elif ext in (".xlsx", ".xlsm"):
        clauses, records, _ = read_xlsx(path)
        method = "xlsx"
    elif ext == ".csv":
        clauses, records, _ = read_csv(path)
        method = "csv"
    elif ext in (".txt", ".md"):
        raw = path.read_bytes()
        text = ""
        for enc in ("utf-8-sig", "cp1251", "utf-8"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        paras = [RawPara(text=line) for line in text.splitlines() if line.strip()]
        clauses, meta = segment(paras)
        method = "txt"
    elif ext in IMAGE_EXT:
        orgchart = _try_orgchart(path, is_pdf=False)
        if orgchart and orgchart.get("units"):
            clauses = [
                Clause(id=f"c{i + 1}", ref=f"блок {i + 1}", ref_display=f"блок {i + 1} схемы", text=u["name"],
                       level=1, kind="structure", actor=u["name"], page=1)
                for i, u in enumerate(orgchart["units"])
            ]
            for c, u in zip(clauses, orgchart["units"]):
                u["clause_id"] = c.id
            method = "orgchart_" + orgchart.get("method", "ocr")
        else:
            if not tesseract_available():
                raise ValueError("Для распознавания изображений нужен Tesseract OCR или vision-модель (см. README).")
            paras, imeta = _image_paras(path)
            clauses, meta = segment(paras)
            method = imeta["method"]
        pages = 1
    else:
        raise ValueError(f"Неподдерживаемый формат: {ext}. Поддерживаются: {', '.join(sorted(SUPPORTED))}")

    texts = [c.text for c in clauses]
    abbreviations = extract_abbreviations(([meta.get("title", "")] if meta.get("title") else []) + texts)
    sample = " ".join(texts[:40])
    title = meta.get("title") or ""
    if not title:
        stem = Path(filename).stem
        title = clean_text(re.sub(r"[_]+", " ", stem))
    doc_kind = detect_doc_kind(title, filename, sample)
    if orgchart and orgchart.get("units"):
        doc_kind = "org_structure"
    if not clauses:
        warnings.append("В документе не найден текст. Проверьте файл или включите OCR / vision-модель.")

    return {
        "title": title,
        "doc_kind": doc_kind,
        "edition": meta.get("edition", ""),
        "approval": meta.get("approval", ""),
        "method": method,
        "pages": pages,
        "clauses": [c.to_dict() for c in clauses],
        "records": records,
        "abbreviations": abbreviations,
        "orgchart": orgchart,
        "warnings": warnings,
    }


def _try_orgchart(path: Path, is_pdf: bool) -> dict[str, Any] | None:
    """Пытается распознать схему оргструктуры (блоки и связи)."""
    try:
        from ..orgchart.extract import extract_orgchart_from_file
    except ImportError:  # pragma: no cover
        return None
    try:
        return extract_orgchart_from_file(path, is_pdf=is_pdf)
    except Exception as exc:  # noqa: BLE001 - схема необязательна
        return {"units": [], "method": "error", "warnings": [str(exc)]}
