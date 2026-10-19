"""run_m5b: M5b orchestration and on-disk output (cases #42-47).

End to end: synthetic mini-universe -> exclusion set (p01/p05 delivery definition) -> u0 aggregation of 12 keys ->
quality fill -> two same-source named tables (#1) + single-source exclusion / subtraction exactly once /
triple guard that the two tables share one source + six-key tally + idempotent ledger + output_diag.json
sidecar. Everything uses tmp; nothing is ever written to the SSD.
"""
from __future__ import annotations

import json

import pyarrow.parquet as pq
import pytest

from common.manifest import dataset_is_valid, sha256_file
from common.schema import OUTPUT, TALLY, assert_matches_schema
from m4_dose import io_load
from m5b_aggregate import run_m5b


def _mk_inputs(mk, *, extra_pc=None):
    """Mini-universe: two stars (P_S = 1% + 5%, P_S5 = 5% only; both poach) + incumbent P_I with five papers.

    works: W_A (coauthored with P_S, 2010, fwci 2.0, frac .5) / W_B (with P_S5, 2011, 4.0, .5)
           W_C (solo, 2010, 1.0, 1.0) / W_NA (solo, 2010, fwci NA) / W_NOYEAR (year missing)
    Expected: p01 excludes {W_A}; p05 excludes {W_A, W_B}.
    """
    pm = [mk.pm("A_S", "P_S"), mk.pm("A_S5", "P_S5"), mk.pm("A_I", "P_I")]
    stars = [mk.star("A_S", is_star_1pct=True, is_star_5pct=True),
             mk.star("A_S5", is_star_1pct=False, is_star_5pct=True)]
    edges = [
        mk.edge("W_A", "A_S", 2010), mk.edge("W_A", "A_I", 2010),
        mk.edge("W_B", "A_S5", 2011), mk.edge("W_B", "A_I", 2011),
        mk.edge("W_C", "A_I", 2010),
        mk.edge("W_NA", "A_I", 2010),
        mk.edge("W_NOYEAR", "A_I", 2012),
    ]
    works = [mk.work("W_A", 2010), mk.work("W_B", 2011), mk.work("W_C", 2010),
             mk.work("W_NA", 2010), mk.work("W_NOYEAR", 2012)]
    pc = [
        # (work, inc, person) granularity, including coauthor rows, to verify de-duplication (the definition the U4 producer fixes)
        mk.pc("W_A", "P_I", "P_I", 2010, frac_credit=0.5, fwci=2.0),
        mk.pc("W_A", "P_I", "P_S", 2010, frac_credit=0.5, fwci=2.0),
        mk.pc("W_B", "P_I", "P_I", 2011, frac_credit=0.5, fwci=4.0),
        mk.pc("W_B", "P_I", "P_S5", 2011, frac_credit=0.5, fwci=4.0),
        mk.pc("W_C", "P_I", "P_I", 2010, frac_credit=1.0, fwci=1.0),
        mk.pc("W_NA", "P_I", "P_I", 2010, frac_credit=1.0, fwci=None),
        mk.pc("W_NOYEAR", "P_I", "P_I", None, frac_credit=1.0, fwci=1.0),
    ]
    if extra_pc:
        pc += extra_pc
    return io_load.U5Inputs(
        authorship_edges=edges, refs_edges=[], works=works, work_text=[],
        person_map=pm, star_set=stars, events=[], paper_contrib=pc,
        star_pids={},
    )


def _cfg(**over):
    cfg = {
        "mnar_missing_threshold": 0.20,
        "rule_version": "u5_m5b_signed_2026-07-10",
        "config_sha": "cfg_sha_m5b",
        "source_snapshot_merkle": "merkle_m5b",
        "stars_set_hash": "stars_hash_m5b",
    }
    cfg.update(over)
    return cfg


def _run(mk, tmp_path, *, sub="out", inputs=None, cfg=None, force=False):
    inputs = inputs if inputs is not None else _mk_inputs(mk)
    out_root = tmp_path / sub
    report = run_m5b.run_m5b(
        inputs, config=(cfg or _cfg()), out_root=out_root,
        ledger_path=tmp_path / sub / "_ledger_events.jsonl",
        force_recompute=force,
    )
    return out_root, report


def _read(out_root, name):
    return pq.read_table(str(out_root / "_frozen" / name)).to_pylist()


def _by_pk(rows):
    return {(r["incumbent_person_id"], r["year"]): r for r in rows}


# ---------------------------------------------------------------------------
# #42 / #1 two named tables + 12 keys + #43 PK
# ---------------------------------------------------------------------------
def test_two_named_tables_twelve_keys(mk, tmp_path):
    out_root, report = _run(mk, tmp_path)
    for name in ("output_star1pct.parquet", "output_star5pct.parquet"):
        tbl = pq.read_table(str(out_root / "_frozen" / name))
        assert list(tbl.column_names) == list(OUTPUT.keys())      # Column order = schema key order
        assert_matches_schema(tbl.column_names, OUTPUT, label=name)  # #42: 12 keys
        assert "star_p_level" not in tbl.column_names             # #44b: no long-table dimension
    assert dataset_is_valid(out_root)
    assert report["skipped"] is False


def test_output_is_per_person_per_year(mk, tmp_path):
    """#43: PK=(incumbent_person_id, year) is unique and carries year."""
    out_root, _ = _run(mk, tmp_path)
    rows = _read(out_root, "output_star1pct.parquet")
    pks = [(r["incumbent_person_id"], r["year"]) for r in rows]
    assert len(pks) == len(set(pks))
    assert {pk for pk in pks} == {("P_I", 2010), ("P_I", 2011)}   # Rows with a missing year form no group


# ---------------------------------------------------------------------------
# Hand-computed values (difference between the p01 and p05 exclusion definitions)
# ---------------------------------------------------------------------------
def test_values_hand_computed_p01(mk, tmp_path):
    out_root, _ = _run(mk, tmp_path)
    r10 = _by_pk(_read(out_root, "output_star1pct.parquet"))[("P_I", 2010)]
    # 2010: W_A (coauthored with the star, excluded under p01) + W_C + W_NA (fwci NA)
    assert r10["pub_count"] == 3 and r10["pub_count_ex_star"] == 2
    assert r10["n_works_frac"] == pytest.approx(2.5)
    assert r10["fwci_frac"] == pytest.approx(0.5 * 2.0 + 1.0 * 1.0)
    assert r10["fwci_frac_ex_star"] == pytest.approx(1.0)
    assert r10["fwci_mean"] == pytest.approx(1.5)
    assert r10["fwci_mean_ex_star"] == pytest.approx(1.0)
    assert r10["quality"] == pytest.approx(1.0 / 1.0)   # ex-star: only W_C (1.0 x 1.0)/1.0

    r11 = _by_pk(_read(out_root, "output_star1pct.parquet"))[("P_I", 2011)]
    # 2011: only W_B (S5 is not a 1% star, so p01 does not exclude it)
    assert r11["pub_count"] == 1 and r11["pub_count_ex_star"] == 1
    assert r11["fwci_frac_ex_star"] == pytest.approx(2.0)
    assert r11["quality"] == pytest.approx(4.0)


def test_values_hand_computed_p05(mk, tmp_path):
    out_root, _ = _run(mk, tmp_path)
    r11 = _by_pk(_read(out_root, "output_star5pct.parquet"))[("P_I", 2011)]
    # p05 excludes W_B too -> 2011 ex_star is entirely empty
    assert r11["pub_count"] == 1 and r11["pub_count_ex_star"] == 0
    assert r11["fwci_frac_ex_star"] == pytest.approx(0.0)
    assert r11["fwci_mean_ex_star"] is None                 # 0 works -> NA, not 0
    assert r11["quality"] is None                           # 0 works after excluding stars -> NA


def test_two_tables_shared_cols_equal(mk, tmp_path):
    """#44b: the shared columns unaffected by exclusion (pub_count/n_works_frac/fwci_frac/full/mean)
    have the same value in both tables for every PK. This is the substantive test that the two tables share one source."""
    out_root, _ = _run(mk, tmp_path)
    a = _by_pk(_read(out_root, "output_star1pct.parquet"))
    b = _by_pk(_read(out_root, "output_star5pct.parquet"))
    assert set(a) == set(b)
    for pk in a:
        for col in ("pub_count", "n_works_frac", "fwci_frac", "fwci_full",
                    "fwci_mean"):
            assert a[pk][col] == b[pk][col]


# ---------------------------------------------------------------------------
# #45 idempotency key + resume; #46 deterministic across two runs
# ---------------------------------------------------------------------------
def test_idempotency_key_includes_star_hash(mk, tmp_path):
    out_root, rep1 = _run(mk, tmp_path)
    assert "stars_hash_m5b" in rep1["idempotency_key"]
    # Rerun with the same config -> skip (same as #30)
    _, rep2 = _run(mk, tmp_path)
    assert rep2["skipped"] is True
    # Change the star_set hash -> the key flips and nothing is skipped (#45)
    _, rep3 = _run(mk, tmp_path, cfg=_cfg(stars_set_hash="stars_hash_CHANGED"))
    assert rep3["skipped"] is False
    assert rep3["idempotency_key"] != rep1["idempotency_key"]


def test_determinism_two_runs_byte_identical(mk, tmp_path):
    """Same as #46/#27: two independent runs give byte-identical tables."""
    out_a, _ = _run(mk, tmp_path, sub="a")
    out_b, _ = _run(mk, tmp_path, sub="b")
    for name in ("output_star1pct.parquet", "output_star5pct.parquet"):
        assert sha256_file(out_a / "_frozen" / name) == \
               sha256_file(out_b / "_frozen" / name)


# ---------------------------------------------------------------------------
# #47 diagnostics sidecar + six-key tally + provenance + bookkeeping
# ---------------------------------------------------------------------------
def test_diag_not_in_output_tally(mk, tmp_path):
    out_root, _ = _run(mk, tmp_path)
    diag = json.loads((out_root / "output_diag.json").read_text(encoding="utf-8"))
    assert "mnar_robustness_required" in diag["p01"]
    tally = json.loads((out_root / "tally.json").read_text(encoding="utf-8"))
    assert_matches_schema(tally.keys(), TALLY, label="m5b tally")
    # Diagnostic keys never leak into the main OUTPUT table
    rows = _read(out_root, "output_star1pct.parquet")
    for bad in ("n_excluded_works", "mnar_robustness_required", "n_papers_fwci_na"):
        assert bad not in rows[0]


def test_null_year_and_exclusion_accounted_in_diag(mk, tmp_path):
    out_root, _ = _run(mk, tmp_path)
    diag = json.loads((out_root / "output_diag.json").read_text(encoding="utf-8"))
    assert diag["p01"]["n_dropped_null_pub_year"] == 1     # W_NOYEAR (missing-year bookkeeping, #5)
    assert diag["p01"]["n_excluded_works"] == 1            # {W_A}
    assert diag["p05"]["n_excluded_works"] == 2            # {W_A, W_B}
    assert diag["p01"]["n_ship_stars"] == 1                # P_S
    assert diag["p05"]["n_ship_stars"] == 2                # P_S + P_S5


def test_mnar_flag_fires_in_diag(mk, tmp_path):
    """#41c wiring: NA rate > threshold -> diag mnar_robustness_required=true (+WARN)."""
    extra = [
        # Add 3 more NA papers (4 NA out of 7 papers with a year, about 57%), pushing the rate past the 20% threshold
        {"work_id": w, "incumbent_person_id": "P_I", "person_id": "P_I",
         "publication_year": 2012, "frac_credit": 1.0, "fwci": None,
         "is_star_coauthored": False, "subfield_id": "2002"}
        for w in ("W_NA2", "W_NA3", "W_NA4")
    ]
    inputs = _mk_inputs(mk, extra_pc=extra)
    inputs.works += [
        {**inputs.works[0], "work_id": w, "publication_year": 2012}
        for w in ("W_NA2", "W_NA3", "W_NA4")
    ]
    with pytest.warns(UserWarning, match="MNAR"):
        out_root, _ = _run(mk, tmp_path, inputs=inputs)
    diag = json.loads((out_root / "output_diag.json").read_text(encoding="utf-8"))
    assert diag["p01"]["mnar_robustness_required"] is True


def test_provenance_four_tuple_in_header(mk, tmp_path):
    """The four provenance fields are non-empty and equal the config (the on-disk side of the fail-loud binding)."""
    out_root, _ = _run(mk, tmp_path)
    hdr = json.loads(
        (out_root / "_frozen" / "manifest_header.json").read_text(encoding="utf-8"))
    assert hdr["stars_set_hash"] == "stars_hash_m5b"
    assert hdr["config_sha"] == "cfg_sha_m5b"
    assert hdr["source_snapshot_merkle"] == "merkle_m5b"
    assert hdr["rule_version"] == "u5_m5b_signed_2026-07-10"


def test_empty_provenance_key_fail_loud(mk, tmp_path):
    """Any empty-string provenance key -> raise (guards against empty provenance passing as green)."""
    with pytest.raises(ValueError, match="provenance"):
        _run(mk, tmp_path, cfg=_cfg(stars_set_hash=""))


def test_exclusion_edges_override_year_agnostic(mk, tmp_path):
    """#8 excluding the full history is independent of year: exclusion_edges may carry star edges with a missing year. A missing-year star
    coauthored work still enters the exclusion set (counted in n_excluded_works), but its pc cell is dropped by the missing-year
    bookkeeping, so the OUTPUT rows do not change."""
    inputs = _mk_inputs(mk)
    # W_NOYEAR is really a missing-year work coauthored with P_S: the star edge is given only in exclusion_edges
    exclusion_edges = list(inputs.authorship_edges) + [
        {"work_id": "W_NOYEAR", "author_id": "A_S", "publication_year": None}]
    out_root = tmp_path / "out"
    report = run_m5b.run_m5b(
        inputs, config=_cfg(), out_root=out_root,
        ledger_path=tmp_path / "l.jsonl", exclusion_edges=exclusion_edges,
    )
    diag = json.loads((out_root / "output_diag.json").read_text(encoding="utf-8"))
    assert diag["p01"]["n_exclusion_set_works"] == 2   # The full set {W_A, W_NOYEAR}
    assert diag["p01"]["n_excluded_works"] == 1        # Only W_A hits a retained cell
    rows = _read(out_root, "output_star1pct.parquet")
    assert {(r["incumbent_person_id"], r["year"]) for r in rows} \
        == {("P_I", 2010), ("P_I", 2011)}              # The missing-year cell still does not enter the aggregation
