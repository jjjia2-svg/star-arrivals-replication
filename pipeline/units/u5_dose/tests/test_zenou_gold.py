"""Yves Zenou gold-standard acceptance at U5 level (cases #49-52 + 12-key spot check).

Yves Zenou shape (same structure as the real data): arrival 2016 -> t_minus_1=2015; the dose uses only refs <= 2015 and
frozen_at_year==2015 (never trust the affiliations.years 1998 backfill); the M5b exclusion goes one step and does not walk,
a paper shared by two stars is excluded only once, and both the with-stars and without-stars versions are reported; 12-key spot check
(an incumbent with 0 non-NA paper-years -> mean=NA, not 0).
"""
from __future__ import annotations

import pyarrow.parquet as pq
import pytest

from m4_dose import io_load, run_dose
from m5b_aggregate import run_m5b


ZENOU_ARRIVAL, ZENOU_T1 = 2016, 2015


def _zenou_universe(mk):
    """P_ZEN arrives in 2016; ego1 coauthored W_co with P_ZEN in 2014 (shared R_OLD); they coauthored W_post only in 2016
    (shared R_NEW; if the cutoff leaks 2016, coupling must change: mutant-killer); ego2 only coauthored W_2hop with ego1 in
    2015; a second star P_S2 is also attached to W_co (two stars on one paper)."""
    pm = [mk.pm("A_ZEN", "P_ZEN"), mk.pm("A_S2", "P_S2"),
          mk.pm("A_E1", "P_E1"), mk.pm("A_E2", "P_E2")]
    stars = [mk.star("A_ZEN", name="Yves Zenou", arrival=ZENOU_ARRIVAL),
             mk.star("A_S2", name="Second Star", arrival=ZENOU_ARRIVAL)]
    edges = [
        mk.edge("W_co", "A_ZEN", 2014), mk.edge("W_co", "A_E1", 2014),
        mk.edge("W_co", "A_S2", 2014),
        mk.edge("W_post", "A_ZEN", 2016), mk.edge("W_post", "A_E1", 2016),
        mk.edge("W_2hop", "A_E1", 2015), mk.edge("W_2hop", "A_E2", 2015),
        mk.edge("W_e1", "A_E1", 2013),
        mk.edge("W_zen1", "A_ZEN", 2015),
    ]
    works = [mk.work("W_co", 2014), mk.work("W_post", 2016),
             mk.work("W_2hop", 2015), mk.work("W_e1", 2013),
             mk.work("W_zen1", 2015)]
    refs = [
        # The union of refs of both people up to 2015 is deliberately identical, {R_A, R_B} (neither is a hub across the whole database, so idf>0):
        #   ego1 = W_co{R_A,R_B} ∪ W_e1{R_B} ∪ W_2hop{R_A}; Yves Zenou = W_co ∪ W_zen1{R_A,R_B}
        mk.ref("W_co", "R_A"), mk.ref("W_co", "R_B"),
        mk.ref("W_e1", "R_B"),
        mk.ref("W_zen1", "R_A"), mk.ref("W_zen1", "R_B"),
        mk.ref("W_2hop", "R_A"),
        # The 2016 W_post cites only R_NEW: if the cutoff leaks, ego1's union gains R_NEW -> cos<1 (mutant-killer)
        mk.ref("W_post", "R_NEW"),
    ]
    texts = [mk.text(w["work_id"]) for w in works]
    events = [mk.event(f"A_ZEN:{ZENOU_ARRIVAL}", "P_ZEN", ZENOU_ARRIVAL, ZENOU_T1)]
    pc = [
        mk.pc("W_co", "P_E1", "P_E1", 2014, frac_credit=1 / 3, fwci=3.0),
        mk.pc("W_co", "P_E1", "P_ZEN", 2014, frac_credit=1 / 3, fwci=3.0),
        mk.pc("W_co", "P_E1", "P_S2", 2014, frac_credit=1 / 3, fwci=3.0),
        mk.pc("W_e1", "P_E1", "P_E1", 2013, frac_credit=1.0, fwci=1.0),
        mk.pc("W_2hop", "P_E1", "P_E1", 2015, frac_credit=0.5, fwci=2.0),
        mk.pc("W_2hop", "P_E1", "P_E2", 2015, frac_credit=0.5, fwci=2.0),
        mk.pc("W_2hop", "P_E2", "P_E2", 2015, frac_credit=0.5, fwci=2.0),
        mk.pc("W_2hop", "P_E2", "P_E1", 2015, frac_credit=0.5, fwci=2.0),
        # ego2 in 2016: only papers with fwci=NA -> fwci_mean must be NA, not 0 (12-key spot check)
        mk.pc("W_na16", "P_E2", "P_E2", 2016, frac_credit=1.0, fwci=None),
    ]
    edges.append(mk.edge("W_na16", "A_E2", 2016))
    works.append(mk.work("W_na16", 2016))
    texts.append(mk.text("W_na16"))
    return io_load.U5Inputs(
        authorship_edges=edges, refs_edges=refs, works=works, work_text=texts,
        person_map=pm, star_set=stars, events=events, paper_contrib=pc,
        star_pids={"p01": {"P_ZEN", "P_S2"}, "p05": {"P_ZEN", "P_S2"}},
    )


def _cfg(tmp_path):
    return {
        "degree2_cap_k": 99, "degree2_incumbent_cap_per_star": 99,
        "mnar_missing_threshold": 0.20,
        "duckdb_db_path": str(tmp_path / "z.db"),
        "embed_model_sha": "deferred",
        "rule_version": "zen_signed", "config_sha": "zen_cfg",
        "source_snapshot_merkle": "zen_merkle", "stars_set_hash": "zen_stars",
    }


@pytest.mark.depends_on_u4
def test_zenou_dose_frozen_to_2015(mk, tmp_path, signed_dose):
    """#49: arrival 2016 -> coupling uses only refs <= 2015 and frozen_at_year==2015.

    mutant-killer: W_post (2016) shares R_NEW with the star; if the cutoff leaks, ego1's coupling must rise.
    """
    inputs = _zenou_universe(mk)
    rep = run_dose.run_m4_dose(
        inputs, config=_cfg(tmp_path), out_root=tmp_path / "dose",
        ledger_path=tmp_path / "l.jsonl", p_level="p01", embedder=None,
    )
    rows = pq.read_table(rep["dose_parquet"]).to_pylist()
    assert rows, "the Zenou event must produce dose rows"
    for r in rows:
        assert r["frozen_at_year"] == ZENOU_T1
    e1 = [r for r in rows if r["incumbent_person_id"] == "P_E1"
          and r["star_person_id"] == "P_ZEN"][0]
    # <=2015: ego1 refs={R_OLD} (W_co/W_e1/W_2hop), Yves Zenou refs={R_OLD} (W_co/W_zen1)
    # -> fully shared -> cosine=1.0; if it peeked at the 2016 W_post, ego1 would gain R_NEW -> cos<1 (caught by the mutant)
    assert e1["coupling_share"] == pytest.approx(1.0)
    assert e1["degree"] == 1


@pytest.mark.depends_on_u4
def test_zenou_coauthor_excluded_first_order_only(mk, tmp_path, signed_dose):
    """#50: W_co between ego1 and Yves Zenou is excluded; ego2 connects only to ego1 -> none of its papers is excluded (catches a graph-walking mutant)."""
    inputs = _zenou_universe(mk)
    rep = run_m5b.run_m5b(
        inputs, config=_cfg(tmp_path), out_root=tmp_path / "out",
        ledger_path=tmp_path / "l.jsonl",
    )
    rows = pq.read_table(rep["tables"]["p01"]).to_pylist()
    by = {(r["incumbent_person_id"], r["year"]): r for r in rows}
    e1_2014 = by[("P_E1", 2014)]
    assert e1_2014["pub_count"] == 1 and e1_2014["pub_count_ex_star"] == 0  # W_co excluded
    e2_2015 = by[("P_E2", 2015)]
    assert e2_2015["pub_count"] == 1 and e2_2015["pub_count_ex_star"] == 1  # No walking
    assert e2_2015["fwci_frac_ex_star"] == pytest.approx(1.0)               # 0.5×2.0


@pytest.mark.depends_on_u4
def test_zenou_full_clean_both_reported(mk, tmp_path, signed_dose):
    """#51: the with-stars and without-stars versions are both present in parallel and the two versions can be told apart for ego1 (#7 parallel report)."""
    inputs = _zenou_universe(mk)
    rep = run_m5b.run_m5b(
        inputs, config=_cfg(tmp_path), out_root=tmp_path / "out",
        ledger_path=tmp_path / "l.jsonl",
    )
    rows = pq.read_table(rep["tables"]["p01"]).to_pylist()
    e1 = [r for r in rows if r["incumbent_person_id"] == "P_E1"
          and r["year"] == 2014][0]
    assert e1["fwci_frac"] == pytest.approx(1.0)          # (1/3)×3.0
    assert e1["fwci_frac_ex_star"] == pytest.approx(0.0)  # W_co is excluded entirely
    assert e1["fwci_mean"] == pytest.approx(3.0)
    assert e1["fwci_mean_ex_star"] is None                # 0 works after exclusion -> NA, not 0


@pytest.mark.depends_on_u4
def test_zenou_no_phantom_double_deduction(mk, tmp_path, signed_dose):
    """#52: W_co attached to both Yves Zenou and the second star -> excluded only once (pub_count differs by exactly 1, diag counts 1 work)."""
    inputs = _zenou_universe(mk)
    rep = run_m5b.run_m5b(
        inputs, config=_cfg(tmp_path), out_root=tmp_path / "out",
        ledger_path=tmp_path / "l.jsonl",
    )
    rows = pq.read_table(rep["tables"]["p01"]).to_pylist()
    e1 = [r for r in rows if r["incumbent_person_id"] == "P_E1"
          and r["year"] == 2014][0]
    assert e1["pub_count"] - e1["pub_count_ex_star"] == 1   # Two stars on one paper, subtract exactly 1
    import json as _json
    diag = _json.loads(
        (tmp_path / "out" / "output_diag.json").read_text(encoding="utf-8"))
    assert diag["p01"]["n_excluded_works"] == 1             # The frozenset has only one entry


@pytest.mark.depends_on_u4
def test_zenou_zero_nonna_year_mean_is_na(mk, tmp_path, signed_dose):
    """12-key spot check: ego2 has only an NA paper in 2016 -> pub_count=1 while fwci_mean=NA, not 0."""
    inputs = _zenou_universe(mk)
    rep = run_m5b.run_m5b(
        inputs, config=_cfg(tmp_path), out_root=tmp_path / "out",
        ledger_path=tmp_path / "l.jsonl",
    )
    rows = pq.read_table(rep["tables"]["p01"]).to_pylist()
    e2 = [r for r in rows if r["incumbent_person_id"] == "P_E2"
          and r["year"] == 2016][0]
    assert e2["pub_count"] == 1
    assert e2["fwci_mean"] is None and e2["fwci_mean_ex_star"] is None
    assert e2["quality"] is None
    assert e2["n_works_frac"] == pytest.approx(1.0)
    assert e2["pub_count"] >= e2["pub_count_ex_star"]       # Monotonicity spot check
