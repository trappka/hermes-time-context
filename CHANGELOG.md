# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] — 2026-11-24

### Added

- GitHub Actions CI: both test suites on Python 3.10–3.13 plus `hermes plugins validate`.
- Issue and pull-request templates.
- Repository banner and rendered example frames.

### Changed

- README rebuilt around the actual output, with install, settings and limits in one pass.
- Repository topics and manifest tags widened so the plugin is findable by search.

## [0.2.1] — 2026-11-24

### Changed

- Chat command replies are localized by `locale` instead of hardcoded Russian.
- Documentation, manifest and tests use neutral examples (office hours, night) rather than any
  one user's timetable.

## [0.2.0] — 2026-11-24

### Added

- `/time-context` command: show the block, list windows, add or remove one.
- Window management persisted through the host settings writer.

### Changed

- Manifest declares labels, descriptions and `choices` for the settings form.

## [0.1.0] — 2026-11-24

### Added

- `pre_llm_call` injection of date, time, UTC offset, session age and previous turn length.
- Named time windows with notes, including ranges that wrap midnight.
- `post_llm_call` turn-duration measurement and the `now` tool.
- 40 unit tests; `hermes plugins validate` passes.

[0.3.0]: https://github.com/trappka/hermes-time-context/releases/tag/v0.3.0
[0.2.1]: https://github.com/trappka/hermes-time-context/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/trappka/hermes-time-context/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/trappka/hermes-time-context/releases/tag/v0.1.0
