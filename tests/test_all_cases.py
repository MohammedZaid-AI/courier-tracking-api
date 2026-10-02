"""Runs scripts/run_all_cases.py inside pytest so CI fails if any case regresses."""

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "run_all_cases.py"
_spec = importlib.util.spec_from_file_location("run_all_cases", _SCRIPT)
run_all_cases = importlib.util.module_from_spec(_spec)
sys.modules["run_all_cases"] = run_all_cases  # @dataclass looks its module up here
_spec.loader.exec_module(run_all_cases)

REQUIRED = {"delivered", "in transit", "returned to origin (COD)", "invalid ID (unknown)", "site down"}


def test_every_courier_covers_the_required_cases():
    from courier_tracking.service import COURIERS

    for courier in COURIERS:
        names = {c.name for c in run_all_cases.CASES if c.courier == courier}
        assert REQUIRED <= names, courier


@pytest.mark.parametrize("case", run_all_cases.CASES, ids=lambda c: f"{c.courier}-{c.name}")
async def test_case(case):
    ok, detail = await run_all_cases.run_case(case)
    assert ok, detail
