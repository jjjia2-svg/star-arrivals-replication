"""11-school registry v3 assembly (four classes of boundary adjudication) - registry_v3 TDD.

In plain words: the draft rosters of the 8 new schools become the final registry under the boundary adjudications - removed people have their rows deleted (fail loudly),
accepted boundary cases get hv=True + an evidence note (year columns untouched, red line #3); the 3 frozen registries (Monash STARFIX/UNSW/UQ)
are carried byte for byte (sha-guarded); Table A rebuilt from code asserts sha == frozen; the Yves Zenou golden test is guarded.
Hard rules: removals/acceptances hit by name (0 hits -> fail loudly); touching a frozen file with the wrong sha -> raise; Yves Zenou drift -> raise; schema guard.
"""
import hashlib
import pathlib

import pytest

from roster.registry_v3 import (
    EXPANSION_SCHOOLS, FROZEN_PANELS, TABLE_A_SHA, ZENOU_AUTHOR_ID, ZENOU_NAME,
    apply_adjudication, assert_zenou_in_panel, carry_frozen,
)
from roster.table_a import build_table_a_rows_all
from roster.table_b import write_table_b


def _row(name, *, aid=None, ys=2005, ye=2010, evidence="wayback_snapshot",
         conf="medium", hv=False, dept="uwa_econ"):
    return {"dept_key": dept, "author_id": aid, "display_name": name,
            "year_start": ys, "year_end": ye, "evidence": evidence,
            "confidence": conf, "human_verified": hv}


def _draft():
    return [
        _row("Clean Keeper", ys=2002, ye=2010),
        _row("Remove Me", ys=2009, ye=2010),
        _row("Also Remove", ys=2013, ye=2013, evidence="official_roster"),
        _row("Verify Me", ys=2003, ye=2005),
    ]


def _adj():
    return {
        "removals": [
            {"name": "Remove Me", "why": "非经济学科"},
            {"name": "Also Remove", "why": "行政岗"},
        ],
        "verified": [
            {"name": "Verify Me", "reason": "边界收: 真经济学家"},
        ],
    }


# ─── apply_adjudication: removals ────────────────────────────────────────────────
def test_removals_drop_all_named_rows():
    res = apply_adjudication(_draft(), _adj())
    names = [r["display_name"] for r in res["rows"]]
    assert "Remove Me" not in names and "Also Remove" not in names
    assert res["report"]["n_removed_rows"] == 2
    assert res["report"]["n_removed_people"] == 2
    assert res["report"]["n_final_rows"] == 2


def test_removal_zero_hit_fails_loud():
    adj = _adj()
    adj["removals"].append({"name": "Ghost", "why": "x"})
    with pytest.raises(ValueError, match="Ghost"):
        apply_adjudication(_draft(), adj)


# ─── apply_adjudication: accepted boundary cases get hv ─────────────────────────────────────────
def test_verified_gets_hv_true_high_conf_and_annotation():
    res = apply_adjudication(_draft(), _adj(), batch_date="2026-07-12")
    r = next(x for x in res["rows"] if x["display_name"] == "Verify Me")
    assert r["human_verified"] is True and r["confidence"] == "high"
    assert "hv:2026-07-12边界裁决_收" in r["evidence"]
    assert "真经济学家" in r["evidence"]
    assert "src:" in r["evidence"] and "discipline_boundary_ruling" in r["evidence"]


def test_verified_year_columns_unchanged():
    """The check goes into the evidence note, the year columns are never touched (red line #3)."""
    res = apply_adjudication(_draft(), _adj())
    r = next(x for x in res["rows"] if x["display_name"] == "Verify Me")
    assert r["year_start"] == 2003 and r["year_end"] == 2005


def test_verified_zero_hit_fails_loud():
    adj = _adj()
    adj["verified"].append({"name": "Nobody", "reason": "x"})
    with pytest.raises(ValueError, match="Nobody"):
        apply_adjudication(_draft(), adj)


def test_remove_and_verify_same_row_clashes():
    adj = {"removals": [{"name": "Verify Me", "why": "x"}],
           "verified": [{"name": "Verify Me", "reason": "y"}]}
    with pytest.raises(RuntimeError, match="both removed and verified"):
        apply_adjudication(_draft(), adj)


def test_untouched_row_passes_through_verbatim():
    res = apply_adjudication(_draft(), _adj())
    keeper = next(r for r in res["rows"] if r["display_name"] == "Clean Keeper")
    assert keeper == _draft()[0]


def test_report_counts_and_unique_people():
    res = apply_adjudication(_draft(), _adj())
    rep = res["report"]
    assert rep["n_verified_people"] == 1
    assert rep["n_hv_true_rows"] == 1
    assert rep["n_unique_people"] == 2   # Clean Keeper + Verify Me


def test_empty_adjudication_passes_all_through():
    res = apply_adjudication(_draft(), {"removals": [], "verified": []})
    assert res["report"]["n_final_rows"] == 4
    assert res["report"]["n_removed_rows"] == 0


# ─── carry_frozen: byte level + sha guard ───────────────────────────────────────────
def test_carry_frozen_copies_and_verifies_sha(tmp_path):
    src = tmp_path / "src.parquet"
    write_table_b([_row("A", dept="monash_econ")], src)
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    dst = tmp_path / "sub" / "dst.parquet"
    got = carry_frozen(src, dst, sha)
    assert got == sha
    assert dst.read_bytes() == src.read_bytes()


def test_carry_frozen_wrong_source_sha_fails_loud(tmp_path):
    src = tmp_path / "src.parquet"
    write_table_b([_row("A", dept="monash_econ")], src)
    dst = tmp_path / "dst.parquet"
    with pytest.raises(RuntimeError, match="wrong frozen file"):
        carry_frozen(src, dst, "deadbeef" * 8)
    assert not dst.exists()


# ─── Yves Zenou golden test guard ──────────────────────────────────────────────────────────
def _write_monash_with_zenou(path):
    rows = [
        {"dept_key": "monash_econ", "author_id": ZENOU_AUTHOR_ID, "display_name": ZENOU_NAME,
         "year_start": 1995, "year_end": 2025, "evidence": "official_roster",
         "confidence": "high", "human_verified": True},
        {"dept_key": "monash_econ", "author_id": None, "display_name": "Someone Else",
         "year_start": 2010, "year_end": 2020, "evidence": "official_roster",
         "confidence": "low", "human_verified": False},
    ]
    write_table_b(rows, path)


def test_assert_zenou_passes_when_present(tmp_path):
    p = tmp_path / "monash.parquet"
    _write_monash_with_zenou(p)
    out = assert_zenou_in_panel(p)
    assert out["author_id"] == ZENOU_AUTHOR_ID and out["dept_key"] == "monash_econ"


def test_assert_zenou_fails_when_missing(tmp_path):
    p = tmp_path / "no_zenou.parquet"
    write_table_b([_row("Someone", dept="monash_econ")], p)
    with pytest.raises(RuntimeError, match="Zenou"):
        assert_zenou_in_panel(p)


def test_assert_zenou_fails_on_id_drift(tmp_path):
    p = tmp_path / "drift.parquet"
    write_table_b([{"dept_key": "monash_econ", "author_id": "A_WRONG",
                    "display_name": ZENOU_NAME, "year_start": 1995, "year_end": 2025,
                    "evidence": "official_roster", "confidence": "high",
                    "human_verified": True}], p)
    with pytest.raises(RuntimeError, match="gold standard broken"):
        assert_zenou_in_panel(p)


# ─── structural invariants ──────────────────────────────────────────────────────────────
def test_expansion_covers_8_schools():
    assert len(EXPANSION_SCHOOLS) == 8
    assert "uq_econ" not in EXPANSION_SCHOOLS   # UQ is a frozen registry and does not go through finalize
    for meta in EXPANSION_SCHOOLS.values():
        assert meta["draft"].endswith(".parquet") and meta["panel"].startswith("dept_roster_panel_")


def test_frozen_panels_are_3_including_starfix_monash():
    assert set(FROZEN_PANELS) == {"monash_econ", "unsw_econ", "uq_econ"}
    # Monash must point to STARFIX (the v3 star-arrival-corrected version), not the pre-starfix centres
    assert FROZEN_PANELS["monash_econ"]["dir"].endswith("centres_starfix")


def test_table_a_all_has_11_rows_and_frozen_sha_constant():
    rows = build_table_a_rows_all()
    assert len(rows) == 11
    keys = {r["dept_key"] for r in rows}
    # the dept_keys of the 3 frozen schools + the 8 new schools are all in Table A
    assert set(FROZEN_PANELS) <= keys
    assert set(EXPANSION_SCHOOLS) <= keys
    assert len(TABLE_A_SHA) == 64
