"""Tests for U0 star_rule.py.

Covers:
  - is_star uses the redlines.RED["star"]["percentile_primary"] threshold (top 1%);
    no identification-level number is hard-coded in the module.
  - identity rule: no IO / no network / no state; an unset (None) threshold -> raise, never a default.
  - interface contract: is_star returns a bare bool/None;
    a thin cell (samples in the cell < cell_min_n) -> None (no forced star call).

Rule (plain words): star = the researcher's citation percentile (0..1, larger = higher) within the
"same subfield x same arrival-year cohort" is >= 1 - percentile_primary (i.e. falls in the top percentile_primary).
percentile_primary=0.01 -> the top 1% are stars (read from RED, not hard-coded).

These tests are local only: no network, no fetching. They test only "read from RED / None -> raise" for the threshold values and do not copy identification constants into the tests.
"""
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common._redlines import RED, RedlineUnsigned  # noqa: E402
from identity import star_rule  # noqa: E402


# A cell counts as "thick" (a star call is possible) when its sample count is >= the cohort's cell_min_n.
# The floor is read from RED (no specific number is hard-coded in the tests).
_FLOOR_N = RED["star"]["cell_min_n"]["floor"]
_THICK_N = _FLOOR_N + 5      # thick cell: far above the floor
_THIN_N = max(_FLOOR_N - 1, 0)  # thin cell: below the floor


def _row(*, citation_percentile, cell_n):
    """Build the is_star input row (per-person-per-cohort citation percentile + the cell's sample count)."""
    return {"citation_percentile": citation_percentile, "cell_n": cell_n}


# ============ main definition: inside the top percentile_primary = star ============

def test_is_star_true_when_in_top_percentile():
    # citation percentile 0.999 (top) and the cell is thick enough -> star True
    row = _row(citation_percentile=0.999, cell_n=_THICK_N)
    assert star_rule.is_star(row) is True


def test_is_star_false_when_below_cutoff():
    # citation percentile 0.50 (mid) -> not a star False
    row = _row(citation_percentile=0.50, cell_n=_THICK_N)
    assert star_rule.is_star(row) is False


def test_is_star_boundary_exactly_at_cutoff_is_star():
    # exactly at cutoff = 1 - percentile_primary -> the endpoint counts as a star (>=)
    p = RED["star"]["percentile_primary"]
    cutoff = 1.0 - p
    row = _row(citation_percentile=cutoff, cell_n=_THICK_N)
    assert star_rule.is_star(row) is True


def test_is_star_just_below_cutoff_not_star():
    p = RED["star"]["percentile_primary"]
    cutoff = 1.0 - p
    row = _row(citation_percentile=cutoff - 1e-6, cell_n=_THICK_N)
    assert star_rule.is_star(row) is False


# ============ thin cell -> None (no forced call; interface contract "thin cell -> None") ============

def test_is_star_thin_cell_returns_none():
    # cell sample below the floor -> None (no forced star call even when the percentile is very high)
    row = _row(citation_percentile=0.999, cell_n=_THIN_N)
    assert star_rule.is_star(row) is None


# ============ the threshold is read only from RED + None -> raise (red-line placeholder rule) ============

def test_is_star_reads_percentile_from_red_not_hardcoded(monkeypatch):
    # Temporarily change RED's percentile_primary to 0.10 -> cutoff becomes 0.90;
    # percentile 0.95 should now be called a star (proving it is read from RED, not hard-coded 0.01).
    monkeypatch.setitem(RED["star"], "percentile_primary", 0.10)
    row = _row(citation_percentile=0.95, cell_n=_THICK_N)
    assert star_rule.is_star(row) is True
    # the same row under the 0.01 definition (cutoff 0.99) should not be a star -> proves the threshold takes effect from RED
    monkeypatch.setitem(RED["star"], "percentile_primary", 0.01)
    assert star_rule.is_star(row) is False


def test_is_star_raises_when_percentile_unsigned(monkeypatch):
    # percentile_primary = None (unset placeholder) -> raise RedlineUnsigned, never a default
    monkeypatch.setitem(RED["star"], "percentile_primary", None)
    row = _row(citation_percentile=0.999, cell_n=_THICK_N)
    with pytest.raises(RedlineUnsigned):
        star_rule.is_star(row)


def test_is_star_raises_when_floor_unsigned(monkeypatch):
    # cell_min_n.floor = None (unset placeholder) -> raise (a missing thin/thick threshold must not get a default)
    monkeypatch.setitem(RED["star"]["cell_min_n"], "floor", None)
    row = _row(citation_percentile=0.999, cell_n=100)
    with pytest.raises(RedlineUnsigned):
        star_rule.is_star(row)


# ============ missing field -> raise (a None input is not silent) ============

def test_is_star_none_row_raises():
    with pytest.raises((ValueError, KeyError, TypeError)):
        star_rule.is_star(None)


def test_is_star_missing_citation_percentile_raises():
    with pytest.raises((ValueError, KeyError)):
        star_rule.is_star({"cell_n": _THICK_N})


def test_is_star_none_citation_percentile_raises():
    # the percentile itself is None (upstream could not compute it) -> raise, never treated as 0
    row = _row(citation_percentile=None, cell_n=_THICK_N)
    with pytest.raises((ValueError, TypeError)):
        star_rule.is_star(row)


# ============ parameterised entry is_star(row, p=...) - the top-5% star entry ============

def test_is_star_5pct_entry_uses_1_minus_p_cutoff():
    # p=0.05 -> cutoff = 0.95; percentile 0.96 (>=0.95) and a thick cell -> star True
    assert star_rule.is_star(_row(citation_percentile=0.96, cell_n=_THICK_N), p=0.05) is True
    # 0.94 (<0.95) -> not a star (proves the cutoff varies with p)
    assert star_rule.is_star(_row(citation_percentile=0.94, cell_n=_THICK_N), p=0.05) is False


def test_is_star_default_p_falls_back_to_primary():
    # p not passed -> falls back to percentile_primary (backward compatible); passing the same value explicitly gives the same result
    p = RED["star"]["percentile_primary"]
    cutoff = 1.0 - p
    row = _row(citation_percentile=cutoff, cell_n=_THICK_N)
    assert star_rule.is_star(row) is True
    assert star_rule.is_star(row, p=p) is True
    # 0.94 is not a star under the default 1% definition (cutoff 0.99)
    assert star_rule.is_star(_row(citation_percentile=0.94, cell_n=_THICK_N)) is False


def test_is_star_5pct_thin_cell_still_none():
    # the parameterised entry also keeps the thin gate: thin cell -> None (the floor thin gate does not depend on p)
    assert star_rule.is_star(_row(citation_percentile=0.999, cell_n=_THIN_N), p=0.05) is None
