"""Scaffold TDD for the discipline adjudication of the two anchor schools (GAP-4).

In plain words: registry_v3_adjudications_2026-07-12.json covers only the 9 extension schools (8 keys + UQ on a separate line);
Monash/UNSW are **not** in it. The discipline adjudication systematically missed both anchor schools (root cause D, GAP-4: the anchor schools were frozen earlier).
This module makes "extend the discipline adjudication to the two anchor schools" **mechanically ready**: the adjudication file structure is built (empty removals +
PENDING_AUTHOR_SIGNATURE), the load path accepts them, merges and de-duplicates, and the coverage check fails loudly.

Hard rule: names and removals are signed off by a person, so the scaffold is always empty; an empty adjudication through apply_adjudication = everything passes through (zero behaviour change).
"""
import json

import pytest

from roster.adjudications_io import (
    ADJ_REQUIRED_DEPT_KEYS,
    ANCHOR_SCHOOLS,
    UQ_SEPARATE_LINE,
    assert_adjudication_coverage,
    build_anchor_adjudication_scaffold,
    load_adjudications,
)
from roster.registry_v3 import EXPANSION_SCHOOLS, apply_adjudication


# ═══ Scaffold structure ══════════════════════════════════════════════════════════════
def test_anchor_scaffold_has_monash_unsw_empty_and_pending():
    sc = build_anchor_adjudication_scaffold()
    assert set(sc.keys()) == {"monash", "unsw"}
    assert sc["monash"]["dept_key"] == "monash_econ"
    assert sc["unsw"]["dept_key"] == "unsw_econ"
    for entry in sc.values():
        assert entry["removals"] == []          # Names stay empty - filled in only once a human has approved them
        assert entry["verified"] == []
        assert entry["status"] == "PENDING_AUTHOR_SIGNATURE"
        assert "unsigned" in entry["note"]
        assert "GAP-4" in entry["note"]


def test_anchor_constants_consistent():
    assert ANCHOR_SCHOOLS == {"monash": "monash_econ", "unsw": "unsw_econ"}
    assert UQ_SEPARATE_LINE == {"uq_econ"}
    # Required coverage = 8 extension schools + 2 anchor schools = 10 dept_keys (UQ goes through the separate uq_finalize line, exempt with a note)
    assert len(ADJ_REQUIRED_DEPT_KEYS) == 10
    assert set(ANCHOR_SCHOOLS.values()) <= ADJ_REQUIRED_DEPT_KEYS
    assert {m["adj"] for m in EXPANSION_SCHOOLS.values()} == \
        {k for k in ("melbourne", "sydney", "anu", "uwa", "adelaide",
                     "deakin", "uts", "macquarie")}
    assert "uq_econ" not in ADJ_REQUIRED_DEPT_KEYS


def test_empty_scaffold_passes_rows_through_untouched():
    """Empty adjudication = zero behaviour: apply_adjudication passes everything through (mechanically ready, the roster is untouched)."""
    rows = [{"dept_key": "monash_econ", "author_id": "A1", "display_name": "Alice",
             "year_start": 2005, "year_end": 2010, "evidence": "official_roster",
             "confidence": "high", "human_verified": False}]
    sc = build_anchor_adjudication_scaffold()
    res = apply_adjudication(rows, sc["monash"])
    assert res["rows"] == rows
    assert res["report"]["n_removed_rows"] == 0
    assert res["report"]["n_verified_people"] == 0


# ═══ load_adjudications - multi-file merge + validation ══════════════════════════════════
def _write(p, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


def test_load_merges_files_and_keeps_all_keys(tmp_path):
    f1 = _write(tmp_path / "expansion.json",
                {"uwa": {"dept_key": "uwa_econ", "removals": [], "verified": []}})
    f2 = _write(tmp_path / "anchor.json", build_anchor_adjudication_scaffold())
    adj = load_adjudications(f1, f2)
    assert set(adj.keys()) == {"uwa", "monash", "unsw"}


def test_load_duplicate_key_fails_loud(tmp_path):
    f1 = _write(tmp_path / "a.json",
                {"monash": {"dept_key": "monash_econ", "removals": [], "verified": []}})
    f2 = _write(tmp_path / "b.json", build_anchor_adjudication_scaffold())
    with pytest.raises(ValueError, match="monash"):
        load_adjudications(f1, f2)


def test_load_malformed_entry_fails_loud(tmp_path):
    f = _write(tmp_path / "bad.json", {"uwa": {"dept_key": "uwa_econ"}})  # missing removals/verified
    with pytest.raises(ValueError, match="removals"):
        load_adjudications(f)


def test_load_removal_entries_must_have_name(tmp_path):
    f = _write(tmp_path / "bad2.json",
               {"uwa": {"dept_key": "uwa_econ",
                        "removals": [{"why": "缺 name"}], "verified": []}})
    with pytest.raises(ValueError, match="name"):
        load_adjudications(f)


# ═══ assert_adjudication_coverage - GAP-4 is no longer silent ═══════════════════════════
def test_coverage_passes_when_all_ten_present(tmp_path):
    entries = {k: {"dept_key": f"{k}_econ", "removals": [], "verified": []}
               for k in ("melbourne", "sydney", "anu", "uwa", "adelaide",
                         "deakin", "uts", "macquarie")}
    entries.update(build_anchor_adjudication_scaffold())
    report = assert_adjudication_coverage(entries)
    assert report["covered"] == sorted(ADJ_REQUIRED_DEPT_KEYS)
    assert report["pending_signature"] == ["monash_econ", "unsw_econ"]


def test_coverage_missing_anchor_fails_loud_naming_gap4():
    entries = {k: {"dept_key": f"{k}_econ", "removals": [], "verified": []}
               for k in ("melbourne", "sydney", "anu", "uwa", "adelaide",
                         "deakin", "uts", "macquarie")}
    with pytest.raises(ValueError) as ei:
        assert_adjudication_coverage(entries)
    msg = str(ei.value)
    assert "GAP-4" in msg and "monash_econ" in msg and "unsw_econ" in msg


# ═══ E4 - loading contract for the SIGNED adjudication of the two anchor schools ═══════════════════
# In plain words: E4 writes the T1 (remove) / T2 (change years) / T3 (wrong-id pass-through merge) / Chrome per-person adjudications into the adjudication JSON (status=AUTHOR_SIGNED);
# these tests lock the load shape of the signed adjudication: once the always-empty scaffold is signed (status=AUTHOR_SIGNED,
# removals/verified hold real names) it still passes load_adjudications + the 10-school coverage gate, and pending becomes empty.
# (hermetic: the structure is built in place, no dependence on real files on the SSD.)
def _signed_anchor(dept_key: str, *, removals=(), verified=(), extra=None) -> dict:
    entry = {
        "dept_key": dept_key,
        "status": "AUTHOR_SIGNED_2026-07-16",
        "signed": "author_signed_2026-07-16",
        "authorized_by": "2026-07-16 人工批准: 全按推荐 + Chrome 复核",
        "note": "GAP-4 回补 SIGNED — 逐人裁决落地",
        "removals": [dict(r) for r in removals],
        "verified": [dict(v) for v in verified],
    }
    if extra:
        entry.update(extra)
    return entry


def _signed_two_anchor():
    monash = _signed_anchor(
        "monash_econ",
        removals=[{"name": "Person A", "author_id": "A_T01",
                   "why": "药学出身", "evidence_url": "https://x", "confidence": "high",
                   "signed": "author_signed_2026-07-16"}],
        verified=[{"name": "Person B", "author_id": "A_T02",
                   "reason": "真在编卫生经济学家", "review_date": "2026-07-16",
                   "signed": "author_signed_2026-07-16"}],
        extra={"remap": [{"name": "Person C", "old_author_id": "A_T03",
                          "correct_author_id": "A_T04", "why": "碎片号",
                          "evidence_url": "https://x", "collision_note": None,
                          "signed": "author_signed_2026-07-16"}],
               "identity_dispositions": [{"name": "Person D", "author_id": "A_T05",
                                          "disposition": "adjunct_q3_not_incumbent",
                                          "exclude_from_candidates": True, "why": "兼职名义",
                                          "precedent": "A_T06", "signed": "author_signed_2026-07-16"}],
               "split_pending": [{"name": "Person E", "author_id": "A_T07",
                                  "why": "过并号", "queue": "U2", "keep_work": "W4391314444",
                                  "status": "split_pending", "signed": "author_signed_2026-07-16"}],
               "conflicts": [{"name": "Person F", "author_id": "A_T08",
                              "t1": "留", "t3": "剔", "status": "HELD_no_action",
                              "note": "两表相悖归人工裁"}]})
    unsw = _signed_anchor(
        "unsw_econ",
        removals=[{"name": "Person G", "author_id": "A_T09",
                   "why": "纯数理金融, 照 A2 先例", "evidence_url": "https://x",
                   "confidence": "high", "signed": "author_signed_2026-07-16"}],
        verified=[])
    return {"monash": monash, "unsw": unsw}


def _write(p, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


def test_signed_anchor_loads_with_removals_and_extra_blocks(tmp_path):
    """A signed adjudication (removals with real names + remap/identity/split/conflicts extension blocks) loads."""
    f = _write(tmp_path / "signed.json", _signed_two_anchor())
    adj = load_adjudications(f)
    assert set(adj.keys()) == {"monash", "unsw"}
    mon = adj["monash"]
    assert mon["status"] == "AUTHOR_SIGNED_2026-07-16"
    assert mon["removals"][0]["name"] == "Person A"
    assert mon["removals"][0]["author_id"] == "A_T01"
    assert mon["removals"][0]["signed"] == "author_signed_2026-07-16"
    # extension blocks are carried through with their entries unchanged (the loader does not drop them)
    assert mon["remap"][0]["correct_author_id"] == "A_T04"
    assert mon["identity_dispositions"][0]["exclude_from_candidates"] is True
    assert mon["split_pending"][0]["keep_work"] == "W4391314444"
    assert mon["conflicts"][0]["status"] == "HELD_no_action"


def test_signed_anchor_merges_with_expansion_and_covers_ten(tmp_path):
    """9 extension schools + 2 anchor schools (SIGNED) -> the 10-school coverage gate passes, pending_signature becomes empty."""
    exp = {k: {"dept_key": f"{k}_econ", "removals": [], "verified": []}
           for k in ("melbourne", "sydney", "anu", "uwa", "adelaide",
                     "deakin", "uts", "macquarie")}
    fexp = _write(tmp_path / "expansion.json", exp)
    fsig = _write(tmp_path / "signed.json", _signed_two_anchor())
    adj = load_adjudications(fexp, fsig)
    report = assert_adjudication_coverage(adj)
    assert report["covered"] == sorted(ADJ_REQUIRED_DEPT_KEYS)
    assert report["pending_signature"] == []          # signed -> no longer PENDING


def test_signed_removal_missing_name_still_fails_loud(tmp_path):
    """After signing, removals must still have a name (the contract is not relaxed by signing)."""
    bad = _signed_two_anchor()
    bad["monash"]["removals"].append({"author_id": "A5", "why": "缺 name"})
    f = _write(tmp_path / "bad.json", bad)
    with pytest.raises(ValueError, match="name"):
        load_adjudications(f)
