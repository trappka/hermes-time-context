## What changed

<!-- One paragraph: what the change does and why. -->

## Checklist

- [ ] `python tests/test_time_context.py` and `python tests/test_command.py` pass
- [ ] `python scripts/check_manifest.py` passes
- [ ] `hermes plugins validate .` passes (run locally; CI cannot install Hermes)
- [ ] If a setting or surface changed: `plugin.yaml`, README and `CHANGELOG.md` updated together
- [ ] The block stays small — it is re-sent every turn and is not cached
- [ ] Nothing user-specific (names, timetables, timezones) leaked into docs or tests
