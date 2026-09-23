"""Итоговое аналитическое заключение (RU/KZ) со ссылками на пункты документов.

Структура заключения формируется детерминированно из выводов. Если подключена
ИИ-модель, она пишет только краткое резюме, где каждое утверждение обязано
ссылаться на идентификаторы выводов [F-xxx]; ссылки проверяются, иначе резюме
заменяется шаблонным.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from ..services.llm import LLMClient, LLMError
from . import prompts
from .recommend import recommendation_text
from .text import short

SEV_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}

T = {
    "ru": {
        "title": "Аналитическое заключение по результатам сравнения организационной структуры и функционала",
        "s_scope": "1. Объект и источники анализа",
        "s_summary": "2. Основные выводы",
        "s_structure": "3. Изменения организационной структуры",
        "s_losses": "4. Потенциальная потеря функций",
        "s_dups": "5. Дублирование функций",
        "s_conflicts": "6. Потенциальные конфликты интересов",
        "s_req": "7. Соответствие внешним требованиям",
        "s_bench": "8. Сравнение с практикой других операторов",
        "s_recs": "9. Рекомендации",
        "s_limits": "10. Ограничения",
        "before_docs": "Документы «до»",
        "after_docs": "Документы «после»",
        "req_docs": "Требования",
        "bench_docs": "Практика других операторов",
        "stats": ("Подразделений: до — {ub}, после — {ua}. Функций (пунктов): до — {fb}, после — {fa}. "
                  "Сохранено функций: {kept}, передано в другие подразделения: {moved}, изменено: {mod}, "
                  "потенциально утрачено: {lost}, новых: {new}."),
        "status": {"preserved": "сохранено", "renamed": "переименовано/преобразовано", "reorganized": "реорганизовано",
                   "merged": "образовано слиянием", "split": "разделено", "abolished": "упразднено",
                   "created": "создано"},
        "none_losses": "Потенциальных потерь функций не выявлено.",
        "none_dups": "Дублирования функций между подразделениями не выявлено.",
        "none_conflicts": "Потенциальных конфликтов интересов не выявлено.",
        "loss_item": "Функция подразделения «{unit}» не найдена в документах «после»: «{text}».",
        "dup_item": "Схожая функция закреплена за несколькими подразделениями ({units}): «{text}».",
        "dup_shared": "Общая и частная нормы дублируют друг друга ({units}): «{text}».",
        "sod_item": "«{unit}»: {title}.",
        "dual_item": "Двойное подчинение должности «{pos}»: {units}.",
        "declared_item": "Документы содержат нормы о потенциальном конфликте интересов при совмещении функций.",
        "improve_item": "Устранено двойное подчинение должности «{pos}».",
        "req_stats": "Требований проанализировано: {n}; отражены в функциях: {c}; частично: {p}; не отражены: {g}.",
        "req_item": "Требование не отражено в функциях подразделений: «{text}».",
        "bench_item": "«{unit}» ↔ «{other}» ({doc}): у аналога есть функции, отсутствующие у подразделения.",
        "limits": ("Выводы сформированы автоматически и носят рекомендательный характер; они требуют проверки "
                   "ответственным сотрудником. Каждый вывод сопровождается ссылкой на документ и пункт, на "
                   "основании которых он сделан; утверждения, не подтверждённые документами, не формируются. "
                   "Сходство формулировок оценивается алгоритмически и может не учитывать контекст, не "
                   "отражённый в тексте документов."),
        "reviewed": "Проверено сотрудником: подтверждено — {c}, отклонено — {r}, ожидает проверки — {p}.",
        "sources": "Источник",
        "summary_template": ("В результате сравнения выявлено: создано подразделений — {created}, упразднено — {abolished}, "
                             "реорганизовано — {reorg}, сохранено — {preserved}. Потенциально утрачено функций — {lost}; "
                             "случаев дублирования — {dups}; потенциальных конфликтов интересов — {conf}. {top}"),
        "top_prefix": "Наиболее значимые выводы: ",
        "method_llm": "Резюме подготовлено ИИ-моделью {model} на основе выводов; ссылки проверены.",
        "method_rules": "Резюме подготовлено по шаблону на основе выводов (ИИ-модель не использовалась).",
    },
    "kz": {
        "title": "Ұйымдық құрылым мен функционалды салыстыру нәтижелері бойынша талдамалық қорытынды",
        "s_scope": "1. Талдау объектісі және дереккөздер",
        "s_summary": "2. Негізгі қорытындылар",
        "s_structure": "3. Ұйымдық құрылымның өзгерістері",
        "s_losses": "4. Функциялардың ықтимал жоғалуы",
        "s_dups": "5. Функциялардың қайталануы",
        "s_conflicts": "6. Мүдделер қақтығысының ықтимал тәуекелдері",
        "s_req": "7. Сыртқы талаптарға сәйкестік",
        "s_bench": "8. Басқа операторлардың тәжірибесімен салыстыру",
        "s_recs": "9. Ұсынымдар",
        "s_limits": "10. Шектеулер",
        "before_docs": "«Дейінгі» құжаттар",
        "after_docs": "«Кейінгі» құжаттар",
        "req_docs": "Талаптар",
        "bench_docs": "Басқа операторлардың тәжірибесі",
        "stats": ("Бөлімшелер саны: дейін — {ub}, кейін — {ua}. Функциялар (тармақтар): дейін — {fb}, кейін — {fa}. "
                  "Сақталған функциялар: {kept}, басқа бөлімшелерге берілгені: {moved}, өзгертілгені: {mod}, "
                  "ықтимал жоғалғаны: {lost}, жаңалары: {new}."),
        "status": {"preserved": "сақталған", "renamed": "атауы өзгертілген/қайта құрылған",
                   "reorganized": "қайта ұйымдастырылған", "merged": "біріктіру арқылы құрылған",
                   "split": "бөлінген", "abolished": "таратылған", "created": "жаңадан құрылған"},
        "none_losses": "Функциялардың ықтимал жоғалуы анықталған жоқ.",
        "none_dups": "Бөлімшелер арасында функциялардың қайталануы анықталған жоқ.",
        "none_conflicts": "Мүдделер қақтығысының ықтимал тәуекелдері анықталған жоқ.",
        "loss_item": "«{unit}» бөлімшесінің функциясы «кейінгі» құжаттарда табылмады: «{text}».",
        "dup_item": "Ұқсас функция бірнеше бөлімшеге бекітілген ({units}): «{text}».",
        "dup_shared": "Жалпы және жеке нормалар бірін-бірі қайталайды ({units}): «{text}».",
        "sod_item": "«{unit}»: функцияларды қоса атқару мүдделер қақтығысы тәуекелін тудырады.",
        "dual_item": "«{pos}» лауазымының қос бағыныштылығы: {units}.",
        "declared_item": "Құжаттарда функцияларды қоса атқарған кездегі ықтимал мүдделер қақтығысы туралы нормалар бар.",
        "improve_item": "«{pos}» лауазымының қос бағыныштылығы жойылды.",
        "req_stats": "Талданған талаптар: {n}; функцияларда көрсетілгені: {c}; ішінара: {p}; көрсетілмегені: {g}.",
        "req_item": "Талап бөлімшелердің функцияларында көрсетілмеген: «{text}».",
        "bench_item": "«{unit}» ↔ «{other}» ({doc}): аналогта бөлімшеде жоқ функциялар бар.",
        "limits": ("Қорытындылар автоматты түрде қалыптастырылған және ұсыныс сипатында болады; оларды жауапты "
                   "қызметкер тексеруі тиіс. Әрбір қорытынды негізінде жасалған құжатқа және тармаққа сілтемемен "
                   "беріледі; құжаттармен расталмаған тұжырымдар қалыптастырылмайды."),
        "reviewed": "Қызметкер тексерді: расталды — {c}, қабылданбады — {r}, тексеруді күтуде — {p}.",
        "sources": "Дереккөз",
        "summary_template": ("Салыстыру нәтижесінде анықталды: құрылған бөлімшелер — {created}, таратылғаны — {abolished}, "
                             "қайта ұйымдастырылғаны — {reorg}, сақталғаны — {preserved}. Ықтимал жоғалған функциялар — "
                             "{lost}; қайталану жағдайлары — {dups}; мүдделер қақтығысының ықтимал тәуекелдері — {conf}. {top}"),
        "top_prefix": "Ең маңызды қорытындылар: ",
        "method_llm": "Түйіндемені {model} ЖИ-моделі қорытындылар негізінде дайындады; сілтемелер тексерілді.",
        "method_rules": "Түйіндеме қорытындылар негізінде үлгі бойынша дайындалды (ЖИ-модель қолданылмады).",
    },
}


def ref_for(ev: dict[str, Any], lang: str) -> str:
    title = ev.get("doc_title") or ""
    ref = ev.get("ref_display") or ""
    if lang == "kz":
        ref = re.sub(r"^пп\. «(.+?)» п\. (.+)$", r"\2-тармақтың «\1» тармақшасы", ref)
        ref = re.sub(r"^п\. (.+?), абз\. (\d+)$", r"\1-тармақ, \2-азатжол", ref)
        ref = re.sub(r"^п\. (.+)$", r"\1-тармақ", ref)
    page = ev.get("page")
    page_s = (f", с. {page}" if lang == "ru" else f", {page}-бет") if page else ""
    return f"{title}, {ref}{page_s}".strip(", ")


def _item(f: dict[str, Any], text: str, lang: str, reviews: dict[str, str]) -> dict[str, Any]:
    return {
        "finding_id": f["id"],
        "severity": f["severity"],
        "text": text,
        "sources": [ref_for(e, lang) for e in f.get("evidence", [])[:4]],
        "review": reviews.get(f["id"], "pending"),
        "disputed": bool(f.get("disputed")),
    }


def build_conclusion(result: dict[str, Any], docs: list[dict[str, Any]], lang: str = "ru",
                     reviews: dict[str, str] | None = None, llm: LLMClient | None = None,
                     project_name: str = "") -> dict[str, Any]:
    t = T.get(lang, T["ru"])
    reviews = reviews or {}
    findings = [f for f in result["findings"] if reviews.get(f["id"]) != "rejected"]
    s = result["summary"]
    fs = s.get("functions_by_status", {})
    us = s.get("units_by_status", {})
    sections: list[dict[str, Any]] = []

    # 1. Объект и источники
    groups = []
    for side, label in (("before", t["before_docs"]), ("after", t["after_docs"]),
                        ("requirements", t["req_docs"]), ("benchmark", t["bench_docs"])):
        items = [d for d in docs if d["side"] == side]
        if items:
            groups.append({"text": label + ": " + "; ".join(
                (d.get("title") or d["filename"]) + (f" (ред. {d['edition']})" if d.get("edition") else "")
                + f" — {d['filename']}" for d in items), "sources": []})
    sections.append({"id": "scope", "title": t["s_scope"], "paragraphs": [project_name] if project_name else [],
                     "items": groups})

    # 2. Резюме
    stats_line = t["stats"].format(ub=s["units_before"], ua=s["units_after"], fb=s["functions_before"],
                                   fa=s["functions_after"], kept=fs.get("preserved", 0), moved=fs.get("transferred", 0),
                                   mod=fs.get("modified", 0), lost=fs.get("lost", 0), new=fs.get("new", 0))
    top = sorted([f for f in findings if f["severity"] in ("high", "medium") and f["type"] != "reorganization"],
                 key=lambda f: SEV_ORDER.get(f["severity"], 9))[:4]
    summary_text = t["summary_template"].format(
        created=us.get("created", 0) + us.get("merged", 0), abolished=us.get("abolished", 0),
        reorg=us.get("reorganized", 0) + us.get("split", 0), preserved=us.get("preserved", 0) + us.get("renamed", 0),
        lost=sum(1 for f in findings if f["type"] == "loss"),
        dups=sum(1 for f in findings if f["type"] == "duplication"),
        conf=sum(1 for f in findings if f["type"] == "conflict"),
        top=(t["top_prefix"] + "; ".join(f"{short(f['title'], 90)} [{f['id']}]" for f in top) + ".") if top else "",
    )
    method = t["method_rules"]
    if llm is not None and llm.allowed("conclusion"):
        ai = _llm_summary(llm, result, findings)
        if ai:
            if lang == "kz":
                try:
                    ai = llm.complete(prompts.SYSTEM_ANALYST, prompts.TRANSLATE_KZ.format(text=ai), max_tokens=1200)
                except LLMError:
                    ai = None
            if ai:
                summary_text = ai
                method = t["method_llm"].format(model=llm.model)
    c_ = sum(1 for v in reviews.values() if v == "confirmed")
    r_ = sum(1 for v in reviews.values() if v == "rejected")
    p_ = len(result["findings"]) - c_ - r_
    sections.append({"id": "summary", "title": t["s_summary"],
                     "paragraphs": [summary_text, stats_line, t["reviewed"].format(c=c_, r=r_, p=p_)],
                     "items": [], "method": method})

    # 3. Структура
    st_items = []
    for u in result["units"]:
        if u["status"] == "preserved" and not u.get("functions_lost") and not u.get("parent_changed"):
            continue
        name = (f"{u['before']['name']}" + (f" ({u['before']['short']})" if u["before"].get("short") else "")) \
            if u["before"] else (u["after"][0]["name"] + (f" ({u['after'][0]['short']})" if u["after"][0].get("short") else ""))
        succ = ", ".join(a["name"] + (f" ({a['short']})" if a.get("short") else "") for a in u["after"]) \
            if u["before"] else ", ".join(u.get("sources", []))
        arrow = f" → {succ}" if succ and u["before"] else (f" ← {succ}" if succ else "")
        f = next((x for x in result["findings"] if x.get("id") == u.get("finding_id")), None)
        st_items.append({
            "finding_id": u.get("finding_id"),
            "severity": f["severity"] if f else "info",
            "text": f"{name}: {t['status'].get(u['status'], u['status'])}{arrow}.",
            "sources": [ref_for(e, lang) for e in u.get("evidence", [])[:3]],
            "review": reviews.get(u.get("finding_id") or "", "pending"),
        })
    preserved = [u for u in result["units"] if u["status"] == "preserved"]
    para = []
    if preserved:
        para.append(f"{t['status']['preserved'].capitalize()}: " + ", ".join(
            u["before"]["name"] + (f" ({u['before']['short']})" if u["before"].get("short") else "") for u in preserved) + ".")
    sections.append({"id": "structure", "title": t["s_structure"], "paragraphs": para, "items": st_items})

    # 4. Потери
    loss_items = [
        _item(f, t["loss_item"].format(unit=f["units"][0] if f["units"] else "",
                                       text=short(f["evidence"][0].get("text", ""), 220)), lang, reviews)
        for f in sorted([f for f in findings if f["type"] == "loss"], key=lambda f: SEV_ORDER.get(f["severity"], 9))
    ]
    sections.append({"id": "losses", "title": t["s_losses"], "paragraphs": [] if loss_items else [t["none_losses"]],
                     "items": loss_items})

    # 5. Дублирование
    dup_items = []
    for f in sorted([f for f in findings if f["type"] == "duplication"], key=lambda f: SEV_ORDER.get(f["severity"], 9)):
        key = "dup_shared" if "общей и частной" in f["title"] else "dup_item"
        dup_items.append(_item(f, t[key].format(units=", ".join(f["units"]),
                                                text=short(f["evidence"][0].get("text", ""), 200)), lang, reviews))
    sections.append({"id": "duplication", "title": t["s_dups"], "paragraphs": [] if dup_items else [t["none_dups"]],
                     "items": dup_items})

    # 6. Конфликты
    c_items = []
    for f in sorted([f for f in findings if f["type"] in ("conflict", "improvement")],
                    key=lambda f: SEV_ORDER.get(f["severity"], 9)):
        sub = f.get("subtype")
        if sub == "sod":
            text = t["sod_item"].format(unit=f["units"][0] if f["units"] else "",
                                        title=f["title"].split(": ", 1)[-1].rsplit(" — ", 1)[0])
        elif sub == "dual_subordination":
            text = t["dual_item"].format(pos=f["title"].split("«", 1)[-1].rstrip("»"), units=", ".join(f["units"]))
        elif sub == "declared":
            text = t["declared_item"]
        else:
            text = t["improve_item"].format(pos=f["title"].split("«", 1)[-1].rstrip("»"))
        c_items.append(_item(f, text, lang, reviews))
    sections.append({"id": "conflicts", "title": t["s_conflicts"],
                     "paragraphs": [] if c_items else [t["none_conflicts"]], "items": c_items})

    # 7–8. Опциональные
    req = result.get("requirements")
    if req and req.get("items"):
        items = [_item(f, t["req_item"].format(text=short(f["evidence"][0].get("text", ""), 200)), lang, reviews)
                 for f in findings if f["type"] == "requirement_gap"]
        sections.append({"id": "requirements", "title": t["s_req"], "paragraphs": [t["req_stats"].format(
            n=len(req["items"]), c=req["covered"], p=req["partial"], g=req["gaps"])], "items": items})
    bench = result.get("benchmark")
    if bench and bench.get("items"):
        items = [{"finding_id": None, "severity": "info", "text": t["bench_item"].format(
            unit=b["unit"], other=b["benchmark_unit"], doc=b["benchmark_doc"]),
            "sources": [ref_for(e, lang) for e in b["missing"][:3]], "review": "pending"} for b in bench["items"]]
        sections.append({"id": "benchmark", "title": t["s_bench"], "paragraphs": [], "items": items})

    # 9. Рекомендации
    rec_items = []
    for f in sorted(findings, key=lambda f: SEV_ORDER.get(f["severity"], 9)):
        if f.get("recommendation") and f["severity"] != "info":
            text = recommendation_text(f, result["units"], lang) if lang != "ru" else ""
            rec_items.append(_item(f, text or f["recommendation"], lang, reviews))
    sections.append({"id": "recommendations", "title": t["s_recs"], "paragraphs": [], "items": rec_items[:25]})

    # 10. Ограничения
    sections.append({"id": "limitations", "title": t["s_limits"], "paragraphs": [t["limits"]], "items": []})

    return {
        "title": t["title"],
        "lang": lang,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sections": sections,
        "summary_method": method,
    }


def _llm_summary(llm: LLMClient, result: dict[str, Any], findings: list[dict[str, Any]]) -> str | None:
    data = {
        "summary": {k: v for k, v in result["summary"].items() if k != "embeddings"},
        "units": [{"status": u["status"],
                   "before": (u["before"] or {}).get("name"),
                   "after": [a["name"] for a in u["after"]]} for u in result["units"] if u["status"] != "preserved"],
        "findings": [{"id": f["id"], "type": f["type"], "severity": f["severity"], "title": f["title"],
                      "units": f.get("units", [])} for f in findings if f["severity"] != "info"][:40],
    }
    try:
        text = llm.complete(prompts.SYSTEM_ANALYST, prompts.SUMMARY.format(data=json.dumps(data, ensure_ascii=False)),
                            max_tokens=900)
    except LLMError:
        return None
    ids = set(re.findall(r"F-\d{3}", text))
    valid = {f["id"] for f in findings}
    if not ids or not ids <= valid:
        return None  # резюме без ссылок или со ссылками на несуществующие выводы отбрасывается
    return text.strip()
