from __future__ import annotations

from datetime import UTC, datetime, timedelta
import uuid

from server.issues.database import IssueDatabase
from server.service import ServiceError, SessionPrincipal

ISSUE_STATUS_ALL = "all"
ISSUE_STATUS_INVESTIGATING = "investigating"
ISSUE_STATUS_RESOLVED = "resolved"
ISSUE_STATUS_FILTERS = (ISSUE_STATUS_ALL, ISSUE_STATUS_INVESTIGATING, ISSUE_STATUS_RESOLVED)
ISSUE_PERSISTED_STATUSES = (ISSUE_STATUS_INVESTIGATING, ISSUE_STATUS_RESOLVED)
ISSUE_PAGE_SIZE = 50
ISSUE_MAX_TITLE_LENGTH = 250
ISSUE_MAX_MESSAGE_LENGTH = 1500
ISSUE_DAILY_SUBMISSION_LIMIT = 3

class IssueService:
    def __init__(self, database: IssueDatabase):
        self.database = database

    @staticmethod
    def utcnow() -> datetime:
        return datetime.now(UTC)

    def submit_issue_report(self, principal: SessionPrincipal, title: str, message: str) -> dict:
        normalized_title = self._normalize_title(title)
        normalized_message = self._normalize_message(message)
        now = self.utcnow()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        reports_today = self.database.fetchone(
            """
            SELECT COUNT(*) AS report_count
            FROM issue_reports
            WHERE reporter_account_id = ? AND created_at_epoch >= ? AND created_at_epoch < ?
            """,
            (
                int(principal.account_id),
                int(day_start.timestamp()),
                int(day_end.timestamp()),
            ),
        )
        report_count = int(reports_today["report_count"]) if reports_today is not None else 0
        if report_count >= ISSUE_DAILY_SUBMISSION_LIMIT:
            raise ServiceError(
                "issue_daily_limit_reached",
                f"You can submit at most {ISSUE_DAILY_SUBMISSION_LIMIT} bug reports per day.",
            )
        report_id = uuid.uuid4().hex
        now_text = now.isoformat()
        now_epoch = int(now.timestamp())
        self.database.execute(
            """
            INSERT INTO issue_reports (
                id,
                reporter_account_id,
                reporter_username,
                title,
                message,
                status,
                created_at,
                created_at_epoch,
                updated_at,
                updated_at_epoch,
                resolved_at,
                resolved_at_epoch
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
            """,
            (
                report_id,
                int(principal.account_id),
                principal.username,
                normalized_title,
                normalized_message,
                ISSUE_STATUS_INVESTIGATING,
                now_text,
                now_epoch,
                now_text,
                now_epoch,
            ),
        )
        return {
            "report_id": report_id,
            "title": normalized_title,
            "message": normalized_message,
            "status": ISSUE_STATUS_INVESTIGATING,
            "created_at": now_text,
            "updated_at": now_text,
            "submissions_remaining_today": max(0, ISSUE_DAILY_SUBMISSION_LIMIT - (report_count + 1)),
        }

    def fetch_issue_reports(self, *, status: str = ISSUE_STATUS_ALL, offset: int = 0, limit: int = ISSUE_PAGE_SIZE) -> dict:
        normalized_status = self._normalize_status_filter(status)
        normalized_offset = max(0, int(offset))
        normalized_limit = max(1, min(ISSUE_PAGE_SIZE, int(limit)))
        where_clause = ""
        parameters: list[object] = []
        if normalized_status != ISSUE_STATUS_ALL:
            where_clause = "WHERE status = ?"
            parameters.append(normalized_status)
        rows = self.database.fetchall(
            f"""
            SELECT id, reporter_username, title, status, created_at
            FROM issue_reports
            {where_clause}
            ORDER BY created_at_epoch DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (*parameters, normalized_limit, normalized_offset),
        )
        total_row = self.database.fetchone(
            f"""
            SELECT COUNT(*) AS total_reports
            FROM issue_reports
            {where_clause}
            """,
            tuple(parameters),
        )
        total_reports = int(total_row["total_reports"]) if total_row is not None else 0
        return {
            "entries": [self._serialize_summary_row(row) for row in rows],
            "status": normalized_status,
            "offset": normalized_offset,
            "limit": normalized_limit,
            "total_reports": total_reports,
        }

    def fetch_issue_report_detail(self, report_id: str) -> dict:
        normalized_report_id = str(report_id or "").strip().lower()
        if len(normalized_report_id) != 32:
            raise ServiceError("invalid_issue_report", "Issue report identifier is invalid.")
        row = self.database.fetchone(
            """
            SELECT
                id,
                reporter_username,
                title,
                message,
                status,
                created_at,
                updated_at,
                resolved_at
            FROM issue_reports
            WHERE id = ?
            """,
            (normalized_report_id,),
        )
        if row is None:
            raise ServiceError("issue_not_found", "Issue report could not be found.")
        return {
            "report_id": str(row["id"]),
            "reporter_username": str(row["reporter_username"]),
            "title": str(row["title"]),
            "message": str(row["message"]),
            "status": str(row["status"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "resolved_at": str(row["resolved_at"]) if row["resolved_at"] is not None else None,
        }

    def _normalize_title(self, title: str) -> str:
        normalized = " ".join(str(title or "").strip().split())
        if not normalized:
            raise ServiceError("invalid_issue_title", "Issue title is required.")
        if len(normalized) > ISSUE_MAX_TITLE_LENGTH:
            raise ServiceError(
                "invalid_issue_title",
                f"Issue title must be at most {ISSUE_MAX_TITLE_LENGTH} characters.",
            )
        return normalized

    def _normalize_message(self, message: str) -> str:
        normalized = str(message or "").replace("\r\n", "\n").replace("\r", "\n")
        if not normalized.strip():
            raise ServiceError("invalid_issue_message", "Issue message is required.")
        if len(normalized) > ISSUE_MAX_MESSAGE_LENGTH:
            raise ServiceError(
                "invalid_issue_message",
                f"Issue message must be at most {ISSUE_MAX_MESSAGE_LENGTH} characters.",
            )
        return normalized

    def _normalize_status_filter(self, status: str) -> str:
        normalized = str(status or ISSUE_STATUS_ALL).strip().lower()
        if normalized not in ISSUE_STATUS_FILTERS:
            raise ServiceError("invalid_issue_status", "Unsupported issue status filter.")
        return normalized

    @staticmethod
    def _serialize_summary_row(row) -> dict:
        return {
            "report_id": str(row["id"]),
            "reporter_username": str(row["reporter_username"]),
            "title": str(row["title"]),
            "status": str(row["status"]),
            "created_at": str(row["created_at"]),
        }
