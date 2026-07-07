"""Migration script: Add annotation_groups table and group_id column to annotations.

This script is idempotent — it checks whether the table and column already exist
before attempting to create them. Safe to run multiple times.

Usage:
    python migrations/add_annotation_groups.py
"""

import os
import sqlite3
import sys


def get_db_path() -> str:
    """Resolve the SQLite database path (same logic as Flask app)."""
    # Default: instance/mvr.db relative to project root
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project_root, "instance", "mvr.db")


def table_exists(cursor: sqlite3.Cursor, table_name: str) -> bool:
    """Check if a table exists in the database."""
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return cursor.fetchone() is not None


def column_exists(cursor: sqlite3.Cursor, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns


def run_migration(db_path: str | None = None) -> None:
    """Run the migration to add annotation_groups table and group_id column."""
    if db_path is None:
        db_path = get_db_path()

    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}. Skipping migration.")
        print("The tables will be created automatically on first app startup.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 1. Create annotation_groups table if it doesn't exist
        if not table_exists(cursor, "annotation_groups"):
            print("Creating annotation_groups table...")
            cursor.execute("""
                CREATE TABLE annotation_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    attachment_id INTEGER NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    color VARCHAR(7) NOT NULL DEFAULT '#3498db',
                    display_order INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL,
                    UNIQUE (attachment_id, name)
                )
            """)
            print("  annotation_groups table created.")
        else:
            print("annotation_groups table already exists. Skipping.")

        # 2. Add group_id column to annotations table if it doesn't exist
        if not column_exists(cursor, "annotations", "group_id"):
            print("Adding group_id column to annotations table...")
            cursor.execute("""
                ALTER TABLE annotations
                ADD COLUMN group_id INTEGER REFERENCES annotation_groups(id) ON DELETE SET NULL
            """)
            print("  group_id column added.")
        else:
            print("group_id column already exists in annotations table. Skipping.")

        conn.commit()
        print("Migration completed successfully.")

    except Exception as e:
        conn.rollback()
        print(f"Migration failed: {e}", file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    run_migration()
