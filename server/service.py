from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import uuid

from argon2 import PasswordHasher

from server.database import LeaderboardDatabase
from server.security import (
    SecurityValidationError,
    build_password_hasher,
    validate_password,
    validate_username,
    verify_password,
)

ACCOUNT_DEVICE_LIMIT = 3
ACCOUNT_CREATION_COOLDOWN_DAYS = 7
SESSION_LIFETIME_DAYS = 30
MAX_SCORE = 100_000_000
MAX_COINS = 1_000_000
MAX_PLAY_TIME_SECONDS = 24 * 60 * 60


class ServiceError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SessionPrincipal:
    account_id: int
    username: str
    auth_epoch: int
    device_hash: str


class LeaderboardService:
    def __init__(self, database: LeaderboardDatabase, password_hasher: PasswordHasher | None = None):
        self.database = database
        self.password_hasher = password_hasher or build_password_hasher()
        self._leaderboard_cache: dict[tuple[int, int], dict] = {}

    @staticmethod
    def utcnow() -> datetime:
        return datetime.now(UTC)

    def login_or_create_account(self, username: str, password: str, device_hash: str) -> dict:
        normalized_username = validate_username(username)
        normalized_password = validate_password(password)
        normalized_device_hash = self._normalize_device_hash(device_hash)
        existing_account = self.database.fetchone(
            "SELECT id, username, password_hash, auth_epoch FROM accounts WHERE username = ?",
            (normalized_username,),
        )
        if existing_account is None:
            self._enforce_account_creation_cooldown(normalized_device_hash)
            now = self.utcnow()
            password_hash = self.password_hasher.hash(normalized_password)
            cursor = self.database.execute(
                """
                INSERT INTO accounts (username, password_hash, created_at, updated_at, last_login_at, auth_epoch)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (normalized_username, password_hash, now.isoformat(), now.isoformat(), now.isoformat()),
            )
            account_id = int(cursor.lastrowid)
            self.database.execute(
                """
                INSERT INTO device_account_creations (device_hash, last_created_at)
                VALUES (?, ?)
                ON CONFLICT(device_hash) DO UPDATE SET last_created_at = excluded.last_created_at
                """,
                (normalized_device_hash, now.isoformat()),
            )
            self._authorize_device(account_id, normalized_device_hash, now)
            session_token = self._issue_session_token(account_id, normalized_device_hash, 0, now)
            return {
                "status": "created",
                "principal": SessionPrincipal(
                    account_id=account_id,
                    username=normalized_username,
                    auth_epoch=0,
                    device_hash=normalized_device_hash,
                ),
                "session_token": session_token,
            }

        if not verify_password(self.password_hasher, str(existing_account["password_hash"]), normalized_password):
            raise ServiceError("invalid_credentials", "User name or password is incorrect.")

        now = self.utcnow()
        account_id = int(existing_account["id"])
        self._authorize_device(account_id, normalized_device_hash, now)
        self.database.execute(
            "UPDATE accounts SET last_login_at = ?, updated_at = ? WHERE id = ?",
            (now.isoformat(), now.isoformat(), account_id),
        )
        session_token = self._issue_session_token(
            account_id,
            normalized_device_hash,
            int(existing_account["auth_epoch"]),
            now,
        )
        return {
            "status": "logged_in",
            "principal": SessionPrincipal(
                account_id=account_id,
                username=str(existing_account["username"]),
                auth_epoch=int(existing_account["auth_epoch"]),
                device_hash=normalized_device_hash,
            ),
            "session_token": session_token,
        }

    def resume_session(self, session_token: str, device_hash: str) -> SessionPrincipal:
        normalized_token = str(session_token or "").strip()
        normalized_device_hash = self._normalize_device_hash(device_hash)
        if len(normalized_token) < 20:
            raise ServiceError("authentication_required", "Session token is missing.")
        now = self.utcnow()
        session_row = self.database.fetchone(
            """
            SELECT token, account_id, device_hash, auth_epoch, expires_at
            FROM auth_sessions
            WHERE token = ?
            """,
            (normalized_token,),
        )
        if session_row is None:
            raise ServiceError("reauth_required", "Session expired. Sign in again.")
        if str(session_row["device_hash"]) != normalized_device_hash:
            self.database.execute("DELETE FROM auth_sessions WHERE token = ?", (normalized_token,))
            raise ServiceError("reauth_required", "Session device mismatch. Sign in again.")
        expires_at = datetime.fromisoformat(str(session_row["expires_at"]))
        if expires_at <= now:
            self.database.execute("DELETE FROM auth_sessions WHERE token = ?", (normalized_token,))
            raise ServiceError("reauth_required", "Session expired. Sign in again.")
        principal = self.revalidate_principal(
            SessionPrincipal(
                account_id=int(session_row["account_id"]),
                username="",
                auth_epoch=int(session_row["auth_epoch"]),
                device_hash=normalized_device_hash,
            )
        )
        self.database.execute(
            "UPDATE auth_sessions SET last_used_at = ?, auth_epoch = ? WHERE token = ?",
            (now.isoformat(), principal.auth_epoch, normalized_token),
        )
        return principal

    def revalidate_principal(self, principal: SessionPrincipal) -> SessionPrincipal:
        record = self.database.fetchone(
            "SELECT id, username, auth_epoch FROM accounts WHERE id = ?",
            (int(principal.account_id),),
        )
        if record is None:
            raise ServiceError("reauth_required", "Account no longer exists. Sign in again.")
        current_auth_epoch = int(record["auth_epoch"])
        if current_auth_epoch != int(principal.auth_epoch):
            raise ServiceError("reauth_required", "Password changed on the server. Sign in again.")
        return SessionPrincipal(
            account_id=int(record["id"]),
            username=str(record["username"]),
            auth_epoch=current_auth_epoch,
            device_hash=principal.device_hash,
        )

    def fetch_leaderboard(self, offset: int = 0, limit: int = 100) -> dict:
        normalized_offset = max(0, int(offset))
        normalized_limit = max(1, min(100, int(limit)))
        cache_key = (normalized_offset, normalized_limit)
        cached = self._leaderboard_cache.get(cache_key)
        if cached is not None:
            return self._copy_leaderboard_payload(cached)
        rows = self.database.fetchall(
            """
            WITH best_runs AS (
                SELECT
                    s.account_id,
                    a.username,
                    s.id,
                    s.score,
                    s.coins,
                    s.play_time_seconds,
                    s.published_at,
                    s.published_at_epoch,
                    ROW_NUMBER() OVER (
                        PARTITION BY s.account_id
                        ORDER BY s.score DESC, s.coins DESC, s.play_time_seconds DESC, s.published_at_epoch ASC
                    ) AS account_rank
                FROM submissions s
                INNER JOIN accounts a ON a.id = s.account_id
            ),
            ranked AS (
                SELECT
                    account_id,
                    username,
                    id,
                    score,
                    coins,
                    play_time_seconds,
                    published_at,
                    ROW_NUMBER() OVER (
                        ORDER BY score DESC, coins DESC, play_time_seconds DESC, published_at_epoch ASC, account_id ASC
                    ) AS board_rank
                FROM best_runs
                WHERE account_rank = 1
            )
            SELECT account_id, username, id, score, coins, play_time_seconds, published_at, board_rank
            FROM ranked
            ORDER BY board_rank
            LIMIT ? OFFSET ?
            """,
            (normalized_limit, normalized_offset),
        )
        total = self.database.fetchone(
            """
            SELECT COUNT(*) AS total_players
            FROM (
                SELECT account_id
                FROM submissions
                GROUP BY account_id
            )
            """
        )
        payload = {
            "entries": [self._serialize_leaderboard_row(row) for row in rows],
            "offset": normalized_offset,
            "limit": normalized_limit,
            "total_players": int(total["total_players"]) if total is not None else 0,
        }
        self._leaderboard_cache[cache_key] = payload
        return self._copy_leaderboard_payload(payload)

    def fetch_profile(self, username: str, history_offset: int = 0, history_limit: int = 50) -> dict:
        normalized_username = validate_username(username)
        normalized_offset = max(0, int(history_offset))
        normalized_limit = max(1, min(100, int(history_limit)))
        account = self.database.fetchone(
            "SELECT id, username FROM accounts WHERE username = ?",
            (normalized_username,),
        )
        if account is None:
            raise ServiceError("not_found", "Player could not be found.")
        account_id = int(account["id"])
        latest_run = self.database.fetchone(
            """
            SELECT id, score, coins, play_time_seconds, published_at, published_at_epoch
            FROM submissions
            WHERE account_id = ?
            ORDER BY published_at_epoch DESC
            LIMIT 1
            """,
            (account_id,),
        )
        best_run = self.database.fetchone(
            """
            SELECT id, score, coins, play_time_seconds, published_at, published_at_epoch
            FROM submissions
            WHERE account_id = ?
            ORDER BY score DESC, coins DESC, play_time_seconds DESC, published_at_epoch ASC
            LIMIT 1
            """,
            (account_id,),
        )
        if latest_run is None or best_run is None:
            raise ServiceError("not_found", "Player has not published any runs yet.")
        board_rank_row = self.database.fetchone(
            """
            WITH best_runs AS (
                SELECT
                    s.account_id,
                    s.score,
                    s.coins,
                    s.play_time_seconds,
                    s.published_at_epoch,
                    ROW_NUMBER() OVER (
                        PARTITION BY s.account_id
                        ORDER BY s.score DESC, s.coins DESC, s.play_time_seconds DESC, s.published_at_epoch ASC
                    ) AS account_rank
                FROM submissions s
            ),
            ranked AS (
                SELECT
                    account_id,
                    ROW_NUMBER() OVER (
                        ORDER BY score DESC, coins DESC, play_time_seconds DESC, published_at_epoch ASC, account_id ASC
                    ) AS board_rank
                FROM best_runs
                WHERE account_rank = 1
            )
            SELECT board_rank
            FROM ranked
            WHERE account_id = ?
            """,
            (account_id,),
        )
        history_rows = self.database.fetchall(
            """
            SELECT id, score, coins, play_time_seconds, published_at, published_at_epoch
            FROM submissions
            WHERE account_id = ?
            ORDER BY published_at_epoch DESC
            LIMIT ? OFFSET ?
            """,
            (account_id, normalized_limit, normalized_offset),
        )
        history_total_row = self.database.fetchone(
            "SELECT COUNT(*) AS total_runs FROM submissions WHERE account_id = ?",
            (account_id,),
        )
        return {
            "username": str(account["username"]),
            "board_rank": int(board_rank_row["board_rank"]) if board_rank_row is not None else None,
            "latest_run": self._serialize_run_row(latest_run),
            "best_run": self._serialize_run_row(best_run),
            "history": [self._serialize_run_row(row) for row in history_rows],
            "history_offset": normalized_offset,
            "history_limit": normalized_limit,
            "history_total": int(history_total_row["total_runs"]) if history_total_row is not None else 0,
        }

    def submit_score(
        self,
        principal: SessionPrincipal,
        score: int,
        coins: int,
        play_time_seconds: int,
        game_version: str,
    ) -> dict:
        principal = self.revalidate_principal(principal)
        normalized_score = self._normalize_score(score)
        normalized_coins = self._normalize_coins(coins)
        normalized_play_time = self._normalize_play_time(play_time_seconds)
        previous_best = self.database.fetchone(
            """
            SELECT score, coins, play_time_seconds, published_at_epoch
            FROM submissions
            WHERE account_id = ?
            ORDER BY score DESC, coins DESC, play_time_seconds DESC, published_at_epoch ASC
            LIMIT 1
            """,
            (principal.account_id,),
        )
        now = self.utcnow()
        submission_id = str(uuid.uuid4())
        self.database.execute(
            """
            INSERT INTO submissions (
                id,
                account_id,
                score,
                coins,
                play_time_seconds,
                published_at,
                published_at_epoch,
                game_version,
                device_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                submission_id,
                principal.account_id,
                normalized_score,
                normalized_coins,
                normalized_play_time,
                now.isoformat(),
                int(now.timestamp()),
                str(game_version or "").strip() or "unknown",
                principal.device_hash,
            ),
        )
        self._leaderboard_cache.clear()
        new_best = self.database.fetchone(
            """
            SELECT id, score, coins, play_time_seconds, published_at, published_at_epoch
            FROM submissions
            WHERE account_id = ?
            ORDER BY score DESC, coins DESC, play_time_seconds DESC, published_at_epoch ASC
            LIMIT 1
            """,
            (principal.account_id,),
        )
        if new_best is None:
            raise ServiceError("server_error", "Unable to determine the updated personal best.")
        high_score = previous_best is None or self._run_is_better(new_best, previous_best)
        board_rank = None
        if high_score:
            rank_row = self.database.fetchone(
                """
                WITH best_runs AS (
                    SELECT
                        s.account_id,
                        s.score,
                        s.coins,
                        s.play_time_seconds,
                        s.published_at_epoch,
                        ROW_NUMBER() OVER (
                            PARTITION BY s.account_id
                            ORDER BY s.score DESC, s.coins DESC, s.play_time_seconds DESC, s.published_at_epoch ASC
                        ) AS account_rank
                    FROM submissions s
                ),
                ranked AS (
                    SELECT
                        account_id,
                        ROW_NUMBER() OVER (
                            ORDER BY score DESC, coins DESC, play_time_seconds DESC, published_at_epoch ASC, account_id ASC
                        ) AS board_rank
                    FROM best_runs
                    WHERE account_rank = 1
                )
                SELECT board_rank
                FROM ranked
                WHERE account_id = ?
                """,
                (principal.account_id,),
            )
            board_rank = int(rank_row["board_rank"]) if rank_row is not None else None
        return {
            "submission_id": submission_id,
            "high_score": high_score,
            "board_rank": board_rank,
            "best_run": self._serialize_run_row(new_best),
        }

    def change_password(self, username: str, new_password: str) -> None:
        normalized_username = validate_username(username)
        normalized_password = validate_password(new_password)
        account = self.database.fetchone("SELECT id FROM accounts WHERE username = ?", (normalized_username,))
        if account is None:
            raise ServiceError("not_found", "User could not be found.")
        now = self.utcnow()
        self.database.execute(
            """
            UPDATE accounts
            SET password_hash = ?, auth_epoch = auth_epoch + 1, updated_at = ?
            WHERE username = ?
            """,
            (self.password_hasher.hash(normalized_password), now.isoformat(), normalized_username),
        )
        self.database.execute(
            "DELETE FROM auth_sessions WHERE account_id = ?",
            (int(account["id"]),),
        )

    def list_accounts(self, limit: int = 50) -> list[dict]:
        normalized_limit = max(1, min(500, int(limit)))
        rows = self.database.fetchall(
            """
            SELECT
                a.username,
                a.created_at,
                a.last_login_at,
                (SELECT COUNT(*) FROM account_devices d WHERE d.account_id = a.id) AS device_count,
                (SELECT COUNT(*) FROM submissions s WHERE s.account_id = a.id) AS submission_count
            FROM accounts a
            ORDER BY a.username COLLATE NOCASE ASC
            LIMIT ?
            """,
            (normalized_limit,),
        )
        return [
            {
                "username": str(row["username"]),
                "created_at": str(row["created_at"]),
                "last_login_at": str(row["last_login_at"]),
                "device_count": int(row["device_count"]),
                "submission_count": int(row["submission_count"]),
            }
            for row in rows
        ]

    def _authorize_device(self, account_id: int, device_hash: str, now: datetime) -> None:
        existing_device = self.database.fetchone(
            "SELECT device_hash FROM account_devices WHERE account_id = ? AND device_hash = ?",
            (account_id, device_hash),
        )
        if existing_device is not None:
            self.database.execute(
                "UPDATE account_devices SET last_seen_at = ? WHERE account_id = ? AND device_hash = ?",
                (now.isoformat(), account_id, device_hash),
            )
            return
        device_count_row = self.database.fetchone(
            "SELECT COUNT(*) AS device_count FROM account_devices WHERE account_id = ?",
            (account_id,),
        )
        device_count = int(device_count_row["device_count"]) if device_count_row is not None else 0
        if device_count >= ACCOUNT_DEVICE_LIMIT:
            raise ServiceError(
                "device_limit_reached",
                "This account has already been used on the maximum number of computers.",
            )
        self.database.execute(
            """
            INSERT INTO account_devices (account_id, device_hash, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?)
            """,
            (account_id, device_hash, now.isoformat(), now.isoformat()),
        )

    def _issue_session_token(self, account_id: int, device_hash: str, auth_epoch: int, now: datetime) -> str:
        token = uuid.uuid4().hex + uuid.uuid4().hex
        self.database.execute(
            """
            INSERT INTO auth_sessions (token, account_id, device_hash, auth_epoch, created_at, last_used_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                token,
                account_id,
                device_hash,
                auth_epoch,
                now.isoformat(),
                now.isoformat(),
                (now + timedelta(days=SESSION_LIFETIME_DAYS)).isoformat(),
            ),
        )
        return token

    def _enforce_account_creation_cooldown(self, device_hash: str) -> None:
        creation_record = self.database.fetchone(
            "SELECT last_created_at FROM device_account_creations WHERE device_hash = ?",
            (device_hash,),
        )
        if creation_record is None:
            return
        last_created_at = datetime.fromisoformat(str(creation_record["last_created_at"]))
        if (self.utcnow() - last_created_at) < timedelta(days=ACCOUNT_CREATION_COOLDOWN_DAYS):
            raise ServiceError(
                "account_creation_cooldown",
                "This computer must wait 7 days before creating another account.",
            )

    @staticmethod
    def _normalize_device_hash(device_hash: str) -> str:
        normalized = str(device_hash or "").strip().lower()
        if len(normalized) < 32 or len(normalized) > 128:
            raise ServiceError("invalid_device", "Invalid device identifier.")
        return normalized

    @staticmethod
    def _normalize_score(score: int) -> int:
        try:
            normalized = int(score)
        except (TypeError, ValueError) as exc:
            raise ServiceError("invalid_score", "Score must be an integer.") from exc
        if normalized < 0 or normalized > MAX_SCORE:
            raise ServiceError("invalid_score", "Score is outside the accepted range.")
        return normalized

    @staticmethod
    def _normalize_coins(coins: int) -> int:
        try:
            normalized = int(coins)
        except (TypeError, ValueError) as exc:
            raise ServiceError("invalid_coins", "Coins must be an integer.") from exc
        if normalized < 0 or normalized > MAX_COINS:
            raise ServiceError("invalid_coins", "Coin count is outside the accepted range.")
        return normalized

    @staticmethod
    def _normalize_play_time(play_time_seconds: int) -> int:
        try:
            normalized = int(play_time_seconds)
        except (TypeError, ValueError) as exc:
            raise ServiceError("invalid_play_time", "Play time must be an integer number of seconds.") from exc
        if normalized < 0 or normalized > MAX_PLAY_TIME_SECONDS:
            raise ServiceError("invalid_play_time", "Play time is outside the accepted range.")
        return normalized

    @staticmethod
    def _run_is_better(left, right) -> bool:
        left_tuple = (
            int(left["score"]),
            int(left["coins"]),
            int(left["play_time_seconds"]),
            -int(left["published_at_epoch"]),
        )
        right_tuple = (
            int(right["score"]),
            int(right["coins"]),
            int(right["play_time_seconds"]),
            -int(right["published_at_epoch"]),
        )
        return left_tuple > right_tuple

    @staticmethod
    def _serialize_leaderboard_row(row) -> dict:
        return {
            "account_id": int(row["account_id"]),
            "username": str(row["username"]),
            "submission_id": str(row["id"]),
            "score": int(row["score"]),
            "coins": int(row["coins"]),
            "play_time_seconds": int(row["play_time_seconds"]),
            "published_at": str(row["published_at"]),
            "rank": int(row["board_rank"]),
        }

    @staticmethod
    def _serialize_run_row(row) -> dict:
        return {
            "submission_id": str(row["id"]),
            "score": int(row["score"]),
            "coins": int(row["coins"]),
            "play_time_seconds": int(row["play_time_seconds"]),
            "published_at": str(row["published_at"]),
        }

    @staticmethod
    def _copy_leaderboard_payload(payload: dict) -> dict:
        return {
            "entries": [dict(entry) for entry in list(payload.get("entries") or [])],
            "offset": int(payload.get("offset", 0) or 0),
            "limit": int(payload.get("limit", 0) or 0),
            "total_players": int(payload.get("total_players", 0) or 0),
        }
