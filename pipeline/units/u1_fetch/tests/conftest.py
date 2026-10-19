"""Import bridge for U1 tests: puts the U0 src and U1 src on sys.path.

Follows the U0 tests (`sys.path.insert(0, str(SRC))` in test_preflight.py:17-18),
but U1 needs two paths:
  - U0_SRC = units/u0_foundation/src  -> makes `from common.schema import ...` /
    `from identity.golden import ...` visible (U1 reuses the U0 foundation, no copy).
  - U1_SRC = units/u1_fetch/src        -> makes `from m0_snapshot.xxx import ...` /
    `from m1_ingest.xxx import ...` visible.

The anchor does not count `parents` levels (error-prone): it anchors directly on the
`units` directory and appends relative paths, with an `assert .exists()` backstop
against path drift.
"""
import pathlib
import sys

_here = pathlib.Path(__file__).resolve()
_units = next(p for p in _here.parents if p.name == "units")

U0_SRC = _units / "u0_foundation" / "src"
U1_SRC = _units / "u1_fetch" / "src"

assert U0_SRC.exists(), f"U0 src not at the expected location: {U0_SRC}"
assert U1_SRC.exists(), f"U1 src not at the expected location: {U1_SRC}"

for _p in (str(U0_SRC), str(U1_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def pytest_configure(config):
    """Register the `slow` marker (real-data smoke tests): runs real shards with bounded RSS,
    does not block by default, and skips itself when the SSD is missing.

    No addopts deselection, so the normal suite still collects every test (slow real-data
    tests skip via skipif when the disk is missing).
    """
    config.addinivalue_line(
        "markers", "slow: 真数据/重 IO 冒烟 (需 4TB SSD 挂载; 缺盘自动 skip)"
    )


# Once the preflight environment gate is wired into the execute production path, that path
# really probes OPENALEX_API_KEY (one of the four gates). The test shell may not export it
# (the real value lives in the user's shell profile), so add a dummy when it is missing; the
# suite then does not depend on the shell environment. This affects the test process only and
# does not mask the gate itself: the gate's failure path has its own red test with explicit
# injection (monkeypatch PYARROW_LOCK).
import os      # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _openalex_key_for_env_gate(monkeypatch):
    if not os.environ.get("OPENALEX_API_KEY"):
        monkeypatch.setenv("OPENALEX_API_KEY", "test-key-env-gate")
