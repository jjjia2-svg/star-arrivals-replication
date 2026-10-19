"""TDD red tests for U0 identity/output_rule.py.

Module duty (C.4):
  - is_star_coauthored(work, star_person_ids) -> bool: the single definition (2 arguments, no parallel set);
    no downstream code may rewrite it; all of it imports this function.
  - aggregate_output(...): produces the OUTPUT table (per person per year);
    fwci_frac_ex_star = the version without star co-authored papers (numerator_leave_star=true / denominator_leave_star=false).

T35 star-removal isolation (the main point of this file): the code path of the FWCI baseline node
(fwci_baseline_contribution / the accumulation path) never reads the is_star_coauthored column
(guards denominator_leave_star=false).
  Two guards:
    (1) Behaviour: the baseline contribution function gives exactly the same output for input "with the is_star_coauthored column" and "without" (so it did not read it).
    (2) Static source: the literal 'is_star_coauthored' does not appear in the source of the baseline contribution function (it does not rely on that column).
"""
import inspect
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from identity import output_rule  # noqa: E402

STAR_A = "P_star_A"
STAR_B = "P_star_B"
INCUMBENT = "P_incumbent"


# ===========================================================================
# C.4: the single definition of is_star_coauthored (2 arguments, no parallel set)
# ===========================================================================

def test_is_star_coauthored_signature_exactly_two_params():
    # Rule: a single definition with exactly 2 parameters (work, star_person_ids); no third argument for a parallel set
    sig = inspect.signature(output_rule.is_star_coauthored)
    params = list(sig.parameters.keys())
    assert params == ["work", "star_person_ids"], f"must take exactly 2 parameters, got {params}"


def test_is_star_coauthored_true_when_any_author_is_star():
    # a co-author person_id of the work is in the star set -> True
    work = {"work_id": "W1", "author_person_ids": [INCUMBENT, STAR_A]}
    assert output_rule.is_star_coauthored(work, {STAR_A, STAR_B}) is True


def test_is_star_coauthored_false_when_no_author_is_star():
    work = {"work_id": "W2", "author_person_ids": [INCUMBENT, "P_other"]}
    assert output_rule.is_star_coauthored(work, {STAR_A, STAR_B}) is False


def test_is_star_coauthored_false_on_empty_star_set():
    work = {"work_id": "W3", "author_person_ids": [INCUMBENT, STAR_A]}
    assert output_rule.is_star_coauthored(work, set()) is False


def test_is_star_coauthored_accepts_list_or_set_star_ids():
    # star_person_ids may be a list or a set, with the same behaviour
    work = {"work_id": "W4", "author_person_ids": [STAR_B]}
    assert output_rule.is_star_coauthored(work, [STAR_A, STAR_B]) is True
    assert output_rule.is_star_coauthored(work, {STAR_A, STAR_B}) is True


def test_is_star_coauthored_returns_real_bool():
    work = {"work_id": "W5", "author_person_ids": [STAR_A]}
    out = output_rule.is_star_coauthored(work, {STAR_A})
    assert out is True and isinstance(out, bool)


# ===========================================================================
# T35: the FWCI baseline node never reads is_star_coauthored
# ===========================================================================

def test_T35_fwci_baseline_source_does_not_reference_is_star_coauthored():
    # Static guard: 'is_star_coauthored' does not appear in the executable code of the baseline contribution function (star-removal isolation).
    # Check only the code body, with the docstring stripped (the docstring may mention the word to explain "why it is not read").
    fn = output_rule.fwci_baseline_contribution
    src = inspect.getsource(fn)
    doc = fn.__doc__ or ""
    code_only = src.replace(doc, "")   # strip the docstring text, leaving only executable code + signature
    assert "is_star_coauthored" not in code_only, (
        "the FWCI baseline node's code path must never read the is_star_coauthored column (denominator_leave_star=false)"
    )


def test_T35_fwci_baseline_ignores_star_flag_behaviorally():
    # Behaviour guard: the baseline contribution gives exactly the same output for input "with is_star_coauthored" and "without" -> proves it did not read it.
    # Baseline contribution = accumulating the denominator population, independent of star co-authorship (the denominator keeps stars).
    work_with_flag = {
        "subfield_id": "2002", "year": 2016, "work_type": "article",
        "cited_by_count": 10, "is_star_coauthored": True,   # the column is present but must be ignored
    }
    work_without_flag = {
        "subfield_id": "2002", "year": 2016, "work_type": "article",
        "cited_by_count": 10,
    }
    assert (
        output_rule.fwci_baseline_contribution(work_with_flag)
        == output_rule.fwci_baseline_contribution(work_without_flag)
    )


def test_T35_fwci_baseline_contribution_shape():
    # the baseline contribution returns the denominator accumulation key: (subfield_id, year, work_type) -> cited_by_count
    work = {"subfield_id": "2002", "year": 2016, "work_type": "article", "cited_by_count": 7}
    out = output_rule.fwci_baseline_contribution(work)
    assert out["key"] == ("2002", 2016, "article")
    assert out["cited_by_count"] == 7


# ===========================================================================
# C.4: aggregate_output rule (fwci_frac_ex_star drops stars from the numerator / the denominator keeps them)
# ===========================================================================

def test_aggregate_output_drops_star_in_numerator_only():
    # Two papers: one star co-authored (fwci=4), one not (fwci=2), same person and same year.
    #   fwci_frac      = all of them = 4*0.5 + 2*0.5 = 3.0 (the numerator keeps everything)
    #   fwci_frac_ex_star = without the star co-authored paper = only 2*0.5 = 1.0 (numerator_leave_star=true)
    contribs = [
        {"incumbent_person_id": INCUMBENT, "year": 2016, "frac_credit": 0.5,
         "fwci": 4.0, "is_star_coauthored": True},
        {"incumbent_person_id": INCUMBENT, "year": 2016, "frac_credit": 0.5,
         "fwci": 2.0, "is_star_coauthored": False},
    ]
    rows = output_rule.aggregate_output(contribs)
    assert len(rows) == 1
    row = rows[0]
    assert row["incumbent_person_id"] == INCUMBENT
    assert row["year"] == 2016
    assert row["fwci_frac"] == 3.0          # the numerator keeps stars
    assert row["fwci_frac_ex_star"] == 1.0  # the numerator drops star co-authored papers


def test_aggregate_output_row_keys_match_output_schema():
    # the key set of an output row = the 12 keys of the OUTPUT schema;
    # assert_matches_schema must pass
    from common.schema import OUTPUT, assert_matches_schema
    contribs = [
        {"incumbent_person_id": INCUMBENT, "year": 2016, "frac_credit": 1.0,
         "fwci": 3.0, "is_star_coauthored": False},
    ]
    rows = output_rule.aggregate_output(contribs)
    # must not raise SchemaMismatchError
    assert_matches_schema(rows[0].keys(), OUTPUT, label="OUTPUT")


def test_aggregate_output_groups_per_person_per_year():
    # per person per year: the same person in different years -> two rows; different people -> a row each
    contribs = [
        {"incumbent_person_id": INCUMBENT, "year": 2016, "frac_credit": 1.0,
         "fwci": 1.0, "is_star_coauthored": False},
        {"incumbent_person_id": INCUMBENT, "year": 2017, "frac_credit": 1.0,
         "fwci": 1.0, "is_star_coauthored": False},
        {"incumbent_person_id": "P_other", "year": 2016, "frac_credit": 1.0,
         "fwci": 1.0, "is_star_coauthored": False},
    ]
    rows = output_rule.aggregate_output(contribs)
    keys = {(r["incumbent_person_id"], r["year"]) for r in rows}
    assert keys == {(INCUMBENT, 2016), (INCUMBENT, 2017), ("P_other", 2016)}


def test_aggregate_output_pub_count_counts_contributions():
    # The count key is pub_count (formerly n_works)
    # (plain-count semantics unchanged: each paper counts 1, regardless of fwci / star flag). The assertion on it was updated accordingly.
    contribs = [
        {"incumbent_person_id": INCUMBENT, "year": 2016, "frac_credit": 0.5,
         "fwci": 1.0, "is_star_coauthored": False},
        {"incumbent_person_id": INCUMBENT, "year": 2016, "frac_credit": 0.5,
         "fwci": 1.0, "is_star_coauthored": True},
    ]
    rows = output_rule.aggregate_output(contribs)
    assert rows[0]["pub_count"] == 2
