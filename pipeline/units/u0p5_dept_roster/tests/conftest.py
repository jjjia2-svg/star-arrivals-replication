"""Import bridge for the U0.5 tests: puts U0 src and U0.5 src on sys.path.

Follows the U1 tests (units/u1_fetch/tests/conftest.py:16-27, anchor-by-`units` + assert);
this unit adds two paths as well:
  - U0_SRC = units/u0_foundation/src  -> makes `from common.schema import ...` /
    `from common.inst_lineage import ...` / `from identity.golden import ...` visible
    (U0.5 reuses the U0 foundation, no copy).
  - U0P5_SRC = units/u0p5_dept_roster/src -> makes `from roster.xxx import ...` visible.

The anchor does not count `parents` levels (error-prone): it anchors on the `units` directory and appends
the relative path, with an `assert .exists()` guard against path drift (same style as the U1 conftest).
"""
import pathlib
import sys

_here = pathlib.Path(__file__).resolve()
_units = next(p for p in _here.parents if p.name == "units")

U0_SRC = _units / "u0_foundation" / "src"
U0P5_SRC = _units / "u0p5_dept_roster" / "src"

assert U0_SRC.exists(), f"U0 src not at the expected location: {U0_SRC}"
assert U0P5_SRC.exists(), f"U0.5 src not at the expected location: {U0P5_SRC}"

for _p in (str(U0_SRC), str(U0P5_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# --run-live: explicit switch; only then do tests that hit the real OpenAlex API (@pytest.mark.live) run.
# Skipped by default -> offline TDD needs no network/quota; in a smoke run `pytest --run-live` checks that Yves Zenou maps to A5017376589.
# ---------------------------------------------------------------------------
import pytest  # noqa: E402


def pytest_addoption(parser):
    parser.addoption(
        "--run-live", action="store_true", default=False,
        help="Run live tests that hit the real OpenAlex API (skipped by default).",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "live: 打真 OpenAlex API (需 --run-live + OPENALEX_API_KEY)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-live"):
        return
    skip_live = pytest.mark.skip(reason="needs --run-live to enable (default: no real API calls)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
