"""Сопоставление структуры и функций двух подразделений (фактическое ↔ эталонное / до ↔ после).

Реализация функции compare_departments из исходного прототипа команды
(structure_matcher.py) поверх общего движка сравнения.
"""
from __future__ import annotations

from typing import Any

from .text import Similarity, is_generic, short
from .structure import unit_name_similarity

DEFAULT_HIGH = 0.62
DEFAULT_LOW = 0.38


def _functions(dep: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for i, f in enumerate(dep.get("functions") or []):
        if isinstance(f, str):
            out.append({"text": f, "ref": str(i + 1)})
        elif isinstance(f, dict) and f.get("text"):
            out.append({"text": f["text"], "ref": f.get("ref_display") or f.get("ref") or str(i + 1)})
    return out


def compare_departments(actual: dict, reference: dict, *, high: float = DEFAULT_HIGH, low: float = DEFAULT_LOW,
                        generic_phrases: list[str] | None = None) -> dict:
    """Сравнивает два подразделения.

    Формат входа: {"name": str, "short"?: str, "functions": [str | {"text", "ref"?}], "units"?: [{"name"}]}
    Возвращает {"status", "deviations", "explanation", "coverage", "matches"}.
    """
    a_fns, r_fns = _functions(actual), _functions(reference)
    generic = generic_phrases or []
    deviations: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []

    name_sim = unit_name_similarity(actual.get("name", ""), reference.get("name", "")) if actual.get("name") else 0.0
    if actual.get("name") and reference.get("name") and name_sim < 0.9:
        deviations.append({"type": "name_mismatch", "severity": "low",
                           "message": f"Название отличается: «{actual['name']}» ↔ «{reference['name']}»",
                           "details": {"similarity": round(name_sim, 3)}})

    sim = Similarity()
    if a_fns and r_fns:
        m = sim.matrix([f["text"] for f in r_fns], [f["text"] for f in a_fns])
        for i, rf in enumerate(r_fns):
            j = int(m[i].argmax())
            score = float(m[i, j])
            status = "matched" if score >= high else "partial" if score >= low else "missing"
            matches.append({"reference": rf, "actual": a_fns[j] if status != "missing" else None,
                            "score": round(score, 3), "status": status})
            if status == "missing" and not is_generic(rf["text"], generic):
                deviations.append({"type": "missing_function", "severity": "high",
                                   "message": f"Отсутствует функция эталона: «{short(rf['text'], 150)}» (п. {rf['ref']})",
                                   "details": {"reference": rf, "nearest": a_fns[j], "score": round(score, 3)}})
            elif status == "partial":
                deviations.append({"type": "partial_function", "severity": "medium",
                                   "message": f"Функция отражена частично: «{short(rf['text'], 120)}» ↔ «{short(a_fns[j]['text'], 120)}»",
                                   "details": {"reference": rf, "actual": a_fns[j], "score": round(score, 3)}})
        best_for_actual = m.max(axis=0)
        for j, af in enumerate(a_fns):
            if float(best_for_actual[j]) < low and not is_generic(af["text"], generic):
                deviations.append({"type": "extra_function", "severity": "low",
                                   "message": f"Функция отсутствует в эталоне: «{short(af['text'], 150)}» (п. {af['ref']})",
                                   "details": {"actual": af, "score": round(float(best_for_actual[j]), 3)}})
    elif r_fns and not a_fns:
        deviations += [{"type": "missing_function", "severity": "high", "message": f"Отсутствует функция: «{short(f['text'], 150)}»",
                        "details": {"reference": f}} for f in r_fns]

    a_units = {u.get("name", "").strip().lower() for u in actual.get("units") or []}
    for u in reference.get("units") or []:
        n = u.get("name", "")
        if n and not any(unit_name_similarity(n, x) >= 0.85 for x in a_units):
            deviations.append({"type": "missing_unit", "severity": "medium", "message": f"Нет структурной единицы «{n}»",
                               "details": {"unit": n}})

    covered = sum(1 for x in matches if x["status"] == "matched") + 0.5 * sum(1 for x in matches if x["status"] == "partial")
    coverage = round(covered / len(r_fns), 3) if r_fns else None
    missing = sum(1 for d in deviations if d["type"] == "missing_function")
    if not deviations:
        explanation = "Структура и функции подразделения соответствуют эталону."
    else:
        explanation = (f"Покрытие функций эталона: {round((coverage or 0) * 100)}%. Отсутствует функций: {missing}; "
                       f"частично отражено: {sum(1 for d in deviations if d['type'] == 'partial_function')}; "
                       f"дополнительных функций: {sum(1 for d in deviations if d['type'] == 'extra_function')}.")
    return {
        "status": "ok" if not deviations else "deviations_found",
        "deviations": deviations,
        "explanation": explanation,
        "coverage": coverage,
        "matches": matches,
    }
