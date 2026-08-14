"""Shared provider backoff state used by concurrent AI workers."""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
import time


@dataclass
class ProviderBackoff:
    """Thread-safe cooldown state for a single provider."""

    _lock: Lock = Lock()
    _until: float = 0.0

    def wait_if_needed(self) -> None:
        with self._lock:
            remaining = self._until - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)

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
