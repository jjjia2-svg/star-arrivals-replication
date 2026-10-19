"""m7a_star.adjudications — fail-loud consumption of the manual-review adjudication file (TDD).

In plain words: two eligibility adjudications from a case-by-case check of 15 people feed into the star-identification path —
  (1) adjunct staff (adjunct_q3) leave the candidate pool (Q3: adjuncts are not in post → they do not count as a star arriving from outside);
  (2) local transfers with prior_au_employment=True → is_foreign_poach forced False
    (rule: "never employed in Australia before"; a local transfer fails it).
The adjudications = u0p5_roster/roster_fix_2026-07-10_star_arrival_annotations.json (same format as the earlier
roster-fix files, with authorized_by + evidence URL). Reading fails loudly: missing file / missing authorization statement → raise, never skip silently.
verify_roster_matches_fixes = a guard: the new roster version must really carry the 6 corrected years
(prevents U4 pointing at an old roster version).
"""
import json

import pytest

from m7a_star.adjudications import (
    ADJUDICATIONS_SUB,
    human_verified_arrival_basis,
    load_star_adjudications,
    verify_roster_matches_fixes,
)


def _ann():
    return {
        "date": "2026-07-10",
        "authorized_by": "2026-07-10 人工裁定「按证据改」(测试夹具)",
        "year_start_fixes": {
            "A_S1": {"dept_key": "monash_econ", "year_start": 2021,
                      "evidence": "human_verified_web:CV", "url": "https://e.org/cv"},
        },
        "identity_dispositions": {
            "A_ADJ": {"dept_key": "monash_econ",
                      "disposition": "adjunct_q3_not_incumbent",
                      "exclude_from_candidates": True,
                      "note": "adjunct_q3: test note"},
            "A_KEEPME": {"dept_key": "monash_econ",
                         "disposition": "note_only", "note": "只注记不剔"},
        },
        "poach_dispositions": {
            "A_S2": {"dept_key": "monash_econ", "prior_au_employment": True,
                       "is_foreign_poach": False,
                       "note": "本地转入, 非国外挖角 (测试夹具)",
                       "url": "https://web.archive.org/web/20230130041156/..."},
        },
    }


def _write(tmp_path, ann):
    p = tmp_path / ADJUDICATIONS_SUB          # Single source of truth: production and tests use the same path constant
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(ann, ensure_ascii=False), encoding="utf-8")
    return p


def test_loader_returns_three_consumption_maps(tmp_path):
    """The loader folds the file into three consumption maps: exclude_candidates (only exclude_from_candidates=True) /
    poach_overrides {aid: bool} / year_fixes {aid: {dept_key, year_start}}."""
    _write(tmp_path, _ann())
    adj = load_star_adjudications(tmp_path)
    assert adj["exclude_candidates"] == {
        "A_ADJ": "adjunct_q3: test note"}
    assert "A_KEEPME" not in adj["exclude_candidates"]      # Non-exclusion adjudications do not enter the exclusion map
    assert adj["poach_overrides"] == {"A_S2": False}
    assert adj["year_fixes"] == {"A_S1": {"dept_key": "monash_econ", "year_start": 2021}}
    assert adj["authorized_by"].startswith("2026-07-10 人工裁定")
    assert adj["sha256"]


def test_loader_missing_file_fails_loud(tmp_path):
    """Adjudication file missing → ValueError naming the path (the production star path never silently skips manual adjudications)."""
    with pytest.raises(ValueError, match="roster_fix_2026-07-10"):
        load_star_adjudications(tmp_path)


def test_loader_missing_authorization_fails_loud(tmp_path):
    """Missing authorized_by → ValueError (an adjudication without an authorization statement is not consumed)."""
    ann = _ann()
    del ann["authorized_by"]
    _write(tmp_path, ann)
    with pytest.raises(ValueError, match="authorized_by"):
        load_star_adjudications(tmp_path)


def test_loader_poach_override_true_not_allowed(tmp_path):
    """poach_dispositions may only force the flag to False (removing the person from the treated group); a True → raise
    (a manual adjudication never creates positive 'poaching' evidence — that must go through the full determination path)."""
    ann = _ann()
    ann["poach_dispositions"]["A_S2"]["is_foreign_poach"] = True
    _write(tmp_path, ann)
    with pytest.raises(ValueError, match="A_S2"):
        load_star_adjudications(tmp_path)


def test_verify_roster_matches_fixes_passes_on_fixed_roster():
    """Guard: roster row carries the corrected year (hv=True) → pass."""
    rows = [{"author_id": "A_S1", "dept_key": "monash_econ",
             "year_start": 2021, "human_verified": True}]
    verify_roster_matches_fixes(rows, {"A_S1": {"dept_key": "monash_econ",
                                                 "year_start": 2021}})


def test_verify_roster_matches_fixes_catches_stale_roster():
    """Guard: roster still has the old year (2016) → ValueError (U4 points at an old roster version; stop at once)."""
    rows = [{"author_id": "A_S1", "dept_key": "monash_econ",
             "year_start": 2016, "human_verified": False}]
    with pytest.raises(ValueError, match="A_S1"):
        verify_roster_matches_fixes(rows, {"A_S1": {"dept_key": "monash_econ",
                                                     "year_start": 2021}})


# ====== v2 sections: signal_discards + arrival_verifications ======

def _discard(**kw):
    e = {"dept_key": "unsw_econ", "institution_id": "I31746571",
         "year_from": 2000, "year_to": 2002,
         "reason": "错挂署名 (测试夹具)",
         "evidence": "human_verified_web:官方staff页/Wayback (证据表 §一)",
         "url": "https://example.org/staff-page"}
    e.update(kw)
    return e


def test_loader_parses_signal_discards_and_arrival_verifications(tmp_path):
    """The two v2 sections: signal_discards is a per-person list of entries (institution + year window + evidence + URL), folded out unchanged;
    arrival_verifications (manually confirmed years) folds to {aid: {year, source_kind, ...}}."""
    ann = _ann()
    ann["signal_discards"] = {"A_S4": [_discard()]}
    ann["arrival_verifications"] = {
        "A_S3": {"dept_key": "monash_econ", "year": 2018,
                    "source_kind": "orcid_employment",
                    "evidence": "CV 'Lecturer 2018-present' + ORCID 2018-09 (§一 ✅)",
                    "url": None}}
    _write(tmp_path, ann)
    adj = load_star_adjudications(tmp_path)
    assert adj["signal_discards"]["A_S4"][0]["institution_id"] == "I31746571"
    assert adj["signal_discards"]["A_S4"][0]["year_from"] == 2000
    assert adj["arrival_verifications"]["A_S3"]["year"] == 2018
    assert adj["arrival_verifications"]["A_S3"]["source_kind"] == "orcid_employment"


def test_loader_absent_v2_sections_default_empty(tmp_path):
    """Old-format file (no v2 sections) → both maps are empty dicts (no regression, no raise)."""
    _write(tmp_path, _ann())
    adj = load_star_adjudications(tmp_path)
    assert adj["signal_discards"] == {} and adj["arrival_verifications"] == {}


def test_loader_signal_discard_entry_missing_evidence_or_url_fails(tmp_path):
    """A discard entry is an auditable adjudication: missing evidence / missing url key / inverted year window / missing institution id → all raise."""
    for bad in (_discard(evidence=""), {k: v for k, v in _discard().items() if k != "url"},
                _discard(year_from=2003, year_to=2000), _discard(institution_id="")):
        ann = _ann()
        ann["signal_discards"] = {"A_S4": [bad]}
        _write(tmp_path, ann)
        with pytest.raises(ValueError, match="signal_discards"):
            load_star_adjudications(tmp_path)


def test_poach_true_ban_survives_v2(tmp_path):
    """The ban stays after the v2 sections were added: poach_dispositions forcing True still raises — the only legitimate way to restore True
    = an indirect discard through signal_discards with evidence + URL (the organic verdict returns), not a hard override."""
    ann = _ann()
    ann["signal_discards"] = {"A_S4": [_discard()]}          # legitimate path present
    ann["poach_dispositions"]["A_S2"]["is_foreign_poach"] = True   # hard override still illegal
    _write(tmp_path, ann)
    with pytest.raises(ValueError, match="A_S2"):
        load_star_adjudications(tmp_path)


# ====== work_pollution_discards (exact exclusion of same-name pollution by work_id) ======
# A5071656006's 1985 meteorology paper (W2019882445) is exactly 10 years before the true first health-economics publication in 1995, so robust_first_pub
# (max_gap=10) cannot remove it → exclude it exactly by work_id. Same convention as signal_discards (auditable: work_id + evidence + URL keys).


def _wpd(**kw):
    e = {"work_id": "W2019882445",
         "reason": "同名污染 — 1985 数值天气预报论文 (气象), 非本人 (卫生经济学家)",
         "evidence": "verified externally:OpenAlex earliest works + 证据表 §四 (sf=2306 气象)",
         "url": "https://openalex.org/W2019882445"}
    e.update(kw)
    return e


def test_loader_parses_work_pollution_discards(tmp_path):
    """The work_pollution_discards section → {aid: [{work_id, reason, evidence, url}]}, folded out unchanged."""
    ann = _ann()
    ann["work_pollution_discards"] = {"A_S5": [_wpd()]}
    _write(tmp_path, ann)
    adj = load_star_adjudications(tmp_path)
    assert adj["work_pollution_discards"]["A_S5"][0]["work_id"] == "W2019882445"
    assert adj["work_pollution_discards"]["A_S5"][0]["url"].endswith("W2019882445")


def test_loader_work_pollution_absent_defaults_empty(tmp_path):
    """Old-format file (no such section) → empty dict (no regression, no raise)."""
    _write(tmp_path, _ann())
    adj = load_star_adjudications(tmp_path)
    assert adj["work_pollution_discards"] == {}


def test_loader_work_pollution_entry_bad_shape_fails(tmp_path):
    """Auditable adjudication: missing work_id / missing evidence / missing url key / empty list → all raise loudly."""
    bads = [_wpd(work_id=""), _wpd(evidence=""),
            {k: v for k, v in _wpd().items() if k != "url"}]
    for bad in bads:
        ann = _ann()
        ann["work_pollution_discards"] = {"A_S5": [bad]}
        _write(tmp_path, ann)
        with pytest.raises(ValueError, match="work_pollution_discards"):
            load_star_adjudications(tmp_path)
    # An empty entry list also raises (an empty discard adjudication is meaningless)
    ann = _ann()
    ann["work_pollution_discards"] = {"A_S5": []}
    _write(tmp_path, ann)
    with pytest.raises(ValueError, match="work_pollution_discards"):
        load_star_adjudications(tmp_path)


def test_human_verified_arrival_basis_from_roster_and_verifications():
    """hv criteria: (1) roster human_verified row and year_start == frozen arrival year → roster tier
    (evidence starts with human_verified_web → tag web); (2) adjudication arrival_verifications
    year matches → adjudication tier; (3) year mismatch / no manual check → no basis (keep the HALT discipline)."""
    roster = [
        {"author_id": "A_WEB", "dept_key": "unsw_econ", "year_start": 2019,
         "human_verified": True, "evidence": "human_verified_web:CV/Wayback ..."},
        {"author_id": "A_S6", "dept_key": "monash_econ", "year_start": 2017,
         "human_verified": True, "evidence": "manual"},
        {"author_id": "A_UNV", "dept_key": "monash_econ", "year_start": 2018,
         "human_verified": False, "evidence": "official_roster"},
        {"author_id": "A_YMIS", "dept_key": "monash_econ", "year_start": 2010,
         "human_verified": True, "evidence": "manual"},
    ]
    verifs = {"A_UNV": {"dept_key": "monash_econ", "year": 2018,
                        "source_kind": "orcid_employment", "evidence": "x", "url": None},
              "A_YMIS2": {"dept_key": "monash_econ", "year": 2011,
                          "source_kind": "cv", "evidence": "x", "url": None}}
    stars = [
        {"author_id": "A_WEB", "arrival": 2019},
        {"author_id": "A_S6", "arrival": 2017},
        {"author_id": "A_UNV", "arrival": 2018},
        {"author_id": "A_YMIS", "arrival": 2012},     # roster manual-check year 2010 ≠ arrival 2012 → no basis
        {"author_id": "A_YMIS2", "arrival": 2012},    # adjudication year 2011 ≠ arrival 2012 → no basis
        {"author_id": "A_NONE", "arrival": 2015},
    ]
    basis = human_verified_arrival_basis(roster, verifs, stars)
    assert basis["A_WEB"] == "roster:human_verified_web"
    assert basis["A_S6"] == "roster:human_verified"
    assert basis["A_UNV"] == "adjudication:arrival_verification(orcid_employment)"
    assert "A_YMIS" not in basis and "A_YMIS2" not in basis and "A_NONE" not in basis
