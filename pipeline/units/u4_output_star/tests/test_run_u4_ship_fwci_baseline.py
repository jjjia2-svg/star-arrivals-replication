"""U4 shipping - ship_fwci_baseline wiring (runner level, synthetic data, does not touch the SSD).

In plain words: write_fwci_baseline existed but nothing called it - run_u4 now adds thin wiring:
read the U1 fwci_baseline_pop (bucketed or single-file, transparently) -> build_fwci_baseline (mean + the B-SYM
whitelist) -> resolve_provenance injects the four-tuple (empty values fail-loud, never a placeholder
string) -> write_fwci_baseline.

Leave-star version (leave-star-out): an independent thin function ship_leave_star_baseline - for the affected
cells, recompute on a small scale from works (star works excluded; the denominator comes from the same B-SYM
source: whitelist + symmetric paratext drop), written to the sidecar table fwci_baseline_leave_star (a
diagnostic/control artifact outside the six tables; the name explicitly marks leave_star).
"""
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


def _pop_row(subfield="2002", year=2010, wtype="article", n=4, cites=20):
    """One FWCI_BASELINE_POP row (the six columns of the real U1 artifact schema)."""
    return {"subfield_id": subfield, "year": year, "work_type": wtype,
            "work_count": n, "citation_sum": cites, "cit_hist_32": [0] * 32}


_POP_SCHEMA = pa.schema([
    ("subfield_id", pa.string()), ("year", pa.int64()), ("work_type", pa.string()),
    ("work_count", pa.int64()), ("citation_sum", pa.int64()),
    ("cit_hist_32", pa.list_(pa.int64())),
])

EDGES_SUB = "u1_edges_full_2026-07-05"


def _mk_root(tmp_path, pop_rows=None, *, merkle="snap:SHIPTEST", with_manifest=True,
             works_rows=None):
    """Synthetic derived_root: the pop table uses the **bucketed layout** (bucket=000/part-*.parquet, exercising the
    transparent read) + the U1 run_manifest (the source for resolve_provenance) + an optional works table (for
    leave-star)."""
    root = tmp_path / "derived"
    if pop_rows is not None:
        tdir = root / EDGES_SUB / "fwci_baseline_pop" / "bucket=000"
        tdir.mkdir(parents=True)
        pq.write_table(pa.Table.from_pylist(pop_rows, schema=_POP_SCHEMA),
                       str(tdir / "part-000.parquet"))
    if works_rows is not None:
        wdir = root / EDGES_SUB / "works"
        wdir.mkdir(parents=True)
        pq.write_table(pa.Table.from_pylist(works_rows), str(wdir / "data.parquet"))
    if with_manifest:
        mdir = root / EDGES_SUB / "_manifest"
        mdir.mkdir(parents=True, exist_ok=True)
        (mdir / "run_manifest.json").write_text(
            json.dumps({"source_snapshot_merkle": merkle}), encoding="utf-8")
    return root


# ---- main-table wiring: pop -> build -> provenance -> write --------------------------------

def test_ship_fwci_baseline_lands_table_and_provenance_quad(tmp_path):
    """Whole chain to disk: expected=mean checked cell by cell; non-whitelist types dropped (B-SYM);
    manifest_header four-tuple values non-empty (merkle=U1's existing value / config_sha=sha256_of_red())
    + stars_set_hash placeholder empty string (injected by U5) + snapshot_year set to the true value."""
    from common._redlines import require, sha256_of_red
    from run_u4 import ship_fwci_baseline

    root = _mk_root(tmp_path, [
        _pop_row(n=4, cites=20),                        # expected 5.0
        _pop_row(year=2011, n=5, cites=7),              # expected 1.4
        _pop_row(wtype="editorial", n=9, cites=900),    # not on the whitelist -> dropped
    ])
    res = ship_fwci_baseline(root, tmp_path / "out")

    p = tmp_path / "out" / "fwci_baseline" / "data.parquet"
    assert p.exists(), "fwci_baseline/data.parquet should be written to disk"
    rows = pq.read_table(str(p)).to_pylist()
    by = {(r["subfield_id"], r["year"], r["work_type"]): r["expected_citations"]
          for r in rows}
    assert by[("2002", 2010, "article")] == 5.0
    assert by[("2002", 2011, "article")] == pytest.approx(1.4)
    assert not any(k[2] == "editorial" for k in by), "types outside the whitelist must not enter the denominator"

    hdr = json.loads((tmp_path / "out" / "fwci_baseline" / "manifest_header.json")
                     .read_text(encoding="utf-8"))
    assert hdr["source_snapshot_merkle"] == "snap:SHIPTEST"
    assert hdr["config_sha"] == sha256_of_red()
    assert hdr["rule_version"] == "redlines_v4_signed_2026-07-05"
    assert hdr["stars_set_hash"] == ""          # the placeholder key is present, U5 injects it
    assert hdr["snapshot_year"] == require("fwci", "snapshot_year")
    assert res["n_rows"] == 2


def test_ship_fwci_baseline_fail_loud_when_u1_manifest_missing(tmp_path):
    """Discipline: U1 run_manifest absent -> ValueError, and nothing is written (never a placeholder string)."""
    from run_u4 import ship_fwci_baseline

    root = _mk_root(tmp_path, [_pop_row()], with_manifest=False)
    with pytest.raises(ValueError, match="run_manifest"):
        ship_fwci_baseline(root, tmp_path / "out")
    assert not (tmp_path / "out" / "fwci_baseline").exists(), "a failed parse must never be written to disk"


def test_ship_fwci_baseline_fail_loud_on_missing_or_empty_pop(tmp_path):
    """pop table absent / 0 rows -> ValueError fail-loud (an empty baseline would make everything downstream
    missing_cell, never silent)."""
    from run_u4 import ship_fwci_baseline

    root = _mk_root(tmp_path, pop_rows=None)             # the table is not there at all
    with pytest.raises(ValueError, match="fwci_baseline_pop"):
        ship_fwci_baseline(root, tmp_path / "out")

    root2 = _mk_root(tmp_path / "b", pop_rows=[])        # the table is there but has 0 rows
    with pytest.raises(ValueError, match="fwci_baseline_pop"):
        ship_fwci_baseline(root2, tmp_path / "b_out")


# ---- leave-star version (leave-star-out; small-scale recompute, POP untouched) ----------------

def _work(wid, subfield="2002", year=2010, wtype="article", cites=10, paratext=False):
    return {"work_id": wid, "subfield_id": subfield, "publication_year": year,
            "work_type": wtype, "cited_by_count": cites, "is_paratext": paratext}


def test_ship_leave_star_baseline_small_range_recompute(tmp_path):
    """Affected cells recompute expected after excluding star works (W1, star, 100 citations, dropped -> (2+4)/2=3.0);
    other cells are not included; paratext dropped symmetrically (B-SYM); written to the sidecar table + a header
    carrying the leave_star mark."""
    from run_u4 import ship_leave_star_baseline

    root = _mk_root(tmp_path, works_rows=[
        _work("W1", cites=100),                          # star work -> dropped
        _work("W2", cites=2), _work("W3", cites=4),
        _work("W4", year=2011, cites=8),                 # other cells -> outside the recompute scope
        _work("W5", cites=999, paratext=True),           # paratext -> dropped symmetrically
    ])
    res = ship_leave_star_baseline(
        root, tmp_path / "out",
        star_work_ids={"W1"}, affected_cells={("2002", 2010, "article")})

    p = tmp_path / "out" / "fwci_baseline_leave_star" / "data.parquet"
    assert p.exists()
    rows = pq.read_table(str(p)).to_pylist()
    assert len(rows) == 1
    assert rows[0]["expected_citations"] == 3.0
    assert rows[0]["year"] == 2010

    hdr = json.loads((tmp_path / "out" / "fwci_baseline_leave_star" /
                      "manifest_header.json").read_text(encoding="utf-8"))
    assert hdr["table"] == "fwci_baseline_leave_star"
    assert hdr["leave_star"] is True
    assert hdr["source_snapshot_merkle"] == "snap:SHIPTEST"
    assert hdr["n_star_works_excluded"] == 1
    assert res["n_rows"] == 1


def test_ship_leave_star_baseline_requires_explicit_cells(tmp_path):
    """The cell set is passed explicitly and is part of the definition (small scale != global) - empty cells ->
    ValueError, no silent full scan."""
    from run_u4 import ship_leave_star_baseline

    root = _mk_root(tmp_path, works_rows=[_work("W1")])
    with pytest.raises(ValueError, match="affected_cells"):
        ship_leave_star_baseline(root, tmp_path / "out",
                                 star_work_ids={"W1"}, affected_cells=set())
