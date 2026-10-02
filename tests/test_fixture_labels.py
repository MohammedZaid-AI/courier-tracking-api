"""Every fixture must say whether it is real (live capture) or synthetic (hand-built)."""

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
FILES = sorted(p for p in FIXTURES.rglob("*") if p.is_file() and p.name != "README.md")
INDEX = (FIXTURES / "README.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(FIXTURES)))
def test_fixture_is_labelled_live_or_synthetic(path):
    labels = {part for part in path.name.split(".") if part in {"live", "synthetic"}}
    assert len(labels) == 1, f"{path.name} must contain exactly one of .live. or .synthetic."
    assert f"`{path.parent.name}/{path.name}`" in INDEX, f"{path.name} is not listed in tests/fixtures/README.md"


@pytest.mark.parametrize(
    "path", [p for p in FILES if ".synthetic." in p.name and p.suffix == ".html"], ids=lambda p: p.name
)
def test_synthetic_html_starts_with_a_synthetic_comment(path):
    assert path.read_text(encoding="utf-8").startswith("<!-- SYNTHETIC FIXTURE")
