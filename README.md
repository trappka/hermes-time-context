# time-context

A Hermes Agent plugin that tells the model **what time it is**.

Hermes stamps the *session start* into the system prompt and nothing else. Ask an
agent "is it a good moment to deploy?" at 22:40 and it has no idea — it guesses,
or it spends a tool call on `date`. This plugin puts a one-line, always-fresh
clock reading into every turn, together with the two durations a model cannot
feel on its own: how long the session has been running and how long the previous
turn actually took.

```
[time-context] Now: Tue 24 Nov 2026, 22:14:07 (+01:00 Europe/Berlin) · session 1 h 12 m · last turn 4 m 38 s · reading taken at turn start
Window: "Work hours" (Mon-Fri 09:00-18:00) — office hours: no deploys while people are around
```

## Why not a file in the system prompt

A `time.md` pasted into the system prompt has two problems: it freezes at session
start, and it **breaks the prompt cache** — the system prompt is meant to be
byte-stable across a session, so a changing line there makes the provider rewrite
the whole prefix every turn.

Hermes has a purpose-built slot for per-turn text: `pre_llm_call` returns
`{"context": ...}` and the host appends it to the **current user message** at API
time (`agent/turn_context.py`), leaving the system prompt and every earlier
message byte-identical. So the clock rides the tail: cache-safe by construction,
refreshed every turn.

## What you get

| Surface | What it does |
|---|---|
| turn context | one line with date, weekday, time, offset, session age, previous turn length |
| active windows | every configured window that is active right now, with its note |
| `now` tool | exact reading on demand: ISO time, epoch, weekday, durations, active windows |
| `/time-context` | inspect the block; `add` / `remove` / `windows` to manage windows from chat |

## Windows: the part that changes behaviour

A clock is data. Decisions are made on **intervals**. Windows let you describe
your own schedule — class hours, quiet hours, night, a maintenance slot — and
attach the rule the agent should follow inside them:

```yaml
plugins:
  entries:
    time-context:
      settings:
        locale: ru
        timezone: Europe/Berlin
        windows:
          - name: Рабочие часы
            when: "пн-пт 09:00-18:00"
            note: "люди на работе: деплой и тяжёлые сборки лучше отложить"
          - name: Ночь
            when: "23:00-08:00"
            note: "владелец, вероятно, спит: не задавай вопросов, решай и отчитывайся утром"
```

`when` accepts `Mon-Fri` / `пн-пт` / `sat,sun` / `daily` / `0-4`, English or
Russian day names, and one time range. A range that wraps midnight
(`23:00-08:00`) belongs to the day it starts on, so it covers the early morning.

Windows are pure configuration: nothing about work hours, night or quiet time is
hardcoded. A new project or a new timetable is a new entry, not a code change.

## Install

```bash
hermes plugins install trappka/hermes-time-context
hermes config set plugins.entries.time-context.settings.locale ru
hermes config set plugins.entries.time-context.settings.timezone Europe/Berlin
```

Or drop the directory into `~/.hermes/plugins/time-context/` and restart Hermes.

Manage windows from chat:

```
/time-context
/time-context add Office | Mon-Fri 09:00-18:00 | no deploys while people work
/time-context windows
/time-context remove Office
```

## Settings

Everything the host can render in the Desktop/Dashboard settings form is declared
in `plugin.yaml` under `config_schema`.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | bool | `true` | Inject the block at turn start |
| `locale` | str (`en`/`ru`) | `en` | Language of the block and of weekday/month names |
| `timezone` | str | machine zone | IANA zone, e.g. `Europe/Berlin` |
| `show_seconds` | bool | `true` | Seconds in the clock reading |
| `show_durations` | bool | `true` | Session age and previous turn length |
| `show_stamp_note` | bool | `true` | "reading taken at turn start" hint |
| `windows` | list | `[]` | Named intervals with notes |

**What fits in `config_schema`:** `str`, `int`, `float`, `bool`, `list`, `dict`,
`secret` (stored in `.env`, never `config.yaml`), plus `default`, `required`,
`label`, `description`, and `choices` — `choices` on a `str` field renders as a
dropdown. A `list`/`dict` field is edited as JSON in the form.

**What does not:** there is no nested schema, no per-element validation of a
list, no cross-field dependencies, and no hot-reload of code. Window entries are
validated by the plugin itself, malformed ones are skipped rather than raising.

Settings are read through `ctx.get_config` on every turn, so changes apply on the
next turn without restarting anything.

## Cost

The block is ~30 tokens per turn and sits in the uncached tail. The `now` tool
adds its schema once per session. In exchange the agent stops calling `date`
(another round-trip, 200–500 tokens) to answer "can I do this now?".

## What it deliberately does not do

- Does not touch the system prompt (cache safety).
- Does not rewrite history or tool results.
- Does not block actions — time is information, not a gate. Use `pre_tool_call`
  policies when you need a hard stop.
- Does not reach the network. It reports the machine clock and says so
  (`clock_source: system`); if your host clock drifts, so does the reading.

## Development

```bash
python tests/test_time_context.py
python tests/test_command.py
hermes plugins validate .
```

No third-party dependencies; Python standard library only.

## License

MIT
