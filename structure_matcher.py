"""Совместимость с исходным прототипом команды.

Функция compare_departments перенесена в backend (backend/app/analysis/departments.py)
и реализована поверх движка сравнения. Этот модуль оставлен, чтобы прежний импорт
`from structure_matcher import compare_departments` продолжал работать из корня репозитория.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from app.analysis.departments import compare_departments  # noqa: E402,F401

__all__ = ["compare_departments"]
