"""Estado persistente: permite reanudar el respaldo sin repetir trabajo."""
import sqlite3
import time
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    identifier TEXT PRIMARY KEY,
    title      TEXT,
    mediatype  TEXT DEFAULT 'audio',
    status     TEXT NOT NULL DEFAULT 'pending',
    error      TEXT,
    parts      INTEGER DEFAULT 0,
    bytes      INTEGER DEFAULT 0,
    updated_at REAL
);
CREATE INDEX IF NOT EXISTS idx_status ON items(status);
"""


@contextmanager
def connect():
    conn = sqlite3.connect(config.STATE_DB, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init():
    config.STATE_DB.parent.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        c.executescript(SCHEMA)
        # La base creada antes de los temas no tiene mediatype.
        cols = {r["name"] for r in c.execute("PRAGMA table_info(items)")}
        if "mediatype" not in cols:
            c.execute("ALTER TABLE items ADD COLUMN mediatype TEXT DEFAULT 'audio'")


def add_items(rows):
    """Inserta identificadores nuevos; no toca los ya registrados."""
    with connect() as c:
        cur = c.executemany(
            "INSERT OR IGNORE INTO items(identifier,title,mediatype,updated_at) "
            "VALUES(?,?,?,?)",
            [(r["identifier"], r.get("title", ""),
              r.get("mediatype", "audio"), time.time()) for r in rows],
        )
        return cur.rowcount


def pending(limit=None):
    q = ("SELECT identifier,title,mediatype FROM items "
         "WHERE status IN ('pending','failed') ORDER BY identifier")
    if limit:
        q += f" LIMIT {int(limit)}"
    with connect() as c:
        return [dict(r) for r in c.execute(q)]


def mark(identifier, status, error=None, parts=0, nbytes=0):
    with connect() as c:
        c.execute(
            "UPDATE items SET status=?, error=?, parts=?, bytes=?, updated_at=? WHERE identifier=?",
            (status, error, parts, nbytes, time.time(), identifier),
        )


def stats():
    with connect() as c:
        rows = c.execute("SELECT status, COUNT(*) n, COALESCE(SUM(bytes),0) b FROM items GROUP BY status")
        return {r["status"]: {"n": r["n"], "bytes": r["b"]} for r in rows}
