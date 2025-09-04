from __future__ import annotations
"""Persistência SQLite para histórico de chat."""
import sqlite3, os, json, threading
from typing import List, Dict, Any

_LOCK = threading.Lock()
_CONN: sqlite3.Connection | None = None

def init(db_path: str) -> None:
    global _CONN
    with _LOCK:
        if _CONN is not None:
            return
        os.makedirs(os.path.dirname(db_path) or '.', exist_ok=True)
        _CONN = sqlite3.connect(db_path, check_same_thread=False)
        _CONN.execute("PRAGMA journal_mode=WAL;")
        _CONN.execute("""CREATE TABLE IF NOT EXISTS sessions(
            id TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        _CONN.execute("""CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            actions TEXT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(session_id) REFERENCES sessions(id))""")
        _CONN.commit()

def save_message(session_id: str, role: str, content: str, actions: list[dict[str, Any]] | None = None) -> None:
    if _CONN is None:
        return
    with _LOCK:
        _CONN.execute("INSERT OR IGNORE INTO sessions(id) VALUES (?)", (session_id,))
        _CONN.execute("INSERT INTO messages(session_id, role, content, actions) VALUES (?,?,?,?)",
                      (session_id, role, content, json.dumps(actions, ensure_ascii=False) if actions else None))
        _CONN.commit()

def load_history(session_id: str) -> List[Dict[str, Any]]:
    if _CONN is None:
        return []
    cur = _CONN.execute("SELECT role, content, actions, created_at FROM messages WHERE session_id=? ORDER BY id ASC", (session_id,))
    rows = cur.fetchall()
    out: List[Dict[str, Any]] = []
    for role, content, actions_raw, created_at in rows:
        actions = None
        if actions_raw:
            try:
                actions = json.loads(actions_raw)
            except Exception:
                actions = []
        out.append({"role": role, "text": content, "actions": actions, "created_at": created_at})
    return out
