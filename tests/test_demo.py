"""The screen-recording demo must keep running, offline, with every section present."""

import importlib.util
import logging
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "demo.py"
_spec = importlib.util.spec_from_file_location("demo_script", _SCRIPT)
demo = importlib.util.module_from_spec(_spec)
sys.modules["demo_script"] = demo
_spec.loader.exec_module(demo)


def test_demo_runs_offline_and_shows_every_section(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["demo.py"])
    try:
        demo.main()
    finally:
        logging.disable(logging.NOTSET)
    out = capsys.readouterr().out
    for expected in [
        "1. Delivered parcel",
        '"status": "delivered"',
        "2. Returned parcel (RTO)",
        "refund hint: no_refund_due",
        "3. Failed delivery attempt",
        "Wait for the next delivery attempt, do not cancel",
        "4. Typed error",
        '"error": "NOT_FOUND"',
        "5. MCP tool",
        "refund hint: consider_refund",
        "is_suggestion: true",
    ]:
        assert expected in out, expected
