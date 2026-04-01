from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class IssueDatabase:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path, timeout=10.0, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = NORMAL")
        self.connection.execute("PRAGMA temp_store = MEMORY")
        self._initialize_schema()

    def close(self) -> None:
        self.connection.close()

    def _initialize_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS issue_reports (
                id TEXT PRIMARY KEY,
                reporter_account_id INTEGER NOT NULL,
                reporter_username TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                created_at_epoch INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                updated_at_epoch INTEGER NOT NULL,
                resolved_at TEXT,
                resolved_at_epoch INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_issue_reports_created_desc
                ON issue_reports(created_at_epoch DESC, id DESC);

            CREATE INDEX IF NOT EXISTS idx_issue_reports_status_created_desc
                ON issue_reports(status, created_at_epoch DESC, id DESC);

            CREATE INDEX IF NOT EXISTS idx_issue_reports_account_created_desc
                ON issue_reports(reporter_account_id, created_at_epoch DESC, id DESC);
            """
        )
        self.connection.commit()

    def fetchone(self, query: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        return self.connection.execute(query, parameters).fetchone()

    def fetchall(self, query: str, parameters: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        return list(self.connection.execute(query, parameters).fetchall())

    def execute(self, query: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        cursor = self.connection.execute(query, parameters)
        self.connection.commit()
        return cursor
