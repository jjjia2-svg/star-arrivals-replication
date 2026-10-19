"""TDD red tests for U0 exit_codes.py.

Guards P-5 (the single source of truth for the whole pipeline's exit codes) + the tail of T37:
identity/exit_codes.py registers up to GOLDEN_FAIL=18, exactly the seven values 12-18.
The 1-11 range is "engineering to decide" and is not added here (only 12-18 are defined).
"""
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from identity import exit_codes  # noqa: E402


def test_exit_codes_verbatim_values_12_to_18():
    # the seven code values are pinned, never invented
    assert exit_codes.RESOLVE_GATE_FAIL == 12
    assert exit_codes.PROVENANCE_MISMATCH == 13
    assert exit_codes.STRUCTURAL_GATE_FAIL == 14
    assert exit_codes.TALLY_IMBALANCE == 15
    assert exit_codes.CAPACITY_GATE_FAIL == 16
    assert exit_codes.CORRUPT_SHARD == 17
    assert exit_codes.GOLDEN_FAIL == 18


def test_exit_codes_names_exist():
    # all seven named constants must be present (downstream imports must not dangle)
    for name in (
        "RESOLVE_GATE_FAIL",
        "PROVENANCE_MISMATCH",
        "STRUCTURAL_GATE_FAIL",
        "TALLY_IMBALANCE",
        "CAPACITY_GATE_FAIL",
        "CORRUPT_SHARD",
        "GOLDEN_FAIL",
    ):
        assert hasattr(exit_codes, name), f"missing exit-code constant {name}"


def test_exit_codes_1_to_11_not_self_added():
    # Discipline: only 12-18 are defined; the 1-11 range is "to be registered / engineering to decide" and is not added here.
    # Guard "never invented": the module must contain no named exit-code constant whose value falls in 1-11.
    public_int_consts = {
        k: v
        for k, v in vars(exit_codes).items()
        if not k.startswith("_") and isinstance(v, int) and not isinstance(v, bool)
    }
    offending = {k: v for k, v in public_int_consts.items() if 1 <= v <= 11}
    assert offending == {}, f"must not add exit-code constants in the 1–11 range: {offending}"


def test_exit_codes_no_duplicate_values():
    # exit codes must be distinguishable: the seven values 12-18 are all different
    values = [
        exit_codes.RESOLVE_GATE_FAIL,
        exit_codes.PROVENANCE_MISMATCH,
        exit_codes.STRUCTURAL_GATE_FAIL,
        exit_codes.TALLY_IMBALANCE,
        exit_codes.CAPACITY_GATE_FAIL,
        exit_codes.CORRUPT_SHARD,
        exit_codes.GOLDEN_FAIL,
    ]
    assert len(set(values)) == len(values), "duplicate exit-code values"


# --- C-B (U1 alignment addition, 19-23): used by the new U1 fetch/write gates ---
def test_exit_codes_u1_new_codes_exist_and_values_19_to_23():
    # the five new codes exist by name (U1 imports must not dangle) + consecutive 19-23
    assert exit_codes.EXIT_FIELDS_MISSING == 19
    assert exit_codes.EXIT_FRONTIER_MISS == 20
    assert exit_codes.EXIT_DEDUP_NONZERO == 21
    assert exit_codes.EXIT_CANONICAL_SPACE_SPLIT == 22
    assert exit_codes.EXIT_MERKLE_INVALID == 23


def test_exit_codes_all_distinct_12_to_23():
    # 12-23 are all different (new codes do not collide with old codes or each other)
    values = [
        exit_codes.RESOLVE_GATE_FAIL,
        exit_codes.PROVENANCE_MISMATCH,
        exit_codes.STRUCTURAL_GATE_FAIL,
        exit_codes.TALLY_IMBALANCE,
        exit_codes.CAPACITY_GATE_FAIL,
        exit_codes.CORRUPT_SHARD,
        exit_codes.GOLDEN_FAIL,
        exit_codes.EXIT_FIELDS_MISSING,
        exit_codes.EXIT_FRONTIER_MISS,
        exit_codes.EXIT_DEDUP_NONZERO,
        exit_codes.EXIT_CANONICAL_SPACE_SPLIT,
        exit_codes.EXIT_MERKLE_INVALID,
    ]
    assert len(set(values)) == len(values), "duplicate exit-code values in 12–23"


# --- U2 alignment addition (24): used by the U2 entry canonical-space gate ---
def test_exit_codes_u2_input_not_canonical_exists_and_value_24():
    # U2 entry author_id still has an unnormalised redirect -> EXIT_INPUT_NOT_CANONICAL=24
    # (24 = the next free number after 12-23 are all taken; 13 is already PROVENANCE_MISMATCH and cannot be borrowed)
    assert exit_codes.EXIT_INPUT_NOT_CANONICAL == 24


def test_exit_codes_all_distinct_12_to_24():
    # 12-24 are all different (the new U2 code does not collide with 12-23)
    values = [
        exit_codes.RESOLVE_GATE_FAIL,
        exit_codes.PROVENANCE_MISMATCH,
        exit_codes.STRUCTURAL_GATE_FAIL,
        exit_codes.TALLY_IMBALANCE,
        exit_codes.CAPACITY_GATE_FAIL,
        exit_codes.CORRUPT_SHARD,
        exit_codes.GOLDEN_FAIL,
        exit_codes.EXIT_FIELDS_MISSING,
        exit_codes.EXIT_FRONTIER_MISS,
        exit_codes.EXIT_DEDUP_NONZERO,
        exit_codes.EXIT_CANONICAL_SPACE_SPLIT,
        exit_codes.EXIT_MERKLE_INVALID,
        exit_codes.EXIT_INPUT_NOT_CANONICAL,
    ]
    assert len(set(values)) == len(values), "duplicate exit-code values in 12–24"
