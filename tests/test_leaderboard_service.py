import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from server.database import LeaderboardDatabase
from server.service import LeaderboardService, ServiceError
from subway_blind.leaderboard_protocol import (
    CLIENT_SEND_NONCE_PREFIX,
    SERVER_SEND_NONCE_PREFIX,
    SecureChannel,
    derive_session_key,
    generate_private_key,
)


class LeaderboardServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database = LeaderboardDatabase(Path(self.temp_directory.name) / "leaderboard.sqlite3")
        self.service = LeaderboardService(self.database)

    def tearDown(self):
        self.database.close()
        self.temp_directory.cleanup()

    def test_login_creates_account_and_reuses_same_device_without_spending_slot(self):
        created = self.service.login_or_create_account("runner01", "secret123", "a" * 64)
        logged_in = self.service.login_or_create_account("runner01", "secret123", "a" * 64)

        self.assertEqual(created["status"], "created")
        self.assertEqual(logged_in["status"], "logged_in")
        count_row = self.database.fetchone("SELECT COUNT(*) AS device_count FROM account_devices WHERE account_id = 1")
        self.assertEqual(int(count_row["device_count"]), 1)

    def test_account_creation_is_limited_per_device_for_seven_days(self):
        self.service.login_or_create_account("runner01", "secret123", "a" * 64)

        with self.assertRaises(ServiceError) as context:
            self.service.login_or_create_account("runner02", "secret123", "a" * 64)

        self.assertEqual(context.exception.code, "account_creation_cooldown")

    def test_account_allows_only_three_different_devices(self):
        self.service.login_or_create_account("runner01", "secret123", "a" * 64)
        self.service.login_or_create_account("runner01", "secret123", "b" * 64)
        self.service.login_or_create_account("runner01", "secret123", "c" * 64)

        with self.assertRaises(ServiceError) as context:
            self.service.login_or_create_account("runner01", "secret123", "d" * 64)

        self.assertEqual(context.exception.code, "device_limit_reached")

    def test_password_change_invalidates_existing_sessions(self):
        result = self.service.login_or_create_account("runner01", "secret123", "a" * 64)
        principal = result["principal"]

        self.service.change_password("runner01", "updated-secret")

        with self.assertRaises(ServiceError) as context:
            self.service.revalidate_principal(principal)

        self.assertEqual(context.exception.code, "reauth_required")

    def test_login_with_invalid_stored_hash_fails_as_invalid_credentials(self):
        created = self.service.login_or_create_account("runner01", "secret123", "a" * 64)
        self.database.execute(
            "UPDATE accounts SET password_hash = ? WHERE id = ?",
            ("not-a-valid-argon2-hash", created["principal"].account_id),
        )

        with self.assertRaises(ServiceError) as context:
            self.service.login_or_create_account("runner01", "secret123", "a" * 64)

        self.assertEqual(context.exception.code, "invalid_credentials")

    def test_session_can_resume_after_reconnect_on_same_device(self):
        result = self.service.login_or_create_account("runner01", "secret123", "a" * 64)

        resumed = self.service.resume_session(result["session_token"], "a" * 64)

        self.assertEqual(resumed.username, "runner01")

    def test_session_cannot_resume_on_different_device(self):
        result = self.service.login_or_create_account("runner01", "secret123", "a" * 64)

        with self.assertRaises(ServiceError) as context:
            self.service.resume_session(result["session_token"], "b" * 64)

        self.assertEqual(context.exception.code, "reauth_required")

    def test_submit_score_promotes_new_high_score_and_returns_rank(self):
        first = self.service.login_or_create_account("runner01", "secret123", "a" * 64)
        second = self.service.login_or_create_account("runner02", "secret123", "b" * 64)
        self.service.submit_score(first["principal"], score=100, coins=4, play_time_seconds=20, game_version="1.0")
        self.service.submit_score(second["principal"], score=200, coins=6, play_time_seconds=30, game_version="1.0")

        result = self.service.submit_score(first["principal"], score=300, coins=7, play_time_seconds=35, game_version="1.0")
        board = self.service.fetch_leaderboard()

        self.assertTrue(result["high_score"])
        self.assertEqual(result["board_rank"], 1)
        self.assertEqual(board["entries"][0]["username"], "runner01")

    def test_fetch_leaderboard_filters_by_period_and_difficulty(self):
        easy = self.service.login_or_create_account("runner01", "secret123", "a" * 64)
        hard = self.service.login_or_create_account("runner02", "secret123", "b" * 64)
        old = self.service.login_or_create_account("runner03", "secret123", "c" * 64)
        submission_times = [
            datetime(2026, 3, 26, 8, 0, tzinfo=UTC),
            datetime(2026, 3, 29, 9, 30, tzinfo=UTC),
            datetime(2026, 2, 10, 14, 0, tzinfo=UTC),
        ]
        with patch.object(self.service, "utcnow", side_effect=submission_times):
            self.service.submit_score(easy["principal"], score=900, coins=11, play_time_seconds=70, game_version="1.0", difficulty="easy")
            self.service.submit_score(hard["principal"], score=1500, coins=14, play_time_seconds=82, game_version="1.0", difficulty="hard")
            self.service.submit_score(old["principal"], score=1900, coins=18, play_time_seconds=95, game_version="1.0", difficulty="hard")

        with patch.object(self.service, "utcnow", return_value=datetime(2026, 3, 29, 12, 0, tzinfo=UTC)):
            weekly_hard = self.service.fetch_leaderboard(period="weekly", difficulty="hard")
            monthly_all = self.service.fetch_leaderboard(period="monthly", difficulty="all")

        self.assertEqual(weekly_hard["total_players"], 1)
        self.assertEqual(weekly_hard["entries"][0]["username"], "runner02")
        self.assertEqual(weekly_hard["entries"][0]["difficulty"], "hard")
        self.assertEqual(monthly_all["total_players"], 2)
        self.assertEqual(monthly_all["entries"][0]["username"], "runner02")

    def test_profile_includes_summary_and_extended_run_metadata(self):
        result = self.service.login_or_create_account("runner01", "secret123", "a" * 64)
        submission_times = [
            datetime(2026, 3, 28, 10, 0, tzinfo=UTC),
            datetime(2026, 3, 29, 11, 0, tzinfo=UTC),
        ]
        with patch.object(self.service, "utcnow", side_effect=submission_times):
            self.service.submit_score(
                result["principal"],
                score=1000,
                coins=8,
                play_time_seconds=61,
                game_version="1.1.3",
                difficulty="normal",
                death_reason="Hit train",
                distance_meters=1180,
                clean_escapes=4,
                revives_used=1,
                powerup_usage={"magnet": 1, "hoverboard": 1},
            )
            self.service.submit_score(
                result["principal"],
                score=1450,
                coins=12,
                play_time_seconds=73,
                game_version="1.1.3",
                difficulty="hard",
                death_reason="Missed jump",
                distance_meters=1495,
                clean_escapes=6,
                revives_used=0,
                powerup_usage={"jetpack": 1, "mult2x": 2},
            )

        profile = self.service.fetch_profile("runner01", history_limit=10)

        self.assertEqual(profile["summary"]["published_runs_total"], 2)
        self.assertEqual(profile["summary"]["active_days"], 2)
        self.assertEqual(profile["summary"]["best_improvement_score"], 450)
        self.assertEqual(profile["latest_run"]["difficulty"], "hard")
        self.assertEqual(profile["latest_run"]["game_version"], "1.1.3")
        self.assertEqual(profile["latest_run"]["distance_meters"], 1495)
        self.assertEqual(profile["latest_run"]["clean_escapes"], 6)
        self.assertEqual(profile["latest_run"]["powerup_usage"]["jetpack"], 1)

    def test_submit_score_flags_impossible_distance_as_suspicious(self):
        result = self.service.login_or_create_account("runner01", "secret123", "a" * 64)

        suspicious = self.service.submit_score(
            result["principal"],
            score=9000,
            coins=40,
            play_time_seconds=10,
            game_version="1.1.3",
            difficulty="easy",
            distance_meters=950,
            clean_escapes=2,
            powerup_usage={"magnet": 1},
        )
        leaderboard = self.service.fetch_leaderboard()

        self.assertEqual(suspicious["verification_status"], "suspicious")
        self.assertTrue(suspicious["verification_reasons"])
        self.assertEqual(leaderboard["entries"][0]["verification_status"], "suspicious")


class SecureChannelTests(unittest.TestCase):
    def test_secure_channels_encrypt_and_decrypt_in_sequence(self):
        client_private = generate_private_key()
        server_private = generate_private_key()
        client_nonce = b"1" * 16
        server_nonce = b"2" * 16
        session_id = "session-1"
        client_key = derive_session_key(
            client_private,
            server_private.public_key(),
            client_nonce,
            server_nonce,
            session_id,
        )
        server_key = derive_session_key(
            server_private,
            client_private.public_key(),
            client_nonce,
            server_nonce,
            session_id,
        )
        client_channel = SecureChannel(client_key, session_id, CLIENT_SEND_NONCE_PREFIX, SERVER_SEND_NONCE_PREFIX)
        server_channel = SecureChannel(server_key, session_id, SERVER_SEND_NONCE_PREFIX, CLIENT_SEND_NONCE_PREFIX)

        packet = client_channel.seal({"type": "ping", "payload": {"value": 1}})
        response = server_channel.open(packet)

        self.assertEqual(response["type"], "ping")
        self.assertEqual(response["payload"]["value"], 1)


if __name__ == "__main__":
    unittest.main()
