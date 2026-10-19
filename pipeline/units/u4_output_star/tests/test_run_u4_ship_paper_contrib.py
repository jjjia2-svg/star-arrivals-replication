"""U4 shipping - run_u4 paper_contrib shipping orchestration (runner level, synthetic data, does not touch
the SSD).

Pipeline: roster staff -> pop -> baseline expected -> assemble (fwci raw value passes through)
-> star folding -> isc backfill -> write_paper_contrib (256 buckets, PK conflict raises) + diag sidecar + _reports.

The pipeline applies **no winsorization at all**: none of the 8 benchmark papers clips (they use log(1+x) in the
regression layer, Poisson QML, or raw values), so skewness is handled in the regression layer; the former
"p99 winsorize" step is not used, and the paratext exclusion is unchanged. Accordingly,
ship_paper_contrib runs end to end, each paper's raw fwci is stored, and there is no clipping step.

Two layers of tests:
  (1) ship_paper_contrib (the full production entry): runs end to end to disk; fwci passes through raw paper by
     paper (extreme values are not capped).
  (2) finalize_paper_contrib (the write-out stage): fed assembled raw-value rows directly to test the isc
     backfill + bucketed write + diagnostic sidecar + [inferred] share report + FWCI-NA count report.
"""
import csv
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

EDGES_SUB = "u1_edges_full_2026-07-05"
PM_SUB = "u2_person_map_2026-07-05"
ROSTER_SUB = "u0p5_roster/roster_v2026-07-10_starfix"   # corrected roster version (same source as run_u4.ROSTER_SUB)

_POP_SCHEMA = pa.schema([
    ("subfield_id", pa.string()), ("year", pa.int64()), ("work_type", pa.string()),
    ("work_count", pa.int64()), ("citation_sum", pa.int64()),
    ("cit_hist_32", pa.list_(pa.int64())),
])


def _mk_root(tmp_path, extra_works=(), extra_edges=()):
    """Synthetic derived_root with everything: works/edges/pop/manifest + person_map + two-university roster.

    Population: P1 = Monash staff (A1); SP1 = star (SA1, 5% and foreign_poach);
    P2 = off-campus ordinary co-author (A2); A3 = unmapped author.
    works: W1 = P1+SP1 co-authored (isc should be True); W2 = P1+P2 (isc False); W3 = P1 sole-authored, missing
    cell.
    extra_works/extra_edges: rows a test appends on demand (e.g. an extreme fwci scenario) without changing the
    base layout.
    """
    root = tmp_path / "derived"

    def _tbl(sub, name, rows, schema=None):
        d = root / sub / name
        d.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), str(d / "data.parquet"))

    _tbl(EDGES_SUB, "works", [
        {"work_id": "W1", "publication_year": 2010, "subfield_id": "2002",
         "work_type": "article", "cited_by_count": 10, "is_paratext": False, "fwci": 1.2},
        {"work_id": "W2", "publication_year": 2010, "subfield_id": "2002",
         "work_type": "article", "cited_by_count": 5, "is_paratext": False, "fwci": 0.8},
        {"work_id": "W3", "publication_year": 2012, "subfield_id": "2002",
         "work_type": "article", "cited_by_count": 7, "is_paratext": False, "fwci": None},
    ] + list(extra_works))
    _tbl(EDGES_SUB, "authorship_edges", [
        {"work_id": "W1", "author_id": "A1", "publication_year": 2010},
        {"work_id": "W1", "author_id": "SA1", "publication_year": 2010},
        {"work_id": "W2", "author_id": "A1", "publication_year": 2010},
        {"work_id": "W2", "author_id": "A2", "publication_year": 2010},
        {"work_id": "W2", "author_id": "A3", "publication_year": 2010},
        {"work_id": "W3", "author_id": "A1", "publication_year": 2012},
    ] + list(extra_edges))
    _tbl(EDGES_SUB, "fwci_baseline_pop",
         [{"subfield_id": "2002", "year": 2010, "work_type": "article",
           "work_count": 4, "citation_sum": 20, "cit_hist_32": [0] * 32}],
         schema=_POP_SCHEMA)
    _tbl(PM_SUB, "person_map", [
        {"author_id": "A1", "person_id": "P1"},
        {"author_id": "A2", "person_id": "P2"},
        {"author_id": "SA1", "person_id": "SP1"},
    ])
    roster_dir = root / ROSTER_SUB
    roster_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist([
        {"author_id": "A1", "dept_key": "monash_econ", "display_name": "Inc One",
         "year_start": 2008, "year_end": None, "confidence": "high",
         "human_verified": True},
    ]), str(roster_dir / "dept_roster_panel_monash.parquet"))
    pq.write_table(pa.Table.from_pylist([
        {"author_id": None, "dept_key": "unsw_econ", "display_name": "Ghost",
         "year_start": None, "year_end": None, "confidence": "low",
         "human_verified": False},
    ]), str(roster_dir / "dept_roster_panel_unsw.parquet"))
    mdir = root / EDGES_SUB / "_manifest"
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / "run_manifest.json").write_text(
        json.dumps({"source_snapshot_merkle": "snap:PC"}), encoding="utf-8")
    return root


def _star_rows():
    """Frozen star_set shape (only the keys isc consumes): SA1 = 5% and foreign_poach star;
    SA9 = 5% but not a foreign poach (removed by source_filter)."""
    return [
        {"author_id": "SA1", "is_star_5pct": True, "is_foreign_poach": True},
        {"author_id": "SA9", "is_star_5pct": True, "is_foreign_poach": False},
    ]


# ---- (1) production entry: runs end to end, fwci passes through raw (no clipping) -----------------

def _read_landed(out):
    """Read back all rows of the written main table (256 buckets -> flat list)."""
    back = []
    for p in sorted((out / "paper_contrib").rglob("*.parquet")):
        back += pq.read_table(str(p)).to_pylist()
    return back


def test_ship_paper_contrib_ships_end_to_end_no_winsor_stage(tmp_path):
    """There is no winsorization step in the shipping pipeline -> ship_paper_contrib runs end to end through to
    write-out/finalize - main table + diagnostic sidecar + _reports all written, isc backfill correct (W1 star
    co-authored True)."""
    from run_u4 import ship_paper_contrib

    root = _mk_root(tmp_path)
    out = tmp_path / "out"
    res = ship_paper_contrib(root, out, star_rows=_star_rows())  # no raise means it ran through
    assert (out / "paper_contrib").exists(), "the main table should be written to disk (the ship gate is unlocked)"
    assert (out / "paper_contrib_diag" / "data.parquet").exists(), "the diagnostic sidecar should be written to disk"
    assert (out / "_reports" / "fwci_na_counts.csv").exists(), "the FWCI-NA report should be written"
    assert (out / "_reports" / "fwci_inferred_ratio.csv").exists(), "the inferred-share report should be written"
    back = _read_landed(out)
    assert len(back) == res["n_rows"] > 0
    isc_by_work = {}
    for r in back:
        isc_by_work.setdefault(r["work_id"], set()).add(r["is_star_coauthored"])
    assert isc_by_work["W1"] == {True}, "isc of W1, co-authored by star SA1 and SP1, is back-filled to True"
    assert isc_by_work["W2"] == {False}
    assert res["n_star_persons"] == 1


def test_ship_lands_fwci_raw_values_verbatim(tmp_path):
    """Core assertion (not clipping = record faithfully): the written rows' fwci equals the input paper by paper - raw
    values pass through, no clipping at all.
    expected = 20/4 = 5.0 -> W1 = 10/5 = 2.0; W2 = 5/5 = 1.0; W3 missing cell = None (unchanged)."""
    from run_u4 import ship_paper_contrib

    root = _mk_root(tmp_path)
    out = tmp_path / "out"
    ship_paper_contrib(root, out, star_rows=_star_rows())
    fwci_by_work = {}
    for r in _read_landed(out):
        fwci_by_work.setdefault(r["work_id"], set()).add(r["fwci"])
    assert fwci_by_work["W1"] == {2.0}, "the original W1 values 10/5.0 are written verbatim"
    assert fwci_by_work["W2"] == {1.0}, "the original W2 values 5/5.0 are written verbatim"
    assert fwci_by_work["W3"] == {None}, "a missing cell stays NA (the missing-value rule is unaffected by not capping)"


def test_ship_extreme_fwci_lands_uncapped(tmp_path):
    """Extreme-value sentinel: build a row with fwci = 385/5.0 = 77.0 -> still 77.0 after writing -
    not capped, no p99, not changed at all (skewness is handled in the regression layer)."""
    from run_u4 import ship_paper_contrib

    root = _mk_root(
        tmp_path,
        extra_works=[{"work_id": "W_EXT", "publication_year": 2010,
                      "subfield_id": "2002", "work_type": "article",
                      "cited_by_count": 385, "is_paratext": False, "fwci": 30.0}],
        extra_edges=[{"work_id": "W_EXT", "author_id": "A1",
                      "publication_year": 2010}])
    out = tmp_path / "out"
    ship_paper_contrib(root, out, star_rows=_star_rows())
    ext = [r for r in _read_landed(out) if r["work_id"] == "W_EXT"]
    assert ext, "the extreme-value row should be written as usual"
    assert {r["fwci"] for r in ext} == {77.0}, "77.0 must be stored as is (any capping is a violation)"


# ---- (2) write-out stage (finalize): backfill + bucketing + sidecar + reports ---------------------------

def _assembled(root):
    """Borrow the assembler's rows/diagnostics (small synthetic data) and feed them directly to finalize as assembled
    raw-value rows (no clipping step)."""
    from m5_output.assemble_contrib import assemble_paper_contrib

    return assemble_paper_contrib(
        root, incumbent_person_ids={"P1"},
        author_person={"A1": "P1", "A2": "P2", "SA1": "SP1"},
        expected_by_cell={("2002", 2010, "article"): 5.0}, edges_sub=EDGES_SUB)


def test_finalize_lands_buckets_isc_diag_and_reports(tmp_path):
    """Whole write-out: (1) the bucketed parquet reads back, row count conserved (2) W1 (co-authored with star SP1)
    isc backfill True, W2/W3 False (3) the diagnostic sidecar is written (4) two _reports files ([inferred] share +
    FWCI-NA count)."""
    from run_u4 import finalize_paper_contrib

    root = _mk_root(tmp_path)
    asm = _assembled(root)
    out = tmp_path / "out"
    res = finalize_paper_contrib(
        asm["rows"], asm["diag"], star_author_ids=["SA1"],
        author_person={"A1": "P1", "A2": "P2", "SA1": "SP1"}, out_dir=out)

    parts = sorted((out / "paper_contrib").rglob("*.parquet"))
    assert parts, "the bucketed paper_contrib parquet should be written to disk"
    back = []
    for p in parts:
        back += pq.read_table(str(p)).to_pylist()
    assert len(back) == len(asm["rows"]) == res["n_rows"]
    isc_by_work = {}
    for r in back:
        isc_by_work.setdefault(r["work_id"], set()).add(r["is_star_coauthored"])
    assert isc_by_work["W1"] == {True}, "every W1 row co-authored by star SP1 has isc=True"
    assert isc_by_work["W2"] == {False}
    assert isc_by_work["W3"] == {False}

    dpath = out / "paper_contrib_diag" / "data.parquet"
    assert dpath.exists(), "the diagnostic sidecar should be written to disk"
    drows = pq.read_table(str(dpath)).to_pylist()
    assert {d["work_id"] for d in drows} == {"W1", "W2", "W3"}

    ratio_csv = out / "_reports" / "fwci_inferred_ratio.csv"
    na_csv = out / "_reports" / "fwci_na_counts.csv"
    assert ratio_csv.exists(), "the [inferred]-share report should be written"
    assert na_csv.exists(), "the FWCI-NA count report should be written"
    with na_csv.open(encoding="utf-8") as f:
        na_rows = {r["fwci_missing_reason"]: int(r["n"]) for r in csv.DictReader(f)}
    assert na_rows.get("missing_cell") == 1                # W3 (2012, no baseline)
    assert res["n_unmapped_star_authors"] == 0


def test_finalize_warns_star_missing_person_map(tmp_path, capsys):
    """A person in star_set lacks a person_map mapping -> a counted WARN, not silent (goes into the return value +
    stderr)."""
    from run_u4 import finalize_paper_contrib

    root = _mk_root(tmp_path)
    asm = _assembled(root)
    res = finalize_paper_contrib(
        asm["rows"], asm["diag"], star_author_ids=["SA1", "SA_GONE"],
        author_person={"A1": "P1", "A2": "P2", "SA1": "SP1"}, out_dir=tmp_path / "out")
    assert res["n_unmapped_star_authors"] == 1
    assert res["unmapped_star_author_ids"] == ["SA_GONE"]
    assert "WARN" in capsys.readouterr().err


def test_finalize_pk_payload_conflict_raises(tmp_path):
    """PK conflict raises: same primary key with an inconsistent payload -> ValueError (the write_paper_contrib
    dedup guard, never silently erases a disagreement)."""
    from run_u4 import finalize_paper_contrib

    row = {"work_id": "W1", "incumbent_person_id": "P1", "person_id": "P1",
           "publication_year": 2010, "frac_credit": 0.5, "fwci": 2.0,
           "is_star_coauthored": False, "subfield_id": "2002"}
    clash = dict(row, fwci=9.9)
    diag = [{"work_id": "W1", "fwci_native": 1.0, "fwci_incomplete": False,
             "fwci_missing_reason": None, "fwci_inferred_fallback": False}]
    with pytest.raises(ValueError, match="primary key"):
        finalize_paper_contrib([row, clash], diag, star_author_ids=[],
                               author_person={}, out_dir=tmp_path / "out")
