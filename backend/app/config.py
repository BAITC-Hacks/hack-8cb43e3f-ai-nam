"""Конфигурация приложения.

Все параметры читаются из переменных окружения (или файла `.env` в корне проекта).
Полный список с пояснениями — в `.env.example`.
"""
from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "OrgStruct AI"
    data_dir: Path = ROOT_DIR / "data"
    database_url: str = ""  # по умолчанию SQLite в data_dir
    secret_key: str = ""  # если пусто — генерируется и сохраняется в data_dir/.secret
    access_token_minutes: int = 60 * 12
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_upload_mb: int = 50

    # Первичный администратор (создаётся при первом запуске)
    admin_email: str = "admin@example.com"
    admin_password: str = "admin12345"
    # Демо-пользователи (аналитик и наблюдатель) и демо-проект
    seed_demo: bool = True

    # ИИ-модель: любой OpenAI-совместимый сервер (Ollama, vLLM, LM Studio, llama.cpp, OpenAI…)
    # LLM_PROVIDER=none — работа без модели (детерминированные алгоритмы + шаблоны).
    llm_provider: str = "none"  # none | openai
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = ""
    llm_model: str = "qwen2.5:7b-instruct"
    llm_vision_model: str = ""
    llm_embed_model: str = ""
    llm_timeout: int = 120
    llm_temperature: float = 0.1

    # OCR
    tesseract_cmd: str = ""  # путь к tesseract, если его нет в PATH
    ocr_langs: str = "rus+kaz+eng"

    # Собранный фронтенд (для режима одного контейнера)
    frontend_dist: Path = ROOT_DIR / "frontend" / "dist"

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'app.db').as_posix()}"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def generated_dir(self) -> Path:
        return self.data_dir / "generated"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.uploads_dir, self.generated_dir):
            d.mkdir(parents=True, exist_ok=True)

    def resolved_secret(self) -> str:
        if self.secret_key:
            return self.secret_key
        self.ensure_dirs()
        path = self.data_dir / ".secret"
        if path.exists():
            return path.read_text().strip()
        key = secrets.token_urlsafe(48)
        path.write_text(key)
        return key


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
