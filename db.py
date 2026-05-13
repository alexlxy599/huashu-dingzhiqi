import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS sender_config (
        id          INTEGER PRIMARY KEY CHECK (id = 1),
        name        TEXT NOT NULL DEFAULT '',
        team        TEXT NOT NULL DEFAULT '',
        contact     TEXT NOT NULL DEFAULT '',
        updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    INSERT OR IGNORE INTO sender_config (id) VALUES (1);

    CREATE TABLE IF NOT EXISTS history (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL,
        url         TEXT NOT NULL DEFAULT '',
        community   TEXT NOT NULL DEFAULT '',
        language    TEXT NOT NULL DEFAULT 'zh',
        message     TEXT NOT NULL,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    conn.close()


# ── sender config ──

def get_sender_config():
    conn = get_conn()
    row = conn.execute("SELECT name, team, contact FROM sender_config WHERE id = 1").fetchone()
    conn.close()
    return dict(row) if row else {"name": "", "team": "", "contact": ""}


def save_sender_config(name: str, team: str, contact: str):
    conn = get_conn()
    conn.execute(
        "UPDATE sender_config SET name=?, team=?, contact=?, updated_at=CURRENT_TIMESTAMP WHERE id=1",
        (name, team, contact),
    )
    conn.commit()
    conn.close()


# ── history ──

def add_history(name: str, url: str, community: str, language: str, message: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO history (name, url, community, language, message) VALUES (?, ?, ?, ?, ?)",
        (name, url, community, language, message),
    )
    conn.commit()
    conn.close()


def get_history(search: str = "", limit: int = 50, offset: int = 0):
    conn = get_conn()
    if search:
        rows = conn.execute(
            "SELECT * FROM history WHERE name LIKE ? OR message LIKE ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (f"%{search}%", f"%{search}%", limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM history ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_history(record_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM history WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()


def clear_history():
    conn = get_conn()
    conn.execute("DELETE FROM history")
    conn.commit()
    conn.close()
