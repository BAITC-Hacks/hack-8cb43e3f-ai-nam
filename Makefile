.PHONY: help setup dev backend frontend build test demo-data docker docker-ollama mock-llm clean

PY ?= python3
VENV = .venv
BIN = $(VENV)/bin

help:
	@echo "make setup        — установить зависимости (Python venv + npm) и собрать интерфейс"
	@echo "make dev          — режим разработки: backend :8000 + frontend :5173 (hot reload)"
	@echo "make backend      — только backend (с собранным интерфейсом) на http://localhost:8000"
	@echo "make test         — автотесты backend (pytest)"
	@echo "make demo-data    — пересоздать контрольный комплект samples/demo"
	@echo "make mock-llm     — мок OpenAI-совместимой модели на :11500 (проверка ИИ-режима без GPU)"
	@echo "make docker       — docker compose up --build (http://localhost:8000)"
	@echo "make docker-ollama— то же + локальная модель в Ollama"

setup:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -r backend/requirements-dev.txt
	cd frontend && npm ci && npm run build

dev:
	./scripts/dev.sh

backend:
	cd backend && ../$(BIN)/uvicorn app.main:app --host 0.0.0.0 --port 8000

frontend:
	cd frontend && npm run dev

build:
	cd frontend && npm run build

test:
	cd backend && ../$(BIN)/python -m pytest -q

demo-data:
	$(BIN)/python scripts/make_demo.py

mock-llm:
	$(BIN)/python scripts/mock_llm_server.py --port 11500

docker:
	docker compose up -d --build

docker-ollama:
	docker compose --profile ollama up -d --build

clean:
	rm -rf data frontend/dist
