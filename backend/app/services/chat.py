"""Диалог с агентом по документам проекта (RAG с обязательными ссылками на источники).

Инструменты агента: поиск по пунктам документов (TF-IDF/эмбеддинги) и поиск по выводам
анализа. Модель получает только найденные фрагменты и обязана ссылаться на них [S1]…;
ответ без ссылок заменяется списком найденных фрагментов (без модели — то же самое).
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from ..analysis import prompts
from ..analysis.text import Similarity, short
from ..models import AnalysisRun, Document
from .llm import LLMClient, LLMError

INTENTS = {
    "loss": re.compile(r"потер|утрач|пропал|жоғал", re.I),
    "duplication": re.compile(r"дубл|пересеч|қайтал", re.I),
    "conflict": re.compile(r"конфликт|совмещ|қақтығ", re.I),
    "reorganization": re.compile(r"реорганиз|созда|упраздн|переимен|структур|құрыл", re.I),
}


def _sources(db: Session, project_id: int, question: str, llm: LLMClient | None, k: int = 8) -> list[dict[str, Any]]:
    docs = db.query(Document).filter_by(project_id=project_id, status="parsed").all()
    pool: list[dict[str, Any]] = []
    for d in docs:
        title = d.title or d.filename
        for c in (d.parsed or {}).get("clauses", []):
            if c.get("kind") == "toc" or len(c.get("text", "")) < 15:
                continue
            pool.append({"type": "clause", "side": d.side, "doc_id": d.id, "doc_title": title,
                         "clause_id": c["id"], "ref_display": c.get("ref_display"), "page": c.get("page"),
                         "text": c.get("text", ""), "unit": c.get("actor", "")})
    if not pool:
        return []
    embed = llm.embed if (llm and llm.embeddings_enabled) else None
    sim = Similarity(embed=embed)
    scores = sim.matrix([question], [p["text"] + " " + p.get("unit", "") for p in pool])[0]
    order = scores.argsort()[::-1][:k]
    found = [pool[i] | {"score": round(float(scores[i]), 3)} for i in order if scores[i] > 0.05]

    run = (db.query(AnalysisRun).filter_by(project_id=project_id, status="done")
           .order_by(AnalysisRun.id.desc()).first())
    if run and run.result:
        wanted = [t for t, rx in INTENTS.items() if rx.search(question)]
        for f in run.result.get("findings", []):
            if f["type"] in wanted and len(found) < k + 6:
                found.append({"type": "finding", "finding_id": f["id"], "text": f"{f['title']}. {f['description']}",
                              "doc_title": "Результаты анализа", "ref_display": f["id"],
                              "evidence": f.get("evidence", [])[:2]})
    return found


def answer(db: Session, project_id: int, question: str, llm: LLMClient) -> dict[str, Any]:
    use_llm = llm.allowed("chat")
    sources = _sources(db, project_id, question, llm if use_llm else None)
    for i, s in enumerate(sources, start=1):
        s["sid"] = f"S{i}"
    if not sources:
        return {"content": "В документах проекта не найдено фрагментов по этому вопросу. Загрузите документы "
                           "или переформулируйте вопрос.", "sources": [], "mode": "retrieval"}
    if use_llm:
        ctx = "\n".join(
            f"[{s['sid']}] {s.get('doc_title', '')}, {s.get('ref_display', '')}"
            + (f" ({'до' if s.get('side') == 'before' else 'после' if s.get('side') == 'after' else s.get('side')})"
               if s.get("side") else "")
            + f": {short(s['text'], 700)}" for s in sources)
        try:
            text = llm.complete(prompts.CHAT_SYSTEM, f"ФРАГМЕНТЫ:\n{ctx}\n\nВОПРОС: {question}", max_tokens=900)
            cited = set(re.findall(r"\[(S\d+)\]", text))
            valid = {s["sid"] for s in sources}
            if cited and cited <= valid:
                used = [s for s in sources if s["sid"] in cited]
                return {"content": text, "sources": used, "mode": "llm", "model": llm.model}
        except LLMError:
            pass
    lines = ["Найдены релевантные фрагменты документов (ИИ-модель не подключена или ответ не прошёл проверку ссылок):"]
    for s in sources[:6]:
        lines.append(f"• [{s['sid']}] {s.get('doc_title', '')}, {s.get('ref_display', '')}: «{short(s['text'], 220)}»")
    return {"content": "\n".join(lines), "sources": sources[:6], "mode": "retrieval"}
