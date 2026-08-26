import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "chatbot.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            first_name TEXT NOT NULL,
            whatsapp_number TEXT NOT NULL,
            email TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS course_interest (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    conn.commit()
    conn.close()


def save_lead(session_id: str, first_name: str, whatsapp_number: str, email: str):
    conn = get_connection()
    conn.execute(
        "INSERT INTO leads (session_id, first_name, whatsapp_number, email, created_at) VALUES (?, ?, ?, ?, ?)",
        (session_id, first_name, whatsapp_number, email, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def save_course_interest(session_id: str, first_name: str, whatsapp_number: str, email: str, recommended_courses: str) -> int:
    """Saves the recommendation event and returns the new row's id (used later to record the selection)."""
    conn = get_connection()
    cursor = conn.execute(
        """INSERT INTO course_interest
           (session_id, first_name, whatsapp_number, email, recommended_courses, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (session_id, first_name, whatsapp_number, email, recommended_courses, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id


def update_selected_course(row_id: int, selected_course: str):
    conn = get_connection()
    conn.execute(
        "UPDATE course_interest SET selected_course = ?, updated_at = ? WHERE id = ?",
        (selected_course, datetime.now().isoformat(timespec="seconds"), row_id),
    )
    conn.commit()
    conn.close()


init_db()