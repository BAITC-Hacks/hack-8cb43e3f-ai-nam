"""Мок OpenAI-совместимого сервера модели — для тестов и проверки ИИ-режима без GPU.

Отвечает детерминированно, соблюдая форматы промптов проекта (JSON-вердикты, ссылки [F-xxx]/[S1]).
Запуск:  python scripts/mock_llm_server.py --port 11500
Затем в админ-панели: base_url = http://localhost:11500/v1, model = mock-model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _embed(text: str, dim: int = 64) -> list[float]:
    vec = [0.0] * dim
    for tok in re.findall(r"\w{3,}", text.lower()):
        h = int(hashlib.md5(tok[:6].encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _reply(messages: list[dict]) -> str:
    text = " ".join(m["content"] if isinstance(m.get("content"), str) else json.dumps(m.get("content"), ensure_ascii=False)
                    for m in messages)
    if '"verdict"' in text:
        return json.dumps({"verdict": "different", "reason": "Формулировки описывают разные действия."}, ensure_ascii=False)
    if '"is_duplicate"' in text:
        return json.dumps({"is_duplicate": True, "reason": "Одна и та же работа закреплена за двумя подразделениями.",
                           "recommendation": "Закрепить функцию за одним подразделением."}, ensure_ascii=False)
    if '"is_conflict"' in text:
        return json.dumps({"is_conflict": True, "reason": "Подразделение контролирует собственные действия.",
                           "recommendation": "Передать контроль независимому подразделению."}, ensure_ascii=False)
    if '"units": [{"id"' in text or "схема организационной структуры" in text.lower():
        return json.dumps({"units": [{"id": "1", "name": "Правление", "parent_id": None}]}, ensure_ascii=False)
    if "Переведи на казахский" in text:
        return "Қазақ тіліндегі аударма (мок): " + text[-120:]
    ids = re.findall(r"F-\d{3}", text)
    if "аналитическое резюме" in text.lower() and ids:
        uniq = list(dict.fromkeys(ids))[:3]
        return ("По результатам анализа выявлены изменения структуры и риски, требующие внимания "
                + " ".join(f"[{i}]" for i in uniq) + ".")
    sids = re.findall(r"\[(S\d+)\]", text)
    if sids:
        return f"Согласно найденным фрагментам, ответ содержится в документах проекта [{sids[0]}]."
    return "готов"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # тихий режим
        pass

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            self._send(200, {"data": [{"id": "mock-model"}, {"id": "mock-embed"}]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length) or b"{}")
        if self.path.endswith("/chat/completions"):
            content = _reply(data.get("messages", []))
            self._send(200, {"choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
                             "usage": {"prompt_tokens": 10, "completion_tokens": 10}})
        elif self.path.endswith("/embeddings"):
            inputs = data.get("input", [])
            inputs = [inputs] if isinstance(inputs, str) else inputs
            self._send(200, {"data": [{"index": i, "embedding": _embed(t)} for i, t in enumerate(inputs)]})
        else:
            self._send(404, {"error": "not found"})


def start(port: int = 0) -> tuple[ThreadingHTTPServer, int]:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=11500)
    args = ap.parse_args()
    srv, port = start(args.port)
    print(f"Mock LLM: http://127.0.0.1:{port}/v1  (model: mock-model, embeddings: mock-embed). Ctrl+C — выход.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()
