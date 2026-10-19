"""m7c provenance_gate tests (written test-first): HALT on mismatch + narrowed object set + consistency of the two anchors.

Covers: T35 (HALT on a mismatch in any one key, parametrised over four keys) / T36 (a mismatch raises
instead of returning False) / T37 (the object set excludes fwci_baseline/embeddings/groups).
Provenance is bound to u5_ship + the 10c anchor (the three shared keys must agree across the two anchors).
"""
from __future__ import annotations

import pytest

from common.manifest import PROVENANCE_KEYS, ProvenanceMismatch
from m7c_gates import provenance_gate as pg

_Q = {"source_snapshot_merkle": "snap:aaa", "config_sha": "c1",
      "rule_version": "rv", "stars_set_hash": "s1"}


def _headers():
    return {name: dict(_Q) for name in pg.GPROV_OBJECTS}


def _expected():
    return {name: dict(_Q) for name in pg.GPROV_OBJECTS}


def test_gprov_pass_on_equal_quads():
    res = pg.run_provenance_gate(_headers(), _expected())
    assert res["verdict"] == "PASS"
    assert set(res["checked"]) == set(pg.GPROV_OBJECTS)


@pytest.mark.parametrize("key", PROVENANCE_KEYS)
def test_each_prov_key_mismatch_halts(key):
    """T35: any one key unequal -> ProvenanceMismatch (HALT, not WARN)."""
    headers = _headers()
    headers["events"] = dict(headers["events"], **{key: "TAMPERED"})
    with pytest.raises(ProvenanceMismatch):
        pg.run_provenance_gate(headers, _expected())


def test_prov_mismatch_is_halt_not_warn():
    """T36: a mismatch raises; it does not return {all_match: False}."""
    headers = _headers()
    headers["dose_p01"]["stars_set_hash"] = "x"
    try:
        pg.run_provenance_gate(headers, _expected())
    except ProvenanceMismatch as e:
        assert e.exit_code == 13
        return
    pytest.fail("a mismatch must raise ProvenanceMismatch, never return silently")


def test_gprov_object_set_excludes_fwci_baseline_and_embeddings():
    """T37: object set = star_set/events/dose_p01/dose_p05/output;
    no fwci_baseline (DAG-only; its empty stars_set_hash would cause a false HALT), no embeddings
    (provenance not recorded), no groups_ABC."""
    assert set(pg.GPROV_OBJECTS) == {"star_set", "events", "dose_p01",
                                     "dose_p05", "output"}
    for banned in ("fwci_baseline", "embeddings", "groups_ABC"):
        assert banned not in pg.GPROV_OBJECTS
        assert banned in pg.GPROV_EXCLUDED


def test_missing_header_is_mismatch():
    headers = _headers()
    del headers["output"]
    with pytest.raises(ProvenanceMismatch):
        pg.run_provenance_gate(headers, _expected())


def test_cross_anchor_shared_keys_must_agree():
    """The three shared keys (merkle / stars_set_hash / rule_version) of the two anchors (u4 = 10c, u5 = u5_ship)
    must agree (config_sha is independent per unit and may differ)."""
    u4 = dict(_Q)
    u5 = dict(_Q, config_sha="c_other")           # a different config_sha is legal
    pg.assert_cross_anchor_consistent(u4, u5)     # does not raise
    u5_bad = dict(u5, stars_set_hash="DRIFT")
    with pytest.raises(ProvenanceMismatch):
        pg.assert_cross_anchor_consistent(u4, u5_bad)
