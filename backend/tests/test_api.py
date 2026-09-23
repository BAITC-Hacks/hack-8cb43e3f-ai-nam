"""Сквозной сценарий через HTTP API: вход, отдельный вход администратора, проект, анализ, экспорт, ИИ-режим."""
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from app.main import app  # noqa: E402

DEMO = ROOT / "samples" / "demo"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def login(client, email="admin@example.com", password="admin12345", admin=False):
    r = client.post("/api/auth/admin/login" if admin else "/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_admin_scope_separation(client):
    app_h = login(client)
    adm_h = login(client, admin=True)
    # токен рабочей области не открывает админ-API и наоборот
    assert client.get("/api/admin/stats", headers=app_h).status_code == 401
    assert client.get("/api/admin/stats", headers=adm_h).status_code == 200
    assert client.get("/api/projects", headers=adm_h).status_code == 401
    # не-администратор не может войти в панель администратора
    r = client.post("/api/admin/users", headers=adm_h, json={"email": "a1@example.com", "role": "analyst",
                                                             "password": "password123"})
    assert r.status_code == 200
    r = client.post("/api/auth/admin/login", json={"email": "a1@example.com", "password": "password123"})
    assert r.status_code == 403
    assert client.post("/api/auth/login", json={"email": "a1@example.com", "password": "bad"}).status_code == 401


def _wait(client, h, run_id, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = client.get(f"/api/analysis/{run_id}/status", headers=h).json()
        if st["status"] in ("done", "error"):
            return st
        time.sleep(0.5)
    raise AssertionError("анализ не завершился")


def _project_with_demo(client, h):
    p = client.post("/api/projects", headers=h, json={"name": "Тест"}).json()
    for side in ("before", "after", "requirements"):
        files = [("files", (f.name, f.read_bytes())) for f in sorted((DEMO / side).iterdir())]
        r = client.post(f"/api/projects/{p['id']}/documents", headers=h, data={"side": side}, files=files)
        assert r.status_code == 200, r.text
    return p


def test_full_flow_without_model(client):
    h = login(client)
    p = _project_with_demo(client, h)
    run = client.post(f"/api/projects/{p['id']}/analysis", headers=h, json={}).json()
    st = _wait(client, h, run["id"])
    assert st["status"] == "done", st
    full = client.get(f"/api/analysis/{run['id']}", headers=h).json()
    types = {f["type"] for f in full["result"]["findings"]}
    assert {"loss", "duplication", "conflict", "reorganization"} <= types
    assert all(s["status"] in ("done", "skipped") for s in full["trace"])
    fid = full["result"]["findings"][0]["id"]
    r = client.put(f"/api/analysis/{run['id']}/findings/{fid}/review", headers=h,
                   json={"status": "confirmed", "comment": "проверено"})
    assert r.status_code == 200
    concl = client.get(f"/api/analysis/{run['id']}/conclusion?lang=kz", headers=h).json()
    assert concl["title"].startswith("Ұйымдық")
    for kind in ("conclusion.docx", "mapping.xlsx", "result.json"):
        r = client.get(f"/api/analysis/{run['id']}/export/{kind}", headers=h)
        assert r.status_code == 200 and len(r.content) > 1000, kind
    diff = client.get(f"/api/projects/{p['id']}/structure-diff", headers=h).json()
    statuses = {n["status"] for n in diff["nodes"]}
    assert "created" in statuses and "split" in statuses
    pkg = client.post(f"/api/projects/{p['id']}/structures/after/package", headers=h,
                      json={"langs": ["ru", "kz"]}).json()
    assert client.get(f"/api/files/{pkg['id']}", headers=h).status_code == 200
    chat = client.post(f"/api/projects/{p['id']}/chat", headers=h, json={"message": "Какие функции утрачены?"}).json()
    assert chat["sources"]


def test_viewer_is_read_only(client):
    h = login(client, "viewer@example.com", "viewer12345") if False else None  # демо-пользователи отключены в тестах
    adm = login(client, admin=True)
    client.post("/api/admin/users", headers=adm, json={"email": "v@example.com", "role": "viewer", "password": "viewer123"})
    h = login(client, "v@example.com", "viewer123")
    assert client.post("/api/projects", headers=h, json={"name": "x"}).status_code == 403
    assert client.get("/api/projects", headers=h).status_code == 200


def test_llm_mode_with_mock_server(client):
    import mock_llm_server

    srv, port = mock_llm_server.start(0)
    try:
        adm = login(client, admin=True)
        cfg = {"provider": "openai", "base_url": f"http://127.0.0.1:{port}/v1", "model": "mock-model",
               "embed_model": "mock-embed"}
        t = client.post("/api/admin/llm/test", headers=adm, json={"values": cfg}).json()
        assert t["ok"] and "mock-model" in t["models"]
        assert client.put("/api/admin/settings/llm", headers=adm, json={"values": cfg}).status_code == 200
        h = login(client)
        p = _project_with_demo(client, h)
        run = client.post(f"/api/projects/{p['id']}/analysis", headers=h, json={"use_llm": True}).json()
        st = _wait(client, h, run["id"])
        assert st["status"] == "done", st
        full = client.get(f"/api/analysis/{run['id']}", headers=h).json()
        assert full["result"]["llm"]["enabled"] and full["result"]["llm"]["calls"] > 0
        verify = next(s for s in full["trace"] if s["step"] == "verify")
        assert verify["status"] == "done"
        assert any(f.get("method") == "rules+llm" for f in full["result"]["findings"])
        chat = client.post(f"/api/projects/{p['id']}/chat", headers=h, json={"message": "Что с ИТ-стратегией?"}).json()
        assert chat["meta"]["mode"] == "llm"
    finally:
        client.post("/api/admin/settings/llm/reset", headers=login(client, admin=True))
        srv.shutdown()
