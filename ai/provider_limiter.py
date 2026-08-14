"""Shared provider backoff state used by concurrent AI workers."""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
import time


@dataclass
class ProviderBackoff:
    """Thread-safe cooldown state for a single provider."""

    _lock: Lock = field(default_factory=Lock)
    _until: float = 0.0

    def wait_if_needed(self, deadline: float | None = None) -> bool:
        """Wait for cooldown without sleeping past an optional deadline.

        Returns False when the deadline has already been reached; existing
        callers that ignore the return value retain the previous behavior.
        """
        with self._lock:
            remaining = self._until - time.monotonic()
        if remaining <= 0:
            return deadline is None or time.monotonic() < deadline

        if deadline is not None:
            remaining = min(remaining, max(0.0, deadline - time.monotonic()))
        if remaining > 0:
            time.sleep(remaining)
        return deadline is None or time.monotonic() < deadline

    def activate(self, seconds: float) -> None:
        if seconds <= 0:
            return
        with self._lock:
            self._until = max(self._until, time.monotonic() + seconds)

    def clear(self) -> None:
        with self._lock:
            self._until = 0.0

    def is_active(self) -> bool:
        with self._lock:
            return self._until > time.monotonic()
