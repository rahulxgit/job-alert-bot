"""Defensive parsing helpers for JSON returned by LLM providers."""
from __future__ import annotations

import json
from typing import Any


def _scan_brackets(fragment: str) -> tuple[list[str], bool, int]:
    """Replay a fragment and return (open_bracket_stack, ended_inside_string,
    index_of_last_comma_outside_any_string)."""
    stack: list[str] = []
    in_string = False
    escape = False
    last_comma = -1
    for index, char in enumerate(fragment):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append(char)
        elif char in "}]":
            if stack:
                stack.pop()
        elif char == ",":
            last_comma = index
    return stack, in_string, last_comma


def _close_and_parse(fragment: str, stack: list[str]) -> dict[str, Any] | None:
    closers = {"{": "}", "[": "]"}
    candidate = fragment + "".join(closers[opener] for opener in reversed(stack))
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) and parsed else None


def _repair_truncated_json(fragment: str) -> dict[str, Any] | None:
    """Best-effort recovery for a JSON object that got cut off mid-stream
    (hit an output-token budget before finishing). Tries closing every
    still-open string/array/object as-is first; if that isn't valid JSON
    (e.g. a dangling `"key":` with no value yet, or a half-written string),
    backs off to the last comma that sat outside any string — the last
    point we know for certain held a complete key/value pair or array
    element — and closes from there instead. This trades a little bit of
    the tail of the response for actually getting a usable, if partial,
    verdict instead of discarding the whole thing over one missing brace."""
    if not fragment or "{" not in fragment:
        return None

    stack, ended_in_string, last_comma = _scan_brackets(fragment)
    if not stack:
        return None  # already balanced; the earlier plain parse should have worked

    if not ended_in_string:
        trimmed = fragment.rstrip()
        if trimmed.endswith(","):
            trimmed = trimmed[:-1]
        trimmed_stack, _, _ = _scan_brackets(trimmed)
        result = _close_and_parse(trimmed, trimmed_stack)
        if result is not None:
            return result

    if last_comma < 0:
        return None
    trimmed = fragment[:last_comma]
    trimmed_stack, _, _ = _scan_brackets(trimmed)
    return _close_and_parse(trimmed, trimmed_stack)


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from plain text, fenced JSON, or surrounding prose."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("empty LLM response")

    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].strip().lower() in {"```", "```json"}:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    if start < 0:
        raise ValueError("LLM response did not contain a JSON object")
    end = cleaned.rfind("}")

    if end > start:
        try:
            parsed = json.loads(cleaned[start:end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    # A closing "}" being present doesn't guarantee it's balanced — an
    # output-token cutoff mid-array/mid-string can still leave the slice
    # invalid. Try to repair a truncated object before giving up.
    repaired = _repair_truncated_json(cleaned[start:])
    if repaired is not None:
        return repaired

    raise ValueError("LLM response did not contain a JSON object")


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        value = value.strip().lower()
        if value in {"true", "yes", "1"}:
            return True
        if value in {"false", "no", "0"}:
            return False
    return default


def as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []
