"""Tests for the U0 redlines threshold entry point (T36).

Two rules:
  1. Unset red-line keys (entity_resolve.score_threshold / reverse_validate.* /
     fwci.snapshot_year etc., 13 in all) = None (null); a function that reads one
     and gets None must raise, never fall back to a default (placeholder rule).
  2. The _redlines.RED literal dict and the safe_load result of contracts/redlines.yaml
     have the same SHA (prevents the YAML and the code from drifting apart; preflight
     environment gate (3) compares it too).

Mechanism: a person edits the YAML, _redlines.py imports the literal dict (identity, zero IO).
These tests are local only: no network, no fetching.
"""
import hashlib
import json
import pathlib
import sys

import pytest
import yaml

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

# contracts/ is under the multiplex_pipeline/ root (the grandparent of units/u0_foundation)
PIPELINE_ROOT = pathlib.Path(__file__).resolve().parents[3]
REDLINES_YAML = PIPELINE_ROOT / "contracts" / "redlines.yaml"

from common._redlines import (  # noqa: E402
    RED,
    RedlineUnsigned,
    require,
)


# --- T36 half 2: the RED dict has the same SHA as the YAML safe_load ---

def _canonical_sha(obj) -> str:
    """Deterministic SHA of any JSON-able structure (sort_keys, compact separators)."""
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def test_red_dict_sha_matches_yaml_safe_load():
    # the RED literal dict must match the safe_load of contracts/redlines.yaml exactly
    with open(REDLINES_YAML, "r", encoding="utf-8") as fh:
        from_yaml = yaml.safe_load(fh)
    assert _canonical_sha(RED) == _canonical_sha(from_yaml), (
        "RED literals drift from redlines.yaml — keys must match one by one (preflight environment gate 3 checks the same)"
    )


def test_redlines_yaml_exists_and_parses():
    assert REDLINES_YAML.exists(), f"missing contracts/redlines.yaml: {REDLINES_YAML}"
    with open(REDLINES_YAML, "r", encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh)
    assert isinstance(loaded, dict)


# --- T36 half 1: unset key = None -> require() raises on None ---

# red-line keys that are still None placeholders (once a key gets a value, move it to the set-value assertions)
UNSIGNED_KEYS = [
    # ("fwci", "snapshot_year") - set (= the frozen snapshot of 2026-06-29); moved to the set-value assertions below
    # ("entity_resolve", "score_threshold") - set (=0.8, calibrated on real data); moved to the set-value assertions below
    ("entity_resolve", "homogeneity_min"),
    ("entity_resolve", "completeness_min"),
    ("reverse_validate", "recall_large_dept"),
    ("reverse_validate", "recall_small_dept"),
    ("reverse_validate", "precision_min"),
    ("reverse_validate", "completeness_min"),
    ("reverse_validate", "homogeneity_min"),
    ("reverse_validate", "faceting_recall_min"),
    ("failure_class", "unknown_default_class"),
    # ("reconcile", "diff_tolerance") - set (=0); moved to the set-value assertions below
    # ("output_quality", "need_leave_star_output") - set (=true, p01/p05 two tables from the same source); moved to the set-value assertions below
    # list completed to match the YAML count (13 -> 17); defence in depth:
    ("resolve", "subfield_coverage_floor"),
    # ("dose", "coupling_normalization") - set (=cosine, the U5 v3 final value); moved to the set-value assertions below
    # ("dose", "hub_ref_idf_floor") - set (=0.0, same); moved to the set-value assertions below
    # ("dose", "coverage_floor") - set (=0.0, same); moved to the set-value assertions below
]

# The three dose keys have values (cosine as the main normalisation, both floors 0.0).
# Symmetric guard: the RED value equals the set value verbatim and require() returns it unchanged.
DOSE_SIGNED_KEYS = [
    ("dose", "coupling_normalization", "cosine"),
    ("dose", "hub_ref_idf_floor", 0.0),
    ("dose", "coverage_floor", 0.0),
]


@pytest.mark.parametrize("section,key", UNSIGNED_KEYS)
def test_unsigned_key_is_none_in_red(section, key):
    # the 13 unset keys must be None in RED (never a silent default value)
    assert RED[section][key] is None, (
        f"{section}.{key} must stay None (unset red-line placeholder); filling in a default yourself crosses the line"
    )


@pytest.mark.parametrize("section,key", UNSIGNED_KEYS)
def test_require_on_unsigned_key_raises(section, key):
    # reading an unset key (None) -> require() raises RedlineUnsigned, never silently returns None or a default
    with pytest.raises(RedlineUnsigned):
        require(section, key)


@pytest.mark.parametrize("section,key,expected", DOSE_SIGNED_KEYS)
def test_dose_signed_key_value_in_red(section, key, expected):
    # the three dose keys have values: in RED they equal those values verbatim (any drift fails this test)
    assert RED[section][key] == expected


@pytest.mark.parametrize("section,key,expected", DOSE_SIGNED_KEYS)
def test_require_on_dose_signed_key_returns_value(section, key, expected):
    # once a key has a value, require() returns it unchanged and no longer raises (replaces the former unset double guard)
    assert require(section, key) == expected


def test_require_on_signed_key_returns_value():
    # a set value returns normally (require only blocks None, not real values)
    assert require("cohort", "same_gen_max_gap_years") == 5
    assert require("education_whitelist") == ["education"]
    assert require("star", "percentile_primary") == 0.01


def test_snapshot_year_signed_s8_2():
    # FWCI citation counts use the frozen snapshot of 2026-06-29 (merkle da78e4b9)
    assert require("fwci", "snapshot_year") == "snapshot_2026-06-29_merkle_da78e4b9"


def test_need_leave_star_output_signed_s8_6():
    # produce the leave-star version of OUTPUT (p01/p05, two tables from the same source)
    assert require("output_quality", "need_leave_star_output") is True


def test_require_missing_key_raises_keyerror():
    # a key that does not exist at all -> KeyError (a misspelt key name must blow up, not fall back silently)
    with pytest.raises(KeyError):
        require("entity_resolve", "no_such_threshold")


# --- spot checks of the set values (the set-value block is in place verbatim) ---

def test_signed_truth_block_spot_checks():
    assert RED["cohort"]["same_gen_max_gap_years"] == 5
    assert RED["cohort"]["robustness_gap_years"] == [4, 8, 10]
    assert RED["academic_age"]["baseline"] == "career_first_pub_year"
    assert RED["fwci"]["field_level"] == "subfield"
    assert RED["fwci"]["expected_method"] == "mean"
    assert RED["fwci"]["denominator_leave_star"] is False
    assert RED["fwci"]["numerator_leave_star"] is True
    assert RED["arrival"]["trust_affiliations_years"] is False
    assert RED["star"]["percentile_primary"] == 0.01
    assert RED["star"]["percentile_robustness"] == [0.01, 0.05]
    assert RED["subfield_whitelist"]["include"] == ["2002"]
    assert RED["generation"]["gen_pk_includes_year"] is False
    assert RED["population_gate"]["pop_min"] == "ge_2_distinct_publication_years"
    assert RED["pass_c"]["missing_ratio_halt"] == 0.15  # tolerance threshold for dangling references
    assert RED["reconcile"]["diff_tolerance"] == 0      # four-number reconciliation with zero tolerance
    assert RED["entity_resolve"]["score_threshold"] == 0.8  # calibrated on real data: 0.75, in the middle of the cliff band
    assert RED["rule_version"] == "redlines_v4_signed_2026-07-05"
