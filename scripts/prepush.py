"""Pre-push checklist: runs the automatic checks, then lists what must be done by hand.

    python scripts/prepush.py

Offline only. It never calls a courier site and never pushes.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from courier_tracking.http import DEFAULT_CONTACT  # noqa: E402

AUTOMATIC = [
    ("Tests pass (incl. fixture secret/PII scan, offline guard)", [sys.executable, "-m", "pytest", "-q"]),
    ("All-cases script: every case passes", [sys.executable, "scripts/run_all_cases.py"]),
    ("Drift check against saved fixtures", [sys.executable, "-m", "courier_tracking.drift"]),
]

MANUAL = [
    (
        "Run the live drift check once",
        "python -m courier_tracking.drift --live\n"
        "Expect OK or WARN for every line. DRIFT means a page changed; UNREACHABLE means a site was down.",
    ),
    (
        "Add a real Trackon tracking ID (your own shipment)",
        "python -m courier_tracking.drift --live --id trackon=<AWB> --save\n"
        "Then redact names, phone numbers and addresses in .drift/trackon/*.html and send it over: the parser\n"
        "gets fixed and the synthetic Trackon fixtures get replaced.",
    ),
    (
        "Check the User-Agent contact URL",
        f"The default is {DEFAULT_CONTACT}\n"
        "If your GitHub repo has a different name, edit DEFAULT_CONTACT in courier_tracking/http.py.",
    ),
    (
        "Push to GitHub",
        "Create an EMPTY repo on GitHub (no README, licence or .gitignore), then:\n"
        "git remote add origin https://github.com/<you>/<repo>.git\n"
        "git push -u origin main\n"
        "(History was rewritten before the first push, so no force push is needed.)",
    ),
    (
        "Check CI",
        "GitHub > Actions > 'tests' must be green on Python 3.12. Also confirm the push was not blocked by\n"
        "GitHub secret scanning.",
    ),
]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def main() -> int:
    print("Automatic checks")
    print("-" * 60)
    failed = 0
    dirty = git("status", "--porcelain")
    print(f"[{'PASS' if not dirty else 'FAIL'}] Working tree is clean (everything committed)")
    failed += bool(dirty)
    for label, cmd in AUTOMATIC:
        ok = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True).returncode == 0
        failed += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
    remote = git("remote", "-v")
    print(f"[INFO] Git remote: {remote.splitlines()[0] if remote else 'none yet (expected before first push)'}")
    print(f"[INFO] Branch: {git('branch', '--show-current')}, {git('rev-list', '--count', 'HEAD')} commits")

    print("\nBy hand, in this order")
    print("-" * 60)
    for i, (title, how) in enumerate(MANUAL, 1):
        print(f"[ ] {i}. {title}")
        for line in how.splitlines():
            print(f"       {line}")
    print()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
