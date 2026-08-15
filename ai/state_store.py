"""Durable, atomic persistence for unified AI evaluation state."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Iterable

from ai.state import EvaluationState, STATE_VERSION, from_dict


STATE_PATH = Path("run-artifacts/ai-state.json")
STATE_META_VERSION = 1


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

    def load(self) -> dict[str, EvaluationState]:
        with self._lock:
            if self._loaded:
                return dict(self._states)
            self._states = self._read_locked()
            self._loaded = True
            return dict(self._states)

    def get(self, job_url: str) -> EvaluationState | None:
        self.load()
        with self._lock:
            return self._states.get(job_url)

    def upsert(self, state: EvaluationState) -> None:
        if not state.job_url:
            raise ValueError("job_url is required for AI state")
        self.load()
        with self._lock:
            self._states[state.job_url] = state
            self._write_locked()

    def upsert_many(self, states: Iterable[EvaluationState]) -> None:
        self.load()
        with self._lock:
            for state in states:
                if state.job_url:
                    self._states[state.job_url] = state
            self._write_locked()

    def snapshot(self) -> dict[str, dict]:
        self.load()
        with self._lock:
            return {url: state.to_dict() for url, state in self._states.items()}

    def replace_all(self, states: Iterable[EvaluationState]) -> None:
        with self._lock:
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
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
