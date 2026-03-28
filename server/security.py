from __future__ import annotations

import hmac
import re
import time
from dataclasses import dataclass
from typing import Final

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

USERNAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,23}$")


class SecurityValidationError(ValueError):
    pass


def build_password_hasher() -> PasswordHasher:
    return PasswordHasher(
        time_cost=3,
        memory_cost=65536,
        parallelism=2,
        hash_len=32,
        salt_len=16,
        type=Type.ID,
    )


def validate_username(username: str) -> str:
    normalized = str(username or "").strip()
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise SecurityValidationError(
            "User name must be 3 to 24 characters and may contain letters, numbers, dot, underscore, or hyphen."
        )
    return normalized


def validate_password(password: str) -> str:
    normalized = str(password or "")
    if len(normalized) < 6 or len(normalized) > 128:
        raise SecurityValidationError("Password must be between 6 and 128 characters.")
    return normalized


def verify_password(password_hasher: PasswordHasher, password_hash: str, candidate_password: str) -> bool:
    try:
        return bool(password_hasher.verify(password_hash, candidate_password))
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


def safe_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(str(left), str(right))


@dataclass
class TokenBucket:
    capacity: float
    refill_rate: float
    tokens: float
    updated_at: float

    @classmethod
    def create(cls, capacity: float, refill_rate: float) -> "TokenBucket":
        now = time.monotonic()
        return cls(capacity=float(capacity), refill_rate=float(refill_rate), tokens=float(capacity), updated_at=now)

    def allow(self, amount: float = 1.0) -> bool:
        current = time.monotonic()
        elapsed = max(0.0, current - self.updated_at)
        self.tokens = min(self.capacity, self.tokens + (elapsed * self.refill_rate))
        self.updated_at = current
        if self.tokens < amount:
            return False
        self.tokens -= amount
        return True
