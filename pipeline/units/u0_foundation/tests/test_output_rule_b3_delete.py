"""B3: delete OUTPUT.citation_weighted.

It was computed as a clone of fwci_frac (the same Σ frac_credit×fwci); with no cited_by_count in its input it
cannot produce a true "citation-weighted" value, so it is a redundant, wrong value: the same quantity under a different
label, with zero downstream consumers. None of the star-spillover literature (6 papers, DOIs
checked one by one) reports the two output definitions "raw citation weighting + field normalisation" side by
side, so keeping the clone is the worst option. The column is removed.
The second outcome that is really missing is the "publication count", built in U5/U6 (to address the quantity vs quality question).
"""
from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common.schema import OUTPUT  # noqa: E402
from identity.output_rule import aggregate_output  # noqa: E402


def test_output_schema_has_no_citation_weighted():
    """The OUTPUT schema no longer contains citation_weighted (the clone column is deleted)."""
    assert "citation_weighted" not in OUTPUT


def test_aggregate_output_row_has_no_citation_weighted():
    """Output rows no longer contain citation_weighted; the headline fwci_frac_ex_star and the others remain."""
    rows = aggregate_output([
        {"incumbent_person_id": "P", "year": 2015, "frac_credit": 0.5,
         "fwci": 4.0, "is_star_coauthored": False},
    ])
    assert "citation_weighted" not in rows[0]
    assert "fwci_frac_ex_star" in rows[0]     # the headline output metric is kept
