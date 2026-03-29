from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import time
from typing import Any

import enet

from subway_blind.leaderboard_protocol import (
    CLIENT_SEND_NONCE_PREFIX,
    PROTOCOL_VERSION,
    SERVER_SEND_NONCE_PREFIX,
    LeaderboardProtocolError,
    SecureChannel,
    ServerConnectionConfig,
    derive_session_key,
    generate_private_key,
    make_handshake_hello,
    pack_handshake_message,
    unpack_handshake_message,
    load_public_key,
)
from subway_blind.server_config import load_server_config
from subway_blind.version import APP_VERSION

CLIENT_CONNECTION_MAX_IDLE_SECONDS = 480.0


class LeaderboardClientError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class LeaderboardClient:
    def __init__(self, connection_config: ServerConnectionConfig | None = None):
        self.connection_config = connection_config or load_server_config()
        self.host: enet.Host | None = None
        self.peer: enet.Peer | None = None
        self.secure_channel: SecureChannel | None = None
        self.connected = False
        self.principal_username = ""
        self.auth_token = ""
        self._last_activity_at = 0.0

    def close(self) -> None:
        if self.peer is not None:
            try:
                self.peer.disconnect_now()
            except Exception:
                pass
        self.peer = None
        self.connected = False
        self.secure_channel = None
        self.host = None
        self._last_activity_at = 0.0

    def is_authenticated(self) -> bool:
        return bool(self.auth_token)

    def connect(self) -> bool:
        self._drain_nonblocking_events()
        if (
            self.connected
            and self.peer is not None
            and self.secure_channel is not None
            and not self._connection_idle_expired()
        ):
            return False
        if not self.connection_config.server_public_key:
            raise LeaderboardClientError(
                "missing_server_key",
                "server.json does not contain a server public key.",
            )
        self.close()
        self.host = enet.Host(None, 1, 1, 0, 0)
        self.host.compress_with_range_coder()
        self.peer = self.host.connect(
            enet.Address(self.connection_config.host.encode("utf-8"), int(self.connection_config.port)),
            1,
            0,
        )
        connected_event = self._wait_for_event(enet.EVENT_TYPE_CONNECT, self.connection_config.connect_timeout_ms)
        if connected_event is None:
            self.close()
            raise LeaderboardClientError("connect_timeout", "Unable to connect to the leaderboard server.")
        private_key = generate_private_key()
        hello_payload, client_nonce = make_handshake_hello(private_key)
        self.peer.send(0, enet.Packet(pack_handshake_message(hello_payload), enet.PACKET_FLAG_RELIABLE))
        handshake_response = self._wait_for_event(enet.EVENT_TYPE_RECEIVE, self.connection_config.request_timeout_ms)
        if handshake_response is None:
            self.close()
            raise LeaderboardClientError("handshake_timeout", "Timed out while negotiating a secure session.")
        server_hello = unpack_handshake_message(bytes(handshake_response.packet.data))
        if int(server_hello.get("protocol", 0)) != PROTOCOL_VERSION or str(server_hello.get("type")) != "hello_ack":
            self.close()
            raise LeaderboardClientError("handshake_failed", "Server returned an invalid handshake response.")
        session_id = str(server_hello.get("session_id") or "").strip()
        if not session_id:
            self.close()
            raise LeaderboardClientError("handshake_failed", "Server did not supply a secure session identifier.")
        server_nonce = str(server_hello.get("server_nonce") or "").strip()
        session_key = derive_session_key(
            private_key,
            load_public_key(self.connection_config.server_public_key),
            client_nonce,
            base64.urlsafe_b64decode(server_nonce.encode("ascii")),
            session_id,
        )
        self.secure_channel = SecureChannel(
            key=session_key,
            session_id=session_id,
            send_prefix=CLIENT_SEND_NONCE_PREFIX,
            receive_prefix=SERVER_SEND_NONCE_PREFIX,
        )
        self.connected = True
        self._mark_activity()
        if self.auth_token:
            try:
                result = self._request(
                    "resume_session",
                    {
                        "session_token": self.auth_token,
                        "device_hash": machine_fingerprint(),
                    },
                    allow_retry=False,
                    close_after_response=False,
                )
                self.principal_username = str(result.get("username") or self.principal_username or "")
            except LeaderboardClientError as exc:
                if exc.code == "reauth_required":
                    self.auth_token = ""
                    self.principal_username = ""
                else:
                    raise
        return True

    def ping(self) -> dict[str, Any]:
        return self._request("ping", {})

    def login(self, username: str, password: str) -> dict[str, Any]:
        result = self._request(
            "login",
            {
                "username": str(username or ""),
                "password": str(password or ""),
                "device_hash": machine_fingerprint(),
                "game_version": APP_VERSION,
            },
        )
        self.principal_username = str(result.get("username") or "")
        self.auth_token = str(result.get("session_token") or "")
        return result

    def logout(self) -> None:
        try:
            self._request("logout", {})
        except Exception:
            pass
        self.auth_token = ""
        self.principal_username = ""

    def fetch_leaderboard(
        self,
        offset: int = 0,
        limit: int | None = None,
        period: str = "all_time",
        difficulty: str = "all",
    ) -> dict[str, Any]:
        result_limit = self.connection_config.page_size if limit is None else int(limit)
        return self._request(
            "fetch_leaderboard",
            {
                "offset": int(offset),
                "limit": result_limit,
                "period": str(period or "all_time"),
                "difficulty": str(difficulty or "all"),
            },
        )

    def fetch_profile(self, username: str, history_offset: int = 0, history_limit: int = 50) -> dict[str, Any]:
        return self._request(
            "fetch_profile",
            {
                "username": str(username or ""),
                "history_offset": int(history_offset),
                "history_limit": int(history_limit),
            },
        )

    def submit_score(
        self,
        score: int,
        coins: int,
        play_time_seconds: int,
        *,
        difficulty: str = "unknown",
        death_reason: str = "",
        distance_meters: int | None = None,
        clean_escapes: int | None = None,
        revives_used: int | None = None,
        powerup_usage: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "submit_score",
            {
                "score": int(score),
                "coins": int(coins),
                "play_time_seconds": int(play_time_seconds),
                "game_version": APP_VERSION,
                "difficulty": str(difficulty or "unknown"),
                "death_reason": str(death_reason or ""),
                "distance_meters": None if distance_meters is None else int(distance_meters),
                "clean_escapes": None if clean_escapes is None else int(clean_escapes),
                "revives_used": None if revives_used is None else int(revives_used),
                "powerup_usage": dict(powerup_usage or {}),
            },
        )

    def _request(
        self,
        request_type: str,
        payload: dict[str, Any],
        allow_retry: bool = True,
        close_after_response: bool = True,
    ) -> dict[str, Any]:
        self.connect()
        if self.peer is None or self.secure_channel is None or self.host is None:
            raise LeaderboardClientError("disconnected", "No active server connection is available.")
        message = {"type": str(request_type), "payload": payload}
        self.peer.send(0, enet.Packet(self.secure_channel.seal(message), enet.PACKET_FLAG_RELIABLE))
        self._mark_activity()
        try:
            response_event = self._wait_for_event(enet.EVENT_TYPE_RECEIVE, self.connection_config.request_timeout_ms)
            if response_event is None:
                self.close()
                if allow_retry:
                    return self._request(request_type, payload, allow_retry=False, close_after_response=close_after_response)
                raise LeaderboardClientError("request_timeout", "Leaderboard server did not respond in time.")
            response = self.secure_channel.open(bytes(response_event.packet.data))
            self._mark_activity()
            if not bool(response.get("ok")):
                error_code = str(response.get("error_code") or "server_error")
                message = str(response.get("message") or "Leaderboard request failed.")
                if error_code == "reauth_required":
                    self.auth_token = ""
                    self.principal_username = ""
                raise LeaderboardClientError(error_code, message)
            return dict(response.get("payload") or {})
        finally:
            if close_after_response:
                self.close()

    def _wait_for_event(self, expected_type: int, timeout_ms: int) -> enet.Event | None:
        if self.host is None:
            return None
        deadline = time.monotonic() + (max(1, int(timeout_ms)) / 1000.0)
        while time.monotonic() < deadline:
            event = self.host.service(20)
            if event is None or event.type == enet.EVENT_TYPE_NONE:
                continue
            if event.type == expected_type:
                return event
            if event.type == enet.EVENT_TYPE_DISCONNECT:
                self.close()
                raise LeaderboardClientError("disconnected", "Disconnected from the leaderboard server.")
            if event.type == enet.EVENT_TYPE_RECEIVE and expected_type != enet.EVENT_TYPE_RECEIVE:
                continue
        return None

    def _drain_nonblocking_events(self) -> None:
        if self.host is None:
            return
        while True:
            event = self.host.service(0)
            if event is None or event.type == enet.EVENT_TYPE_NONE:
                return
            if event.type == enet.EVENT_TYPE_DISCONNECT:
                self.close()
                return

    def _connection_idle_expired(self) -> bool:
        if not self.connected or self._last_activity_at <= 0:
            return False
        return (time.monotonic() - self._last_activity_at) >= CLIENT_CONNECTION_MAX_IDLE_SECONDS

    def _mark_activity(self) -> None:
        self._last_activity_at = time.monotonic()


def machine_fingerprint() -> str:
    identity_parts = [
        _windows_machine_guid(),
        platform.node(),
        platform.machine(),
        os.environ.get("PROCESSOR_IDENTIFIER", ""),
    ]
    material = "|".join(part.strip() for part in identity_parts if str(part).strip())
    if not material:
        material = json.dumps(platform.uname()._asdict(), sort_keys=True, default=str)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _windows_machine_guid() -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as handle:
            value, _ = winreg.QueryValueEx(handle, "MachineGuid")
        return str(value or "").strip()
    except Exception:
        return ""
