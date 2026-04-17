import unittest
from types import SimpleNamespace
import json
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

import enet

from subway_blind.leaderboard_client import LeaderboardClient
from subway_blind.leaderboard_protocol import ServerConnectionConfig
import subway_blind.server_config as server_config_module


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class _FakeHost:
    def __init__(self, events):
        self._events = list(events)
        self.calls = 0

    def service(self, _timeout):
        self.calls += 1
        if self._events:
            return self._events.pop(0)
        return SimpleNamespace(type=enet.EVENT_TYPE_NONE)


class _FakePeer:
    def __init__(self):
        self.sent_packets = []

    def send(self, channel_id, packet):
        self.sent_packets.append((channel_id, packet))


class LeaderboardClientTests(unittest.TestCase):
    def setUp(self):
        self.client = LeaderboardClient(
            ServerConnectionConfig(
                host="127.0.0.1",
                port=27888,
                server_public_key="test-key",
                connect_timeout_ms=250,
                request_timeout_ms=250,
                page_size=10,
            )
        )

    def test_drain_nonblocking_events_stops_on_empty_enet_event(self):
        self.client.host = _FakeHost([SimpleNamespace(type=enet.EVENT_TYPE_NONE)])

        self.client._drain_nonblocking_events()

        self.assertEqual(self.client.host.calls, 1)

    def test_close_keeps_session_identity_for_resume(self):
        self.client.principal_username = "runner01"
        self.client.auth_token = "session-token"

        self.client.close()

        self.assertEqual(self.client.principal_username, "runner01")
        self.assertTrue(self.client.is_authenticated())

    def test_connection_idle_expired_after_threshold(self):
        self.client.connected = True

        with mock.patch("subway_blind.leaderboard_client.time.monotonic", return_value=1000.0):
            self.client._last_activity_at = 1000.0
            self.assertFalse(self.client._connection_idle_expired())

        with mock.patch("subway_blind.leaderboard_client.time.monotonic", return_value=1481.0):
            self.assertTrue(self.client._connection_idle_expired())

    def test_request_closes_connection_after_response(self):
        peer = _FakePeer()
        secure_channel = mock.Mock()
        secure_channel.seal.return_value = b"encrypted"
        secure_channel.open.return_value = {"ok": True, "payload": {"status": "ok"}}
        self.client.peer = peer
        self.client.host = object()
        self.client.secure_channel = secure_channel
        self.client.connected = True

        with mock.patch.object(self.client, "connect"), mock.patch.object(
            self.client, "_wait_for_event", return_value=SimpleNamespace(packet=SimpleNamespace(data=b"packet"))
        ), mock.patch.object(self.client, "close") as close_mock:
            result = self.client._request("ping", {})

        self.assertEqual(result["status"], "ok")
        close_mock.assert_called_once()
        self.assertEqual(len(peer.sent_packets), 1)

    def test_fetch_leaderboard_passes_period_and_difficulty_filters(self):
        with mock.patch.object(self.client, "_request", return_value={"entries": []}) as request_mock:
            self.client.fetch_leaderboard(limit=25, period="season", difficulty="hard")

        request_mock.assert_called_once_with(
            "fetch_leaderboard",
            {
                "offset": 0,
                "limit": 25,
                "period": "season",
                "difficulty": "hard",
            },
        )

    def test_sync_account_sends_claimed_reward_ids(self):
        with mock.patch.object(self.client, "_request", return_value={"pending_rewards": []}) as request_mock:
            self.client.sync_account(["reward-1", "reward-2"])

        request_mock.assert_called_once_with(
            "sync_account",
            {
                "claimed_reward_ids": ["reward-1", "reward-2"],
            },
        )

    def test_sync_account_sends_consumed_special_item_keys_when_provided(self):
        with mock.patch.object(self.client, "_request", return_value={"pending_rewards": []}) as request_mock:
            self.client.sync_account(["reward-1"], ["phantom_step", "vault_seal"])

        request_mock.assert_called_once_with(
            "sync_account",
            {
                "claimed_reward_ids": ["reward-1"],
                "consumed_special_item_keys": ["phantom_step", "vault_seal"],
            },
        )

    def test_fetch_issue_reports_sends_pagination_and_status(self):
        with mock.patch.object(self.client, "_request", return_value={"entries": []}) as request_mock:
            self.client.fetch_issue_reports(offset=50, limit=50, status="resolved")

        request_mock.assert_called_once_with(
            "fetch_issue_reports",
            {
                "offset": 50,
                "limit": 50,
                "status": "resolved",
            },
        )

    def test_fetch_issue_report_detail_sends_report_id(self):
        with mock.patch.object(self.client, "_request", return_value={"report_id": "issue-1"}) as request_mock:
            self.client.fetch_issue_report_detail("issue-1")

        request_mock.assert_called_once_with(
            "fetch_issue_report_detail",
            {
                "report_id": "issue-1",
            },
        )

    def test_submit_issue_report_sends_title_and_message(self):
        with mock.patch.object(self.client, "_request", return_value={"report_id": "issue-1"}) as request_mock:
            self.client.submit_issue_report(title="Crash on launch", message="The game crashes\nwhen I press Enter.")

        request_mock.assert_called_once_with(
            "submit_issue_report",
            {
                "title": "Crash on launch",
                "message": "The game crashes\nwhen I press Enter.",
            },
        )

    def test_submit_score_includes_extended_run_metadata(self):
        with mock.patch.object(self.client, "_request", return_value={"high_score": True}) as request_mock:
            self.client.submit_score(
                score=4200,
                coins=17,
                play_time_seconds=65,
                difficulty="hard",
                death_reason="Hit train",
                distance_meters=1490,
                clean_escapes=6,
                revives_used=1,
                powerup_usage={"magnet": 1, "jetpack": 2},
            )

        request_mock.assert_called_once_with(
            "submit_score",
            {
                "score": 4200,
                "coins": 17,
                "play_time_seconds": 65,
                "game_version": mock.ANY,
                "difficulty": "hard",
                "death_reason": "Hit train",
                "distance_meters": 1490,
                "clean_escapes": 6,
                "revives_used": 1,
                "powerup_usage": {"magnet": 1, "jetpack": 2},
            },
        )


class ServerConfigTests(unittest.TestCase):
    def test_default_server_config_path_prefers_executable_directory_when_frozen(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            external_path = temp_root / "server.json"

            with mock.patch.object(server_config_module, "RESOURCE_BASE_DIR", temp_root), mock.patch.object(
                server_config_module.sys,
                "frozen",
                True,
                create=True,
            ):
                config_path = server_config_module.default_server_config_path()

            self.assertEqual(config_path, external_path)

    def test_load_server_config_uses_inline_server_connection_values(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            config_path = temp_root / "user-data" / "server.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps(
                    {
                        "host": "tt5server.com.tr",
                        "port": 5363,
                        "server_public_key": "inline-public-key",
                        "server_public_key_path": "",
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(server_config_module, "default_server_config_path", return_value=config_path):
                config = server_config_module.load_server_config()

            self.assertEqual(config.host, "tt5server.com.tr")
            self.assertEqual(config.port, 5363)
            self.assertEqual(config.server_public_key, "inline-public-key")

    def test_load_server_config_resolves_relative_key_from_resource_dirs(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            temp_root = Path(temp_directory)
            config_path = temp_root / "user-data" / "server.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps(server_config_module.DEFAULT_SERVER_CONFIG), encoding="utf-8")

            resource_root = temp_root / "project-root"
            public_key_path = resource_root / "server" / "runtime" / "server_public_key.b64"
            public_key_path.parent.mkdir(parents=True, exist_ok=True)
            public_key_path.write_text("test-public-key", encoding="utf-8")

            with mock.patch.object(server_config_module, "RESOURCE_BASE_DIR", resource_root), mock.patch.object(
                server_config_module, "BUNDLED_RESOURCE_BASE_DIR", temp_root / "bundle-root"
            ), mock.patch.object(server_config_module, "BASE_DIR", temp_root / "appdata-root"), mock.patch.object(
                server_config_module, "default_server_config_path", return_value=config_path
            ):
                config = server_config_module.load_server_config()

            self.assertEqual(config.server_public_key, "test-public-key")


class LeaderboardIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.runtime_directory = Path(self.temp_directory.name) / "runtime"
        self.runtime_directory.mkdir(parents=True, exist_ok=True)
        self.port = self._allocate_udp_port()
        self.server_process: subprocess.Popen[str] | None = None

    def tearDown(self):
        if self.server_process is not None:
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
                self.server_process.wait(timeout=5)
        self.temp_directory.cleanup()

    def test_live_server_supports_create_login_submit_and_session_resume(self):
        self.server_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "server",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--runtime-dir",
                str(self.runtime_directory),
            ],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        public_key = self._wait_for_public_key()
        connection_config = ServerConnectionConfig(
            host="127.0.0.1",
            port=self.port,
            server_public_key=public_key,
            connect_timeout_ms=1000,
            request_timeout_ms=2000,
            page_size=20,
        )

        client = LeaderboardClient(connection_config)
        auth_result = client.login("runner01", "secret123")
        self.assertEqual(auth_result["status"], "created")

        submit_result = client.submit_score(
            score=4200,
            coins=17,
            play_time_seconds=65,
            difficulty="hard",
            death_reason="Hit train",
            distance_meters=1490,
            clean_escapes=6,
            revives_used=1,
            powerup_usage={"magnet": 1, "jetpack": 1, "hoverboard": 1},
        )
        self.assertTrue(submit_result["high_score"])

        leaderboard = client.fetch_leaderboard(limit=10, period="season", difficulty="hard")
        self.assertEqual(leaderboard["total_players"], 1)
        self.assertEqual(leaderboard["entries"][0]["username"], "runner01")
        self.assertEqual(leaderboard["entries"][0]["score"], 4200)
        self.assertEqual(leaderboard["entries"][0]["difficulty"], "hard")

        session_token = client.auth_token
        client.close()

        resumed_client = LeaderboardClient(connection_config)
        resumed_client.auth_token = session_token
        resumed_client.principal_username = "runner01"
        resumed_client.connect()
        self.assertEqual(resumed_client.principal_username, "runner01")

        profile = resumed_client.fetch_profile("runner01", history_limit=10)
        self.assertEqual(profile["username"], "runner01")
        self.assertEqual(profile["best_run"]["score"], 4200)
        self.assertEqual(profile["best_run"]["difficulty"], "hard")
        self.assertEqual(profile["best_run"]["game_version"], mock.ANY)
        self.assertEqual(profile["best_run"]["clean_escapes"], 6)
        self.assertEqual(profile["summary"]["published_runs_total"], 1)
        resumed_client.close()

    def test_live_server_supports_issue_submission_listing_and_detail(self):
        self.server_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "server",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--runtime-dir",
                str(self.runtime_directory),
            ],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        public_key = self._wait_for_public_key()
        connection_config = ServerConnectionConfig(
            host="127.0.0.1",
            port=self.port,
            server_public_key=public_key,
            connect_timeout_ms=1000,
            request_timeout_ms=2000,
            page_size=20,
        )

        client = LeaderboardClient(connection_config)
        client.login("runner01", "secret123")

        submit_result = client.submit_issue_report(
            title="Menu focus jumps unexpectedly",
            message="Open the shop.\nMove down twice.\nFocus returns to the top item.",
        )
        self.assertEqual(submit_result["status"], "investigating")

        reports = client.fetch_issue_reports(status="investigating", limit=50)
        self.assertEqual(reports["total_reports"], 1)
        self.assertEqual(reports["entries"][0]["title"], "Menu focus jumps unexpectedly")

        detail = client.fetch_issue_report_detail(reports["entries"][0]["report_id"])
        self.assertEqual(detail["status"], "investigating")
        self.assertIn("Focus returns to the top item.", detail["message"])
        client.close()

    def _wait_for_public_key(self) -> str:
        public_key_path = self.runtime_directory / "server_public_key.b64"
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if self.server_process is not None and self.server_process.poll() is not None:
                stdout, stderr = self.server_process.communicate(timeout=2)
                self.fail(f"Server exited unexpectedly.\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")
            if public_key_path.exists():
                key = public_key_path.read_text(encoding="utf-8").strip()
                if key:
                    time.sleep(0.2)
                    return key
            time.sleep(0.05)
        self.fail("Timed out waiting for the leaderboard server public key.")

    @staticmethod
    def _allocate_udp_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])


if __name__ == "__main__":
    unittest.main()
