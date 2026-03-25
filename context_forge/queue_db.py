"""SQLite queue database for Context Forge import operations."""

import os
import sqlite3
from datetime import datetime, timezone


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS import_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    priority INTEGER DEFAULT 0,
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_import_source_id
    ON import_queue(source, source_id);
CREATE INDEX IF NOT EXISTS idx_import_status ON import_queue(status);
CREATE INDEX IF NOT EXISTS idx_import_priority ON import_queue(priority DESC);

CREATE TABLE IF NOT EXISTS api_usage (
    date TEXT PRIMARY KEY,
    anthropic_calls INTEGER DEFAULT 0,
    items_processed INTEGER DEFAULT 0
);
"""


class ImportQueueDB:
    """Interface for the Context Forge import queue."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def init_db(self):
        """Create tables and indexes."""
        conn = self._connect()
        conn.executescript(SCHEMA_SQL)
        conn.commit()

    def add_item(
        self,
        source: str,
        source_id: str,
        priority: int = 0,
        metadata: str | None = None,
    ) -> bool:
        """Add an item to the import queue. Returns True if added, False if duplicate."""
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO import_queue (source, source_id, priority, metadata)
                   VALUES (?, ?, ?, ?)""",
                (source, source_id, priority, metadata),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_pending(self, source: str | None = None, limit: int = 100) -> list[dict]:
        """Get pending items, highest priority first."""
        conn = self._connect()
        if source:
            rows = conn.execute(
                """SELECT * FROM import_queue
                   WHERE status = 'pending' AND source = ?
                   ORDER BY priority DESC, created_at ASC
                   LIMIT ?""",
                (source, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM import_queue
                   WHERE status = 'pending'
                   ORDER BY priority DESC, created_at ASC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_processing(self, item_id: int) -> None:
        conn = self._connect()
        conn.execute(
            "UPDATE import_queue SET status = 'processing' WHERE id = ?",
            (item_id,),
        )
        conn.commit()

    def mark_complete(self, item_id: int) -> None:
        conn = self._connect()
        conn.execute(
            """UPDATE import_queue
               SET status = 'complete', processed_at = ?
               WHERE id = ?""",
            (datetime.now(timezone.utc).isoformat(), item_id),
        )
        conn.commit()

    def mark_failed(self, item_id: int, error: str) -> None:
        conn = self._connect()
        conn.execute(
            """UPDATE import_queue
               SET status = 'failed', error_message = ?, retry_count = retry_count + 1
               WHERE id = ?""",
            (error, item_id),
        )
        conn.commit()

    def mark_skipped(self, item_id: int) -> None:
        conn = self._connect()
        conn.execute(
            "UPDATE import_queue SET status = 'skipped' WHERE id = ?",
            (item_id,),
        )
        conn.commit()

    def exists(self, source: str, source_id: str) -> bool:
        conn = self._connect()
        row = conn.execute(
            "SELECT 1 FROM import_queue WHERE source = ? AND source_id = ?",
            (source, source_id),
        ).fetchone()
        return row is not None

    def get_status_counts(self, source: str | None = None) -> dict:
        conn = self._connect()
        if source:
            rows = conn.execute(
                """SELECT status, COUNT(*) as count
                   FROM import_queue WHERE source = ?
                   GROUP BY status""",
                (source,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT status, COUNT(*) as count
                   FROM import_queue
                   GROUP BY status"""
            ).fetchall()
        return {row["status"]: row["count"] for row in rows}

    def reset_failed(self, max_retries: int = 3) -> int:
        """Reset failed items back to pending. Returns count reset."""
        conn = self._connect()
        cursor = conn.execute(
            """UPDATE import_queue
               SET status = 'pending', error_message = NULL
               WHERE status = 'failed' AND retry_count < ?""",
            (max_retries,),
        )
        conn.commit()
        return cursor.rowcount

    def add_anthropic_call(self) -> None:
        conn = self._connect()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        conn.execute(
            "INSERT OR IGNORE INTO api_usage (date) VALUES (?)", (today,)
        )
        conn.execute(
            "UPDATE api_usage SET anthropic_calls = anthropic_calls + 1 WHERE date = ?",
            (today,),
        )
        conn.commit()

    def add_item_processed(self) -> None:
        conn = self._connect()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        conn.execute(
            "INSERT OR IGNORE INTO api_usage (date) VALUES (?)", (today,)
        )
        conn.execute(
            "UPDATE api_usage SET items_processed = items_processed + 1 WHERE date = ?",
            (today,),
        )
        conn.commit()

    def get_usage_today(self) -> dict:
        conn = self._connect()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT * FROM api_usage WHERE date = ?", (today,)
        ).fetchone()
        if row:
            return dict(row)
        return {"date": today, "anthropic_calls": 0, "items_processed": 0}
