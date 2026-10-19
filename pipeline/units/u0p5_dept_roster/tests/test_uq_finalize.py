"""UQ Table B finalisation v1 - uq_finalize TDD.

In plain words: the 377-row draft becomes the final Table B - 6 not admitted + 2 removed + 2 removed/not admitted after a browser check have their rows deleted from the roster;
checked people get hv=True + an evidence URL; 1 person is accepted but tagged with an academic-support post type; 1 person is accepted with low confidence;
1 person is accepted with two spells (2015-17 + 2025-26, gap years left empty). All other rows are kept unchanged with hv=False
(automatic years do not get the human-checked stamp). Writing follows the finalisation precedent: a new version directory, never overwriting an existing one.
Hard rules: row deletions/notes must hit by name (0 hits -> fail loudly, a misspelt name is never silent); schema guard.
"""
import pytest

from roster.uq_finalize import apply_uq_adjudication


def _row(name, *, aid=None, ys=None, ye=None, evidence="wayback_snapshot",
         conf="low", hv=False):
    return {"dept_key": "uq_econ", "author_id": aid, "display_name": name,
            "year_start": ys, "year_end": ye, "evidence": evidence,
            "confidence": conf, "human_verified": hv}


def _draft():
    return [
        _row("Clean Keeper", ys=2002, ye=2010),                              # remaining row, untouched
        _row("Person J", aid="A_PJ", ys=2009, ye=2010,
             evidence="raw_affil_year"),                                     # removed (by id)
        _row("Person K", ys=2013, ye=2013),                           # not admitted (by name)
        _row("Person V", ys=2023, ye=2023),                           # ✅ checked
        _row("Person W.X. Support", ys=2002, ye=2005),                        # accepted (held-over case) + support post
        _row("Person L", ys=2002, ye=2004),                            # accepted (held-over case) + low confidence
        _row("Person M", ys=2015, ye=2025),                         # wayback row of the two-spell person
        _row("Person M", evidence="official_roster"),               # current row of the two-spell person (no year)
    ]


def _adj():
    return {
        "removals": [
            {"name": "Person J", "author_id": "A_PJ", "why": "剔: ITEE"},
            {"name": "Person K", "author_id": None, "why": "不入: GCI"},
        ],
        "special": {
            "Person W.X. Support": {"action": "keep_support", "confidence": "high",
                                   "note": "学术支持岗", "url": "https://e.org/f"},
            "Person L": {"action": "keep_low_confidence", "confidence": "low",
                               "note": "一手名册证据优先", "url": "https://e.org/j"},
            "Person M": {"action": "keep_two_segments", "confidence": "high",
                                  "segments": [[2015, 2017], [2025, 2026]],
                                  "note": "两段, 断档年留空", "url": "https://e.org/p"},
        },
        "verified": [
            {"name": "Person V", "role": "staff", "verified_span": "2022–2023",
             "url": "https://e.org/a", "evidence_note": "本人网站"},
        ],
    }


def test_removals_drop_all_rows_of_named_people():
    res = apply_uq_adjudication(_draft(), _adj())
    names = [r["display_name"] for r in res["rows"]]
    assert "Person J" not in names and "Person K" not in names
    assert res["report"]["n_removed_rows"] == 2
    assert res["report"]["n_removed_people"] == 2


def test_removal_zero_hit_fails_loud():
    adj = _adj()
    adj["removals"].append({"name": "Nobody Here", "author_id": None, "why": "x"})
    with pytest.raises(ValueError, match="Nobody Here"):
        apply_uq_adjudication(_draft(), adj)


def test_verified_rows_get_hv_true_high_conf_and_url():
    res = apply_uq_adjudication(_draft(), _adj())
    by = {r["display_name"]: r for r in res["rows"] if r["display_name"] == "Person V"}
    r = by["Person V"]
    assert r["human_verified"] is True and r["confidence"] == "high"
    assert "hv_web:staff" in r["evidence"] and "https://e.org/a" in r["evidence"]
    assert "核实年段:2022–2023" in r["evidence"]
    # year columns untouched (the verified year span goes into the evidence note; the columns are changed uniformly in the final per-person check)
    assert r["year_start"] == 2023 and r["year_end"] == 2023


def test_verified_zero_hit_fails_loud():
    adj = _adj()
    adj["verified"].append({"name": "Ghost Person", "role": "staff",
                            "verified_span": None, "url": "https://e.org/g",
                            "evidence_note": ""})
    with pytest.raises(ValueError, match="Ghost Person"):
        apply_uq_adjudication(_draft(), adj)


def test_support_class_row_keeps_its_label():
    res = apply_uq_adjudication(_draft(), _adj())
    r = next(x for x in res["rows"] if x["display_name"] == "Person W.X. Support")
    assert r["human_verified"] is True and r["confidence"] == "high"
    assert "job_class=academic_support" in r["evidence"]


def test_verified_row_keeps_low_confidence():
    res = apply_uq_adjudication(_draft(), _adj())
    r = next(x for x in res["rows"] if x["display_name"] == "Person L")
    assert r["human_verified"] is True and r["confidence"] == "low"


def test_two_segment_person_replaces_rows():
    """Two rows (wayback with a year + official without) -> two spells: the early spell lands on the wayback row, the late spell on the official row."""
    res = apply_uq_adjudication(_draft(), _adj())
    rows = [r for r in res["rows"] if r["display_name"] == "Person M"]
    assert len(rows) == 2
    spans = sorted((r["year_start"], r["year_end"]) for r in rows)
    assert spans == [(2015, 2017), (2025, 2026)]
    assert all(r["human_verified"] is True for r in rows)


def test_untouched_rows_pass_through_verbatim():
    res = apply_uq_adjudication(_draft(), _adj())
    keeper = next(r for r in res["rows"] if r["display_name"] == "Clean Keeper")
    assert keeper == _draft()[0]
