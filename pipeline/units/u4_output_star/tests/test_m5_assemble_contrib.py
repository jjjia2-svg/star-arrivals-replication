"""U4 first shipment wave: the production assembler m5_output/assemble_contrib (synthetic data, no SSD).

In plain words: the pure-function parts of paper_contrib already exist (frac_credit / 8-key row / compute_fwci /
the three safeguards for the subfield-to-field fallback). What was missing is the production assembler that scans
U1 works × authorship_edges and feeds those parts. This file tests:
  1. DuckDB read-only scan: every work of each incumbent (roster person) of the two schools, plus its full author set
  2. Per-work 8-key row assembly (stage one of the two-stage isc = False) + fwci (expected from fwci_baseline
     + pass-through of the field-level fallback) + a diagnostics sidecar row
  3. No winsorization step: fwci passes through as is (nothing is capped); a tombstone assertion guards against
     its revival, and the legacy winsorize_pct key is never consumed
  4. Two-stage isc backfill: frozen star_set (keyed by author_id) → folded to person via person_map →
     intersected with the work's author set (single definition identity.output_rule.is_star_coauthored, isc#2)
"""
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from common._redlines import RED

EDGES_SUB = "u1_edges_full_2026-07-05"


def _work_row(wid, *, year=2010, subfield="2002", wtype="article", cites=10,
              paratext=False, native=1.5):
    """One row of the U1 works table (only the 7 columns M5 consumes; the real table has 12, and a SELECT by column name is unaffected)."""
    return {"work_id": wid, "publication_year": year, "subfield_id": subfield,
            "work_type": wtype, "cited_by_count": cites, "is_paratext": paratext,
            "fwci": native}


def _mk_root(tmp_path, works, edges):
    """Synthetic derived_root: works + authorship_edges (single-file data.parquet layout)."""
    root = tmp_path / "derived"
    for name, rows in (("works", works), ("authorship_edges", edges)):
        d = root / EDGES_SUB / name
        d.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows), str(d / "data.parquet"))
    return root


def _edge(wid, aid, year=2010):
    return {"work_id": wid, "author_id": aid, "publication_year": year}


# Fixture population: P1 = incumbent (author A1); P2 = outside co-author (A2); A3 = no person mapping.
_AP = {"A1": "P1", "A2": "P2"}
_EXP = {("2002", 2010, "article"): 5.0}


def _std_fixture(tmp_path):
    """W1 incumbent + 2 co-authors (fwci computable); W2 no incumbent (must not be scanned in);
    W3 excluded_type; W4 missing_cell; W5 paratext."""
    works = [
        _work_row("W1", cites=10, native=1.5),
        _work_row("W2", cites=99),
        _work_row("W3", wtype="editorial", native=None),
        _work_row("W4", year=2012),
        _work_row("W5", paratext=True),
    ]
    edges = [
        _edge("W1", "A1"), _edge("W1", "A2"), _edge("W1", "A3"),
        _edge("W2", "A2"),
        _edge("W3", "A1"), _edge("W4", "A1"), _edge("W5", "A1"),
    ]
    return _mk_root(tmp_path, works, edges)


def _assemble(root, **kw):
    from m5_output.assemble_contrib import assemble_paper_contrib

    return assemble_paper_contrib(
        root, incumbent_person_ids={"P1"}, author_person=dict(_AP),
        expected_by_cell=dict(_EXP), edges_sub=EDGES_SUB, **kw)


# ---- 1. scan + row granularity ------------------------------------------------

def test_assemble_rows_grain_frac_and_stage1_isc(tmp_path):
    """W1: 3 authorships (A3 has no mapping but still counts in the frac denominator) → frac=1/3; rows = incumbent P1 × mapped {P1,P2};
    W2 has no incumbent → not scanned in (no rows, no diagnostics); stage one of the two-stage isc is all False; rows follow the 8 keys of schema [18]."""
    from common.schema import PAPER_CONTRIB, assert_matches_schema

    res = _assemble(_std_fixture(tmp_path))
    w1 = [r for r in res["rows"] if r["work_id"] == "W1"]
    assert len(w1) == 2
    assert {(r["incumbent_person_id"], r["person_id"]) for r in w1} == {("P1", "P1"), ("P1", "P2")}
    assert all(r["frac_credit"] == pytest.approx(1 / 3) for r in w1)
    assert all(r["is_star_coauthored"] is False for r in w1), "in the two-stage scheme, isc is always False in the first stage"
    assert not any(r["work_id"] == "W2" for r in res["rows"]), "a work with no incumbent is not included"
    assert not any(d["work_id"] == "W2" for d in res["diag"])
    for r in res["rows"]:
        assert_matches_schema(r.keys(), PAPER_CONTRIB, label="paper_contrib")


def test_assemble_fwci_wiring_hit_and_na_reasons(tmp_path):
    """expected hit → fwci=cites/expected; missing cell / not whitelisted / paratext → None + reason
    (missing = NA, never 0); NA rows are still written to the main table (fwci column empty)."""
    res = _assemble(_std_fixture(tmp_path))
    by_w = {r["work_id"]: r for r in res["rows"]}
    dg = {d["work_id"]: d for d in res["diag"]}
    assert by_w["W1"]["fwci"] == 2.0                       # 10 / 5.0
    assert by_w["W3"]["fwci"] is None
    assert dg["W3"]["fwci_missing_reason"] == "excluded_type"
    assert by_w["W4"]["fwci"] is None
    assert dg["W4"]["fwci_missing_reason"] == "missing_cell"
    assert by_w["W5"]["fwci"] is None
    assert dg["W5"]["fwci_missing_reason"] == "paratext"


def test_assemble_diag_sidecar_semantics(tmp_path):
    """Diagnostics row, 5 keys: fwci_native = the native works.fwci passed through for comparison; fwci_incomplete = (fwci is None);
    inferred defaults to False (the fallback did not fire)."""
    res = _assemble(_std_fixture(tmp_path))
    dg = {d["work_id"]: d for d in res["diag"]}
    assert set(dg) == {"W1", "W3", "W4", "W5"}
    assert dg["W1"]["fwci_native"] == 1.5
    assert dg["W1"]["fwci_incomplete"] is False
    assert dg["W1"]["fwci_missing_reason"] is None
    assert dg["W4"]["fwci_incomplete"] is True
    assert all(d["fwci_inferred_fallback"] is False for d in dg.values())


def test_assemble_s84_field_fallback_passthrough(tmp_path):
    """Missing subfield → field-level denominator fallback + [inferred] flag: the assembler passes
    field_expected/field_of_work through to compute_fwci, and the diagnostics row carries inferred=True."""
    works = [_work_row("W6", subfield=None, cites=8)]
    edges = [_edge("W6", "A1")]
    root = _mk_root(tmp_path, works, edges)
    res = _assemble(root, field_expected={("20", 2010, "article"): 4.0},
                    field_of_work=lambda w: "20")
    (row,) = [r for r in res["rows"] if r["work_id"] == "W6"]
    assert row["fwci"] == 2.0                              # 8 / 4.0 — field-level denominator
    (d,) = res["diag"]
    assert d["fwci_inferred_fallback"] is True


def test_assemble_deterministic_two_runs(tmp_path):
    """Same input assembled twice → rows identical in order and value (works sorted by work_id; person order fixed inside the pure function)."""
    root = _std_fixture(tmp_path)
    assert _assemble(root) == _assemble(root)


def test_assemble_fail_loud_when_edge_points_to_missing_work(tmp_path):
    """edges point to a work that is not in works → ValueError, fail loud
    (upstream integrity is broken; never skip silently — a silent error is the worst failure here)."""
    root = _mk_root(tmp_path, [_work_row("W1")],
                    [_edge("W1", "A1"), _edge("W_GONE", "A1")])
    with pytest.raises(ValueError, match="W_GONE"):
        _assemble(root)


def test_assemble_fail_loud_when_no_incumbent_authors(tmp_path):
    """The incumbent set folds to no author_id in person_map → ValueError (empty scan scope = assembly failure;
    never silently produce a 0-row table)."""
    from m5_output.assemble_contrib import assemble_paper_contrib

    root = _std_fixture(tmp_path)
    with pytest.raises(ValueError, match="incumbent set"):
        assemble_paper_contrib(root, incumbent_person_ids={"P_NOBODY"},
                               author_person=dict(_AP), expected_by_cell=dict(_EXP),
                               edges_sub=EDGES_SUB)


# ---- 3. no winsorization step (fwci passes through as is) ---------------------

def test_winsor_stage_removed_per_signed_no_winsorize():
    """Rewritten test (replaces the earlier three tests of "guard not lifted → raise"): the shipping path no longer has a winsorization step —
    winsor_pool_scope / apply_winsor_stage have been removed from the assembler (a tombstone note stays in the source file);
    whoever revives them must pass this test first."""
    import m5_output.assemble_contrib as ac

    assert not hasattr(ac, "winsor_pool_scope"), "the winsor pool guard has been removed and must not return"
    assert not hasattr(ac, "apply_winsor_stage"), "the winsor step has been removed and must not return"


def test_assemble_ignores_legacy_winsor_keys_extreme_value_untouched(tmp_path, monkeypatch):
    """Core assertion (not capping = record as is): even if RED['fwci'] still carries the old winsorize_pct
    key (spec text not yet cleaned), production assembly never consumes it — set pct to an absurd 1 (= cap at p1;
    if it were consumed, 77.0 would be capped), and the extreme fwci=385/5.0=77.0 still comes out unchanged."""
    monkeypatch.setitem(RED["fwci"], "winsorize_pct", 1)
    works = [_work_row("W_EXT", cites=385)]
    edges = [_edge("W_EXT", "A1")]
    res = _assemble(_mk_root(tmp_path, works, edges))
    (row,) = [r for r in res["rows"] if r["work_id"] == "W_EXT"]
    assert row["fwci"] == 77.0, "extreme values are left uncapped and untouched (skew handling belongs to the regression layer)"


# ---- 4. two-stage isc backfill ------------------------------------------------

def test_star_pool_author_ids_signed_gates():
    """Star-set definition = the combination of two rules: the full 5% star pool (is_star_5pct)
    ∧ star.source_filter=foreign_poach_only (is_foreign_poach).
    Thin-sample None (cannot be estimated) is excluded; False is excluded."""
    from m5_output.assemble_contrib import star_pool_author_ids

    rows = [
        {"author_id": "S1", "is_star_5pct": True, "is_foreign_poach": True},
        {"author_id": "S2", "is_star_5pct": True, "is_foreign_poach": False},
        {"author_id": "S3", "is_star_5pct": False, "is_foreign_poach": True},
        {"author_id": "S4", "is_star_5pct": None, "is_foreign_poach": True},
    ]
    assert star_pool_author_ids(rows) == ["S1"]


def test_star_pool_asserts_source_filter_unchanged(monkeypatch):
    """source_filter changed → blow up loudly so a human re-decides (a definition change is never settled by a silent fallback; same self-check pattern as output_rule)."""
    from m5_output.assemble_contrib import star_pool_author_ids

    monkeypatch.setitem(RED["star"], "source_filter", "everyone")
    with pytest.raises(ValueError, match="source_filter"):
        star_pool_author_ids([{"author_id": "S1", "is_star_5pct": True,
                               "is_foreign_poach": True}])


def test_fold_star_authors_missing_mapping_warns_not_silent(capsys):
    """A person in star_set with no person_map entry → counted in the return value plus a stderr WARN; the set is never shrunk silently."""
    from m5_output.assemble_contrib import fold_star_authors_to_persons

    fold = fold_star_authors_to_persons(["SA1", "SA2"], {"SA1": "SP1"})
    assert fold["star_person_ids"] == {"SP1"}
    assert fold["unmapped_star_author_ids"] == ["SA2"]
    assert "SA2" not in fold["star_person_ids"]
    err = capsys.readouterr().err
    assert "WARN" in err and "1" in err, "a missing mapping must be reported (WARN + count)"


def test_backfill_isc_double_star_marks_once_and_keeps_rows(tmp_path):
    """One work with two star co-authors → every row of that work gets isc=True once (a bool does not accumulate; row count unchanged);
    a work with no star stays False; all other fields are untouched."""
    from m5_output.assemble_contrib import backfill_isc

    rows = [
        {"work_id": "W1", "incumbent_person_id": "P1", "person_id": "P1",
         "publication_year": 2010, "frac_credit": 0.25, "fwci": 2.0,
         "is_star_coauthored": False, "subfield_id": "2002"},
        {"work_id": "W1", "incumbent_person_id": "P1", "person_id": "SP1",
         "publication_year": 2010, "frac_credit": 0.25, "fwci": 2.0,
         "is_star_coauthored": False, "subfield_id": "2002"},
        {"work_id": "W1", "incumbent_person_id": "P1", "person_id": "SP2",
         "publication_year": 2010, "frac_credit": 0.25, "fwci": 2.0,
         "is_star_coauthored": False, "subfield_id": "2002"},
        {"work_id": "W2", "incumbent_person_id": "P1", "person_id": "P1",
         "publication_year": 2011, "frac_credit": 1.0, "fwci": None,
         "is_star_coauthored": False, "subfield_id": "2002"},
    ]
    out = backfill_isc(rows, {"SP1", "SP2"})            # two stars
    assert len(out) == len(rows), "the back-fill must not add or drop rows"
    assert all(r["is_star_coauthored"] is True for r in out if r["work_id"] == "W1")
    assert all(r["is_star_coauthored"] is False for r in out if r["work_id"] == "W2")
    stripped = [{k: v for k, v in r.items() if k != "is_star_coauthored"} for r in out]
    assert stripped == [{k: v for k, v in r.items() if k != "is_star_coauthored"}
                        for r in rows], "everything except isc is left unchanged verbatim"


def test_backfill_uses_unique_isc_definition():
    """isc#2 iron rule: the decision function bound by the assembler is identity.output_rule.is_star_coauthored
    itself (not rewritten, not copied)."""
    import identity.output_rule as our
    import m5_output.assemble_contrib as ac

    assert ac.is_star_coauthored is our.is_star_coauthored
