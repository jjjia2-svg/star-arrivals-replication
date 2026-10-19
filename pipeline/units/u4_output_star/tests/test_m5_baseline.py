"""M5-T0 fwci_baseline_build — TDD first batch (FWCI baseline rules + schema).

Fixed rules (only copied here, never changed):
  - expected = citation_sum / work_count (arithmetic mean; the 32-bucket variant is retired)
  - included_types=[article,review] whitelist = same source as the denominator (symmetric drop)
  - subfield all None → HALT (guards against falling back to a snapshot)
  - output rows = the 4 columns of common.schema.FWCI_BASELINE (registered in schema.py [24])
"""
import pytest


def _pop(subfield="2002", year=2010, wtype="article", n=4, cites=20, hist=None):
    """One row of FWCI_BASELINE_POP (the six columns of the real U1 output schema)."""
    return {
        "subfield_id": subfield, "year": year, "work_type": wtype,
        "work_count": n, "citation_sum": cites,
        "cit_hist_32": hist if hist is not None else [0] * 32,
    }


def test_expected_is_arithmetic_mean():
    """Fixed-value guard: expected == citation_sum/work_count (mean), cell by cell."""
    from m5_output.fwci_baseline_build import build_fwci_baseline

    rows = build_fwci_baseline([_pop(n=4, cites=20), _pop(year=2011, n=5, cites=7)])
    by_key = {(r["subfield_id"], r["year"], r["work_type"]): r for r in rows}
    assert by_key[("2002", 2010, "article")]["expected_citations"] == 5.0
    assert by_key[("2002", 2011, "article")]["expected_citations"] == pytest.approx(1.4)


def test_expected_does_not_use_32bucket():
    """The 32-bucket proposal is retired: whatever cit_hist_32 holds, expected does not change (diagnostic carrier only)."""
    from m5_output.fwci_baseline_build import build_fwci_baseline

    a = build_fwci_baseline([_pop(hist=[0] * 32)])
    b = build_fwci_baseline([_pop(hist=[999] * 32)])
    assert a == b


def test_build_baseline_keeps_only_included_types():
    """Whitelist (real key fwci.included_types=[article,review]): rows of all other types are dropped from the denominator."""
    from m5_output.fwci_baseline_build import build_fwci_baseline

    rows = build_fwci_baseline([
        _pop(wtype="article"), _pop(wtype="review", n=2, cites=2),
        _pop(wtype="editorial", n=9, cites=900), _pop(wtype="paratext", n=3, cites=30),
    ])
    assert {r["work_type"] for r in rows} == {"article", "review"}


def test_build_baseline_halts_when_all_subfield_null(tmp_path):
    """Snapshot-fallback guard: all input subfield_id None → sys.exit(2); never silently produce an empty baseline."""
    from m5_output.fwci_baseline_build import build_fwci_baseline

    with pytest.raises(SystemExit) as ei:
        build_fwci_baseline([_pop(subfield=None), _pop(subfield=None, year=2011)])
    assert ei.value.code == 2


def test_baseline_schema_matches_u0():
    """Output row key set == common.schema.FWCI_BASELINE (schema.py [24], imported directly)."""
    from common.schema import FWCI_BASELINE, assert_matches_schema
    from m5_output.fwci_baseline_build import build_fwci_baseline

    rows = build_fwci_baseline([_pop()])
    assert rows, "non-empty input must produce output"
    for r in rows:
        assert_matches_schema(r.keys(), FWCI_BASELINE, label="fwci_baseline")


# ── Second batch: leave-star recompute / denominator keeps stars / provenance 4-tuple ──
def _work(wid, subfield="2002", year=2010, wtype="article", cites=10):
    """One row of the works table (only the keys M5 uses; the real table has 12 columns)."""
    return {"work_id": wid, "subfield_id": subfield, "publication_year": year,
            "work_type": wtype, "cited_by_count": cites}


def test_leave_star_baseline_rebuilds_from_works():
    """Leave-star-out: recompute from works for the affected cells, excluding star works, so
    expected falls (highly cited star papers raise the mean → it drops after removal). Does not modify the POP table."""
    from m5_output.fwci_baseline_build import rebuild_leave_star_baseline

    works = [_work("W1", cites=100), _work("W2", cites=2), _work("W3", cites=4),
             _work("W4", year=2011, cites=8)]  # another cell, outside the recompute scope
    rows = rebuild_leave_star_baseline(
        works, star_work_ids={"W1"}, cells={("2002", 2010, "article")})
    assert len(rows) == 1
    assert rows[0]["expected_citations"] == 3.0  # (2+4)/2 — W1 removed, W4 not in the cell
    assert rows[0]["year"] == 2010


def test_denominator_does_not_leave_star():
    """The denominator side does not drop stars: the global baseline function takes no star argument at all —
    for the same input the global expected is identical whoever the stars are (dropping stars happens only in the narrow recompute)."""
    import inspect

    from m5_output.fwci_baseline_build import build_fwci_baseline

    params = inspect.signature(build_fwci_baseline).parameters
    assert not any("star" in name for name in params), "the global-denominator function must not take a star parameter"


def test_write_baseline_manifest_has_provenance_quad(tmp_path):
    """The written file carries the provenance 4-tuple keys (stars_set_hash is an empty-string placeholder, injected by U5);
    snapshot_year is read from RED into the header (a null would raise; it is set, so this passes)."""
    import json

    from m5_output.fwci_baseline_build import build_fwci_baseline, write_fwci_baseline

    rows = build_fwci_baseline([_pop()])
    write_fwci_baseline(rows, tmp_path / "fwci_baseline")

    hdr = json.loads((tmp_path / "fwci_baseline" / "manifest_header.json"
                      ).read_text(encoding="utf-8"))
    for key in ("source_snapshot_merkle", "config_sha", "rule_version", "stars_set_hash"):
        assert key in hdr, f"the 4-tuple is missing key {key}"
    assert hdr["stars_set_hash"] == ""  # placeholder; injected by U5 after M7a freezes
    assert hdr["snapshot_year"] == "snapshot_2026-06-29_merkle_da78e4b9"  # snapshot_year as set in RED
    assert (tmp_path / "fwci_baseline" / "data.parquet").exists()
