import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("AI_NAM_DATA_DIR", str(ROOT / "data"))).resolve()


@contextmanager
def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DATA_DIR / "app.sqlite3", timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    try:
        with con:
            yield con
    finally:
        con.close()


def init():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
          role TEXT NOT NULL, password TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (
          token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS cases (
          id TEXT PRIMARY KEY, title TEXT NOT NULL, created REAL NOT NULL, owner_id TEXT NOT NULL,
          status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0, stage TEXT NOT NULL,
          error TEXT, result TEXT, manifest TEXT NOT NULL, use_ai INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS audit (
          id INTEGER PRIMARY KEY AUTOINCREMENT, time REAL NOT NULL, user_id TEXT,
          action TEXT NOT NULL, target TEXT NOT NULL, detail TEXT NOT NULL);
        """)
        if "shared" not in {r[1] for r in con.execute("PRAGMA table_info(cases)")}:
            con.execute("ALTER TABLE cases ADD COLUMN shared INTEGER NOT NULL DEFAULT 0")
        con.execute("UPDATE cases SET status='failed', error='Обработка прервана перезапуском сервера. Запустите сравнение ещё раз.', stage='Обработка прервана' WHERE status='processing'")
        con.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))


def public_user(row):
    return {key: row[key] for key in ["id", "username", "name", "role", "active"]} if row else None


def password_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ":" + digest.hex()


def verify_password(password, value):
    try:
        salt, expected = value.split(":")
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
        return secrets.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_user(username, name, role, password, bootstrap=False):
    uid = secrets.token_hex(12)
    hashed = password_hash(password)
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        if bootstrap and con.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            raise ValueError("Администратор уже создан. Войдите в систему.")
        try:
            con.execute("INSERT INTO users VALUES(?,?,?,?,?,1,?)", (uid, username.lower(), name, role, hashed, time.time()))
        except sqlite3.IntegrityError as exc:
            raise ValueError("Этот логин уже используется.") from exc
    return {"id": uid, "username": username.lower(), "name": name, "role": role, "active": 1}


def user_count():
    with connect() as con:
        return con.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def authenticate(username, password):
    with connect() as con:
        row = con.execute("SELECT * FROM users WHERE username=?", (username.lower(),)).fetchone()
    if row and row["active"] and verify_password(password, row["password"]):
        return public_user(row)
    return None


def new_session(uid):
    token = secrets.token_urlsafe(40)
    with connect() as con:
        con.execute("INSERT INTO sessions VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), uid, time.time() + 43200))
    return token


def session_user(token):
    if not token:
        return None
    with connect() as con:
        row = con.execute("SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires>? AND u.active=1", (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
    return public_user(row)


def logout(token):
    with connect() as con:
        con.execute("DELETE FROM sessions WHERE token=?", (hashlib.sha256((token or "").encode()).hexdigest(),))


def log(uid, action, target="", detail=""):
    with connect() as con:
        con.execute("INSERT INTO audit(time,user_id,action,target,detail) VALUES(?,?,?,?,?)", (time.time(), uid, action, target, detail))


def create_case(title, owner_id, manifest, use_ai=False):
    cid = secrets.token_hex(12)
    with connect() as con:
        con.execute("INSERT INTO cases(id,title,created,owner_id,status,progress,stage,manifest,use_ai) VALUES(?,?,?,?,?,?,?,?,?)", (cid, title, time.time(), owner_id, "processing", 5, "Документы получены", json.dumps(manifest, ensure_ascii=False), int(use_ai)))
    return cid


def get_case(cid, include_result=True):
    with connect() as con:
        row = con.execute("SELECT c.*,u.name as owner_name FROM cases c LEFT JOIN users u ON c.owner_id=u.id WHERE c.id=?", (cid,)).fetchone()
    if not row:
        return None
    case = dict(row)
    case["manifest"] = json.loads(case["manifest"])
    case["result"] = json.loads(case["result"]) if include_result and case["result"] else None
    return case


def can_access(case, user):
    return user["role"] == "admin" or case["owner_id"] == user["id"] or bool(case["shared"])


def list_cases(user):
    with connect() as con:
        rows = con.execute("SELECT c.id,c.title,c.created,c.owner_id,c.shared,c.status,c.progress,c.stage,c.error,c.use_ai,u.name AS owner_name,json_extract(c.result,'$.stats') AS stats FROM cases c LEFT JOIN users u ON c.owner_id=u.id WHERE (?='admin' OR c.owner_id=? OR c.shared=1) ORDER BY c.created DESC LIMIT 200", (user["role"], user["id"])).fetchall()
    return [{**dict(row), "stats": json.loads(row["stats"]) if row["stats"] else None} for row in rows]


def update_progress(cid, value, stage):
    with connect() as con:
        con.execute("UPDATE cases SET progress=?,stage=? WHERE id=?", (value, stage, cid))


def save_intermediate(cid, result):
    with connect() as con:
        con.execute("UPDATE cases SET result=? WHERE id=?", (json.dumps(result, ensure_ascii=False), cid))


def finish_case(cid, result=None, error=None):
    with connect() as con:
        con.execute("UPDATE cases SET status=?,progress=?,stage=?,result=?,error=? WHERE id=?", ("failed" if error else "complete", 100, "Ошибка обработки" if error else "Анализ завершён", json.dumps(result, ensure_ascii=False) if result else None, error, cid))


def review(cid, fid, status, comment, user):
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT result FROM cases WHERE id=? AND status='complete'", (cid,)).fetchone()
        if not row:
            raise ValueError("Сравнение не найдено или ещё обрабатывается.")
        result = json.loads(row["result"])
        finding = next((f for f in result["findings"] if f["id"] == fid), None)
        if not finding:
            raise ValueError("Вывод не найден.")
        finding.update(review=status, comment=comment, reviewer=user["name"], reviewed_at=time.time())
        con.execute("UPDATE cases SET result=? WHERE id=?", (json.dumps(result, ensure_ascii=False), cid))
        con.execute("INSERT INTO audit(time,user_id,action,target,detail) VALUES(?,?,?,?,?)", (time.time(), user["id"], "review", cid, f"{fid}: {status}"))
    return finding
