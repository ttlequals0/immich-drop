"""
Central SQLite access for immich-drop.
All connections go through connect(); all tables and migrations are created
once at startup via init_db() instead of ad hoc DDL in request handlers.
"""

from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger("immich_drop.db")

_DB_PATH: str = ""


def configure(path: str) -> None:
    global _DB_PATH
    _DB_PATH = path


def connect() -> sqlite3.Connection:
    """Return a new connection to the state DB (short-lived, caller closes)."""
    return sqlite3.connect(_DB_PATH, timeout=10)


def init_db() -> None:
    """Create all tables and run best-effort column migrations (idempotent)."""
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                checksum TEXT UNIQUE,
                filename TEXT,
                size INTEGER,
                device_asset_id TEXT,
                immich_asset_id TEXT,
                created_at TEXT,
                inserted_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS invites (
                token TEXT PRIMARY KEY,
                album_id TEXT,
                album_name TEXT,
                max_uses INTEGER DEFAULT 1,
                used_count INTEGER DEFAULT 0,
                expires_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        # Best-effort column migrations for older databases
        for ddl in (
            "ALTER TABLE invites ADD COLUMN claimed INTEGER DEFAULT 0",
            "ALTER TABLE invites ADD COLUMN claimed_at TEXT",
            "ALTER TABLE invites ADD COLUMN claimed_by_session TEXT",
            "ALTER TABLE invites ADD COLUMN password_hash TEXT",
            "ALTER TABLE invites ADD COLUMN owner_user_id TEXT",
            "ALTER TABLE invites ADD COLUMN owner_email TEXT",
            "ALTER TABLE invites ADD COLUMN owner_name TEXT",
            "ALTER TABLE invites ADD COLUMN name TEXT",
            "ALTER TABLE invites ADD COLUMN disabled INTEGER DEFAULT 0",
        ):
            try:
                cur.execute(ddl)
            except sqlite3.OperationalError:
                pass
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS platform_cookies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL UNIQUE,
                cookie_string TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS upload_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT,
                uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                ip TEXT,
                user_agent TEXT,
                fingerprint TEXT,
                filename TEXT,
                size INTEGER,
                checksum TEXT,
                immich_asset_id TEXT
            );
            """
        )
        conn.commit()
    except Exception as e:
        logger.exception("Failed to initialize state DB: %s", e)
    finally:
        conn.close()
