"""Опциональные проверки: соответствие внешним требованиям и сравнение с практикой других операторов."""
from __future__ import annotations

import re
from typing import Any

from .compare import Comparator, _unit_label
from .structure import build_structure, unit_name_similarity
from .text import short

NORMATIVE_RE = re.compile(
    r"должн|обязан|обеспечива|осуществля|проводит|провод|следует|необходимо|требуется|не допускается|"
    r"устанавлива|определя|утвержда|контрол|оценива|предусматрива", re.I)


def check_requirements(cmp: Comparator, req_docs: list[dict[str, Any]], limit: int = 150) -> dict[str, Any]:
    """Сопоставляет требования (законы, стандарты, ВНД) с функциями подразделений «после»."""
    reqs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for d in req_docs:
        for c in (d.get("parsed") or {}).get("clauses") or []:
            text = c.get("text", "")
            if c.get("is_heading") or c.get("kind") in ("toc", "definition") or len(text.split()) < 5:
                continue
            if not NORMATIVE_RE.search(text) and c.get("kind") not in ("function", "duty", "task"):
                continue
            reqs.append((d, c))
    reqs = reqs[:limit]
    fns = [(u, f) for u in cmp.after["units"] for f in u["functions"]]
    if not reqs or not fns:
        return {"items": [], "covered": 0, "partial": 0, "gaps": 0}
    m = cmp.sim.matrix([c["text"] for _, c in reqs], [f["match_text"] for _, f in fns])
    hi, lo = cmp.s.get("match_high", 0.62), cmp.s.get("match_low", 0.38)
    # требования обычно сформулированы иначе, чем функции — пороги мягче
    hi_r, lo_r = hi - 0.12, lo - 0.08
    items = []
    counts = {"covered": 0, "partial": 0, "gap": 0}
    for i, (d, c) in enumerate(reqs):
        j = int(m[i].argmax())
        score = float(m[i, j])
        u, f = fns[j]
        status = "covered" if score >= hi_r else "partial" if score >= lo_r else "gap"
        counts[status] += 1
        req_ev = {"side": "requirements", "doc_id": d["id"], "doc_title": d.get("title") or d.get("filename"),
                  "clause_id": c["id"], "ref": c.get("ref"), "ref_display": c.get("ref_display"),
                  "page": c.get("page"), "text": c.get("text", "")}
        fn_ev = cmp.ev("after", f, score) | {"unit": _unit_label(u)}
        items.append({"status": status, "score": round(score, 3), "requirement": req_ev, "function": fn_ev})
        if status == "gap":
            cmp.add_finding(
                type="requirement_gap",
                severity="medium",
                title=f"Требование не отражено в функциях подразделений: {short(c.get('text', ''), 90)}",
                description=f"Требование «{short(c.get('text', ''), 200)}» ({req_ev['doc_title']}, "
                            f"{c.get('ref_display')}) не сопоставлено ни с одной функцией подразделений «после». "
                            f"Ближайшая функция: «{short(f['text'], 120)}» ({_unit_label(u)}, сходство {score:.2f}).",
                units=[_unit_label(u)],
                evidence=[req_ev, fn_ev | {"role": "nearest"}],
                confidence=round(0.85 - score, 2),
            )
    return {"items": items, "covered": counts["covered"], "partial": counts["partial"], "gaps": counts["gap"]}


def benchmark(cmp: Comparator, bench_docs: list[dict[str, Any]], function_kinds: list[str],
              focus_unit_ids: set[str]) -> dict[str, Any]:
    """Сравнивает созданные/преобразованные подразделения с подразделениями других операторов."""
    if not bench_docs:
        return {"items": []}
    items = []
    for d in bench_docs:
        other = build_structure("benchmark", [d], function_kinds)
        o_units = [u for u in other["units"] if u["functions"]]
        if not o_units:
            continue
        for au in cmp.after["units"]:
            if focus_unit_ids and au["id"] not in focus_unit_ids:
                continue
            best, best_score = None, 0.0
            for ou in o_units:
                name_s = unit_name_similarity(au["name"], ou["name"])
                if au["functions"] and ou["functions"]:
                    mm = cmp.sim.matrix([f["match_text"] for f in au["functions"]],
                                        [f["match_text"] for f in ou["functions"]])
                    fn_s = float(mm.max(axis=1).mean())
                else:
                    fn_s = 0.0
                score = 0.4 * name_s + 0.6 * fn_s
                if score > best_score:
                    best, best_score = ou, score
            if not best or best_score < 0.45:
                continue
            missing = []
            if au["functions"]:
                mm = cmp.sim.matrix([f["match_text"] for f in best["functions"]],
                                    [f["match_text"] for f in au["functions"]])
                for k, bf in enumerate(best["functions"]):
                    if float(mm[k].max()) < cmp.s.get("match_low", 0.38) and len(bf["text"].split()) >= 4:
                        missing.append({"side": "benchmark", "doc_id": d["id"],
                                        "doc_title": d.get("title") or d.get("filename"),
                                        "clause_id": bf["clause_id"], "ref": bf.get("ref"),
                                        "ref_display": bf.get("ref_display"), "page": bf.get("page"),
                                        "text": bf["text"]})
            item = {"unit": _unit_label(au), "benchmark_unit": _unit_label(best),
                    "benchmark_doc": d.get("title") or d.get("filename"), "score": round(best_score, 3),
                    "missing": missing[:10]}
            items.append(item)
            if missing:
                cmp.add_finding(
                    type="benchmark",
                    severity="info",
                    title=f"Практика других операторов: «{_unit_label(au)}» ↔ «{_unit_label(best)}»",
                    description=f"У аналогичного подразделения ({item['benchmark_doc']}) закреплены функции, "
                                f"не найденные у «{_unit_label(au)}»: "
                                + "; ".join(f"«{short(x['text'], 90)}»" for x in missing[:3])
                                + ("…" if len(missing) > 3 else "."),
                    units=[_unit_label(au)],
                    evidence=missing[:5],
                    confidence=round(best_score, 2),
                )
    return {"items": items}
