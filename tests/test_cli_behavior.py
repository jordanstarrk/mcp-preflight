from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from conftest import TOY_DIR


def test_cli_save_writes_json_report() -> None:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "report.json"
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "mcp_preflight",
                "--json",
                "--save",
                str(out),
                sys.executable,
                str(TOY_DIR / "toy_open.py"),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        assert proc.stdout.strip()
        assert out.exists()
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["server"]["name"] == "toy-open"


def test_cli_no_signals_disables_signal_output_in_json() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "mcp_preflight",
            "--json",
            "--no-signals",
            sys.executable,
            str(TOY_DIR / "toy_open.py"),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    report = json.loads(proc.stdout)
    assert report["signals"] == []


def test_cli_env_requires_key_value() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "mcp_preflight", "--env", "NOT_KEY_VALUE", sys.executable, str(TOY_DIR / "toy_open.py")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.returncode != 0
    assert "--env must be KEY=VALUE" in (proc.stderr + proc.stdout)


def test_cli_diff_subcommand_prints_diff() -> None:
    before = {"server": {"name": "s"}, "risk": {"write": 0, "destructive": 0, "read": 0}, "tools": [], "resources": [], "resourceTemplates": [], "prompts": []}
    after = {"server": {"name": "s"}, "risk": {"write": 1, "destructive": 0, "read": 0}, "tools": [{"name": "t", "risk": "write"}], "resources": [], "resourceTemplates": [], "prompts": []}

    with tempfile.TemporaryDirectory() as td:
        b = Path(td) / "before.json"
        a = Path(td) / "after.json"
        b.write_text(json.dumps(before), encoding="utf-8")
        a.write_text(json.dumps(after), encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, "-m", "mcp_preflight", "diff", str(b), str(a)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        assert "Diff" in proc.stdout
        assert "+ t (write)" in proc.stdout

