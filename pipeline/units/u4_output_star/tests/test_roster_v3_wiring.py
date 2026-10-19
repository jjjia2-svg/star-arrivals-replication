"""registry v3 wiring red test — the U4 roster read can point at the 11-school registry v3; the two-school default can be rolled back.

Pre-AWS-full-run requirement: run_u4 gets a roster_files_for(registry_version) selector:
  - "two" (default, frozen) → ROSTER_FILES two schools (roster_v2026-07-10_starfix, Monash+UNSW);
  - "v3"            → ROSTER_FILES_V3 11-school panel (registry_v3_2026-07-12/).

No regression: the ROSTER_SUB / ROSTER_FILES two-school default literals are untouched (real_inputs still imports ROSTER_FILES,
the single source of truth); v3 is a new optional path. The SSD real-disk read test skips automatically when the disk is absent (EC2/CI green).
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_UNITS = next(p for p in pathlib.Path(__file__).resolve().parents if p.name == "units")
_U4_SRC = _UNITS / "u4_output_star" / "src"
if str(_U4_SRC) not in sys.path:
    sys.path.insert(0, str(_U4_SRC))

import run_u4 as U  # noqa: E402

# --- M3 port: repo path resolution (legacy hard-coded the author's machine) — config/paths.yaml ---
import pathlib as _sar_pl, sys as _sar_sys
_sar_repo = next(p for p in _sar_pl.Path(__file__).resolve().parents if p.name == "units").parents[1]
if str(_sar_repo) not in _sar_sys.path:
    _sar_sys.path.append(str(_sar_repo))
from pipeline.lib.paths import derived_root as _sar_derived_root  # noqa: E402

_V3_DIR = "u0p5_roster/registry_v3_2026-07-12"
_SHORT_11 = {"adelaide", "anu", "deakin", "macquarie", "melbourne",
             "monash", "sydney", "unsw", "uq", "uts", "uwa"}
_SSD_V3 = pathlib.Path(
    str(_sar_derived_root() / "u0p5_roster/registry_v3_2026-07-12"))


def _short(rel: str) -> str:
    return rel.rsplit("dept_roster_panel_", 1)[-1].replace(".parquet", "")


def test_two_school_default_literals_frozen():
    """No regression: the two-school default path literals are untouched (the single source of truth imported by real_inputs)."""
    assert U.ROSTER_SUB == "u0p5_roster/roster_v2026-07-10_starfix"
    assert U.ROSTER_FILES == (
        "u0p5_roster/roster_v2026-07-10_starfix/dept_roster_panel_monash.parquet",
        "u0p5_roster/roster_v2026-07-10_starfix/dept_roster_panel_unsw.parquet",
    )


def test_roster_files_for_two_is_frozen_pair():
    files = U.roster_files_for("two")
    assert files == U.ROSTER_FILES
    assert {_short(f) for f in files} == {"monash", "unsw"}


def test_roster_files_for_v3_is_eleven_under_registry_v3():
    files = U.roster_files_for("v3")
    assert len(files) == 11
    assert all(f.startswith(_V3_DIR) for f in files)
    assert {_short(f) for f in files} == _SHORT_11


def test_roster_default_is_two_school():
    assert U.roster_files_for() == U.ROSTER_FILES


def test_roster_unknown_version_fails_loud():
    with pytest.raises(ValueError):
        U.roster_files_for("nope")


@pytest.mark.skipif(not _SSD_V3.exists(), reason="SSD registry_v3 not present (EC2/CI environment)")
def test_v3_roster_files_resolve_to_eleven_real_panels_with_zenou():
    """SSD real disk: the v3 relative paths resolve to the 11 real panels, each readable, 11 dept_keys in total + includes the Zenou gold standard."""
    import pyarrow.parquet as pq

    derived = _sar_derived_root()
    dept_keys: set = set()
    zenou = False
    for rel in U.roster_files_for("v3"):
        p = derived / rel
        assert p.exists(), f"v3 panel missing: {p}"
        for r in pq.read_table(str(p)).to_pylist():
            dept_keys.add(r["dept_key"])
            if r.get("display_name") == "Yves Zenou":
                zenou = True
    assert len(dept_keys) == 11, f"the 11-university roster should have 11 dept_keys, got {sorted(dept_keys)}"
    assert zenou, "golden test: the Monash roster must contain Yves Zenou"
