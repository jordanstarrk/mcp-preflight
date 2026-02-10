#!/usr/bin/env python3
"""
Run mcp-preflight against each toy server and display the results.

Usage:
  uv run python tests/show_outputs.py          # text output (default)
  uv run python tests/show_outputs.py --json   # JSON output
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOY_DIR = ROOT / "tests" / "toy_servers"

# Each entry: (label, server script, extra mcp-preflight args, extra env)
SCENARIOS: list[tuple[str, str, list[str], dict[str, str]]] = [
    (
        "Open server (tools + resources + prompts)",
        "toy_open.py",
        [],
        {},
    ),
    (
        "Tools-only server (no resources/prompts capability)",
        "toy_tools_only.py",
        [],
        {},
    ),
    (
        "Auth-gated server (no token → auth_gated)",
        "toy_auth_gated.py",
        [],
        {},
    ),
    (
        "Auth-gated server (with token → ok)",
        "toy_auth_gated.py",
        ["--env", "TOY_TOKEN=ok"],
        {},
    ),
    (
        "Auth crash server (startup failure)",
        "toy_auth_crash.py",
        [],
        {},
    ),
    (
        "Partial resources (list_resources times out)",
        "toy_partial_resources.py",
        ["--timeout", "0.8"],
        {},
    ),
    (
        "Stderr-chatty server (default — stderr suppressed)",
        "toy_stderr_chatty.py",
        [],
        {},
    ),
    (
        "Stderr-chatty server (--verbose — stderr shown)",
        "toy_stderr_chatty.py",
        ["--verbose"],
        {},
    ),
    (
        "CWD-aware server (default cwd)",
        "toy_cwd_aware.py",
        [],
        {},
    ),
    (
        "CWD-aware server (--cwd /tmp)",
        "toy_cwd_aware.py",
        ["--cwd", "/tmp"],
        {},
    ),
    (
        "Env-aware server (no TOY_ENV_VAL → unset)",
        "toy_env_aware.py",
        [],
        {},
    ),
    (
        "Env-aware server (--env TOY_ENV_VAL=hello)",
        "toy_env_aware.py",
        ["--env", "TOY_ENV_VAL=hello"],
        {},
    ),
    (
        "Home-aware server (default HOME)",
        "toy_home_aware.py",
        [],
        {},
    ),
    (
        "Home-aware server (--isolate-home)",
        "toy_home_aware.py",
        ["--isolate-home"],
        {},
    ),
]


def main() -> None:
    use_json = "--json" in sys.argv[1:]
    extra_flags = ["--json"] if use_json else []
    separator = "─" * 72

    for label, script, args, env in SCENARIOS:
        server_path = str(TOY_DIR / script)
        cmd = [
            sys.executable, "-m", "mcp_preflight",
            *extra_flags,
            *args,
            sys.executable, server_path,
        ]

        print(f"\n{separator}")
        print(f"  {label}")
        print(f"  cmd: mcp-preflight {' '.join(extra_flags + args)} python {script}")
        print(separator)

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**dict(__import__("os").environ), **env} if env else None,
        )

        has_stdout = bool(result.stdout.strip())
        has_stderr = bool(result.stderr.strip())

        if has_stdout:
            # Primary output — show as-is.
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")

        if has_stderr and has_stdout:
            # Stderr alongside normal output — label it so it's distinguishable.
            for line in result.stderr.strip().splitlines():
                print(f"  [stderr] {line}")
            print()
        elif has_stderr:
            # Stderr is the *only* output (e.g. crash) — show it directly, no prefix.
            for line in result.stderr.strip().splitlines():
                print(f"  {line}")
            print()

        if result.returncode != 0:
            print(f"  exit code {result.returncode}\n")

    print(separator)
    print(f"  {len(SCENARIOS)} scenarios complete.")
    print(separator)


if __name__ == "__main__":
    main()
