"""Проверка пограничных выводов ИИ-моделью (LLM-as-a-judge).

Модель не создаёт новых выводов — она лишь подтверждает или оспаривает выводы,
найденные правилами, и всегда видит исходные формулировки. Оспоренные выводы
не удаляются, а помечаются (прослеживаемость + решение за сотрудником).
"""
from __future__ import annotations

from typing import Any, Callable

from ..services.llm import LLMClient, LLMError
from . import prompts
from .text import short

Log = Callable[[str], None]


def verify_function_map(llm: LLMClient, fmap: list[dict[str, Any]], findings: list[dict[str, Any]],
                        log: Log, limit: int = 30) -> dict[str, int]:
    stats = {"checked": 0, "confirmed_same": 0, "partial": 0, "different": 0, "errors": 0}
    by_related = {r: f for f in findings for r in f.get("related", [])}
    candidates = [r for r in fmap if r["status"] == "modified" and r["before"] and r["after"]]
    candidates += [r for r in fmap if r["status"] == "lost" and r["after"] and r["after"][0].get("score", 0) >= 0.25]
    for row in candidates[:limit]:
        b, a = row["before"], row["after"][0]
        try:
            res = llm.complete_json(prompts.SYSTEM_ANALYST, prompts.SAME_FUNCTION.format(
                before_unit=b["unit"], before_ref=b["ref_display"], before_text=short(b["text"], 600),
                after_unit=a["unit"], after_ref=a["ref_display"], after_text=short(a["text"], 600)), max_tokens=300)
        except LLMError as exc:
            stats["errors"] += 1
            log(f"Ошибка проверки {row['id']}: {exc}")
            if stats["errors"] >= 3:
                log("Слишком много ошибок модели — проверка остановлена")
                break
            continue
        stats["checked"] += 1
        verdict = str(res.get("verdict", "")).lower()
        row["verified"] = {"verdict": verdict, "reason": res.get("reason", ""), "by": llm.model}
        if verdict == "same":
            stats["confirmed_same"] += 1
            if row["status"] in ("modified", "lost"):
                old = row["status"]
                row["status"] = "preserved" if a["unit_id"] == b.get("pair_unit_id") else "transferred"
                f = by_related.get(row["id"])
                if f and old == "lost":
                    f["disputed"] = True
                    f["severity"] = "low"
                    f["llm_note"] = f"Модель считает функцию сохранённой: {res.get('reason', '')}"
                    f["method"] = "rules+llm"
        elif verdict == "partial":
            stats["partial"] += 1
            if row["status"] == "lost":
                row["status"] = "modified"
                f = by_related.get(row["id"])
                if f:
                    f["severity"] = "low" if f["severity"] == "medium" else f["severity"]
                    f["llm_note"] = f"Модель: функция сохранена частично — {res.get('reason', '')}"
                    f["method"] = "rules+llm"
        else:
            stats["different"] += 1
            f = by_related.get(row["id"])
            if f:
                f["llm_note"] = f"Модель подтверждает отсутствие аналога: {res.get('reason', '')}"
                f["method"] = "rules+llm"
                f["confidence"] = min(0.95, f.get("confidence", 0.7) + 0.1)
    return stats


def verify_findings(llm: LLMClient, findings: list[dict[str, Any]], log: Log, limit: int = 20) -> dict[str, int]:
    stats = {"checked": 0, "confirmed": 0, "disputed": 0, "errors": 0}
    targets = [f for f in findings if f["type"] == "duplication" or (f["type"] == "conflict" and f.get("subtype") == "sod")]
    for f in targets[:limit]:
        ev = f.get("evidence") or []
        try:
            if f["type"] == "duplication":
                items = "\n".join(
                    f"- {e.get('unit', '')} ({e.get('ref_display')}): «{short(e.get('text', ''), 400)}»" for e in ev[:5])
                res = llm.complete_json(prompts.SYSTEM_ANALYST, prompts.CHECK_DUPLICATE.format(items=items),
                                        max_tokens=350)
                ok = bool(res.get("is_duplicate"))
            else:
                if len(ev) < 2:
                    continue
                res = llm.complete_json(prompts.SYSTEM_ANALYST, prompts.CHECK_CONFLICT.format(
                    unit=", ".join(f.get("units", [])), ref1=ev[0].get("ref_display"), text1=short(ev[0].get("text", ""), 400),
                    ref2=ev[1].get("ref_display"), text2=short(ev[1].get("text", ""), 400)), max_tokens=350)
                ok = bool(res.get("is_conflict"))
        except LLMError as exc:
            stats["errors"] += 1
            log(f"Ошибка проверки {f['id']}: {exc}")
            if stats["errors"] >= 3:
                log("Слишком много ошибок модели — проверка остановлена")
                break
            continue
        stats["checked"] += 1
        f["method"] = "rules+llm"
        f["llm_note"] = res.get("reason", "")
        if res.get("recommendation"):
            f["llm_recommendation"] = res["recommendation"]
        if ok:
            stats["confirmed"] += 1
            f["confidence"] = min(0.95, f.get("confidence", 0.7) + 0.1)
        else:
            stats["disputed"] += 1
            f["disputed"] = True
            f["confidence"] = max(0.2, f.get("confidence", 0.7) - 0.3)
            if f["severity"] in ("high", "medium"):
                f["severity"] = "low"
    return stats
