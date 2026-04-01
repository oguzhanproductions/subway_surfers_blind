from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Any, Callable

from server.issues.bot.config import TelegramIssueBotConfig, TelegramIssueBotConfigStore, TelegramIssueBotSubscriber
from server.issues.service import ISSUE_STATUS_ALL, ISSUE_STATUS_INVESTIGATING, ISSUE_STATUS_RESOLVED, IssueService

STATUS_ORDER = (ISSUE_STATUS_ALL, ISSUE_STATUS_INVESTIGATING, ISSUE_STATUS_RESOLVED)
STATUS_SHORT_CODES = {
    ISSUE_STATUS_ALL: "a",
    ISSUE_STATUS_INVESTIGATING: "i",
    ISSUE_STATUS_RESOLVED: "r",
}
STATUS_SHORT_CODES_REVERSE = {value: key for key, value in STATUS_SHORT_CODES.items()}
STATUS_LABELS = {
    ISSUE_STATUS_ALL: "All Statuses",
    ISSUE_STATUS_INVESTIGATING: "Investigating",
    ISSUE_STATUS_RESOLVED: "Resolved",
}
BOT_PAGE_SIZE = 8


@dataclass(slots=True, frozen=True)
class TelegramInlineButtonSpec:
    text: str
    callback_data: str


@dataclass(slots=True, frozen=True)
class TelegramRenderedView:
    text: str
    buttons: tuple[tuple[TelegramInlineButtonSpec, ...], ...]


class TelegramIssueAdminBot:
    def __init__(
        self,
        issue_service: IssueService,
        config_store: TelegramIssueBotConfigStore,
        *,
        logger: Callable[[str], None] | None = None,
        telebot_loader: Callable[[], tuple[Any, Any]] | None = None,
    ):
        self.issue_service = issue_service
        self.config_store = config_store
        self.logger = logger or print
        self._telebot_loader = telebot_loader or self._load_telebot
        self._config = self.config_store.load()
        self._bot: Any | None = None
        self._types: Any | None = None
        self._polling_thread: threading.Thread | None = None
        self._started = False
        self.issue_service.add_submission_listener(self.notify_new_issue)

    @property
    def config_path(self) -> Path:
        return self.config_store.config_path

    def start(self) -> bool:
        self._config = self.config_store.load()
        self.logger(f"Telegram issue bot config: {self.config_path}")
        if not self._config.enabled:
            self.logger("Telegram issue bot is disabled.")
            return False
        if not self._config.bot_token:
            self.logger("Telegram issue bot is enabled but bot_token is empty.")
            return False
        if not self._config.allowed_user_ids:
            self.logger("Telegram issue bot is enabled but allowed_user_ids is empty.")
            return False
        try:
            telebot, types = self._telebot_loader()
            self._bot = telebot.TeleBot(self._config.bot_token, parse_mode=None)
            self._types = types
            self._register_handlers()
            self._polling_thread = threading.Thread(target=self._poll_forever, name="telegram-issue-bot", daemon=True)
            self._polling_thread.start()
            self._started = True
            self.logger("Telegram issue bot started.")
            return True
        except Exception as exc:
            self._bot = None
            self._types = None
            self.logger(f"Telegram issue bot failed to start: {exc}")
            return False

    def stop(self) -> None:
        bot = self._bot
        self._started = False
        self._bot = None
        self._types = None
        if bot is not None:
            try:
                bot.stop_polling()
            except Exception:
                pass
        if self._polling_thread is not None:
            self._polling_thread.join(timeout=2.0)
            self._polling_thread = None

    def notify_new_issue(self, report: dict[str, object]) -> None:
        if not self._started or self._bot is None or not self._config.subscribers:
            return
        try:
            detail = self.issue_service.fetch_issue_report_detail(str(report.get("report_id") or ""))
            view = self._render_issue_detail_view(
                detail,
                source_status=ISSUE_STATUS_INVESTIGATING,
                source_offset=0,
            )
            for subscriber in self._config.subscribers:
                self._bot.send_message(
                    subscriber.chat_id,
                    self._render_issue_detail_text(detail, header="New Bug Report"),
                    reply_markup=self._create_markup(view.buttons),
                )
        except Exception as exc:
            self.logger(f"Telegram issue notification failed: {exc}")

    def build_issue_list_view(self, status: str = ISSUE_STATUS_INVESTIGATING, offset: int = 0) -> TelegramRenderedView:
        normalized_status = self._normalize_status(status)
        normalized_offset = max(0, int(offset))
        reports = self.issue_service.fetch_issue_reports(status=normalized_status, offset=normalized_offset, limit=BOT_PAGE_SIZE)
        total_reports = int(reports.get("total_reports", 0) or 0)
        if normalized_offset > 0 and total_reports > 0 and not reports.get("entries"):
            normalized_offset = ((total_reports - 1) // BOT_PAGE_SIZE) * BOT_PAGE_SIZE
            reports = self.issue_service.fetch_issue_reports(status=normalized_status, offset=normalized_offset, limit=BOT_PAGE_SIZE)
            total_reports = int(reports.get("total_reports", 0) or 0)
        total_pages = max(1, (total_reports + BOT_PAGE_SIZE - 1) // BOT_PAGE_SIZE)
        current_page = (normalized_offset // BOT_PAGE_SIZE) + 1
        start_index = normalized_offset + 1 if total_reports else 0
        end_index = min(normalized_offset + len(list(reports.get("entries") or [])), total_reports)
        lines = [
            "Bug Reports",
            f"Status: {STATUS_LABELS[normalized_status]}",
            f"Page: {current_page}/{total_pages}",
            f"Showing: {start_index}-{end_index} of {total_reports}" if total_reports else "Showing: 0 of 0",
            "",
        ]
        entries = list(reports.get("entries") or [])
        if entries:
            for index, entry in enumerate(entries, start=normalized_offset + 1):
                lines.append(f"{index}. {self._format_summary_label(entry)}")
        else:
            lines.append("No bug reports were found for the current filter.")
        buttons: list[tuple[TelegramInlineButtonSpec, ...]] = [
            tuple(
                TelegramInlineButtonSpec(
                    self._filter_button_text(filter_status, normalized_status),
                    self._encode_list_callback(filter_status, 0),
                )
                for filter_status in STATUS_ORDER
            )
        ]
        for entry in entries:
            buttons.append(
                (
                    TelegramInlineButtonSpec(
                        self._truncate_button_label(self._format_detail_button_label(entry)),
                        self._encode_detail_callback(str(entry.get("report_id") or ""), normalized_status, normalized_offset),
                    ),
                )
            )
        buttons.append(
            (
                TelegramInlineButtonSpec("Previous", self._encode_list_callback(normalized_status, max(0, normalized_offset - BOT_PAGE_SIZE))),
                TelegramInlineButtonSpec("Refresh", self._encode_list_callback(normalized_status, normalized_offset)),
                TelegramInlineButtonSpec(
                    "Next",
                    self._encode_list_callback(normalized_status, normalized_offset + BOT_PAGE_SIZE),
                ),
            )
        )
        return TelegramRenderedView(text="\n".join(lines).strip(), buttons=tuple(buttons))

    def build_issue_detail_view(
        self,
        report_id: str,
        *,
        source_status: str = ISSUE_STATUS_INVESTIGATING,
        source_offset: int = 0,
    ) -> TelegramRenderedView:
        detail = self.issue_service.fetch_issue_report_detail(report_id)
        return self._render_issue_detail_view(detail, source_status=source_status, source_offset=source_offset)

    def handle_start_message(self, chat_id: int, user_id: int) -> TelegramRenderedView | None:
        if not self._is_allowed_user(user_id):
            return None
        self._register_started_user(chat_id=chat_id, user_id=user_id)
        return self.build_issue_list_view()

    def handle_callback(self, callback_data: str, user_id: int) -> tuple[str, TelegramRenderedView | str]:
        if not self._is_allowed_user(user_id):
            return "denied", "This bot is restricted to the configured admin accounts."
        try:
            action, payload = self._parse_callback_data(callback_data)
        except ValueError:
            return "error", "This action is no longer valid."
        if action == "list":
            return "view", self.build_issue_list_view(status=payload["status"], offset=payload["offset"])
        if action == "detail":
            return "view", self.build_issue_detail_view(
                payload["report_id"],
                source_status=payload["status"],
                source_offset=payload["offset"],
            )
        if action == "resolve":
            self.issue_service.resolve_issue_report(payload["report_id"])
            return "view", self.build_issue_detail_view(
                payload["report_id"],
                source_status=payload["status"],
                source_offset=payload["offset"],
            )
        return "error", "Unsupported bot action."

    def _register_handlers(self) -> None:
        if self._bot is None:
            return

        @self._bot.message_handler(commands=["start", "issues", "help"])
        def handle_start(message):
            view = self.handle_start_message(int(message.chat.id), int(message.from_user.id))
            if view is None:
                self._bot.reply_to(message, "This bot is restricted to the configured admin accounts.")
                return
            self._bot.send_message(message.chat.id, view.text, reply_markup=self._create_markup(view.buttons))

        @self._bot.callback_query_handler(func=lambda call: True)
        def handle_callback(call):
            state, payload = self.handle_callback(str(call.data or ""), int(call.from_user.id))
            if state == "denied":
                self._bot.answer_callback_query(call.id, str(payload), show_alert=True)
                return
            if state == "error":
                self._bot.answer_callback_query(call.id, str(payload), show_alert=True)
                return
            view = payload
            self._bot.answer_callback_query(call.id)
            self._edit_message(
                chat_id=int(call.message.chat.id),
                message_id=int(call.message.message_id),
                view=view,
            )

    def _edit_message(self, *, chat_id: int, message_id: int, view: TelegramRenderedView) -> None:
        if self._bot is None:
            return
        try:
            self._bot.edit_message_text(
                view.text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=self._create_markup(view.buttons),
            )
        except Exception as exc:
            if "message is not modified" not in str(exc).lower():
                raise

    def _poll_forever(self) -> None:
        if self._bot is None:
            return
        self._bot.infinity_polling(
            timeout=self._config.polling_timeout_seconds,
            long_polling_timeout=self._config.polling_timeout_seconds,
            skip_pending=True,
            allowed_updates=["message", "callback_query"],
        )

    def _render_issue_detail_view(
        self,
        report: dict[str, object],
        *,
        source_status: str,
        source_offset: int,
    ) -> TelegramRenderedView:
        report_id = str(report.get("report_id") or "")
        buttons: list[tuple[TelegramInlineButtonSpec, ...]] = []
        if str(report.get("status") or "") != ISSUE_STATUS_RESOLVED:
            buttons.append(
                (
                    TelegramInlineButtonSpec(
                        "Mark Resolved",
                        self._encode_resolve_callback(report_id, source_status, source_offset),
                    ),
                )
            )
        buttons.append(
            (
                TelegramInlineButtonSpec("Back to List", self._encode_list_callback(source_status, source_offset)),
                TelegramInlineButtonSpec("Refresh", self._encode_detail_callback(report_id, source_status, source_offset)),
            )
        )
        return TelegramRenderedView(
            text=self._render_issue_detail_text(report),
            buttons=tuple(buttons),
        )

    def _render_issue_detail_text(self, report: dict[str, object], *, header: str = "Bug Report") -> str:
        message_lines = str(report.get("message") or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        created_at = self._format_timestamp(report.get("created_at"))
        updated_at = self._format_timestamp(report.get("updated_at"))
        resolved_at = self._format_timestamp(report.get("resolved_at"))
        lines = [
            header,
            f"Player: {str(report.get('reporter_username') or 'Unknown user')}",
            f"Status: {STATUS_LABELS.get(str(report.get('status') or ''), 'Unknown')}",
            f"Created: {created_at}",
            f"Updated: {updated_at}",
            f"Resolved: {resolved_at}",
            "",
            f"Title: {str(report.get('title') or 'Untitled issue')}",
            "",
            "Message:",
        ]
        lines.extend(line if line else " " for line in message_lines)
        return "\n".join(lines).strip()

    def _create_markup(self, rows: tuple[tuple[TelegramInlineButtonSpec, ...], ...]):
        if self._types is None:
            return None
        markup = self._types.InlineKeyboardMarkup()
        for row in rows:
            markup.row(*[self._types.InlineKeyboardButton(button.text, callback_data=button.callback_data) for button in row])
        return markup

    @staticmethod
    def _load_telebot():
        import telebot
        from telebot import types

        return telebot, types

    def _is_allowed_user(self, user_id: int) -> bool:
        return int(user_id) in set(self._config.allowed_user_ids)

    def _register_started_user(self, *, chat_id: int, user_id: int) -> None:
        normalized_user_id = int(user_id)
        normalized_chat_id = int(chat_id)
        existing = {subscriber.user_id: subscriber for subscriber in self._config.subscribers}
        current = existing.get(normalized_user_id)
        if current is not None and current.chat_id == normalized_chat_id:
            return
        existing[normalized_user_id] = TelegramIssueBotSubscriber(
            user_id=normalized_user_id,
            chat_id=normalized_chat_id,
        )
        updated_config = TelegramIssueBotConfig(
            enabled=self._config.enabled,
            bot_token=self._config.bot_token,
            allowed_user_ids=self._config.allowed_user_ids,
            subscribers=tuple(existing[user_id_key] for user_id_key in sorted(existing)),
            polling_timeout_seconds=self._config.polling_timeout_seconds,
        )
        self.config_store.save(updated_config)
        self._config = updated_config

    def _parse_callback_data(self, callback_data: str) -> tuple[str, dict[str, object]]:
        parts = str(callback_data or "").split(":")
        if len(parts) != 3 and len(parts) != 4:
            raise ValueError("Invalid callback data.")
        action = parts[0]
        if action == "list" and len(parts) == 3:
            return action, {
                "status": self._decode_status(parts[1]),
                "offset": max(0, int(parts[2])),
            }
        if action in {"detail", "resolve"} and len(parts) == 4:
            report_id = str(parts[1] or "").strip().lower()
            if len(report_id) != 32:
                raise ValueError("Invalid issue report identifier.")
            return action, {
                "report_id": report_id,
                "status": self._decode_status(parts[2]),
                "offset": max(0, int(parts[3])),
            }
        raise ValueError("Invalid callback data.")

    @staticmethod
    def _normalize_status(status: str) -> str:
        normalized = str(status or ISSUE_STATUS_INVESTIGATING).strip().lower()
        if normalized not in STATUS_LABELS:
            return ISSUE_STATUS_INVESTIGATING
        return normalized

    @staticmethod
    def _decode_status(value: str) -> str:
        return STATUS_SHORT_CODES_REVERSE.get(str(value or "").strip().lower(), ISSUE_STATUS_INVESTIGATING)

    @staticmethod
    def _format_timestamp(value: object) -> str:
        normalized = str(value or "").replace("T", " ")[:19].strip()
        if not normalized:
            return "Not set"
        return normalized

    @staticmethod
    def _format_summary_label(entry: dict[str, object]) -> str:
        created_at = TelegramIssueAdminBot._format_timestamp(entry.get("created_at"))
        username = str(entry.get("reporter_username") or "Unknown user").strip() or "Unknown user"
        title = str(entry.get("title") or "Untitled issue").strip() or "Untitled issue"
        status = STATUS_LABELS.get(str(entry.get("status") or ""), "Unknown")
        return f"{username}: {title}: {status}: {created_at}"

    @staticmethod
    def _format_detail_button_label(entry: dict[str, object]) -> str:
        username = str(entry.get("reporter_username") or "Unknown user").strip() or "Unknown user"
        title = str(entry.get("title") or "Untitled issue").strip() or "Untitled issue"
        status = STATUS_LABELS.get(str(entry.get("status") or ""), "Unknown")
        return f"{username} | {title} | {status}"

    @staticmethod
    def _truncate_button_label(value: str, limit: int = 60) -> str:
        normalized = " ".join(str(value or "").split())
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[: limit - 3].rstrip()}..."

    @staticmethod
    def _filter_button_text(candidate_status: str, active_status: str) -> str:
        prefix = ">" if candidate_status == active_status else ""
        return f"{prefix}{STATUS_LABELS[candidate_status]}"

    @staticmethod
    def _encode_list_callback(status: str, offset: int) -> str:
        return f"list:{STATUS_SHORT_CODES[status]}:{max(0, int(offset))}"

    @staticmethod
    def _encode_detail_callback(report_id: str, status: str, offset: int) -> str:
        return f"detail:{str(report_id or '').strip().lower()}:{STATUS_SHORT_CODES[status]}:{max(0, int(offset))}"

    @staticmethod
    def _encode_resolve_callback(report_id: str, status: str, offset: int) -> str:
        return f"resolve:{str(report_id or '').strip().lower()}:{STATUS_SHORT_CODES[status]}:{max(0, int(offset))}"
