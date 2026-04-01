from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

from subway_blind.config import BASE_DIR, BUNDLED_RESOURCE_BASE_DIR, RESOURCE_BASE_DIR, resource_path
from subway_blind.leaderboard_protocol import (
    DEFAULT_CONNECT_TIMEOUT_MS,
    DEFAULT_PAGE_SIZE,
    DEFAULT_REQUEST_TIMEOUT_MS,
    MAX_PAGE_SIZE,
    ServerConnectionConfig,
)

DEFAULT_SERVER_CONFIG: dict[str, Any] = {
    "host": "127.0.0.1",
    "port": 27888,
    "server_public_key": "",
    "server_public_key_path": "server/runtime/server_public_key.b64",
    "connect_timeout_ms": DEFAULT_CONNECT_TIMEOUT_MS,
    "request_timeout_ms": DEFAULT_REQUEST_TIMEOUT_MS,
    "page_size": DEFAULT_PAGE_SIZE,
}


def default_server_config_path() -> Path:
    external_path = RESOURCE_BASE_DIR / "server.json"
    if external_path.exists():
        return external_path
    if getattr(sys, "frozen", False):
        return external_path
    fallback_directory = BASE_DIR / "data"
    fallback_directory.mkdir(parents=True, exist_ok=True)
    return fallback_directory / "server.json"


def ensure_server_config() -> Path:
    config_path = default_server_config_path()
    if config_path.exists():
        return config_path
    template_path = Path(resource_path("server.json"))
    try:
        if template_path.exists() and template_path != config_path:
            config_path.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            config_path.write_text(json.dumps(DEFAULT_SERVER_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        fallback_directory = BASE_DIR / "data"
        fallback_directory.mkdir(parents=True, exist_ok=True)
        fallback_path = fallback_directory / "server.json"
        try:
            if template_path.exists() and template_path != fallback_path:
                fallback_path.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                fallback_path.write_text(json.dumps(DEFAULT_SERVER_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
            return fallback_path
        except Exception:
            pass
    return config_path


def load_server_config() -> ServerConnectionConfig:
    config_path = ensure_server_config()
    raw_config = dict(DEFAULT_SERVER_CONFIG)
    try:
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            raw_config.update(loaded)
    except Exception:
        pass

    host = str(raw_config.get("host") or DEFAULT_SERVER_CONFIG["host"]).strip() or str(DEFAULT_SERVER_CONFIG["host"])
    port = _normalize_int(raw_config.get("port"), int(DEFAULT_SERVER_CONFIG["port"]), 1, 65535)
    public_key = str(raw_config.get("server_public_key") or "").strip()
    public_key_path = str(raw_config.get("server_public_key_path") or "").strip()
    if not public_key and public_key_path:
        public_key = _load_public_key_from_path(config_path=config_path, configured_path=public_key_path)

    connect_timeout_ms = _normalize_int(
        raw_config.get("connect_timeout_ms"),
        DEFAULT_CONNECT_TIMEOUT_MS,
        250,
        15000,
    )
    request_timeout_ms = _normalize_int(
        raw_config.get("request_timeout_ms"),
        DEFAULT_REQUEST_TIMEOUT_MS,
        250,
        30000,
    )
    page_size = _normalize_int(raw_config.get("page_size"), DEFAULT_PAGE_SIZE, 10, MAX_PAGE_SIZE)
    return ServerConnectionConfig(
        host=host,
        port=port,
        server_public_key=public_key,
        connect_timeout_ms=connect_timeout_ms,
        request_timeout_ms=request_timeout_ms,
        page_size=page_size,
    )


def _normalize_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = int(default)
    return max(minimum, min(maximum, normalized))


def _load_public_key_from_path(config_path: Path, configured_path: str) -> str:
    for candidate in _server_key_path_candidates(config_path=config_path, configured_path=configured_path):
        try:
            key_text = candidate.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if key_text:
            return key_text
    return ""


def _server_key_path_candidates(config_path: Path, configured_path: str) -> list[Path]:
    raw_path = str(configured_path or "").strip()
    if not raw_path:
        return []
    key_path = Path(raw_path)
    if key_path.is_absolute():
        return [key_path]

    candidates: list[Path] = []
    seen: set[str] = set()
    search_roots = (
        config_path.parent,
        RESOURCE_BASE_DIR,
        BUNDLED_RESOURCE_BASE_DIR,
        BASE_DIR,
        BASE_DIR / "data",
    )
    for root in search_roots:
        candidate = (Path(root) / key_path).resolve()
        signature = str(candidate).lower()
        if signature in seen:
            continue
        seen.add(signature)
        candidates.append(candidate)
    return candidates
