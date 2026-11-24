"""time-context — the agent's sense of "when am I".

Hermes already stamps the *session start* into the system prompt; nothing tells
the model what time it is *now*. This plugin closes that gap without touching
the cached system prompt: the reading rides the per-turn user message, which the
host composes at API time (``agent/turn_context.py``) exactly so that a changing
block cannot break the prompt-cache prefix.

Two hooks, one tool, one command:

* ``pre_llm_call``  — injects the block once per turn.
* ``post_llm_call`` — records how long the turn actually took.
* ``now``           — an exact reading on demand (durations, offsets, windows).
* ``/time-context`` — inspect the block and manage windows from the chat.
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from datetime import datetime
from typing import Any, Optional

from .clock import (
    ClockOptions,
    parse_window,
    parse_windows,
    prior_turn_seconds,
    render_block,
    render_payload,
    resolve_tz,
    session_elapsed_seconds,
    wall_now,
)

logger = logging.getLogger("time_context")

# Per-session bookkeeping. Small, bounded, and keyed by the host's session id so
# one gateway serving several sessions (or profiles) cannot mix them up.
_STATE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_MAX_SESSIONS = 256
# A turn longer than this is almost certainly a suspended machine, not real work.
_MAX_TURN_SECONDS = 6 * 3600

_HELP = (
    "**time-context**\n"
    "• `/time-context` — the block the model sees right now\n"
    "• `/time-context windows` — configured windows\n"
    "• `/time-context add <name> | <when> | <note>` — add or replace a window\n"
    "• `/time-context remove <name>` — delete a window\n"
    "Example: `/time-context add School | Mon-Fri 08:30-15:10 | no deploy, no heavy builds`"
)


def _session_state(session_id: str, *, create: bool = True) -> dict[str, Any]:
    key = session_id or "<none>"
    state = _STATE.get(key)
    if state is None:
        if not create:
            return {}
        state = {}
        _STATE[key] = state
        while len(_STATE) > _MAX_SESSIONS:
            _STATE.popitem(last=False)
    else:
        _STATE.move_to_end(key)
    return state


def read_options(ctx: Any) -> ClockOptions:
    """Resolve user settings into a :class:`ClockOptions`, tolerating a bare ctx."""

    def get(key: str, default: Any) -> Any:
        try:
            value = ctx.get_config(key, default)
        except Exception:
            return default
        if value is None:
            return default
        return value

    locale = str(get("locale", "en") or "en").strip().lower()
    if locale not in ("en", "ru"):
        locale = "en"
    return ClockOptions(
        enabled=bool(get("enabled", True)),
        timezone=str(get("timezone", "") or "").strip(),
        locale=locale,
        show_seconds=bool(get("show_seconds", True)),
        show_durations=bool(get("show_durations", True)),
        show_stamp_note=bool(get("show_stamp_note", True)),
        windows=parse_windows(get("windows", [])),
    )


def _windows_raw(ctx: Any) -> list[Any]:
    try:
        raw = ctx.get_config("windows", []) or []
    except Exception:
        return []
    return raw if isinstance(raw, list) else []


def _save_windows(ctx: Any, windows: list[Any]) -> bool:
    """Persist the window list through the host's settings writer (if exposed)."""
    setter = getattr(ctx, "set_config", None)
    if not callable(setter):
        return False
    try:
        setter("windows", windows)
        return True
    except Exception as exc:
        logger.warning("time-context: cannot save windows: %s", exc)
        return False


def _measurements(messages: Any, state: dict[str, Any],
                  now: datetime) -> tuple[Optional[float], Optional[float]]:
    """Session age and previous-turn length, preferring conversation timestamps."""
    history = list(messages) if isinstance(messages, (list, tuple)) else []
    session_seconds = session_elapsed_seconds(history, now, state.get("first_seen"))
    last_turn = prior_turn_seconds(history)
    if last_turn is None:
        last_turn = state.get("last_turn_seconds")
    else:
        state["last_turn_seconds"] = last_turn
    if session_seconds is not None:
        state["session_seconds"] = session_seconds
        state.setdefault("first_seen", now.timestamp() - session_seconds)
    else:
        state.setdefault("first_seen", now.timestamp())
    return session_seconds, last_turn


def _current_view(ctx: Any, session_id: str = "") -> tuple[str, dict[str, Any]]:
    options = read_options(ctx)
    now = wall_now(resolve_tz(options.timezone))
    state = _session_state(session_id, create=False)
    session_seconds = state.get("session_seconds")
    if session_seconds is None:
        first_seen = state.get("first_seen")
        if first_seen is not None:
            session_seconds = now.timestamp() - first_seen
    last_turn = state.get("last_turn_seconds")
    block = render_block(
        now=now, options=options, session_seconds=session_seconds, last_turn_seconds=last_turn,
    )
    payload = render_payload(
        now=now, options=options, session_seconds=session_seconds, last_turn_seconds=last_turn,
    )
    return block, payload


def register(ctx: Any) -> None:
    # --- Turn start: the actual injection ---------------------------------
    def on_pre_llm_call(session_id: str = "", conversation_history: Any = None,
                        **_kwargs: Any) -> Optional[dict[str, str]]:
        try:
            options = read_options(ctx)
            if not options.enabled:
                return None
            now = wall_now(resolve_tz(options.timezone))
            state = _session_state(session_id)
            session_seconds, last_turn = _measurements(conversation_history, state, now)
            state["turn_started"] = now
            block = render_block(
                now=now,
                options=options,
                session_seconds=session_seconds,
                last_turn_seconds=last_turn,
            )
            return {"context": block} if block else None
        except Exception:  # never break a turn over a clock
            logger.warning("time-context: pre_llm_call failed", exc_info=True)
            return None

    # --- Turn end: how long did it really take ----------------------------
    def on_post_llm_call(session_id: str = "", **_kwargs: Any) -> None:
        try:
            state = _session_state(session_id, create=False)
            started = state.pop("turn_started", None)
            if not isinstance(started, datetime):
                return
            duration = (wall_now(started.tzinfo) - started).total_seconds()
            if 0 <= duration < _MAX_TURN_SECONDS:
                state["last_turn_seconds"] = duration
        except Exception:
            logger.debug("time-context: post_llm_call failed", exc_info=True)

    ctx.register_hook("pre_llm_call", on_pre_llm_call)
    ctx.register_hook("post_llm_call", on_post_llm_call)

    # --- Exact reading on demand -----------------------------------------
    schema = {
        "name": "now",
        "description": (
            "Exact current date and time on this machine, plus how long the session "
            "and the previous turn have been running and which user-defined time "
            "windows are active right now. Use it when an action depends on the "
            "clock (schedules, quiet hours, deadlines) or when the time stamp in the "
            "turn context may be stale because the turn has been running for a while."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    }

    def handle_now(params: Any = None, session_id: str = "", **_kwargs: Any) -> str:
        try:
            _, payload = _current_view(ctx, session_id)
            payload["success"] = True
            return json.dumps(payload, ensure_ascii=False)
        except Exception as exc:
            logger.warning("time-context: now tool failed: %s", exc)
            return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)

    ctx.register_tool(
        name="now",
        toolset="time_context",
        schema=schema,
        handler=handle_now,
    )

    # --- Chat-side control ------------------------------------------------
    def handle_command(raw_args: str = "") -> str:
        args = (raw_args or "").strip()
        lowered = args.lower()
        try:
            if not args or lowered in ("show", "status"):
                block, payload = _current_view(ctx)
                active = payload.get("active_windows") or []
                tail = f"Активных окон: {len(active)}" if active else "Активных окон нет"
                return f"{block}\n\n{tail}"

            if lowered in ("help", "?", "-h", "--help"):
                return _HELP

            if lowered in ("windows", "list", "ls"):
                windows = parse_windows(_windows_raw(ctx))
                if not windows:
                    return ("Окон нет. Добавить: "
                            "`/time-context add School | Mon-Fri 08:30-15:10 | no deploy`")
                lines = ["**Окна:**"]
                for window in windows:
                    note = f" — {window.note}" if window.note else ""
                    lines.append(f"• {window.label()}{note}")
                return "\n".join(lines)

            if lowered.startswith("add ") or lowered.startswith("set "):
                payload_text = args.split(" ", 1)[1].strip()
                parts = [part.strip() for part in payload_text.split("|")]
                name = parts[0] if parts else ""
                when = parts[1] if len(parts) > 1 else ""
                note = parts[2] if len(parts) > 2 else ""
                candidate = parse_window({"name": name, "when": when, "note": note})
                if candidate is None:
                    return ("Не понял окно. Формат: `/time-context add <name> | <when> | <note>`, "
                            "например `School | Mon-Fri 08:30-15:10 | no deploy`.")
                stored = [
                    entry for entry in _windows_raw(ctx)
                    if not (isinstance(entry, dict)
                            and str(entry.get("name") or "").lower() == name.lower())
                ]
                stored.append({"name": name, "when": when, "note": note})
                if not _save_windows(ctx, stored):
                    return "Хост не дал записать настройки — задай окно в config.yaml вручную."
                return f"Окно {candidate.label()} сохранено (всего {len(stored)})."

            if lowered.startswith(("remove ", "rm ", "delete ")):
                target = args.split(" ", 1)[1].strip().lower()
                current = _windows_raw(ctx)
                stored = [
                    entry for entry in current
                    if not (isinstance(entry, dict)
                            and str(entry.get("name") or "").lower() == target)
                ]
                if len(stored) == len(current):
                    return f"Окна «{target}» нет."
                if not _save_windows(ctx, stored):
                    return "Хост не дал записать настройки — правь config.yaml вручную."
                return f"Окно «{target}» удалено (осталось {len(stored)})."

            return _HELP
        except Exception as exc:
            logger.warning("time-context: command failed: %s", exc)
            return f"time-context: ошибка — {exc}"

    ctx.register_command(
        "time-context",
        handler=handle_command,
        description="Current time block, time windows, add/remove a window",
        args_hint="[windows|add <name> | <when> | <note>|remove <name>]",
    )
