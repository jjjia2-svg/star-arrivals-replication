"""Wiring tests for registry v3: the U1 seed (econ_dept_ids) can point at the 11-university registry v3, with the two-university default as fallback.

Prerequisite for the full AWS run: run_smoke_m1.build_inputs gets a registry_version knob:
  - "two" (default, frozen) -> build_table_a_rows() two universities (Monash+UNSW) -> econ_dept_ids holds the 2 universities' institutions;
  - "v3"                    -> build_table_a_rows_all() 11 universities -> econ_dept_ids holds the 11 universities' institutions (a superset of the two).

No regression: the default is still the two universities (existing two-university runs and the full test
suite are unchanged); v3 is a new optional path.
EC2 only rsyncs code (without the SSD roster parquet), so the seed must come from the table-A rows inside
the code. The knob therefore selects among the build_table_a_rows* functions and does not read the
registry_v3 parquet (the parquet is the frozen product / provenance, and its sha equals the output of
build_table_a_rows_all(); see the TABLE_A_SHA guard in roster/registry_v3.py).
"""
from __future__ import annotations

import pathlib
import sys

import pytest

pytest.importorskip("pyarrow")

# The driver sits at the repo root (not in units/*/src); put the repo root on the path before importing (run_smoke_m1 adds the roster src automatically when imported).
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import run_smoke_m1 as D  # noqa: E402
from roster.table_a import (  # noqa: E402
    build_econ_dept_ids,
    build_table_a_rows,
    build_table_a_rows_all,
)


def _self_folding_registry(rows):
    """Each openalex_inst_id folds to itself as an education anchor (same as the test_table_a precedent)."""
    return {r["openalex_inst_id"]: {"openalex_id": r["openalex_inst_id"], "type": "education"}
            for r in rows}


def test_select_two_is_frozen_two_school():
    rows = D.select_table_a_rows("two")
    assert rows == build_table_a_rows()
    assert [r["dept_key"] for r in rows] == ["monash_econ", "unsw_econ"]


def test_select_v3_is_all_eleven():
    rows = D.select_table_a_rows("v3")
    assert rows == build_table_a_rows_all()
    keys = [r["dept_key"] for r in rows]
    assert len(keys) == 11 and len(set(keys)) == 11
    assert {"monash_econ", "unsw_econ"} <= set(keys)


def test_select_default_is_two_school():
    assert D.select_table_a_rows() == build_table_a_rows()


def test_select_unknown_version_fails_loud():
    with pytest.raises(ValueError):
        D.select_table_a_rows("nope")


def test_v3_seed_set_is_eleven_and_superset_of_two():
    """Wiring check: pointing at v3 -> econ_dept_ids covers the 11 universities' institutions (a superset of the two-university seed set)."""
    all_rows = build_table_a_rows_all()
    reg = _self_folding_registry(all_rows)
    ids_v3 = build_econ_dept_ids(all_rows, reg)
    ids_two = build_econ_dept_ids(build_table_a_rows(), reg)
    assert len(ids_v3) == 11
    assert len(ids_two) == 2
    assert ids_two < ids_v3   # proper subset: two universities < 11 universities


def test_build_inputs_threads_registry_version(monkeypatch):
    """build_inputs(registry_version=...) passes the choice through to econ_dept_ids; the default is two universities (fallback)."""
    all_rows = build_table_a_rows_all()
    reg = _self_folding_registry(all_rows)
    monkeypatch.setattr(D, "load_education_registry", lambda _s: list(reg.values()))
    monkeypatch.setattr(D, "build_registry_by_id", lambda _r: reg)

    _, ids_default = D.build_inputs("SNAP")
    _, ids_v3 = D.build_inputs("SNAP", registry_version="v3")
    assert len(ids_default) == 2      # the default falls back to two universities
    assert len(ids_v3) == 11
    assert ids_default < ids_v3
