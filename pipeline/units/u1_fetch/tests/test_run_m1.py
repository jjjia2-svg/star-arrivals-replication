"""Tests for run_m1.py: the M1 main orchestration (snapshot -> canonical -> write tables -> reconcile -> freeze + provenance).

Behaviour covered:
  - If the entry-time Merkle check fails -> exit(EXIT_MERKLE_INVALID=23).
  - A field probe with a required key missing -> exit(EXIT_FIELDS_MISSING=19); all present -> PASS.
  - Canonical before dedup: the canonical map is built first and tables are written with canonical ids
    (one person does not split).
  - Cross-four-table canonical-space guard: any foreign key not a subset of the same space ->
    exit(EXIT_CANONICAL_SPACE_SPLIT=22).
  - run_manifest.json: source_snapshot_merkle == the M0 merkle_root, otherwise HALT(PROVENANCE_MISMATCH);
    it holds config_sha/rule_version/code_version + each table's sha and row_count.
  - Each table gets a provenance.json sidecar (atomic write, not in the COMMIT set).
  - Determinism: two runs on the same slice give the same per-table sha.

Discipline: all tests use fixture / small-sample works JSON to test orchestration and never download from
S3. Output goes to tmp_path. Exit codes are always named constants (no bare numbers). Assertions that depend
on pyarrow use importorskip.
"""
from __future__ import annotations

import json

import pytest

from m1_ingest import run_m1 as R
from identity.exit_codes import (
    EXIT_MERKLE_INVALID,
    EXIT_FIELDS_MISSING,
    EXIT_CANONICAL_SPACE_SPLIT,
)
from common.manifest import ProvenanceMismatch


# ---------------------------------------------------------------------------
# fixture: minimal works (one in-department author + one outside collaborator; includes a refs frontier)
# ---------------------------------------------------------------------------
_REGISTRY = [{"openalex_id": "I_ECON", "type": "education"}]
_ECON_DEPT_IDS = {"I_ECON"}


def _inst(inst_id, *, country="AU", itype="education", lineage=None):
    return {
        "id": f"https://openalex.org/{inst_id}",
        "display_name": inst_id,
        "country_code": country,
        "type": itype,
        "lineage": lineage or [f"https://openalex.org/{inst_id}"],
    }


def _au(author_id, *, institutions, raw_affil=None):
    return {
        "author": {"id": f"https://openalex.org/{author_id}", "display_name": author_id, "orcid": None},
        "institutions": institutions,
        "raw_affiliation_strings": raw_affil or [],
    }


def _work(wid, *, year=2010, refs=None, authorships=None, subfield="2002", wtype="article"):
    return {
        "id": f"https://openalex.org/{wid}",
        "publication_year": year,
        "title": f"paper {wid}",
        "type": wtype,
        "cited_by_count": 7,
        "referenced_works": [f"https://openalex.org/{r}" for r in (refs or [])],
        "primary_topic": {"subfield": {"id": f"https://openalex.org/subfields/{subfield}"}},
        "authorships": authorships or [],
    }


def _seed_works():
    """Seed work W1 (in-department A_SEED + outside A_CO), citing W_REF (the frontier)."""
    w1 = _work(
        "W1", year=2010, refs=["W_REF"],
        authorships=[
            _au("A_SEED", institutions=[_inst("I_ECON")], raw_affil=["Econ Dept"]),
            _au("A_CO", institutions=[_inst("I_FOREIGN", country="US")], raw_affil=["Foreign U"]),
        ],
    )
    w_ref = _work("W_REF", year=2005, authorships=[_au("A_OTHER", institutions=[_inst("I_FOREIGN", country="US")])])
    return [w1], [w_ref]   # (pass A/B shards, pass C re-scan shards)


# ===========================================================================
# Entry-time Merkle check
# ===========================================================================
def test_entry_merkle_mismatch_exits(monkeypatch):
    """Entry-time Merkle mismatch -> exit(EXIT_MERKLE_INVALID=23)."""
    def _boom(*a, **k):
        import sys
        sys.exit(EXIT_MERKLE_INVALID)
    monkeypatch.setattr(R, "assert_entry_merkle", _boom)
    with pytest.raises(SystemExit) as ei:
        R.preflight_entry(snapshot_root="/nonexistent", entities=("works",))
    assert ei.value.code == EXIT_MERKLE_INVALID


# ===========================================================================
# Field probe
# ===========================================================================
def test_field_probe_missing_key_exits():
    """A required key is missing (no primary_topic) -> exit(EXIT_FIELDS_MISSING=19)."""
    bad = [{"id": "https://openalex.org/Wx", "publication_year": 2010, "type": "article",
            "cited_by_count": 1, "referenced_works": [], "authorships": []}]  # primary_topic missing
    with pytest.raises(SystemExit) as ei:
        R.field_probe(bad)
    assert ei.value.code == EXIT_FIELDS_MISSING


def test_field_probe_all_present_passes():
    """All required keys present -> field_probe does not exit."""
    seed, _ = _seed_works()
    R.field_probe(seed)  # no raise = PASS


# ===========================================================================
# canonical-before-dedup + canonical-space guard
# ===========================================================================
def test_canonical_space_guard_passes_on_consistent_keys():
    """Foreign keys of all four tables land in the same canonical space -> the guard does not exit."""
    tables = {
        "authors": [{"author_id": "A1", "display_name": "x", "orcid": None}],
        "authorship_edges": [{"work_id": "W1", "author_id": "A1", "publication_year": 2010}],
        "work_first_pub": [{"author_id": "A1", "first_pub_year": 2010, "first_pub_year_is_full_history": True}],
        "works_affil": [{"work_id": "W1", "author_id": "A1", "institution_id": "I1", "raw_affiliation_strings": []}],
        "institutions": [{"institution_id": "I1", "display_name": "x", "country_code": "AU",
                          "type": "education", "lineage": [], "associated_institutions": [], "ror": None}],
    }
    R.assert_canonical_space(tables)  # no raise


def test_canonical_space_guard_fails_when_edge_author_not_in_authors():
    """authorship_edges.author_id is not a subset of authors -> exit(EXIT_CANONICAL_SPACE_SPLIT=22)."""
    tables = {
        "authors": [{"author_id": "A1", "display_name": "x", "orcid": None}],
        "authorship_edges": [{"work_id": "W1", "author_id": "A_GHOST", "publication_year": 2010}],
        "work_first_pub": [],
        "works_affil": [],
        "institutions": [],
    }
    with pytest.raises(SystemExit) as ei:
        R.assert_canonical_space(tables)
    assert ei.value.code == EXIT_CANONICAL_SPACE_SPLIT


def test_canonical_space_guard_fails_when_affil_inst_not_in_institutions():
    """works_affil.institution_id is not a subset of institutions -> exit(EXIT_CANONICAL_SPACE_SPLIT=22)."""
    tables = {
        "authors": [{"author_id": "A1", "display_name": "x", "orcid": None}],
        "authorship_edges": [],
        "work_first_pub": [],
        "works_affil": [{"work_id": "W1", "author_id": "A1", "institution_id": "I_GHOST", "raw_affiliation_strings": []}],
        "institutions": [{"institution_id": "I1", "display_name": "x", "country_code": "AU",
                          "type": "education", "lineage": [], "associated_institutions": [], "ror": None}],
    }
    with pytest.raises(SystemExit) as ei:
        R.assert_canonical_space(tables)
    assert ei.value.code == EXIT_CANONICAL_SPACE_SPLIT


def test_canonical_space_guard_ignores_none_institution():
    """works_affil.institution_id=None (a fallback row for failed institution resolution) does not count as a space split (None does not enter the subset check)."""
    tables = {
        "authors": [{"author_id": "A1", "display_name": "x", "orcid": None}],
        "authorship_edges": [],
        "work_first_pub": [],
        "works_affil": [{"work_id": "W1", "author_id": "A1", "institution_id": None, "raw_affiliation_strings": ["x"]}],
        "institutions": [],
    }
    R.assert_canonical_space(tables)  # a None-institution fallback row does not trip the guard


# ===========================================================================
# canonical merge: one person's two raw ids fold to the same canonical id (canonical before dedup)
# ===========================================================================
def test_canonical_applied_before_write_merges_split_ids():
    """One person A_OLD->A_NEW is merged -> after writing, authors has only one row A_NEW (no split)."""
    # A_OLD and A_NEW are the same person; cmap folds A_OLD to A_NEW.
    w = _work("W1", year=2010, authorships=[
        _au("A_OLD", institutions=[_inst("I_ECON")], raw_affil=["Econ"]),
    ])
    w2 = _work("W2", year=2012, authorships=[
        _au("A_NEW", institutions=[_inst("I_ECON")], raw_affil=["Econ"]),
    ])
    merged_rows = [{"raw_id": "A_OLD", "canonical_id": "A_NEW"}]
    tables = R.run_slice_tables(
        [w, w2], [],
        registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        author_merged_rows=merged_rows,
    )
    author_ids = [r["author_id"] for r in tables["authors"]]
    assert "A_NEW" in author_ids
    assert "A_OLD" not in author_ids, "A_OLD should already be folded into A_NEW (canonical before dedup)"
    # first_pub takes the min after the merge: the first-publication year of A_NEW = 2010 (W1), not 2012.
    fp = {r["author_id"]: r["first_pub_year"] for r in tables["work_first_pub"]}
    assert fp["A_NEW"] == 2010


# ===========================================================================
# run_manifest + provenance sidecar written to disk
# ===========================================================================
def test_run_manifest_emitted_with_provenance_and_table_shas(tmp_path):
    """Writes run_manifest.json: source_snapshot_merkle + config_sha/rule_version/code_version + each table's sha and row_count."""
    pytest.importorskip("pyarrow")
    seed, refz = _seed_works()
    out = R.run_m1_slice(
        seed, refz,
        registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=tmp_path,
        source_snapshot_merkle="MERKLE_ABC",
        config_sha="CFG1", rule_version="m1_v1", code_version="codeX",
    )
    mf_path = tmp_path / "_manifest" / "run_manifest.json"
    assert mf_path.is_file()
    mf = json.loads(mf_path.read_text(encoding="utf-8"))
    assert mf["source_snapshot_merkle"] == "MERKLE_ABC"
    assert mf["config_sha"] == "CFG1" and mf["rule_version"] == "m1_v1" and mf["code_version"] == "codeX"
    # each table's sha + row_count is present.
    assert "tables" in mf and "works" in mf["tables"]
    assert "sha256" in mf["tables"]["works"] and "row_count" in mf["tables"]["works"]
    assert out["source_snapshot_merkle"] == "MERKLE_ABC"


def test_run_manifest_halts_on_merkle_mismatch(tmp_path):
    """source_snapshot_merkle != the expected M0 merkle -> HALT(ProvenanceMismatch=13)."""
    pytest.importorskip("pyarrow")
    seed, refz = _seed_works()
    with pytest.raises(ProvenanceMismatch):
        R.run_m1_slice(
            seed, refz,
            registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
            out_root=tmp_path,
            source_snapshot_merkle="MERKLE_ABC",
            expected_snapshot_merkle="MERKLE_DIFFERENT",   # M0 frozen root does not match
            config_sha="CFG1", rule_version="m1_v1", code_version="codeX",
        )


def test_provenance_sidecar_per_table_not_in_commit(tmp_path):
    """Each table gets a provenance.json sidecar (atomic write); no COMMIT/_frozen is created (the sidecar is not in the COMMIT set)."""
    pytest.importorskip("pyarrow")
    seed, refz = _seed_works()
    R.run_m1_slice(
        seed, refz,
        registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        out_root=tmp_path,
        source_snapshot_merkle="MERKLE_ABC",
        config_sha="CFG1", rule_version="m1_v1", code_version="codeX",
    )
    side = tmp_path / "works" / "provenance.json"
    assert side.is_file(), "The works table must have a provenance.json sidecar"
    prov = json.loads(side.read_text(encoding="utf-8"))
    assert prov["source_snapshot_merkle"] == "MERKLE_ABC"
    assert prov["table"] == "works"
    # The sidecar is not in COMMIT: there must be no _frozen/COMMIT marker (provenance is a side channel, not part of the frozen set).
    assert not (tmp_path / "works" / "_frozen" / "COMMIT").exists()


# ===========================================================================
# Determinism: two runs give the same per-table sha
# ===========================================================================
def test_two_runs_identical_table_shas(tmp_path):
    """Two runs on the same slice -> the per-table sha in run_manifest is identical (deterministic reproduction)."""
    pytest.importorskip("pyarrow")
    seed, refz = _seed_works()
    a = tmp_path / "runA"
    b = tmp_path / "runB"
    out_a = R.run_m1_slice(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
                           out_root=a, source_snapshot_merkle="M", config_sha="C",
                           rule_version="v", code_version="z")
    out_b = R.run_m1_slice(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
                           out_root=b, source_snapshot_merkle="M", config_sha="C",
                           rule_version="v", code_version="z")
    for tbl in out_a["tables"]:
        assert out_a["tables"][tbl]["sha256"] == out_b["tables"][tbl]["sha256"], (
            f"Table {tbl}: sha differs between the two runs (non-deterministic)"
        )


# ===========================================================================
# Key case: edges of non-seed collaborators inside a seed work are also written to authorship_edges
# ===========================================================================
def test_high4_nonseed_coauthor_edge_kept(tmp_path):
    """The edge of the non-seed collaborator A_CO inside seed work W1 must also be in authorship_edges."""
    pytest.importorskip("pyarrow")
    seed, refz = _seed_works()
    tables = R.run_slice_tables(seed, refz, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS)
    edge_authors = {r["author_id"] for r in tables["authorship_edges"]}
    assert "A_SEED" in edge_authors
    assert "A_CO" in edge_authors, "Losing non-seed collaborator edges = the HIGH-4 killer regression"
