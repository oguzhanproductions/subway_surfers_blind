import tempfile
import unittest
from pathlib import Path

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
