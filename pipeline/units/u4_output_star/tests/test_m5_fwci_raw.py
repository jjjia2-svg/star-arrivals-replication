"""M5-T2 fwci_raw — per-paper citation ratio normalised within the self-built field.

Rules: fwci = cited_by_count / expected (the "divide" step of divide-then-average); a missing cell → None, never 0;
missing_fill=NA; too_new → NA + flag; a missing subfield → field-level fallback + [inferred] flag;
three steps in order (whitelist → paratext symmetric drop → winsor p99).
"""
import pytest


def _w(wid="W1", subfield="2002", year=2010, wtype="article", cites=10,
       paratext=False):
    return {"work_id": wid, "subfield_id": subfield, "publication_year": year,
            "work_type": wtype, "cited_by_count": cites, "is_paratext": paratext}


_EXP = {("2002", 2010, "article"): 5.0}


def test_fwci_self_is_citations_over_expected():
    """fwci = own citations ÷ expected for its cell (10/5 = 2.0)."""
    from m5_output.fwci_raw import compute_fwci

    r = compute_fwci(_w(cites=10), _EXP)
    assert r["fwci"] == 2.0
    assert r["fwci_missing_reason"] is None


def test_fwci_self_missing_cell_returns_none_not_zero():
    """Regression on the old bug: cell missing (no baseline) → fwci=None + reason, never filled with 0."""
    from m5_output.fwci_raw import compute_fwci

    r = compute_fwci(_w(year=1999), _EXP)  # no baseline for (2002,1999,article)
    assert r["fwci"] is None
    assert r["fwci_missing_reason"] == "missing_cell"


def test_excluded_type_gets_none_with_reason():
    """Step 1: non-whitelisted types (editorial etc.) get no score → None + reason (the whole type is dropped)."""
    from m5_output.fwci_raw import compute_fwci

    r = compute_fwci(_w(wtype="editorial"), _EXP)
    assert r["fwci"] is None
    assert r["fwci_missing_reason"] == "excluded_type"


def test_paratext_symmetric_drop():
    """Step 2 (real key paratext_symmetric_drop=true): is_paratext → dropped (symmetric;
    the denominator side is dropped too, guaranteed upstream by the baseline whitelist + POP; this is the numerator side)."""
    from m5_output.fwci_raw import compute_fwci

    r = compute_fwci(_w(paratext=True), _EXP)
    assert r["fwci"] is None
    assert r["fwci_missing_reason"] == "paratext"


def test_field_fallback_marks_inferred():
    """Missing subfield → field-level denominator fallback + [inferred] flag
    (fwci_inferred_fallback=True); both levels missing → None + reason."""
    from m5_output.fwci_raw import compute_fwci

    field_exp = {("11", 2010, "article"): 4.0}  # field-level baseline (economics field)
    r = compute_fwci(_w(subfield=None, cites=8), _EXP,
                     field_expected={("11", 2010, "article"): 4.0},
                     field_of_work=lambda w: "11")
    assert r["fwci"] == 2.0  # 8/4 — uses the field-level denominator
    assert r["fwci_inferred_fallback"] is True

    r2 = compute_fwci(_w(subfield=None), _EXP)  # no field baseline to fall back on
    assert r2["fwci"] is None
    assert r2["fwci_missing_reason"] == "missing_subfield_no_fallback"


def test_zero_expected_cell_is_na_not_crash():
    """Found on real data (the two-school run crashed after 11.4 s): in fwci_baseline_pop, 8,793
    article/review cells have zero citations in the whole pool (citation_sum=0, mostly single-paper cells from the 1600s-1700s)
    → expected=0.0 → division by zero. The rule "cannot compute → NA + reason, never 0" covers this case word for word:
    denominator 0 = ratio undefined = cannot compute → fwci=None + reason=zero_expected_cell
    (an engineering branch for missing values, not a change of definition; NA counts are still written to _reports)."""
    from m5_output.fwci_raw import compute_fwci

    r = compute_fwci(_w(cites=0, year=1700), {("2002", 1700, "article"): 0.0})
    assert r["fwci"] is None
    assert r["fwci_missing_reason"] == "zero_expected_cell"


def test_zero_expected_field_fallback_is_na_too():
    """The field-level fallback denominator has the same guard: field expected=0 → also NA + reason (no [inferred] flag —
    no value was computed), no division by zero."""
    from m5_output.fwci_raw import compute_fwci

    r = compute_fwci(_w(subfield=None, cites=0, year=1700), {},
                     field_expected={("11", 1700, "article"): 0.0},
                     field_of_work=lambda w: "11")
    assert r["fwci"] is None
    assert r["fwci_missing_reason"] == "zero_expected_cell"
    assert r["fwci_inferred_fallback"] is False


def test_winsorize_upper_is_p99():
    """winsorize_fwci pure function, kept for history: p99 cap — values above p99 are set to p99, the rest are untouched.
    Production no longer calls it (on the shipping path fwci passes through as is); the function and this test are kept
    only as a reference for the analysis layer (see the fwci_raw.winsorize_fwci docstring)."""
    from m5_output.fwci_raw import winsorize_fwci

    vals = [float(i) for i in range(1, 101)]  # 1..100, p99=99.01 (linear interpolation)
    capped = winsorize_fwci(vals)
    assert max(capped) == pytest.approx(99.01)
    assert capped[:98] == vals[:98]  # low values untouched
    assert winsorize_fwci([]) == []  # empty set does not blow up
