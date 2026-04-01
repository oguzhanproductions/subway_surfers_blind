import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

from server.issues.bot.config import TelegramIssueBotConfig, TelegramIssueBotConfigStore
from server.issues.bot.telegram_admin_bot import TelegramIssueAdminBot
from server.issues.database import IssueDatabase
from server.issues.service import IssueService
from server.service import SessionPrincipal


class TelegramIssueBotConfigStoreTests(unittest.TestCase):
    def test_load_creates_default_config_when_missing(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            config_path = Path(temp_directory) / "telegram_bot.json"
            store = TelegramIssueBotConfigStore(config_path)

            config = store.load()

            self.assertFalse(config.enabled)
            self.assertEqual(config.allowed_user_ids, ())
            self.assertTrue(config_path.exists())

    def test_load_normalizes_ids_and_timeout(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            config_path = Path(temp_directory) / "telegram_bot.json"
            config_path.write_text(
                """
                {
                  "enabled": true,
                  "bot_token": " token ",
                  "allowed_user_ids": ["12", 4, "bad", 12],
                  "subscribers": [
                    {"user_id": "12", "chat_id": "1200"},
                    {"user_id": 4, "chat_id": "-10012345"},
                    {"user_id": "bad", "chat_id": "77"},
                    {"user_id": 12, "chat_id": "1300"}
                  ],
                  "polling_timeout_seconds": 120
                }
                """.strip(),
                encoding="utf-8",
            )
            store = TelegramIssueBotConfigStore(config_path)

            config = store.load()

            self.assertTrue(config.enabled)
            self.assertEqual(config.bot_token, "token")
            self.assertEqual(config.allowed_user_ids, (4, 12))
            self.assertEqual(len(config.subscribers), 2)
            self.assertEqual(config.subscribers[0].user_id, 4)
            self.assertEqual(config.subscribers[0].chat_id, -10012345)
            self.assertEqual(config.subscribers[1].user_id, 12)
            self.assertEqual(config.subscribers[1].chat_id, 1300)
            self.assertEqual(config.polling_timeout_seconds, 60)


class TelegramIssueAdminBotTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database = IssueDatabase(Path(self.temp_directory.name) / "issues.sqlite3")
        self.issue_service = IssueService(self.database)
        self.principal = SessionPrincipal(account_id=7, username="runner01", auth_epoch=0, device_hash="d" * 64)
        self.config_store = TelegramIssueBotConfigStore(Path(self.temp_directory.name) / "telegram_bot.json")
        self.config_store.save(
            TelegramIssueBotConfig(
                enabled=True,
                bot_token="token",
                allowed_user_ids=(1001, 1002),
            )
        )
        self.bot = TelegramIssueAdminBot(self.issue_service, self.config_store, logger=lambda message: None)

    def tearDown(self):
        self.database.close()
        self.temp_directory.cleanup()

    def _create_issue(self, *, title: str, message: str, when: datetime) -> dict[str, object]:
        with patch.object(self.issue_service, "utcnow", return_value=when):
            return self.issue_service.submit_issue_report(self.principal, title=title, message=message)

    def test_list_view_matches_issue_summary_shape(self):
        self._create_issue(
            title="Menu focus jumps unexpectedly",
            message="Open the shop.\nMove down twice.\nFocus returns to the top item.",
            when=datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
        )

        view = self.bot.build_issue_list_view()

        self.assertIn("Bug Reports", view.text)
        self.assertIn("runner01: Menu focus jumps unexpectedly: Investigating: 2026-04-01 10:00:00", view.text)
        self.assertEqual(view.buttons[0][0].callback_data, "list:a:0")
        self.assertTrue(view.buttons[1][0].callback_data.startswith("detail:"))

    def test_detail_view_shows_player_and_resolve_action(self):
        created = self._create_issue(
            title="Esc closes the dialog",
            message="Press Esc in the editor.\nThe menu needs Enter twice.",
            when=datetime(2026, 4, 1, 11, 30, tzinfo=UTC),
        )

        view = self.bot.build_issue_detail_view(created["report_id"])

        self.assertIn("Player: runner01", view.text)
        self.assertIn("Title: Esc closes the dialog", view.text)
        self.assertEqual(view.buttons[0][0].text, "Mark Resolved")

    def test_resolve_callback_marks_issue_resolved(self):
        created = self._create_issue(
            title="Ticket stays selected",
            message="Open the issue list.\nSelection does not update.",
            when=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
        )
        callback_data = f"resolve:{created['report_id']}:i:0"

        with patch.object(self.issue_service, "utcnow", return_value=datetime(2026, 4, 1, 12, 10, tzinfo=UTC)):
            state, payload = self.bot.handle_callback(callback_data, 1001)

        self.assertEqual(state, "view")
        self.assertIn("Status: Resolved", payload.text)
        self.assertNotIn("Mark Resolved", [button.text for row in payload.buttons for button in row])

    def test_start_message_registers_subscriber_once(self):
        first_view = self.bot.handle_start_message(7001, 1001)
        second_view = self.bot.handle_start_message(7001, 1001)
        reloaded_config = self.config_store.load()

        self.assertIsNotNone(first_view)
        self.assertIsNotNone(second_view)
        self.assertEqual(len(reloaded_config.subscribers), 1)
        self.assertEqual(reloaded_config.subscribers[0].user_id, 1001)
        self.assertEqual(reloaded_config.subscribers[0].chat_id, 7001)

    def test_new_issue_notification_goes_to_started_admins(self):
        self.bot.handle_start_message(7001, 1001)
        self.bot.handle_start_message(7002, 1002)
        fake_telegram_bot = Mock()
        self.bot._bot = fake_telegram_bot
        self.bot._started = True
        self.bot._config = self.config_store.load()

        self._create_issue(
            title="Player gets stuck in menu",
            message="Open settings.\nFocus stops responding.",
            when=datetime(2026, 4, 1, 12, 30, tzinfo=UTC),
        )

        self.assertEqual(fake_telegram_bot.send_message.call_count, 2)
        destination_chat_ids = [call.args[0] for call in fake_telegram_bot.send_message.call_args_list]
        self.assertEqual(destination_chat_ids, [7001, 7002])

    def test_unauthorized_users_are_rejected(self):
        state, payload = self.bot.handle_callback("list:i:0", 9999)

        self.assertEqual(state, "denied")
        self.assertIn("restricted", payload)

    def test_invalid_callback_is_rejected_without_crashing(self):
        state, payload = self.bot.handle_callback("bad-callback", 1001)

        self.assertEqual(state, "error")
        self.assertIn("no longer valid", payload)


if __name__ == "__main__":
    unittest.main()
