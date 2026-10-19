"""Signal discard mechanism - build_star_set consumes a discard list (TDD).

In plain words: the rule is that part-time / honorary affiliations before full-time arrival, and mis-attributed
bylines, do not count as "having worked in Australia". It is implemented **not** by forcing poach=True without
evidence (still forbidden), but by **discarding, one by one,** the specific affiliation rows from the
contaminated / part-time period (an auditable adjudication with evidence + URL), so that is_foreign_poach organically
returns True on the remaining clean evidence:
  - mis-affiliation type: a mis-affiliated byline row at the home university before arrival is discarded ->
    overseas evidence remains -> True;
  - part-time type: a part-time-period byline at the home university before arrival is discarded -> overseas
    evidence remains -> True;
  - bio-backfill type: the current-post bio backfill row + the adjunct-period row are discarded separately ->
    overseas evidence remains -> True.
fail-loud: a discard entry not in the candidates / matching 0 rows (cannot be matched) -> ValueError; unrelated
people do not move at all; the local-transfer type (hand-review forces False) is unaffected.
"""
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from run_u4 import ROSTER_FILES, build_star_set

ECON = "2002"
UNSW = "I31746571"
MON = "I56590836"

_ROSTER_SCHEMA = pa.schema([
    ("author_id", pa.string()), ("display_name", pa.string()), ("dept_key", pa.string()),
    ("year_start", pa.int64()), ("confidence", pa.string()), ("human_verified", pa.bool_()),
])


def _w(root, subpath, rows, schema=None):
    p = root / subpath
    p.parent.mkdir(parents=True, exist_ok=True)
    tbl = pa.Table.from_pylist(rows, schema=schema) if schema else pa.Table.from_pylist(rows)
    pq.write_table(tbl, str(p))


def _root(tmp_path):
    """Synthetic derived_root: three poached stars "pushed to False by a false in-Australia signal" + a local transfer
    + an unrelated overseas person.

    S_MIS   (mis-affiliation type): arrival 2003; before arrival NZ 2000 + UNSW mis-affiliation 2000 (a clean row,
                                    not an exploded or stamped one).
    S_ADJ   (part-time type):       arrival 2021; before arrival SE 2017 + Monash part-time byline 2020 (a clean row).
    S_BIO   (bio-backfill type):    arrival 2021; before arrival US 2018 + Monash bio backfill 2019 + adjunct 2020.
    S_LOC   (local-transfer type):  arrival 1997; before arrival a genuine AU employment -> organic False +
                                    hand-review forces False.
    M_CLEAN (unrelated person):     arrival 2016; before arrival only SE -> True (discarding other people's signals
                                    must not move this person).
    """
    r = tmp_path
    _w(r, ROSTER_FILES[0], [
        {"author_id": "S_ADJ", "display_name": "Star Adj", "dept_key": "monash_econ",
         "year_start": 2021, "confidence": "high", "human_verified": True},
        {"author_id": "S_BIO", "display_name": "Star Bio", "dept_key": "monash_econ",
         "year_start": 2021, "confidence": "high", "human_verified": True},
        {"author_id": "S_LOC", "display_name": "Star Loc", "dept_key": "monash_econ",
         "year_start": 1997, "confidence": "high", "human_verified": True},
        {"author_id": "M_CLEAN", "display_name": "Clean Person", "dept_key": "monash_econ",
         "year_start": 2016, "confidence": "high", "human_verified": True},
    ], schema=_ROSTER_SCHEMA)
    _w(r, ROSTER_FILES[1], [
        {"author_id": "S_MIS", "display_name": "Star Mis", "dept_key": "unsw_econ",
         "year_start": 2003, "confidence": "high", "human_verified": True},
    ], schema=_ROSTER_SCHEMA)
    _w(r, "u1_edges_full_2026-07-05/authorship_edges/part.parquet", [
        {"author_id": "S_MIS", "work_id": "W1"}])
    _w(r, "u1_edges_full_2026-07-05/works/part.parquet", [
        {"work_id": "W1", "publication_year": 2000, "cited_by_count": 5, "subfield_id": ECON}])
    _w(r, "u1_edges_full_2026-07-05/institutions/part.parquet", [
        {"institution_id": "I_NZ", "country_code": "NZ"},
        {"institution_id": "I_SE", "country_code": "SE"},
        {"institution_id": "I_US", "country_code": "US"},
        {"institution_id": "I_AU2", "country_code": "AU"},
        {"institution_id": UNSW, "country_code": "AU"},
        {"institution_id": MON, "country_code": "AU"}])
    _w(r, "u2_person_map_2026-07-05/person_map/part.parquet", [
        {"author_id": "S_MIS", "person_id": "P_MIS"},
        {"author_id": "S_ADJ", "person_id": "P_ADJ"},
        {"author_id": "S_BIO", "person_id": "P_BIO"},
        {"author_id": "S_LOC", "person_id": "P_LOC"},
        {"author_id": "M_CLEAN", "person_id": "P_C"}])
    _w(r, "u3_panel_2026-07-06/panel/part.parquet", [
        {"person_id": "P_MIS", "year": 2003, "primary_affil_id": UNSW}])
    _w(r, "u3_panel_2026-07-06/affil_timeline/part.parquet", [
        # S_MIS: genuine NZ prehistory + UNSW mis-affiliation (2000-2002, the person was overseas)
        {"person_id": "P_MIS", "year": 2000, "work_id": "WJ0",
         "raw_affil": "Overseas University, New Zealand", "canonical_affil_id": "I_NZ"},
        {"person_id": "P_MIS", "year": 2000, "work_id": "WJ1",
         "raw_affil": "School of Economics, UNSW Sydney", "canonical_affil_id": UNSW},
        # S_ADJ: genuine SE prehistory + Monash part-time-period byline 2020
        {"person_id": "P_ADJ", "year": 2017, "work_id": "WM0",
         "raw_affil": "Overseas University, Sweden", "canonical_affil_id": "I_SE"},
        {"person_id": "P_ADJ", "year": 2020, "work_id": "WM1",
         "raw_affil": "Overseas University, Monash University, and CEPR",
         "canonical_affil_id": MON},
        # S_BIO: genuine US prehistory + 2019 bio backfill + 2020 adjunct-period byline
        {"person_id": "P_BIO", "year": 2018, "work_id": "WW0",
         "raw_affil": "Overseas University, USA", "canonical_affil_id": "I_US"},
        {"person_id": "P_BIO", "year": 2019, "work_id": "WW1",
         "raw_affil": "Star Bio is a member of staff at Monash University",
         "canonical_affil_id": MON},
        {"person_id": "P_BIO", "year": 2020, "work_id": "WW2",
         "raw_affil": "Monash University, Clayton, Australia", "canonical_affil_id": MON},
        # S_LOC: genuine AU employment before arrival -> local transfer
        {"person_id": "P_LOC", "year": 1995, "work_id": "WB0",
         "raw_affil": "Australian University", "canonical_affil_id": "I_AU2"},
        # M_CLEAN: overseas only
        {"person_id": "P_C", "year": 2014, "work_id": "WC0",
         "raw_affil": "Overseas University B, Sweden", "canonical_affil_id": "I_SE"},
    ])
    return r


def _discards():
    def e(dept, inst, y0, y1, reason):
        return {"dept_key": dept, "institution_id": inst, "year_from": y0, "year_to": y1,
                "reason": reason, "evidence": "human_verified_web:CV/Wayback (test fixture)",
                "url": "https://example.org/evidence"}
    return {
        "S_MIS": [e("unsw_econ", UNSW, 2000, 2002, "misattributed byline: person was abroad")],
        "S_ADJ": [e("monash_econ", MON, 2016, 2020, "full-time abroad + Monash adjunct-period byline")],
        "S_BIO": [e("monash_econ", MON, 2019, 2019, "current-post bio backfill, misattributed"),
                  e("monash_econ", MON, 2020, 2021, "CV adjunct 2020-2021 adjunct affiliation period")],
    }


def test_signal_discards_restore_poach_true_for_three(tmp_path):
    """Red -> green core: no discards -> three people are pushed to False by false in-Australia signals; with the
    discard list -> organically back to True; the local-transfer type (genuine local transfer + hand-review forces
    False) and the unrelated person do not move at all."""
    root = _root(tmp_path)
    base = build_star_set(root, poach_overrides={"S_LOC": False})
    b = {s["author_id"]: s["is_foreign_poach"] for s in base["stars"]}
    assert b["S_MIS"] is False and b["S_ADJ"] is False and b["S_BIO"] is False
    assert b["S_LOC"] is False and b["M_CLEAN"] is True

    res = build_star_set(root, poach_overrides={"S_LOC": False},
                         signal_discards=_discards())
    g = {s["author_id"]: s["is_foreign_poach"] for s in res["stars"]}
    assert g["S_MIS"] is True          # mis-affiliation discarded -> NZ evidence remains -> pure foreign poach
    assert g["S_ADJ"] is True           # part-time-period byline discarded -> SE evidence remains
    assert g["S_BIO"] is True           # bio backfill + adjunct period both discarded -> US evidence remains
    assert g["S_LOC"] is False          # the hand-review adjudication (genuine employment in Australia) is not affected by the discard mechanism
    assert g["M_CLEAN"] is True         # the unrelated person does not move


def test_signal_discards_diag_counts_in_result(tmp_path):
    """Each discard records a diagnostic count: result["signal_discards_applied"] has, per person and per entry, the
    number of matched rows."""
    res = build_star_set(_root(tmp_path), poach_overrides={"S_LOC": False},
                         signal_discards=_discards())
    diag = res["signal_discards_applied"]
    assert diag["S_MIS"]["n_rows_discarded"] == 1
    assert diag["S_ADJ"]["n_rows_discarded"] == 1
    assert diag["S_BIO"]["n_rows_discarded"] == 2
    ents = diag["S_BIO"]["entries"]
    assert [e["n_rows_matched"] for e in ents] == [1, 1]
    assert ents[0]["institution_id"] == MON and ents[0]["year_from"] == 2019


def test_signal_discard_zero_match_entry_fails_loud(tmp_path):
    """Mismatch 1: an entry matches 0 rows (the window/institution does not match the evidence on disk) -> ValueError
    naming it, never a silently ineffective discard."""
    bad = {"M_CLEAN": [{"dept_key": "monash_econ", "institution_id": MON,
                        "year_from": 1980, "year_to": 1981, "reason": "signal that does not exist",
                        "evidence": "x", "url": None}]}
    with pytest.raises(ValueError, match="M_CLEAN"):
        build_star_set(_root(tmp_path), poach_overrides={"S_LOC": False},
                       signal_discards=bad)


def test_signal_discard_unknown_author_fails_loud(tmp_path):
    """Mismatch 2: a discard entry's author_id is not in the candidate set (mistyped id / wrong roster version) ->
    ValueError naming it."""
    bad = {"A_NOBODY": [{"dept_key": "monash_econ", "institution_id": MON,
                         "year_from": 2019, "year_to": 2020, "reason": "misspelled id",
                         "evidence": "x", "url": None}]}
    with pytest.raises(ValueError, match="A_NOBODY"):
        build_star_set(_root(tmp_path), poach_overrides={"S_LOC": False},
                       signal_discards=bad)
