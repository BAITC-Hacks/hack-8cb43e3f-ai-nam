"""Выявление потенциальных конфликтов интересов.

1. Несовместимые функции в одном подразделении (матрица разделения обязанностей, SoD):
   выполнение ↔ контроль, методология ↔ оценка соблюдения, консультирование ↔ проверка
   (Стандарт IIA 1130), подготовка ↔ утверждение, учёт ↔ хранение/распоряжение активами.
   Конфликт фиксируется, только если у функций общий объект (пересечение значимых основ слов).
2. Двойное (функциональное) подчинение работников разным руководителям.
3. Прямые упоминания конфликта интересов / совмещения в документах.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from .text import is_generic, normalize, short, stem

if TYPE_CHECKING:  # pragma: no cover
    from .compare import Comparator

CATEGORIES: dict[str, re.Pattern[str]] = {
    "consult": re.compile(r"консультир\w*|консультаци[июей]\w*|содействи\w*|содейству\w*"),
    "methodology": re.compile(r"методолог\w*|методическ\w*|актуализ\w*"),
    "develop": re.compile(r"разрабатыва\w*|разработк\w*"),
    "approve": re.compile(r"утвержда\w*|утверждени\w*|согласовыва\w*|согласовани\w*|одобря\w*|одобрени\w*|"
                          r"визиру\w*|санкционир\w*|авторизац\w*"),
    "plan": re.compile(r"планир\w*|формировани\w* план\w*|формиру\w* план\w*"),
    "record": re.compile(r"\bучет\w*|регистрац\w*"),
    "custody": re.compile(r"хранени\w*|сохранност\w*|распоряжени\w* (средств|имуществ|актив)\w*"),
    "control": re.compile(r"контрол\w*|провер(?:к\w*|ок|я\w*|и\w*)|\bоцен(?:к\w*|ок|ива\w*|и\w*)|мониторинг\w*|"
                          r"ревизи\w*|тестирован\w*|экспертиз\w*|аудит\w*"),
    "execute": re.compile(r"провод\w*|проведени\w*|выполня\w*|выполнени\w*|исполня\w*|администрир\w*|"
                          r"предоставлени\w*|предоставля\w*|закупк\w*|заключени\w*|внедр\w*|эксплуатац\w*|"
                          r"сопровожд\w*|осуществля\w* (закуп|платеж|операц)"),
}

RULES: list[tuple[str, str, str, str, str]] = [
    ("execute", "control", "Совмещение выполнения и контроля",
     "Подразделение одновременно выполняет действия и контролирует/оценивает их результат (самоконтроль).", "high"),
    ("develop", "control", "Разработка мер и контроль их исполнения",
     "Подразделение разрабатывает меры/документы и само же контролирует их исполнение (риск самопроверки).",
     "medium"),
    ("methodology", "control", "Оценка соблюдения собственной методологии",
     "Подразделение разрабатывает методологию/ВНД и само же оценивает их соблюдение или качество работ.",
     "medium"),
    ("consult", "control", "Консультирование и последующая проверка одного объекта",
     "Подразделение оказывает консультации по объекту и затем его проверяет — риск утраты объективности "
     "(принцип независимости, Стандарт IIA 1130).", "medium"),
    ("execute", "approve", "Исполнение и согласование одних и тех же операций",
     "Подразделение исполняет операции и само согласует/утверждает их.", "high"),
    ("plan", "approve", "Подготовка и утверждение одного документа",
     "Подразделение формирует документ (план) и утверждает его.", "medium"),
    ("record", "custody", "Учёт и распоряжение активами",
     "Подразделение ведёт учёт активов и одновременно хранит их/распоряжается ими.", "high"),
]

OBJECT_STOP = {stem(w) for w in (
    "работ", "деятельность", "вопросам", "соответствии", "рамках", "целях", "обеспечение", "организация",
    "организует", "осуществляет", "общества", "подразделений", "подразделения", "результатов", "результаты",
    "мероприятий", "материалы", "предложения", "информации", "порядке", "установленном", "зоне",
    "ответственности", "руководителями", "руководителей", "бва", "также", "всех", "уровнях",
)}

COI_MENTION_RE = re.compile(r"конфликт\w*\s+интерес\w*|\bсовмещени\w*|\bКИ\b", re.I)


LIGHT_WORDS = re.compile(
    r"^(организу\w*|организаци\w*|осуществля\w*|осуществлени\w*|обеспечива\w*|обеспечени\w*|участву\w*|"
    r"участи\w*|проведени\w*|провод\w*|непрерывн\w*|периодическ\w*|постоянн\w*|систематическ\w*|"
    r"текущ\w*|регулярн\w*|в|по|и)$"
)


def _primary_and_object(text: str) -> tuple[str | None, set[str]]:
    """Основное действие пункта (категория SoD) и его объект.

    Действие определяется по первому «значимому» слову: служебные глаголы
    («организует», «осуществляет», «проведение») пропускаются.
    """
    words = re.findall(r"[a-zа-яёәғқңөұүһі0-9-]+", normalize(text))
    k = 0
    while k < len(words) and k < 3 and LIGHT_WORDS.match(words[k]):
        k += 1
    if k >= len(words):
        return None, set()
    head = " ".join(words[k:k + 2])
    primary = None
    for cat, rx in CATEGORIES.items():
        m = rx.match(head)
        if m:
            primary = cat
            break
    if primary is None:
        return None, set()
    obj = set()
    for w in words[k + 1:]:
        if len(w) < 3 or any(rx.fullmatch(w) for rx in CATEGORIES.values()):
            continue
        st = stem(w)
        if len(st) > 2 and st not in OBJECT_STOP:
            obj.add(st)
    return primary, obj


def detect_conflicts(structure: dict[str, Any], cmp: Comparator, side: str, record: bool = True,
                     per_unit_limit: int = 3) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    generic = cmp.generic
    # «вездесущие» основы (встречаются в большой доле функций стороны) не характеризуют объект
    all_fns = [f for u in structure["units"] for f in u["functions"]]
    df: dict[str, int] = defaultdict(int)
    for f in all_fns:
        for st in set(_primary_and_object(f["text"])[1]):
            df[st] += 1
    n_all = max(1, len(all_fns))
    ubiquitous = {st for st, c in df.items() if c / n_all > 0.12}
    for u in structure["units"]:
        tagged = []
        for f in u["functions"]:
            if is_generic(f["text"], generic) or len(f["text"].split()) < 3:
                continue
            primary, obj = _primary_and_object(f["text"])
            obj -= ubiquitous
            if primary and obj:
                tagged.append((f, primary, obj))
        cands = []
        for i in range(len(tagged)):
            for j in range(len(tagged)):
                if i == j:
                    continue
                fi, ci, oi = tagged[i]
                fj, cj, oj = tagged[j]
                if fi.get("shared") and fj.get("shared"):
                    continue
                if fi["clause_id"] == fj["clause_id"] and fi["doc_id"] == fj["doc_id"]:
                    continue
                for a, b, title, desc, severity in RULES:
                    if (ci, cj) != (a, b):
                        continue
                    inter = oi & oj
                    union = oi | oj
                    jac = len(inter) / len(union) if union else 0.0
                    if len(inter) >= 2 and jac >= 0.15:
                        cands.append((jac, fi, fj, title, desc, severity, sorted(inter)))
        cands.sort(key=lambda x: -x[0])
        used_rules: dict[str, int] = defaultdict(int)
        taken = 0
        seen_pairs: set[frozenset[str]] = set()
        for jac, fi, fj, title, desc, severity, inter in cands:
            key = frozenset((fi["id"], fj["id"]))
            if key in seen_pairs or used_rules[title] >= 1 or taken >= per_unit_limit:
                continue
            seen_pairs.add(key)
            used_rules[title] += 1
            taken += 1
            unit_label = f"{u['name']} ({u['short']})" if u.get("short") else u["name"]
            item = {"unit": unit_label, "title": title, "score": round(jac, 3), "objects": inter,
                    "a": fi, "b": fj}
            results.append(item)
            if record:
                cmp.add_finding(
                    type="conflict",
                    subtype="sod",
                    severity=severity if jac >= 0.25 else "low" if severity == "medium" else "medium",
                    title=f"Потенциальный конфликт интересов: {title.lower()} — {unit_label}",
                    description=f"{desc} Общий объект: {', '.join(inter[:6])}. "
                                f"Функции: «{short(fi['text'], 110)}» и «{short(fj['text'], 110)}».",
                    units=[unit_label],
                    evidence=[cmp.ev(side, fi) | {"unit": unit_label}, cmp.ev(side, fj) | {"unit": unit_label}],
                    confidence=round(min(0.85, 0.45 + jac), 2),
                    score=round(jac, 3),
                )
    return results


def detect_dual_subordination(structure: dict[str, Any], cmp: Comparator, side: str,
                              record: bool = True) -> list[dict[str, Any]]:
    units = {u["id"]: u for u in structure["units"]}
    by_title: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in structure.get("subordination", []):
        key = normalize(p["title"])
        by_title[key].append(p)
    out = []
    for title, rows in by_title.items():
        managers = {r["manager_unit_id"] for r in rows}
        if len(managers) < 2:
            continue
        if not any(r.get("functional") or r["home_unit_id"] != r["manager_unit_id"] for r in rows):
            continue
        labels = []
        for mid in managers:
            mu = units.get(mid)
            if mu:
                labels.append(f"{mu['name']} ({mu['short']})" if mu.get("short") else mu["name"])
        item = {"title": rows[0]["title"], "managers": labels, "rows": rows}
        out.append(item)
        if record:
            cmp.add_finding(
                type="conflict",
                subtype="dual_subordination",
                severity="medium",
                title=f"Двойное подчинение: «{rows[0]['title']}»",
                description=(
                    f"Должность «{rows[0]['title']}» одновременно подчинена: {', '.join(labels)}"
                    + (" (в т.ч. функционально)" if any(r.get('functional') for r in rows) else "")
                    + ". Совмещение подчинённости подразделению, выполняющему проверки, и подразделению, "
                      "контролирующему их качество, создаёт риск конфликта интересов."
                ),
                units=labels,
                evidence=[r["source"] for r in rows if r.get("source")],
                confidence=0.75,
            )
    return out


def detect_declared_conflicts(structure: dict[str, Any], cmp: Comparator) -> list[dict[str, Any]]:
    mentions = structure.get("coi_mentions") or []
    if not mentions:
        return []
    cmp.add_finding(
        type="conflict",
        subtype="declared",
        severity="info",
        title="Документы содержат нормы о потенциальном конфликте интересов / совмещении",
        description="В документах «после» прямо упоминаются потенциальный конфликт интересов или совмещение "
                    "функций. Рекомендуется проверить, что по каждому случаю совмещения определён порядок "
                    "раскрытия и исключения конфликта интересов.",
        units=[],
        evidence=mentions[:6],
        confidence=0.9,
    )
    return mentions


def resolved_dual_subordination(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    after_titles = {normalize(x["title"]) for x in after}
    return [x for x in before if normalize(x["title"]) not in after_titles]


__all__ = ["detect_conflicts", "detect_dual_subordination", "detect_declared_conflicts", "COI_MENTION_RE",
           "resolved_dual_subordination"]
