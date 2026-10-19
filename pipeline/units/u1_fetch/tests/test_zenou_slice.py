"""U1 T8 Zenou golden-standard hard-gate slice - a fixture builds simplified Zenou works -> M1 filter -> classify_golden.

Build list §F + group 9: must catch (this test uses fixture works; real shards are left to the operations script):
  ① A5017376589 is findable (works in the output + edges in authorship_edges).
  ② Recognised as a star (top 1%).
  ③ Placed at Monash I56590836, not Sydney (attribution after institution folding).
  ④ ARMI I2801239119 (facility, lineage contains Monash) -> fold_to_canonical -> Monash I56590836.
  ⑤ Caulfield Hospital I4210114009 (healthcare) -> None (no fake arrival material).
  ⑥ * Foreign institutions such as Stockholm I161593684 (country≠AU) must appear in the institutions output (closure item 1;
     C-A: foreign is judged from the country_code column).
  ⑧ * Never read affiliations[].years (live check: Zenou's Monash years were backfilled as [1998,...]).
  ⑨ Never take the largest cluster (edges/works/works_affil of all 13 ORCID-less fragments are kept; merging back is U2, this slice drops no fragment).
  ⑩ orcid=0000-0001-6516-0812 lands in the authors table (confirmed live).

How it is judged (spec §6): build the Zenou observation frame -> classify_golden(frame) -> structural_pass=True;
  otherwise run_m1 emits exit(GOLDEN_FAIL=18). works_count_observed∈[550,620] and
  arrival_year_observed∈[2015,2017] -> observed_in_range=True.

* U1/U4/U3 boundary (S6): the U1 golden standard checks only the **raw-material layer** - Zenou is findable, papers/edges/
  affiliations land in the tables, Monash (not Sydney) folds correctly, foreign institutions are in the table, orcid, years not read, largest cluster not taken (all computed and checked for real below from the fixture).
  * "Recognised as a star (top 1%) / arrival 2016 / works in [550,620]" depend on U4 (star) / U3 (arrival) / the full run (works count),
  which U1 cannot produce at its stage -> they are injected placeholders and U1 **does not check** their numeric range (checking an injected value is a false green). The complete real-data golden standard is left to U4/U3 + the full run.

* Discipline: only small fixture works JSON samples test the filter + folding + table writes + decision logic, never a real S3 download.
  classify_golden is a U0 identity pure function (single anchor ZENOU_STRUCTURAL); this test imports the single copy and never makes a second one.
"""
from __future__ import annotations

import pytest

from m1_ingest import run_m1 as R
from identity.golden import MONASH_CANONICAL_ID, classify_golden
from identity.exit_codes import GOLDEN_FAIL


# ---------------------------------------------------------------------------
# fixture: simplified Zenou works records (attached to Monash + Stockholm + ARMI + Caulfield, including fragments)
# ---------------------------------------------------------------------------
# The real Zenou: A5017376589 / orcid 0000-0001-6516-0812.
_ZENOU_ID = "A5017376589"
_ZENOU_ORCID = "0000-0001-6516-0812"

# Institutions (dehydrated, authorships[].institutions[] shape).
_MONASH = {  # A legitimate education parent institution (folding target + registry hit)
    "id": "https://openalex.org/I56590836",
    "display_name": "Monash University",
    "country_code": "AU",
    "type": "education",
    "lineage": ["https://openalex.org/I56590836"],
}
_STOCKHOLM = {  # Foreign institution (country=SE) -> must be in the institutions table (closure item 1, Zenou killer ⑥)
    "id": "https://openalex.org/I161593684",
    "display_name": "Stockholm University",
    "country_code": "SE",
    "type": "education",
    "lineage": ["https://openalex.org/I161593684"],
}
_ARMI = {  # facility, lineage contains Monash -> fold -> Monash
    "id": "https://openalex.org/I2801239119",
    "display_name": "Australian Regenerative Medicine Institute",
    "country_code": "AU",
    "type": "facility",
    "lineage": ["https://openalex.org/I56590836", "https://openalex.org/I2801239119"],
}
_CAULFIELD = {  # healthcare, no education parent institution -> fold -> None (no fake arrival material)
    "id": "https://openalex.org/I4210114009",
    "display_name": "Caulfield Hospital",
    "country_code": "AU",
    "type": "healthcare",
    "lineage": ["https://openalex.org/I4210114009"],
}

# registry (U0.5 table A): only legitimate canonical education parent institutions are in the registry (Monash + Stockholm).
# ARMI / Caulfield are not in the registry -> decided by lineage / failure to fold.
_REGISTRY = [
    {"openalex_id": "I56590836", "type": "education"},
    {"openalex_id": "I161593684", "type": "education"},
]
_ECON_DEPT_IDS = {"I56590836"}  # department boundary set = Monash (this slice only cares about Zenou at Monash)


def _au(institutions, *, raw_affil, orcid=None, with_years=False):
    """Build one Zenou authorship (with institutions + raw_affiliation_strings + an optional trap years)."""
    au = {
        "author": {
            "id": f"https://openalex.org/{_ZENOU_ID}",
            "display_name": "Yves Zénou",
            "orcid": orcid,
        },
        "institutions": institutions,
        "raw_affiliation_strings": raw_affil,
    }
    if with_years:
        # * Trap: real OpenAlex backfills Monash years to [1998, ...]; M1 must never read this field.
        au["affiliations"] = [
            {"raw_affiliation_string": raw_affil[0], "institution_ids": [], "years": [1998, 2000, 2024]}
        ]
    return au


def _zenou_work(wid, *, year, institutions, raw_affil, orcid=None, with_years=False, refs=None):
    return {
        "id": f"https://openalex.org/{wid}",
        "publication_year": year,
        "title": f"Zenou paper {wid}",
        "type": "article",
        "cited_by_count": 500,
        "referenced_works": refs or [],
        "primary_topic": {"subfield": {"id": "https://openalex.org/subfields/2002"}},
        "authorships": [
            _au(institutions, raw_affil=raw_affil, orcid=orcid, with_years=with_years)
        ],
    }


# Zenou works slice: Stockholm early (2010) + Monash later (2018) + ARMI fragment + Caulfield fragment.
# Of the 13 fragments, 4 representative ones are taken here (ORCID-less fragments are also all kept, the largest cluster is not taken).
_ZENOU_WORKS = [
    _zenou_work("W_STK1", year=2010, institutions=[_STOCKHOLM],
                raw_affil=["Stockholm University, Sweden"], orcid=_ZENOU_ORCID),
    _zenou_work("W_MON1", year=2018, institutions=[_MONASH],
                raw_affil=["Monash University, Australia"], orcid=None, with_years=True),
    _zenou_work("W_ARMI1", year=2019, institutions=[_ARMI],
                raw_affil=["ARMI, Monash University"], orcid=None),
    _zenou_work("W_CAUL1", year=2019, institutions=[_CAULFIELD],
                raw_affil=["Caulfield Hospital"], orcid=None),
]


# ---------------------------------------------------------------------------
# slice run: run_m1.build_zenou_slice(works, registry, econ_dept_ids) -> observation frame + output tables
# ---------------------------------------------------------------------------
def _run_slice():
    """Run the M1 Zenou slice (fixture works), returning (frame, tables).

    frame = the observation frame fed to classify_golden; tables = the in-memory rows of each output table (to assert findable / in the tables).
    """
    return R.build_zenou_slice(
        _ZENOU_WORKS,
        registry=_REGISTRY,
        econ_dept_ids=_ECON_DEPT_IDS,
        # The observed works_count / arrival_year are fed in by the caller (a true-value anchor, not computed by the slice):
        # this fixture has only 4 works, but the golden-standard anchor works_count∈[550,620] is the real Zenou's full count;
        # the slice layer injects "observed works_count / arrival_year" as external true-value parameters (spec: the slice checks structural anchors only).
        works_count_observed=580,
        arrival_year_observed=2016,
    )


# ===========================================================================
# tests ①②③: findable + recognised as a star + Monash, not Sydney
# ===========================================================================
def test_found_in_works_and_edges():
    """① Zenou A5017376589 is findable: this author appears in both the works rows and the authorship edges."""
    frame, tables = _run_slice()
    work_ids = {r["work_id"] for r in tables["works"]}
    assert "W_STK1" in work_ids and "W_MON1" in work_ids
    edge_authors = {r["author_id"] for r in tables["authorship_edges"]}
    assert _ZENOU_ID in edge_authors
    assert frame["found"] is True


def test_institution_folds_to_monash_not_sydney():
    """③ After folding, attributed to Monash I56590836 (not Sydney)."""
    frame, _ = _run_slice()
    assert frame["institution_canonical_observed"] == MONASH_CANONICAL_ID
    assert MONASH_CANONICAL_ID == "I56590836"


# ===========================================================================
# tests ④⑤: ARMI -> Monash; Caulfield -> None
# ===========================================================================
def test_armi_folds_to_monash():
    """④ ARMI facility (lineage contains Monash) -> fold_to_canonical -> Monash."""
    frame, _ = _run_slice()
    assert frame["armi_folded_to_monash"] is True


def test_caulfield_folds_to_none():
    """⑤ Caulfield healthcare -> None (not forced into a university, no fake arrival material)."""
    frame, _ = _run_slice()
    assert frame["caulfield_folded_to_none"] is True


# ===========================================================================
# test ⑥: foreign institutions such as Stockholm are in the institutions table (closure item 1, C-A country_code)
# ===========================================================================
def test_foreign_institutions_in_institutions_table():
    """⑥ Stockholm I161593684 (country=SE) is in the institutions table with country_code written correctly (the crux of judging foreign)."""
    _, tables = _run_slice()
    by_id = {r["institution_id"]: r for r in tables["institutions"]}
    assert "I161593684" in by_id, "The Stockholm foreign institution must be in the institutions table (otherwise U3 cannot identify the switch point)"
    assert by_id["I161593684"]["country_code"] == "SE"
    # Monash is there too (AU); foreign and domestic are both kept with zero filtering.
    assert "I56590836" in by_id and by_id["I56590836"]["country_code"] == "AU"


# ===========================================================================
# test ⑧: never read affiliations[].years (redline #3)
# ===========================================================================
def test_never_reads_affiliations_years():
    """⑧ frame.read_affiliations_years must be False (M1 never reads the 1998 backfill trap)."""
    frame, _ = _run_slice()
    assert frame["read_affiliations_years"] is False
    # The observed arrival must not land on 1998 (a 1998 backfill that is not blocked is a failure).
    assert frame["arrival_year_observed"] != 1998


# ===========================================================================
# test ⑨: never take the largest cluster (all fragments kept, including ORCID-less ones)
# ===========================================================================
def test_does_not_take_largest_cluster():
    """⑨ The edges/works_affil of the ORCID-less fragments (W_MON1/W_ARMI1/W_CAUL1) are all kept; the largest cluster is not taken."""
    frame, tables = _run_slice()
    assert frame["took_largest_cluster"] is False
    # works_affil must contain the raw strings of the ORCID-less fragments (left for U2 to merge into clusters).
    affil_works = {r["work_id"] for r in tables["works_affil"]}
    assert {"W_MON1", "W_ARMI1", "W_CAUL1"} <= affil_works
    # The raw_affil of ORCID-less fragments is written out faithfully (contains "Monash University", not zeroed).
    mon_rows = [r for r in tables["works_affil"] if r["work_id"] == "W_MON1"]
    assert any("Monash University" in s for r in mon_rows for s in r["raw_affiliation_strings"])


# ===========================================================================
# test ⑩: orcid lands in the authors table
# ===========================================================================
def test_orcid_in_authors_table():
    """⑩ The Zenou canonical author lands in the authors table + orcid=0000-0001-6516-0812 (kept if any fragment has it)."""
    _, tables = _run_slice()
    by_id = {r["author_id"]: r for r in tables["authors"]}
    assert _ZENOU_ID in by_id, "Yves Zenou must be in the authors table (one row after the canonical merge)"
    assert by_id[_ZENOU_ID]["orcid"] == _ZENOU_ORCID


# ===========================================================================
# test: classify_golden structural_pass=True + observed_in_range
# ===========================================================================
def test_classify_golden_structural_pass():
    """All structural anchors are correct -> classify_golden(frame).structural_pass=True (otherwise run_m1 emits GOLDEN_FAIL=18)."""
    frame, _ = _run_slice()
    verdict = classify_golden(frame)
    assert verdict["structural_pass"] is True, f"Structural anchor flipped: {verdict['flips']}"
    # * U1 boundary (S6): observed_in_range depends on works_count (full run) + arrival (U3),
    #   which are injected placeholders, not computed by U1 -> the U1 golden standard **does not check** it (checking an injected value is a false green). The complete real-data works in [550,620]
    #   + arrival 2016 are left to U4/U3 + the full-run golden standard. U1 checks only structural_pass (structural anchors, computed above from the fixture).


def test_u1_golden_raw_material_independent_of_observed():
    """U1 boundary contract (S6): the U1 golden standard checks only the **raw-material layer**, independent of is_star/arrival/works_count.
    Proof: two different observed sets (works_count/arrival) -> the raw-material output tables are identical byte for byte -> the raw material is not contaminated by the U4 (star) / U3 (arrival)
    placeholders. The complete real-data golden standard (works in [550,620] + real arrival) needs the full run (Zenou's papers span all shards), and is checked after the full run."""
    _, a = R.build_zenou_slice(
        _ZENOU_WORKS, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        works_count_observed=580, arrival_year_observed=2016)
    _, b = R.build_zenou_slice(
        _ZENOU_WORKS, registry=_REGISTRY, econ_dept_ids=_ECON_DEPT_IDS,
        works_count_observed=590, arrival_year_observed=2015)
    for t in ("works", "works_affil", "institutions", "authors", "authorship_edges"):
        assert a[t] == b[t], f"{t} raw material should not change with the observed(star/arrival) placeholder (U1 only verifies raw material)"


def test_zenou_gate_passes_does_not_exit():
    """run_m1.zenou_gate(frame) with structural_pass -> does not exit (returns the verdict)."""
    frame, _ = _run_slice()
    verdict = R.zenou_gate(frame)  # not raising = passed
    assert verdict["structural_pass"] is True


# ===========================================================================
# test: structural_pass=False -> run_m1 emits exit(GOLDEN_FAIL=18)
# ===========================================================================
def test_zenou_gate_fail_exits_golden_fail():
    """Any structural anchor failing (e.g. folded to Sydney) -> zenou_gate exit(GOLDEN_FAIL=18)."""
    bad_frame = {
        "found": True,
        "resolved_single_person": True,
        "is_star_at_p01": True,
        # * Folded to Sydney (not Monash) = a structural anchor fails.
        "institution_canonical_observed": "I_SYDNEY",
        "armi_folded_to_monash": True,
        "caulfield_folded_to_none": True,
        "rejected_1998_backfill": True,
        "read_affiliations_years": False,
        "took_largest_cluster": False,
        "arrival_year_observed": 2016,
        "works_count_observed": 580,
    }
    with pytest.raises(SystemExit) as ei:
        R.zenou_gate(bad_frame)
    assert ei.value.code == GOLDEN_FAIL


def test_zenou_gate_fail_on_1998_backfill():
    """Reading affiliations.years and putting arrival at 1998 = redline #3 fails -> exit(GOLDEN_FAIL)."""
    bad_frame = {
        "found": True,
        "resolved_single_person": True,
        "is_star_at_p01": True,
        "institution_canonical_observed": MONASH_CANONICAL_ID,
        "armi_folded_to_monash": True,
        "caulfield_folded_to_none": True,
        "rejected_1998_backfill": False,      # did not block the 1998 backfill
        "read_affiliations_years": True,      # read the years trap
        "took_largest_cluster": False,
        "arrival_year_observed": 1998,        # landed on 1998
        "works_count_observed": 580,
    }
    with pytest.raises(SystemExit) as ei:
        R.zenou_gate(bad_frame)
    assert ei.value.code == GOLDEN_FAIL
