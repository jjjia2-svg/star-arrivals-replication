"""aggregate (M5b) — aggregation only calls u0 pure functions (#36-40c).

Rules (prevent a recurrence of review finding B5, "several implementations drift apart"):
  - the single source of the aggregation formula = u0 identity/output_rule.aggregate_output (12 keys, 405 tests pass);
    this unit only feeds (paper_contrib rows -> contribs) and never rewrites any aggregation formula (grep guard);
  - the is_star_coauthored flag = work_id is in the exclusion set of this p_level — the same-named pc column is not read (#2/C1);
  - precondition assertion on the article+review domain (caveat#4 inherited, #40c);
  - rows with a missing publication year = excluded + logged (no year, no per-year computation;
    never dropped silently).
"""
from __future__ import annotations

import pathlib
import random
import re

import pytest

from m5b_aggregate import aggregate as agg


def _rows_by_pk(rows):
    return {(r["incumbent_person_id"], r["year"]): r for r in rows}


def _agg(mk, pc, exclude=frozenset(), works=None):
    if works is None:
        wids = {r["work_id"] for r in pc}
        works = [mk.work(w, 2010) for w in sorted(wids)]
    return agg.aggregate_via_u0(pc, works, exclude_works=frozenset(exclude))


# ---------------------------------------------------------------------------
# flag source = exclusion set, the pc column is not read (#2/C1)
# ---------------------------------------------------------------------------
def test_flag_from_exclude_set_not_pc_column(mk):
    """pc column is_star_coauthored=True but the work is not in the exclusion set -> not excluded (the column is ignored)."""
    pc = [mk.pc("W1", "P_I", "P_I", 2010, frac_credit=1.0, fwci=2.0,
                is_star_coauthored=True)]  # the column deliberately lies
    rows, stats = _agg(mk, pc, exclude=frozenset())
    r = _rows_by_pk(rows)[("P_I", 2010)]
    assert r["pub_count_ex_star"] == 1          # the column was not read -> not excluded
    assert r["fwci_frac_ex_star"] == pytest.approx(2.0)

    pc2 = [mk.pc("W1", "P_I", "P_I", 2010, frac_credit=1.0, fwci=2.0,
                 is_star_coauthored=False)]
    rows2, _ = _agg(mk, pc2, exclude=frozenset({"W1"}))
    r2 = _rows_by_pk(rows2)[("P_I", 2010)]
    assert r2["pub_count_ex_star"] == 0         # the exclusion set decides


# ---------------------------------------------------------------------------
# #36 / #37 / #38 / #39 / #40
# ---------------------------------------------------------------------------
def test_full_equals_empty_exclude(mk):
    """#36: empty exclusion set -> the with/without versions are equal key by key."""
    pc = [mk.pc("W1", "P_I", "P_I", 2010, frac_credit=0.5, fwci=2.0),
          mk.pc("W2", "P_I", "P_I", 2010, frac_credit=1.0, fwci=1.0)]
    rows, _ = _agg(mk, pc, exclude=frozenset())
    r = _rows_by_pk(rows)[("P_I", 2010)]
    assert r["pub_count"] == r["pub_count_ex_star"] == 2
    assert r["fwci_frac"] == pytest.approx(r["fwci_frac_ex_star"])
    assert r["fwci_full"] == pytest.approx(r["fwci_full_ex_star"])
    assert r["fwci_mean"] == pytest.approx(r["fwci_mean_ex_star"])


def test_clean_excludes_only_listed_works(mk):
    """#37: exclude={W2} -> the ex_star keys are short by exactly W2's contribution; the other keys are unchanged."""
    pc = [mk.pc("W1", "P_I", "P_I", 2010, frac_credit=0.5, fwci=2.0),
          mk.pc("W2", "P_I", "P_I", 2010, frac_credit=0.25, fwci=4.0)]
    rows, stats = _agg(mk, pc, exclude=frozenset({"W2"}))
    r = _rows_by_pk(rows)[("P_I", 2010)]
    assert r["pub_count"] == 2 and r["pub_count_ex_star"] == 1
    assert r["fwci_frac"] == pytest.approx(0.5 * 2.0 + 0.25 * 4.0)
    assert r["fwci_frac_ex_star"] == pytest.approx(0.5 * 2.0)
    assert r["fwci_full_ex_star"] == pytest.approx(2.0)
    assert r["fwci_mean_ex_star"] == pytest.approx(2.0)
    assert stats["n_excluded_works"] == 1


def test_per_person_exact_deduction_multistar(mk):
    """#38 (12-key version): a work with two stars appears once in the exclusion set -> pub_count_ex_star is short by exactly 1 (not 2);
    n_works_frac (no ex version) is unchanged; fwci_frac_ex_star is short by exactly that paper's one contribution."""
    pc = [mk.pc("W_DUO", "P_E", "P_E", 2010, frac_credit=0.5, fwci=2.0),
          mk.pc("W_OK", "P_E", "P_E", 2010, frac_credit=1.0, fwci=1.0)]
    # W_DUO is attached to two stars -> the exclusion set still holds only one entry {W_DUO} (guaranteed by the star_coauthored_works frozenset)
    rows, stats = _agg(mk, pc, exclude=frozenset({"W_DUO"}))
    r = _rows_by_pk(rows)[("P_E", 2010)]
    assert r["pub_count"] - r["pub_count_ex_star"] == 1     # exactly once, not 2
    assert r["n_works_frac"] == pytest.approx(1.5)          # count keys have no ex version, unchanged
    assert r["fwci_frac_ex_star"] == pytest.approx(1.0)
    assert stats["n_excluded_works"] == 1


def test_clean_monotone_le_full_property(mk):
    """#39 (property, many seeds): for all person-years ex_star <= full and pub_count_ex_star <= pub_count."""
    for seed in (7, 42, 2026):
        rng = random.Random(seed)
        universe = [f"W{i}" for i in range(30)]
        # work-level values are drawn once per work (real-data invariant: year/frac/fwci are always the same across rows of one work)
        wmeta = {w: (2000 + rng.randint(0, 3),
                     rng.choice([0.25, 0.5, 1.0]),
                     rng.choice([None, 0.0, 0.5, 2.0, 9.0])) for w in universe}
        pc = []
        for i in range(120):
            wid = rng.choice(universe)
            yr, frac, fw = wmeta[wid]
            pc.append(mk.pc(wid, f"P{rng.randint(0, 5)}", "P_X", yr,
                            frac_credit=frac, fwci=fw))
        exclude = frozenset(rng.sample(universe, 8))
        rows, _ = _agg(mk, pc, exclude=exclude)
        for r in rows:
            assert r["pub_count_ex_star"] <= r["pub_count"]
            assert r["fwci_frac_ex_star"] <= r["fwci_frac"] + 1e-12
            assert r["fwci_full_ex_star"] <= r["fwci_full"] + 1e-12


def test_fwci_na_excluded_from_both_numerator_and_divisor(mk):
    """#40: fwci=NA counts toward pub_count/n_works_frac, but not toward fwci_frac and not toward the mean divisor."""
    pc = [mk.pc("W1", "P_I", "P_I", 2010, frac_credit=1.0, fwci=None),
          mk.pc("W2", "P_I", "P_I", 2010, frac_credit=1.0, fwci=3.0)]
    rows, stats = _agg(mk, pc)
    r = _rows_by_pk(rows)[("P_I", 2010)]
    assert r["pub_count"] == 2
    assert r["n_works_frac"] == pytest.approx(2.0)
    assert r["fwci_frac"] == pytest.approx(3.0)
    assert r["fwci_mean"] == pytest.approx(3.0)   # divisor=1 (the number of non-NA papers), not 2
    assert stats["n_papers_fwci_na"] == 1


def test_fwci_inherits_article_review_domain(mk):
    """#40c (fwci column domain form): a non-article/review work **with non-NA fwci** -> the precondition assertion raises.

    Definition note (following the frozen U4 10c output): the domain constraint of caveat#4 sits on the
    fwci column — U4 computes FWCI only for article+review, and rows of other types with fwci=NA are legitimately present
    (pub_count counts them, as it is defined to "include papers with missing fwci").
    """
    pc = [mk.pc("W_DS", "P_I", "P_I", 2010, fwci=1.0)]
    works = [mk.work("W_DS", 2010, work_type="dataset")]
    from m4_dose.io_load import DomainViolation
    with pytest.raises(DomainViolation):
        agg.aggregate_via_u0(pc, works, exclude_works=frozenset())


def test_na_fwci_non_article_row_counted_not_blocked(mk):
    """Frozen U4 reality: dataset/preprint rows have fwci=NA -> allowed + enter the count keys (papers with missing fwci are included)."""
    pc = [mk.pc("W_DS", "P_I", "P_I", 2010, fwci=None),
          mk.pc("W_ART", "P_I", "P_I", 2010, fwci=2.0)]
    works = [mk.work("W_DS", 2010, work_type="dataset"),
             mk.work("W_ART", 2010, work_type="article")]
    rows, _ = agg.aggregate_via_u0(pc, works, exclude_works=frozenset())
    r = _rows_by_pk(rows)[("P_I", 2010)]
    assert r["pub_count"] == 2            # dataset NA papers are still counted (missing papers included)
    assert r["fwci_mean"] == pytest.approx(2.0)   # but they do not enter the fwci keys


# ---------------------------------------------------------------------------
# (work, incumbent) de-duplication — the row grain of U4 paper_contrib = work x incumbent x person,
# and the producer docstring says in plain words: "downstream U5 de-duplicates to (work, incumbent) to get each person's output"
# (u4 m5_output/paper_contrib.py). The co-author dimension is for the collaboration network, not for output counts.
# ---------------------------------------------------------------------------
def test_dedupe_to_work_incumbent_grain(mk):
    """Two person rows with the same (work, inc) -> counted as one paper (the de-duplication definition set by the U4 producer)."""
    pc = [mk.pc("W1", "P_I", "P_I", 2010, frac_credit=0.5, fwci=2.0),
          mk.pc("W1", "P_I", "P_COAUTH", 2010, frac_credit=0.5, fwci=2.0)]
    rows, stats = _agg(mk, pc)
    r = _rows_by_pk(rows)[("P_I", 2010)]
    assert r["pub_count"] == 1                       # one paper, not two
    assert r["n_works_frac"] == pytest.approx(0.5)   # frac is counted only once
    assert r["fwci_frac"] == pytest.approx(1.0)
    assert stats["n_raw_rows"] == 2 and stats["n_contrib_units"] == 1


def test_dedupe_conflicting_work_values_raise(mk):
    """Two rows with the same (work, inc) whose work-level values disagree (fwci conflict) -> fail loud, never silently pick one."""
    pc = [mk.pc("W1", "P_I", "P_I", 2010, fwci=2.0),
          mk.pc("W1", "P_I", "P_X", 2010, fwci=3.0)]
    with pytest.raises(ValueError, match="inconsistent"):
        _agg(mk, pc)


def test_same_work_two_incumbents_both_counted(mk):
    """The same paper attached to two incumbents -> each of the two counts one paper (the de-duplication key includes incumbent; no de-duplication across people)."""
    pc = [mk.pc("W1", "P_A", "P_A", 2010, frac_credit=0.5, fwci=2.0),
          mk.pc("W1", "P_A", "P_B", 2010, frac_credit=0.5, fwci=2.0),
          mk.pc("W1", "P_B", "P_A", 2010, frac_credit=0.5, fwci=2.0),
          mk.pc("W1", "P_B", "P_B", 2010, frac_credit=0.5, fwci=2.0)]
    rows, _ = _agg(mk, pc)
    assert _rows_by_pk(rows)[("P_A", 2010)]["pub_count"] == 1
    assert _rows_by_pk(rows)[("P_B", 2010)]["pub_count"] == 1


# ---------------------------------------------------------------------------
# rows with a missing year = excluded + logged
# ---------------------------------------------------------------------------
def test_null_pub_year_dropped_and_accounted(mk):
    """publication_year=None row: cannot enter per-year aggregation -> excluded + logged in n_dropped_null_pub_year."""
    pc = [mk.pc("W1", "P_I", "P_I", 2010, frac_credit=1.0, fwci=1.0)]
    pc.append(mk.pc("W_NOYEAR", "P_I", "P_I", None, frac_credit=1.0, fwci=1.0))
    rows, stats = _agg(mk, pc)
    assert set(_rows_by_pk(rows)) == {("P_I", 2010)}       # no (P_I, None) group
    assert stats["n_dropped_null_pub_year"] == 1


# ---------------------------------------------------------------------------
# 12-key positive case + B5 source guard
# ---------------------------------------------------------------------------
def test_twelve_keys_exact(mk):
    """After wiring, the row key set == the current 12 OUTPUT keys (quality is a None placeholder at this layer)."""
    from common.schema import OUTPUT, assert_matches_schema
    rows, _ = _agg(mk, [mk.pc("W1", "P_I", "P_I", 2010)])
    assert_matches_schema(rows[0].keys(), OUTPUT, label="m5b_rows")
    assert rows[0]["quality"] is None


def test_m5b_source_does_not_rewrite_aggregation():
    """Prevent B5: aggregate.py only feeds — it computes no OUTPUT value key, and aggregation must go through u0 aggregate_output.

    Guard rules: (1) it must import the u0 aggregation function (2) it must never redefine it (3) the code body (docstrings/comments stripped)
    contains no OUTPUT value key name (value keys may only be computed in u0) (4) no arithmetic multiplication (frac*fwci may live only in u0).
    Bookkeeping counters (n_dropped etc.) are the feeding layer's job and are not forbidden.
    """
    src = pathlib.Path(agg.__file__).read_text(encoding="utf-8")
    assert "from identity.output_rule import aggregate_output" in src
    body = re.sub(r'""".*?"""', "", src, flags=re.S)      # strip docstrings
    body = "\n".join(l.split("#")[0] for l in body.splitlines())  # strip comments
    assert "def aggregate_output(" not in body, "M5b reimplemented aggregate_output — guards against B5"
    for key in ("fwci_frac", "fwci_full", "fwci_mean", "pub_count", "n_works_frac"):
        assert key not in body, f"M5b source contains OUTPUT value key {key} — value keys may only be computed in u0"
    assert not re.search(r"[\w\)\]]\s*\*\s*[\w\(]", body), \
        "M5b source contains a multiplication — formulas such as frac×fwci may only live in u0"
    assert "fwci_baseline" not in body.lower()             # #48: the denominator is not touched
