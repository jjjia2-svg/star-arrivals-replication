"""M7a-T2 subfield_assign — person×year subfield = the mode of that year's papers, ties take the lexicographically smallest (checks #28/#39, S8-3).

In plain words: in one year a person published several papers, each in some subfield. Take "the subfield that appears most" as the person's subfield for that year;
if several tie, take the smallest id (deterministic, reproducible).

Fixed rules: S8-3: person×year subfield = the mode of that year's papers, ties take the lexicographically smallest
(subfield_id is a 4-character code string, so lexicographically smallest = smallest id).
"""
import pytest


def test_mode_is_most_frequent_subfield():
    """Mode: 2002 appears 2 times > 2003 once → 2002."""
    from m7a_star.subfield_assign import assign_subfield
    assert assign_subfield(["2002", "2002", "2003"]) == "2002"


def test_tiebreak_lexicographically_smallest():
    """Tie (once each) → take the lexicographically smallest / smallest id: {2003, 2002} → 2002."""
    from m7a_star.subfield_assign import assign_subfield
    assert assign_subfield(["2003", "2002"]) == "2002"


def test_input_order_independent():
    """Input order does not affect the result (deterministic): shuffling the input two ways gives the same result."""
    from m7a_star.subfield_assign import assign_subfield
    a = assign_subfield(["2003", "2002", "2002"])
    b = assign_subfield(["2002", "2002", "2003"])
    assert a == b == "2002"


def test_tiebreak_three_way_smallest():
    """Three tied at once each → the smallest: {2005, 2002, 2003} → 2002."""
    from m7a_star.subfield_assign import assign_subfield
    assert assign_subfield(["2005", "2002", "2003"]) == "2002"


def test_empty_raises():
    """No papers → raise (a person×year without papers must not be assigned a subfield; the gap fails loudly, not silently)."""
    from m7a_star.subfield_assign import assign_subfield
    with pytest.raises(ValueError):
        assign_subfield([])
