"""Unit tests for time-context. Run: python -m unittest discover -s tests -v"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def _load_plugin():
    """Import the plugin directory as a package (its name has a dash, so no plain import)."""
    name = "time_context_under_test"
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN_DIR / "__init__.py", submodule_search_locations=[str(PLUGIN_DIR)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


plugin = _load_plugin()
clock = sys.modules[f"{plugin.__name__}.clock"]

TZ = timezone(timedelta(hours=3))


def at(year: int, month: int, day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=TZ)


class FakeCtx:
    """The slice of the host plugin context this plugin actually touches."""

    def __init__(self, settings=None):
        self.settings = dict(settings or {})
        self.hooks = {}
        self.tools = {}
        self.commands = {}

    def get_config(self, key, default=None):
        return self.settings.get(key, default)

    def register_hook(self, name, callback):
        self.hooks.setdefault(name, []).append(callback)

    def register_tool(self, name, toolset, schema, handler):
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler}

    def register_command(self, name, handler, description="", args_hint=""):
        self.commands[name] = handler


class FormatTests(unittest.TestCase):
    def test_stamp_english(self):
        self.assertEqual(clock.format_stamp(at(2026, 11, 24, 18, 28, 11), "en"),
                         "Tue 24 Nov 2026, 18:28:11")

    def test_stamp_russian(self):
        self.assertEqual(clock.format_stamp(at(2026, 11, 24, 18, 28, 11), "ru"),
                         "вт, 24 ноября 2026, 18:28:11")

    def test_offset_label(self):
        self.assertEqual(clock.offset_label(at(2026, 11, 24, 18, 0)), "+03:00")

    def test_durations(self):
        self.assertEqual(clock.format_duration(45, "en"), "45 s")
        self.assertEqual(clock.format_duration(278, "en"), "4 m 38 s")
        self.assertEqual(clock.format_duration(4331, "en"), "1 h 12 m 11 s")
        self.assertEqual(clock.format_duration(4331, "ru"), "1 ч 12 м 11 с")
        self.assertEqual(clock.format_duration(278, "ru", show_seconds=False), "4 м")
        self.assertEqual(clock.format_duration(None, "en"), "")

    def test_duration_never_negative(self):
        self.assertEqual(clock.format_duration(-500, "en"), "0 s")


class DayParsingTests(unittest.TestCase):
    def test_english_range(self):
        self.assertEqual(clock.parse_days("Mon-Fri"), frozenset({0, 1, 2, 3, 4}))

    def test_russian_range(self):
        self.assertEqual(clock.parse_days("пн-пт"), frozenset({0, 1, 2, 3, 4}))

    def test_list(self):
        self.assertEqual(clock.parse_days("sat,sun"), frozenset({5, 6}))

    def test_daily_tokens(self):
        self.assertEqual(clock.parse_days("ежедневно"), frozenset(range(7)))
        self.assertEqual(clock.parse_days("*"), frozenset(range(7)))

    def test_wrapping_range(self):
        self.assertEqual(clock.parse_days("sat-tue"), frozenset({5, 6, 0, 1}))

    def test_numeric(self):
        self.assertEqual(clock.parse_days("0-4"), frozenset({0, 1, 2, 3, 4}))

    def test_garbage_is_rejected(self):
        self.assertIsNone(clock.parse_days("когда-нибудь"))

    def test_empty_defaults_to_weekdays(self):
        self.assertEqual(clock.parse_days(""), frozenset({0, 1, 2, 3, 4}))


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.office = clock.parse_window({
            "name": "office",
            "when": "Mon-Fri 09:00-18:00",
            "note": "busy",
        })

    def test_parse(self):
        self.assertIsNotNone(self.office)
        self.assertEqual(self.office.start_minute, 9 * 60)
        self.assertEqual(self.office.end_minute, 18 * 60)

    def test_inside_on_weekday(self):
        self.assertTrue(self.office.covers(at(2026, 11, 24, 10, 0)))  # Tuesday

    def test_outside_before_start(self):
        self.assertFalse(self.office.covers(at(2026, 11, 24, 8, 59)))

    def test_end_is_exclusive(self):
        self.assertFalse(self.office.covers(at(2026, 11, 24, 18, 0)))

    def test_weekend_is_outside(self):
        self.assertFalse(self.office.covers(at(2026, 11, 28, 10, 0)))  # Saturday

    def test_midnight_wrap_belongs_to_start_day(self):
        night = clock.parse_window({"name": "night", "when": "23:00-08:00"})
        self.assertTrue(night.covers(at(2026, 11, 24, 23, 30)))
        self.assertTrue(night.covers(at(2026, 11, 25, 1, 0)))    # started on the 24th
        self.assertFalse(night.covers(at(2026, 11, 25, 12, 0)))

    def test_friday_night_does_not_cover_saturday_evening(self):
        night = clock.parse_window({"name": "night", "when": "Fri 23:00-08:00"})
        self.assertTrue(night.covers(at(2026, 11, 27, 23, 30)))  # Friday evening
        self.assertTrue(night.covers(at(2026, 11, 28, 7, 0)))    # Saturday morning
        self.assertFalse(night.covers(at(2026, 11, 28, 23, 30)))  # Saturday evening: not Friday-started

    def test_malformed_windows_are_skipped(self):
        self.assertIsNone(clock.parse_window({"when": "скоро"}))
        self.assertIsNone(clock.parse_window({"when": "08:00-08:00"}))

    def test_hour_only_syntax(self):
        window = clock.parse_window({"when": "daily 9-17"})
        self.assertEqual((window.start_minute, window.end_minute), (540, 1020))

    def test_parse_windows_ignores_noise(self):
        windows = clock.parse_windows([{"when": "Mon-Fri 09:00-18:00"}, "мусор", 42, None])
        self.assertEqual(len(windows), 1)


class MeasurementTests(unittest.TestCase):
    def test_prior_turn_from_timestamps(self):
        base = at(2026, 11, 24, 18, 0).timestamp()
        messages = [
            {"role": "user", "timestamp": base},
            {"role": "assistant", "timestamp": base + 278},
            {"role": "user", "timestamp": base + 400},
        ]
        self.assertAlmostEqual(clock.prior_turn_seconds(messages), 278.0)

    def test_prior_turn_without_assistant(self):
        base = at(2026, 11, 24, 18, 0).timestamp()
        self.assertIsNone(clock.prior_turn_seconds([{"role": "user", "timestamp": base}]))

    def test_prior_turn_rejects_absurd_gap(self):
        base = at(2026, 11, 24, 18, 0).timestamp()
        messages = [
            {"role": "user", "timestamp": base},
            {"role": "assistant", "timestamp": base + 40 * 3600},
        ]
        self.assertIsNone(clock.prior_turn_seconds(messages))

    def test_session_elapsed(self):
        base = at(2026, 11, 24, 17, 0).timestamp()
        now = at(2026, 11, 24, 18, 0)
        messages = [{"role": "user", "timestamp": base}]
        self.assertAlmostEqual(clock.session_elapsed_seconds(messages, now), 3600.0)


class RenderTests(unittest.TestCase):
    def options(self, **overrides):
        defaults = dict(
            locale="ru",
            windows=clock.parse_windows([
                {"name": "ночь", "when": "23:00-08:00", "note": "владелец, вероятно, спит"},
            ]),
        )
        defaults.update(overrides)
        return clock.ClockOptions(**defaults)

    def test_block_has_clock_and_note(self):
        block = clock.render_block(
            now=at(2026, 11, 24, 23, 30),
            options=self.options(),
            session_seconds=4331,
            last_turn_seconds=278,
        )
        self.assertIn("[time-context] Сейчас: вт, 24 ноября 2026, 23:30:00 (+03:00", block)
        self.assertIn("сессия 1 ч 12 м 11 с", block)
        self.assertIn("прошлый ход 4 м 38 с", block)
        self.assertIn("время на начало хода", block)
        self.assertIn('Окно: "ночь" (23:00-08:00) — владелец, вероятно, спит', block)
        self.assertEqual(len(block.splitlines()), 2)

    def test_no_windows_no_extra_line(self):
        block = clock.render_block(now=at(2026, 11, 24, 12, 0), options=self.options())
        self.assertEqual(len(block.splitlines()), 1)

    def test_durations_can_be_hidden(self):
        block = clock.render_block(
            now=at(2026, 11, 24, 12, 0),
            options=self.options(show_durations=False),
            session_seconds=9999,
            last_turn_seconds=999,
        )
        self.assertNotIn("сессия", block)

    def test_english_block(self):
        block = clock.render_block(
            now=at(2026, 11, 24, 18, 28),
            options=self.options(locale="en", windows=[]),
            session_seconds=4331,
            last_turn_seconds=278,
        )
        self.assertIn("Now: Tue 24 Nov 2026, 18:28:", block)
        self.assertIn("last turn 4 m 38 s", block)

    def test_tokens_are_cheap(self):
        """The block must stay small: it is re-sent every turn, uncached."""
        block = clock.render_block(
            now=at(2026, 11, 24, 23, 30),
            options=self.options(),
            session_seconds=4331,
            last_turn_seconds=278,
        )
        self.assertLess(len(block), 300, block)

    def test_payload_shape(self):
        payload = clock.render_payload(
            now=at(2026, 11, 24, 23, 30),
            options=self.options(),
            session_seconds=60,
            last_turn_seconds=5,
        )
        self.assertEqual(payload["date"], "2026-11-24")
        self.assertEqual(payload["weekday"], "вторник")
        self.assertEqual(payload["timezone"], "+03:00")
        self.assertEqual([w["name"] for w in payload["active_windows"]], ["ночь"])


class PluginWiringTests(unittest.TestCase):
    def test_registers_hooks_and_tool(self):
        ctx = FakeCtx()
        plugin.register(ctx)
        self.assertIn("pre_llm_call", ctx.hooks)
        self.assertIn("post_llm_call", ctx.hooks)
        self.assertIn("now", ctx.tools)
        self.assertEqual(ctx.tools["now"]["toolset"], "time_context")

    def test_pre_llm_call_injects_context(self):
        ctx = FakeCtx({"locale": "en", "windows": [{"name": "night", "when": "23:00-08:00"}]})
        plugin.register(ctx)
        hook = ctx.hooks["pre_llm_call"][0]
        result = hook(session_id="s1", conversation_history=[])
        self.assertIsInstance(result, dict)
        self.assertIn("[time-context] Now:", result["context"])

    def test_disabled_plugin_injects_nothing(self):
        ctx = FakeCtx({"enabled": False})
        plugin.register(ctx)
        hook = ctx.hooks["pre_llm_call"][0]
        self.assertIsNone(hook(session_id="s2", conversation_history=[]))

    def test_turn_duration_is_measured(self):
        ctx = FakeCtx({"locale": "en"})
        plugin.register(ctx)
        pre, post = ctx.hooks["pre_llm_call"][0], ctx.hooks["post_llm_call"][0]
        pre(session_id="s3", conversation_history=[])
        post(session_id="s3")
        state = plugin._STATE["s3"]
        self.assertIn("last_turn_seconds", state)
        self.assertGreaterEqual(state["last_turn_seconds"], 0)

    def test_now_tool_returns_json(self):
        import json
        ctx = FakeCtx({"locale": "en"})
        plugin.register(ctx)
        payload = json.loads(ctx.tools["now"]["handler"]({}))
        self.assertTrue(payload["success"])
        self.assertIn("now", payload)
        self.assertEqual(payload["clock_source"], "system")

    def test_broken_settings_do_not_raise(self):
        class Broken(FakeCtx):
            def get_config(self, key, default=None):
                raise RuntimeError("registry down")

        ctx = Broken()
        plugin.register(ctx)
        # Fail-open with defaults: a broken settings registry must not silence the clock.
        result = ctx.hooks["pre_llm_call"][0](session_id="s4", conversation_history=[])
        self.assertIsInstance(result, dict)
        self.assertIn("[time-context]", result["context"])

    def test_state_is_bounded(self):
        plugin._STATE.clear()
        for index in range(plugin._MAX_SESSIONS + 20):
            plugin._session_state(f"session-{index}")
        self.assertLessEqual(len(plugin._STATE), plugin._MAX_SESSIONS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
