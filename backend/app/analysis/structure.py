"""Извлечение оргструктуры (подразделения, подчинённость, должности, функции) из документов одной стороны.

Источники подразделений:
  * определения с сокращениями: «Департамент … (ДНМ)», «Блок … (далее - БВА)»;
  * перечни состава: «БВА состоит из следующих структурных подразделений: а. …»;
  * пункты о подчинённости: «Директору ДИТААД подчиняются …: а. Директор направления …»;
  * заголовки «Положение о Департаменте …»;
  * табличные реестры (Excel/Word) и распознанные схемы (фото/PDF).

Функции закрепляются за подразделениями по субъекту пункта («Директор ДНМ:»,
«Директоры департаментов …:») или по предмету документа (Положение о подразделении).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .text import name_similarity, normalize, tokens

UNIT_FORMS: dict[str, tuple[str, str]] = {}
_BASES = {
    "department": ("Департамент", ["департамент", "департамента", "департаменте", "департаменту", "департаментом"]),
    "directorate": ("Управление", ["управление", "управления", "управлении", "управлению"]),
    "division": ("Отдел", ["отдел", "отдела", "отделе", "отделу", "отделом"]),
    "service": ("Служба", ["служба", "службы", "службе", "службу", "службой"]),
    "block": ("Блок", ["блок", "блока", "блоке", "блоку", "блоком"]),
    "center": ("Центр", ["центр", "центра", "центре", "центру", "центром"]),
    "sector": ("Сектор", ["сектор", "сектора", "секторе", "сектору"]),
    "group": ("Группа", ["группа", "группы", "группе", "группу"]),
    "direction": ("Направление", ["направление", "направления", "направлении", "направлению"]),
    "office": ("Дирекция", ["дирекция", "дирекции", "дирекцию"]),
    "branch": ("Филиал", ["филиал", "филиала", "филиале", "филиалу"]),
    "committee": ("Комитет", ["комитет", "комитета", "комитете"]),
    "lab": ("Лаборатория", ["лаборатория", "лаборатории"]),
    "unit": ("Подразделение", ["подразделение", "подразделения", "подразделении"]),
}
for _type, (_nom, _forms) in _BASES.items():
    for _f in _forms:
        UNIT_FORMS[_f] = (_nom, _type)

SUBUNIT_TYPES = {"department", "directorate", "division", "service", "center", "sector", "office", "lab"}
PLURAL_GENERIC = {
    "департаментов": "department", "управлений": "directorate", "отделов": "division",
    "служб": "service", "центров": "center", "секторов": "sector", "подразделений": None,
}
ROLE_WORDS = re.compile(
    r"^(главн\w+\s+)?(исполнительн\w+\s+)?(заместител\w+\s+)?(директор\w*|руководител\w+|начальник\w*|"
    r"заведующ\w+|менеджер\w*|председател\w+|работник\w*|сотрудник\w*|куратор\w*)\s*",
    re.I,
)
HEAD_ROLE_RE = re.compile(r"^(главн\w+\s+\w+|руководител\w+|начальник\w*|председател\w+)$", re.I)
COMPOSITION_RE = re.compile(r"состоит из|входят|в состав\b|включает в себя|структурн\w+ подразделени\w+:", re.I)
SUBORDINATION_RE = re.compile(r"подчиня\w+", re.I)
TITLE_UNIT_RE = re.compile(r"положени\w*\s+об?\s+(.+)$", re.I)
INTRO_RE = re.compile(r"следующ\w+ (функци|задач|прав|обязанност)|имеет право|имеют право|вправе:|обязан\w*:", re.I)


def unit_type_of(name: str) -> str:
    words = normalize(name).split(" ") if name else [""]
    if words[0] in UNIT_FORMS:
        return UNIT_FORMS[words[0]][1]
    if len(words) > 1 and words[1] in UNIT_FORMS:  # «Юридический департамент»
        return UNIT_FORMS[words[1]][1]
    return "unit"


def starts_with_unit(text: str) -> bool:
    words = [re.sub(r"[^\wЁё-]", "", w).lower() for w in text.split()[:2]]
    if not words:
        return False
    return words[0] in UNIT_FORMS or (len(words) > 1 and words[1] in UNIT_FORMS
                                      and re.search(r"(ом|ой|ого|ому|ем|ий|ый|ая|ое|ые|ых)$", words[0]) is not None)


GENDER = {"department": "m", "division": "m", "block": "m", "center": "m", "sector": "m", "branch": "m",
          "committee": "m", "directorate": "n", "direction": "n", "unit": "n", "service": "f", "group": "f",
          "office": "f", "lab": "f"}


def _adj_nominative(adj: str, gender: str) -> str:
    """Прилагательное в косвенном падеже -> именительный («Юридическом» -> «Юридический»)."""
    low = adj.lower()
    m = re.match(r"^(.+?)(ому|ому|ом|ого|ему|ем|его|ой|ую|ая|ое|ый|ий|ым|им)$", low)
    if not m:
        return adj
    stem = adj[: len(m.group(1))]
    soft = stem[-1:].lower() in "кгхжшчщ"
    if gender == "f":
        end = "ая" if not stem.lower().endswith(("н",)) or soft else "ая"
    elif gender == "n":
        end = "ое" if not soft else "ое"
    else:
        end = "ий" if soft else "ый"
    return stem + end


def to_nominative(phrase: str) -> str:
    """«департамента непрерывного мониторинга» -> «Департамент непрерывного мониторинга»;
    «Юридическом департаменте» -> «Юридический департамент»."""
    words = phrase.strip().split()
    if not words:
        return phrase
    first = re.sub(r"[^\wЁё-]", "", words[0]).lower()
    second = re.sub(r"[^\wЁё-]", "", words[1]).lower() if len(words) > 1 else ""
    if first in UNIT_FORMS:
        words[0] = UNIT_FORMS[first][0]
    elif second in UNIT_FORMS and re.search(r"(ом|ой|ого|ому|ем|ий|ый|ая|ое)$", first):
        nom, utype = UNIT_FORMS[second]
        words[0] = _adj_nominative(words[0], GENDER.get(utype, "m"))
        words[0] = words[0][:1].upper() + words[0][1:]
        words[1] = nom.lower()
    else:
        words[0] = words[0][:1].upper() + words[0][1:]
    name = " ".join(words)
    name = re.sub(r"\s*\((?:далее[^)]*|[А-ЯЁA-Z]{2,12})\)\s*", " ", name)
    name = re.sub(r"\s+(Общества|Компании|АО\s*«[^»]+»)\s*$", "", name, flags=re.I)
    return name.strip(" .;:,")


def unit_name_similarity(a: str, b: str) -> float:
    """Сходство названий подразделений: тип («Департамент»/«Направление») должен совпадать."""
    from rapidfuzz import fuzz

    ta, tb = unit_type_of(a), unit_type_of(b)
    na, nb = " ".join(tokens(a)), " ".join(tokens(b))
    if not na or not nb:
        return 0.0
    sim = max(fuzz.token_sort_ratio(na, nb), fuzz.ratio(normalize(a), normalize(b))) / 100.0
    if ta != tb and "unit" not in (ta, tb):
        sim *= 0.6
    return sim


def role_title(text: str, abbrs: list[str]) -> str:
    """«Директор ДИТААД» -> «Директор»; «Главный аудитор» -> «Главный аудитор»."""
    words = []
    for w in text.split():
        clean = re.sub(r"[^\wЁё-]", "", w)
        if clean in abbrs or clean.lower() in UNIT_FORMS or (clean.isupper() and len(clean) > 1):
            break
        words.append(w)
        if len(words) >= 4:
            break
    return " ".join(words).strip(" ,.;:")


def _slug(n: int) -> str:
    return f"u{n}"


@dataclass
class Unit:
    id: str
    name: str
    short: str = ""
    type: str = "unit"
    parent_id: str | None = None
    head_title: str = ""
    origin: str = "document"
    evidence: list[dict[str, Any]] = field(default_factory=list)
    functions: list[dict[str, Any]] = field(default_factory=list)
    positions: list[dict[str, Any]] = field(default_factory=list)
    aliases: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "short": self.short,
            "type": self.type,
            "parent_id": self.parent_id,
            "head_title": self.head_title,
            "origin": self.origin,
            # сначала пункты документов, затем строки таблиц и блоки схем
            "evidence": sorted(self.evidence, key=lambda e: 0 if str(e.get("ref_display", "")).startswith(("п.", "пп.")) else 1)[:6],
            "functions": self.functions,
            "positions": self.positions,
        }


class SideBuilder:
    """Строит оргструктуру одной стороны (до/после) по набору разобранных документов."""

    def __init__(self, side: str, documents: list[dict[str, Any]], function_kinds: list[str]) -> None:
        self.side = side
        self.documents = documents
        self.function_kinds = set(function_kinds)
        self.units: dict[str, Unit] = {}
        self.abbr: dict[str, dict[str, Any]] = {}
        self.main_units: dict[int, str] = {}
        self.unassigned: list[dict[str, Any]] = []
        self.subordination: list[dict[str, Any]] = []
        self.warnings: list[str] = []
        self._counter = 0
        for d in documents:
            for k, v in ((d.get("parsed") or {}).get("abbreviations") or {}).items():
                if k not in self.abbr or (v.get("is_unit") and not self.abbr[k].get("is_unit")):
                    self.abbr[k] = v

    # ------------------------------------------------------------ helpers

    def _ev(self, doc: dict[str, Any], clause: dict[str, Any]) -> dict[str, Any]:
        return {
            "side": self.side,
            "doc_id": doc["id"],
            "doc_title": doc.get("title") or doc.get("filename"),
            "filename": doc.get("filename"),
            "clause_id": clause.get("id"),
            "ref": clause.get("ref"),
            "ref_display": clause.get("ref_display"),
            "page": clause.get("page"),
            "text": clause.get("text", ""),
        }

    def _new_unit(self, name: str, short: str = "", origin: str = "document") -> Unit:
        self._counter += 1
        u = Unit(id=_slug(self._counter), name=name, short=short, type=unit_type_of(name), origin=origin)
        u.aliases.add(normalize(name))
        if short:
            u.aliases.add(short.lower())
        self.units[u.id] = u
        return u

    def find_unit(self, mention: str, min_sim: float = 0.82) -> Unit | None:
        if not mention:
            return None
        m = mention.strip()
        # 1) сокращение целиком
        for u in self.units.values():
            if u.short and re.search(rf"(?<![\wЁё]){re.escape(u.short)}(?![\wЁё])", m):
                return u
        # 2) похожее название
        nm = normalize(to_nominative(m))
        best, best_sim = None, 0.0
        for u in self.units.values():
            for alias in u.aliases | {normalize(u.name)}:
                if len(alias) < 4:
                    continue
                sim = unit_name_similarity(nm, alias)
                if sim > best_sim:
                    best, best_sim = u, sim
        return best if best_sim >= min_sim else None

    def get_or_create(self, name: str, short: str = "", origin: str = "document") -> Unit:
        name = to_nominative(name)
        if short and short in self.abbr and self.abbr[short].get("is_unit"):
            name = to_nominative(self.abbr[short]["full"])
        existing = None
        if short:
            existing = next((u for u in self.units.values() if u.short == short), None)
        existing = existing or self.find_unit(name, min_sim=0.9)
        if existing:
            if short and not existing.short:
                existing.short = short
                existing.aliases.add(short.lower())
            if len(name) > len(existing.name) and unit_name_similarity(name, existing.name) > 0.9:
                existing.name = name
            return existing
        return self._new_unit(name, short, origin)

    def _mentioned_abbrs(self, text: str) -> list[str]:
        out = []
        for abbr, info in self.abbr.items():
            if info.get("is_unit") and re.search(rf"(?<![\wЁё]){re.escape(abbr)}(?![\wЁё])", text):
                out.append(abbr)
        return out

    def resolve_actor(self, actor: str, doc_id: int, allow_create: bool = True,
                      allowed_types: set[str] | None = None) -> list[tuple[Unit, bool]]:
        """Субъект пункта → подразделения. bool — «общая норма» для нескольких подразделений."""
        if not actor:
            return []
        a = actor.strip()
        found: list[tuple[Unit, bool]] = []
        abbrs = self._mentioned_abbrs(a)
        for ab in abbrs:
            u = next((x for x in self.units.values() if x.short == ab), None)
            if u:
                found.append((u, len(abbrs) > 1))
        low = a.lower()
        generic_types = [t for w, t in PLURAL_GENERIC.items() if re.search(rf"\b{w}\b", low)]
        if generic_types:
            main = self.main_units.get(doc_id)
            for u in self.units.values():
                if u.id == main:
                    continue
                if any(t is None or u.type == t for t in generic_types) and all(u.id != f.id for f, _ in found):
                    found.append((u, True))
            return [(u, True) for u, _ in found]
        if found:
            return found
        remainder = ROLE_WORDS.sub("", a).strip()
        role_only = not remainder or HEAD_ROLE_RE.match(a) is not None
        if remainder:
            u = self.find_unit(remainder)
            if u:
                return [(u, False)]
            if (
                allow_create
                and starts_with_unit(remainder)
                and len(remainder.split()) >= 2
                and (allowed_types is None or unit_type_of(to_nominative(remainder)) in allowed_types)
            ):
                u = self.get_or_create(remainder)
                main = self.main_units.get(doc_id)
                if main and u.id != main and u.parent_id is None:
                    u.parent_id = main
                return [(u, False)]
        if role_only or re.match(r"^главн", low):
            main = self.main_units.get(doc_id)
            if main:
                return [(self.units[main], False)]
        return []

    # ------------------------------------------------------------ шаги

    def _collect_defined_units(self) -> None:
        for doc in self.documents:
            parsed = doc.get("parsed") or {}
            clauses = parsed.get("clauses") or []
            for abbr, info in (parsed.get("abbreviations") or {}).items():
                if not info.get("is_unit"):
                    continue
                u = self.get_or_create(info["full"], abbr)
                for c in clauses:
                    if re.search(rf"\((?:далее\s*[-–—]?\s*)?{re.escape(abbr)}\)", c.get("text", "")):
                        u.evidence.append(self._ev(doc, c))
                        break
            # табличные реестры
            for rec in parsed.get("records") or []:
                if rec.get("unit"):
                    u = self.get_or_create(rec["unit"], origin="table")
                    clause = next((c for c in clauses if c["id"] == rec.get("clause_id")), None)
                    if clause and len(u.evidence) < 3:
                        u.evidence.append(self._ev(doc, clause))
                    if rec.get("parent"):
                        p = self.get_or_create(rec["parent"], origin="table")
                        if p.id != u.id:
                            u.parent_id = p.id
                    if rec.get("position"):
                        u.positions.append({"title": rec["position"], "count": rec.get("count"),
                                            "source": clause and self._ev(doc, clause)})
                    if rec.get("head") and not u.head_title:
                        u.head_title = rec["head"]
            # распознанная схема
            chart = parsed.get("orgchart") or {}
            id_map: dict[str, Unit] = {}
            for cu in chart.get("units") or []:
                u = self.get_or_create(cu["name"], origin="orgchart")
                id_map[cu["id"]] = u
                clause = next((c for c in clauses if c["id"] == cu.get("clause_id")), None)
                if clause:
                    u.evidence.append(self._ev(doc, clause))
            for cu in chart.get("units") or []:
                if cu.get("parent_id") and cu["parent_id"] in id_map and cu["id"] in id_map:
                    child, parent = id_map[cu["id"]], id_map[cu["parent_id"]]
                    if child.id != parent.id:
                        child.parent_id = parent.id

    def _detect_main_units(self) -> None:
        for doc in self.documents:
            parsed = doc.get("parsed") or {}
            if parsed.get("records") or parsed.get("orgchart"):
                continue
            title = parsed.get("title") or doc.get("title") or ""
            clauses = parsed.get("clauses") or []
            m = TITLE_UNIT_RE.search(title.replace("\n", " "))
            main: Unit | None = None
            if m:
                rest = m.group(1).strip()
                if starts_with_unit(rest):
                    abbrs = self._mentioned_abbrs(rest)
                    main = self.get_or_create(rest, abbrs[0] if abbrs else "")
                    if clauses and not main.evidence:
                        main.evidence.append({**self._ev(doc, clauses[0]), "text": title, "ref_display": "заголовок"})
            if main is None:
                # подразделение, определённое в документе, наиболее близкое к заголовку и чаще упоминаемое
                title_stems = set(tokens(title))
                full_text = " ".join(c.get("text", "") for c in clauses[:400])
                best, best_score = None, 0.0
                for abbr, info in (parsed.get("abbreviations") or {}).items():
                    if not info.get("is_unit"):
                        continue
                    u = next((x for x in self.units.values() if x.short == abbr), None)
                    if not u:
                        continue
                    overlap = len(title_stems & set(tokens(u.name)))
                    mentions = len(re.findall(rf"(?<![\wЁё]){re.escape(abbr)}(?![\wЁё])", full_text))
                    score = overlap * 20 + mentions
                    if score > best_score:
                        best, best_score = u, score
                main = best
            if main is not None:
                self.main_units[doc["id"]] = main.id

    def _collect_composition_and_subordination(self) -> None:
        for doc in self.documents:
            parsed = doc.get("parsed") or {}
            clauses = parsed.get("clauses") or []
            children_of: dict[str, list[dict[str, Any]]] = {}
            for c in clauses:
                if c.get("parent"):
                    children_of.setdefault(c["parent"], []).append(c)
            main_id = self.main_units.get(doc["id"])
            for c in clauses:
                text = c.get("text", "")
                if not text.rstrip().endswith(":"):
                    continue
                items = [x for x in children_of.get(c["id"], []) if x["ref"].count(".") >= c["ref"].count(".")]
                if not items:
                    continue
                if COMPOSITION_RE.search(text) and not SUBORDINATION_RE.search(text):
                    subject = re.split(COMPOSITION_RE, text)[0].strip()
                    owner = self.find_unit(subject) or (self.units.get(main_id) if main_id else None)
                    for it in items:
                        itext = it.get("text", "")
                        if not starts_with_unit(itext):
                            continue
                        abbrs = self._mentioned_abbrs(itext)
                        u = self.get_or_create(itext, abbrs[0] if abbrs else "")
                        u.evidence.insert(0, self._ev(doc, it))
                        if owner and owner.id != u.id:
                            u.parent_id = owner.id
                elif SUBORDINATION_RE.search(text):
                    manager_text = re.split(SUBORDINATION_RE, text)[0].strip()
                    functional = bool(re.search(r"функционально", text, re.I))
                    manager_nom = _dative_to_nominative(manager_text)
                    managers = self.resolve_actor(manager_nom, doc["id"])
                    if not managers:
                        continue
                    manager = managers[0][0]
                    if not manager.head_title:
                        manager.head_title = role_title(manager_nom, list(self.abbr))
                    allowed = None if manager.id == main_id else SUBUNIT_TYPES
                    for it in items:
                        title = it.get("text", "").strip().rstrip(".;")
                        sub = self.resolve_actor(title, doc["id"], allowed_types=allowed)
                        target = sub[0][0] if sub else None
                        abbrs = self._mentioned_abbrs(title)
                        is_head_of_unit = bool(target) and re.match(r"^(директор|руководител|начальник)\w*\s", title, re.I) \
                            and target.id != manager.id and (abbrs or unit_type_of(ROLE_WORDS.sub("", title)) != "unit")
                        ev = self._ev(doc, it)
                        if is_head_of_unit and target is not None and not functional:
                            if target.parent_id is None or target.parent_id == main_id:
                                target.parent_id = manager.id if target.id != manager.id else target.parent_id
                            if not target.head_title:
                                target.head_title = role_title(title, list(self.abbr))
                            target.evidence.append(ev)
                            continue
                        home = target if (target and abbrs) else manager
                        pos = {"title": title, "manager_unit_id": manager.id, "home_unit_id": home.id,
                               "functional": functional, "source": ev}
                        manager.positions.append(pos)
                        self.subordination.append(pos)

    def _collect_functions(self) -> None:
        for doc in self.documents:
            parsed = doc.get("parsed") or {}
            clauses = parsed.get("clauses") or []
            by_id = {c["id"]: c for c in clauses}
            main_id = self.main_units.get(doc["id"])
            for c in clauses:
                kind = c.get("kind")
                text = (c.get("text") or "").strip()
                if kind not in self.function_kinds or c.get("is_heading"):
                    continue
                if len(text.split()) < 2:
                    continue
                if text.endswith(":") and (ROLE_START(text) or INTRO_RE.search(text)):
                    continue  # заголовок-роль («Директор ДНМ:») или вводная фраза перечня, не функция
                actor = c.get("actor") or ""
                targets = self.resolve_actor(actor, doc["id"]) if actor else []
                if len(targets) == 1 and not targets[0][0].head_title and ROLE_WORDS.match(actor) \
                        and not re.match(r"^(работник|сотрудник)", actor, re.I):
                    targets[0][0].head_title = role_title(actor, list(self.abbr))
                if not targets and not actor and main_id:
                    targets = [(self.units[main_id], False)]
                if not targets and c.get("extra", {}).get("unit"):
                    targets = [(self.get_or_create(c["extra"]["unit"], origin="table"), False)]
                match_text = text
                if len(text.split()) < 7 and c.get("parent") and c["parent"] in by_id:
                    parent_text = by_id[c["parent"]].get("text", "").rstrip(":").strip()
                    match_text = f"{parent_text}: {text}"
                fn = {
                    "id": f"{doc['id']}:{c['id']}",
                    "doc_id": doc["id"],
                    "clause_id": c["id"],
                    "ref": c.get("ref"),
                    "ref_display": c.get("ref_display"),
                    "page": c.get("page"),
                    "text": text,
                    "match_text": match_text,
                    "kind": kind,
                    "actor": actor,
                    "parent_clause": c.get("parent"),
                    "shared": False,
                }
                if not targets:
                    self.unassigned.append(fn)
                    continue
                for u, shared in targets:
                    u.functions.append({**fn, "shared": shared or len(targets) > 1})

    def _attach_orphans(self) -> None:
        # подразделения без родителя, определённые в документе с «главным» подразделением
        for doc_id, main_id in self.main_units.items():
            for u in self.units.values():
                if u.id == main_id or u.parent_id:
                    continue
                if any(ev.get("doc_id") == doc_id for ev in u.evidence) and u.type not in ("committee",):
                    u.parent_id = main_id
        # защита от циклов
        for u in self.units.values():
            seen = {u.id}
            cur = u
            while cur.parent_id:
                if cur.parent_id in seen or cur.parent_id not in self.units:
                    cur.parent_id = None
                    break
                seen.add(cur.parent_id)
                cur = self.units[cur.parent_id]

    def _prune(self) -> None:
        # «Подразделение» без функций, должностей и детей, созданное из случайного упоминания
        referenced = {u.parent_id for u in self.units.values() if u.parent_id}
        for uid in list(self.units):
            u = self.units[uid]
            if u.type == "committee" and not u.functions:
                del self.units[uid]
                continue
            if not u.functions and not u.positions and uid not in referenced and not u.evidence:
                del self.units[uid]

    def _collect_coi_mentions(self) -> list[dict[str, Any]]:
        from .conflicts import COI_MENTION_RE

        out = []
        for doc in self.documents:
            for c in (doc.get("parsed") or {}).get("clauses") or []:
                if c.get("kind") in ("toc", "definition"):
                    continue
                if COI_MENTION_RE.search(c.get("text", "")):
                    out.append(self._ev(doc, c))
        return out

    def build(self) -> dict[str, Any]:
        self._collect_defined_units()
        self._detect_main_units()
        self._collect_composition_and_subordination()
        self._collect_functions()
        self._attach_orphans()
        self._prune()
        units = [u.to_dict() for u in self.units.values()]
        return {
            "side": self.side,
            "units": units,
            "unassigned": self.unassigned,
            "subordination": self.subordination,
            "main_units": {str(k): v for k, v in self.main_units.items()},
            "coi_mentions": self._collect_coi_mentions(),
            "abbreviations": self.abbr,
            "stats": {
                "units": len(units),
                "functions": sum(len(u["functions"]) for u in units),
                "unassigned": len(self.unassigned),
            },
        }


def ROLE_START(text: str) -> bool:  # noqa: N802 - короткий предикат
    return bool(re.match(
        r"^(главн\w+|директор\w*|руководител\w+|начальник\w*|заместител\w+|менеджер\w*|работник\w*|"
        r"сотрудник\w*|департамент\w*|управлени\w+|отдел\w*|служб\w+|блок\w*)\b", text.strip(), re.I))


_DATIVE = [
    (r"^Главному\s+(\w+?)у\b", r"Главный \1"),
    (r"^Директору\b", "Директор"),
    (r"^Руководителю\b", "Руководитель"),
    (r"^Начальнику\b", "Начальник"),
    (r"^Заместителю\b", "Заместитель"),
    (r"^Председателю\b", "Председатель"),
    (r"^Директорам\b", "Директоры"),
]


def _dative_to_nominative(text: str) -> str:
    t = text.strip()
    for pat, rep in _DATIVE:
        t = re.sub(pat, rep, t, flags=re.I)
    t = re.sub(r"\s+(работники|сотрудники)\b.*$", "", t, flags=re.I)
    return t.strip()


def build_structure(side: str, documents: list[dict[str, Any]], function_kinds: list[str]) -> dict[str, Any]:
    return SideBuilder(side, documents, function_kinds).build()
