"""Durable, atomic persistence for unified AI evaluation state."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Iterable

from ai.state import EvaluationState, STATE_VERSION, from_dict

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None


STATE_PATH = Path("run-artifacts/ai-state.json")
STATE_META_VERSION = 2


class AIStateStore:
    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            try:
                from ai import evaluator
                path = evaluator.AI_PROGRESS_PATH.with_name("ai-state.json")
            except (ImportError, AttributeError):
                path = STATE_PATH
        self.path = path
        self._lock = Lock()
        self._states: dict[str, EvaluationState] = {}
        self._loaded = False
        self._lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    @contextmanager
    def _file_lock(self):
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._lock_path.open("a+", encoding="utf-8")
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def load(self) -> dict[str, EvaluationState]:
        with self._lock:
            if not self._loaded:
                with self._file_lock():
                    self._states = self._read_locked()
                    changed = False
                    for state in self._states.values():
                        if state.is_stale():
                            state.mark_stale()
                            changed = True
                    self._loaded = True
                    if changed:
                        self._write_locked()
            return dict(self._states)

    def get(self, job_url: str) -> EvaluationState | None:
        return self.load().get(job_url)

    def upsert(self, state: EvaluationState) -> None:
        if not state.job_url:
            raise ValueError("job_url is required for AI state")
        with self._lock:
            with self._file_lock():
                disk_states = self._read_locked()
                disk_states[state.job_url] = state
                self._states = disk_states
                self._loaded = True
                self._write_locked()

    def upsert_many(self, states: Iterable[EvaluationState]) -> None:
        with self._lock:
            with self._file_lock():
                disk_states = self._read_locked()
                for state in states:
                    if state.job_url:
                        disk_states[state.job_url] = state
                self._states = disk_states
                self._loaded = True
                self._write_locked()

    def snapshot(self) -> dict[str, dict]:
        return {url: state.to_dict() for url, state in self.load().items()}

    def replace_all(self, states: Iterable[EvaluationState]) -> None:
        with self._lock:
            with self._file_lock():
                self._states = {state.job_url: state for state in states if state.job_url}
                self._loaded = True
                self._write_locked()

    def _read_locked(self) -> dict[str, EvaluationState]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return {}
        raw_states = payload.get("states", {}) if isinstance(payload, dict) else {}
        if not isinstance(raw_states, dict):
            return {}
        loaded: dict[str, EvaluationState] = {}
        for url, raw in raw_states.items():
            state = from_dict(raw)
            if state and state.job_url == url:
                loaded[url] = state
        return loaded

    def _write_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": STATE_META_VERSION,
            "state_version": STATE_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "states": {url: state.to_dict() for url, state in self._states.items()},
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
