"""Tests for run_m1 assembly: with the real closures wired into each sink, a small fixture checks the 10 table contents end to end, plus the four-number reconcile and the bucketed write path.

Why this is a separate file (it complements test_run_m1.py):
  test_run_m1.py checks the orchestration skeleton (Merkle / field probe / canonical-space guard /
  run_manifest / deterministic sha).
  This file checks whether the 10 tables produced after the real closures are wired into each sink have
  the right content. It runs run_slice_tables on a small fixture containing Monash + Stockholm and asserts:
    1. all 10 tables are produced (all keys present);
    2. key columns really carry the output of the real closures:
       - institutions has country_code (Stockholm=SE, a foreign institution, is in the table: the
         Zenou key-case safeguard);
       - work_text has title (abstract_reverse.flatten_work_text is really wired in);
       - works_affil has raw_affiliation_strings (the field disambiguation depends on; schema_map/works_affil is really wired in).
  Also:
    3. the four-number reconcile (reconcile_m1 wired into run_m1: expected == kept + failed + skipped);
    4. the HashBucketWriter bucketed write path (write_tables_bucketed: deterministic, part sha identical across two runs).

Discipline: all tests use fixture / small-sample works JSON and never download from S3 or write to the SSD
(output goes to tmp_path). The Monash canonical id uses the real value I56590836 (golden.MONASH_CANONICAL_ID);
Stockholm uses the placeholder I_STOCKHOLM (a foreign institution, country_code=SE). Identification
placeholders (diff_tolerance) are always passed explicitly and never filled in here.
"""
from __future__ import annotations

import pytest

from m1_ingest import run_m1 as R
from m1_ingest import reconcile_m1 as REC
from identity.golden import MONASH_CANONICAL_ID  # real value I56590836
from common._redlines import RedlineUnsigned


def _manifest_works(n):
    """Top-level manifest fixture (observed shape): the sum of record_count for the works entity == n (external ground-truth anchor).

    It feeds the anti-circularity anchor: reconcile now takes expected from here (compute_expected_from_manifest), no longer from its own scan count.
    """
    return {
        "date": "2026-06-26",
        "format": "jsonl",
        "meta": {"record_count": n, "content_length": 1},
        "entities": [{
            "entity": "works",
            "record_count": n,
            "content_length": 1,
            "files": [{
                "url": "s3://openalex/data/jsonl/works/updated_date=2016-01-01/part_0000.gz",
                "meta": {"content_length": 1, "record_count": n},
            }],
        }],
    }


# ---------------------------------------------------------------------------
# fixture: Monash (in the department, AU) + Stockholm (outside, SE), with a refs frontier
# ---------------------------------------------------------------------------
# registry: Monash is a valid canonical edu parent institution; econ_dept_ids holds Monash -> Monash authors are seeds.
_REGISTRY = [{"openalex_id": MONASH_CANONICAL_ID, "type": "education"}]
_ECON_DEPT_IDS = {MONASH_CANONICAL_ID}

_MONASH_ID = MONASH_CANONICAL_ID   # I56590836 (AU)
_STOCKHOLM_ID = "I_STOCKHOLM"      # foreign institution placeholder (country_code=SE)


def _inst(inst_id, *, country, itype="education", lineage=None):
    return {
        "id": f"https://openalex.org/{inst_id}",
        "display_name": inst_id,
        "country_code": country,
        "type": itype,
        "lineage": lineage or [f"https://openalex.org/{inst_id}"],
    }


def _au(author_id, *, institutions, raw_affil, orcid=None):
    return {
        "author": {
            "id": f"https://openalex.org/{author_id}",
            "display_name": author_id,
            "orcid": orcid,
        },
        "institutions": institutions,
        "raw_affiliation_strings": raw_affil,
    }


def _work(wid, *, year, refs=None, authorships=None, subfield="2002",
          wtype="article", title=None, inverted=None):
    w = {
        "id": f"https://openalex.org/{wid}",
        "publication_year": year,
        "type": wtype,
        "cited_by_count": 11,
        "referenced_works": [f"https://openalex.org/{r}" for r in (refs or [])],
        "primary_topic": {"subfield": {"id": f"https://openalex.org/subfields/{subfield}"}},
        "authorships": authorships or [],
    }
    if title is not None:
        w["title"] = title
    if inverted is not None:
        w["abstract_inverted_index"] = inverted
    return w


def _monash_stockholm_works():
    """Seed work W_MS:
        - Zenou (A5017376589) @ Monash (in the department, AU) + a real ORCID;
        - collaborator A_STK @ Stockholm (outside, SE);
      cites W_REF (the frontier, added by the re-scan shard).
    """
    w_ms = _work(
        "W_MS", year=2016, refs=["W_REF"],
        title="Network spillovers in economics",
        inverted={"Network": [0], "spillovers": [1]},
        authorships=[
            _au("A5017376589",
                institutions=[_inst(_MONASH_ID, country="AU")],
                raw_affil=["Monash University, Department of Economics"],
                orcid="0000-0001-6516-0812"),
            _au("A_STK",
                institutions=[_inst(_STOCKHOLM_ID, country="SE")],
                raw_affil=["Stockholm University"]),
        ],
    )
    w_ref = _work(
        "W_REF", year=2009, title="Prior network paper",
        authorships=[_au("A_OTHER", institutions=[_inst(_STOCKHOLM_ID, country="SE")],
                         raw_affil=["Stockholm University"])],
    )
    return [w_ms], [w_ref]


# canonical names of the 10 tables (the keys of run_slice_tables).
_TEN_TABLES = (
    "works", "authorship_edges", "refs_edges", "works_affil", "institutions",
    "authors", "work_text", "work_first_pub", "fwci_baseline_pop", "canonical_id_map",
)


# ===========================================================================
# 1. All 10 tables produced + 2. key columns really written (real closures wired into each sink)
# ===========================================================================
def test_slice_produces_all_ten_tables():
    """run_slice_tables produces all 10 tables in one call (all keys present, real closures wired in)."""
    seed, refz = _monash_stockholm_works()
    tables = R.run_slice_tables(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS)
    assert set(tables.keys()) == set(_TEN_TABLES)
    # the main table is non-empty (the seed work was written).
    assert tables["works"], "The works table should not be empty (seed works should be written)"
    assert tables["authorship_edges"], "authorship_edges should not be empty"


def test_institutions_carries_country_code_for_foreign():
    """institutions really has country_code, and the foreign Stockholm (SE) institution is in the table (Zenou key-case safeguard)."""
    seed, refz = _monash_stockholm_works()
    tables = R.run_slice_tables(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS)
    insts = {r["institution_id"]: r for r in tables["institutions"]}
    # the real closure institutions.flatten_institution wrote the country_code column.
    assert all("country_code" in r for r in tables["institutions"])
    # Monash (AU) + Stockholm (SE) are both in the table; foreign institutions are not filtered at all.
    assert _MONASH_ID in insts and insts[_MONASH_ID]["country_code"] == "AU"
    assert _STOCKHOLM_ID in insts, "The Stockholm foreign institution must be in the institutions table (no in_au filter at all)"
    assert insts[_STOCKHOLM_ID]["country_code"] == "SE"


def test_work_text_carries_title():
    """work_text really has title (abstract_reverse.flatten_work_text is wired in)."""
    seed, refz = _monash_stockholm_works()
    tables = R.run_slice_tables(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS)
    by_id = {r["work_id"]: r for r in tables["work_text"]}
    assert all("title" in r for r in tables["work_text"])
    assert by_id["W_MS"]["title"] == "Network spillovers in economics"
    # abstract inversion is really wired in (inverted index -> readable string).
    assert by_id["W_MS"]["abstract_text"] == "Network spillovers"


def test_works_affil_carries_raw_affiliation_strings():
    """works_affil really has raw_affiliation_strings (what disambiguation depends on; the raw strings are kept as-is, not flattened)."""
    seed, refz = _monash_stockholm_works()
    tables = R.run_slice_tables(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS)
    assert all("raw_affiliation_strings" in r for r in tables["works_affil"])
    # the Zenou row carries the Monash raw affiliation strings (list<str> as-is).
    zenou_rows = [r for r in tables["works_affil"] if r["author_id"] == "A5017376589"]
    assert zenou_rows, "Yves Zenou's works_affil rows should be present"
    assert any("Monash University, Department of Economics" in r["raw_affiliation_strings"]
               for r in zenou_rows)


def test_authors_carries_orcid_for_zenou():
    """authors is really wired in (Zenou's ORCID lands in the authors table, via the real closure add_author)."""
    seed, refz = _monash_stockholm_works()
    tables = R.run_slice_tables(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS)
    by_id = {r["author_id"]: r for r in tables["authors"]}
    assert "A5017376589" in by_id
    assert by_id["A5017376589"]["orcid"] == "0000-0001-6516-0812"


def test_high4_foreign_coauthor_edge_kept():
    """Key case: the edge of the non-seed Stockholm collaborator A_STK inside the seed work is also written to authorship_edges."""
    seed, refz = _monash_stockholm_works()
    tables = R.run_slice_tables(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS)
    edge_authors = {r["author_id"] for r in tables["authorship_edges"]}
    assert "A5017376589" in edge_authors   # seed author Zenou
    assert "A_STK" in edge_authors, "Losing non-seed foreign collaborator edges = the HIGH-4 killer regression"


def test_frontier_refs_work_landed():
    """Pass-C re-scan: the cited W_REF is added to the works table (every frontier work is hit, none dangling)."""
    seed, refz = _monash_stockholm_works()
    tables = R.run_slice_tables(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS)
    work_ids = {r["work_id"] for r in tables["works"]}
    assert "W_MS" in work_ids
    assert "W_REF" in work_ids, "The frontier work should be added back to the works table by pass-C"


# ===========================================================================
# 3. Four-number reconcile (reconcile_m1 wired into run_m1)
# ===========================================================================
def test_compute_slice_tally_counts_balanced():
    """The four numbers are consistent: expected (external manifest ground truth) == kept + failed + skipped. expected is no longer counted from the scan itself."""
    seed, refz = _monash_stockholm_works()
    tables = R.run_slice_tables(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS)
    # fixture snapshot = W_MS (seed) + W_REF (frontier) = 2 works -> external manifest ground truth = 2.
    expected = REC.compute_expected_from_manifest(_manifest_works(2), entity="works")
    c = R.compute_slice_tally_counts(seed, tables, expected=expected)
    assert c["failed"] == 0
    assert c["expected"] == c["kept"] + c["failed"] + c["skipped"]
    # seed W_MS + frontier W_REF are both written -> kept=2, no skips.
    assert c["kept"] == 2 and c["skipped"] == 0


def test_reconcile_slice_passes_with_explicit_tolerance(tmp_path):
    """reconcile_slice with an explicit diff_tolerance=0 + the external manifest anchor -> the tally balances, and op_id_arm is honestly N/A."""
    seed, refz = _monash_stockholm_works()
    tables = R.run_slice_tables(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS)
    tally = R.reconcile_slice(
        seed, tables,
        stage="m1_ms_slice",
        tally_path=tmp_path / "tally.json",
        diff_tolerance=0,
        manifest=_manifest_works(2),   # W_MS + W_REF = 2 (external ground truth)
    )
    assert tally["balanced"] is True
    assert tally["op_id_arm"] == "N/A"


def test_reconcile_slice_unsigned_tolerance_raises(tmp_path):
    """diff_tolerance=None (unset red-line placeholder) -> RedlineUnsigned (a default of 0 is never substituted), even if the four numbers balance."""
    seed, refz = _monash_stockholm_works()
    tables = R.run_slice_tables(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS)
    with pytest.raises(RedlineUnsigned):
        R.reconcile_slice(
            seed, tables,
            stage="m1_ms_slice",
            tally_path=tmp_path / "tally.json",
            diff_tolerance=None,
            manifest=_manifest_works(2),
        )


def test_reconcile_slice_detects_manifest_drop_exits_15(tmp_path):
    """Anti-circularity anchor (slice path): the manifest says 5 works but the scan wrote only 1 -> the arithmetic arm does not match -> exit(TALLY_IMBALANCE=15).

    This is exactly the case the old "fake reconcile" missed: the old version counted expected from its own scan, so it always equalled kept+skipped and silently lost 4 works with no warning.
    The new version takes expected from the external manifest ground truth (=5), which does not match the scan (kept=1, skipped=0) -> HALT.
    """
    from identity.exit_codes import TALLY_IMBALANCE

    # One Monash seed work with no refs (no frontier -> no pass C): scan gives kept={W_SOLO}=1, seen=1, skipped=0.
    w_solo = _work(
        "W_SOLO", year=2016,
        authorships=[_au("A_M", institutions=[_inst(_MONASH_ID, country="AU")],
                         raw_affil=["Monash University, Department of Economics"])],
    )
    tables = R.run_slice_tables([w_solo], [], registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS)
    with pytest.raises(SystemExit) as ei:
        R.reconcile_slice(
            [w_solo], tables,
            stage="m1_drop_slice",
            tally_path=tmp_path / "tally.json",
            diff_tolerance=0,
            manifest=_manifest_works(5),   # external ground truth says 5 works, the scan has only 1 -> 4 missing -> HALT
        )
    assert ei.value.code == TALLY_IMBALANCE


def test_skipped_counts_pure_foreign_work(tmp_path):
    """A work entirely outside the department (no seed author) is not written to the tables -> counted as skipped, and the four numbers still balance (external manifest anchor)."""
    seed, refz = _monash_stockholm_works()
    # Add a pure-Stockholm work (no Monash author) -> not a seed, should be skipped.
    pure_foreign = _work(
        "W_PURE", year=2018, title="unrelated",
        authorships=[_au("A_X", institutions=[_inst(_STOCKHOLM_ID, country="SE")],
                         raw_affil=["Stockholm University"])],
    )
    seed2 = seed + [pure_foreign]
    tables = R.run_slice_tables(seed2, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS)
    # fixture snapshot = W_MS + W_PURE + W_REF = 3 -> external manifest ground truth = 3.
    expected = REC.compute_expected_from_manifest(_manifest_works(3), entity="works")
    c = R.compute_slice_tally_counts(seed2, tables, expected=expected)
    work_ids = {r["work_id"] for r in tables["works"]}
    assert "W_PURE" not in work_ids, "A work wholly outside the department should not be written to the works table"
    assert c["skipped"] >= 1, "A work wholly outside the department should count toward skipped"
    assert c["expected"] == c["kept"] + c["failed"] + c["skipped"]


def test_run_m1_slice_with_reconcile_flag_emits_tally(tmp_path):
    """run_m1_slice(reconcile=True, explicit tolerance) -> runs end to end and writes reconcile_tally.json."""
    pytest.importorskip("pyarrow")
    seed, refz = _monash_stockholm_works()
    R.run_m1_slice(
        seed, refz,
        registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=tmp_path,
        source_snapshot_merkle="MERKLE_MS", config_sha="CFG", rule_version="v", code_version="z",
        reconcile=True, reconcile_diff_tolerance=0,
        reconcile_manifest=_manifest_works(2),   # external ground-truth anchor (W_MS + W_REF = 2)
    )
    tally_path = tmp_path / "_manifest" / "reconcile_tally.json"
    assert tally_path.is_file(), "reconcile=True should write reconcile_tally.json"


def test_run_m1_slice_reconcile_requires_manifest_anchor(tmp_path):
    """run_m1_slice(reconcile=True) without reconcile_manifest -> ValueError (no external anchor = a fake reconcile)."""
    pytest.importorskip("pyarrow")
    seed, refz = _monash_stockholm_works()
    with pytest.raises(ValueError):
        R.run_m1_slice(
            seed, refz,
            registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
            out_root=tmp_path,
            source_snapshot_merkle="MERKLE_MS", config_sha="CFG", rule_version="v", code_version="z",
            reconcile=True, reconcile_diff_tolerance=0,   # reconcile_manifest missing -> refuse to proceed
        )


def test_run_m1_slice_reconcile_unsigned_tolerance_raises(tmp_path):
    """run_m1_slice(reconcile=True, tolerance=None) -> RedlineUnsigned is passed through (no tolerance is filled in)."""
    pytest.importorskip("pyarrow")
    seed, refz = _monash_stockholm_works()
    with pytest.raises(RedlineUnsigned):
        R.run_m1_slice(
            seed, refz,
            registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
            out_root=tmp_path,
            source_snapshot_merkle="MERKLE_MS", config_sha="CFG", rule_version="v", code_version="z",
            reconcile=True, reconcile_diff_tolerance=None,
            reconcile_manifest=_manifest_works(2),
        )


# ===========================================================================
# 4. HashBucketWriter bucketed write (write_tables_bucketed: deterministic + 10 tables)
# ===========================================================================
def test_write_tables_bucketed_lands_all_ten(tmp_path):
    """write_tables_bucketed writes the 10 tables with HashBucketWriter; each table produces a part manifest (row counts match)."""
    pytest.importorskip("pyarrow")
    seed, refz = _monash_stockholm_works()
    tables = R.run_slice_tables(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS)
    manifest = R.write_tables_bucketed(tables, tmp_path)
    assert set(manifest.keys()) == set(_TEN_TABLES)
    # the sum of rows over the works-table parts == the in-memory works row count.
    works_part_rows = sum(p["row_count"] for p in manifest["works"])
    assert works_part_rows == len(tables["works"])
    # every part wrote a real file.
    for name, parts in manifest.items():
        for part in parts:
            assert (tmp_path / name / part["rel_path"]).is_file()


def test_write_tables_bucketed_deterministic(tmp_path):
    """Two bucketed writes of the same slice -> the (rel_path, sha256) of every table's parts are identical (deterministic reproduction)."""
    pytest.importorskip("pyarrow")
    seed, refz = _monash_stockholm_works()
    tables = R.run_slice_tables(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS)
    mf_a = R.write_tables_bucketed(tables, tmp_path / "runA")
    mf_b = R.write_tables_bucketed(tables, tmp_path / "runB")
    for name in _TEN_TABLES:
        sig_a = [(p["rel_path"], p["sha256"]) for p in mf_a[name]]
        sig_b = [(p["rel_path"], p["sha256"]) for p in mf_b[name]]
        assert sig_a == sig_b, f"Table {name}: bucketed part sha differs between the two runs (non-deterministic)"
