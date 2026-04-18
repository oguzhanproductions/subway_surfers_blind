from __future__ import annotations
from subway_blind.strings import sx as _sx
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import time
from typing import Any
import enet
from subway_blind.leaderboard_protocol import CLIENT_SEND_NONCE_PREFIX, PROTOCOL_VERSION, SERVER_SEND_NONCE_PREFIX, LeaderboardProtocolError, SecureChannel, ServerConnectionConfig, derive_session_key, generate_private_key, make_handshake_hello, pack_handshake_message, unpack_handshake_message, load_public_key
from subway_blind.server_config import load_server_config
from subway_blind.version import APP_VERSION
CLIENT_CONNECTION_MAX_IDLE_SECONDS = 480.0
ISSUE_REPORT_PAGE_SIZE = 50

class LeaderboardClientError(RuntimeError):

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

class LeaderboardClient:

    def __init__(self, connection_config: ServerConnectionConfig | None=None):
        self.connection_config = connection_config or load_server_config()
        self.host: enet.Host | None = None
        self.peer: enet.Peer | None = None
        self.secure_channel: SecureChannel | None = None
        self.connected = False
        self.principal_username = _sx(2)
        self.auth_token = _sx(2)
        self.last_account_sync: dict[str, Any] = {}
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
        if self.connected and self.peer is not None and (self.secure_channel is not None) and (not self._connection_idle_expired()):
            return False
        if not self.connection_config.server_public_key:
            raise LeaderboardClientError(_sx(1960), _sx(1961))
        self.close()
        self.host = enet.Host(None, 1, 1, 0, 0)
        self.host.compress_with_range_coder()
        self.peer = self.host.connect(enet.Address(self.connection_config.host.encode(_sx(386)), int(self.connection_config.port)), 1, 0)
        connected_event = self._wait_for_event(enet.EVENT_TYPE_CONNECT, self.connection_config.connect_timeout_ms)
        if connected_event is None:
            self.close()
            raise LeaderboardClientError(_sx(1962), _sx(1963))
        private_key = generate_private_key()
        hello_payload, client_nonce = make_handshake_hello(private_key)
        self.peer.send(0, enet.Packet(pack_handshake_message(hello_payload), enet.PACKET_FLAG_RELIABLE))
        handshake_response = self._wait_for_event(enet.EVENT_TYPE_RECEIVE, self.connection_config.request_timeout_ms)
        if handshake_response is None:
            self.close()
            raise LeaderboardClientError(_sx(1964), _sx(1965))
        server_hello = unpack_handshake_message(bytes(handshake_response.packet.data))
        if int(server_hello.get(_sx(1986), 0)) != PROTOCOL_VERSION or str(server_hello.get(_sx(1957))) != _sx(1966):
            self.close()
            raise LeaderboardClientError(_sx(1967), _sx(1968))
        session_id = str(server_hello.get(_sx(1990)) or _sx(2)).strip()
        if not session_id:
            self.close()
            raise LeaderboardClientError(_sx(1967), _sx(1969))
        server_nonce = str(server_hello.get(_sx(1991)) or _sx(2)).strip()
        session_key = derive_session_key(private_key, load_public_key(self.connection_config.server_public_key), client_nonce, base64.urlsafe_b64decode(server_nonce.encode(_sx(1980))), session_id)
        self.secure_channel = SecureChannel(key=session_key, session_id=session_id, send_prefix=CLIENT_SEND_NONCE_PREFIX, receive_prefix=SERVER_SEND_NONCE_PREFIX)
        self.connected = True
        self._mark_activity()
        if self.auth_token:
            try:
                result = self._request(_sx(1981), {_sx(1982): self.auth_token, _sx(1971): machine_fingerprint()}, allow_retry=False, close_after_response=False)
                self.principal_username = str(result.get(_sx(1502)) or self.principal_username or _sx(2))
            except LeaderboardClientError as exc:
                if exc.code == _sx(1440):
                    self.auth_token = _sx(2)
                    self.principal_username = _sx(2)
                else:
                    raise
        return True

    def ping(self) -> dict[str, Any]:
        return self._request(_sx(1945), {})

    def login(self, username: str, password: str) -> dict[str, Any]:
        result = self._request(_sx(1946), {_sx(1502): str(username or _sx(2)), _sx(1970): str(password or _sx(2)), _sx(1971): machine_fingerprint(), _sx(971): APP_VERSION})
        self.principal_username = str(result.get(_sx(1502)) or _sx(2))
        self.auth_token = str(result.get(_sx(1982)) or _sx(2))
        return result

    def sync_account(self, claimed_reward_ids: list[str] | None=None, consumed_special_item_keys: list[str] | None=None) -> dict[str, Any]:
        normalized_claimed_reward_ids = [str(reward_id).strip() for reward_id in list(claimed_reward_ids or []) if str(reward_id).strip()]
        normalized_consumed_special_item_keys = [str(item_key).strip() for item_key in list(consumed_special_item_keys or []) if str(item_key).strip()]
        payload: dict[str, Any] = {_sx(1947): normalized_claimed_reward_ids}
        if consumed_special_item_keys is not None:
            payload[_sx(1329)] = normalized_consumed_special_item_keys
        result = self._request(_sx(1948), payload)
        self.last_account_sync = dict(result)
        return result

    def spin_weekly_wheel(self) -> dict[str, Any]:
        result = self._request(_sx(1949), {})
        self.last_account_sync = dict(result)
        return result

    def set_special_item_loadout(self, item_key: str, enabled: bool) -> dict[str, Any]:
        result = self._request(_sx(1950), {_sx(1890): str(item_key or _sx(2)), _sx(1863): bool(enabled)})
        self.last_account_sync = dict(result)
        return result

    def logout(self) -> None:
        try:
            self._request(_sx(1972), {})
        except Exception:
            pass
        self.auth_token = _sx(2)
        self.principal_username = _sx(2)

    def fetch_leaderboard(self, offset: int=0, limit: int | None=None, period: str=_sx(659), difficulty: str=_sx(660)) -> dict[str, Any]:
        result_limit = self.connection_config.page_size if limit is None else int(limit)
        return self._request(_sx(1951), {_sx(1825): int(offset), _sx(1973): result_limit, _sx(1816): str(period or _sx(659)), _sx(318): str(difficulty or _sx(660))})

    def fetch_profile(self, username: str, history_offset: int=0, history_limit: int=50) -> dict[str, Any]:
        return self._request(_sx(1952), {_sx(1502): str(username or _sx(2)), _sx(1974): int(history_offset), _sx(1975): int(history_limit)})

    def fetch_issue_reports(self, *, offset: int=0, limit: int=ISSUE_REPORT_PAGE_SIZE, status: str=_sx(660)) -> dict[str, Any]:
        return self._request(_sx(1953), {_sx(1825): max(0, int(offset)), _sx(1973): max(1, min(ISSUE_REPORT_PAGE_SIZE, int(limit))), _sx(1823): str(status or _sx(660))})

    def fetch_issue_report_detail(self, report_id: str) -> dict[str, Any]:
        return self._request(_sx(1954), {_sx(1885): str(report_id or _sx(2))})

    def submit_issue_report(self, *, title: str, message: str) -> dict[str, Any]:
        return self._request(_sx(1955), {_sx(1106): str(title or _sx(2)), _sx(1495): str(message or _sx(2))})

    def submit_score(self, score: int, coins: int, play_time_seconds: int, *, difficulty: str=_sx(578), death_reason: str=_sx(2), distance_meters: int | None=None, clean_escapes: int | None=None, revives_used: int | None=None, powerup_usage: dict[str, int] | None=None) -> dict[str, Any]:
        return self._request(_sx(1956), {_sx(968): int(score), _sx(363): int(coins), _sx(969): int(play_time_seconds), _sx(971): APP_VERSION, _sx(318): str(difficulty or _sx(578)), _sx(970): str(death_reason or _sx(2)), _sx(972): None if distance_meters is None else int(distance_meters), _sx(966): None if clean_escapes is None else int(clean_escapes), _sx(973): None if revives_used is None else int(revives_used), _sx(967): dict(powerup_usage or {})})

    def _request(self, request_type: str, payload: dict[str, Any], allow_retry: bool=True, close_after_response: bool=True) -> dict[str, Any]:
        self.connect()
        if self.peer is None or self.secure_channel is None or self.host is None:
            raise LeaderboardClientError(_sx(1976), _sx(1977))
        message = {_sx(1957): str(request_type), _sx(1958): payload}
        self.peer.send(0, enet.Packet(self.secure_channel.seal(message), enet.PACKET_FLAG_RELIABLE))
        self._mark_activity()
        try:
            response_event = self._wait_for_event(enet.EVENT_TYPE_RECEIVE, self.connection_config.request_timeout_ms)
            if response_event is None:
                self.close()
                if allow_retry:
                    return self._request(request_type, payload, allow_retry=False, close_after_response=close_after_response)
                raise LeaderboardClientError(_sx(1983), _sx(1984))
            response = self.secure_channel.open(bytes(response_event.packet.data))
            self._mark_activity()
            if not bool(response.get(_sx(1987))):
                error_code = str(response.get(_sx(1992)) or _sx(1988))
                message = str(response.get(_sx(1495)) or _sx(1989))
                if error_code == _sx(1440):
                    self.auth_token = _sx(2)
                    self.principal_username = _sx(2)
                raise LeaderboardClientError(error_code, message)
            return dict(response.get(_sx(1958)) or {})
        finally:
            if close_after_response:
                self.close()

    def _wait_for_event(self, expected_type: int, timeout_ms: int) -> enet.Event | None:
        if self.host is None:
            return None
        deadline = time.monotonic() + max(1, int(timeout_ms)) / 1000.0
        while time.monotonic() < deadline:
            event = self.host.service(20)
            if event is None or event.type == enet.EVENT_TYPE_NONE:
                continue
            if event.type == expected_type:
                return event
            if event.type == enet.EVENT_TYPE_DISCONNECT:
                self.close()
                raise LeaderboardClientError(_sx(1976), _sx(1985))
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
        return time.monotonic() - self._last_activity_at >= CLIENT_CONNECTION_MAX_IDLE_SECONDS

    def _mark_activity(self) -> None:
        self._last_activity_at = time.monotonic()

def machine_fingerprint() -> str:
    identity_parts = [_windows_machine_guid(), platform.node(), platform.machine(), os.environ.get(_sx(1959), _sx(2))]
    material = _sx(556).join((part.strip() for part in identity_parts if str(part).strip()))
    if not material:
        material = json.dumps(platform.uname()._asdict(), sort_keys=True, default=str)
    return hashlib.sha256(material.encode(_sx(386))).hexdigest()

def _windows_machine_guid() -> str:
    if os.name != _sx(85):
        return _sx(2)
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _sx(1978)) as handle:
            value, _ = winreg.QueryValueEx(handle, _sx(1979))
        return str(value or _sx(2)).strip()
    except Exception:
        return _sx(2)
