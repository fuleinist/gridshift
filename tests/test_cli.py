from __future__ import annotations

from gridshift.cli import main


def test_demo_command_runs_offline():
    assert main(["demo", "--hours", "6"]) == 0


def test_loads_command_runs():
    assert main(["loads"]) == 0


def test_plan_rejects_bad_weight():
    assert main(["demo", "--carbon-weight", "0", "--price-weight", "0"]) == 1