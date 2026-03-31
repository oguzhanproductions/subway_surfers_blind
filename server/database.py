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

            CREATE TABLE IF NOT EXISTS leaderboard_seasons (
                season_key TEXT PRIMARY KEY,
                start_at TEXT NOT NULL,
                end_at TEXT NOT NULL,
                start_epoch INTEGER NOT NULL,
                end_epoch INTEGER NOT NULL,
                reward_kind TEXT NOT NULL,
                created_at TEXT NOT NULL,
                finalized_at TEXT
            );

            CREATE TABLE IF NOT EXISTS season_rewards (
                id TEXT PRIMARY KEY,
                season_key TEXT NOT NULL,
                account_id INTEGER NOT NULL,
                submission_id TEXT NOT NULL,
                rank INTEGER NOT NULL,
                reward_kind TEXT NOT NULL,
                reward_amount INTEGER NOT NULL,
                base_run_coins INTEGER,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                claimed_at TEXT,
                FOREIGN KEY (season_key) REFERENCES leaderboard_seasons(season_key) ON DELETE CASCADE,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
                FOREIGN KEY (submission_id) REFERENCES submissions(id) ON DELETE CASCADE,
                UNIQUE (season_key, account_id)
            );

            CREATE TABLE IF NOT EXISTS account_reward_inbox (
                id TEXT PRIMARY KEY,
                account_id INTEGER NOT NULL,
                season_key TEXT NOT NULL,
                season_name TEXT NOT NULL,
                season_start_at TEXT NOT NULL,
                season_end_at TEXT NOT NULL,
                rank INTEGER NOT NULL,
                reward_kind TEXT NOT NULL,
                reward_amount INTEGER NOT NULL,
                base_run_coins INTEGER,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                claimed_at TEXT,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
                UNIQUE (account_id, season_key)
            );

            CREATE INDEX IF NOT EXISTS idx_submissions_account_time
                ON submissions(account_id, published_at_epoch DESC);

            CREATE INDEX IF NOT EXISTS idx_submissions_ranking
                ON submissions(score DESC, coins DESC, play_time_seconds DESC, published_at_epoch ASC);

            CREATE INDEX IF NOT EXISTS idx_submissions_period
                ON submissions(published_at_epoch DESC, score DESC, coins DESC, play_time_seconds DESC);

            CREATE INDEX IF NOT EXISTS idx_auth_sessions_account
                ON auth_sessions(account_id, expires_at DESC);

            CREATE INDEX IF NOT EXISTS idx_leaderboard_seasons_finalization
                ON leaderboard_seasons(finalized_at, end_epoch DESC);

            CREATE INDEX IF NOT EXISTS idx_season_rewards_account_claimed
                ON season_rewards(account_id, claimed_at, season_key DESC);

            CREATE INDEX IF NOT EXISTS idx_account_reward_inbox_claimed
                ON account_reward_inbox(account_id, claimed_at, season_key DESC);
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
