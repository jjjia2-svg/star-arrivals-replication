"""Import bridge for the U2 tests: puts the U0 src, U1 src and U2 src on sys.path.

Follows the U1 tests/conftest.py pattern: anchor on the `units` directory, append the relative paths, and assert .exists() as a guard against drift.
All three paths are inserted:
  - U0_SRC -> `from common.* import ...` / `from identity.* import ...` (foundation, not copied)
  - U1_SRC -> `from m1_ingest._writer_util import write_rows_parquet` etc.
             (the deterministic parquet writer is owned by U1; build list B2) + reading the U1 derived tables
  - U2_SRC -> `from m2_resolve.resolve import ...` / `from m2_resolve.gate import ...`
U1_SRC cannot be dropped (U2 writes parquet with the U1 writer; U0 common has no parquet writer).
"""
import pathlib
import sys

_here = pathlib.Path(__file__).resolve()
_units = next(p for p in _here.parents if p.name == "units")

U0_SRC = _units / "u0_foundation" / "src"
U1_SRC = _units / "u1_fetch" / "src"
U2_SRC = _units / "u2_resolve" / "src"

assert U0_SRC.exists(), f"U0 src not at the expected location: {U0_SRC}"
assert U1_SRC.exists(), f"U1 src not at the expected location: {U1_SRC}"
assert U2_SRC.exists(), f"U2 src not at the expected location: {U2_SRC}"

for _p in (str(U0_SRC), str(U1_SRC), str(U2_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def pytest_configure(config):
    """Register the `slow` marker (for real-data smoke tests): runs real shards with bounded RSS, and skips itself when the SSD is absent."""
    config.addinivalue_line(
        "markers", "slow: 真数据/重 IO 冒烟 (需 4TB SSD 挂载; 缺盘自动 skip)"
    )
