"""Table A school-expansion registration TDD - department-name whitelist for 9 schools (expansion pilot: UQ).

Boundary rules (Table A draft: 9-school department-name whitelist):
  - rule #1: Melbourne Institute counts (included in the in-post pool, phrases go into include);
  - rule #2: phrases of Sydney's SEPS period are accepted;
  - rule #3: UQ CEPA / CUBES count;
  - rule #4: UTS CHERE is added;
  - rule #5: Adelaide's merger follows the old school name (main I5681781; the new entity I4405259444 is only watched);
  - rule #6: works missed in the UWA Business School period are recovered = backfill from the real-data scan;
  - general rule derived: economics-type institutes/centres of the same establishment/community as an economics department count towards the in-post pool, phrases are accepted widely, identity is guarded by human checks.
Boundary discipline (no overreach): phrases for faculty-level/higher establishments (FEC/FBE/CBE/Division/Business School etc.) are
  not adopted as a blanket wide inclusion -> this expansion never registers them and leaves them pending.
No regression: build_table_a_rows() (the two-school production path) behaviour/row content is untouched;
  monash/unsw phrase config bytes unchanged (per-phrase requires keys are emitted only for schools with registrations).
"""
import pytest

from common.schema import ECON_DEPT_REGISTRY, assert_matches_schema
from identity.golden import MONASH_CANONICAL_ID

# Candidate institution ids per school in the draft (looked up in the OpenAlex API, checked by hand candidate by candidate)
_EXPECTED_INST = {
    "melbourne_econ": "I165779595",
    "sydney_econ": "I129604602",
    "anu_econ": "I118347636",
    "uq_econ": "I165143802",
    "uwa_econ": "I177877127",
    "adelaide_econ": "I5681781",   # the old entity is the main one (works in the 2000-2025 window all attach to it, rule #5)
    "deakin_econ": "I149704539",
    "uts_econ": "I114017466",
    "macquarie_econ": "I99043593",
}


def _by_key(rows):
    return {r["dept_key"]: r for r in rows}


# ── 9 school rows: schema / institution ids / verified flags ─────────────────────────────────────────
def test_expansion_rows_schema_inst_ids_and_signed():
    from roster.table_a import build_expansion_table_a_rows

    rows = build_expansion_table_a_rows()
    assert len(rows) == 9, "expansion batch = 9 universities (Melbourne/Sydney/ANU/UQ/UWA/Adelaide/Deakin/UTS/MQ)"
    for r in rows:
        assert_matches_schema(r.keys(), ECON_DEPT_REGISTRY, label="econ_dept_registry")
    by = _by_key(rows)
    assert set(by) == set(_EXPECTED_INST)
    for dk, inst in _EXPECTED_INST.items():
        assert by[dk]["openalex_inst_id"] == inst, f"{dk} institution id must follow the draft candidates (manual batch)"
    # whole batch verified by hand -> human_verified=True (precondition for byline probe_registry to pass)
    assert all(r["human_verified"] is True for r in rows)
    assert all(r["is_business_school"] is False for r in rows)
    assert all("Economics and Econometrics" in r["subfield_primary"] for r in rows), "the G5 definition is kept"
    assert all(r["source"] == "manual" for r in rows)


def test_all_rows_is_two_plus_nine_and_frozen_two_unchanged():
    """build_table_a_rows_all() = the two frozen school rows + the 9 expansion rows; the two schools' rows are unchanged byte for byte (no regression)."""
    from roster.table_a import build_expansion_table_a_rows, build_table_a_rows, build_table_a_rows_all

    frozen = build_table_a_rows()
    assert len(frozen) == 2, "the production path of the two original universities must not change because of the expansion"
    all_rows = build_table_a_rows_all()
    assert len(all_rows) == 11
    assert all_rows[:2] == frozen, "first two rows = the frozen two-university rows unchanged (same order and content)"
    assert all_rows[2:] == build_expansion_table_a_rows()
    keys = [r["dept_key"] for r in all_rows]
    assert len(keys) == len(set(keys)), "dept_key is globally unique"


def test_adelaide_dual_id_watch_registered():
    """Rule #5: the 2000-2025 window uses the old entity I5681781; the 2026-merged new entity I4405259444 is only a watch
    (checked in the OpenAlex API: the new entity's associated_institutions has predecessor=I5681781, works=0)."""
    from roster.table_a import ADELAIDE_WATCH_INST_ID, build_expansion_table_a_rows

    assert ADELAIDE_WATCH_INST_ID == "I4405259444"
    by = _by_key(build_expansion_table_a_rows())
    assert by["adelaide_econ"]["openalex_inst_id"] == "I5681781"


# ── institute/centre phrases added by the rules (rules #1-4) ────────────────────────────────────────
def test_ruled_in_centre_phrases_present():
    from roster.table_a import build_expansion_table_a_rows

    by = _by_key(build_expansion_table_a_rows())
    mel = by["melbourne_econ"]["dept_name_variants"]
    # rule #1 - accept both name forms (1962-96/2024- "of...and" form; 1996-2024 colon & form, used in practice on SSRN/LinkedIn)
    assert "Melbourne Institute of Applied Economic and Social Research" in mel
    assert "Melbourne Institute: Applied Economic & Social Research" in mel

    syd = by["sydney_econ"]["dept_name_variants"]
    assert "School of Economics and Political Science" in syd  # rule #2 SEPS accepted

    uq = by["uq_econ"]["dept_name_variants"]
    assert "Centre for Efficiency and Productivity Analysis" in uq   # rule #3 CEPA
    assert "Centre for Unified Behavioural and Economic Sciences" in uq  # rule #3 CUBES (full name verified on the web)

    uts = by["uts_econ"]["dept_name_variants"]
    assert "Centre for Health Economics Research and Evaluation" in uts  # rule #4 CHERE


def test_faculty_level_phrases_not_registered_pending_blanket_sign():
    """Phrases of faculty-level/higher establishments are not adopted as a blanket wide inclusion -> none of them go into include in this batch (they stay pending)."""
    from roster.table_a import build_table_a_rows_all

    all_variants = {p for r in build_table_a_rows_all() for p in r["dept_name_variants"]}
    for pending in (
        "Faculty of Economics and Commerce",        # Melbourne 2000-09 / ANU 2000-06 higher level
        "Faculty of Business and Economics",        # Melbourne 2010- / MQ 2009-19 higher level
        "Faculty of Economics and Business",        # Sydney 2000-10 higher level
        "College of Business and Economics",        # ANU 2006- higher level
        "UWA Business School",                      # UWA higher level (rule #6 = backfill from real data, not wide inclusion of the higher level)
        "Faculty of Arts, Business, Law and Economics",  # Adelaide ABLE higher level
        "Deakin Business School",                   # Deakin higher level
        "UTS Business School",                      # UTS higher level
        "Division of Economic and Financial Studies",  # MQ 2000-08 higher-level Division
        "Macquarie Business School",                # MQ 2019- higher level
    ):
        assert pending not in all_variants, f"parent-body phrases not accepted as broad matches must not be registered: {pending}"


# ── per-school registration: department-level phrases registered (year-span notes are in table_a.py) ────────────────────────────
def test_per_school_dept_phrases_registered():
    from roster.table_a import build_expansion_table_a_rows

    by = {dk: set(r["dept_name_variants"]) for dk, r in _by_key(build_expansion_table_a_rows()).items()}
    assert "Department of Economics" in by["melbourne_econ"]          # the whole of 2000-2025
    assert {"School of Economics", "Discipline of Economics",
            "Discipline of Econometrics and Business Statistics"} <= by["sydney_econ"]
    assert {"Research School of Economics", "School of Economics",
            "Economics Program"} <= by["anu_econ"]
    assert {"School of Economics", "Department of Economics",
            "Economics Department"} <= by["uq_econ"]                  # name change around 2001 pinned
    assert {"Department of Economics", "Economics Department",
            "School of Economics and Commerce"} <= by["uwa_econ"]
    assert {"School of Economics", "School of Economics and Public Policy"} <= by["adelaide_econ"]
    assert {"School of Economics", "School of Accounting, Economics and Finance",
            "Department of Economics", "Economics Discipline Group"} <= by["deakin_econ"]
    assert {"School of Finance and Economics", "Economics Discipline Group",
            "Economics Department", "Department of Economics",
            "School of Economics and Marketing"} <= by["uts_econ"]
    assert by["macquarie_econ"] >= {"Department of Economics"}        # the most stable department name among the 9 schools


# ── byline line: bind/exclude token registration for 9 schools + zero byte regression of the monash/unsw config ─────────
def test_phrase_config_covers_all_11_and_two_school_bytes_frozen(tmp_path):
    import yaml

    from roster.byline import build_phrase_config, write_phrase_config
    from roster.table_a import build_table_a_rows_all

    cfgs = build_phrase_config(build_table_a_rows_all())  # a school without registered tokens raises KeyError
    assert {c["dept_key"] for c in cfgs} == set(_EXPECTED_INST) | {"monash_econ", "unsw_econ"}

    write_phrase_config(cfgs, tmp_path)
    for dk in ("monash_econ", "unsw_econ"):
        new = (tmp_path / f"{dk}.yaml").read_bytes()
        frozen_file = (
            __import__("pathlib").Path(__file__).resolve()
        )
        frozen_dir = next(p for p in frozen_file.parents if p.name == "units").parent / "config" / "econ_dept_phrases"
        assert new == (frozen_dir / f"{dk}.yaml").read_bytes(), (
            f"{dk} phrase config bytes must be identical to the frozen copy (zero regression from the expansion)"
        )

    by = {c["dept_key"]: c for c in cfgs}
    # Binding tokens: all nine schools forbid bare city/state/brand names
    def _texts(dk):
        return {t["text"] for t in by[dk]["bind_tokens"]}

    assert _texts("melbourne_econ") == {"University of Melbourne"}
    assert _texts("sydney_econ") == {"University of Sydney"}
    assert _texts("anu_econ") == {"Australian National University", "ANU"}
    assert _texts("uq_econ") == {"University of Queensland", "UQ"}
    assert _texts("uwa_econ") == {"University of Western Australia", "UWA"}
    assert _texts("adelaide_econ") == {"University of Adelaide", "Adelaide University"}, (
        "in 2001-02 the official name was Adelaide University (confirmed in snapshots) — both full names are needed, else early years are missed"
    )
    assert _texts("deakin_econ") == {"Deakin University"}
    assert _texts("uts_econ") == {"University of Technology Sydney",
                                  "University of Technology, Sydney", "UTS"}, (
        "the old official name has a comma (2014 snapshot title); the comma is dropped around 2015 — accept both forms"
    )
    assert _texts("macquarie_econ") == {"Macquarie University"}

    for dk in ("Sydney", "Melbourne", "Adelaide", "Queensland", "Western Australia",
               "Deakin", "Macquarie"):
        for c in cfgs:
            assert dk not in {t["text"] for t in c["bind_tokens"]}, f"bare city/state/brand names are forbidden: {dk}"

    # abbreviation tokens are always case-sensitive whole words (UNSW <-> New BrUNSWick precedent)
    for dk, abbr in (("anu_econ", "ANU"), ("uq_econ", "UQ"), ("uwa_econ", "UWA"), ("uts_econ", "UTS")):
        tok = next(t for t in by[dk]["bind_tokens"] if t["text"] == abbr)
        assert tok["case_sensitive"] is True and tok["word_boundary"] is True

    # ANU neighbouring units isolated: Arndt-Corden / Crawford School do not belong to anu_econ
    assert set(by["anu_econ"]["exclude_tokens"]) == {"Arndt-Corden", "Crawford School"}


# ── matching behaviour: positive cases hit per school + counter-examples blocked against contamination (real-shape fixtures) ─────────────────────────
def _match(s):
    from roster.byline import build_phrase_config, match_string
    from roster.table_a import build_table_a_rows_all

    cfgs = build_phrase_config(build_table_a_rows_all())
    bound, unbound = match_string(s, cfgs)
    return {b[0] for b in bound}, unbound


@pytest.mark.parametrize("affil,dept", [
    ("Department of Economics, University of Melbourne, Victoria 3010, Australia", "melbourne_econ"),
    ("Melbourne Institute of Applied Economic and Social Research, The University of Melbourne", "melbourne_econ"),
    ("Melbourne Institute: Applied Economic & Social Research, The University of Melbourne", "melbourne_econ"),
    ("School of Economics, University of Sydney, NSW 2006, Australia", "sydney_econ"),
    ("School of Economics and Political Science, University of Sydney", "sydney_econ"),
    ("Research School of Economics, Australian National University, Canberra", "anu_econ"),
    ("School of Economics, ANU, Canberra ACT 0200", "anu_econ"),
    ("Economics Program, Research School of Social Sciences, Australian National University", "anu_econ"),
    ("School of Economics, The University of Queensland, Brisbane, Qld 4072", "uq_econ"),
    ("Department of Economics, University of Queensland, St Lucia", "uq_econ"),
    ("School of Economics, UQ, St Lucia QLD", "uq_econ"),
    ("Centre for Efficiency and Productivity Analysis, School of Economics, University of Queensland", "uq_econ"),
    ("Centre for Unified Behavioural and Economic Sciences, University of Queensland", "uq_econ"),
    ("Department of Economics, University of Western Australia, Crawley WA 6009", "uwa_econ"),
    ("Economics Department, UWA Business School, University of Western Australia", "uwa_econ"),
    ("School of Economics and Commerce, University of Western Australia", "uwa_econ"),
    ("School of Economics, University of Adelaide, SA 5005, Australia", "adelaide_econ"),
    ("School of Economics, Adelaide University, Australia", "adelaide_econ"),
    ("School of Economics and Public Policy, University of Adelaide", "adelaide_econ"),
    ("School of Accounting, Economics and Finance, Deakin University, Geelong", "deakin_econ"),
    ("Department of Economics, Deakin University, Burwood VIC 3125", "deakin_econ"),
    ("School of Finance and Economics, University of Technology, Sydney", "uts_econ"),
    ("Economics Discipline Group, University of Technology Sydney", "uts_econ"),
    ("School of Economics and Marketing, University of Technology Sydney", "uts_econ"),
    ("Centre for Health Economics Research and Evaluation, University of Technology, Sydney", "uts_econ"),
    ("Department of Economics, Macquarie University, NSW 2109, Australia", "macquarie_econ"),
])
def test_positive_byline_binds(affil, dept):
    depts, _ = _match(affil)
    assert dept in depts, f"a real-form affiliation string must match {dept}: {affil!r}"


@pytest.mark.parametrize("affil,not_dept", [
    # type 2, bare city/state-name trap: same-city other-school / state-name address strings are never wrongly bound
    ("Department of Economics, RMIT University, Melbourne, Australia", "melbourne_econ"),
    ("School of Economics, University of Technology Sydney", "sydney_econ"),
    ("School of Economics, Queensland University of Technology, Brisbane", "uq_econ"),
    ("Department of Economics, Curtin University, Perth, Western Australia", "uwa_econ"),
    ("School of Economics, Flinders University, Adelaide, South Australia", "adelaide_econ"),
    ("Economics Department, The Treasury, Deakin ACT 2600, Australia", "deakin_econ"),
    ("Economics Department, Macquarie Group, Sydney NSW", "macquarie_econ"),
    # type 1, abbreviation-substring trap: a lower-case substring never hits a case-sensitive whole-word abbreviation
    ("Research School of Economics, Vanuatu National University", "anu_econ"),
    ("Economics Department, Suwa University of Science, Japan", "uwa_econ"),
    # type 5, neighbouring unit / double condition
    ("Economics Program, Australian National University", "anu_econ"),  # missing RSSS double condition
    ("School of Economics, Crawford School of Public Policy, Australian National University", "anu_econ"),
    # colliding phrases are assigned to the school they belong to (cross-school rule 1)
    ("Economics Discipline Group, Deakin University", "uts_econ"),
])
def test_pollution_fixtures_do_not_bind(affil, not_dept):
    depts, _ = _match(affil)
    assert not_dept not in depts, f"contamination guard: {affil!r} must never bind to {not_dept}"


def test_shared_phrase_collision_resolved_by_tokens():
    """'Economics Discipline Group' at UTS (2011-19) and Deakin (2025/26) is the same name - told apart only by the binding token."""
    uts_depts, _ = _match("Economics Discipline Group, University of Technology Sydney")
    dk_depts, _ = _match("Economics Discipline Group, Deakin University")
    assert "uts_econ" in uts_depts and "deakin_econ" not in uts_depts
    assert "deakin_econ" in dk_depts and "uts_econ" not in dk_depts


def test_economics_program_requires_rsss_cotoken():
    """ANU rule: register "Economics Program" + the binding word "Research School of Social Sciences"
    as a double condition, so a bare Economics Program does not collide with a same-named program at another school. requires absent -> no binding + a separate reason."""
    depts, unbound = _match("Economics Program, Australian National University")
    assert "anu_econ" not in depts
    assert ("Economics Program", "required_token_missing") in unbound

    depts2, _ = _match(
        "Economics Program, Research School of Social Sciences, Australian National University")
    assert "anu_econ" in depts2


def test_monash_unsw_match_behavior_unchanged():
    """After the expansion the hit behaviour on the real shapes of the two schools is unchanged (regression on the full evidence strings)."""
    depts, _ = _match("Department of Economics, Monash University, Clayton VIC")
    assert depts == {"monash_econ"}
    depts2, _ = _match("School of Economics, University of New South Wales, Sydney")
    assert depts2 == {"unsw_econ"}
    depts3, _ = _match("Department of Economics, Monash University Malaysia")
    assert "monash_econ" not in depts3  # overseas-campus exclude as before
