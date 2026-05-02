"""Test CLI."""

import json
import subprocess
import sys
from pathlib import Path


def run_vending(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "vending",
            "--config",
            str(tmp_path / "config.toml"),
            "--state-file",
            str(tmp_path / "state.json"),
            *args,
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_simulate_smoke(tmp_path: Path) -> None:
    completed = run_vending(
        tmp_path, "simulate", "--customers", "5", "--seed", "42", "--format", "json"
    )

    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["customers"] == 5
    assert summary["seed"] == 42
    assert "outcomes" in summary


def test_cli_audit_smoke(tmp_path: Path) -> None:
    run_vending(tmp_path, "simulate", "--customers", "2", "--seed", "7")
    completed = run_vending(tmp_path, "audit")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "ok: True" in completed.stdout
