"""M5-T1 paper_contrib — per-paper contribution rows (row granularity + two-stage isc).

In plain words: spread each paper into rows "department incumbent i × each co-author p of the paper". Each row carries the paper's
fractional count frac_credit (=1/number of authorships), the quality score fwci, whether a star co-authored (isc), and the subfield.
Downstream (U5) dedups to (work, incumbent) to get each person's output, and takes the (i,p) pairs to get the collaboration network.

Fixed rules (only consumed here):
  - frac_credit = 1/number of distinct author_id (fractional counting): a repeated authorship counts as 1 person;
    0 authors raises (no inf); it counts author_id, not person → does not change with U2 clustering.
  - row granularity = (work_id, incumbent_person_id, person_id), i.e. incumbent × person per work
    (schema [18] PK; M5-T3 invariant: rows = sum over works of distinct incumbent × person); only works with ≥1 incumbent.
  - isc#2: is_star_coauthored is stored in the main table PAPER_CONTRIB, but its only definition is in identity.output_rule
    — M5-T1 must import it and must not rewrite its own (two stages: empty star set → all False, backfilled after the freeze).
"""
import pytest


def _work(wid="W1", author_ids=("a1", "a2"), year=2010, subfield="2002", fwci=1.5):
    return {"work_id": wid, "author_ids": list(author_ids),
            "publication_year": year, "subfield_id": subfield, "fwci": fwci}


# ---- frac_credit = 1/number of distinct author_id ---------------------------

def test_frac_credit_is_one_over_author_count():
    """frac_credit = 1/number of authorships (4 authors → 0.25)."""
    from m5_output.paper_contrib import frac_credit
    assert frac_credit(["a", "b", "c", "d"]) == 0.25


def test_frac_credit_rejects_zero_authors():
    """0 authors → raise, never emit inf (1/0 was the old bug)."""
    from m5_output.paper_contrib import frac_credit
    with pytest.raises(ValueError):
        frac_credit([])


def test_author_count_distinct():
    """A repeated authorship counts as 1 person: ['a','a','b'] → distinct=2 → 0.5."""
    from m5_output.paper_contrib import frac_credit
    assert frac_credit(["a", "a", "b"]) == 0.5


def test_frac_credit_counts_author_id_not_person():
    """Does not change with U2 clustering: two author_ids folded into the same person still count as 2 authorships (frac=0.5, not 1.0)."""
    from m5_output.paper_contrib import build_paper_contrib_rows
    rows = build_paper_contrib_rows(
        _work(author_ids=("a1", "a2")),
        author_person={"a1": "P1", "a2": "P1"},  # a1,a2 clustered into P1
        incumbent_person_ids={"P1"},
    )
    assert rows, "in-post members must produce rows"
    assert all(r["frac_credit"] == 0.5 for r in rows)  # 2 author_ids, not 1 person


# ---- row schema is exactly 8 columns (imported from U0 [18]) ----------------

def test_paper_contrib_row_schema_matches_u0_8col():
    """The row key set is exactly the eight columns of PAPER_CONTRIB [18] (imported directly, not written as literals)."""
    from common.schema import PAPER_CONTRIB, assert_matches_schema
    from m5_output.paper_contrib import build_paper_contrib_rows
    rows = build_paper_contrib_rows(
        _work(author_ids=("a1",)),
        author_person={"a1": "P1"},
        incumbent_person_ids={"P1"},
    )
    assert len(rows) == 1
    assert_matches_schema(rows[0].keys(), PAPER_CONTRIB, label="paper_contrib")


# ---- row granularity = incumbent × person per work --------------------------

def test_rows_are_incumbent_by_person_per_work():
    """A work with 3 persons {I1,I2,A} and incumbents {I1,I2} → 2×3=6 rows
    (M5-T3 invariant: rows = sum over works of distinct incumbent × person)."""
    from m5_output.paper_contrib import build_paper_contrib_rows
    rows = build_paper_contrib_rows(
        _work(author_ids=("a_i1", "a_i2", "a_a")),
        author_person={"a_i1": "I1", "a_i2": "I2", "a_a": "A"},
        incumbent_person_ids={"I1", "I2"},
    )
    assert len(rows) == 6
    assert {r["incumbent_person_id"] for r in rows} == {"I1", "I2"}
    assert {r["person_id"] for r in rows} == {"I1", "I2", "A"}


def test_work_without_incumbent_yields_no_rows():
    """A work with no department incumbent → belongs to no unit under test → 0 rows."""
    from m5_output.paper_contrib import build_paper_contrib_rows
    rows = build_paper_contrib_rows(
        _work(author_ids=("a_x", "a_y")),
        author_person={"a_x": "X", "a_y": "Y"},
        incumbent_person_ids={"I1"},  # nobody on this paper
    )
    assert rows == []


# ---- isc#2: single definition + two stages ----------------------------------

def test_isc_is_the_unique_output_rule_definition():
    """The isc of M5-T1 is identity.output_rule.is_star_coauthored itself, not rewritten."""
    import identity.output_rule as orule
    import m5_output.paper_contrib as pc
    assert pc.is_star_coauthored is orule.is_star_coauthored


def test_isc_empty_star_set_all_false_stage1():
    """Stage one of the two stages: star set empty (M7a not frozen) → isc all False (placeholder, backfilled later)."""
    from m5_output.paper_contrib import build_paper_contrib_rows
    rows = build_paper_contrib_rows(
        _work(author_ids=("a1", "a_s")),
        author_person={"a1": "P1", "a_s": "STAR1"},
        incumbent_person_ids={"P1"},
        star_person_ids=frozenset(),  # not yet known who the stars are
    )
    assert rows
    assert all(r["is_star_coauthored"] is False for r in rows)


def test_isc_true_when_star_coauthor_present_stage2():
    """Stage two, backfill: the star set contains a co-author of the paper → every row of that work gets isc=True."""
    from m5_output.paper_contrib import build_paper_contrib_rows
    rows = build_paper_contrib_rows(
        _work(author_ids=("a1", "a_s")),
        author_person={"a1": "P1", "a_s": "STAR1"},
        incumbent_person_ids={"P1"},
        star_person_ids=frozenset({"STAR1"}),
    )
    assert rows
    assert all(r["is_star_coauthored"] is True for r in rows)


# ---- C1 guard: a None value in person_map → loud error carrying work_id (no silent skip) ------

def test_none_person_value_raises_located_error():
    """If upstream U2 breaks the contract and gives a None person_id: raise loudly (with work_id); never skip silently
    and never let sorted() crash with a TypeError that cannot be located. Fail loud, not extra tolerance."""
    from m5_output.paper_contrib import build_paper_contrib_rows
    with pytest.raises(ValueError) as ei:
        build_paper_contrib_rows(
            _work(wid="W_bad", author_ids=("a1", "a2")),
            author_person={"a1": "P1", "a2": None},  # U2 contract violated
            incumbent_person_ids={"P1"},
        )
    assert "W_bad" in str(ei.value)  # the error must locate the specific work
