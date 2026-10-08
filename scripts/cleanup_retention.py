"""
Data Retention & GDPR/DPDP Lead Removal Script for Cybrom Course Chatbot.
Usage:
  python scripts/cleanup_retention.py --days 90
  python scripts/cleanup_retention.py --delete-email student@example.com
  python scripts/cleanup_retention.py --delete-phone 9876543210
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta

# Ensure app path in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import DATA_RETENTION_DAYS
from app.db import OFFLINE_DB_PATH, get_connection, is_db_healthy


def delete_from_postgres(where_clause: str, params: tuple) -> int:
    if not is_db_healthy():
        print("[Warning] PostgreSQL is not reachable.")
        return 0
    total = 0
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM leads WHERE {where_clause}", params)
                total += cur.rowcount
                cur.execute(f"DELETE FROM course_interest WHERE {where_clause}", params)
                cur.execute(f"DELETE FROM callback_requests WHERE {where_clause}", params)
        print(f"[PostgreSQL] Removed records matching criteria: {total} leads.")
        return total
    except Exception as e:
        print(f"[Error] Failed to delete from PostgreSQL: {e}")
        return 0


def delete_from_sqlite(where_clause: str, params: tuple) -> int:
    if not os.path.exists(OFFLINE_DB_PATH):
        return 0
    try:
        with sqlite3.connect(OFFLINE_DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute(f"DELETE FROM pending_writes WHERE {where_clause}", params)
            count = cur.rowcount
            conn.commit()
            print(f"[SQLite Offline Queue] Removed {count} records.")
            return count
    except Exception as e:
        print(f"[Error] Failed to delete from SQLite: {e}")
        return 0


def cleanup_by_days(days: int):
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    print(f"Cleaning up records older than {days} days (cutoff: {cutoff})...")
    delete_from_postgres("created_at < %s", (cutoff,))


def delete_by_email(email: str):
    print(f"Deleting lead with email: {email}...")
    delete_from_postgres("LOWER(email) = LOWER(%s)", (email.strip(),))
    delete_from_sqlite("payload_json LIKE ?", (f"%{email.strip()}%",))


def delete_by_phone(phone: str):
    print(f"Deleting lead with phone: {phone}...")
    delete_from_postgres("whatsapp_number = %s", (phone.strip(),))
    delete_from_sqlite("payload_json LIKE ?", (f"%{phone.strip()}%",))


def main():
    parser = argparse.ArgumentParser(description="Cleanup or remove chatbot leads.")
    parser.add_argument("--days", type=int, default=None, help="Retention period in days")
    parser.add_argument("--delete-email", type=str, default=None, help="Delete by email")
    parser.add_argument("--delete-phone", type=str, default=None, help="Delete by phone")

    args = parser.parse_args()

    if args.delete_email:
        delete_by_email(args.delete_email)
    elif args.delete_phone:
        delete_by_phone(args.delete_phone)
    else:
        days = args.days if args.days is not None else DATA_RETENTION_DAYS
        cleanup_by_days(days)


if __name__ == "__main__":
    main()
