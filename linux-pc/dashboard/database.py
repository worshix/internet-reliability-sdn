import os
import sqlite3
from werkzeug.security import generate_password_hash

DB_PATH = os.environ.get("DB_PATH", "/data/zan.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS telemetry_log (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at      TEXT,
            topic            TEXT,
            node_id          TEXT,
            target_node      TEXT,
            latency_ms       REAL,
            rssi_dbm         INTEGER,
            packet_loss_pct  REAL,
            uptime_s         INTEGER,
            raw_payload      TEXT
        );
    """)

    if not conn.execute("SELECT id FROM users WHERE username='admin'").fetchone():
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?,?)",
            ("admin", generate_password_hash("zan-admin")),
        )

    defaults = [
        ("mqtt_broker",        "localhost"),
        ("mqtt_port",          "1883"),
        ("controller_url",     "http://localhost:8080"),
        ("anomaly_threshold",  "0.75"),
        ("log_retention_days", "7"),
    ]
    for key, val in defaults:
        conn.execute("INSERT OR IGNORE INTO settings (key,value) VALUES (?,?)", (key, val))

    conn.commit()
    conn.close()


def get_setting(key, default=None):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, value))
    conn.commit()
    conn.close()


def log_telemetry(reading, topic, raw_payload):
    conn = get_db()
    conn.execute(
        """INSERT INTO telemetry_log
           (received_at, topic, node_id, target_node,
            latency_ms, rssi_dbm, packet_loss_pct, uptime_s, raw_payload)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            reading.get("received_at"),
            topic,
            reading.get("node_id"),
            reading.get("target_node"),
            reading.get("latency_ms"),
            reading.get("rssi_dbm"),
            reading.get("packet_loss_pct"),
            reading.get("uptime_s"),
            raw_payload,
        ),
    )
    conn.commit()
    conn.close()


def get_recent_logs(limit=200):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM telemetry_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


def purge_old_logs(days):
    conn = get_db()
    conn.execute(
        "DELETE FROM telemetry_log WHERE received_at < datetime('now',?)",
        (f"-{days} days",),
    )
    conn.commit()
    conn.close()
