"""Explicit plugin inheritance: fresh in-process extensions and JSON state for a new interpreter."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Literal

CHILD_STATE = "plugin_child_state"
CHILD_STATE_ENV = "ZETTCODE_PLUGIN_CHILD_STATE"
PLUGIN_ARGS_ENV = "ZETTCODE_PLUGIN_ARGS"
#: Leave room for the interpreter's other environment variables on platforms with small launch limits.
MAX_HANDOFF_BYTES = 16 * 1024


def encode_child_state(state: object) -> str:
    """Serialize a validated handoff with a portable, explicit size limit."""
    return _encode(validate_child_state(state))


def _encode(state: object) -> str:
    raw = json.dumps(state, allow_nan=False, separators=(",", ":"), sort_keys=True)
    if len(raw.encode("utf-8")) > MAX_HANDOFF_BYTES:
        raise ValueError(f"Plugin child JSON handoff exceeds {MAX_HANDOFF_BYTES} bytes (16 KiB)")
    return raw


@dataclass(frozen=True, slots=True)
class ChildSession:
    """The child being created; ``profile`` names a subagent's tool boundary."""

    kind: Literal["subagent", "daemon"]
    profile: str | None = None


def validate_child_state(state: object) -> dict[str, dict[str, Any]]:
    """Return an isolated JSON snapshot, refusing malformed or non-JSON plugin state.

    Keys are exact ``Plugin.name`` identities, not entry-point origins. Empty tables still request inheritance.
    Nothing is dropped on error: silently dropping a tool backend could run a child on the wrong machine.
    """

    def check(value: object) -> None:
        if value is None or isinstance(value, (str, bool, int)):
            return
        if isinstance(value, float) and math.isfinite(value):
            return
        if isinstance(value, list):
            for item in value:
                check(item)
            return
        if isinstance(value, dict) and all(isinstance(key, str) for key in value):
            for item in value.values():
                check(item)
            return
        raise ValueError("Plugin child state must contain only JSON values and string keys")

    if not isinstance(state, dict) or any(
        not isinstance(name, str) or not name or not isinstance(table, dict) for name, table in state.items()
    ):
        raise ValueError("Plugin child state must be an object of plugin names to state objects")
    try:
        check(state)
        return json.loads(_encode(state))
    except (RecursionError, TypeError) as error:
        raise ValueError("Plugin child state must be acyclic JSON") from error


def decode_child_state(raw: str) -> dict[str, dict[str, Any]]:
    """Read a bounded strict JSON handoff, rejecting duplicate keys and non-finite numbers."""
    if len(raw.encode("utf-8")) > MAX_HANDOFF_BYTES:
        raise ValueError(f"Plugin child JSON handoff exceeds {MAX_HANDOFF_BYTES} bytes (16 KiB)")
    return validate_child_state(decode_json(raw))


def decode_json(raw: str) -> Any:
    """Read JSON without silently accepting duplicate keys or non-finite constants."""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate plugin child state key {key!r}")
            result[key] = value
        return result

    def constant(value: str) -> Any:
        raise ValueError(f"Non-finite JSON value {value!r}")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except RecursionError as error:
        raise ValueError("Plugin child state must be acyclic JSON") from error
