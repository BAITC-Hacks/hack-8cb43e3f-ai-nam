"""Клиент ИИ-модели: любой OpenAI-совместимый сервер.

Проверенные варианты (см. docs/MODELS.md):
  * Ollama        — base_url http://localhost:11434/v1, model qwen2.5:7b-instruct
  * LM Studio     — base_url http://localhost:1234/v1
  * vLLM          — base_url http://localhost:8001/v1
  * llama.cpp     — base_url http://localhost:8080/v1
  * OpenAI и др.  — base_url https://api.openai.com/v1 + api_key

Если provider = "none" или сервер недоступен, система работает в детерминированном
режиме (правила + текстовое сходство + шаблоны заключения) — все функции доступны.
"""
from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


class LLMError(RuntimeError):
    pass


@dataclass
class LLMStats:
    calls: int = 0
    errors: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    last_error: str = ""
    log: list[dict[str, Any]] = field(default_factory=list)


def extract_json(text: str) -> Any:
    """Достаёт JSON из ответа модели (в т.ч. из ```json блоков и текста вокруг)."""
    if not text:
        raise ValueError("пустой ответ")
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = text.find(open_ch)
        end = text.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("ответ модели не является JSON")


class LLMClient:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.provider = (cfg.get("provider") or "none").lower()
        self.base_url = (cfg.get("base_url") or "").rstrip("/")
        self.model = cfg.get("model") or ""
        self.vision_model = cfg.get("vision_model") or ""
        self.embed_model = cfg.get("embed_model") or ""
        self.timeout = float(cfg.get("timeout") or 120)
        self.temperature = float(cfg.get("temperature") or 0.1)
        self.stats = LLMStats()
        self._json_mode_supported = True

    # ------------------------------------------------------------------ состояние

    @property
    def enabled(self) -> bool:
        return self.provider not in ("", "none", "off") and bool(self.base_url) and bool(self.model)

    @property
    def vision_enabled(self) -> bool:
        return self.provider not in ("", "none", "off") and bool(self.base_url) and bool(self.vision_model)

    @property
    def embeddings_enabled(self) -> bool:
        return self.provider not in ("", "none", "off") and bool(self.base_url) and bool(self.embed_model)

    def allowed(self, purpose: str) -> bool:
        return self.enabled and bool(self.cfg.get(f"use_for_{purpose}", True))

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        key = self.cfg.get("api_key") or ""
        if key:
            h["Authorization"] = f"Bearer {key}"
        return h

    # ------------------------------------------------------------------ вызовы

    def _post(self, path: str, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        t0 = time.time()
        self.stats.calls += 1
        try:
            with httpx.Client(timeout=timeout or self.timeout) as client:
                r = client.post(f"{self.base_url}{path}", headers=self._headers(), json=payload)
            if r.status_code >= 400:
                raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
            data = r.json()
        except httpx.HTTPError as exc:
            self.stats.errors += 1
            self.stats.last_error = str(exc)
            raise LLMError(f"Сервер модели недоступен ({self.base_url}): {exc}") from exc
        except LLMError as exc:
            self.stats.errors += 1
            self.stats.last_error = str(exc)
            raise
        finally:
            self.stats.seconds += time.time() - t0
        usage = data.get("usage") or {}
        self.stats.prompt_tokens += int(usage.get("prompt_tokens") or 0)
        self.stats.completion_tokens += int(usage.get("completion_tokens") or 0)
        return data

    def chat(self, messages: list[dict[str, Any]], *, json_mode: bool = False, model: str | None = None,
             max_tokens: int = 1500, temperature: float | None = None, tools: list[dict] | None = None) -> dict:
        """Возвращает message-объект ответа (content, tool_calls)."""
        if not self.enabled:
            raise LLMError("ИИ-модель не подключена")
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        if json_mode and self._json_mode_supported:
            payload["response_format"] = {"type": "json_object"}
        try:
            data = self._post("/chat/completions", payload)
        except LLMError as exc:
            if json_mode and "response_format" in payload and "HTTP 4" in str(exc):
                self._json_mode_supported = False
                payload.pop("response_format", None)
                data = self._post("/chat/completions", payload)
            else:
                raise
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("Пустой ответ модели")
        msg = choices[0].get("message") or {}
        self.stats.log.append({"model": payload["model"], "chars": len(msg.get("content") or "")})
        return msg

    def complete(self, system: str, user: str, **kw: Any) -> str:
        msg = self.chat([{"role": "system", "content": system}, {"role": "user", "content": user}], **kw)
        content = msg.get("content") or ""
        # некоторые модели (reasoning) возвращают <think>…</think>
        return re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()

    def complete_json(self, system: str, user: str, retries: int = 1, **kw: Any) -> Any:
        last: Exception | None = None
        for attempt in range(retries + 1):
            text = self.complete(system, user if attempt == 0 else
                                 user + "\n\nВерни ТОЛЬКО корректный JSON без пояснений.", json_mode=True, **kw)
            try:
                return extract_json(text)
            except ValueError as exc:
                last = exc
        raise LLMError(f"Модель вернула некорректный JSON: {last}")

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        if not self.embeddings_enabled or not texts:
            return None
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            batch = [t[:2000] for t in texts[i:i + 64]]
            data = self._post("/embeddings", {"model": self.embed_model, "input": batch})
            items = sorted(data.get("data") or [], key=lambda d: d.get("index", 0))
            out.extend(d["embedding"] for d in items)
        return out if len(out) == len(texts) else None

    def vision_json(self, image_bytes: bytes, prompt: str, mime: str = "image/png") -> Any:
        if not self.vision_enabled:
            raise LLMError("Vision-модель не настроена")
        b64 = base64.b64encode(image_bytes).decode()
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }]
        msg = self.chat(messages, json_mode=True, model=self.vision_model, max_tokens=4000)
        return extract_json(re.sub(r"<think>.*?</think>", "", msg.get("content") or "", flags=re.S))

    # ------------------------------------------------------------------ сервис

    def list_models(self) -> list[str]:
        try:
            with httpx.Client(timeout=10) as client:
                r = client.get(f"{self.base_url}/models", headers=self._headers())
            r.raise_for_status()
            return sorted(m.get("id", "") for m in r.json().get("data", []) if m.get("id"))
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMError(f"Не удалось получить список моделей: {exc}") from exc

    def health(self) -> dict[str, Any]:
        """Проверка подключения: короткий запрос к модели."""
        if not self.enabled:
            return {"ok": False, "mode": "demo", "message": "Модель не подключена — работает детерминированный режим"}
        t0 = time.time()
        try:
            reply = self.complete("Ты — помощник. Отвечай кратко.", "Ответь одним словом: готов?", max_tokens=20)
            result: dict[str, Any] = {"ok": True, "latency_ms": int((time.time() - t0) * 1000), "reply": reply[:100],
                                      "model": self.model}
        except LLMError as exc:
            return {"ok": False, "message": str(exc), "model": self.model}
        if self.embeddings_enabled:
            try:
                vec = self.embed(["проверка"])
                result["embeddings"] = bool(vec)
            except LLMError as exc:
                result["embeddings"] = False
                result["embeddings_error"] = str(exc)
        return result
