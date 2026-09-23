"""Сравнение оргструктур «до» и «после»: подразделения, функции, потери, дублирование, конфликты.

Все выводы строятся детерминированно (правила + текстовое сходство) и содержат
ссылки на пункты исходных документов. ИИ-модель (если подключена) используется
отдельным шагом только для проверки пограничных случаев и формулировок.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

import numpy as np

from .conflicts import (
    detect_conflicts,
    detect_declared_conflicts,
    detect_dual_subordination,
    resolved_dual_subordination,
)
from .structure import unit_name_similarity
from .text import Similarity, content_stems, is_generic, short

UNIT_STATUS_LABELS = {
    "preserved": "сохранено",
    "renamed": "переименовано",
    "reorganized": "реорганизовано",
    "merged": "образовано слиянием",
    "split": "разделено",
    "abolished": "упразднено",
    "created": "создано",
}
FN_STATUS_LABELS = {
    "preserved": "сохранена",
    "transferred": "передана",
    "modified": "изменена",
    "lost": "утрачена",
    "relocated": "перенесена в общие положения",
    "new": "новая",
}


def _unit_label(u: dict[str, Any]) -> str:
    return f"{u['name']} ({u['short']})" if u.get("short") else u["name"]


class Comparator:
    def __init__(self, before: dict[str, Any], after: dict[str, Any], settings: dict[str, Any],
                 similarity: Similarity, doc_titles: dict[int, str]) -> None:
        self.before = before
        self.after = after
        self.s = settings
        self.sim = similarity
        self.doc_titles = doc_titles
        self.b_units = {u["id"]: u for u in before["units"]}
        self.a_units = {u["id"]: u for u in after["units"]}
        self.generic = settings.get("generic_phrases", [])
        self.findings: list[dict[str, Any]] = []
        self._fid = 0

    # ------------------------------------------------------------------ utils

    def ev(self, side: str, fn: dict[str, Any], score: float | None = None) -> dict[str, Any]:
        e = {
            "side": side,
            "doc_id": fn["doc_id"],
            "doc_title": self.doc_titles.get(fn["doc_id"], ""),
            "clause_id": fn["clause_id"],
            "ref": fn.get("ref"),
            "ref_display": fn.get("ref_display"),
            "page": fn.get("page"),
            "text": fn.get("text", ""),
        }
        if score is not None:
            e["score"] = round(float(score), 3)
        return e

    def add_finding(self, **kw: Any) -> dict[str, Any]:
        self._fid += 1
        f = {
            "id": f"F-{self._fid:03d}",
            "severity": "medium",
            "confidence": 0.7,
            "method": "rules",
            "units": [],
            "evidence": [],
            "recommendation": "",
            **kw,
        }
        self.findings.append(f)
        return f

    @staticmethod
    def _functions(structure: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """(подразделение, функция) — без дублей одной и той же функции у одного подразделения."""
        out = []
        for u in structure["units"]:
            for f in u["functions"]:
                out.append((u, f))
        return out

    # ------------------------------------------------------------------ main

    def run(self) -> dict[str, Any]:
        b_fns = self._functions(self.before)
        a_fns = self._functions(self.after)
        b_texts = [f["match_text"] for _, f in b_fns]
        a_texts = [f["match_text"] for _, f in a_fns]
        m = self.sim.matrix(b_texts, a_texts) if b_texts and a_texts else np.zeros((len(b_texts), len(a_texts)))

        unit_pairs = self._match_units_by_name()
        function_map = self._map_functions(b_fns, a_fns, m, unit_pairs)
        units = self._unit_statuses(b_fns, a_fns, m, unit_pairs, function_map)
        self._loss_findings(function_map, units)
        duplicates_after = self._duplicates(a_fns, "after")
        duplicates_before = self._duplicates(b_fns, "before", record=False)
        self._mark_new_duplicates(duplicates_after, duplicates_before, function_map)
        conflicts = detect_conflicts(self.after, self, "after")
        conflicts_before = detect_conflicts(self.before, self, "before", record=False)
        dual = detect_dual_subordination(self.after, self, "after")
        dual_before = detect_dual_subordination(self.before, self, "before", record=False)
        declared = detect_declared_conflicts(self.after, self)
        for item in resolved_dual_subordination(dual_before, dual):
            self.add_finding(
                type="improvement",
                subtype="dual_subordination_resolved",
                severity="info",
                title=f"Устранено двойное подчинение: «{item['title']}»",
                description="В предыдущей редакции должность подчинялась нескольким руководителям ("
                            + ", ".join(item["managers"]) + "). В новой редакции двойное подчинение не выявлено.",
                units=item["managers"],
                evidence=[r["source"] for r in item["rows"] if r.get("source")],
                confidence=0.7,
            )
        self._reorg_findings(units)

        summary = {
            "units_before": len(self.b_units),
            "units_after": len(self.a_units),
            "functions_before": len(b_fns),
            "functions_after": len(a_fns),
            "units_by_status": dict(Counter(u["status"] for u in units)),
            "functions_by_status": dict(Counter(x["status"] for x in function_map)),
            "lost": sum(1 for x in function_map if x["status"] == "lost"),
            "duplicates": len(duplicates_after),
            "duplicates_before": len(duplicates_before),
            "conflicts": len(conflicts) + len(dual) + len(declared),
            "conflicts_before": len(conflicts_before) + len(dual_before),
            "findings": len(self.findings),
            "embeddings": self.sim.used_embeddings,
        }
        return {
            "summary": summary,
            "units": units,
            "function_map": function_map,
            "findings": self.findings,
        }

    # ------------------------------------------------------------------ подразделения

    def _match_units_by_name(self) -> dict[str, str]:
        """Пары до→после по названию/сокращению (жадно, по убыванию сходства)."""
        cands = []
        for b in self.b_units.values():
            for a in self.a_units.values():
                if b.get("short") and b["short"] == a.get("short"):
                    sim = 1.0
                else:
                    sim = unit_name_similarity(b["name"], a["name"])
                if sim >= self.s.get("unit_name", 0.72):
                    cands.append((sim, b["id"], a["id"]))
        cands.sort(reverse=True)
        pairs: dict[str, str] = {}
        used_a: set[str] = set()
        for sim, bid, aid in cands:
            if bid in pairs or aid in used_a:
                continue
            pairs[bid] = aid
            used_a.add(aid)
        return pairs

    def _map_functions(self, b_fns, a_fns, m: np.ndarray, pairs: dict[str, str]) -> list[dict[str, Any]]:
        hi, lo = self.s.get("match_high", 0.62), self.s.get("match_low", 0.38)
        result: list[dict[str, Any]] = []
        a_best = m.max(axis=0) if m.size else np.zeros(len(a_fns))
        # функции «после», не закреплённые за подразделениями (общие положения) — для проверки переноса
        unassigned_after = self.after.get("unassigned", [])
        un_m = self.sim.matrix([f["match_text"] for _, f in b_fns], [f["match_text"] for f in unassigned_after]) \
            if unassigned_after and b_fns else None
        seen_b: set[str] = set()
        for i, (bu, bf) in enumerate(b_fns):
            key = f"{bu['id']}|{bf['id']}"
            if key in seen_b:
                continue
            seen_b.add(key)
            row = m[i] if m.size else np.array([])
            order = np.argsort(-row)[:5] if row.size else []
            cands = []
            for j in order:
                au, af = a_fns[j]
                cands.append({"unit_id": au["id"], "unit": _unit_label(au), "fn": af, "score": float(row[j])})
            # предпочитаем кандидата в «том же» подразделении при близком сходстве
            same_aid = pairs.get(bu["id"])
            best = cands[0] if cands else None
            if best and same_aid:
                same = next((c for c in cands if c["unit_id"] == same_aid), None)
                if same and same["score"] >= best["score"] - 0.08:
                    best = same
            score = best["score"] if best else 0.0
            generic = is_generic(bf["text"], self.generic)
            if best and score >= hi:
                status = "preserved" if best["unit_id"] == same_aid else "transferred"
            elif best and score >= lo:
                status = "modified"
            else:
                status = "lost"
                if un_m is not None and un_m.shape[1] and float(un_m[i].max()) >= hi:
                    status = "relocated"
            # несколько подразделений «после» с высоким сходством (общая норма)
            receivers = sorted({c["unit"] for c in cands if c["score"] >= max(hi, score - 0.05)})
            result.append({
                "id": f"M-{len(result) + 1:03d}",
                "status": status,
                "score": round(score, 3),
                "generic": generic,
                "shared": bf.get("shared", False),
                "before": {"unit_id": bu["id"], "unit": _unit_label(bu), "pair_unit_id": same_aid,
                           **self.ev("before", bf)},
                "after": [
                    {"unit_id": c["unit_id"], "unit": c["unit"], **self.ev("after", c["fn"], c["score"])}
                    for c in cands[:3]
                    if c["score"] >= lo * 0.8
                ],
                "receivers": receivers if status in ("preserved", "transferred") else [],
                "verified": None,
            })
        # новые функции (без аналогов «до»)
        seen_a: set[str] = set()
        for j, (au, af) in enumerate(a_fns):
            if af["id"] in seen_a:
                continue
            if a_best.size and float(a_best[j]) >= lo:
                continue
            seen_a.add(af["id"])
            result.append({
                "id": f"M-{len(result) + 1:03d}",
                "status": "new",
                "score": round(float(a_best[j]) if a_best.size else 0.0, 3),
                "generic": is_generic(af["text"], self.generic),
                "shared": af.get("shared", False),
                "before": None,
                "after": [{"unit_id": au["id"], "unit": _unit_label(au), **self.ev("after", af)}],
                "receivers": [],
                "verified": None,
            })
        return result

    def _unit_statuses(self, b_fns, a_fns, m, pairs, fmap) -> list[dict[str, Any]]:
        units: list[dict[str, Any]] = []
        # распределение функций каждого подразделения «до» по подразделениям «после»
        dist: dict[str, Counter] = defaultdict(Counter)
        lost_by_unit: Counter = Counter()
        total_by_unit: Counter = Counter()
        for row in fmap:
            if row["before"] is None or row["generic"]:
                continue
            bid = row["before"]["unit_id"]
            total_by_unit[bid] += 1
            if row["status"] in ("preserved", "transferred", "modified") and row["after"]:
                # общая норма для нескольких подразделений засчитывается каждому получателю
                for r in (row["receivers"] or [row["after"][0]["unit"]]):
                    dist[bid][r] += 1
            elif row["status"] == "lost":
                lost_by_unit[bid] += 1
        a_label_to_id = {_unit_label(u): u["id"] for u in self.a_units.values()}
        received_from: dict[str, Counter] = defaultdict(Counter)
        for bid, cnt in dist.items():
            for alabel, n in cnt.items():
                received_from[a_label_to_id.get(alabel, alabel)][bid] += n

        for bid, bu in self.b_units.items():
            total = total_by_unit[bid] or 0
            aid = pairs.get(bid)
            d = dist.get(bid, Counter())
            kept_same = d.get(_unit_label(self.a_units[aid]), 0) if aid else 0
            share_same = kept_same / total if total else (1.0 if aid else 0.0)
            destinations = [(lbl, n) for lbl, n in d.most_common() if n / max(total, 1) >= 0.15]
            status, successor_ids = "preserved", [aid] if aid else []
            if aid:
                au = self.a_units[aid]
                renamed = unit_name_similarity(bu["name"], au["name"]) < 0.95 and bu.get("short") != au.get("short")
                if total and share_same < 0.5 and len(destinations) >= 2:
                    status = "reorganized"
                    successor_ids = [a_label_to_id[lbl] for lbl, _ in destinations if lbl in a_label_to_id]
                elif renamed:
                    status = "renamed"
                parent_changed = self._parent_label(self.b_units, bu) != self._parent_label(self.a_units, au)
            else:
                parent_changed = False
                if not total:
                    status = "abolished"
                elif len(destinations) >= 2:
                    status = "split"
                    successor_ids = [a_label_to_id[lbl] for lbl, _ in destinations if lbl in a_label_to_id]
                elif destinations and destinations[0][1] / total >= 0.5:
                    target = a_label_to_id.get(destinations[0][0])
                    if target and target not in pairs.values():
                        status, successor_ids = "renamed", [target]
                    else:
                        status, successor_ids = "reorganized", [target] if target else []
                elif destinations:
                    status = "reorganized"
                    successor_ids = [a_label_to_id[lbl] for lbl, _ in destinations if lbl in a_label_to_id]
                else:
                    status = "abolished"
            units.append({
                "key": f"b:{bid}",
                "status": status,
                "before": {"id": bid, "name": bu["name"], "short": bu.get("short", ""), "type": bu.get("type"),
                           "parent": self._parent_label(self.b_units, bu), "functions": len(bu["functions"]),
                           "head_title": bu.get("head_title", "")},
                "after": [self._unit_brief(self.a_units[x]) for x in successor_ids if x in self.a_units],
                "coverage": round(share_same, 3) if total else None,
                "functions_total": total,
                "functions_lost": lost_by_unit[bid],
                "destinations": [{"unit": lbl, "count": round(n, 1)} for lbl, n in d.most_common(6)],
                "parent_changed": parent_changed,
                "evidence": bu.get("evidence", [])[:3] + [e for x in successor_ids if x in self.a_units
                                                           for e in self.a_units[x].get("evidence", [])[:2]],
            })

        matched_after = set(pairs.values())
        successor_all = {a["id"] for u in units for a in u["after"]}
        for aid, au in self.a_units.items():
            if aid in matched_after:
                continue
            sources = received_from.get(aid, Counter())
            src_units = [self.b_units[b] for b, n in sources.most_common() if b in self.b_units and n >= 1]
            own = len(au["functions"]) or 1
            moved = sum(sources.values())
            status = "created"
            b_status = {u["before"]["id"]: u["status"] for u in units if u["before"]}
            dissolved = [x for x in src_units if b_status.get(x["id"]) in ("abolished", "split", "reorganized")]
            if len(dissolved) >= 2 and moved / own >= 0.3:
                status = "merged"
            if aid in successor_all and status == "created":
                # уже отражено как преемник (переименование/реорганизация)
                pass
            units.append({
                "key": f"a:{aid}",
                "status": status,
                "before": None,
                "after": [self._unit_brief(au)],
                "coverage": None,
                "functions_total": len(au["functions"]),
                "functions_new": sum(1 for r in fmap if r["status"] == "new" and r["after"]
                                     and r["after"][0]["unit_id"] == aid),
                "functions_received": round(moved, 1),
                "sources": [_unit_label(u) for u in src_units[:5]],
                "parent_changed": False,
                "evidence": au.get("evidence", [])[:3],
            })
        order = {"reorganized": 0, "split": 1, "merged": 2, "abolished": 3, "created": 4, "renamed": 5, "preserved": 6}
        units.sort(key=lambda u: order.get(u["status"], 9))
        return units

    @staticmethod
    def _parent_label(index: dict[str, dict[str, Any]], u: dict[str, Any]) -> str:
        p = index.get(u.get("parent_id") or "")
        return _unit_label(p) if p else ""

    @staticmethod
    def _unit_brief(u: dict[str, Any]) -> dict[str, Any]:
        return {"id": u["id"], "name": u["name"], "short": u.get("short", ""), "type": u.get("type"),
                "functions": len(u["functions"]), "head_title": u.get("head_title", "")}

    # ------------------------------------------------------------------ находки

    def _loss_findings(self, fmap: list[dict[str, Any]], units: list[dict[str, Any]]) -> None:
        status_of = {u["before"]["id"]: u["status"] for u in units if u["before"]}
        for row in fmap:
            if row["status"] not in ("lost", "relocated"):
                continue
            b = row["before"]
            unit_status = status_of.get(b["unit_id"], "")
            if row["generic"]:
                severity = "low"
            elif row["status"] == "relocated":
                severity = "low"
            elif unit_status in ("abolished", "reorganized", "split"):
                severity = "high"
            else:
                severity = "medium"
            nearest = row["after"][0] if row["after"] else None
            desc = (
                f"Функция подразделения «{b['unit']}» ({b['ref_display']}) не найдена в документах «после»."
                if row["status"] == "lost"
                else f"Функция подразделения «{b['unit']}» ({b['ref_display']}) не закреплена за подразделением "
                     f"в новой редакции — найдена только в общих положениях."
            )
            if nearest:
                desc += f" Ближайшая формулировка: «{short(nearest['text'], 120)}» ({nearest['unit']}, " \
                        f"{nearest['ref_display']}, сходство {nearest['score']:.2f}) — недостаточно для вывода о сохранении."
            f = self.add_finding(
                type="loss",
                severity=severity,
                title=f"Потенциальная потеря функции: {short(b['text'], 90)}",
                description=desc,
                units=[b["unit"]],
                evidence=[{k: v for k, v in b.items() if k not in ("unit_id", "unit", "pair_unit_id")} | {"unit": b["unit"]}]
                + ([{k: v for k, v in nearest.items() if k != "unit_id"} | {"role": "nearest"}] if nearest else []),
                confidence=round(0.9 - (row["score"] or 0) * 0.8, 2),
                related=[row["id"]],
            )
            row["finding_id"] = f["id"]

    def _duplicates(self, fns, side: str, record: bool = True) -> list[dict[str, Any]]:
        thr = self.s.get("duplicate", 0.66)
        items = [(u, f) for u, f in fns if not is_generic(f["text"], self.generic)
                 and len(f["text"].split()) >= self.s.get("min_function_words", 3)]
        if len(items) < 2:
            return []
        texts = [f["match_text"] for _, f in items]
        m = self.sim.self_matrix(texts)
        index = self.a_units if side == "after" else self.b_units
        # union-find по парам из разных подразделений
        parent = list(range(len(items)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        pair_scores: dict[tuple[int, int], float] = {}
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if m[i, j] < thr:
                    continue
                ui, fi = items[i]
                uj, fj = items[j]
                if ui["id"] == uj["id"] or fi["id"] == fj["id"]:
                    continue
                if fi.get("shared") and fj.get("shared") and (
                    fi["clause_id"] == fj["clause_id"] or fi.get("actor") == fj.get("actor")
                ):
                    continue  # одна и та же общая норма / нормы одной группы руководителей
                if fi["doc_id"] == fj["doc_id"] and (
                    fi.get("parent_clause") == fj["clause_id"] or fj.get("parent_clause") == fi["clause_id"]
                ):
                    continue  # пункт и его подпункт
                if self._related(ui, uj, index):
                    continue  # функция вышестоящего подразделения реализуется нижестоящим
                if self._self_scoped(ui, fi) and self._self_scoped(uj, fj):
                    continue  # «организует работу ДНМ» / «организует работу ДККМ» — разные объекты
                parent[find(i)] = find(j)
                pair_scores[(i, j)] = float(m[i, j])
        groups: dict[int, list[int]] = defaultdict(list)
        for i in range(len(items)):
            groups[find(i)].append(i)
        dups: list[dict[str, Any]] = []
        for members in groups.values():
            unit_ids = {items[i][0]["id"] for i in members}
            if len(members) < 2 or len(unit_ids) < 2:
                continue
            # один пункт (clause) = одна запись, даже если закреплён за несколькими подразделениями
            by_clause: dict[str, dict[str, Any]] = {}
            for i in members:
                u, f = items[i]
                rec = by_clause.setdefault(f["id"], {"fn": f, "units": []})
                rec["units"].append(u)
            if len(by_clause) < 2:
                continue
            scores = [s for (i, j), s in pair_scores.items() if i in members and j in members]
            shared_mix = any(r["fn"].get("shared") for r in by_clause.values()) and \
                any(not r["fn"].get("shared") for r in by_clause.values())
            unit_labels = sorted({_unit_label(u) for r in by_clause.values() for u in r["units"]})
            dup = {
                "units": unit_labels,
                "score": round(max(scores) if scores else thr, 3),
                "shared_mix": shared_mix,
                "clauses": [{"units": [_unit_label(u) for u in r["units"]], **self.ev(side, r["fn"])}
                            for r in by_clause.values()],
            }
            dups.append(dup)
            if record:
                if shared_mix:
                    title = "Дублирование общей и частной нормы"
                    desc = ("Функция закреплена одновременно общей нормой для группы руководителей/подразделений и "
                            "отдельной нормой для конкретного подразделения — возможны пересечение зон "
                            "ответственности и неясность, кто исполняет функцию.")
                    severity = "low"
                else:
                    title = "Дублирование функции в разных подразделениях"
                    desc = ("Схожая функция закреплена за несколькими подразделениями: "
                            + ", ".join(unit_labels) + ". Требуется разграничить зоны ответственности.")
                    severity = "high" if dup["score"] >= 0.8 else "medium"
                first_text = next(iter(by_clause.values()))["fn"]["text"]
                f = self.add_finding(
                    type="duplication",
                    severity=severity,
                    title=f"{title}: {short(first_text, 80)}",
                    description=desc,
                    units=unit_labels,
                    evidence=[{k: v for k, v in c.items() if k != "units"} | {"unit": ", ".join(c["units"])}
                              for c in dup["clauses"]],
                    confidence=round(min(0.95, dup["score"]), 2),
                    score=dup["score"],
                )
                dup["finding_id"] = f["id"]
        return dups

    @staticmethod
    def _related(ua: dict[str, Any], ub: dict[str, Any], index: dict[str, dict[str, Any]]) -> bool:
        """Является ли одно подразделение вышестоящим для другого."""
        def ancestors(u: dict[str, Any]) -> set[str]:
            out, cur, guard = set(), u, 0
            while cur.get("parent_id") and guard < 20:
                out.add(cur["parent_id"])
                cur = index.get(cur["parent_id"], {})
                guard += 1
            return out
        return ua["id"] in ancestors(ub) or ub["id"] in ancestors(ua)

    @staticmethod
    def _self_scoped(u: dict[str, Any], f: dict[str, Any]) -> bool:
        short_name = u.get("short") or ""
        return bool(short_name) and re.search(rf"(?<![\wЁё]){re.escape(short_name)}(?![\wЁё])", f["text"]) is not None

    def _mark_new_duplicates(self, after_dups, before_dups, fmap) -> None:
        before_sets = [set(d["units"]) for d in before_dups]
        for d in after_dups:
            fid = d.get("finding_id")
            if not fid:
                continue
            f = next(x for x in self.findings if x["id"] == fid)
            inherited = any(len(set(d["units"]) & s) >= 2 for s in before_sets)
            f["inherited"] = inherited
            f["description"] += (" Дублирование существовало и в предыдущей редакции." if inherited
                                  else " Дублирование возникло в результате изменений.")

    def _reorg_findings(self, units: list[dict[str, Any]]) -> None:
        for u in units:
            st = u["status"]
            if st == "preserved" and not u.get("functions_lost"):
                continue
            if st == "preserved":
                continue
            if u["before"]:
                name = f"{u['before']['name']}" + (f" ({u['before']['short']})" if u['before']['short'] else "")
            else:
                a = u["after"][0]
                name = f"{a['name']}" + (f" ({a['short']})" if a.get("short") else "")
            succ = ", ".join(_unit_label(a) for a in u["after"]) if u["after"] else ""
            texts = {
                "created": f"Создано новое подразделение «{name}»"
                + (f"; в него переданы функции из: {', '.join(u.get('sources', []))}." if u.get("sources") else "."),
                "merged": f"Подразделение «{name}» образовано с передачей функций из: {', '.join(u.get('sources', []))}.",
                "abolished": f"Подразделение «{name}» отсутствует в документах «после»"
                + (f"; не найдено {u.get('functions_lost', 0)} из {u['functions_total']} функций."
                   if u["functions_total"] and u.get("functions_lost") else "."),
                "reorganized": f"Подразделение «{name}» реорганизовано: функции распределены между: "
                + (", ".join(d["unit"] for d in u.get("destinations", [])[:4]) or succ) + ".",
                "split": f"Подразделение «{name}» разделено: функции переданы в " + succ + ".",
                "renamed": f"Подразделение «{name}» переименовано/преобразовано в «{succ}».",
            }
            severity = {"abolished": "high" if u.get("functions_lost") else "medium", "reorganized": "medium",
                        "split": "medium", "merged": "medium", "created": "info", "renamed": "low"}.get(st, "low")
            f = self.add_finding(
                type="reorganization",
                subtype=st,
                severity=severity,
                title=f"{UNIT_STATUS_LABELS.get(st, st).capitalize()}: {name}",
                description=texts.get(st, ""),
                units=[name] + ([succ] if succ else []),
                evidence=u["evidence"][:4],
                confidence=0.8,
            )
            u["finding_id"] = f["id"]


def compare(before: dict[str, Any], after: dict[str, Any], settings: dict[str, Any],
            similarity: Similarity, doc_titles: dict[int, str]) -> dict[str, Any]:
    return Comparator(before, after, settings, similarity, doc_titles).run()


def unit_display(u: dict[str, Any]) -> str:
    return _unit_label(u)


__all__ = ["compare", "Comparator", "UNIT_STATUS_LABELS", "FN_STATUS_LABELS", "unit_display", "content_stems",
           "re"]
