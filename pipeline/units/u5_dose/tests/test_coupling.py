"""coupling + posting_index — red tests for the main dose (#14/#15/#16/#17/#18/#19).

Main dose = shared-reference coupling (bibliographic coupling) frozen at t-1 (#16);
the single source of the formula = identity.dose.coupling_share — this unit only delegates and never rewrites it (#14).
"""
from __future__ import annotations

import math

import pytest

from identity import dose as identity_dose
from m4_dose import coupling, posting_index


def _pedges(triples):
    return [{"work_id": w, "person_id": p, "publication_year": y} for w, p, y in triples]


# ---------------------------------------------------------------------------
# #14 delegates to identity.dose (single source of the definition)
# ---------------------------------------------------------------------------
def test_coupling_delegates_to_identity(monkeypatch, signed_dose):
    """#14: spy identity.dose.coupling_share — assert it is called and ref_idf= is passed as a kwarg."""
    calls = {}

    def spy(refs_a, refs_b, ref_idf=None):
        calls["args"] = (set(refs_a), set(refs_b))
        calls["ref_idf"] = ref_idf
        return 0.5

    monkeypatch.setattr(identity_dose, "coupling_share", spy)
    idf = {"R1": 1.0}
    out = coupling.pair_coupling({"R1"}, {"R1", "R2"}, idf)
    assert out == 0.5
    assert calls["args"] == ({"R1"}, {"R1", "R2"})
    assert calls["ref_idf"] is idf  # ref_idf is passed through unchanged as a kwarg


def test_no_local_coupling_formula():
    """#14 source side: coupling.py contains no local normalisation formula (sqrt/division normalisation lives in identity, preventing definition forks)."""
    import pathlib

    src = pathlib.Path(coupling.__file__).read_text(encoding="utf-8")
    assert "sqrt" not in src  # cosine normalisation lives only inside identity.dose
    assert "coupling_share" in src  # the delegation point is present


# ---------------------------------------------------------------------------
# #15 column name anchored to the official name
# ---------------------------------------------------------------------------
def test_refs_edges_column_name(mk):
    """#15: reads referenced_work_id; feeding a ref_work_id column -> KeyError (a wrong name is not silently accepted)."""
    good = [mk.ref("W1", "R1")]
    m = coupling.refs_by_work(good)
    assert m == {"W1": {"R1"}}
    bad = [{"work_id": "W1", "ref_work_id": "R1"}]
    with pytest.raises(KeyError):
        coupling.refs_by_work(bad)


# ---------------------------------------------------------------------------
# #16 frozen at t-1 (main-dose input side)
# ---------------------------------------------------------------------------
def test_coupling_frozen_to_t_minus_1(mk):
    """#16: the refs union takes only works <= t-1; the refs of a 2016 work never enter the main-dose input."""
    edges = _pedges([("W14", "P_A", 2014), ("W16", "P_A", 2016)])
    refs_map = coupling.refs_by_work([mk.ref("W14", "R1"), mk.ref("W16", "R2")])
    refs = coupling.person_refs_until("P_A", edges, refs_map, 2015)
    assert refs == {"R1"}  # R2 belongs to a 2016 work -> outside the freeze point


def test_person_refs_goes_through_single_cutoff(monkeypatch, mk):
    """#7 (coupling side): person_refs_until truncates through cutoff.filter_works_until (spy)."""
    from m4_dose import cutoff as cutoff_mod

    seen = []
    real = cutoff_mod.filter_works_until

    def spy(rows, t):
        seen.append(t)
        return real(rows, t)

    monkeypatch.setattr(cutoff_mod, "filter_works_until", spy)
    edges = _pedges([("W1", "P_A", 2014)])
    coupling.person_refs_until("P_A", edges, {"W1": {"R1"}}, 2015)
    assert seen == [2015]


# ---------------------------------------------------------------------------
# #17 hub-ref IDF down-weighting
# ---------------------------------------------------------------------------
def test_hub_ref_downweighted(mk, signed_dose):
    """#17: the coupling from sharing a hub ref (cited by the whole corpus) is far lower than the coupling from sharing a rare ref."""
    refs_rows = []
    # all 10 citing works cite R_HUB; only W0/W1 cite R_RARE
    for i in range(10):
        refs_rows.append(mk.ref(f"W{i}", "R_HUB"))
    refs_rows += [mk.ref("W0", "R_RARE"), mk.ref("W1", "R_RARE")]
    idf = coupling.build_ref_idf(refs_rows, idf_floor=0.0)
    assert idf["R_HUB"] < idf["R_RARE"]

    hub_only = coupling.pair_coupling({"R_HUB"}, {"R_HUB"}, idf)
    rare_only = coupling.pair_coupling({"R_RARE"}, {"R_RARE"}, idf)
    assert hub_only < rare_only
    assert hub_only == 0.0  # df==N -> idf=ln(1)=0, floor 0.0 -> weight 0 -> coupling goes to zero


def test_build_ref_idf_floor_applies(mk):
    """idf floor = RED hub_ref_idf_floor (passed in by the calling layer): weight = max(idf, floor)."""
    refs_rows = [mk.ref("W0", "R_HUB"), mk.ref("W1", "R_HUB")]
    idf = coupling.build_ref_idf(refs_rows, idf_floor=0.25)
    assert idf["R_HUB"] == 0.25  # ln(2/2)=0 < floor -> lifted to the floor


# ---------------------------------------------------------------------------
# #18 coverage diagnostics
# ---------------------------------------------------------------------------
def test_coverage_is_weighted_eligible(mk):
    """#18: the two people's t-1 union has 10 works, 3 with has_references=False -> coverage==0.7."""
    triples, works = [], {}
    for i in range(6):
        triples.append((f"WA{i}", "P_A", 2014))
        works[f"WA{i}"] = mk.work(f"WA{i}", 2014, has_references=(i >= 2))  # 2 papers False
    for i in range(4):
        triples.append((f"WB{i}", "P_B", 2014))
        works[f"WB{i}"] = mk.work(f"WB{i}", 2014, has_references=(i >= 1))  # 1 paper False
    cov = coupling.pair_coverage("P_A", "P_B", _pedges(triples), works, 2015)
    assert cov == pytest.approx(0.7)


def test_coverage_empty_workset_is_zero(mk):
    """Neither person has any work before t-1 -> coverage 0.0 (no divide-by-zero crash; boundary_sensitive is judged by the run layer)."""
    cov = coupling.pair_coverage("P_A", "P_B", [], {}, 2015)
    assert cov == 0.0


# ---------------------------------------------------------------------------
# #19 empty refs are defined
# ---------------------------------------------------------------------------
def test_empty_refs_returns_defined(signed_dose):
    """#19: all refs empty -> coupling 0.0 (no NaN / no raise) — behaviour after delegating to identity."""
    out = coupling.pair_coupling(set(), set(), None)
    assert out == 0.0 and not math.isnan(out)


def test_unsigned_normalization_raises(monkeypatch):
    """Guard: dose.coupling_normalization not set (yaml value null) -> the delegation layer raises unchanged.

    The code never fills it in itself — a value must be set before a real-data run (identity RedlineUnsigned propagates).
    """
    from common._redlines import RED, RedlineUnsigned

    monkeypatch.setitem(RED["dose"], "coupling_normalization", None)
    with pytest.raises(RedlineUnsigned):
        coupling.pair_coupling({"R1"}, {"R1"}, None)


# ---------------------------------------------------------------------------
# posting_index (acceleration helper; H4 year source = works)
# ---------------------------------------------------------------------------
def test_posting_index_year_from_works_and_sorted(tmp_path, mk):
    """H4: posting years come from works (refs_edges has no year); within a partition rows are ascending by (ref, citing).

    Standard hive layout: the year lives only in the partition directory name; reading the dataset root restores the publication_year column automatically.
    """
    refs_rows = [mk.ref("W2", "R2"), mk.ref("W1", "R2"), mk.ref("W1", "R1")]
    works_by_id = {"W1": mk.work("W1", 2014), "W2": mk.work("W2", 2015)}
    out_root = tmp_path / "posting_by_year"
    posting_index.build_posting_by_year(
        refs_rows, works_by_id, out_root, ref_idf=None, idf_floor=0.0
    )
    import pyarrow.parquet as pq

    p14 = pq.read_table(str(out_root / "publication_year=2014" / "part-0.parquet"))
    rows14 = p14.to_pylist()
    assert [(r["referenced_work_id"], r["citing_work_id"]) for r in rows14] \
        == [("R1", "W1"), ("R2", "W1")]  # canonical ascending
    # dataset root read: the partition key is restored as the publication_year column (year source = works, H4)
    whole = pq.read_table(str(out_root)).to_pylist()
    year_by_citing = {r["citing_work_id"]: int(r["publication_year"]) for r in whole}
    assert year_by_citing == {"W1": 2014, "W2": 2015}


def test_posting_index_missing_year_raises(tmp_path, mk):
    """A citing work not in works -> raise (H4 fail loud; never silently dropped or silently left without a year)."""
    refs_rows = [mk.ref("W_GHOST", "R1")]
    with pytest.raises(posting_index.PostingYearMissing):
        posting_index.build_posting_by_year(
            refs_rows, {}, tmp_path / "p", ref_idf=None, idf_floor=0.0
        )


def test_posting_index_hub_pruned(tmp_path, mk):
    """Hub refs dropped by the RED threshold: refs with weight <= idf_floor do not enter the inverted index (shrinks the index on the acceleration path)."""
    refs_rows = [mk.ref("W1", "R_HUB"), mk.ref("W2", "R_HUB"), mk.ref("W1", "R_RARE")]
    works_by_id = {"W1": mk.work("W1", 2014), "W2": mk.work("W2", 2014)}
    idf = coupling.build_ref_idf(refs_rows, idf_floor=0.0)  # R_HUB weight=0.0
    out_root = tmp_path / "posting_by_year"
    posting_index.build_posting_by_year(
        refs_rows, works_by_id, out_root, ref_idf=idf, idf_floor=0.0
    )
    import pyarrow.parquet as pq

    rows = pq.read_table(str(out_root / "publication_year=2014" / "part-0.parquet")).to_pylist()
    refs_present = {r["referenced_work_id"] for r in rows}
    assert refs_present == {"R_RARE"}  # hub dropped
