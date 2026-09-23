"""Разбиение текста документа на пункты (clauses) с сохранением нумерации.

Каждый пункт получает стабильный идентификатор, машинную ссылку (`5.3.2.а`),
человекочитаемую ссылку («пп. «а» п. 5.3.2»), раздел, контекст (заголовок
перечня, к которому он относится), субъект (роль/подразделение), вид
(функция, право, обязанность …) и номер страницы. Это обеспечивает
прослеживаемость каждого вывода до конкретного пункта документа.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------- регулярные выражения

_UPPER = "А-ЯЁӘҒҚҢӨҰҮҺІA-Z"
_LOWER = "а-яёәғқңөұүһіa-z"

NUM_RE = re.compile(
    rf"^\s*(?P<num>\d{{1,2}}(?:\.\d{{1,3}}){{0,5}})(?P<dot>\.)?(?:\s+|(?=[{_UPPER}{_LOWER}«\"(]))"
)
LETTER_RE = re.compile(rf"^\s*(?P<letter>[{_LOWER}])(?P<punct>[.)])\s+")
PAREN_NUM_RE = re.compile(r"^\s*(?P<pnum>\d{1,2})\)\s+")
BULLET_RE = re.compile(r"^\s*[-–—•·▪●○■□✓➢►]\s*")
ARTICLE_RE = re.compile(r"^\s*(?P<word>Статья|Глава|Раздел|Бап|Тарау|Бөлім)\s+(?P<num>\d{1,3})\.?\s*", re.I)
# «… удаленно. 3.10.Рабочие места …» — пункт, склеенный с предыдущим абзацем
EMBEDDED_NUM_RE = re.compile(
    rf"(?<=[^\d\s][.;:!?])\s*(?P<num>\d{{1,2}}(?:\.\d{{1,3}}){{1,5}})\.\s?(?=[{_UPPER}{_LOWER}])"
)
TOC_TITLE_RE = re.compile(r"^\s*(оглавление|содержание|мазмұны)\s*$", re.I)
TOC_LINE_RE = re.compile(rf"^\s*(\d{{1,2}}\.)?\s*[{_UPPER}\s,.\-«»\"()]+\s\d{{1,3}}(\s|$)")
EDITION_RE = re.compile(r"редакц\w*\s*(?:№|No|N)?\s*(\d+)", re.I)
ROLE_START_RE = re.compile(
    r"^(Главн\w+|Директор\w*|Руководител\w+|Начальник\w*|Заместител\w+|Менеджер\w*|"
    r"Председател\w+|Работник\w*|Сотрудник\w*|Специалист\w*|Аудитор\w*|Член\w*|"
    r"Департамент\w*|Управлени\w+|Отдел\w*|Служб\w+|Блок\w*|Центр\w*|Сектор\w*|Групп\w+|"
    r"Дирекци\w+|Комитет\w*|Подразделени\w+)",
    re.I,
)
ACTOR_STOP_RE = re.compile(
    r"\s+(не|обязан\w*|имеет|имеют|несет|несут|подчиня\w+|осуществля\w+|вправе|должен|должны|"
    r"отвечает|отвечают|–|—|-)\s|:\s*$",
    re.I,
)


# ---------------------------------------------------------------- структуры данных


@dataclass
class RawPara:
    """Абзац, извлечённый из исходного файла, до сегментации."""

    text: str
    style: str = ""
    page: int | None = None
    label: str = ""  # номер из автонумерации Word («5.3.1.» / «а)»)
    is_heading: bool = False
    heading_level: int | None = None
    bold: bool = False
    source: str = ""  # доп. координаты (для Excel: «Лист1, строка 5»)


@dataclass
class Clause:
    id: str
    ref: str
    ref_display: str
    text: str
    level: int
    kind: str = "general"
    parent: str | None = None
    section: str = ""
    context: str = ""
    actor: str = ""
    page: int | None = None
    is_heading: bool = False
    source: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = {
            "id": self.id,
            "ref": self.ref,
            "ref_display": self.ref_display,
            "text": self.text,
            "level": self.level,
            "kind": self.kind,
            "parent": self.parent,
            "section": self.section,
            "context": self.context,
            "actor": self.actor,
            "page": self.page,
            "is_heading": self.is_heading,
        }
        if self.source:
            d["source"] = self.source
        if self.extra:
            d["extra"] = self.extra
        return d


# ---------------------------------------------------------------- утилиты


def clean_text(text: str) -> str:
    text = text.replace(" ", " ").replace("​", "").replace("\t", " ")
    text = re.sub(r"[    ]+", " ", text)
    return text.strip()


def _parse_num(num: str) -> list[int]:
    return [int(p) for p in num.split(".") if p]


def _plausible_next(prev: list[int] | None, cand: list[int]) -> bool:
    """Может ли номер `cand` следовать за `prev` (для разбиения склеенных абзацев)."""
    if not prev:
        return False
    if cand[:-1] == prev and cand[-1] == 1:  # потомок: 5.3 -> 5.3.1
        return True
    # следующий на том же или более высоком уровне: 5.3.4 -> 5.3.5 / 5.4 / 6.1
    for depth in range(len(prev), 0, -1):
        if (
            len(cand) >= depth
            and cand[: depth - 1] == prev[: depth - 1]
            and cand[depth - 1] == prev[depth - 1] + 1
        ):
            return all(c == 1 for c in cand[depth:])
    return False


def _ref_display(ref: str, kind: str) -> str:
    if kind == "letter":
        base, _, letter = ref.rpartition(".")
        return f"пп. «{letter}» п. {base}"
    if kind == "paren":
        base, _, n = ref.rpartition(".")
        return f"пп. {n}) п. {base}"
    if kind == "bullet":
        base, _, n = ref.rpartition(".•")
        return f"п. {base}, абз. {n}" if base else f"абз. {n}"
    if kind == "para":
        base, _, n = ref.rpartition("¶")
        return f"п. {base}, абз. {n}" if base else f"абз. {n}"
    if kind in ("article", "row"):
        return ref
    return f"п. {ref}"


KIND_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("toc", re.compile(r"оглавлени|содержани", re.I)),
    ("definition", re.compile(r"термин|определени|сокращени", re.I)),
    ("restriction", re.compile(r"не имеют права|не имеет права|не вправе|запрещ", re.I)),
    ("structure", re.compile(r"подчиня|в составе следующих|состоит из следующ", re.I)),
    ("right", re.compile(r"\bправ[аоу]\b|имеет право|имеют право|вправе|\bправе\b", re.I)),
    ("duty", re.compile(r"обязан|обязанност|должен|должны", re.I)),
    ("responsibility", re.compile(r"нес[её]т ответствен|несут ответствен|ответственност\w* за\b|"
                                  r"ответственность\s*$", re.I)),
    ("function", re.compile(r"функци|осуществляет следующ|выполняет следующ|полномочи", re.I)),
    ("task", re.compile(r"\bзадач", re.I)),
    ("goal", re.compile(r"\bцел[ьи]\b|\bцелей\b", re.I)),
    ("structure", re.compile(r"структур|состав|подчиня|штатн", re.I)),
    ("interaction", re.compile(r"взаимоотношени|взаимодейств|\bсвязи\b", re.I)),
    ("general", re.compile(r"общие положения|заключительн", re.I)),
]

KIND_LABELS = {
    "function": "функция",
    "task": "задача",
    "duty": "обязанность",
    "right": "право",
    "responsibility": "ответственность",
    "structure": "структура",
    "interaction": "взаимодействие",
    "goal": "цель",
    "definition": "термин",
    "restriction": "ограничение",
    "general": "общее положение",
    "toc": "оглавление",
    "row": "строка таблицы",
}


def classify(text: str, context: str, section: str) -> str:
    """Определяет вид пункта: функция / задача / право / обязанность …"""
    # 1) ближайший контекст-перечень («… имеет право:», «… функции:»)
    if context:
        for kind, rx in KIND_RULES:
            if rx.search(context):
                return kind
    # 2) разделы, вид которых не зависит от субъекта
    if section:
        for kind, rx in KIND_RULES:
            if kind in ("toc", "definition", "interaction", "responsibility") and rx.search(section):
                return kind
    # 3) перечень под заголовком-ролью («Директор ДНМ:») — обязанности роли
    if context and ROLE_START_RE.match(NUM_RE.sub("", context, count=1).strip()):
        return "duty"
    # 4) раздел документа
    if section:
        for kind, rx in KIND_RULES:
            if rx.search(section):
                return kind
    # 5) сам текст (только явные маркеры функций и прав)
    for kind, rx in KIND_RULES:
        if kind in ("function", "right") and rx.search(text[:80]):
            return kind
    return "general"


def extract_actor(text: str) -> str:
    """Из заголовка перечня («Директор ДНМ обязан …:») извлекает субъект."""
    t = text.strip().rstrip(":").strip()
    t = NUM_RE.sub("", t, count=1).strip()
    if not ROLE_START_RE.match(t):
        return ""
    m = ACTOR_STOP_RE.search(t + ":")
    actor = t[: m.start()] if m else t
    actor = re.sub(r"\s*\(далее[^)]*\)", "", actor).strip(" ,;")
    if len(actor) > 160 or len(actor.split()) > 18:
        return ""
    return actor


def _split_heading(text: str, toc: dict[str, str]) -> tuple[str, str]:
    """Отделяет заголовок раздела от склеенного с ним текста."""
    m = NUM_RE.match(text)
    num = m.group("num") if m else ""
    body = text[m.end():] if m else text
    if num and num in toc:
        title = toc[num]
        if body.upper().startswith(title.upper()):
            return body[: len(title)].strip(), body[len(title):].strip()
    if len(body) <= 70:
        return body.strip(), ""
    words = body.split()
    for i in range(1, min(len(words), 12)):
        w, prev = words[i], words[i - 1]
        if len(w) > 1 and w[0].isupper() and w[1:].islower() and (prev.endswith(".") or prev.isupper() or i >= 2):
            return " ".join(words[:i]).rstrip("."), " ".join(words[i:])
    return body.strip(), ""


def _is_heading_para(p: RawPara, text: str) -> bool:
    if p.is_heading:
        return True
    style = p.style.lower()
    if any(s in style for s in ("heading", "заголов", "title")):
        return True
    if len(text) < 90 and not text.endswith((";", ",")):
        letters = [c for c in text if c.isalpha()]
        if len(letters) > 3 and sum(c.isupper() for c in letters) / len(letters) > 0.85:
            return True
        if p.bold and not text.endswith("."):
            return True
    return False


def _explode(paras: list[RawPara]) -> list[RawPara]:
    """Разбивает абзацы со «склеенными» пунктами."""
    out: list[RawPara] = []
    prev_num: list[int] | None = None
    for p in paras:
        text = clean_text(p.text)
        if not text:
            continue
        probe = f"{p.label} {text}" if p.label else text
        m = NUM_RE.match(probe)
        if m and (m.group("dot") or "." in m.group("num")):
            prev_num = _parse_num(m.group("num"))
        cursor = prev_num
        splits: list[int] = []
        for em in EMBEDDED_NUM_RE.finditer(text):
            if em.start("num") == 0:
                continue
            cand = _parse_num(em.group("num"))
            if _plausible_next(cursor, cand):
                splits.append(em.start("num"))
                cursor = cand
        pieces = [text]
        if splits:
            pieces, last = [], 0
            for s in splits:
                pieces.append(text[last:s].strip())
                last = s
            pieces.append(text[last:].strip())
            prev_num = cursor
        for i, piece in enumerate(pieces):
            if not piece:
                continue
            first = i == 0
            out.append(
                RawPara(
                    text=piece,
                    style=p.style if first else "",
                    page=p.page,
                    label=p.label if first else "",
                    is_heading=p.is_heading if first else False,
                    heading_level=p.heading_level if first else None,
                    bold=p.bold if first else False,
                    source=p.source,
                )
            )
    return out


# ---------------------------------------------------------------- основной алгоритм


class _Segmenter:
    def __init__(self, toc: dict[str, str]) -> None:
        self.toc = toc
        self.clauses: list[Clause] = []
        self.by_id: dict[str, Clause] = {}
        self.section = ""
        self.sub_section = ""
        self.toc_mode = False
        self.lead_para: dict[str, Clause] = {}

    def add(self, ref: str, kind_ref: str, text: str, level: int, parent: Clause | None,
            is_heading: bool = False, page: int | None = None, source: str = "") -> Clause:
        c = Clause(
            id=f"c{len(self.clauses) + 1}",
            ref=ref,
            ref_display=_ref_display(ref, kind_ref),
            text=text,
            level=level,
            parent=parent.id if parent else None,
            section=" › ".join(s for s in (self.section, self.sub_section) if s),
            page=page,
            is_heading=is_heading,
            source=source,
        )
        ctx, actor = "", ""
        cur = parent
        while cur is not None:
            if not ctx and (cur.text.rstrip().endswith(":") or cur.is_heading):
                ctx = cur.text
                if cur.is_heading and cur.id in self.lead_para:
                    ctx = self.lead_para[cur.id].text
            if not actor and cur.actor:
                actor = cur.actor
            cur = self.by_id.get(cur.parent) if cur.parent else None
        own_actor = extract_actor(text) if text.rstrip().endswith(":") and not is_heading else ""
        if own_actor:
            actor = own_actor
            if kind_ref == "num" and level <= 2:
                self.sub_section = ""  # новая роль: подзаголовок-роль больше не действует
        if not actor and self.sub_section.endswith(":"):
            actor = extract_actor(self.sub_section)
        c.context = ctx
        c.actor = actor
        c.kind = "toc" if self.toc_mode else classify(text, ctx, c.section)
        if kind_ref == "para" and parent is not None and parent.is_heading and text.rstrip().endswith(":"):
            self.lead_para[parent.id] = c
            if not c.actor:
                c.actor = extract_actor(text)
        self.clauses.append(c)
        self.by_id[c.id] = c
        return c


def segment(paras: list[RawPara]) -> tuple[list[Clause], dict[str, Any]]:
    """Преобразует абзацы в иерархию пунктов. Возвращает (пункты, метаданные)."""
    paras = _explode(paras)
    meta: dict[str, Any] = {"title": "", "edition": "", "approval": ""}

    # Оглавление (часто в конце документа) помогает точно отделять заголовки от текста
    toc: dict[str, str] = {}
    in_toc = False
    for p in paras:
        t = clean_text(p.text)
        if TOC_TITLE_RE.match(t):
            in_toc = True
            continue
        if in_toc:
            mt = re.match(r"^\s*(\d{1,2})\.\s+(.+?)\s+\d{1,3}(?:\s|$)", t)
            if mt:
                toc[mt.group(1)] = mt.group(2).strip()

    sg = _Segmenter(toc)
    stack: list[tuple[list[int], Clause]] = []
    last_numeric: Clause | None = None
    last_letter: Clause | None = None
    sub_counter: dict[str, int] = {}
    title_parts: list[str] = []
    approval: list[str] = []
    seen_numbered = False
    restart: tuple[Clause, int] | None = None  # (родитель, последний номер) перезапущенного списка

    def next_sub(key: str) -> int:
        sub_counter[key] = sub_counter.get(key, 0) + 1
        return sub_counter[key]

    for p in paras:
        text = clean_text(p.text)
        if not text:
            continue
        if TOC_TITLE_RE.match(text):
            sg.toc_mode = True
            continue
        if sg.toc_mode:
            if TOC_LINE_RE.match(text) or re.match(r"^\s*приложени", text, re.I) or len(text) < 60:
                continue
            sg.toc_mode = False

        full = f"{p.label} {text}".strip() if p.label else text

        # --- преамбула (гриф утверждения, название, редакция) до первого пункта
        if not seen_numbered:
            me = EDITION_RE.search(full)
            if me and not meta["edition"]:
                meta["edition"] = me.group(1)
            if re.match(r"^(утвержден|утверждено|бекітілген|бекітілді|протокол|от\s*«|решением)", full, re.I) \
                    or "approval" in p.style.lower():
                approval.append(full)
                continue
            if ("title" in p.style.lower() or (_is_heading_para(p, full) and not NUM_RE.match(full))) \
                    and not me and len(full) < 250:
                title_parts.append(full)
                continue
            if me and len(full) < 60:
                continue

        m_num = NUM_RE.match(full)
        m_art = ARTICLE_RE.match(full)
        m_letter = LETTER_RE.match(full)
        m_paren = PAREN_NUM_RE.match(full)
        m_bullet = BULLET_RE.match(full)

        if m_art:
            seen_numbered = True
            num = m_art.group("num")
            body = full[m_art.end():].strip()
            ref = f"{m_art.group('word').capitalize()} {num}"
            sg.section = f"{ref}. {body}" if body and len(body) < 120 else ref
            sg.sub_section = ""
            c = sg.add(ref, "article", body or ref, 1, None, is_heading=len(body) < 120, page=p.page,
                       source=p.source)
            stack = [([int(num)], c)]
            last_numeric, last_letter = c, None
            continue

        if m_num and (m_num.group("dot") or "." in m_num.group("num")):
            seen_numbered = True
            num = m_num.group("num")
            parts = _parse_num(num)
            body = full[m_num.end():].strip()
            # Автонумерованный список «1. 2. 3.», начатый заново внутри раздела «3. Функции»:
            # номер не больше номера текущего раздела (или продолжает такой список) — это подпункты.
            top = stack[0][0][0] if stack else None
            styled_heading = _is_heading_para(p, full) and not body.endswith((";", ","))
            if len(parts) == 1 and last_numeric is not None and not styled_heading and (
                (restart is not None and parts[0] == restart[1] + 1)
                or (restart is None and top is not None and parts[0] <= top and parts[0] == 1)
            ):
                parent = restart[0] if restart is not None else last_numeric
                ref = f"{parent.ref}.{parts[0]}"
                c = sg.add(ref, "paren", body, parent.level + 1, parent, page=p.page, source=p.source)
                restart = (parent, parts[0])
                last_letter = c
                continue
            restart = None
            heading = len(parts) == 1 and (
                _is_heading_para(p, full)
                or (len(body) < 60 and not body.endswith((";", ",", ":", ".")))
            )
            if heading:
                title, rest = _split_heading(full, toc)
                sg.section = f"{num}. {title}".strip()
                sg.sub_section = ""
                c = sg.add(num, "num", title, 1, None, is_heading=True, page=p.page, source=p.source)
                stack = [(parts, c)]
                last_numeric, last_letter = c, None
                if rest:
                    sg.add(f"{num}¶{next_sub(c.id)}", "para", rest, 2, c, page=p.page, source=p.source)
                continue
            while stack and not (len(stack[-1][0]) < len(parts) and parts[: len(stack[-1][0])] == stack[-1][0]):
                stack.pop()
            parent = stack[-1][1] if stack else None
            if len(parts) == 1 and len(body) < 100:
                sg.section, sg.sub_section = f"{num}. {body}", ""
            c = sg.add(num, "num", body, len(parts), parent, page=p.page, source=p.source)
            stack.append((parts, c))
            last_numeric, last_letter = c, None
            continue

        if _is_heading_para(p, full) and len(full) < 150 and not m_letter and not m_bullet:
            sg.sub_section = full  # подзаголовок без номера («Главный аудитор:»)
            continue

        if (m_letter or m_paren) and last_numeric is not None:
            seen_numbered = True
            if m_letter:
                body = full[m_letter.end():].strip()
                ref = f"{last_numeric.ref}.{m_letter.group('letter')}"
                c = sg.add(ref, "letter", body, last_numeric.level + 1, last_numeric, page=p.page, source=p.source)
            else:
                body = full[m_paren.end():].strip()
                ref = f"{last_numeric.ref}.{m_paren.group('pnum')}"
                c = sg.add(ref, "paren", body, last_numeric.level + 1, last_numeric, page=p.page, source=p.source)
            last_letter = c
            continue

        if m_bullet and (last_numeric is not None or last_letter is not None):
            parent = last_letter or last_numeric
            assert parent is not None
            body = full[m_bullet.end():].strip()
            sg.add(f"{parent.ref}.•{next_sub(parent.id)}", "bullet", body, parent.level + 1, parent,
                   page=p.page, source=p.source)
            continue

        # обычный абзац без номера
        parent = last_letter or last_numeric
        if parent is not None:
            sg.add(f"{parent.ref}¶{next_sub(parent.id)}", "para", full, parent.level + 1, parent,
                   page=p.page, source=p.source)
        else:
            sg.add(f"¶{next_sub('root')}", "para", full, 1, None, page=p.page, source=p.source)

    meta["title"] = " ".join(title_parts).strip()
    meta["approval"] = " ".join(approval).strip()
    return sg.clauses, meta


def detect_doc_kind(title: str, filename: str, text_sample: str) -> str:
    probe = f"{title} {filename}".lower()
    rules = [
        ("job_description", r"должностн\w+ инструкц|лауазымдық нұсқаулық"),
        ("org_structure", r"организационн\w+ структур|оргструктур|схем\w+ (управлен|структур)|ұйымдық құрылым"),
        ("staffing", r"штатн\w+ расписан|штатн\w+ численн|штаттық кесте"),
        ("order", r"\bприказ|\bраспоряжени|\bбұйрық|\bрешени\w+ (совета|правления)"),
        ("regulation", r"положени\w* о|положени\w*$|\bереже"),
        ("internal_normative", r"регламент|политик|правил|стандарт|порядок|методик|инструкци"),
        ("law", r"закон|кодекс|постановлени"),
    ]
    for kind, rx in rules:
        if re.search(rx, probe):
            return kind
    sample = text_sample.lower()[:3000]
    for kind, rx in rules:
        if re.search(rx, sample):
            return kind
    return "other"
