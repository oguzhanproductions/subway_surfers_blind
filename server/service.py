from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import uuid

from argon2 import PasswordHasher

from subway_blind.balance import SPEED_PROFILES, speed_profile_for_difficulty
from subway_blind.features import HEADSTART_SPEED_BONUS

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
MAX_DISTANCE_METERS = 5_000_000
MAX_CLEAN_ESCAPES = 250_000
MAX_REVIVES_USED = 250
MAX_POWERUP_ACTIVATIONS = 100_000
LEADERBOARD_PERIODS = ("all_time", "daily", "weekly", "monthly")
LEADERBOARD_DIFFICULTY_FILTERS = ("all", "easy", "normal", "hard")
RUN_DIFFICULTIES = tuple(sorted(SPEED_PROFILES.keys()))
POWERUP_USAGE_KEYS = ("magnet", "jetpack", "mult2x", "sneakers", "pogo", "hoverboard")


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
        self._leaderboard_cache: dict[tuple[int, int, str, str], dict] = {}

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

    def fetch_leaderboard(
        self,
        offset: int = 0,
        limit: int = 100,
        period: str = "all_time",
        difficulty: str = "all",
    ) -> dict:
        normalized_offset = max(0, int(offset))
        normalized_limit = max(1, min(100, int(limit)))
        normalized_period = self._normalize_leaderboard_period(period)
        normalized_difficulty = self._normalize_leaderboard_difficulty_filter(difficulty)
        cache_key = (normalized_offset, normalized_limit, normalized_period, normalized_difficulty)
        cached = self._leaderboard_cache.get(cache_key)
        if cached is not None:
            return self._copy_leaderboard_payload(cached)
        where_clause, filter_parameters = self._build_submission_filter_clause(
            normalized_period,
            normalized_difficulty,
            alias="s",
        )
        rows = self.database.fetchall(
            f"""
            WITH filtered_submissions AS (
                SELECT
                    s.account_id,
                    a.username,
                    s.id,
                    s.score,
                    s.coins,
                    s.play_time_seconds,
                    s.published_at,
                    s.published_at_epoch,
                    s.difficulty,
                    s.verification_status
                FROM submissions s
                INNER JOIN accounts a ON a.id = s.account_id
                {where_clause}
            ),
            best_runs AS (
                SELECT
                    account_id,
                    username,
                    id,
                    score,
                    coins,
                    play_time_seconds,
                    published_at,
                    published_at_epoch,
                    difficulty,
                    verification_status,
                    ROW_NUMBER() OVER (
                        PARTITION BY account_id
                        ORDER BY score DESC, coins DESC, play_time_seconds DESC, published_at_epoch ASC
                    ) AS account_rank
                FROM filtered_submissions
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
                    difficulty,
                    verification_status,
                    ROW_NUMBER() OVER (
                        ORDER BY score DESC, coins DESC, play_time_seconds DESC, published_at_epoch ASC, account_id ASC
                    ) AS board_rank
                FROM best_runs
                WHERE account_rank = 1
            )
            SELECT account_id, username, id, score, coins, play_time_seconds, published_at, difficulty, verification_status, board_rank
            FROM ranked
            ORDER BY board_rank
            LIMIT ? OFFSET ?
            """,
            (*filter_parameters, normalized_limit, normalized_offset),
        )
        total = self.database.fetchone(
            f"""
            SELECT COUNT(DISTINCT s.account_id) AS total_players
            FROM submissions s
            {where_clause}
            """,
            filter_parameters,
        )
        payload = {
            "entries": [self._serialize_leaderboard_row(row) for row in rows],
            "offset": normalized_offset,
            "limit": normalized_limit,
            "total_players": int(total["total_players"]) if total is not None else 0,
            "period": normalized_period,
            "difficulty": normalized_difficulty,
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
            SELECT
                id,
                score,
                coins,
                play_time_seconds,
                published_at,
                published_at_epoch,
                game_version,
                difficulty,
                death_reason,
                distance_meters,
                clean_escapes,
                revives_used,
                powerup_usage_json,
                verification_status,
                verification_reasons_json
            FROM submissions
            WHERE account_id = ?
            ORDER BY published_at_epoch DESC
            LIMIT 1
            """,
            (account_id,),
        )
        best_run = self.database.fetchone(
            """
            SELECT
                id,
                score,
                coins,
                play_time_seconds,
                published_at,
                published_at_epoch,
                game_version,
                difficulty,
                death_reason,
                distance_meters,
                clean_escapes,
                revives_used,
                powerup_usage_json,
                verification_status,
                verification_reasons_json
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
            SELECT
                id,
                score,
                coins,
                play_time_seconds,
                published_at,
                published_at_epoch,
                game_version,
                difficulty,
                death_reason,
                distance_meters,
                clean_escapes,
                revives_used,
                powerup_usage_json,
                verification_status,
                verification_reasons_json
            FROM submissions
            WHERE account_id = ?
            ORDER BY published_at_epoch DESC
            LIMIT ? OFFSET ?
            """,
            (account_id, normalized_limit, normalized_offset),
        )
        recent_rows = self.database.fetchall(
            """
            SELECT score, coins, play_time_seconds, distance_meters
            FROM submissions
            WHERE account_id = ?
            ORDER BY published_at_epoch DESC, id DESC
            LIMIT 10
            """,
            (account_id,),
        )
        history_total_row = self.database.fetchone(
            """
            SELECT
                COUNT(*) AS total_runs,
                COUNT(DISTINCT substr(published_at, 1, 10)) AS active_days
            FROM submissions
            WHERE account_id = ?
            """,
            (account_id,),
        )
        improvement_row = self.database.fetchone(
            """
            WITH ordered_runs AS (
                SELECT
                    score,
                    LAG(score) OVER (ORDER BY published_at_epoch ASC, id ASC) AS previous_score
                FROM submissions
                WHERE account_id = ?
            )
            SELECT MAX(score - previous_score) AS best_improvement_score
            FROM ordered_runs
            WHERE previous_score IS NOT NULL
            """,
            (account_id,),
        )
        return {
            "username": str(account["username"]),
            "board_rank": int(board_rank_row["board_rank"]) if board_rank_row is not None else None,
            "latest_run": self._serialize_run_row(latest_run),
            "best_run": self._serialize_run_row(best_run),
            "summary": self._summarize_profile(
                recent_rows,
                total_runs=int(history_total_row["total_runs"]) if history_total_row is not None else 0,
                active_days=int(history_total_row["active_days"]) if history_total_row is not None else 0,
                best_improvement_score=int(improvement_row["best_improvement_score"] or 0)
                if improvement_row is not None
                else 0,
            ),
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
        difficulty: str = "unknown",
        death_reason: str = "",
        distance_meters: int | None = None,
        clean_escapes: int | None = None,
        revives_used: int | None = None,
        powerup_usage: dict[str, int] | None = None,
    ) -> dict:
        principal = self.revalidate_principal(principal)
        normalized_score = self._normalize_score(score)
        normalized_coins = self._normalize_coins(coins)
        normalized_play_time = self._normalize_play_time(play_time_seconds)
        normalized_difficulty = self._normalize_run_difficulty(difficulty)
        normalized_death_reason = self._normalize_optional_text(death_reason, max_length=160)
        normalized_distance = self._normalize_optional_counter(
            distance_meters,
            code="invalid_distance",
            message="Distance is outside the accepted range.",
            upper_bound=MAX_DISTANCE_METERS,
        )
        normalized_clean_escapes = self._normalize_optional_counter(
            clean_escapes,
            code="invalid_clean_escapes",
            message="Clean escape count is outside the accepted range.",
            upper_bound=MAX_CLEAN_ESCAPES,
        )
        normalized_revives_used = self._normalize_optional_counter(
            revives_used,
            code="invalid_revives",
            message="Revive count is outside the accepted range.",
            upper_bound=MAX_REVIVES_USED,
            default=0,
        )
        normalized_powerup_usage = self._normalize_powerup_usage(powerup_usage)
        verification_status, verification_reasons = self._assess_run_verification(
            play_time_seconds=normalized_play_time,
            difficulty=normalized_difficulty,
            distance_meters=normalized_distance,
            clean_escapes=normalized_clean_escapes,
            revives_used=normalized_revives_used,
            powerup_usage=normalized_powerup_usage,
        )
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
                device_hash,
                difficulty,
                death_reason,
                distance_meters,
                clean_escapes,
                revives_used,
                powerup_usage_json,
                verification_status,
                verification_reasons_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                normalized_difficulty,
                normalized_death_reason,
                normalized_distance,
                normalized_clean_escapes,
                normalized_revives_used,
                json.dumps(normalized_powerup_usage, separators=(",", ":"), sort_keys=True),
                verification_status,
                json.dumps(verification_reasons, separators=(",", ":"), ensure_ascii=False),
            ),
        )
        self._leaderboard_cache.clear()
        new_best = self.database.fetchone(
            """
            SELECT
                id,
                score,
                coins,
                play_time_seconds,
                published_at,
                published_at_epoch,
                game_version,
                difficulty,
                death_reason,
                distance_meters,
                clean_escapes,
                revives_used,
                powerup_usage_json,
                verification_status,
                verification_reasons_json
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
            "verification_status": verification_status,
            "verification_reasons": list(verification_reasons),
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
    def _normalize_optional_counter(
        value: int | None,
        *,
        code: str,
        message: str,
        upper_bound: int,
        default: int | None = None,
    ) -> int | None:
        if value is None:
            return default
        try:
            normalized = int(value)
        except (TypeError, ValueError) as exc:
            raise ServiceError(code, message) from exc
        if normalized < 0 or normalized > upper_bound:
            raise ServiceError(code, message)
        return normalized

    @staticmethod
    def _normalize_optional_text(value: str, max_length: int) -> str:
        normalized = str(value or "").strip()
        if len(normalized) > max_length:
            return normalized[:max_length].rstrip()
        return normalized

    @staticmethod
    def _normalize_leaderboard_period(period: str) -> str:
        normalized = str(period or "all_time").strip().lower()
        if normalized not in LEADERBOARD_PERIODS:
            raise ServiceError("invalid_period", "Unsupported leaderboard period.")
        return normalized

    @staticmethod
    def _normalize_leaderboard_difficulty_filter(difficulty: str) -> str:
        normalized = str(difficulty or "all").strip().lower()
        if normalized not in LEADERBOARD_DIFFICULTY_FILTERS:
            raise ServiceError("invalid_difficulty", "Unsupported leaderboard difficulty filter.")
        return normalized

    @staticmethod
    def _normalize_run_difficulty(difficulty: str) -> str:
        normalized = str(difficulty or "unknown").strip().lower()
        if normalized in RUN_DIFFICULTIES:
            return normalized
        if normalized in {"", "all", "unknown"}:
            return "unknown"
        raise ServiceError("invalid_difficulty", "Unsupported run difficulty.")

    @staticmethod
    def _normalize_powerup_usage(powerup_usage: dict[str, int] | None) -> dict[str, int]:
        if powerup_usage is None:
            return {}
        if not isinstance(powerup_usage, dict):
            raise ServiceError("invalid_powerups", "Power-up usage data is invalid.")
        normalized: dict[str, int] = {}
        for key in POWERUP_USAGE_KEYS:
            raw_value = powerup_usage.get(key, 0)
            try:
                amount = int(raw_value)
            except (TypeError, ValueError) as exc:
                raise ServiceError("invalid_powerups", "Power-up usage data is invalid.") from exc
            if amount < 0 or amount > MAX_POWERUP_ACTIVATIONS:
                raise ServiceError("invalid_powerups", "Power-up usage data is outside the accepted range.")
            if amount > 0:
                normalized[key] = amount
        return normalized

    def _build_submission_filter_clause(self, period: str, difficulty: str, alias: str) -> tuple[str, tuple[object, ...]]:
        parts: list[str] = []
        parameters: list[object] = []
        period_start = self._leaderboard_period_start_epoch(period)
        if period_start is not None:
            parts.append(f"{alias}.published_at_epoch >= ?")
            parameters.append(period_start)
        if difficulty != "all":
            parts.append(f"{alias}.difficulty = ?")
            parameters.append(difficulty)
        if not parts:
            return "", tuple()
        return "WHERE " + " AND ".join(parts), tuple(parameters)

    def _leaderboard_period_start_epoch(self, period: str) -> int | None:
        if period == "all_time":
            return None
        now = self.utcnow()
        if period == "daily":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "weekly":
            start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "monthly":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            raise ServiceError("invalid_period", "Unsupported leaderboard period.")
        return int(start.timestamp())

    def _assess_run_verification(
        self,
        *,
        play_time_seconds: int,
        difficulty: str,
        distance_meters: int | None,
        clean_escapes: int | None,
        revives_used: int | None,
        powerup_usage: dict[str, int],
    ) -> tuple[str, list[str]]:
        reasons: list[str] = []
        if distance_meters is not None and play_time_seconds > 0:
            profile = speed_profile_for_difficulty(difficulty) if difficulty in RUN_DIFFICULTIES else max(
                SPEED_PROFILES.values(),
                key=lambda current: current.max_speed,
            )
            maximum_distance = int((profile.max_speed + HEADSTART_SPEED_BONUS) * play_time_seconds + 250)
            if distance_meters > maximum_distance:
                reasons.append("Distance exceeds the maximum travel range for the recorded play time.")
        if distance_meters is not None and clean_escapes is not None:
            if clean_escapes > max(25, distance_meters // 3):
                reasons.append("Clean escape count is outside the expected range for the recorded distance.")
        if revives_used is not None and revives_used > 25:
            reasons.append("Revive count is unusually high for a single published run.")
        if powerup_usage and play_time_seconds >= 0:
            total_powerups = sum(powerup_usage.values())
            if total_powerups > max(12, (play_time_seconds // 3) + 6):
                reasons.append("Power-up activations are unusually high for the recorded play time.")
        return ("suspicious" if reasons else "verified"), reasons

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
            "difficulty": str(row["difficulty"] or "unknown"),
            "verification_status": str(row["verification_status"] or "verified"),
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
            "game_version": str(row["game_version"] or "unknown"),
            "difficulty": str(row["difficulty"] or "unknown"),
            "death_reason": str(row["death_reason"] or "Run ended."),
            "distance_meters": int(row["distance_meters"]) if row["distance_meters"] is not None else None,
            "clean_escapes": int(row["clean_escapes"]) if row["clean_escapes"] is not None else None,
            "revives_used": int(row["revives_used"]) if row["revives_used"] is not None else 0,
            "powerup_usage": LeaderboardService._deserialize_powerup_usage(row["powerup_usage_json"]),
            "verification_status": str(row["verification_status"] or "verified"),
            "verification_reasons": LeaderboardService._deserialize_text_list(row["verification_reasons_json"]),
        }

    @staticmethod
    def _copy_leaderboard_payload(payload: dict) -> dict:
        return {
            "entries": [dict(entry) for entry in list(payload.get("entries") or [])],
            "offset": int(payload.get("offset", 0) or 0),
            "limit": int(payload.get("limit", 0) or 0),
            "total_players": int(payload.get("total_players", 0) or 0),
            "period": str(payload.get("period") or "all_time"),
            "difficulty": str(payload.get("difficulty") or "all"),
        }

    @staticmethod
    def _deserialize_powerup_usage(value: object) -> dict[str, int]:
        if value in (None, ""):
            return {}
        try:
            decoded = json.loads(str(value))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        if not isinstance(decoded, dict):
            return {}
        normalized: dict[str, int] = {}
        for key in POWERUP_USAGE_KEYS:
            raw_amount = decoded.get(key)
            if raw_amount in (None, ""):
                continue
            try:
                amount = int(raw_amount)
            except (TypeError, ValueError):
                continue
            if amount > 0:
                normalized[key] = amount
        return normalized

    @staticmethod
    def _deserialize_text_list(value: object) -> list[str]:
        if value in (None, ""):
            return []
        try:
            decoded = json.loads(str(value))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(decoded, list):
            return []
        return [str(entry).strip() for entry in decoded if str(entry).strip()]

    @staticmethod
    def _summarize_profile(
        recent_rows,
        *,
        total_runs: int,
        active_days: int,
        best_improvement_score: int,
    ) -> dict:
        row_count = len(recent_rows)
        total_score = sum(int(row["score"]) for row in recent_rows)
        total_coins = sum(int(row["coins"]) for row in recent_rows)
        total_play_time = sum(int(row["play_time_seconds"]) for row in recent_rows)
        total_distance = sum(int(row["distance_meters"]) for row in recent_rows if row["distance_meters"] is not None)
        distance_row_count = sum(1 for row in recent_rows if row["distance_meters"] is not None)
        return {
            "recent_average_score": int(round(total_score / row_count)) if row_count else 0,
            "recent_average_coins": int(round(total_coins / row_count)) if row_count else 0,
            "recent_average_play_time_seconds": int(round(total_play_time / row_count)) if row_count else 0,
            "recent_average_distance_meters": int(round(total_distance / distance_row_count)) if distance_row_count else 0,
            "best_improvement_score": max(0, int(best_improvement_score or 0)),
            "published_runs_total": int(total_runs),
            "active_days": int(active_days),
        }
