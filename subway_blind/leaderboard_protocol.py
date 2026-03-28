from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

PROTOCOL_VERSION = 1
HANDSHAKE_MAGIC = b"SBLH"
SECURE_MAGIC = b"SBLE"
PROTOCOL_INFO = b"subway-blind-leaderboard/v1"
DEFAULT_CONNECT_TIMEOUT_MS = 1800
DEFAULT_REQUEST_TIMEOUT_MS = 4000
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 100
MAX_PACKET_BYTES = 64 * 1024
CLIENT_SEND_NONCE_PREFIX = b"CLNT"
SERVER_SEND_NONCE_PREFIX = b"SRVR"


class LeaderboardProtocolError(RuntimeError):
    pass


@dataclass(frozen=True)
class ServerConnectionConfig:
    host: str
    port: int
    server_public_key: str
    connect_timeout_ms: int = DEFAULT_CONNECT_TIMEOUT_MS
    request_timeout_ms: int = DEFAULT_REQUEST_TIMEOUT_MS
    page_size: int = DEFAULT_PAGE_SIZE


def now_epoch() -> int:
    return int(time.time())


def urlsafe_b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def urlsafe_b64decode(data: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(data.encode("ascii"))
    except Exception as exc:
        raise LeaderboardProtocolError("Invalid base64 payload.") from exc


def encode_message(payload: dict[str, Any]) -> bytes:
    try:
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    except Exception as exc:
        raise LeaderboardProtocolError("Unable to encode protocol message.") from exc
    if len(serialized) > MAX_PACKET_BYTES:
        raise LeaderboardProtocolError("Protocol message exceeds the maximum packet size.")
    return serialized


def decode_message(payload: bytes) -> dict[str, Any]:
    if len(payload) > MAX_PACKET_BYTES:
        raise LeaderboardProtocolError("Protocol message exceeds the maximum packet size.")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except Exception as exc:
        raise LeaderboardProtocolError("Unable to decode protocol message.") from exc
    if not isinstance(decoded, dict):
        raise LeaderboardProtocolError("Protocol message must be a JSON object.")
    return decoded


def pack_handshake_message(payload: dict[str, Any]) -> bytes:
    return HANDSHAKE_MAGIC + encode_message(payload)


def unpack_handshake_message(payload: bytes) -> dict[str, Any]:
    if not payload.startswith(HANDSHAKE_MAGIC):
        raise LeaderboardProtocolError("Expected a handshake packet.")
    return decode_message(payload[len(HANDSHAKE_MAGIC) :])


def generate_private_key() -> X25519PrivateKey:
    return X25519PrivateKey.generate()


def export_private_key(private_key: X25519PrivateKey) -> str:
    return urlsafe_b64encode(
        private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )


def export_public_key(private_key: X25519PrivateKey) -> str:
    return urlsafe_b64encode(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )


def load_private_key(serialized_key: str) -> X25519PrivateKey:
    try:
        return X25519PrivateKey.from_private_bytes(urlsafe_b64decode(serialized_key))
    except Exception as exc:
        raise LeaderboardProtocolError("Invalid private key.") from exc


def load_public_key(serialized_key: str) -> X25519PublicKey:
    try:
        return X25519PublicKey.from_public_bytes(urlsafe_b64decode(serialized_key))
    except Exception as exc:
        raise LeaderboardProtocolError("Invalid public key.") from exc


def derive_session_key(
    local_private_key: X25519PrivateKey,
    remote_public_key: X25519PublicKey,
    client_nonce: bytes,
    server_nonce: bytes,
    session_id: str,
) -> bytes:
    shared_secret = local_private_key.exchange(remote_public_key)
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=client_nonce + server_nonce,
        info=PROTOCOL_INFO + session_id.encode("utf-8"),
    )
    return hkdf.derive(shared_secret)


def make_handshake_hello(client_private_key: X25519PrivateKey) -> tuple[dict[str, Any], bytes]:
    client_nonce = os.urandom(16)
    return (
        {
            "protocol": PROTOCOL_VERSION,
            "type": "hello",
            "client_public_key": export_public_key(client_private_key),
            "client_nonce": urlsafe_b64encode(client_nonce),
        },
        client_nonce,
    )


def make_handshake_ack(server_nonce: bytes, session_id: str) -> dict[str, Any]:
    return {
        "protocol": PROTOCOL_VERSION,
        "type": "hello_ack",
        "session_id": session_id,
        "server_nonce": urlsafe_b64encode(server_nonce),
    }


class SecureChannel:
    def __init__(self, key: bytes, session_id: str, send_prefix: bytes, receive_prefix: bytes):
        if len(send_prefix) != 4 or len(receive_prefix) != 4:
            raise LeaderboardProtocolError("Nonce prefixes must be exactly four bytes long.")
        self._cipher = ChaCha20Poly1305(key)
        self._session_id = str(session_id)
        self._send_prefix = send_prefix
        self._receive_prefix = receive_prefix
        self._send_counter = 0
        self._receive_counter = 0

    def _aad(self, counter: int) -> bytes:
        return self._session_id.encode("utf-8") + counter.to_bytes(8, "big")

    def _nonce(self, prefix: bytes, counter: int) -> bytes:
        return prefix + counter.to_bytes(8, "big")

    def seal(self, payload: dict[str, Any]) -> bytes:
        self._send_counter += 1
        plaintext = encode_message(payload)
        counter_bytes = self._send_counter.to_bytes(8, "big")
        ciphertext = self._cipher.encrypt(
            self._nonce(self._send_prefix, self._send_counter),
            plaintext,
            self._aad(self._send_counter),
        )
        packet = SECURE_MAGIC + counter_bytes + ciphertext
        if len(packet) > MAX_PACKET_BYTES:
            raise LeaderboardProtocolError("Encrypted packet exceeds the maximum packet size.")
        return packet

    def open(self, packet: bytes) -> dict[str, Any]:
        if not packet.startswith(SECURE_MAGIC):
            raise LeaderboardProtocolError("Expected an encrypted packet.")
        if len(packet) <= len(SECURE_MAGIC) + 8:
            raise LeaderboardProtocolError("Encrypted packet is incomplete.")
        counter = int.from_bytes(packet[len(SECURE_MAGIC) : len(SECURE_MAGIC) + 8], "big")
        if counter != self._receive_counter + 1:
            raise LeaderboardProtocolError("Encrypted packet counter is out of sequence.")
        ciphertext = packet[len(SECURE_MAGIC) + 8 :]
        try:
            plaintext = self._cipher.decrypt(
                self._nonce(self._receive_prefix, counter),
                ciphertext,
                self._aad(counter),
            )
        except Exception as exc:
            raise LeaderboardProtocolError("Unable to decrypt encrypted packet.") from exc
        self._receive_counter = counter
        return decode_message(plaintext)
