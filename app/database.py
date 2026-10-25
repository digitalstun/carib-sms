import sqlite3
import os
from datetime import datetime

DB_PATH = os.environ.get("CARIBSMS_DB", "caribsms.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            sid TEXT PRIMARY KEY,
            to_number TEXT NOT NULL,
            from_number TEXT,
            body TEXT NOT NULL,
            status TEXT DEFAULT 'queued',
            direction TEXT DEFAULT 'outbound',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            error_message TEXT,
            num_segments INTEGER DEFAULT 1,
            carrier_ack TEXT,
            delivered_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS failover_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            mode TEXT DEFAULT 'normal',
            activated_at TEXT,
            last_health_check TEXT
        )
    """)
    conn.execute("INSERT OR IGNORE INTO failover_state (id, mode) VALUES (1, 'normal')")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS escalations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sid TEXT NOT NULL,
            escalated_to TEXT DEFAULT 'whatsapp',
            result TEXT,
            timestamp TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_escalations_sid ON escalations(sid)
    """)
    conn.commit()
    conn.close()
