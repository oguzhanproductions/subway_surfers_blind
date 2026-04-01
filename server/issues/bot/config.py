from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path


@dataclass(slots=True, frozen=True)
class TelegramIssueBotSubscriber:
    user_id: int
    chat_id: int


@dataclass(slots=True, frozen=True)
class TelegramIssueBotConfig:
    enabled: bool = False
    bot_token: str = ""
    allowed_user_ids: tuple[int, ...] = ()
    subscribers: tuple[TelegramIssueBotSubscriber, ...] = ()
    polling_timeout_seconds: int = 20


class TelegramIssueBotConfigStore:
    def __init__(self, config_path: Path):
        self.config_path = Path(config_path)

    def load(self) -> TelegramIssueBotConfig:
        if not self.config_path.exists():
            config = TelegramIssueBotConfig()
            self.save(config)
            return config
        try:
            loaded = json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception:
            config = TelegramIssueBotConfig()
            self.save(config)
            return config
        if not isinstance(loaded, dict):
            config = TelegramIssueBotConfig()
            self.save(config)
            return config
        config = TelegramIssueBotConfig(
            enabled=bool(loaded.get("enabled", False)),
            bot_token=str(loaded.get("bot_token") or "").strip(),
            allowed_user_ids=self._normalize_allowed_user_ids(loaded.get("allowed_user_ids")),
            subscribers=self._normalize_subscribers(loaded.get("subscribers")),
            polling_timeout_seconds=max(1, min(60, self._normalize_optional_int(loaded.get("polling_timeout_seconds")) or 20)),
        )
        normalized_payload = self._serialize_config(config)
        if loaded != normalized_payload:
            self.save(config)
        return config

    def save(self, config: TelegramIssueBotConfig) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(self._serialize_config(config), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _normalize_allowed_user_ids(value: object) -> tuple[int, ...]:
        if not isinstance(value, list):
            return ()
        normalized: set[int] = set()
        for item in value:
            parsed = TelegramIssueBotConfigStore._normalize_optional_int(item)
            if parsed is not None:
                normalized.add(parsed)
        return tuple(sorted(normalized))

    @staticmethod
    def _normalize_subscribers(value: object) -> tuple[TelegramIssueBotSubscriber, ...]:
        if not isinstance(value, list):
            return ()
        normalized: dict[int, TelegramIssueBotSubscriber] = {}
        for item in value:
            if not isinstance(item, dict):
                continue
            user_id = TelegramIssueBotConfigStore._normalize_optional_int(item.get("user_id"))
            chat_id = TelegramIssueBotConfigStore._normalize_optional_int(item.get("chat_id"))
            if user_id is None or chat_id is None:
                continue
            normalized[user_id] = TelegramIssueBotSubscriber(user_id=user_id, chat_id=chat_id)
        return tuple(normalized[user_id] for user_id in sorted(normalized))

    @staticmethod
    def _normalize_optional_int(value: object) -> int | None:
        if value in {None, ""}:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _serialize_config(config: TelegramIssueBotConfig) -> dict[str, object]:
        payload = asdict(config)
        payload["allowed_user_ids"] = list(config.allowed_user_ids)
        payload["subscribers"] = [
            {
                "user_id": subscriber.user_id,
                "chat_id": subscriber.chat_id,
            }
            for subscriber in config.subscribers
        ]
        return payload
