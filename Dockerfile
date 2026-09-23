# Один контейнер: FastAPI отдаёт и API, и собранный интерфейс (http://localhost:8000)

# ---------- 1. сборка интерфейса ----------
FROM node:22-slim AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 2. backend + OCR + PDF ----------
FROM python:3.11-slim
# LibreOffice нужен только для экспорта в PDF и чтения .doc/.rtf; отключите для облегчённого образа:
#   docker compose build --build-arg INSTALL_LIBREOFFICE=false
ARG INSTALL_LIBREOFFICE=true
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-rus tesseract-ocr-kaz tesseract-ocr-eng \
      fonts-dejavu-core libglib2.0-0 curl \
 && if [ "$INSTALL_LIBREOFFICE" = "true" ]; then \
      apt-get install -y --no-install-recommends libreoffice-writer-nogui; fi \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend/ backend/
COPY samples/ samples/
COPY scripts/ scripts/
COPY structure_matcher.py ./
COPY --from=frontend /fe/dist frontend/dist

VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
