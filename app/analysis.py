"""Transparent structural comparison. No document-specific result fixtures."""
from collections import Counter, defaultdict
from difflib import SequenceMatcher
import math
import re

from .models import Clause, Document
from .parsers import modality

LABELS = {
    "missing": "Не найдена", "transferred": "Изменён исполнитель",
    "modified": "Изменено содержание", "modality": "Изменена обязательность",
    "added": "Добавлено", "unchanged": "Сохранено", "editorial": "Редакционная правка",
    "renumbered": "Перенумеровано", "unit_added": "Новое подразделение",
    "unit_removed": "Подразделение не найдено", "overlap": "Возможное пересечение",
    "conflict": "Возможный конфликт", "safeguard": "Меры независимости",
}
STOP = set("и в во на по с со к ко о об от для при из за до не но а также как что это или его ее их который которых рамках том числе соответствии настоящего положения общества бва деятельности функций части целях своего своих the a of to and in for".split())
SUFFIX = re.compile(r"(иями|ями|ами|ого|ему|ыми|ими|иям|ием|иях|ах|ях|ов|ев|ий|ый|ой|ая|яя|ое|ее|ые|ие|ам|ям|ом|ем|ию|ия|а|я|ы|и|у|ю|е|о)$")


def content(text):
    return re.sub(r"^(?:\d+(?:\.\d+)*[.)]?|[а-яa-z][.)])\s*", "", text, flags=re.I).strip()


def normalize(text):
    return " ".join(re.findall(r"[а-яәіңғүұқөһa-z0-9]+", content(text).lower().replace("ё", "е")))


def tokens(text):
    return {SUFFIX.sub("", t) if len(t) > 5 else t for t in normalize(text).split() if t not in STOP and len(t) > 2}


def short(text, limit=100):
    text = content(text).strip(" :;.")
    return (text[:limit].rsplit(" ", 1)[0] + "…") if len(text) > limit else text


def source(clause, all_clauses):
    if clause is None:
        return []
    result = [clause.id]
    # Include both the list preamble and the exact role declaration as evidence.
    for cid in [clause.parent_id, clause.actor_source]:
        if cid and cid in all_clauses and cid not in result:
            result.append(cid)
    return result


def same_actor(a, b):
    if not a or not b:
        return True  # Unknown ownership is never treated as proven transfer.
    return normalize(a) == normalize(b) or tokens(a) == tokens(b)


class Matcher:
    def __init__(self, clauses):
        self.clauses = clauses
        self.termsets = [tokens(c.text) for c in clauses]
        self.index = defaultdict(set)
        for idx, ts in enumerate(self.termsets):
            for token in ts:
                self.index[token].add(idx)
        n = max(1, len(clauses))
        self.idf = {t: math.log(1 + n / len(ids)) for t, ids in self.index.items()}

    def candidates(self, clause, limit=28):
        counts = Counter()
        for term in tokens(clause.text):
            for idx in self.index.get(term, []):
                counts[idx] += self.idf.get(term, 1)
        return [idx for idx, _ in counts.most_common(limit)]

    def score(self, clause, idx):
        a, b = tokens(clause.text), self.termsets[idx]
        if not a or not b:
            return 0.0
        intersect = a & b
        weighted = sum(self.idf.get(t, 1) for t in intersect)
        total = sum(self.idf.get(t, 1) for t in a | b)
        jaccard = weighted / total if total else 0
        sequence = SequenceMatcher(None, normalize(clause.text), normalize(self.clauses[idx].text), autojunk=False).ratio()
        contain = len(intersect) / max(1, min(len(a), len(b)))
        return 0.52 * jaccard + 0.35 * sequence + 0.13 * contain


def analyze(documents: list[Document], progress=None):
    progress = progress or (lambda *_: None)
    all_clauses = {c.id: c for doc in documents for c in doc.clauses}
    before = [c for doc in documents if doc.side == "before" for c in doc.clauses if c.kind == "function"]
    after = [c for doc in documents if doc.side == "after" for c in doc.clauses if c.kind == "function"]
    if len(before) + len(after) > 6000:
        raise ValueError("В комплекте слишком много функций для одного анализа. Разделите сравнение по подразделениям (до 6000 фрагментов).")
    matcher = Matcher(after)
    exact = defaultdict(list)
    for idx, clause in enumerate(after):
        exact[normalize(clause.text)].append(idx)
    paired, used = {}, set()
    # First reserve exact matches, preferring same scope. This prevents a generic
    # duplicated clause from stealing a match from the actual predecessor.
    for i, clause in enumerate(before):
        options = [j for j in exact.get(normalize(clause.text), []) if j not in used]
        if options:
            j = max(options, key=lambda idx: 3 * (clause.number == after[idx].number) + 2 * same_actor(clause.actor, after[idx].actor) + (clause.section == after[idx].section))
            paired[i] = (j, 1.0)
            used.add(j)
    progress(46, "Сопоставляем функции и исполнителей")
    candidates = []
    closest = {}
    for i, clause in enumerate(before):
        if i in paired:
            continue
        scores = [(matcher.score(clause, j), j) for j in matcher.candidates(clause)]
        scores.sort(reverse=True)
        if scores:
            closest[i] = scores[0]
        for score, j in scores[:6]:
            if j not in used and score >= 0.65:
                priority = score + 0.025 * same_actor(clause.actor, after[j].actor) + 0.015 * (clause.section == after[j].section)
                candidates.append((priority, score, i, j))
    for _, score, i, j in sorted(candidates, reverse=True):
        if i not in paired and j not in used:
            paired[i] = (j, score)
            used.add(j)
    # Consolidation: several old role-specific duties can become one common
    # duty. Reusing a strong correspondence preserves this evidence for review.
    for i, old in enumerate(before):
        if i in paired:
            continue
        options = [(matcher.score(old, j), j) for j in matcher.candidates(old)]
        if options:
            score, j = max(options)
            if score >= .9:
                paired[i] = (j, score)
                used.add(j)
    # A list preamble is covered when its children were transferred together.
    # Permit many-to-one alignment: a new paragraph can combine old duties.
    after_by_id = {c.id: j for j, c in enumerate(after)}
    children = defaultdict(list)
    for i, c in enumerate(before):
        if c.parent_id:
            children[c.parent_id].append(i)
    for i, old in enumerate(before):
        child_indices = children.get(old.id, [])
        if i in paired or not child_indices or not all(k in paired for k in child_indices):
            continue
        new_parents = {after[paired[k][0]].parent_id for k in child_indices}
        if len(new_parents) == 1 and next(iter(new_parents)) in after_by_id:
            j = after_by_id[next(iter(new_parents))]
            paired[i] = (j, min(paired[k][1] for k in child_indices))
            used.add(j)
    findings, matrix = [], []

    def add(kind, title, description, old=None, new=None, severity="info", score=1.0, **extra):
        finding = {
            "id": f"f{len(findings) + 1}", "kind": kind, "label": LABELS[kind],
            "title": title, "description": description, "severity": severity,
            "score": round(score, 3), "before_ids": source(old, all_clauses),
            "after_ids": source(new, all_clauses), "review": "pending", "comment": "",
            "recommendation": "Проверьте изменение и подтвердите вывод по указанным пунктам.",
            **extra,
        }
        findings.append(finding)
        return finding

    def classify(old, new, score):
        old_body, new_body = content(old.text), content(new.text)
        if modality(old_body) != modality(new_body):
            return "modality"
        if bool(re.search(r"\bне\b", old_body, re.I)) != bool(re.search(r"\bне\b", new_body, re.I)):
            return "modified"
        if not same_actor(old.actor, new.actor) and score >= 0.82:
            return "transferred"
        if old_body == new_body:
            return "unchanged" if old.number == new.number else "renumbered"
        if normalize(old.text) == normalize(new.text) or score >= 0.95:
            return "editorial"
        return "modified"

    incomplete = any("без читаемого" in w or "не распознан" in w for d in documents if d.side == "after" for w in d.warnings)
    for i, old in enumerate(before):
        new, score, candidate_id = None, 0.0, ""
        if i in paired:
            j, score = paired[i]
            new = after[j]
            kind = classify(old, new, score)
        else:
            kind = "missing"
            if i in closest and closest[i][0] >= 0.32:
                candidate_score, j = closest[i]
                candidate_id = after[j].id
        row = {"id": f"m{len(matrix) + 1}", "kind": kind, "label": LABELS[kind], "before_ids": source(old, all_clauses), "after_ids": source(new, all_clauses), "candidate_id": candidate_id, "score": round(score, 3), "finding_id": ""}
        if kind == "missing":
            message = "Явное соответствие не найдено в загруженном комплекте «после». Это кандидат на потерю, а не доказательство отмены функции."
            if incomplete:
                message += " Часть материалов не распознана полностью — сначала проверьте полноту комплекта."
            finding = add(kind, short(old.text), message, old, severity="high", score=0.5, candidate_id=candidate_id,
                          recommendation="Уточните нового исполнителя, проверьте смежные положения и полноту комплекта документов.")
        elif kind == "transferred":
            finding = add(kind, short(old.text), f"Содержание сохранено или близко по смыслу, но изменён круг исполнителей: «{old.actor}» → «{new.actor}». Сопоставление требует проверки области ответственности.", old, new, "medium", score,
                          recommendation="Подтвердите передачу полномочия и уточните границы ответственности каждого исполнителя.")
        elif kind == "modality":
            names = {"permission": "возможность / право", "required": "обязанность", "forbidden": "запрет", "statement": "прямое предписание"}
            finding = add(kind, "Изменено условие выполнения: " + short(old.text, 75), f"Формулировка изменилась: {names[old.modality]} → {names[new.modality]}. Проверьте, меняется ли обязательность выполнения действия.", old, new, "high", score)
        elif kind == "modified":
            finding = add(kind, short(new.text), "Найден близкий пункт с изменённым содержанием. Сравните действие, объект, сроки и условия выполнения в двух редакциях.", old, new, "medium", score)
        elif kind == "editorial":
            finding = add(kind, short(new.text), "Формулировки близки. Вероятна редакционная правка; небольшое изменение слов всё же может менять смысл.", old, new, "low", score)
        else:
            finding = None
        if finding:
            row["finding_id"] = finding["id"]
        matrix.append(row)
    for j, new in enumerate(after):
        if j in used:
            continue
        f = add("added", short(new.text), "Пункт появился в комплекте «после»; явный предшественник в загруженных документах не найден. Возможны детализация или объединение прежних функций.", new=new, score=0.65)
        matrix.append({"id": f"m{len(matrix) + 1}", "kind": "added", "label": LABELS["added"], "before_ids": [], "after_ids": source(new, all_clauses), "score": 0.65, "finding_id": f["id"], "candidate_id": ""})
    progress(66, "Проверяем структуру и пересечения")
    units = {}
    for side in ["before", "after"]:
        unique = {}
        for doc in documents:
            if doc.side != side:
                continue
            for clause in doc.clauses:
                if clause.kind == "unit":
                    key = normalize(clause.text)
                    unique.setdefault(key, clause)
        units[side] = unique
    structure = []
    for key in sorted(set(units["before"]) | set(units["after"])):
        old, new = units["before"].get(key), units["after"].get(key)
        status = "retained" if old and new else "added" if new else "missing"
        structure.append({"name": content((new or old).text).rstrip("."), "status": status, "before_ids": source(old, all_clauses), "after_ids": source(new, all_clauses)})
        if status == "added":
            add("unit_added", short(new.text, 130), "Подразделение явно перечислено в новой структуре. Совпадающее название в прежнем перечне не найдено; возможное переименование необходимо проверить.", new=new)
        elif status == "missing":
            add("unit_removed", short(old.text, 130), "Подразделение не найдено под прежним названием. Возможны переименование, объединение или исключение из структуры.", old=old, severity="medium")
    # Shared boilerplate is not sufficient evidence of duplicate ownership.
    overlaps = set()
    for i, a in enumerate(after):
        if not a.actor or len(tokens(a.text)) < 8:
            continue
        if re.search(r"прочих поручений|предложения для включения в план|запрашив|запрашивает|профессионального уровня", a.text, re.I):
            continue
        for j in matcher.candidates(a, 8):
            if j <= i or len(overlaps) >= 15:
                continue
            b = after[j]
            if not b.actor or same_actor(a.actor, b.actor):
                continue
            # A general rule inherited by the same specific role is not a second owner.
            if any("директоры департаментов" in x.lower() for x in [a.actor, b.actor]):
                continue
            score = matcher.score(a, j)
            if score >= 0.9:
                pair = tuple(sorted((a.id, b.id)))
                if pair not in overlaps:
                    overlaps.add(pair)
                    f = add("overlap", "Пересечение полномочий: " + short(a.text, 72), f"Близкая функция закреплена за «{a.actor}» и «{b.actor}». Общий текст не доказывает дублирование: проверьте объекты, территорию и разделение ролей.", new=a, severity="medium", score=score,
                            recommendation="Уточните, кто исполняет, согласует и контролирует функцию, и зафиксируйте границы ответственности.")
                    f["after_ids"] = list(dict.fromkeys(source(a, all_clauses) + source(b, all_clauses)))
    # Show explicit independence conditions as documented safeguards, not incidents.
    for doc in documents:
        if doc.side != "after":
            continue
        for c in doc.clauses:
            low = c.text.lower()
            if "конфликт" in low and ("независим" in low or "совмещен" in low) and len(low) > 250:
                add("safeguard", "Условия независимости и совмещения ролей", "Документ описывает потенциальный конфликт и/или меры его предотвращения. Наличие такой нормы само по себе не означает фактического конфликта.", new=c, severity="info",
                    recommendation="Проверьте выполнение предусмотренных документом мер: раскрытие совмещения, независимость и заявления о конфликте интересов.")
    # A conservative self-review rule: same actor, same subject, execution + audit.
    for a in after:
        if not a.actor or not re.search(r"\b(?:утверждает|осуществляет закупки|заключает договоры)\b", a.text, re.I):
            continue
        for j in matcher.candidates(a, 8):
            b = after[j]
            if a.id == b.id or not b.actor or not same_actor(a.actor, b.actor):
                continue
            if re.search(r"независим\w* провер|аудит\w* провер|проверяет|оценивает эффективность", b.text, re.I):
                common = tokens(a.text) & tokens(b.text)
                if len(common) >= 3 and len(common) / max(1, min(len(tokens(a.text)), len(tokens(b.text)))) >= 0.5:
                    f = add("conflict", "Возможная проверка собственной работы", f"У «{a.actor}» обнаружены действия по исполнению или утверждению и проверке близкого объекта. Это проверочная гипотеза по правилу разделения ролей.", new=a, severity="high", score=0.6)
                    f["after_ids"] = list(dict.fromkeys(source(a, all_clauses) + source(b, all_clauses)))
                    break
    progress(82, "Формируем заключение и проверяем источники")
    for f in findings:
        if not f["before_ids"] and not f["after_ids"]:
            raise RuntimeError("Найден вывод без подтверждающих источников")
        if any(cid not in all_clauses for cid in f["before_ids"] + f["after_ids"]):
            raise RuntimeError("Повреждена ссылка на источник")
    counts = Counter(f["kind"] for f in findings)
    stats = {
        "before_functions": len(before), "after_functions": len(after),
        "matched": len(paired), "unchanged": sum(m["kind"] in {"unchanged", "renumbered", "editorial"} for m in matrix),
        "findings": len(findings), "attention": sum(f["severity"] in {"high", "medium"} for f in findings),
        "structure_changes": sum(s["status"] != "retained" for s in structure),
        "counts": dict(counts), "source_count": len(documents),
        "coverage": round(100 * len(paired) / max(1, len(before))),
    }
    return {"documents": [d.to_dict() for d in documents], "findings": findings, "matrix": matrix, "structure": structure, "stats": stats,
            "method": "structural", "ai": {"status": "disabled", "reviewed": 0},
            "limitations": ["Выводы относятся только к загруженному комплекту документов.", "Структурный анализ использует формулировки и контекст; смысловые перефразирования могут потребовать проверки.", "Оценка сходства не является вероятностью истинности вывода."]}
