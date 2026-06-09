from __future__ import annotations


import contextlib
import logging
import sqlite3
from typing import Generator


from config.settings import DATABASE_PATH as DEFAULT_PATH


logger = logging.getLogger(__name__)



@contextlib.contextmanager
def get_connection(db_path: str | None = None) -> Generator[sqlite3.Connection, None, None]:
    path = db_path or DEFAULT_PATH
    conn = sqlite3.connect(path, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()



def _table_columns(c: sqlite3.Cursor, table: str) -> set[str]:
    try:
        return {row[1] for row in c.execute(f"PRAGMA table_info({table})")}
    except sqlite3.OperationalError:
        return set()



def init_db(db_path: str | None = None) -> None:
    with get_connection(db_path) as conn:
        c = conn.cursor()
        _create_tables(c)
        _migrate(c)
        _create_indexes(c)
        conn.commit()
    logger.info("✅ DB hazır → %s", db_path or DEFAULT_PATH)



def _create_tables(c: sqlite3.Cursor) -> None:

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id         INTEGER UNIQUE NOT NULL,
            username            TEXT    NOT NULL DEFAULT '',
            first_name          TEXT    NOT NULL DEFAULT '',
            total_points        INTEGER NOT NULL DEFAULT 0,
            total_earned_points INTEGER NOT NULL DEFAULT 0,
            total_wastes        INTEGER NOT NULL DEFAULT 0,
            created_at          DATETIME NOT NULL DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS wastes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            image_hash  TEXT    NOT NULL,
            phash       TEXT    NOT NULL DEFAULT '',
            file_id     TEXT    NOT NULL DEFAULT '',
            points      INTEGER NOT NULL DEFAULT 0,
            brand       TEXT    NOT NULL DEFAULT 'UNKNOWN',
            fingerprint TEXT    NOT NULL DEFAULT '',
            category    TEXT    NOT NULL DEFAULT '',
            is_empty    INTEGER NOT NULL DEFAULT 1,
            is_damaged  INTEGER NOT NULL DEFAULT 0,
            raw_volume  TEXT    NOT NULL DEFAULT '',
            raw_color   TEXT    NOT NULL DEFAULT '',
            fraud_score REAL    NOT NULL DEFAULT 0.0,
            event_proof TEXT    NOT NULL DEFAULT '',
            gps_lat     REAL,
            gps_lon     REAL,
            created_at  DATETIME NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS store_items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            description TEXT    NOT NULL DEFAULT '',
            price       INTEGER NOT NULL CHECK (price >= 0),
            stock       INTEGER NOT NULL DEFAULT -1,
            is_active   INTEGER NOT NULL DEFAULT 1,
            created_at  DATETIME NOT NULL DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id  INTEGER NOT NULL,
            item_id      INTEGER NOT NULL,
            points_spent INTEGER NOT NULL CHECK (points_spent >= 0),
            created_at   DATETIME NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE,
            FOREIGN KEY (item_id) REFERENCES store_items(id) ON DELETE RESTRICT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS review_queue (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            phash       TEXT    NOT NULL DEFAULT '',
            file_id     TEXT    NOT NULL DEFAULT '',
            result_a    TEXT    NOT NULL DEFAULT '{}',
            result_b    TEXT    NOT NULL DEFAULT '{}',
            resolved    INTEGER NOT NULL DEFAULT 0,
            created_at  DATETIME NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS fraud_flags (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            reason      TEXT    NOT NULL DEFAULT '',
            score       REAL    NOT NULL DEFAULT 0.0,
            daily_count INTEGER NOT NULL DEFAULT 0,
            created_at  DATETIME NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE
        )
    """)

    # GPS multiplier için — elle ekle:
    # INSERT INTO recycling_points (name, lat, lon) VALUES ('Merkez', 37.123, 55.456);
    c.execute("""
        CREATE TABLE IF NOT EXISTS recycling_points (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL DEFAULT '',
            lat        REAL NOT NULL,
            lon        REAL NOT NULL,
            created_at DATETIME NOT NULL DEFAULT (datetime('now'))
        )
    """)



def _create_indexes(c: sqlite3.Cursor) -> None:
    wastes_cols   = _table_columns(c, "wastes")
    fraud_cols    = _table_columns(c, "fraud_flags")
    purchase_cols = _table_columns(c, "purchases")
    review_cols   = _table_columns(c, "review_queue")

    candidates = [
        ("CREATE INDEX IF NOT EXISTS idx_wastes_telegram_id  ON wastes(telegram_id)",        wastes_cols,   "telegram_id"),
        ("CREATE INDEX IF NOT EXISTS idx_wastes_image_hash   ON wastes(image_hash)",         wastes_cols,   "image_hash"),
        ("CREATE INDEX IF NOT EXISTS idx_wastes_phash        ON wastes(phash)",              wastes_cols,   "phash"),
        ("CREATE INDEX IF NOT EXISTS idx_wastes_file_id      ON wastes(file_id)",            wastes_cols,   "file_id"),
        ("CREATE INDEX IF NOT EXISTS idx_wastes_fingerprint  ON wastes(fingerprint)",        wastes_cols,   "fingerprint"),
        ("CREATE INDEX IF NOT EXISTS idx_wastes_created_at   ON wastes(created_at)",         wastes_cols,   "created_at"),
        ("CREATE INDEX IF NOT EXISTS idx_fraud_flags_tg_id   ON fraud_flags(telegram_id)",   fraud_cols,    "telegram_id"),
        ("CREATE INDEX IF NOT EXISTS idx_purchases_telegram  ON purchases(telegram_id)",     purchase_cols, "telegram_id"),
        ("CREATE INDEX IF NOT EXISTS idx_review_queue_tg_id  ON review_queue(telegram_id)",  review_cols,   "telegram_id"),
        ("CREATE INDEX IF NOT EXISTS idx_review_queue_res    ON review_queue(resolved)",     review_cols,   "resolved"),
        ("CREATE INDEX IF NOT EXISTS idx_review_queue_fid    ON review_queue(file_id)",      review_cols,   "file_id"),
    ]

    for sql, col_set, required_col in candidates:
        if required_col in col_set:
            c.execute(sql)



def _migrate(c: sqlite3.Cursor) -> None:
    wastes_cols  = _table_columns(c, "wastes")
    users_cols   = _table_columns(c, "users")
    fraud_cols   = _table_columns(c, "fraud_flags")
    review_cols  = _table_columns(c, "review_queue")

    _add_columns(c, "wastes", wastes_cols, {
        "phash":       "TEXT    NOT NULL DEFAULT ''",
        "file_id":     "TEXT    NOT NULL DEFAULT ''",
        "brand":       "TEXT    NOT NULL DEFAULT 'UNKNOWN'",
        "fingerprint": "TEXT    NOT NULL DEFAULT ''",
        "category":    "TEXT    NOT NULL DEFAULT ''",
        "is_empty":    "INTEGER NOT NULL DEFAULT 1",
        "is_damaged":  "INTEGER NOT NULL DEFAULT 0",
        "raw_volume":  "TEXT    NOT NULL DEFAULT ''",
        "raw_color":   "TEXT    NOT NULL DEFAULT ''",
        "fraud_score": "REAL    NOT NULL DEFAULT 0.0",
        "event_proof": "TEXT    NOT NULL DEFAULT ''",
        "gps_lat":     "REAL",
        "gps_lon":     "REAL",
    })

    _add_columns(c, "users", users_cols, {
        "total_earned_points": "INTEGER  NOT NULL DEFAULT 0",
        "created_at":          "DATETIME NOT NULL DEFAULT (datetime('now'))",
    })

    _add_columns(c, "fraud_flags", fraud_cols, {
        "score": "REAL NOT NULL DEFAULT 0.0",
    })

    # ── YENİ: review_queue.file_id migration ─────────────────
    _add_columns(c, "review_queue", review_cols, {
        "file_id": "TEXT NOT NULL DEFAULT ''",
    })



def _add_columns(
    c: sqlite3.Cursor,
    table: str,
    existing: set[str],
    columns: dict[str, str],
) -> None:
    for col_name, col_def in columns.items():
        if col_name not in existing:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
            logger.info("Migration: %s.%s eklendi", table, col_name)