"""Smoke test for the U1 -> U0 import bridge.

Shows that U1 tests can import three kinds of U0 foundation surface (conftest injects u0_foundation/src):
  1. common.schema.INSTITUTIONS: exactly 7 columns, including country_code.
  2. identity.golden.ZENOU_STRUCTURAL: the Zenou golden anchor (has a name field).
  3. identity.exit_codes.GOLDEN_FAIL == 18: the exit code registered by U0, which issues the codes.

This only checks that the bridge works (U1 can reach U0's symbols); it makes no identification choices.
"""


def test_can_import_institutions_schema_from_common():
    from common.schema import INSTITUTIONS

    assert isinstance(INSTITUTIONS, dict)
    assert len(INSTITUTIONS) == 7, f"INSTITUTIONS should have exactly 7 columns, got {len(INSTITUTIONS)}: {sorted(INSTITUTIONS)}"
    assert "country_code" in INSTITUTIONS, "INSTITUTIONS must contain country_code (the key to the Yves Zenou foreign-institution check)"


def test_can_import_zenou_golden_anchor_from_identity():
    from identity.golden import ZENOU_STRUCTURAL

    assert isinstance(ZENOU_STRUCTURAL, dict)
    # The anchor must carry a name field (Yves Zénou), proving it is the real anchor, not an empty shell.
    assert "name" in ZENOU_STRUCTURAL
    assert "Zénou" in ZENOU_STRUCTURAL["name"]


def test_can_import_golden_fail_exit_code_eq_18():
    from identity.exit_codes import GOLDEN_FAIL

    assert GOLDEN_FAIL == 18, f"GOLDEN_FAIL should == 18 (the U0 exit-code ledger), got {GOLDEN_FAIL}"
