# Contributing

Small plugin, small rules.

## What is welcome

- Bug reports with the exact block the agent saw (`/time-context` prints it).
- New locales. Two are wired today (`en`, `ru`); adding one is a `STRINGS` entry in
  `clock.py` plus a test that asserts one line of each surface.
- New time-range syntaxes, as long as a malformed entry still degrades to "skipped", never to
  a crash or a wrong active window.
- Documentation fixes, especially an example where the math does not add up.

## What is out of scope

- Anything that puts a changing value into the system prompt. That breaks the prompt cache and
  is the one design constraint this plugin exists to respect.
- Blocking or gating actions. The plugin reports time; policy belongs in a `pre_tool_call` hook.
- Network calls, subprocesses, credentials.
- Per-user defaults baked into the code. Timetables, timezones and wording belong in
  `config.yaml`, not in the source.

## Before opening a pull request

```bash
python tests/test_time_context.py
python tests/test_command.py
python scripts/check_manifest.py
hermes plugins validate .
```

All four must pass. If you changed a setting, a surface or the rendered text, update
`plugin.yaml`, `README.md` and `CHANGELOG.md` in the same change.

## Testing a hook locally

`hermes chat -q` and `-z` **do not load plugins** (by design), so they cannot verify a hook. Use
an interactive session — `hermes`, TUI, Desktop or Telegram — then ask the model to quote the
`[time-context]` line it received. If the line is there, the path works.

## Style

Standard library only. No dependencies. Every public function gets a docstring that says why it
exists, not what it looks like. Comments explain decisions, not syntax.
