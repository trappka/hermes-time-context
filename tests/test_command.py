"""Chat-command and settings-surface tests. Run from the plugin root:
python -m unittest discover -s tests -v
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def _load_plugin():
    name = "time_context_cmd_test"
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN_DIR / "__init__.py", submodule_search_locations=[str(PLUGIN_DIR)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


plugin = _load_plugin()
clock = sys.modules[f"{plugin.__name__}.clock"]


class FakeCtx:
    """Host context slice, including the settings writer the command needs."""

    def __init__(self, settings=None, writable=True):
        self.settings = dict(settings or {})
        self.writable = writable
        self.written = []
        self.hooks = {}
        self.tools = {}
        self.commands = {}

    def get_config(self, key, default=None):
        return self.settings.get(key, default)

    def set_config(self, key, value):
        if not self.writable:
            raise PermissionError("managed install")
        self.written.append((key, value))
        self.settings[key] = value

    def register_hook(self, name, callback):
        self.hooks.setdefault(name, []).append(callback)

    def register_tool(self, name, toolset, schema, handler):
        self.tools[name] = {"handler": handler, "schema": schema, "toolset": toolset}

    def register_command(self, name, handler, description="", args_hint=""):
        self.commands[name] = handler


class CommandTests(unittest.TestCase):
    def setUp(self):
        plugin._STATE.clear()

    def ctx(self, **settings):
        base = {"locale": "ru", "windows": []}
        base.update(settings)
        ctx = FakeCtx(base)
        plugin.register(ctx)
        return ctx

    def run_cmd(self, ctx, args=""):
        return ctx.commands["time-context"](args)

    def test_registers_command(self):
        ctx = self.ctx()
        self.assertIn("time-context", ctx.commands)

    def test_status_shows_block(self):
        out = self.run_cmd(self.ctx())
        self.assertIn("[time-context] Сейчас:", out)
        self.assertIn("Активных окон нет", out)

    def test_help(self):
        out = self.run_cmd(self.ctx(), "help")
        self.assertIn("/time-context add", out)

    def test_add_then_list(self):
        ctx = self.ctx()
        out = self.run_cmd(ctx, "add School | Mon-Fri 08:30-15:10 | no deploy, no heavy builds")
        self.assertIn("сохранено", out)
        stored = ctx.settings["windows"]
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["name"], "School")
        listing = self.run_cmd(ctx, "windows")
        self.assertIn('"School" (Mon-Fri 08:30-15:10)', listing)
        self.assertIn("no deploy", listing)

    def test_add_replaces_same_name(self):
        ctx = self.ctx()
        self.run_cmd(ctx, "add Night | 23:00-08:00 | sleep")
        self.run_cmd(ctx, "add Night | 22:00-07:00 | sleep")
        self.assertEqual(len(ctx.settings["windows"]), 1)
        self.assertEqual(ctx.settings["windows"][0]["when"], "22:00-07:00")

    def test_add_rejects_bad_window(self):
        ctx = self.ctx()
        out = self.run_cmd(ctx, "add Soon | скоро | note")
        self.assertIn("Не понял окно", out)
        self.assertEqual(ctx.settings["windows"], [])

    def test_remove(self):
        ctx = self.ctx()
        self.run_cmd(ctx, "add Night | 23:00-08:00 | sleep")
        out = self.run_cmd(ctx, "remove night")
        self.assertIn("удалено", out)
        self.assertEqual(ctx.settings["windows"], [])

    def test_remove_missing(self):
        self.assertIn("нет", self.run_cmd(self.ctx(), "remove ghost"))

    def test_readonly_host_reports_honestly(self):
        base = {"locale": "ru", "windows": []}
        ctx = FakeCtx(base, writable=False)
        plugin.register(ctx)
        out = self.run_cmd(ctx, "add School | Mon-Fri 08:30-15:10 | busy")
        self.assertIn("config.yaml", out)

    def test_added_window_is_injected_next_turn(self):
        ctx = self.ctx()
        self.run_cmd(ctx, "add Night | 00:00-23:59 | owner may be asleep")
        result = ctx.hooks["pre_llm_call"][0](session_id="s", conversation_history=[])
        self.assertIn('Окно: "Night"', result["context"])


class SettingsParsingTests(unittest.TestCase):
    def test_windows_accept_mapping_form(self):
        windows = clock.parse_windows({"Night": "23:00-08:00"})
        self.assertEqual([w.name for w in windows], ["Night"])

    def test_windows_accept_plain_strings(self):
        windows = clock.parse_windows(["Mon-Fri 08:30-15:10"])
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].name, "Mon-Fri 08:30-15:10")

    def test_windows_tolerate_junk(self):
        self.assertEqual(clock.parse_windows(None), [])
        self.assertEqual(clock.parse_windows("daily 9-17"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
