"""Pure time, window and duration logic for the time-context plugin.

No Hermes imports and no side effects: this module must be importable by
``hermes plugins validate`` and by the unit tests without a running host.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo
from typing import Any, Iterable, Mapping, Optional, Sequence

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

_DAY_TOKENS: dict[str, int] = {
    # English (abbreviated and full)
    "mon": 0, "monday": 0,
    "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "weds": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
    # Russian (abbreviated and full)
    "пн": 0, "пон": 0, "понедельник": 0,
    "вт": 1, "втор": 1, "вторник": 1,
    "ср": 2, "среда": 2, "среду": 2,
    "чт": 3, "чет": 3, "четверг": 3,
    "пт": 4, "пят": 4, "пятница": 4, "пятницу": 4,
    "сб": 5, "суб": 5, "суббота": 5, "субботу": 5,
    "вс": 6, "воскр": 6, "воскресенье": 6,
}

_EVERY_DAY_TOKENS = frozenset({
    "*", "all", "daily", "everyday", "every-day",
    "ежедневно", "каждый", "любой", "все",
})

_EN_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_EN_WEEKDAYS_FULL = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_EN_WEEKDAYS_LOWER = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_EN_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_RU_WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
_RU_WEEKDAYS_FULL = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
_RU_MONTHS_GEN = ("января", "февраля", "марта", "апреля", "мая", "июня",
                  "июля", "августа", "сентября", "октября", "ноября", "декабря")

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "now": "Now",
        "session": "session",
        "last_turn": "last turn",
        "stamp_note": "reading taken at turn start",
        "window": "Window",
        "windows": "Windows",
        "cmd_help": (
            "**time-context**\n"
            "• `/time-context` — the block the model sees right now\n"
            "• `/time-context windows` — configured windows\n"
            "• `/time-context add <name> | <when> | <note>` — add or replace a window\n"
            "• `/time-context remove <name>` — delete a window\n"
            "Example: `/time-context add Office | Mon-Fri 09:00-18:00 | no deploys while people work`"
        ),
        "cmd_active_none": "No active windows",
        "cmd_active_count": "Active windows: {count}",
        "cmd_windows_empty": "No windows yet. Add one: `/time-context add Office | Mon-Fri 09:00-18:00 | no deploys`",
        "cmd_windows_header": "**Windows:**",
        "cmd_saved": "Window {label} saved ({count} total).",
        "cmd_removed": "Window «{name}» removed ({count} left).",
        "cmd_not_found": "No window named «{name}».",
        "cmd_bad_window": (
            "Could not parse that window. Format: `/time-context add <name> | <when> | <note>`, "
            "e.g. `Office | Mon-Fri 09:00-18:00 | no deploys while people work`."
        ),
        "cmd_save_failed": "The host refused to write settings — set the window in config.yaml instead.",
        "cmd_error": "time-context: error — {error}",
    },
    "ru": {
        "now": "Сейчас",
        "session": "сессия",
        "last_turn": "прошлый ход",
        "stamp_note": "время на начало хода",
        "window": "Окно",
        "windows": "Окна",
        "cmd_help": (
            "**time-context**\n"
            "• `/time-context` — блок, который видит модель сейчас\n"
            "• `/time-context windows` — настроенные окна\n"
            "• `/time-context add <имя> | <когда> | <заметка>` — добавить или заменить окно\n"
            "• `/time-context remove <имя>` — удалить окно\n"
            "Пример: `/time-context add Работа | пн-пт 09:00-18:00 | без деплоя, пока люди работают`"
        ),
        "cmd_active_none": "Активных окон нет",
        "cmd_active_count": "Активных окон: {count}",
        "cmd_windows_empty": "Окон нет. Добавить: `/time-context add Работа | пн-пт 09:00-18:00 | без деплоя`",
        "cmd_windows_header": "**Окна:**",
        "cmd_saved": "Окно {label} сохранено (всего {count}).",
        "cmd_removed": "Окно «{name}» удалено (осталось {count}).",
        "cmd_not_found": "Окна «{name}» нет.",
        "cmd_bad_window": (
            "Не понял окно. Формат: `/time-context add <имя> | <когда> | <заметка>`, "
            "например `Работа | пн-пт 09:00-18:00 | без деплоя, пока люди работают`."
        ),
        "cmd_save_failed": "Хост не дал записать настройки — задай окно в config.yaml вручную.",
        "cmd_error": "time-context: ошибка — {error}",
    },
}


# ---------------------------------------------------------------------------
# Timezone and clock
# ---------------------------------------------------------------------------

def resolve_tz(name: str) -> Optional[tzinfo]:
    """An IANA zone by name, or ``None`` for the machine's local zone."""
    name = (name or "").strip()
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo  # stdlib on 3.9+, tzdata package on Windows
        return ZoneInfo(name)
    except Exception:
        return None


def wall_now(tz: Optional[tzinfo] = None) -> datetime:
    """Timezone-aware wall clock reading. Never naive."""
    if tz is None:
        return datetime.now().astimezone()
    return datetime.now(tz)


def offset_label(dt: datetime) -> str:
    """``+03:00`` — the numeric offset, always unambiguous."""
    raw = dt.strftime("%z") or ""
    if len(raw) == 5:
        return f"{raw[:3]}:{raw[3:]}"
    return raw


def zone_label(dt: datetime) -> str:
    """Short zone abbreviation when the platform exposes a clean one (``MSK``, ``CET``).

    Windows reports things like ``RTZ 2 (зима)``; that is noise in a one-line
    block, so anything with digits, spaces or parentheses falls back to the
    numeric offset alone.
    """
    name = (dt.tzname() or "").strip()
    if not name or len(name) > 8:
        return ""
    if any(char.isdigit() or char in " ()/\\" for char in name):
        return ""
    return name


# ---------------------------------------------------------------------------
# Durations
# ---------------------------------------------------------------------------

def format_duration(seconds: Optional[float], locale: str = "en", *, show_seconds: bool = True) -> str:
    """Human-scale duration: ``1h 12m`` / ``1 ч 12 м``, or ``45s`` under a minute."""
    if seconds is None:
        return ""
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds} s" if locale == "en" else f"{seconds} с"
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if locale == "ru":
        unit_h, unit_m, unit_s = "ч", "м", "с"
    else:
        unit_h, unit_m, unit_s = "h", "m", "s"
    if hours:
        out = f"{hours} {unit_h} {minutes} {unit_m}"
        if show_seconds and sec:
            out += f" {sec} {unit_s}"
        return out
    out = f"{minutes} {unit_m}"
    if show_seconds and sec:
        out += f" {sec} {unit_s}"
    return out


def format_stamp(dt: datetime, locale: str = "en", *, show_seconds: bool = True) -> str:
    """``Tue 24 Nov 2026, 18:28:11`` / ``вт, 24 ноя 2026, 18:28:11``."""
    clock = dt.strftime("%H:%M:%S" if show_seconds else "%H:%M")
    day = dt.weekday()
    month = dt.month - 1
    if locale == "ru":
        return f"{_RU_WEEKDAYS[day]}, {dt.day} {_RU_MONTHS_GEN[month]} {dt.year}, {clock}"
    return f"{_EN_WEEKDAYS[day]} {dt.day} {_EN_MONTHS[month]} {dt.year}, {clock}"


def weekday_name(dt: datetime, locale: str = "en") -> str:
    if locale == "ru":
        return _RU_WEEKDAYS_FULL[dt.weekday()]
    return _EN_WEEKDAYS_FULL[dt.weekday()]


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Window:
    """One named recurring interval, in the machine's local wall clock."""

    name: str
    days: frozenset[int]
    start_minute: int
    end_minute: int
    when: str = ""
    note: str = ""

    @property
    def wraps_midnight(self) -> bool:
        return self.start_minute > self.end_minute

    def covers(self, dt: datetime) -> bool:
        """True when ``dt`` falls inside the window.

        A window that wraps midnight (23:00-08:00) is attributed to the day it
        starts on, so "Fri 23:00-08:00" covers Saturday morning up to 08:00.
        """
        now_minute = dt.hour * 60 + dt.minute
        today = dt.weekday()
        if not self.wraps_midnight:
            return today in self.days and self.start_minute <= now_minute < self.end_minute
        if now_minute >= self.start_minute:
            return today in self.days
        yesterday = (today - 1) % 7
        return now_minute < self.end_minute and yesterday in self.days

    def label(self) -> str:
        return f'"{self.name}" ({self.when})' if self.when else f'"{self.name}"'


_TIME_RE = re.compile(r"^(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))?$")
_WHEN_RE = re.compile(
    r"^\s*(?:(?P<days>[^\d]+?)\s+)?"
    r"(?P<start>\d{1,2}(?:[:.]\d{2})?)"
    r"\s*[-–—]\s*"
    r"(?P<end>\d{1,2}(?:[:.]\d{2})?)"
    r"\s*$"
)


def _parse_minute(token: str) -> Optional[int]:
    match = _TIME_RE.match(token.strip())
    if not match:
        return None
    hour = int(match.group("h"))
    minute = int(match.group("m") or 0)
    if not (0 <= hour <= 24) or not (0 <= minute < 60):
        return None
    return min(hour * 60 + minute, 24 * 60)


def parse_days(spec: str) -> Optional[frozenset[int]]:
    """``Mon-Fri`` / ``пн-пт`` / ``sat,sun`` / ``daily`` / ``0-4`` → day indices."""
    spec = (spec or "").strip().lower().replace("ё", "е")
    if not spec:
        return frozenset({0, 1, 2, 3, 4})
    if spec in _EVERY_DAY_TOKENS:
        return frozenset(range(7))

    days: set[int] = set()
    for chunk in re.split(r"[,;]", spec):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk in _EVERY_DAY_TOKENS:
            days.update(range(7))
            continue
        if "-" in chunk or "–" in chunk:
            left, _, right = re.split(r"([-–])", chunk, maxsplit=1)
            start = _day_index(left.strip())
            end = _day_index(right.strip())
            if start is None or end is None:
                return None
            if start <= end:
                days.update(range(start, end + 1))
            else:  # "sat-tue": a range that wraps the week
                days.update(range(start, 7))
                days.update(range(0, end + 1))
            continue
        index = _day_index(chunk)
        if index is None:
            return None
        days.add(index)
    return frozenset(days) if days else None


def _day_index(token: str) -> Optional[int]:
    token = (token or "").strip().lower().replace("ё", "е")
    if not token:
        return None
    if token.isdigit():
        value = int(token)
        return value % 7 if 0 <= value <= 6 else None
    return _DAY_TOKENS.get(token)


def parse_window(raw: Any) -> Optional[Window]:
    """Build a :class:`Window` from a config mapping, or ``None`` when unparseable."""
    if isinstance(raw, str):
        raw = {"when": raw}
    if not isinstance(raw, Mapping):
        return None
    when = str(raw.get("when") or "").strip()
    name = str(raw.get("name") or when or "window").strip()
    note = str(raw.get("note") or "").strip()
    match = _WHEN_RE.match(when)
    if not match:
        return None
    start = _parse_minute(match.group("start"))
    end = _parse_minute(match.group("end"))
    days = parse_days(match.group("days") or "")
    if start is None or end is None or days is None:
        return None
    if start == end:  # a zero-length window is a configuration mistake, not "all day"
        return None
    return Window(name=name, days=days, start_minute=start, end_minute=end, when=when, note=note)


def parse_windows(raw: Any) -> list[Window]:
    """All valid windows out of a config value; malformed entries are skipped.

    Accepts a list of mappings, a list of ``when`` strings, or a mapping of
    ``name -> when`` (the shortest form a user can type by hand).
    """
    if isinstance(raw, Mapping):
        raw = [{"name": key, "when": value} for key, value in raw.items()]
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes)):
        return []
    windows: list[Window] = []
    for entry in raw:
        window = parse_window(entry)
        if window is not None:
            windows.append(window)
    return windows


def active_windows(windows: Sequence[Window], dt: datetime) -> list[Window]:
    return [window for window in windows if window.covers(dt)]


# ---------------------------------------------------------------------------
# Conversation-derived durations
# ---------------------------------------------------------------------------

def _timestamp(message: Any) -> Optional[float]:
    if not isinstance(message, Mapping):
        return None
    value = message.get("timestamp")
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


# A "session" older than this is stale metadata, not a session anyone is in.
_MAX_SESSION_SECONDS = 30 * 24 * 3600


def session_elapsed_seconds(messages: Sequence[Any], now: datetime,
                            first_seen: Optional[float] = None) -> Optional[float]:
    """Seconds since the session's first message (or since this process first saw it)."""
    first: Optional[float] = None
    for message in messages or ():
        stamp = _timestamp(message)
        if stamp is not None:
            first = stamp
            break
    if first is None:
        first = first_seen
    if first is None:
        return None
    elapsed = now.timestamp() - first
    return elapsed if 0 <= elapsed < _MAX_SESSION_SECONDS else None


def prior_turn_seconds(messages: Sequence[Any]) -> Optional[float]:
    """Duration of the previous turn, read from message timestamps.

    Measured as "last assistant row minus the user row that prompted it", which
    survives a gateway restart — no in-process bookkeeping needed.
    """
    if not messages:
        return None
    assistant_index: Optional[int] = None
    assistant_stamp: Optional[float] = None
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, Mapping) and message.get("role") == "assistant":
            stamp = _timestamp(message)
            if stamp is not None:
                assistant_index, assistant_stamp = index, stamp
                break
    if assistant_index is None or assistant_stamp is None:
        return None
    for index in range(assistant_index - 1, -1, -1):
        message = messages[index]
        if isinstance(message, Mapping) and message.get("role") == "user":
            stamp = _timestamp(message)
            if stamp is None:
                continue
            delta = assistant_stamp - stamp
            return delta if 0 <= delta < 12 * 3600 else None
    return None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

@dataclass
class ClockOptions:
    """Everything the renderer needs, resolved once per turn."""

    enabled: bool = True
    timezone: str = ""
    locale: str = "en"
    show_seconds: bool = True
    show_durations: bool = True
    show_stamp_note: bool = True
    windows: list[Window] = field(default_factory=list)

    def strings(self) -> dict[str, str]:
        return STRINGS.get(self.locale, STRINGS["en"])


def render_block(
    *,
    now: datetime,
    options: ClockOptions,
    session_seconds: Optional[float] = None,
    last_turn_seconds: Optional[float] = None,
) -> str:
    """The one-line block injected into the user message at turn start."""
    text = options.strings()
    head = f"[time-context] {text['now']}: {format_stamp(now, options.locale, show_seconds=options.show_seconds)}"

    zone = zone_label(now)
    offset = offset_label(now)
    zone_part = f"{offset} {zone}".strip() if zone else offset
    if zone_part:
        head += f" ({zone_part})"

    parts: list[str] = []
    if options.show_durations:
        if session_seconds is not None and session_seconds >= 60:
            parts.append(f"{text['session']} {format_duration(session_seconds, options.locale, show_seconds=options.show_seconds)}")
        if last_turn_seconds is not None and last_turn_seconds >= 1:
            parts.append(f"{text['last_turn']} {format_duration(last_turn_seconds, options.locale, show_seconds=options.show_seconds)}")
    if options.show_stamp_note:
        parts.append(text["stamp_note"])
    if parts:
        head += " · " + " · ".join(parts)

    lines = [head]
    for window in active_windows(options.windows, now):
        line = f"{text['window']}: {window.label()}"
        if window.note:
            line += f" — {window.note}"
        lines.append(line)
    return "\n".join(lines)


def render_payload(
    *,
    now: datetime,
    options: ClockOptions,
    session_seconds: Optional[float] = None,
    last_turn_seconds: Optional[float] = None,
) -> dict[str, Any]:
    """Machine-readable counterpart of :func:`render_block`, for the `now` tool."""
    return {
        "now": now.isoformat(),
        "unix": now.timestamp(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": weekday_name(now, options.locale),
        "weekday_index": now.weekday(),
        "timezone": offset_label(now),
        "timezone_name": zone_label(now),
        "clock_source": "system",
        "session_elapsed_seconds": None if session_seconds is None else round(session_seconds, 1),
        "last_turn_seconds": None if last_turn_seconds is None else round(last_turn_seconds, 1),
        "active_windows": [
            {"name": window.name, "when": window.when, "note": window.note}
            for window in active_windows(options.windows, now)
        ],
    }
