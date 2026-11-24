#!/usr/bin/env python3
"""Check plugin.yaml against the code it describes — the part of the catalog gate CI can run
without installing Hermes.

Verifies: required fields, a valid plugin name, that every declared tool and hook is actually
registered, and that every ``config_schema`` key is read through ``ctx.get_config``. Exits non-zero
with one line per problem.

    python scripts/check_manifest.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "plugin.yaml"
SOURCE = ROOT / "__init__.py"

REQUIRED = ("name", "version", "description", "license", "requires_hermes")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def main() -> int:
    problems: list[str] = []
    try:
        manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        print(f"plugin.yaml does not parse: {exc}")
        return 1
    if not isinstance(manifest, dict):
        print("plugin.yaml is not a mapping")
        return 1

    for key in REQUIRED:
        if not manifest.get(key):
            problems.append(f"missing required field: {key}")

    name = str(manifest.get("name") or "")
    if name and not NAME_RE.match(name):
        problems.append(f"name {name!r} must match {NAME_RE.pattern}")

    source = SOURCE.read_text(encoding="utf-8")
    registered_tools = set(re.findall(r'register_tool\(\s*name="([^"]+)"', source))
    registered_hooks = set(re.findall(r'register_hook\("([^"]+)"', source))
    declared_tools = set(manifest.get("provides_tools") or [])
    declared_hooks = set(manifest.get("provides_hooks") or [])

    for missing in sorted(registered_tools - declared_tools):
        problems.append(f"tool {missing!r} is registered but not declared in provides_tools")
    for phantom in sorted(declared_tools - registered_tools):
        problems.append(f"tool {phantom!r} is declared but never registered")
    for missing in sorted(registered_hooks - declared_hooks):
        problems.append(f"hook {missing!r} is registered but not declared in provides_hooks")
    for phantom in sorted(declared_hooks - registered_hooks):
        problems.append(f"hook {phantom!r} is declared but never registered")

    schema = manifest.get("config_schema") or {}
    if not isinstance(schema, dict):
        problems.append("config_schema must be a mapping")
        schema = {}
    for key in schema:
        if f'"{key}"' not in source:
            problems.append(f"config_schema key {key!r} is never read by the code")

    if problems:
        for problem in problems:
            print(f"FAIL: {problem}")
        return 1
    print(f"OK: {name} {manifest.get('version')} · "
          f"{len(registered_tools)} tool(s), {len(registered_hooks)} hook(s), "
          f"{len(schema)} setting(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
