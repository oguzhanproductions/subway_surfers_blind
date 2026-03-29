from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class LeaderboardDatabase:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = NORMAL")
        self._initialize_schema()

    def close(self) -> None:
        self.connection.close()

    def _initialize_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_login_at TEXT NOT NULL,
                auth_epoch INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS account_devices (
                account_id INTEGER NOT NULL,
                device_hash TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                PRIMARY KEY (account_id, device_hash),
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS device_account_creations (
                device_hash TEXT PRIMARY KEY,
                last_created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS submissions (
                id TEXT PRIMARY KEY,
                account_id INTEGER NOT NULL,
                score INTEGER NOT NULL,
                coins INTEGER NOT NULL,
                play_time_seconds INTEGER NOT NULL,
                published_at TEXT NOT NULL,
                published_at_epoch INTEGER NOT NULL,
                game_version TEXT NOT NULL,
                device_hash TEXT NOT NULL,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS auth_sessions (
                token TEXT PRIMARY KEY,
                account_id INTEGER NOT NULL,
                device_hash TEXT NOT NULL,
                auth_epoch INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                last_used_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_submissions_account_time
                ON submissions(account_id, published_at_epoch DESC);

            CREATE INDEX IF NOT EXISTS idx_submissions_ranking
                ON submissions(score DESC, coins DESC, play_time_seconds DESC, published_at_epoch ASC);

            CREATE INDEX IF NOT EXISTS idx_auth_sessions_account
                ON auth_sessions(account_id, expires_at DESC);
            """
        )
        self._ensure_submission_columns()
        self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_submissions_period_difficulty
                ON submissions(difficulty, published_at_epoch DESC, score DESC, coins DESC, play_time_seconds DESC)
            """
        )
        self.connection.commit()

    def _ensure_submission_columns(self) -> None:
        existing_columns = {
            str(row["name"])
            for row in self.connection.execute("PRAGMA table_info(submissions)").fetchall()
        }
        required_columns = {
            "difficulty": "ALTER TABLE submissions ADD COLUMN difficulty TEXT NOT NULL DEFAULT 'unknown'",
            "death_reason": "ALTER TABLE submissions ADD COLUMN death_reason TEXT",
            "distance_meters": "ALTER TABLE submissions ADD COLUMN distance_meters INTEGER",
            "clean_escapes": "ALTER TABLE submissions ADD COLUMN clean_escapes INTEGER",
            "revives_used": "ALTER TABLE submissions ADD COLUMN revives_used INTEGER NOT NULL DEFAULT 0",
            "powerup_usage_json": "ALTER TABLE submissions ADD COLUMN powerup_usage_json TEXT NOT NULL DEFAULT '{}'",
            "verification_status": "ALTER TABLE submissions ADD COLUMN verification_status TEXT NOT NULL DEFAULT 'verified'",
            "verification_reasons_json": "ALTER TABLE submissions ADD COLUMN verification_reasons_json TEXT NOT NULL DEFAULT '[]'",
        }
        for column_name, statement in required_columns.items():
            if column_name in existing_columns:
                continue
            self.connection.execute(statement)

    def fetchone(self, query: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        return self.connection.execute(query, parameters).fetchone()

    def fetchall(self, query: str, parameters: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        return list(self.connection.execute(query, parameters).fetchall())

    def execute(self, query: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        cursor = self.connection.execute(query, parameters)
        self.connection.commit()
        return cursor

    def executescript(self, script: str) -> None:
        self.connection.executescript(script)
        self.connection.commit()
