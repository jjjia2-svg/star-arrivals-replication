"""io_load — step 1: input loading and precondition checks, red tests (the 5 points of step 1 plus the matching numbered items).

Covers:
  (1) per-table assert_matches_schema contract gate (extra/missing columns raise)          — point 1
  (2) star_set keyed by author_id -> folded to person_id through person_map;
     stars whose fragment has no mapping are counted + WARN, not silent (as in #33), and author_id is never used as a placeholder — point 2
  (3) paper_contrib entry assertion on the article+review domain (other types mixed in -> raise, #40c precondition layer) — point 3
  (4) refs_edges has no year -> the cutoff precondition assertion raises (H4, #6b — see test_cutoff)     — point 4
  (5) upstream provenance mismatch -> HALT (ProvenanceMismatch)          — point 5
  Also: #15 the refs_edges column name is referenced_work_id (writing ref_work_id -> rejected by the contract gate);
      events.t_minus_1 missing -> raise (B-EVENTS-T1 fail loud);
      p_level mapping fixed (p01 <=> is_star_1pct / p05 <=> is_star_5pct / anything else -> raise);
      a thin-circle None flag != star;
      the three dose red-line keys are read at their fixed values (cosine/0.0/0.0).
"""
from __future__ import annotations

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from common.manifest import ProvenanceMismatch
from common.schema import (
    AUTHORSHIP_EDGES,
    EVENTS,
    PAPER_CONTRIB,
    PERSON_MAP,
    REFS_EDGES,
    SchemaMismatchError,
    STAR_SET,
    WORKS,
    WORK_TEXT,
)
from m1_ingest._writer_util import write_rows_parquet

from m4_dose import io_load


# ---------------------------------------------------------------------------
# write helper: synthetic upstream parquet (through the deterministic U1 writer = the same way upstream writes)
# ---------------------------------------------------------------------------
def _write(rows, path, schema, pk, label):
    write_rows_parquet(rows, path, schema=schema, pk_cols=pk, label=label)


def _write_raw(rows_dict, path):
    """Bypass the schema gate and write a "bad parquet" directly (to build extra-column / missing-column / wrong-name scenarios)."""
    pq.write_table(pa.table(rows_dict), str(path))


# ---------------------------------------------------------------------------
# (1) contract gate: key sets exactly equal
# ---------------------------------------------------------------------------
def test_load_table_exact_schema_gate_extra_column(tmp_path, mk):
    """authorship_edges with one extra column raw_affil -> SchemaMismatchError (the contract fixes 3 columns)."""
    bad = tmp_path / "authorship_edges.parquet"
    _write_raw(
        {"work_id": ["W1"], "author_id": ["A1"], "publication_year": [2015],
         "raw_affil": ["Monash"]},
        bad,
    )
    with pytest.raises(SchemaMismatchError):
        io_load.load_table(bad, AUTHORSHIP_EDGES, label="authorship_edges")


def test_load_table_exact_schema_gate_missing_column(tmp_path):
    """refs_edges missing referenced_work_id -> SchemaMismatchError."""
    bad = tmp_path / "refs_edges.parquet"
    _write_raw({"work_id": ["W1"]}, bad)
    with pytest.raises(SchemaMismatchError):
        io_load.load_table(bad, REFS_EDGES, label="refs_edges")


def test_refs_edges_wrong_column_name_rejected(tmp_path):
    """#15: the column is named ref_work_id (not the official anchor referenced_work_id) -> rejected by the contract gate."""
    bad = tmp_path / "refs_edges.parquet"
    _write_raw({"work_id": ["W1"], "ref_work_id": ["W9"]}, bad)
    with pytest.raises(SchemaMismatchError):
        io_load.load_table(bad, REFS_EDGES, label="refs_edges")


def test_load_table_roundtrip_ok(tmp_path, mk):
    """A good table is read back as is (key set exact, row count equal)."""
    good = tmp_path / "authorship_edges.parquet"
    rows = [mk.edge("W1", "A1", 2015), mk.edge("W1", "A2", 2015)]
    _write(rows, good, AUTHORSHIP_EDGES, ("work_id", "author_id"), "authorship_edges")
    out = io_load.load_table(good, AUTHORSHIP_EDGES, label="authorship_edges")
    assert len(out) == 2
    assert set(out[0].keys()) == set(AUTHORSHIP_EDGES.keys())


# ---------------------------------------------------------------------------
# (2) star_set: keyed by author_id -> folded through person_map; no mapping is not silent
# ---------------------------------------------------------------------------
@pytest.mark.depends_on_u4
def test_star_set_folds_author_id_via_person_map(mk):
    """Cross-check: star_set currently has 14 columns keyed by author_id -> the linking layer folds to person_id through person_map."""
    stars = [mk.star("A_S1"), mk.star("A_S2", is_star_1pct=False, is_star_5pct=True)]
    pm = [mk.pm("A_S1", "P_S1"), mk.pm("A_S2", "P_S2")]
    pids, n_unmapped = io_load.fold_star_person_ids(stars, pm, p_level="p01")
    assert pids == {"P_S1"}
    assert n_unmapped == 0
    pids5, _ = io_load.fold_star_person_ids(stars, pm, p_level="p05")
    assert pids5 == {"P_S1", "P_S2"}


@pytest.mark.depends_on_u4
def test_unmapped_star_fragment_counted_and_warned(mk):
    """As in #33: a star author_id with no person_map mapping -> counted + WARN, never silent, and author_id is never used as a placeholder."""
    stars = [mk.star("A_S1"), mk.star("A_HOLE")]
    pm = [mk.pm("A_S1", "P_S1")]  # A_HOLE has no mapping
    with pytest.warns(UserWarning, match="unmapped"):
        pids, n_unmapped = io_load.fold_star_person_ids(stars, pm, p_level="p01")
    assert pids == {"P_S1"}          # contains no author_id placeholder
    assert "A_HOLE" not in pids      # never fall back to author_id
    assert n_unmapped == 1


@pytest.mark.depends_on_u4
def test_star_flag_none_is_not_star(mk):
    """Thin-circle people (not in the pool) have is_star_1pct=None — None != True, so they do not enter the star set (schema [22] note)."""
    stars = [mk.star("A_THIN", is_star_1pct=None, is_star_5pct=None, cell_n=None)]
    pm = [mk.pm("A_THIN", "P_THIN")]
    pids, n_unmapped = io_load.fold_star_person_ids(stars, pm, p_level="p01")
    assert pids == set()
    assert n_unmapped == 0


def test_p_level_mapping_pinned(mk):
    """Fixed column mapping: p01 <=> is_star_1pct / p05 <=> is_star_5pct; any other p_level -> raise (as in #31)."""
    stars = [mk.star("A_S1")]
    pm = [mk.pm("A_S1", "P_S1")]
    with pytest.raises(ValueError):
        io_load.fold_star_person_ids(stars, pm, p_level="p10")


# ---------------------------------------------------------------------------
# (3) paper_contrib entry assertion on the article+review domain (caveat#4 inherited, not re-filtered)
# ---------------------------------------------------------------------------
@pytest.mark.depends_on_u4
def test_paper_contrib_non_article_review_raises(mk):
    """#40c precondition layer: a work with work_type=dataset mixed into paper_contrib -> raise (neither silent nor allowed through)."""
    works = [mk.work("W1", 2015), mk.work("W2", 2015, work_type="dataset")]
    pc = [mk.pc("W1", "P_I", "P_I", 2015), mk.pc("W2", "P_I", "P_I", 2015)]
    with pytest.raises(io_load.DomainViolation):
        io_load.assert_article_review_domain(pc, works)


@pytest.mark.depends_on_u4
def test_paper_contrib_workid_missing_in_works_raises(mk):
    """The domain check finds no such work -> raise (an unknown type means cleanliness cannot be proven; fail loud, do not allow)."""
    works = [mk.work("W1", 2015)]
    pc = [mk.pc("W_GHOST", "P_I", "P_I", 2015)]
    with pytest.raises(io_load.DomainViolation):
        io_load.assert_article_review_domain(pc, works)


@pytest.mark.depends_on_u4
def test_paper_contrib_clean_domain_passes(mk):
    """All article/review -> passes (review is also in FWCI_INCLUDED_TYPES, caveat#4)."""
    works = [mk.work("W1", 2015), mk.work("W2", 2015, work_type="review")]
    pc = [mk.pc("W1", "P_I", "P_I", 2015), mk.pc("W2", "P_I", "P_I", 2015)]
    io_load.assert_article_review_domain(pc, works)  # passes if nothing raises


# ---------------------------------------------------------------------------
# (5) upstream provenance check: mismatch -> HALT
# ---------------------------------------------------------------------------
@pytest.mark.depends_on_u4
def test_provenance_mismatch_halts(tmp_path):
    """The star_set manifest_header four-tuple differs from the expected one -> ProvenanceMismatch (HALT, not WARN)."""
    import json

    header = {
        "source_snapshot_merkle": "m_aaa", "config_sha": "c_bbb",
        "rule_version": "u4_v4_signed", "stars_set_hash": "s_ccc",
    }
    header_path = tmp_path / "manifest_header.json"
    header_path.write_text(json.dumps(header), encoding="utf-8")
    expected_bad = dict(header, config_sha="c_DIFFERENT")
    with pytest.raises(ProvenanceMismatch):
        io_load.check_upstream_provenance(header_path, expected_bad)
    # all equal -> allowed through
    io_load.check_upstream_provenance(header_path, dict(header))


@pytest.mark.depends_on_u4
def test_provenance_header_missing_halts(tmp_path):
    """Expected provenance given but no manifest_header.json on disk -> also HALT (no header = the origin cannot be proven)."""
    with pytest.raises(ProvenanceMismatch):
        io_load.check_upstream_provenance(tmp_path / "manifest_header.json",
                                          {"config_sha": "x"})


# ---------------------------------------------------------------------------
# events: missing t_minus_1 fails loud (B-EVENTS-T1)
# ---------------------------------------------------------------------------
@pytest.mark.depends_on_u4
def test_events_missing_t_minus_1_raises(mk):
    """events row with t_minus_1=None -> raise (the single source of the M4 freeze point is missing; never fall back to computing arrival-1)."""
    ev = [mk.event("E1", "P_S1", 2016, None)]
    with pytest.raises(ValueError):
        io_load.assert_events_have_t_minus_1(ev)


@pytest.mark.depends_on_u4
def test_events_with_t_minus_1_pass(mk):
    ev = [mk.event("E1", "P_S1", 2016, 2015)]
    io_load.assert_events_have_t_minus_1(ev)  # does not raise


# ---------------------------------------------------------------------------
# the three dose red-line keys: read at their fixed values (the code only consumes them)
# ---------------------------------------------------------------------------
def test_dose_redlines_signed_values_readable():
    """Fixed values replace the old test that guarded the placeholder state:
    the three dose keys in redlines.yaml = cosine / 0.0 / 0.0 -> require() reads the real values directly and no longer raises.

    The test is a sentinel: it goes red as soon as a value drifts.
    Changing these three values means editing the red-line config, never code.
    """
    from common._redlines import RED, require

    assert RED["dose"]["coupling_normalization"] == "cosine"
    assert RED["dose"]["hub_ref_idf_floor"] == 0.0
    assert RED["dose"]["coverage_floor"] == 0.0
    assert require("dose", "coupling_normalization") == "cosine"
    assert require("dose", "hub_ref_idf_floor") == 0.0
    assert require("dose", "coverage_floor") == 0.0


# ---------------------------------------------------------------------------
# whole load: load_u5_inputs (handle + validation report)
# ---------------------------------------------------------------------------
@pytest.mark.depends_on_u4
def test_load_u5_inputs_end_to_end(tmp_path, mk):
    """A full synthetic upstream -> the handle contains 8 tables + both levels of star_pids + all precondition checks pass."""
    d = tmp_path
    _write([mk.edge("W1", "A_I1", 2014), mk.edge("W1", "A_S1", 2014)],
           d / "authorship_edges.parquet", AUTHORSHIP_EDGES,
           ("work_id", "author_id"), "authorship_edges")
    _write([mk.ref("W1", "W_R1")], d / "refs_edges.parquet", REFS_EDGES,
           ("work_id", "referenced_work_id"), "refs_edges")
    _write([mk.work("W1", 2014)], d / "works.parquet", WORKS, ("work_id",), "works")
    _write([mk.text("W1")], d / "work_text.parquet", WORK_TEXT, ("work_id",), "work_text")
    _write([mk.pm("A_I1", "P_I1"), mk.pm("A_S1", "P_S1")],
           d / "person_map.parquet", PERSON_MAP, ("author_id",), "person_map")
    _write([mk.star("A_S1")], d / "star_set.parquet", STAR_SET, ("author_id",), "star_set")
    _write([mk.event("E1", "P_S1", 2016, 2015)], d / "events.parquet", EVENTS,
           ("event_id",), "events")
    _write([mk.pc("W1", "P_I1", "P_I1", 2014)], d / "paper_contrib.parquet",
           PAPER_CONTRIB, ("work_id", "incumbent_person_id", "person_id"), "paper_contrib")

    paths = {
        "authorship_edges": d / "authorship_edges.parquet",
        "refs_edges": d / "refs_edges.parquet",
        "works": d / "works.parquet",
        "work_text": d / "work_text.parquet",
        "person_map": d / "person_map.parquet",
        "star_set": d / "star_set.parquet",
        "events": d / "events.parquet",
        "paper_contrib": d / "paper_contrib.parquet",
    }
    inputs = io_load.load_u5_inputs(paths)
    assert inputs.star_pids["p01"] == {"P_S1"}
    assert inputs.star_pids["p05"] == {"P_S1"}
    assert inputs.n_unmapped_star_authors == 0
    assert len(inputs.events) == 1
    assert inputs.events[0]["t_minus_1"] == 2015
    assert len(inputs.paper_contrib) == 1
    # report fields are present (diagnostics go into the report, not mixed into data rows)
    assert inputs.report["n_star_rows"] == 1
