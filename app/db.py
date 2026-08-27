import os
import psycopg2
import psycopg2.extras
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL", "")


def get_connection():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id SERIAL PRIMARY KEY,
            session_id TEXT NOT NULL,
            first_name TEXT NOT NULL,
            whatsapp_number TEXT NOT NULL,
            email TEXT NOT NULL,
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
    conn.commit()
    cur.close()
    conn.close()


def save_lead(session_id: str, first_name: str, whatsapp_number: str, email: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO leads (session_id, first_name, whatsapp_number, email, created_at) VALUES (%s, %s, %s, %s, %s)",
        (session_id, first_name, whatsapp_number, email, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    cur.close()
    conn.close()


def save_course_interest(session_id: str, first_name: str, whatsapp_number: str, email: str, recommended_courses: str) -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO course_interest
           (session_id, first_name, whatsapp_number, email, recommended_courses, created_at)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (session_id, first_name, whatsapp_number, email, recommended_courses, datetime.now().isoformat(timespec="seconds")),
    )
    row_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return row_id


def update_selected_course(row_id: int, selected_course: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE course_interest SET selected_course = %s, updated_at = %s WHERE id = %s",
        (selected_course, datetime.now().isoformat(timespec="seconds"), row_id),
    )
    conn.commit()
    cur.close()
    conn.close()


init_db()