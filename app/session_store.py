import json
import logging
import os
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from app.config import (
    DATABASE_URL,
    MAX_HISTORY_MESSAGES,
    REDIS_URL,
    SESSION_EXPIRY_HOURS,
)

logger = logging.getLogger("course_chatbot.session_store")

SESSION_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sessions.db"
)


def _create_default_session() -> Dict[str, Any]:
    return {
        "history": [],
        "profile": {"education_level": ""},
        "lead_captured": False,
        "lead_stage": "first_name",
        "lead_data": {"first_name": "", "whatsapp_number": "", "email": ""},
        "name_attempts": 0,
        "browse_stage": "education",
        "selected_program": "",
        "selected_subprogram": "",
        "shown_courses": [],
        "selected_course": "",
        "course_interest_id": None,
        "consent": True,
        "interrupted_stage": None,
        "pending_question": None,
        "step": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


class BaseSessionStore(ABC):
    @abstractmethod
    def get(self, session_id: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def save(self, session_id: str, data: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    def status_name(self) -> str:
        pass


class RedisSessionStore(BaseSessionStore):
    def __init__(self, redis_url: str):
        import redis

        self.client = redis.Redis.from_url(redis_url, decode_responses=True)
        self.ttl_seconds = SESSION_EXPIRY_HOURS * 3600
        # Test connection
        self.client.ping()
        logger.info("RedisSessionStore initialized and connected.")

    def get(self, session_id: str) -> Dict[str, Any]:
        raw = self.client.get(f"session:{session_id}")
        if not raw:
            default = _create_default_session()
            self.save(session_id, default)
            return default
        try:
            return json.loads(raw)
        except Exception:
            return _create_default_session()

    def save(self, session_id: str, data: Dict[str, Any]) -> None:
        data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self.client.setex(f"session:{session_id}", self.ttl_seconds, json.dumps(data))

    def status_name(self) -> str:
        return "redis"


class PostgresSessionStore(BaseSessionStore):
    def __init__(self):
        from app.db import get_connection

        self.get_conn = get_connection
        logger.info("PostgresSessionStore initialized.")

    def get(self, session_id: str) -> Dict[str, Any]:
        try:
            with self.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT data, updated_at FROM sessions WHERE session_id = %s", (session_id,))
                    row = cur.fetchone()
                    if row:
                        data_str = row[0]
                        updated_at = row[1]
                        # Check expiry
                        if isinstance(updated_at, datetime):
                            if datetime.now() - updated_at > timedelta(hours=SESSION_EXPIRY_HOURS):
                                default = _create_default_session()
                                self.save(session_id, default)
                                return default
                        return json.loads(data_str)
        except Exception as e:
            logger.warning(f"Postgres session get failed ({e}), falling back to SQLite: {e}")

        # Fallback to local SQLite if PG fails
        return _sqlite_store.get(session_id)

    def save(self, session_id: str, data: Dict[str, Any]) -> None:
        data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        raw = json.dumps(data)
        saved_pg = False
        try:
            with self.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO sessions (session_id, data, updated_at)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (session_id) DO UPDATE SET data = EXCLUDED.data, updated_at = EXCLUDED.updated_at
                        """,
                        (session_id, raw, datetime.now()),
                    )
            saved_pg = True
        except Exception as e:
            logger.warning(f"Postgres session save failed: {e}")

        # Always keep SQLite in sync as backup
        _sqlite_store.save(session_id, data)

    def status_name(self) -> str:
        return "postgres"


class SQLiteSessionStore(BaseSessionStore):
    def __init__(self, db_path: str = SESSION_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path, timeout=5) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()
        logger.info(f"SQLiteSessionStore initialized at {self.db_path}.")

    def get(self, session_id: str) -> Dict[str, Any]:
        try:
            with sqlite3.connect(self.db_path, timeout=5) as conn:
                cur = conn.cursor()
                cur.execute("SELECT data, updated_at FROM sessions WHERE session_id = ?", (session_id,))
                row = cur.fetchone()
                if row:
                    data_str, updated_at_str = row
                    try:
                        updated_at = datetime.fromisoformat(updated_at_str)
                        if datetime.now() - updated_at > timedelta(hours=SESSION_EXPIRY_HOURS):
                            default = _create_default_session()
                            self.save(session_id, default)
                            return default
                    except Exception:
                        pass
                    return json.loads(data_str)
        except Exception as e:
            logger.warning(f"SQLite session get failed: {e}")

        default = _create_default_session()
        self.save(session_id, default)
        return default

    def save(self, session_id: str, data: Dict[str, Any]) -> None:
        data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        try:
            with sqlite3.connect(self.db_path, timeout=5) as conn:
                conn.execute(
                    "INSERT INTO sessions (session_id, data, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(session_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
                    (session_id, json.dumps(data), data["updated_at"]),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"SQLite session save failed: {e}")

    def status_name(self) -> str:
        return "sqlite"


class InMemorySessionStore(BaseSessionStore):
    def __init__(self):
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = _create_default_session()
            return self._sessions[session_id]

    def save(self, session_id: str, data: Dict[str, Any]) -> None:
        with self._lock:
            data["updated_at"] = datetime.now().isoformat(timespec="seconds")
            self._sessions[session_id] = data

    def status_name(self) -> str:
        return "memory"


# Initialize SQLite store as universal reliable baseline
_sqlite_store = SQLiteSessionStore()

# Global session store selection
_active_store: BaseSessionStore = _sqlite_store

if REDIS_URL:
    try:
        _active_store = RedisSessionStore(REDIS_URL)
    except Exception as e:
        logger.warning(f"Could not connect to Redis ({e}), falling back to persistent store.")
        if DATABASE_URL:
            _active_store = PostgresSessionStore()
        else:
            _active_store = _sqlite_store
elif DATABASE_URL:
    _active_store = PostgresSessionStore()
else:
    _active_store = _sqlite_store


def get_session_store_status() -> str:
    """Returns the type name of the active session store."""
    return _active_store.status_name()


def get_session(session_id: str) -> Dict[str, Any]:
    """Retrieves session state dictionary by session ID."""
    return _active_store.get(session_id)


def save_session(session_id: str, data: Dict[str, Any]):
    """Persists updated session state."""
    _active_store.save(session_id, data)


def append_message(session_id: str, role: str, content: str):
    """Appends chat message to session history with sliding window limit."""
    s = get_session(session_id)
    s["history"].append({"role": role, "content": content})
    if len(s["history"]) > MAX_HISTORY_MESSAGES:
        s["history"] = s["history"][-MAX_HISTORY_MESSAGES:]
    save_session(session_id, s)