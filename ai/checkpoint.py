"""Versioned identity helpers for resumable AI evaluation checkpoints."""
from __future__ import annotations

import hashlib
import json
from typing import Iterable


CHECKPOINT_VERSION = 2
PROMPT_VERSION = "phase-7"
EVALUATOR_VERSION = "phase-7"


def stable_hash(parts: Iterable[str]) -> str:
    payload = "\n".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def candidate_set_hash(urls: Iterable[str]) -> str:
    return stable_hash(sorted(url for url in urls if url))


def profile_hash(profile: str) -> str:
    return stable_hash([profile])


def evaluation_key(job_url: str, description: str, profile_digest: str) -> str:
    return stable_hash([job_url, description or "", profile_digest, PROMPT_VERSION, EVALUATOR_VERSION])


def checkpoint_identity(candidate_urls: Iterable[str], profile_digest: str) -> dict[str, str | int]:
    return {
        "checkpoint_version": CHECKPOINT_VERSION,
        "candidate_set_hash": candidate_set_hash(candidate_urls),
        "profile_hash": profile_digest,
        "prompt_version": PROMPT_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
    }


def compatible(payload: dict, candidate_urls: Iterable[str], profile_digest: str) -> bool:
    expected = checkpoint_identity(candidate_urls, profile_digest)
    return all(payload.get(key) == value for key, value in expected.items())
