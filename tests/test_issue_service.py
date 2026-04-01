import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from server.issues.database import IssueDatabase
from server.issues.service import IssueService
from server.service import SessionPrincipal, ServiceError


class IssueServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database = IssueDatabase(Path(self.temp_directory.name) / "issues.sqlite3")
        self.service = IssueService(self.database)
        self.principal = SessionPrincipal(account_id=1, username="runner01", auth_epoch=0, device_hash="a" * 64)

    def tearDown(self):
        self.database.close()
        self.temp_directory.cleanup()

    def test_submit_issue_report_persists_multiline_message(self):
        with patch.object(self.service, "utcnow", return_value=datetime(2026, 4, 1, 10, 30, tzinfo=UTC)):
            created = self.service.submit_issue_report(
                self.principal,
                title="Crash on startup",
                message="Open the game.\nPress Enter.\nThe game closes.",
            )

        detail = self.service.fetch_issue_report_detail(created["report_id"])

        self.assertEqual(detail["title"], "Crash on startup")
        self.assertEqual(detail["status"], "investigating")
        self.assertEqual(detail["message"], "Open the game.\nPress Enter.\nThe game closes.")

    def test_submit_issue_report_limits_each_account_to_three_reports_per_day(self):
        fixed_now = datetime(2026, 4, 1, 11, 0, tzinfo=UTC)
        with patch.object(self.service, "utcnow", return_value=fixed_now):
            for index in range(3):
                self.service.submit_issue_report(
                    self.principal,
                    title=f"Issue {index}",
                    message=f"Message {index}",
                )
            with self.assertRaises(ServiceError) as context:
                self.service.submit_issue_report(
                    self.principal,
                    title="Issue 4",
                    message="Too many reports today.",
                )

        self.assertEqual(context.exception.code, "issue_daily_limit_reached")

    def test_submit_issue_report_allows_new_submissions_on_next_day(self):
        first_day = datetime(2026, 4, 1, 23, 50, tzinfo=UTC)
        next_day = first_day + timedelta(minutes=20)
        with patch.object(self.service, "utcnow", return_value=first_day):
            for index in range(3):
                self.service.submit_issue_report(
                    self.principal,
                    title=f"Day one {index}",
                    message="Report",
                )
        with patch.object(self.service, "utcnow", return_value=next_day):
            created = self.service.submit_issue_report(
                self.principal,
                title="Day two",
                message="Allowed again.",
            )

        self.assertEqual(created["submissions_remaining_today"], 2)

    def test_fetch_issue_reports_filters_by_status_and_orders_newest_first(self):
        with patch.object(self.service, "utcnow", return_value=datetime(2026, 4, 1, 10, 0, tzinfo=UTC)):
            first = self.service.submit_issue_report(self.principal, title="Older", message="Older issue")
        self.database.execute(
            """
            UPDATE issue_reports
            SET status = ?, updated_at = ?, updated_at_epoch = ?, resolved_at = ?, resolved_at_epoch = ?
            WHERE id = ?
            """,
            ("resolved", "2026-04-01T11:00:00+00:00", 1743505200, "2026-04-01T11:00:00+00:00", 1743505200, first["report_id"]),
        )
        with patch.object(self.service, "utcnow", return_value=datetime(2026, 4, 1, 12, 0, tzinfo=UTC)):
            self.service.submit_issue_report(self.principal, title="Newest", message="Newest issue")

        resolved = self.service.fetch_issue_reports(status="resolved")
        investigating = self.service.fetch_issue_reports(status="investigating")

        self.assertEqual(resolved["total_reports"], 1)
        self.assertEqual(resolved["entries"][0]["reporter_username"], "runner01")
        self.assertEqual(resolved["entries"][0]["title"], "Older")
        self.assertEqual(investigating["entries"][0]["reporter_username"], "runner01")
        self.assertEqual(investigating["entries"][0]["title"], "Newest")

    def test_fetch_issue_report_detail_rejects_invalid_identifier(self):
        with self.assertRaises(ServiceError) as context:
            self.service.fetch_issue_report_detail("bad-id")

        self.assertEqual(context.exception.code, "invalid_issue_report")

    def test_resolve_issue_report_marks_report_resolved(self):
        with patch.object(self.service, "utcnow", return_value=datetime(2026, 4, 1, 9, 0, tzinfo=UTC)):
            created = self.service.submit_issue_report(
                self.principal,
                title="Dialog refuses to close",
                message="Press Escape.\nThe dialog stays open.",
            )
        with patch.object(self.service, "utcnow", return_value=datetime(2026, 4, 1, 9, 5, tzinfo=UTC)):
            resolved = self.service.resolve_issue_report(created["report_id"])

        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["resolved_at"], "2026-04-01T09:05:00+00:00")

    def test_submit_issue_report_notifies_submission_listeners(self):
        received_reports: list[dict] = []
        self.service.add_submission_listener(received_reports.append)

        with patch.object(self.service, "utcnow", return_value=datetime(2026, 4, 1, 10, 0, tzinfo=UTC)):
            created = self.service.submit_issue_report(
                self.principal,
                title="Menu label is wrong",
                message="Open options.\nLabel is missing.",
            )

        self.assertEqual(len(received_reports), 1)
        self.assertEqual(received_reports[0]["report_id"], created["report_id"])
        self.assertEqual(received_reports[0]["reporter_username"], "runner01")


if __name__ == "__main__":
    unittest.main()
