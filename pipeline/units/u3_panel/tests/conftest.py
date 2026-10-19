"""Import bridge for the U3 tests - injects the U0 src + U1 src + U2 src + U3 src into sys.path.

Follows the U2 tests/conftest.py pattern: anchor on the `units` directory, then append relative paths, with assert .exists() as a drift guard.
All four paths are inserted:
  - U0_SRC → `from common.* import ...` / `from identity.* import ...` (foundation, not copied)
  - U1_SRC → `from m1_ingest._writer_util import write_rows_parquet` (deterministic parquet writer,
             owner=U1) + `from m1_ingest.canonical_id import build_canonical_map/canonicalize/is_deleted`
             (inst/author id normalization; the real source is in U1, not U0 common)
  - U2_SRC → reads person_map (U2 product path convention)
  - U3_SRC → `from m3_panel.panel import ...` / `from m3_panel._panel_redlines import ...`
★U1_SRC cannot be dropped (U3 reuses the U1 writer to write parquet; U0 common has no parquet writer).
"""
import pathlib
import sys

_here = pathlib.Path(__file__).resolve()
_units = next(p for p in _here.parents if p.name == "units")

U0_SRC = _units / "u0_foundation" / "src"
U1_SRC = _units / "u1_fetch" / "src"
U2_SRC = _units / "u2_resolve" / "src"
U3_SRC = _units / "u3_panel" / "src"

for _name, _p in [("U0", U0_SRC), ("U1", U1_SRC), ("U2", U2_SRC), ("U3", U3_SRC)]:
    assert _p.exists(), f"{_name} src not at the expected location: {_p}"

for _p in (str(U0_SRC), str(U1_SRC), str(U2_SRC), str(U3_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def pytest_configure(config):
    """Register the `slow` marker (for real-data smoke runs): runs real shards with bounded RSS, skips itself when the SSD is absent."""
    config.addinivalue_line(
        "markers", "slow: 真数据/重 IO 冒烟 (需 4TB SSD 挂载; 缺盘自动 skip)"
    )


# Now that the preflight environment gate is wired into the real build_panel entry, every call
# really probes OPENALEX_API_KEY (one of the four gates). The test machine's shell may not export that variable
# → add a dummy when it is missing so the suite does not depend on the shell environment. Affects only the test process; does not mask the gate itself -
# the gate's failure path is red-tested separately with explicit injection (monkeypatch PYARROW_LOCK).
import os      # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _openalex_key_for_env_gate(monkeypatch):
    if not os.environ.get("OPENALEX_API_KEY"):
        monkeypatch.setenv("OPENALEX_API_KEY", "test-key-env-gate")
