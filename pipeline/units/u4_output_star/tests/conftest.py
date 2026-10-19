"""Import bridge for the U4 tests: puts the five src directories of U0, U1, U2, U3 and U4 on sys.path (same pattern as the U3 conftest).

  - U0_SRC → common.* / identity.* (foundation: _redlines/schema/derived_table/output_rule/star_rule…)
  - U1_SRC → m1_ingest._writer_util (HashBucketWriter/write_rows_parquet, owner=U1)
  - U2_SRC → person_map path convention
  - U3_SRC → panel/affil_timeline consumption convention (is_modal is consume-only)
  - U4_SRC → m5_output/m6_generation/m7a_star
"""
import pathlib
import sys

_here = pathlib.Path(__file__).resolve()
_units = next(p for p in _here.parents if p.name == "units")

_SRCS = [
    ("U0", _units / "u0_foundation" / "src"),
    ("U1", _units / "u1_fetch" / "src"),
    ("U2", _units / "u2_resolve" / "src"),
    ("U3", _units / "u3_panel" / "src"),
    ("U4", _units / "u4_output_star" / "src"),
]
for _name, _p in _SRCS:
    assert _p.exists(), f"{_name} src not at the expected location: {_p}"
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: 真数据/重 IO 冒烟 (需 4TB SSD 挂载; 缺盘自动 skip)"
    )


# Once the preflight environment gate was wired into run_u4_full, that orchestration
# really probes OPENALEX_API_KEY (one of the four gates). The test shell may not
# export the variable → add a dummy when it is missing, so the suite does not
# depend on the shell environment. It affects only the test process and does not
# hide the gate itself — the gate's failure path is tested separately with explicit
# injection (monkeypatch PYARROW_LOCK).
import os      # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _openalex_key_for_env_gate(monkeypatch):
    if not os.environ.get("OPENALEX_API_KEY"):
        monkeypatch.setenv("OPENALEX_API_KEY", "test-key-env-gate")
