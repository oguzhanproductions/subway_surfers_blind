from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
import uuid
from typing import Any

import enet

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.database import LeaderboardDatabase
from server.security import SecurityValidationError, TokenBucket
from server.service import LeaderboardService, ServiceError, SessionPrincipal
from subway_blind.leaderboard_protocol import (
    CLIENT_SEND_NONCE_PREFIX,
    PROTOCOL_VERSION,
    SERVER_SEND_NONCE_PREFIX,
    LeaderboardProtocolError,
    SecureChannel,
    derive_session_key,
    export_private_key,
    export_public_key,
    generate_private_key,
    load_private_key,
    load_public_key,
    make_handshake_ack,
    pack_handshake_message,
    unpack_handshake_message,
    urlsafe_b64decode,
)

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 27888
DEFAULT_RUNTIME_DIR_NAME = "runtime"
DEFAULT_IDLE_TIMEOUT_SECONDS = 600.0
CONNECT_BUCKET_CAPACITY = 10.0
CONNECT_BUCKET_REFILL = 3.0
REQUEST_BUCKET_CAPACITY = 60.0
REQUEST_BUCKET_REFILL = 20.0


@dataclass
class ConnectedPeer:
    peer: enet.Peer
    address: str
    connected_at: float
    last_seen_at: float
    session_id: str | None = None
    secure_channel: SecureChannel | None = None
    principal: SessionPrincipal | None = None


class AdminRebootRequested(RuntimeError):
    pass


class LeaderboardServer:
    def __init__(self, host: str, port: int, runtime_directory: Path):
        self.host = str(host)
        self.port = int(port)
        self.runtime_directory = Path(runtime_directory)
        self.runtime_directory.mkdir(parents=True, exist_ok=True)
        self.database = LeaderboardDatabase(self.runtime_directory / "leaderboard.sqlite3")
        self.service = LeaderboardService(self.database)
        self.identity_private_key = self._load_or_create_identity()
        self.public_key_text = export_public_key(self.identity_private_key)
        self._write_public_key_file()
        self.host_socket = enet.Host(enet.Address(self.host.encode("utf-8"), self.port), 512, 1, 0, 0)
        self.host_socket.compress_with_range_coder()
        self.connected_peers: dict[int, ConnectedPeer] = {}
        self.connect_buckets: dict[str, TokenBucket] = defaultdict(
            lambda: TokenBucket.create(CONNECT_BUCKET_CAPACITY, CONNECT_BUCKET_REFILL)
        )
        self.request_buckets: dict[str, TokenBucket] = defaultdict(
            lambda: TokenBucket.create(REQUEST_BUCKET_CAPACITY, REQUEST_BUCKET_REFILL)
        )
        self.admin_commands: "queue.Queue[str]" = queue.Queue()
        self.stop_requested = False
        self.reboot_requested = False
        self.admin_thread = threading.Thread(target=self._admin_console_loop, name="server-admin-console", daemon=True)

    def serve_forever(self) -> None:
        self.admin_thread.start()
        print(f"Leaderboard server listening on {self.host}:{self.port}")
        print(f"Server public key: {self.public_key_text}")
        print("Type help for commands.")
        try:
            while not self.stop_requested:
                self._drain_admin_commands()
                event = self.host_socket.service(20)
                if event is not None:
                    self._handle_event(event)
                self._expire_idle_connections()
                self.host_socket.flush()
        finally:
            self._disconnect_all_peers()
            self.database.close()
        if self.reboot_requested:
            raise AdminRebootRequested()

    def _handle_event(self, event: enet.Event) -> None:
        if event.type == enet.EVENT_TYPE_CONNECT:
            self._handle_connect(event.peer)
            return
        if event.type == enet.EVENT_TYPE_DISCONNECT:
            self.connected_peers.pop(int(event.peer.connectID), None)
            return
        if event.type == enet.EVENT_TYPE_RECEIVE:
            self._handle_receive(event.peer, bytes(event.packet.data))

    def _handle_connect(self, peer: enet.Peer) -> None:
        address = self._peer_address(peer)
        if not self.connect_buckets[address].allow():
            peer.disconnect_now()
            return
        now = time.monotonic()
        self.connected_peers[int(peer.connectID)] = ConnectedPeer(
            peer=peer,
            address=address,
            connected_at=now,
            last_seen_at=now,
        )

    def _handle_receive(self, peer: enet.Peer, packet_data: bytes) -> None:
        peer_state = self.connected_peers.get(int(peer.connectID))
        if peer_state is None:
            peer.disconnect_now()
            return
        peer_state.last_seen_at = time.monotonic()
        if not self.request_buckets[peer_state.address].allow():
            self._send_error(peer_state, "rate_limited", "Too many requests.")
            return
        try:
            if peer_state.secure_channel is None:
                self._handle_handshake(peer_state, packet_data)
                return
            request = peer_state.secure_channel.open(packet_data)
            response = self._dispatch_request(peer_state, request)
            self._send_secure(peer_state, response)
        except (LeaderboardProtocolError, SecurityValidationError, ServiceError) as exc:
            self._send_error(peer_state, getattr(exc, "code", "protocol_error"), str(exc))
        except Exception as exc:
            self._send_error(peer_state, "server_error", f"Unexpected server error: {exc}")

    def _handle_handshake(self, peer_state: ConnectedPeer, packet_data: bytes) -> None:
        hello = unpack_handshake_message(packet_data)
        if int(hello.get("protocol", 0)) != PROTOCOL_VERSION or str(hello.get("type")) != "hello":
            raise LeaderboardProtocolError("Unsupported protocol version.")
        client_public_key = load_public_key(str(hello.get("client_public_key") or ""))
        client_nonce = urlsafe_b64decode(str(hello.get("client_nonce") or ""))
        server_nonce = os.urandom(16)
        session_id = uuid.uuid4().hex
        session_key = derive_session_key(
            self.identity_private_key,
            client_public_key,
            client_nonce,
            server_nonce,
            session_id,
        )
        peer_state.session_id = session_id
        peer_state.secure_channel = SecureChannel(
            key=session_key,
            session_id=session_id,
            send_prefix=SERVER_SEND_NONCE_PREFIX,
            receive_prefix=CLIENT_SEND_NONCE_PREFIX,
        )
        self._send_plain(peer_state, make_handshake_ack(server_nonce=server_nonce, session_id=session_id))

    def _dispatch_request(self, peer_state: ConnectedPeer, request: dict[str, Any]) -> dict[str, Any]:
        request_type = str(request.get("type") or "").strip()
        payload = request.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        if request_type == "ping":
            return {"ok": True, "type": "pong", "payload": {"server_time": int(time.time())}}
        if request_type == "login":
            result = self.service.login_or_create_account(
                username=str(payload.get("username") or ""),
                password=str(payload.get("password") or ""),
                device_hash=str(payload.get("device_hash") or ""),
            )
            peer_state.principal = result["principal"]
            return {
                "ok": True,
                "type": "login_result",
                "payload": {
                    "status": result["status"],
                    "username": result["principal"].username,
                    "session_token": result["session_token"],
                },
            }
        if request_type == "resume_session":
            principal = self.service.resume_session(
                session_token=str(payload.get("session_token") or ""),
                device_hash=str(payload.get("device_hash") or ""),
            )
            peer_state.principal = principal
            return {
                "ok": True,
                "type": "resume_result",
                "payload": {
                    "username": principal.username,
                },
            }
        if request_type == "fetch_leaderboard":
            result = self.service.fetch_leaderboard(
                offset=int(payload.get("offset", 0) or 0),
                limit=int(payload.get("limit", 100) or 100),
            )
            return {"ok": True, "type": "leaderboard_result", "payload": result}
        if request_type == "fetch_profile":
            result = self.service.fetch_profile(
                username=str(payload.get("username") or ""),
                history_offset=int(payload.get("history_offset", 0) or 0),
                history_limit=int(payload.get("history_limit", 50) or 50),
            )
            return {"ok": True, "type": "profile_result", "payload": result}
        if request_type == "submit_score":
            if peer_state.principal is None:
                raise ServiceError("authentication_required", "Sign in before publishing a score.")
            peer_state.principal = self.service.revalidate_principal(peer_state.principal)
            result = self.service.submit_score(
                principal=peer_state.principal,
                score=int(payload.get("score", 0) or 0),
                coins=int(payload.get("coins", 0) or 0),
                play_time_seconds=int(payload.get("play_time_seconds", 0) or 0),
                game_version=str(payload.get("game_version") or ""),
            )
            return {"ok": True, "type": "submit_result", "payload": result}
        if request_type == "logout":
            peer_state.principal = None
            return {"ok": True, "type": "logout_result", "payload": {}}
        raise ServiceError("unsupported_request", "Unsupported request type.")

    def _send_plain(self, peer_state: ConnectedPeer, payload: dict[str, Any]) -> None:
        data = pack_handshake_message(payload)
        peer_state.peer.send(0, enet.Packet(data, enet.PACKET_FLAG_RELIABLE))

    def _send_secure(self, peer_state: ConnectedPeer, payload: dict[str, Any]) -> None:
        if peer_state.secure_channel is None:
            raise LeaderboardProtocolError("Secure channel is not available.")
        data = peer_state.secure_channel.seal(payload)
        peer_state.peer.send(0, enet.Packet(data, enet.PACKET_FLAG_RELIABLE))

    def _send_error(self, peer_state: ConnectedPeer, code: str, message: str) -> None:
        payload = {"ok": False, "type": "error", "error_code": str(code), "message": str(message)}
        if peer_state.secure_channel is None:
            self._send_plain(peer_state, payload)
            return
        self._send_secure(peer_state, payload)

    def _expire_idle_connections(self) -> None:
        deadline = time.monotonic() - DEFAULT_IDLE_TIMEOUT_SECONDS
        for connect_id, peer_state in list(self.connected_peers.items()):
            if peer_state.last_seen_at >= deadline:
                continue
            try:
                peer_state.peer.disconnect_now()
            except Exception:
                pass
            self.connected_peers.pop(connect_id, None)

    def _disconnect_all_peers(self) -> None:
        for peer_state in list(self.connected_peers.values()):
            try:
                peer_state.peer.disconnect_now()
            except Exception:
                pass
        self.connected_peers.clear()

    def _drain_admin_commands(self) -> None:
        while True:
            try:
                command = self.admin_commands.get_nowait()
            except queue.Empty:
                return
            self._handle_admin_command(command)

    def _handle_admin_command(self, command_line: str) -> None:
        tokens = str(command_line or "").strip().split()
        if not tokens:
            return
        command = tokens[0].lower()
        if command == "help":
            print("Available commands: help, changepass <username> <password>, listusers [limit], reboot, shutdown")
            return
        if command == "changepass":
            if len(tokens) < 3:
                print("Usage: changepass <username> <password>")
                return
            username, password = tokens[1], " ".join(tokens[2:])
            try:
                self.service.change_password(username, password)
            except (ServiceError, SecurityValidationError) as exc:
                print(f"changepass failed: {exc}")
                return
            print(f"Password changed for {username}. Existing sessions must sign in again.")
            return
        if command == "listusers":
            limit = 25
            if len(tokens) >= 2:
                try:
                    limit = int(tokens[1])
                except ValueError:
                    pass
            for account in self.service.list_accounts(limit):
                print(json.dumps(account, ensure_ascii=False))
            return
        if command == "reboot":
            self.reboot_requested = True
            self.stop_requested = True
            print("Reboot requested.")
            return
        if command == "shutdown":
            self.stop_requested = True
            print("Shutdown requested.")
            return
        print(f"Unknown command: {command}")

    def _admin_console_loop(self) -> None:
        while not self.stop_requested:
            try:
                line = input()
            except EOFError:
                return
            except Exception:
                time.sleep(0.1)
                continue
            self.admin_commands.put(line)

    def _load_or_create_identity(self):
        identity_path = self.runtime_directory / "server_identity.json"
        if identity_path.exists():
            try:
                loaded = json.loads(identity_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and str(loaded.get("private_key") or "").strip():
                    return load_private_key(str(loaded["private_key"]))
            except Exception:
                pass
        private_key = generate_private_key()
        identity_path.write_text(
            json.dumps(
                {
                    "private_key": export_private_key(private_key),
                    "public_key": export_public_key(private_key),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return private_key

    def _write_public_key_file(self) -> None:
        (self.runtime_directory / "server_public_key.b64").write_text(self.public_key_text, encoding="utf-8")

    @staticmethod
    def _peer_address(peer: enet.Peer) -> str:
        address = getattr(peer, "address", None)
        host = getattr(address, "host", 0)
        port = getattr(address, "port", 0)
        return f"{host}:{port}"


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Subway Surfers Blind leaderboard server")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host/IP to bind the ENet server to.")
    parser.add_argument("--port", default=DEFAULT_PORT, type=int, help="UDP port to bind the ENet server to.")
    parser.add_argument(
        "--runtime-dir",
        default=str(Path(__file__).resolve().parent / DEFAULT_RUNTIME_DIR_NAME),
        help="Directory used for the database and generated server identity.",
    )
    return parser


def main() -> None:
    parser = build_argument_parser()
    args = parser.parse_args()
    runtime_directory = Path(args.runtime_dir).resolve()
    while True:
        server = LeaderboardServer(host=args.host, port=args.port, runtime_directory=runtime_directory)
        try:
            server.serve_forever()
            return
        except AdminRebootRequested:
            print("Restarting server process.")
            time.sleep(0.3)
            continue


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
