from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import math
import random
import re
import uuid

from argon2 import PasswordHasher

from subway_blind.balance import SPEED_PROFILES, speed_profile_for_difficulty
from subway_blind.features import HEADSTART_SPEED_BONUS, HOVERBOARD_MAX_USES_PER_RUN, REVIVE_MAX_USES_PER_RUN

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
EXPECTED_HOVERBOARD_USES_PER_RUN = HOVERBOARD_MAX_USES_PER_RUN
EXPECTED_REVIVES_PER_RUN = REVIVE_MAX_USES_PER_RUN
LEADERBOARD_PERIODS = ("season",)
LEADERBOARD_DIFFICULTY_FILTERS = ("all", "easy", "normal", "hard")
RUN_DIFFICULTIES = tuple(sorted(SPEED_PROFILES.keys()))
POWERUP_USAGE_KEYS = ("magnet", "jetpack", "mult2x", "sneakers", "pogo", "hoverboard")
DEVICE_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SEASON_REWARD_KINDS = ("coins", "hoverboard", "key", "headstart", "score_booster")
SEASON_ITEM_REWARD_COUNTS = (5, 5, 4, 4, 3, 3, 2, 2, 1, 1)
SEASON_COIN_REWARD_MULTIPLIERS = (3.0, 2.75, 2.5, 2.25, 2.0, 1.75, 1.5, 1.25, 1.1, 1.0)
SEASON_NAMES_2026 = (
    "Neon Kickoff",
    "Rail Rush",
    "Tunnel Echo",
    "Skyline Sprint",
    "Signal Surge",
    "Metro Pulse",
    "Steel Horizon",
    "Afterglow Dash",
    "Turbo Junction",
    "Sonic Drift",
    "City Flash",
    "Ember Track",
    "Voltage Alley",
    "Nightline Chase",
    "Chrome Current",
    "Beacon Burst",
    "Gravity Glide",
    "Sonic Overpass",
    "Iron Tempo",
    "Dawn Runner",
    "Prism Route",
    "Thunder Rail",
    "Velocity Bloom",
    "Horizon Break",
    "Firetrail Loop",
    "Rushline Prime",
    "Orbit Runner",
    "Asphalt Pulse",
    "Hyper Junction",
    "Aurora Tracks",
    "Echo Velocity",
    "Summit Sprint",
    "Flashpoint Run",
    "Neon Tide",
    "Railbreaker",
    "Zenith Rush",
    "Skyline Heat",
    "Pulsefront",
    "Circuit Dash",
    "Ember Velocity",
    "Metro Mirage",
    "Stormline",
    "Rapid Orbit",
    "Blueflare Run",
    "Trackstorm",
    "Luminous Rail",
    "Overdrive Week",
    "Midnight Momentum",
    "Frostline Sprint",
    "Golden Signal",
    "Final Ascent",
    "Nightshift Rush",
    "Terminal Crown",
)
SEASON_REWARD_LABELS = {
    "coins": "Coins",
    "hoverboard": "Hoverboard",
    "key": "Key",
    "headstart": "Headstart",
    "score_booster": "Score Booster",
}
SPECIAL_WHEEL_MAX_SPINS = 2
SPECIAL_ITEM_LABELS = {
    "phantom_step": "Phantom Step",
    "afterimage_dash": "Afterimage Dash",
    "crowd_jammer": "Crowd Jammer",
    "impact_foam": "Impact Foam",
    "overclock_key": "Overclock Key",
    "magnet_echo": "Magnet Echo",
    "quiet_jet": "Quiet Jet",
    "combo_battery": "Combo Battery",
    "hyper_sneakers": "Hyper Sneakers",
    "risk_converter": "Risk Converter",
    "jackpot_fuse": "Jackpot Fuse",
    "chain_saver": "Chain Saver",
    "vault_seal": "Vault Seal",
    "season_imprint": "Season Imprint",
}
SPECIAL_ITEM_KEYS = tuple(SPECIAL_ITEM_LABELS.keys())
SPECIAL_WHEEL_REWARD_WEIGHTS = {
    "phantom_step": 8,
    "afterimage_dash": 7,
    "crowd_jammer": 8,
    "impact_foam": 9,
    "overclock_key": 8,
    "magnet_echo": 8,
    "quiet_jet": 7,
    "combo_battery": 8,
    "hyper_sneakers": 7,
    "risk_converter": 8,
    "jackpot_fuse": 5,
    "chain_saver": 6,
    "vault_seal": 6,
    "season_imprint": 5,
}
SEASON_IMPRINT_BONUS_KEYS = (
    "coin_drift",
    "risk_bloom",
    "safe_stride",
    "power_echo",
    "fortune_line",
    "streak_guard",
    "spawn_calm",
)


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


@dataclass(frozen=True)
class SeasonDefinition:
    season_key: str
    season_name: str
    start_at: datetime
    end_at: datetime
    reward_kind: str

    @property
    def start_epoch(self) -> int:
        return int(self.start_at.timestamp())

    @property
    def end_epoch(self) -> int:
        return int(self.end_at.timestamp())


class LeaderboardService:
    def __init__(self, database: LeaderboardDatabase, password_hasher: PasswordHasher | None = None):
        self.database = database
        self.password_hasher = password_hasher or build_password_hasher()
        self._leaderboard_cache: dict[tuple[int, int, str, str, str], dict] = {}

    @staticmethod
    def utcnow() -> datetime:
        return datetime.now(UTC)

    def login_or_create_account(self, username: str, password: str, device_hash: str) -> dict:
        normalized_username = validate_username(username)
        normalized_password = validate_password(password)
        normalized_device_hash = self._normalize_device_hash(device_hash)
        self._ensure_season_state_current()
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
        self._ensure_season_state_current()
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

    def sync_account(
        self,
        principal: SessionPrincipal,
        claimed_reward_ids: list[str] | None = None,
        consumed_special_item_keys: list[str] | None = None,
    ) -> dict:
        principal = self.revalidate_principal(principal)
        self._acknowledge_reward_claims(principal.account_id, claimed_reward_ids or [])
        self._consume_special_items(principal.account_id, consumed_special_item_keys or [])
        current_season = self._ensure_season_state_current()
        pending_rewards = self._fetch_pending_rewards(principal.account_id)
        special_state = self._special_state_payload(principal.account_id)
        return {
            "username": principal.username,
            "season": self._serialize_season_definition(current_season),
            "pending_rewards": pending_rewards,
            "pending_reward_count": len(pending_rewards),
            "special_items": dict(special_state["items"]),
            "special_item_loadout": dict(special_state["loadout"]),
            "wheel": dict(special_state["wheel"]),
            "season_imprint_bonus": str(special_state["season_imprint_bonus"]),
        }

    def _consume_special_items(self, account_id: int, consumed_item_keys: list[str]) -> None:
        normalized_keys: list[str] = []
        for raw_key in consumed_item_keys:
            key = str(raw_key or "").strip().lower()
            if key not in SPECIAL_ITEM_KEYS:
                continue
            normalized_keys.append(key)
        if not normalized_keys:
            return
        unique_keys = list(dict.fromkeys(normalized_keys))[:64]
        now_text = self.utcnow().isoformat()
        connection = self.database.connection
        try:
            connection.execute("BEGIN")
            for item_key in unique_keys:
                row = connection.execute(
                    """
                    SELECT quantity
                    FROM account_special_items
                    WHERE account_id = ? AND item_key = ?
                    """,
                    (int(account_id), item_key),
                ).fetchone()
                if row is None:
                    continue
                current_quantity = max(0, int(row["quantity"] or 0))
                next_quantity = max(0, current_quantity - 1)
                connection.execute(
                    """
                    UPDATE account_special_items
                    SET quantity = ?, updated_at = ?
                    WHERE account_id = ? AND item_key = ?
                    """,
                    (next_quantity, now_text, int(account_id), item_key),
                )
                if next_quantity <= 0:
                    connection.execute(
                        """
                        UPDATE account_special_item_loadout
                        SET enabled = 0, updated_at = ?
                        WHERE account_id = ? AND item_key = ?
                        """,
                        (now_text, int(account_id), item_key),
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def spin_weekly_wheel(self, principal: SessionPrincipal) -> dict:
        principal = self.revalidate_principal(principal)
        week_key, week_start, next_reset_at = self._wheel_week_window_for_time(self.utcnow())
        usage_row = self.database.fetchone(
            """
            SELECT spins_used
            FROM wheel_spin_usage
            WHERE account_id = ? AND week_key = ?
            """,
            (principal.account_id, week_key),
        )
        spins_used = int(usage_row["spins_used"]) if usage_row is not None else 0
        if spins_used >= SPECIAL_WHEEL_MAX_SPINS:
            raise ServiceError("wheel_spins_exhausted", "No wheel spins remaining this week.")
        reward_key = random.choices(
            list(SPECIAL_WHEEL_REWARD_WEIGHTS.keys()),
            weights=list(SPECIAL_WHEEL_REWARD_WEIGHTS.values()),
            k=1,
        )[0]
        reward_amount = 1
        if reward_key in {"chain_saver", "vault_seal", "jackpot_fuse", "season_imprint"} and random.random() < 0.2:
            reward_amount = 2
        now = self.utcnow()
        now_text = now.isoformat()
        connection = self.database.connection
        try:
            connection.execute("BEGIN")
            connection.execute(
                """
                INSERT INTO wheel_spin_usage (account_id, week_key, spins_used, updated_at, last_spin_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(account_id, week_key) DO UPDATE
                SET spins_used = excluded.spins_used,
                    updated_at = excluded.updated_at,
                    last_spin_at = excluded.last_spin_at
                """,
                (principal.account_id, week_key, spins_used + 1, now_text, now_text),
            )
            connection.execute(
                """
                INSERT INTO account_special_items (account_id, item_key, quantity, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(account_id, item_key) DO UPDATE
                SET quantity = account_special_items.quantity + excluded.quantity,
                    updated_at = excluded.updated_at
                """,
                (principal.account_id, reward_key, reward_amount, now_text),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        wheel_status = self._wheel_status_for_account(
            account_id=principal.account_id,
            week_key=week_key,
            week_start=week_start,
            next_reset_at=next_reset_at,
        )
        special_state = self._special_state_payload(
            principal.account_id,
            cached_wheel=wheel_status,
            now=now,
        )
        return {
            "reward": {
                "item_key": reward_key,
                "item_label": self._special_item_label(reward_key),
                "amount": reward_amount,
            },
            "special_items": dict(special_state["items"]),
            "special_item_loadout": dict(special_state["loadout"]),
            "wheel": dict(special_state["wheel"]),
            "season_imprint_bonus": str(special_state["season_imprint_bonus"]),
        }

    def set_special_item_loadout(self, principal: SessionPrincipal, item_key: str, enabled: bool) -> dict:
        principal = self.revalidate_principal(principal)
        normalized_item_key = self._normalize_special_item_key(item_key)
        now = self.utcnow()
        now_text = now.isoformat()
        quantity_row = self.database.fetchone(
            """
            SELECT quantity
            FROM account_special_items
            WHERE account_id = ? AND item_key = ?
            """,
            (principal.account_id, normalized_item_key),
        )
        current_quantity = int(quantity_row["quantity"]) if quantity_row is not None else 0
        next_enabled = bool(enabled)
        if next_enabled and current_quantity <= 0:
            raise ServiceError("special_item_locked", "This special item is not owned on the server.")
        self.database.execute(
            """
            INSERT INTO account_special_item_loadout (account_id, item_key, enabled, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(account_id, item_key) DO UPDATE
            SET enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (principal.account_id, normalized_item_key, 1 if next_enabled else 0, now_text),
        )
        special_state = self._special_state_payload(principal.account_id, now=now)
        return {
            "item_key": normalized_item_key,
            "item_label": self._special_item_label(normalized_item_key),
            "enabled": bool(special_state["loadout"].get(normalized_item_key, False)),
            "special_items": dict(special_state["items"]),
            "special_item_loadout": dict(special_state["loadout"]),
            "wheel": dict(special_state["wheel"]),
            "season_imprint_bonus": str(special_state["season_imprint_bonus"]),
        }

    def fetch_leaderboard(
        self,
        offset: int = 0,
        limit: int = 100,
        period: str = "season",
        difficulty: str = "all",
    ) -> dict:
        current_season = self._ensure_season_state_current()
        normalized_offset = max(0, int(offset))
        normalized_limit = max(1, min(100, int(limit)))
        normalized_period = self._normalize_leaderboard_period(period)
        normalized_difficulty = self._normalize_leaderboard_difficulty_filter(difficulty)
        cache_key = (
            normalized_offset,
            normalized_limit,
            normalized_period,
            normalized_difficulty,
            current_season.season_key if normalized_period == "season" else "",
        )
        cached = self._leaderboard_cache.get(cache_key)
        if cached is not None:
            return self._copy_leaderboard_payload(cached)
        where_clause, filter_parameters = self._build_submission_filter_clause(
            normalized_period,
            normalized_difficulty,
            alias="s",
            current_season=current_season,
            verified_only=True,
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
            "season": self._serialize_season_definition(current_season),
        }
        self._leaderboard_cache[cache_key] = payload
        return self._copy_leaderboard_payload(payload)

    def fetch_profile(self, username: str, history_offset: int = 0, history_limit: int = 50) -> dict:
        current_season = self._ensure_season_state_current()
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
                WHERE s.published_at_epoch >= ? AND s.published_at_epoch < ? AND s.verification_status = 'verified'
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
            (current_season.start_epoch, current_season.end_epoch, account_id),
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
            "season": self._serialize_season_definition(current_season),
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
        current_season = self._ensure_season_state_current()
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
                    WHERE s.published_at_epoch >= ? AND s.published_at_epoch < ? AND s.verification_status = 'verified'
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
                (current_season.start_epoch, current_season.end_epoch, principal.account_id),
            )
            board_rank = int(rank_row["board_rank"]) if rank_row is not None else None
        return {
            "submission_id": submission_id,
            "high_score": high_score,
            "board_rank": board_rank,
            "season": self._serialize_season_definition(current_season),
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
        if not DEVICE_HASH_PATTERN.fullmatch(normalized):
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
        normalized = str(period or "season").strip().lower()
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

    def _ensure_season_state_current(self) -> SeasonDefinition:
        current_season = self._season_for_time(self.utcnow())
        self._finalize_completed_seasons(current_season)
        self._migrate_legacy_pending_rewards_to_inbox()
        self._purge_expired_leaderboard_data(current_season.start_epoch)
        self._ensure_season_row(current_season)
        return current_season

    def _season_for_time(self, value: datetime) -> SeasonDefinition:
        normalized = value.astimezone(UTC)
        start_at = (normalized - timedelta(days=normalized.weekday())).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        end_at = start_at + timedelta(days=7)
        season_key = f"{start_at.isocalendar().year}-W{start_at.isocalendar().week:02d}"
        season_name = self._season_name(season_key)
        reward_kind = self._season_reward_kind(start_at)
        return SeasonDefinition(
            season_key=season_key,
            season_name=season_name,
            start_at=start_at,
            end_at=end_at,
            reward_kind=reward_kind,
        )

    @staticmethod
    def _season_name(season_key: str) -> str:
        normalized_key = str(season_key or "").strip().upper()
        if normalized_key.startswith("2026-W"):
            try:
                week_number = int(normalized_key.split("-W", 1)[1])
            except (IndexError, ValueError):
                week_number = 0
            if 1 <= week_number <= len(SEASON_NAMES_2026):
                return SEASON_NAMES_2026[week_number - 1]
        return f"Weekly Season {normalized_key}" if normalized_key else "Weekly Season"

    def _season_reward_kind(self, season_start_at: datetime) -> str:
        normalized_start = season_start_at.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        rotation_index = int(normalized_start.timestamp() // int(timedelta(days=7).total_seconds()))
        return SEASON_REWARD_KINDS[rotation_index % len(SEASON_REWARD_KINDS)]

    def _ensure_season_row(self, season: SeasonDefinition) -> None:
        self.database.execute(
            """
            INSERT INTO leaderboard_seasons (
                season_key,
                start_at,
                end_at,
                start_epoch,
                end_epoch,
                reward_kind,
                created_at,
                finalized_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(season_key) DO NOTHING
            """,
            (
                season.season_key,
                season.start_at.isoformat(),
                season.end_at.isoformat(),
                int(season.start_at.timestamp()),
                int(season.end_at.timestamp()),
                season.reward_kind,
                self.utcnow().isoformat(),
            ),
        )

    def _finalize_completed_seasons(self, current_season: SeasonDefinition) -> None:
        seasons_to_finalize = self.database.fetchall(
            """
            SELECT season_key, start_at, end_at, start_epoch, end_epoch, reward_kind
            FROM leaderboard_seasons
            WHERE finalized_at IS NULL AND end_epoch <= ?
            ORDER BY end_epoch ASC
            """,
            (current_season.start_epoch,),
        )
        for row in seasons_to_finalize:
            self._finalize_season(row)

    def _finalize_season(self, season_row) -> None:
        season_key = str(season_row["season_key"])
        season_name = self._season_name(season_key)
        start_epoch = int(season_row["start_epoch"])
        end_epoch = int(season_row["end_epoch"])
        reward_kind = str(season_row["reward_kind"])
        ranked_rows = self.database.fetchall(
            """
            WITH filtered_submissions AS (
                SELECT
                    s.account_id,
                    s.id,
                    s.score,
                    s.coins,
                    s.play_time_seconds,
                    s.published_at_epoch
                FROM submissions s
                WHERE s.published_at_epoch >= ? AND s.published_at_epoch < ?
            ),
            best_runs AS (
                SELECT
                    account_id,
                    id,
                    score,
                    coins,
                    play_time_seconds,
                    published_at_epoch,
                    ROW_NUMBER() OVER (
                        PARTITION BY account_id
                        ORDER BY score DESC, coins DESC, play_time_seconds DESC, published_at_epoch ASC
                    ) AS account_rank
                FROM filtered_submissions
            ),
            ranked AS (
                SELECT
                    account_id,
                    id,
                    score,
                    coins,
                    play_time_seconds,
                    published_at_epoch,
                    ROW_NUMBER() OVER (
                        ORDER BY score DESC, coins DESC, play_time_seconds DESC, published_at_epoch ASC, account_id ASC
                    ) AS board_rank
                FROM best_runs
                WHERE account_rank = 1
            )
            SELECT account_id, id, coins, board_rank
            FROM ranked
            WHERE board_rank <= 10
            ORDER BY board_rank ASC
            """,
            (start_epoch, end_epoch),
        )
        now_text = self.utcnow().isoformat()
        connection = self.database.connection
        try:
            connection.execute("BEGIN")
            for row in ranked_rows:
                reward_amount, base_run_coins = self._season_reward_values(
                    reward_kind=reward_kind,
                    rank=int(row["board_rank"]),
                    coins=int(row["coins"]),
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO account_reward_inbox (
                        id,
                        account_id,
                        season_key,
                        season_name,
                        season_start_at,
                        season_end_at,
                        rank,
                        reward_kind,
                        reward_amount,
                        base_run_coins,
                        message,
                        created_at,
                        claimed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        uuid.uuid4().hex,
                        int(row["account_id"]),
                        season_key,
                        season_name,
                        str(season_row["start_at"]),
                        str(season_row["end_at"]),
                        int(row["board_rank"]),
                        reward_kind,
                        reward_amount,
                        base_run_coins,
                        self._season_reward_message(
                            season_key=season_key,
                            season_name=season_name,
                            reward_kind=reward_kind,
                            rank=int(row["board_rank"]),
                            reward_amount=reward_amount,
                            base_run_coins=base_run_coins,
                        ),
                        now_text,
                    ),
                )
            connection.execute(
                "UPDATE leaderboard_seasons SET finalized_at = ? WHERE season_key = ?",
                (now_text, season_key),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        self._leaderboard_cache.clear()

    def _migrate_legacy_pending_rewards_to_inbox(self) -> None:
        legacy_rows = self.database.fetchall(
            """
            SELECT
                r.id,
                r.account_id,
                r.season_key,
                r.rank,
                r.reward_kind,
                r.reward_amount,
                r.base_run_coins,
                r.message,
                r.created_at,
                s.start_at,
                s.end_at
            FROM season_rewards r
            INNER JOIN leaderboard_seasons s ON s.season_key = r.season_key
            WHERE r.claimed_at IS NULL
            ORDER BY s.end_epoch DESC, r.rank ASC
            """
        )
        if not legacy_rows:
            return
        connection = self.database.connection
        try:
            connection.execute("BEGIN")
            for row in legacy_rows:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO account_reward_inbox (
                        id,
                        account_id,
                        season_key,
                        season_name,
                        season_start_at,
                        season_end_at,
                        rank,
                        reward_kind,
                        reward_amount,
                        base_run_coins,
                        message,
                        created_at,
                        claimed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        str(row["id"]),
                        int(row["account_id"]),
                        str(row["season_key"]),
                        self._season_name(str(row["season_key"])),
                        str(row["start_at"]),
                        str(row["end_at"]),
                        int(row["rank"]),
                        str(row["reward_kind"]),
                        int(row["reward_amount"]),
                        int(row["base_run_coins"]) if row["base_run_coins"] is not None else None,
                        str(row["message"]),
                        str(row["created_at"]),
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def _purge_expired_leaderboard_data(self, current_season_start_epoch: int) -> None:
        connection = self.database.connection
        try:
            connection.execute("BEGIN")
            connection.execute(
                "DELETE FROM submissions WHERE published_at_epoch < ?",
                (int(current_season_start_epoch),),
            )
            connection.execute(
                "DELETE FROM season_rewards WHERE season_key IN (SELECT season_key FROM leaderboard_seasons WHERE end_epoch <= ?)",
                (int(current_season_start_epoch),),
            )
            connection.execute(
                "DELETE FROM leaderboard_seasons WHERE end_epoch <= ?",
                (int(current_season_start_epoch),),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        self._leaderboard_cache.clear()

    def _season_reward_values(self, *, reward_kind: str, rank: int, coins: int) -> tuple[int, int | None]:
        normalized_rank = max(1, min(10, int(rank)))
        if reward_kind == "coins":
            multiplier = SEASON_COIN_REWARD_MULTIPLIERS[normalized_rank - 1]
            normalized_coins = max(0, int(coins))
            return int(math.floor(normalized_coins * multiplier)), normalized_coins
        return int(SEASON_ITEM_REWARD_COUNTS[normalized_rank - 1]), None

    def _season_reward_message(
        self,
        *,
        season_key: str,
        season_name: str,
        reward_kind: str,
        rank: int,
        reward_amount: int,
        base_run_coins: int | None,
    ) -> str:
        reward_label = self._reward_kind_label(reward_kind, reward_amount)
        season_title = f"{season_name} ({season_key})"
        if reward_kind == "coins":
            multiplier = SEASON_COIN_REWARD_MULTIPLIERS[max(0, min(9, int(rank) - 1))]
            return (
                f"Season {season_title} reward: rank {rank} earned {reward_amount} coins "
                f"from {base_run_coins or 0} run coins at x{multiplier:.2f}."
            )
        return f"Season {season_title} reward: rank {rank} earned {reward_label}."

    def _fetch_pending_rewards(self, account_id: int) -> list[dict]:
        rows = self.database.fetchall(
            """
            SELECT
                r.id,
                r.season_key,
                r.rank,
                r.reward_kind,
                r.reward_amount,
                r.base_run_coins,
                r.message,
                r.created_at,
                r.season_name,
                r.season_start_at,
                r.season_end_at
            FROM account_reward_inbox r
            WHERE r.account_id = ? AND r.claimed_at IS NULL
            ORDER BY r.season_end_at DESC, r.rank ASC
            """,
            (account_id,),
        )
        return [
            {
                "id": str(row["id"]),
                "season_key": str(row["season_key"]),
                "season_name": str(row["season_name"]),
                "rank": int(row["rank"]),
                "reward_kind": str(row["reward_kind"]),
                "reward_label": self._reward_kind_label(str(row["reward_kind"]), int(row["reward_amount"])),
                "reward_amount": int(row["reward_amount"]),
                "base_run_coins": int(row["base_run_coins"]) if row["base_run_coins"] is not None else None,
                "message": str(row["message"]),
                "created_at": str(row["created_at"]),
                "season_start_at": str(row["season_start_at"]),
                "season_end_at": str(row["season_end_at"]),
            }
            for row in rows
        ]

    def _acknowledge_reward_claims(self, account_id: int, reward_ids: list[str]) -> None:
        normalized_ids = [str(reward_id).strip() for reward_id in reward_ids if str(reward_id).strip()]
        if not normalized_ids:
            return
        unique_ids = list(dict.fromkeys(normalized_ids))[:256]
        placeholders = ", ".join("?" for _ in unique_ids)
        self.database.execute(
            f"""
            UPDATE account_reward_inbox
            SET claimed_at = ?
            WHERE account_id = ? AND claimed_at IS NULL AND id IN ({placeholders})
            """,
            (self.utcnow().isoformat(), account_id, *unique_ids),
        )

    def _special_state_payload(
        self,
        account_id: int,
        *,
        cached_wheel: dict | None = None,
        now: datetime | None = None,
    ) -> dict:
        current_time = now or self.utcnow()
        week_key, week_start, next_reset_at = self._wheel_week_window_for_time(current_time)
        items = self._special_items_for_account(account_id)
        loadout = self._special_item_loadout_for_account(account_id, items)
        wheel = cached_wheel or self._wheel_status_for_account(
            account_id=account_id,
            week_key=week_key,
            week_start=week_start,
            next_reset_at=next_reset_at,
        )
        return {
            "items": items,
            "loadout": loadout,
            "wheel": wheel,
            "season_imprint_bonus": self._season_imprint_bonus_key(week_key),
        }

    def _special_items_for_account(self, account_id: int) -> dict[str, int]:
        rows = self.database.fetchall(
            """
            SELECT item_key, quantity
            FROM account_special_items
            WHERE account_id = ?
            """,
            (int(account_id),),
        )
        normalized: dict[str, int] = {}
        for row in rows:
            item_key = str(row["item_key"] or "").strip().lower()
            if item_key not in SPECIAL_ITEM_KEYS:
                continue
            quantity = max(0, int(row["quantity"] or 0))
            if quantity > 0:
                normalized[item_key] = quantity
        return normalized

    def _special_item_loadout_for_account(self, account_id: int, items: dict[str, int]) -> dict[str, bool]:
        rows = self.database.fetchall(
            """
            SELECT item_key, enabled
            FROM account_special_item_loadout
            WHERE account_id = ?
            """,
            (int(account_id),),
        )
        enabled_map = {
            str(row["item_key"] or "").strip().lower(): bool(int(row["enabled"] or 0))
            for row in rows
            if str(row["item_key"] or "").strip().lower() in SPECIAL_ITEM_KEYS
        }
        normalized: dict[str, bool] = {}
        for item_key in SPECIAL_ITEM_KEYS:
            if int(items.get(item_key, 0)) <= 0:
                normalized[item_key] = False
                continue
            normalized[item_key] = bool(enabled_map.get(item_key, False))
        return normalized

    def _wheel_status_for_account(
        self,
        *,
        account_id: int,
        week_key: str,
        week_start: datetime,
        next_reset_at: datetime,
    ) -> dict:
        row = self.database.fetchone(
            """
            SELECT spins_used
            FROM wheel_spin_usage
            WHERE account_id = ? AND week_key = ?
            """,
            (int(account_id), str(week_key)),
        )
        spins_used = max(0, int(row["spins_used"] or 0)) if row is not None else 0
        spins_used = min(SPECIAL_WHEEL_MAX_SPINS, spins_used)
        return {
            "week_key": week_key,
            "week_start_at": week_start.isoformat(),
            "next_reset_at": next_reset_at.isoformat(),
            "max_spins": SPECIAL_WHEEL_MAX_SPINS,
            "spins_used": spins_used,
            "spins_remaining": max(0, SPECIAL_WHEEL_MAX_SPINS - spins_used),
        }

    @staticmethod
    def _wheel_week_window_for_time(value: datetime) -> tuple[str, datetime, datetime]:
        normalized = value.astimezone(UTC)
        start_of_day = normalized.replace(hour=0, minute=0, second=0, microsecond=0)
        days_since_wednesday = (start_of_day.weekday() - 2) % 7
        week_start = start_of_day - timedelta(days=days_since_wednesday)
        next_reset = week_start + timedelta(days=7)
        week_key = week_start.strftime("%Y-%m-%d")
        return week_key, week_start, next_reset

    @staticmethod
    def _season_imprint_bonus_key(week_key: str) -> str:
        if not week_key:
            return SEASON_IMPRINT_BONUS_KEYS[0]
        total = 0
        for char in str(week_key):
            total += ord(char)
        return SEASON_IMPRINT_BONUS_KEYS[total % len(SEASON_IMPRINT_BONUS_KEYS)]

    @staticmethod
    def _special_item_label(item_key: str) -> str:
        normalized = str(item_key or "").strip().lower()
        return SPECIAL_ITEM_LABELS.get(normalized, "Special Item")

    @staticmethod
    def _normalize_special_item_key(item_key: str) -> str:
        normalized = str(item_key or "").strip().lower()
        if normalized not in SPECIAL_ITEM_KEYS:
            raise ServiceError("invalid_special_item", "Unknown special item.")
        return normalized

    def _serialize_season_definition(self, season: SeasonDefinition) -> dict:
        seconds_remaining = max(0, int((season.end_at - self.utcnow()).total_seconds()))
        return {
            "season_key": season.season_key,
            "season_name": season.season_name,
            "starts_at": season.start_at.isoformat(),
            "ends_at": season.end_at.isoformat(),
            "seconds_remaining": seconds_remaining,
            "reward_kind": season.reward_kind,
            "reward_label": self._reward_kind_label(season.reward_kind, 2),
            "reward_preview": self._season_reward_preview(season.reward_kind),
        }

    def _season_reward_preview(self, reward_kind: str) -> str:
        if reward_kind == "coins":
            return (
                f"Rank 1 earns x{SEASON_COIN_REWARD_MULTIPLIERS[0]:.2f} run coins. "
                f"Rank 10 earns x{SEASON_COIN_REWARD_MULTIPLIERS[9]:.2f} run coins."
            )
        return (
            f"Rank 1 earns {SEASON_ITEM_REWARD_COUNTS[0]} {self._reward_kind_label(reward_kind, SEASON_ITEM_REWARD_COUNTS[0])}. "
            f"Rank 10 earns {SEASON_ITEM_REWARD_COUNTS[9]} {self._reward_kind_label(reward_kind, SEASON_ITEM_REWARD_COUNTS[9])}."
        )

    def _reward_kind_label(self, reward_kind: str, amount: int) -> str:
        base_label = SEASON_REWARD_LABELS.get(str(reward_kind), "Reward")
        if str(reward_kind) == "coins":
            return "Coin" if int(amount) == 1 else "Coins"
        if str(reward_kind) == "hoverboard":
            return "Hoverboard" if int(amount) == 1 else "Hoverboards"
        if str(reward_kind) == "key":
            return "Key" if int(amount) == 1 else "Keys"
        if str(reward_kind) == "headstart":
            return "Headstart" if int(amount) == 1 else "Headstarts"
        if str(reward_kind) == "score_booster":
            return "Score Booster" if int(amount) == 1 else "Score Boosters"
        return base_label

    def _build_submission_filter_clause(
        self,
        period: str,
        difficulty: str,
        alias: str,
        current_season: SeasonDefinition | None = None,
        verified_only: bool = False,
    ) -> tuple[str, tuple[object, ...]]:
        parts: list[str] = []
        parameters: list[object] = []
        if verified_only:
            parts.append(f"{alias}.verification_status = ?")
            parameters.append("verified")
        if period == "season":
            season = current_season or self._ensure_season_state_current()
            parts.append(f"{alias}.published_at_epoch >= ?")
            parameters.append(int(season.start_at.timestamp()))
            parts.append(f"{alias}.published_at_epoch < ?")
            parameters.append(int(season.end_at.timestamp()))
        else:
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
        if revives_used is not None and revives_used > EXPECTED_REVIVES_PER_RUN:
            reasons.append(f"Revive count exceeds the in-game run limit ({EXPECTED_REVIVES_PER_RUN}).")
        hoverboard_uses = int(powerup_usage.get("hoverboard", 0) or 0)
        if hoverboard_uses > EXPECTED_HOVERBOARD_USES_PER_RUN:
            reasons.append(
                f"Hoverboard activations exceed the in-game run limit ({EXPECTED_HOVERBOARD_USES_PER_RUN})."
            )
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
            "period": str(payload.get("period") or "season"),
            "difficulty": str(payload.get("difficulty") or "all"),
            "season": dict(payload.get("season") or {}),
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
