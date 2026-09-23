"""Хранилище настроек (в БД), редактируемых из панели администратора.

Значения по умолчанию берутся из переменных окружения / кода, а изменения
администратора сохраняются в таблицу `settings` и имеют приоритет.
"""
from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Setting


def _llm_defaults() -> dict[str, Any]:
    s = get_settings()
    return {
        "provider": s.llm_provider,  # none | openai
        "base_url": s.llm_base_url,
        "api_key": s.llm_api_key,
        "model": s.llm_model,
        "vision_model": s.llm_vision_model,
        "embed_model": s.llm_embed_model,
        "temperature": s.llm_temperature,
        "timeout": s.llm_timeout,
        # Какие шаги анализа разрешено выполнять модели
        "use_for_verification": True,
        "use_for_conclusion": True,
        "use_for_extraction": True,
        "use_for_chat": True,
    }


ANALYSIS_DEFAULTS: dict[str, Any] = {
    # Пороги сходства (0..1) для сопоставления функций
    "match_high": 0.62,  # не ниже — функция считается сохранённой
    "match_low": 0.38,  # ниже — функция считается утраченной
    "duplicate": 0.66,  # не ниже — функции разных подразделений считаются дублирующими
    "unit_name": 0.72,  # сходство названий для сопоставления подразделений
    "min_function_words": 3,
    # Типовые формулировки, которые не считаются дублированием
    "generic_phrases": [
        "осуществляет выполнение прочих поручений",
        "выполнение иных поручений",
        "взаимодействует с руководителями общества по всему кругу вопросов",
        "выносит предложения по повышению профессионального уровня",
        "ведет делопроизводство",
        "иные функции в соответствии с законодательством",
        "другие функции необходимые для решения задач",
    ],
    # Какие виды пунктов анализировать как функционал
    "function_kinds": ["function", "task", "duty", "right"],
}

ORG_DEFAULTS: dict[str, Any] = {
    "company_name": "АО «Компания»",
    "company_name_kz": "«Компания» АҚ",
    "city": "Астана",
    # в родительном падеже: «УТВЕРЖДЕНО приказом Председателя Правления …»
    "approver_title": "Председателя Правления",
    "approver_title_kz": "Басқарма Төрағасының",
    "approver_name": "",
}

DEFAULTS = {
    "llm": _llm_defaults,
    "analysis": lambda: copy.deepcopy(ANALYSIS_DEFAULTS),
    "org": lambda: copy.deepcopy(ORG_DEFAULTS),
}


def get_setting(db: Session, key: str) -> dict[str, Any]:
    base = DEFAULTS[key]()
    row = db.get(Setting, key)
    if row and isinstance(row.value, dict):
        base.update(row.value)
    return base


def put_setting(db: Session, key: str, value: dict[str, Any]) -> dict[str, Any]:
    allowed = set(DEFAULTS[key]().keys())
    clean = {k: v for k, v in value.items() if k in allowed}
    row = db.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=clean)
        db.add(row)
    else:
        merged = dict(row.value or {})
        merged.update(clean)
        row.value = merged
    db.commit()
    return get_setting(db, key)


def reset_setting(db: Session, key: str) -> dict[str, Any]:
    row = db.get(Setting, key)
    if row:
        db.delete(row)
        db.commit()
    return get_setting(db, key)
