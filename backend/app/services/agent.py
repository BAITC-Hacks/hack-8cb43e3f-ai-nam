"""ИИ-агент анализа реорганизации: оркестрация шагов с журналом (trace) для интерфейса.

План агента фиксирован и прозрачен для пользователя:
  1. Разбор документов (DOCX/PDF/Excel/фото → пункты с номерами)
  2. Извлечение оргструктуры и функций по сторонам «до»/«после»
  3. Сопоставление подразделений и функций, поиск потерь, дублирования, конфликтов
  4. Опционально: требования (законодательство/стандарты) и практика других операторов
  5. Проверка пограничных выводов ИИ-моделью (если подключена)
  6. Рекомендации
  7. Итоговое заключение со ссылками на источники
"""
from __future__ import annotations

import threading
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from sqlalchemy.orm import Session

from ..analysis.compare import compare
from ..analysis.conclusion import build_conclusion
from ..analysis.extras import benchmark, check_requirements
from ..analysis.recommend import add_recommendations
from ..analysis.structure import build_structure
from ..analysis.text import Similarity
from ..analysis.verify import verify_findings, verify_function_map
from ..db import SessionLocal
from ..models import AnalysisRun, Document, FindingReview, Project, Structure
from .documents import parse_document
from .llm import LLMClient, LLMError
from .settings_store import get_setting

STEPS: list[tuple[str, str]] = [
    ("parse", "Разбор документов"),
    ("extract", "Извлечение оргструктуры и функций"),
    ("compare", "Сопоставление подразделений и функций"),
    ("extras", "Требования и практика других операторов"),
    ("verify", "Проверка пограничных выводов ИИ-моделью"),
    ("recommend", "Формирование рекомендаций"),
    ("conclusion", "Итоговое заключение"),
]


def doc_payload(d: Document) -> dict[str, Any]:
    parsed = d.parsed or {}
    return {"id": d.id, "side": d.side, "filename": d.filename, "title": d.title or d.filename,
            "doc_kind": d.doc_kind, "edition": parsed.get("edition", ""), "parsed": parsed}


def get_llm(db: Session) -> LLMClient:
    return LLMClient(get_setting(db, "llm"))


def structure_for_side(db: Session, project: Project, side: str, docs: list[dict[str, Any]],
                       kinds: list[str], prefer_saved: bool = True) -> tuple[dict[str, Any], str]:
    saved = db.query(Structure).filter_by(project_id=project.id, side=side).first()
    if saved and prefer_saved and saved.source in ("manual", "import") and saved.data.get("units"):
        return saved.data, saved.source
    data = build_structure(side, docs, kinds)
    if saved:
        saved.data, saved.source = data, "auto"
    else:
        db.add(Structure(project_id=project.id, side=side, data=data, source="auto"))
    db.commit()
    return data, "auto"


class _Runner:
    def __init__(self, run_id: int) -> None:
        self.run_id = run_id
        self.db = SessionLocal()
        self.run = self.db.get(AnalysisRun, run_id)
        self.trace: list[dict[str, Any]] = []

    def _save(self) -> None:
        self.run.trace = [dict(x) for x in self.trace]
        self.db.commit()

    @contextmanager
    def step(self, key: str, title: str, index: int) -> Iterator[dict[str, Any]]:
        entry = {"step": key, "title": title, "status": "running", "started_at": time.time(), "log": [],
                 "summary": ""}
        self.trace.append(entry)
        self.run.current_step = key
        self.run.progress = round(index / len(STEPS), 3)
        self._save()
        try:
            yield entry
            if entry["status"] == "running":
                entry["status"] = "done"
        except Exception as exc:
            entry["status"] = "error"
            entry["summary"] = f"Ошибка: {exc}"
            raise
        finally:
            entry["finished_at"] = time.time()
            entry["duration"] = round(entry["finished_at"] - entry["started_at"], 2)
            self._save()

    def execute(self) -> None:
        run, db = self.run, self.db
        project = db.get(Project, run.project_id)
        options = run.options or {}
        settings = get_setting(db, "analysis")
        settings.update({k: v for k, v in options.get("thresholds", {}).items() if k in settings})
        kinds = settings.get("function_kinds", ["function", "task", "duty", "right"])
        llm = get_llm(db)
        use_llm = llm.enabled and options.get("use_llm", True)
        run.status = "running"
        run.llm_model = llm.model if use_llm else ""
        self._save()

        # 1. Разбор
        with self.step("parse", STEPS[0][1], 0) as st:
            docs = db.query(Document).filter_by(project_id=project.id).order_by(Document.id).all()
            for d in docs:
                if d.status != "parsed":
                    st["log"].append(f"Разбор: {d.filename}")
                    self._save()
                    parse_document(db, d)
            ok = [d for d in docs if d.status == "parsed"]
            failed = [d for d in docs if d.status != "parsed"]
            for d in failed:
                st["log"].append(f"Не удалось разобрать {d.filename}: {d.error}")
            st["summary"] = (f"Документов: {len(ok)} (до — {sum(d.side == 'before' for d in ok)}, "
                             f"после — {sum(d.side == 'after' for d in ok)}), пунктов: {sum(d.clause_count for d in ok)}")
            payloads = [doc_payload(d) for d in ok]
            if not any(d["side"] == "before" for d in payloads) or not any(d["side"] == "after" for d in payloads):
                raise ValueError("Нужны документы и «до», и «после» реорганизации")

        by_side = {s: [d for d in payloads if d["side"] == s] for s in ("before", "after", "requirements", "benchmark")}
        titles = {d["id"]: (d["title"] or d["filename"]) + (f" (ред. {d['edition']})" if d.get("edition") else "")
                  for d in payloads}

        # 2. Структура
        with self.step("extract", STEPS[1][1], 1) as st:
            prefer = options.get("use_edited_structure", True)
            before, src_b = structure_for_side(db, project, "before", by_side["before"], kinds, prefer)
            after, src_a = structure_for_side(db, project, "after", by_side["after"], kinds, prefer)
            st["log"].append(f"«До»: подразделений {len(before['units'])}, функций "
                             f"{sum(len(u['functions']) for u in before['units'])} (источник: {src_b})")
            st["log"].append(f"«После»: подразделений {len(after['units'])}, функций "
                             f"{sum(len(u['functions']) for u in after['units'])} (источник: {src_a})")
            st["summary"] = (f"До: {len(before['units'])} подразделений; после: {len(after['units'])} подразделений")

        # 3. Сравнение
        with self.step("compare", STEPS[2][1], 2) as st:
            embed = None
            if use_llm and llm.embeddings_enabled:
                def embed(texts: list[str]):  # noqa: E306
                    return llm.embed(texts)
            sim = Similarity(embed=embed)
            from ..analysis.compare import Comparator

            cmp = Comparator(before, after, settings, sim, titles)
            result = cmp.run()
            s = result["summary"]
            st["summary"] = (f"Потерь: {s['lost']}, дублирований: {s['duplicates']}, конфликтов: {s['conflicts']}"
                             + (" (с эмбеддингами)" if s.get("embeddings") else ""))
            st["log"].append(f"Статусы подразделений: {s['units_by_status']}")
            st["log"].append(f"Статусы функций: {s['functions_by_status']}")

        # 4. Опционально
        with self.step("extras", STEPS[3][1], 3) as st:
            if by_side["requirements"]:
                result["requirements"] = check_requirements(cmp, by_side["requirements"])
                r = result["requirements"]
                st["log"].append(f"Требования: отражены {r['covered']}, частично {r['partial']}, не отражены {r['gaps']}")
            if by_side["benchmark"]:
                focus = {a["id"] for u in result["units"] if u["status"] != "preserved" for a in u["after"]}
                result["benchmark"] = benchmark(cmp, by_side["benchmark"], kinds, focus)
                st["log"].append(f"Сопоставлено с практикой: {len(result['benchmark']['items'])} подразделений")
            if not by_side["requirements"] and not by_side["benchmark"]:
                st["status"] = "skipped"
                st["summary"] = "Документы с требованиями и практикой других операторов не загружены"
            else:
                st["summary"] = "; ".join(st["log"])

        # 5. Проверка моделью
        with self.step("verify", STEPS[4][1], 4) as st:
            if use_llm and llm.allowed("verification"):
                def log(msg: str) -> None:
                    st["log"].append(msg)
                    self._save()
                try:
                    s1 = verify_function_map(llm, result["function_map"], result["findings"], log)
                    s2 = verify_findings(llm, result["findings"], log)
                    st["summary"] = (f"Проверено сопоставлений: {s1['checked']}, выводов: {s2['checked']}; "
                                     f"оспорено: {s2['disputed']}")
                except LLMError as exc:
                    st["status"] = "skipped"
                    st["summary"] = f"Модель недоступна: {exc}"
            else:
                st["status"] = "skipped"
                st["summary"] = "ИИ-модель не подключена — используются только детерминированные правила"

        # 6. Рекомендации
        with self.step("recommend", STEPS[5][1], 5) as st:
            recs = add_recommendations(result)
            result["recommendations"] = recs
            st["summary"] = f"Рекомендаций: {len(recs)}"

        # 7. Заключение
        with self.step("conclusion", STEPS[6][1], 6) as st:
            docs_meta = [{"id": d["id"], "side": d["side"], "filename": d["filename"], "title": d["title"],
                          "edition": d.get("edition")} for d in payloads]
            result["conclusion"] = build_conclusion(result, docs_meta, "ru", {}, llm if use_llm else None,
                                                    project.name)
            st["summary"] = result["conclusion"]["summary_method"]

        result["documents"] = [{"id": d["id"], "side": d["side"], "filename": d["filename"], "title": d["title"],
                                "edition": d.get("edition"), "doc_kind": d.get("doc_kind")} for d in payloads]
        result["structures"] = {"before": {"source": src_b, "units": len(before["units"])},
                                "after": {"source": src_a, "units": len(after["units"])}}
        result["settings"] = {k: settings[k] for k in ("match_high", "match_low", "duplicate", "unit_name")}
        result["llm"] = {"enabled": use_llm, "model": llm.model if use_llm else "", "calls": llm.stats.calls,
                         "errors": llm.stats.errors, "seconds": round(llm.stats.seconds, 1),
                         "embeddings": bool(result["summary"].get("embeddings"))}
        run.result = result
        run.status = "done"
        run.progress = 1.0
        run.current_step = ""
        run.finished_at = datetime.now(timezone.utc)
        project.status = "analyzed"
        self._save()

    def __call__(self) -> None:
        try:
            self.execute()
        except Exception as exc:  # noqa: BLE001
            self.run.status = "error"
            self.run.error = f"{exc}"
            self.run.finished_at = datetime.now(timezone.utc)
            self.trace.append({"step": "error", "title": "Ошибка", "status": "error", "summary": str(exc),
                               "log": traceback.format_exc().splitlines()[-6:]})
            self._save()
        finally:
            self.db.close()


def start_analysis(db: Session, project: Project, user_id: int | None, options: dict[str, Any],
                   background: bool = True) -> AnalysisRun:
    run = AnalysisRun(project_id=project.id, status="pending", options=options, started_by=user_id,
                      trace=[{"step": k, "title": t, "status": "pending", "log": [], "summary": ""} for k, t in STEPS])
    db.add(run)
    db.commit()
    db.refresh(run)
    runner = _Runner(run.id)
    runner.trace = []
    if background:
        threading.Thread(target=runner, daemon=True, name=f"analysis-{run.id}").start()
    else:
        runner()
        db.refresh(run)
    return run


def reviews_map(db: Session, run_id: int) -> dict[str, str]:
    return {r.finding_id: r.status for r in db.query(FindingReview).filter_by(run_id=run_id).all()}
