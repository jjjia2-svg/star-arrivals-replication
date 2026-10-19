"""DEPT_ROSTER_PANEL_V2 (table B v2) tests.

In plain words: affil_type used to be written only as an evidence string, so downstream code could
not filter on it, and the source of the arrival year could not be traced. Both are now proper
schema columns.

Rules (nothing may break):
  - the old 8-column DEPT_ROSTER_PANEL is unchanged (frozen artifacts and downstream u2/u4/u6 still assert 8 columns);
  - V2 = the 8 base columns in the original order + affil_type + year_start_provenance (appended at the end);
  - new roster outputs go to a new dated directory in V2 and never overwrite frozen artifacts.

Value domains (mechanical, not identification choices):
  affil_type in {dept_only, centre_only, both}
  year_start_provenance in {bio_stated, snapshot_first_seen, unknown}
"""
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common.schema import (  # noqa: E402
    DEPT_ROSTER_PANEL,
    DEPT_ROSTER_PANEL_V2,
    assert_matches_schema,
)


def test_v1_untouched_exactly_8_cols():
    """The old 8 columns are unchanged (contract for downstream frozen artifacts)."""
    assert list(DEPT_ROSTER_PANEL.keys()) == [
        "dept_key", "author_id", "display_name", "year_start", "year_end",
        "evidence", "confidence", "human_verified",
    ]
    assert "affil_type" not in DEPT_ROSTER_PANEL
    assert "year_start_provenance" not in DEPT_ROSTER_PANEL


def test_v2_is_v1_plus_two_tail_cols():
    """V2 = the 8 V1 columns in the original order + affil_type + year_start_provenance (exactly 10 columns, appended at the end)."""
    keys = list(DEPT_ROSTER_PANEL_V2.keys())
    assert keys == list(DEPT_ROSTER_PANEL.keys()) + [
        "affil_type", "year_start_provenance",
    ]
    assert len(DEPT_ROSTER_PANEL_V2) == 10
    # the types of the 8 base columns are inherited verbatim
    for k, v in DEPT_ROSTER_PANEL.items():
        assert DEPT_ROSTER_PANEL_V2[k] == v


def test_v2_new_cols_are_category():
    assert DEPT_ROSTER_PANEL_V2["affil_type"] == "category"
    assert DEPT_ROSTER_PANEL_V2["year_start_provenance"] == "category"


def test_v2_row_asserts_exact_ten_keys():
    """The V2 row key set is exactly 10 keys: feeding a V1 row to V2 -> raise (2 keys missing); feeding a V2 row to V1 -> raise (2 extra keys)."""
    v1_keys = set(DEPT_ROSTER_PANEL.keys())
    v2_keys = set(DEPT_ROSTER_PANEL_V2.keys())
    assert_matches_schema(v2_keys, DEPT_ROSTER_PANEL_V2, label="v2_ok")
    with pytest.raises(Exception):
        assert_matches_schema(v1_keys, DEPT_ROSTER_PANEL_V2, label="v1_row_vs_v2")
    with pytest.raises(Exception):
        assert_matches_schema(v2_keys, DEPT_ROSTER_PANEL, label="v2_row_vs_v1")
