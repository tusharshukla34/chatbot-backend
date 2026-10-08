import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras
import psycopg2.pool
from app.config import DATABASE_URL

logger = logging.getLogger("course_chatbot.db")

_POOL: Optional[psycopg2.pool.ThreadedConnectionPool] = None
_POOL_LOCK = threading.Lock()
_DB_HEALTHY = False

# Path for offline SQLite buffer when PostgreSQL is unreachable
OFFLINE_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "offline_queue.db"
)


def _init_offline_sqlite():
    """Initializes local SQLite database for resilient offline queuing."""
    os.makedirs(os.path.dirname(OFFLINE_DB_PATH), exist_ok=True)
    try:
        with sqlite3.connect(OFFLINE_DB_PATH, timeout=5) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_writes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    write_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    attempts INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to initialize offline SQLite queue: {e}")


_init_offline_sqlite()


_LAST_CONNECT_ATTEMPT = 0.0
_CONNECT_COOLDOWN = 30.0


def get_db_pool() -> Optional[psycopg2.pool.ThreadedConnectionPool]:
    """Retrieves or creates the PostgreSQL connection pool with reconnect cooldown."""
    global _POOL, _DB_HEALTHY, _LAST_CONNECT_ATTEMPT
    if not DATABASE_URL:
        return None

    if _POOL is not None and not _POOL.closed:
        return _POOL

    now = time.time()
    if now - _LAST_CONNECT_ATTEMPT < _CONNECT_COOLDOWN:
        return None

    with _POOL_LOCK:
        if _POOL is not None and not _POOL.closed:
            return _POOL
        if now - _LAST_CONNECT_ATTEMPT < _CONNECT_COOLDOWN:
            return None

        _LAST_CONNECT_ATTEMPT = now
        try:
            conn_url = DATABASE_URL
            if "sslmode" not in conn_url and ("render.com" in conn_url or "aws" in conn_url):
                delimiter = "&" if "?" in conn_url else "?"
                conn_url = f"{conn_url}{delimiter}sslmode=require"

            _POOL = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=conn_url,
                connect_timeout=3,
            )
            _DB_HEALTHY = True
            logger.info("PostgreSQL connection pool established successfully.")
            return _POOL
        except Exception as e:
            _DB_HEALTHY = False
            logger.warning(f"Could not connect to PostgreSQL pool (cooling down {_CONNECT_COOLDOWN}s): {e}")
            return None



@contextmanager
def get_connection():
    """Context manager yielding a pooled connection with auto-return."""
    global _DB_HEALTHY
    pool = get_db_pool()
    if not pool:
        raise psycopg2.OperationalError("Database pool is unavailable")

    conn = None
    try:
        conn = pool.getconn()
        conn.autocommit = False
        yield conn
        conn.commit()
        _DB_HEALTHY = True
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        raise e
    finally:
        if conn and pool and not pool.closed:
            pool.putconn(conn)


def is_db_healthy() -> bool:
    """Returns True if PostgreSQL is reachable, False otherwise."""
    global _DB_HEALTHY
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        _DB_HEALTHY = True
        return True
    except Exception:
        _DB_HEALTHY = False
        return False


def init_db() -> bool:
    """
    Initializes PostgreSQL tables if connected.
    Returns True if successfully initialized, False if operating in degraded mode.
    """
    global _DB_HEALTHY
    if not DATABASE_URL:
        logger.warning("DATABASE_URL is not set. Operating in local degraded mode.")
        _DB_HEALTHY = False
        return False

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS leads (
                        id SERIAL PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        first_name TEXT NOT NULL,
                        whatsapp_number TEXT NOT NULL,
                        email TEXT NOT NULL,
                        consent BOOLEAN DEFAULT TRUE,
                        created_at TEXT NOT NULL
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS course_interest (
                        id SERIAL PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        first_name TEXT NOT NULL,
                        whatsapp_number TEXT NOT NULL,
                        email TEXT NOT NULL,
                        recommended_courses TEXT NOT NULL,
                        selected_course TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS callback_requests (
                        id SERIAL PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        first_name TEXT,
                        whatsapp_number TEXT,
                        email TEXT,
                        reason TEXT,
                        created_at TEXT NOT NULL
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY,
                        data TEXT NOT NULL,
                        updated_at TIMESTAMP NOT NULL
                    )
                """)
        _DB_HEALTHY = True
        logger.info("PostgreSQL tables successfully initialized.")
        # Trigger offline queue flush in background
        threading.Thread(target=flush_offline_queue, daemon=True).start()
        return True
    except Exception as e:
        _DB_HEALTHY = False
        logger.warning(
            f"Failed to initialize PostgreSQL tables: {e}. Running in degraded mode with offline fallback."
        )
        return False


def _queue_offline_write(write_type: str, payload: dict):
    """Enqueues a DB write to SQLite when PostgreSQL is offline."""
    try:
        with sqlite3.connect(OFFLINE_DB_PATH, timeout=5) as conn:
            conn.execute(
                "INSERT INTO pending_writes (write_type, payload_json, created_at) VALUES (?, ?, ?)",
                (write_type, json.dumps(payload), datetime.now().isoformat(timespec="seconds")),
            )
            conn.commit()
        logger.info(f"Buffered {write_type} write to offline queue.")
    except Exception as e:
        logger.error(f"Failed to write to offline queue: {e}")


def get_offline_queue_count() -> int:
    """Returns number of items pending in offline queue."""
    try:
        with sqlite3.connect(OFFLINE_DB_PATH, timeout=2) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM pending_writes")
            row = cur.fetchone()
            return row[0] if row else 0
    except Exception:
        return 0


def flush_offline_queue():
    """Flushes buffered offline writes into PostgreSQL when connectivity restores."""
    count = get_offline_queue_count()
    if count == 0 or not is_db_healthy():
        return

    logger.info(f"Flushing {count} offline writes to PostgreSQL...")
    try:
        with sqlite3.connect(OFFLINE_DB_PATH, timeout=5) as s_conn:
            s_cur = s_conn.cursor()
            s_cur.execute("SELECT id, write_type, payload_json FROM pending_writes ORDER BY id ASC LIMIT 50")
            rows = s_cur.fetchall()

            for row_id, w_type, payload_str in rows:
                payload = json.loads(payload_str)
                success = False

                if w_type == "save_lead":
                    success = _execute_save_lead_pg(payload)
                elif w_type == "save_course_interest":
                    success = _execute_save_course_interest_pg(payload)
                elif w_type == "update_selected_course":
                    success = _execute_update_selected_course_pg(payload)
                elif w_type == "save_callback":
                    success = _execute_save_callback_pg(payload)

                if success:
                    s_conn.execute("DELETE FROM pending_writes WHERE id = ?", (row_id,))
                    s_conn.commit()
                else:
                    break
    except Exception as e:
        logger.error(f"Error while flushing offline queue: {e}")


def _execute_save_lead_pg(p: dict) -> bool:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO leads (session_id, first_name, whatsapp_number, email, consent, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (p["session_id"], p["first_name"], p["whatsapp_number"], p["email"], p.get("consent", True), p["created_at"]),
                )
        return True
    except Exception as e:
        logger.warning(f"Failed to write lead to PG: {e}")
        return False


def _execute_save_course_interest_pg(p: dict) -> bool:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO course_interest "
                    "(session_id, first_name, whatsapp_number, email, recommended_courses, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (p["session_id"], p["first_name"], p["whatsapp_number"], p["email"], p["recommended_courses"], p["created_at"]),
                )
        return True
    except Exception as e:
        logger.warning(f"Failed to write course interest to PG: {e}")
        return False


def _execute_update_selected_course_pg(p: dict) -> bool:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                if p.get("row_id"):
                    cur.execute(
                        "UPDATE course_interest SET selected_course = %s, updated_at = %s WHERE id = %s",
                        (p["selected_course"], p["updated_at"], p["row_id"]),
                    )
                else:
                    cur.execute(
                        "UPDATE course_interest SET selected_course = %s, updated_at = %s "
                        "WHERE session_id = %s ORDER BY id DESC LIMIT 1",
                        (p["selected_course"], p["updated_at"], p["session_id"]),
                    )
        return True
    except Exception as e:
        logger.warning(f"Failed to update selected course in PG: {e}")
        return False


def _execute_save_callback_pg(p: dict) -> bool:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO callback_requests (session_id, first_name, whatsapp_number, email, reason, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (p["session_id"], p.get("first_name", ""), p.get("whatsapp_number", ""), p.get("email", ""), p.get("reason", ""), p["created_at"]),
                )
        return True
    except Exception as e:
        logger.warning(f"Failed to write callback request to PG: {e}")
        return False


def save_lead(session_id: str, first_name: str, whatsapp_number: str, email: str, consent: bool = True):
    """Saves lead to PostgreSQL, or buffers into local offline queue if unavailable."""
    payload = {
        "session_id": session_id,
        "first_name": first_name,
        "whatsapp_number": whatsapp_number,
        "email": email,
        "consent": consent,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if not _execute_save_lead_pg(payload):
        _queue_offline_write("save_lead", payload)


def save_course_interest(
    session_id: str, first_name: str, whatsapp_number: str, email: str, recommended_courses: str
) -> Optional[int]:
    """Saves recommended courses to PostgreSQL or queues offline."""
    payload = {
        "session_id": session_id,
        "first_name": first_name,
        "whatsapp_number": whatsapp_number,
        "email": email,
        "recommended_courses": recommended_courses,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "INSERT INTO course_interest "
                    "(session_id, first_name, whatsapp_number, email, recommended_courses, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                    (session_id, first_name, whatsapp_number, email, recommended_courses, payload["created_at"]),
                )
                row = cur.fetchone()
                return row["id"] if row else None
    except Exception as e:
        logger.warning(f"PostgreSQL unavailable for course interest. Queuing offline: {e}")
        _queue_offline_write("save_course_interest", payload)
        return None


def update_selected_course(row_id: Optional[int], selected_course: str, session_id: Optional[str] = None):
    """Updates selected course in PostgreSQL or queues offline."""
    payload = {
        "row_id": row_id,
        "session_id": session_id,
        "selected_course": selected_course,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if not _execute_update_selected_course_pg(payload):
        _queue_offline_write("update_selected_course", payload)


def save_callback_request(
    session_id: str, first_name: str = "", whatsapp_number: str = "", email: str = "", reason: str = ""
):
    """Saves counselor callback request to PostgreSQL or queues offline."""
    payload = {
        "session_id": session_id,
        "first_name": first_name,
        "whatsapp_number": whatsapp_number,
        "email": email,
        "reason": reason,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if not _execute_save_callback_pg(payload):
        _queue_offline_write("save_callback", payload)


def get_all_leads() -> List[Dict[str, Any]]:
    """Retrieves all leads from PostgreSQL, appending any pending in offline queue."""
    leads = []
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM leads ORDER BY id DESC")
                leads = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.warning(f"Could not fetch leads from PostgreSQL: {e}")

    # Also include pending leads from offline queue
    try:
        with sqlite3.connect(OFFLINE_DB_PATH, timeout=2) as s_conn:
            s_cur = s_conn.cursor()
            s_cur.execute("SELECT payload_json FROM pending_writes WHERE write_type = 'save_lead'")
            for (p_str,) in s_cur.fetchall():
                p = json.loads(p_str)
                leads.append({
                    "id": "(offline)",
                    "session_id": p.get("session_id", ""),
                    "first_name": p.get("first_name", ""),
                    "whatsapp_number": p.get("whatsapp_number", ""),
                    "email": p.get("email", ""),
                    "consent": p.get("consent", True),
                    "created_at": p.get("created_at", ""),
                })
    except Exception:
        pass

    return leads


def get_all_course_interests() -> List[Dict[str, Any]]:
    """Retrieves all course interest rows from PostgreSQL and offline queue."""
    interests = []
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM course_interest ORDER BY id DESC")
                interests = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.warning(f"Could not fetch course interests from PostgreSQL: {e}")

    return interests


def get_all_callbacks() -> List[Dict[str, Any]]:
    """Retrieves all callback requests from PostgreSQL."""
    callbacks = []
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM callback_requests ORDER BY id DESC")
                callbacks = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.warning(f"Could not fetch callbacks from PostgreSQL: {e}")
    return callbacks