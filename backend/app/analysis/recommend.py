"""Рекомендации по устранению выявленных проблем и перераспределению функций."""
from __future__ import annotations

from typing import Any

from .text import short


def _successors(units: list[dict[str, Any]], unit_label: str) -> list[str]:
    for u in units:
        b = u.get("before")
        if not b:
            continue
        label = f"{b['name']} ({b['short']})" if b.get("short") else b["name"]
        if label == unit_label:
            return [f"{a['name']} ({a['short']})" if a.get("short") else a["name"] for a in u.get("after", [])]
    return []


def add_recommendations(result: dict[str, Any]) -> list[dict[str, Any]]:
    units = result["units"]
    recs: list[dict[str, Any]] = []
    for f in result["findings"]:
        t, sub = f["type"], f.get("subtype", "")
        text = ""
        if t == "loss":
            src_unit = f["units"][0] if f["units"] else ""
            nearest = next((e for e in f["evidence"] if e.get("role") == "nearest"), None)
            succ = _successors(units, src_unit)
            target = succ[0] if succ else (nearest.get("unit") if nearest else "")
            fn_text = short(f["evidence"][0].get("text", ""), 140) if f["evidence"] else ""
            text = (f"Закрепить функцию «{fn_text}» за подразделением «{target}» в новой редакции документов "
                    f"либо оформить решение об её упразднении/передаче." if target else
                    f"Определить подразделение-владельца функции «{fn_text}» либо оформить решение об её упразднении.")
        elif t == "duplication":
            if len(f["evidence"]) >= 2 and "общей и частной" in f["title"]:
                text = ("Оставить одну норму: исключить частную формулировку из раздела подразделения или "
                        "указать в общей норме, что она применяется с учётом специальных положений.")
            else:
                owner = f["units"][0] if f["units"] else ""
                text = (f"Определить единственного владельца функции (например, «{owner}»), для остальных "
                        f"подразделений закрепить участие/взаимодействие; разграничить зоны ответственности в положениях.")
        elif t == "conflict" and sub == "sod":
            text = ("Разделить несовместимые функции: передать контрольную (оценочную) функцию независимому "
                    "подразделению или предусмотреть утверждение/проверку вышестоящим руководителем; "
                    "закрепить процедуру раскрытия и урегулирования конфликта интересов.")
        elif t == "conflict" and sub == "dual_subordination":
            text = ("Устранить двойное подчинение: определить одного линейного руководителя, функциональное "
                    "взаимодействие закрепить регламентом.")
        elif t == "conflict" and sub == "declared":
            text = ("Проверить, что для каждого случая совмещения определён порядок раскрытия и исключения "
                    "конфликта интересов (декларации, информирование Комитета по аудиту).")
        elif t == "reorganization":
            if sub == "abolished":
                text = ("Проверить передачу всех функций упразднённого подразделения; составить перечень передаваемых "
                        "функций и документов.")
            elif sub in ("created", "merged"):
                text = ("Утвердить положение о подразделении и должностные инструкции; проверить отсутствие "
                        "пересечений функций с действующими подразделениями.")
            elif sub in ("reorganized", "split"):
                text = ("Сверить перечень функций подразделения-предшественника с положениями подразделений-"
                        "преемников; при необходимости дополнить положения.")
            elif sub == "renamed":
                text = "Актуализировать ссылки на подразделение во внутренних нормативных документах."
        elif t == "requirement_gap":
            nearest = next((e for e in f["evidence"] if e.get("role") == "nearest"), None)
            text = (f"Закрепить исполнение требования в положении подразделения"
                    + (f" «{nearest.get('unit')}»" if nearest and nearest.get("unit") else "") + ".")
        elif t == "benchmark":
            text = "Рассмотреть целесообразность закрепления указанных функций с учётом практики других операторов."
        if f.get("llm_recommendation"):
            text = f"{text} ИИ-модель дополнительно предлагает: {f['llm_recommendation']}".strip()
        if text:
            f["recommendation"] = text
            recs.append({"finding_id": f["id"], "type": t, "severity": f["severity"], "text": text,
                         "units": f.get("units", [])})
    return recs
