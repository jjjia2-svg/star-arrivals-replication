"""U0.5 Table A ECON_DEPT_REGISTRY producer - folds out `econ_dept_ids`.

Table A = the department-level list of "which institutions count as economics departments"; it folds out
`econ_dept_ids: set[str]` (bare canonical education ids), which feeds the downstream
`pass_a_seed_authors(..., econ_dept_ids=<produced by this unit>)` directly.

★ Start with a coarse criterion: econ_dept_ids = the university institution sets of the two schools {Monash, UNSW};
  downstream then narrows to economics departments with the curated list + the subfield definition
  (Economics and Econometrics).
★ The boundary metadata (dept_name_variants / subfield_*) comes from the subfield definition: wide keyword
  inclusion + main subfield = "Economics and Econometrics", excluding Finance / Business-Management-Accounting;
  no discretionary choice.
★ Institution ids: Monash I56590836 (golden anchor); UNSW I31746571 (confirmed by the full run).
"""
from __future__ import annotations

from typing import Dict, List

from common.inst_lineage import fold_to_canonical
from identity.golden import MONASH_CANONICAL_ID

UNSW_INST_ID = "I31746571"  # Confirmed by full-run evidence

# The merged new Adelaide entity of 2026 (Adelaide University,
# ROR 028g18b61, works=0, associated=predecessor I5681781, checked via the API) is only a
# watch - usable by current resolution, never put into the registry rows of the 2000-2025 window (all works inside the
# window attach to the old entity).
ADELAIDE_WATCH_INST_ID = "I4405259444"

# Main subfield list (the subfields under the OpenAlex field "Economics, Econometrics and Finance").
_SUBFIELD_PRIMARY = ["Economics and Econometrics"]
_SUBFIELD_EXCLUDED = ["Finance"]  # + the whole Business/Management/Accounting field (field level, filtered downstream)


def build_table_a_rows() -> List[dict]:
    """ECON_DEPT_REGISTRY rows of the two economics departments (10 columns, coarse-criterion smoke test). Boundary from the subfield definition, institution ids confirmed."""
    return [
        {
            "dept_key": "monash_econ",
            "university": "Monash University",
            "openalex_inst_id": MONASH_CANONICAL_ID,  # I56590836 (golden anchor)
            "dept_name_variants": [
                "Department of Economics",
                "Department of Econometrics and Business Statistics",
                # The '&' form, measured in a full works_affil evidence scan: 113 authors
                # ('Monash University - Department of Econometrics & Business Statistics'),
                # the 'and' form phrase does not hit it -> listed as a separate entry; whether EBS belongs is a separate department-boundary question.
                "Department of Econometrics & Business Statistics",
            ],
            "is_business_school": False,
            "subfield_primary": list(_SUBFIELD_PRIMARY),
            "subfield_robustness_flagged": [],
            "subfield_excluded": list(_SUBFIELD_EXCLUDED),
            "source": "manual",
            "human_verified": True,  # Monash institution id confirmed against the golden anchor + boundary from the subfield definition
        },
        {
            "dept_key": "unsw_econ",
            "university": "UNSW Sydney",
            "openalex_inst_id": UNSW_INST_ID,
            "dept_name_variants": [
                "School of Economics",
                # Historical old name; an evidence scan measured 141 authors with the real string
                # ('Department of Economics, University of New South Wales' etc.) -
                # keeping only the current name would miss the early 2000s = exactly the years the historical roster is meant to recover.
                "Department of Economics",
            ],
            "is_business_school": False,
            "subfield_primary": list(_SUBFIELD_PRIMARY),
            "subfield_robustness_flagged": [],
            "subfield_excluded": list(_SUBFIELD_EXCLUDED),
            "source": "manual",
            # I31746571 confirmed (in the full U1 run all school bylines of A5006435210/A5103238089/A5054240727
            # attach to it).
            "human_verified": True,
        },
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Department-name whitelist of the 9 added schools.
#
# Registration discipline:
#   - include phrases = the "include" rows of the draft + the institutes/centres added by the boundary adjudications
#     (Melbourne Institute / SEPS / CEPA / CUBES / CHERE) + department-level "pending" rows included widely by the
#     derived general rule (include phrases widely and let human review guard identity; the wide-inclusion precedent
#     of Monash EBS).
#   - Faculty-level / higher-level establishment phrases (FEC/FBE/CBE/ABLE/Division/Business School etc.) are
#     **not registered** - wide inclusion of such phrases is not applied, so they stay pending (to be added only
#     deliberately).
#   - The effective years per phrase come from the draft evidence (Wayback snapshot anchors, boundary years ±1 are
#     normal) and are recorded in the in-line comments.
#   - human_verified=True: the institution ids were verified manually together with the candidates, in bulk.
#   - The two-school production path build_table_a_rows() is untouched (frozen pipeline, zero regression); the
#     expansion goes through build_expansion_table_a_rows() / build_table_a_rows_all().
# ═══════════════════════════════════════════════════════════════════════════


def build_expansion_table_a_rows() -> List[dict]:
    """ECON_DEPT_REGISTRY rows of the 9 expansion schools. Same schema as the two-school rows (10 columns)."""

    def _row(dept_key: str, university: str, inst_id: str, variants: List[str]) -> dict:
        return {
            "dept_key": dept_key,
            "university": university,
            "openalex_inst_id": inst_id,
            "dept_name_variants": variants,
            "is_business_school": False,
            "subfield_primary": list(_SUBFIELD_PRIMARY),
            "subfield_robustness_flagged": [],
            "subfield_excluded": list(_SUBFIELD_EXCLUDED),
            "source": "manual",
            # All verified manually in bulk, together with the candidates.
            "human_verified": True,
        }

    return [
        _row("melbourne_econ", "University of Melbourne", "I165779595", [
            "Department of Economics",  # Full 2000-2025 (2009 snapshot + the current FBE page returns 200 every year)
            # The Melbourne Institute counts (it is in the same building as the department; counted from 2000 on).
            # Both name forms are accepted: the of…and form (original name 1962-96, restored from 2024);
            # the colon-& form (1996-2024, strings in practical use on SSRN/LinkedIn) - same reasoning as the Monash EBS '&' form precedent.
            "Melbourne Institute of Applied Economic and Social Research",
            "Melbourne Institute: Applied Economic & Social Research",
            # The higher-level FEC (2000-~09)/FBE (~2010-) is not registered for wide inclusion -> pending (faculty-level phrase).
        ]),
        _row("sydney_econ", "The University of Sydney", "I129604602", [
            "School of Economics",       # 2011-2025 (2012 snapshot 8x + current live page 200)
            "Discipline of Economics",   # ~2002-2010 (2005 snapshot title 6x)
            # SEPS counts (a politics department was still in use in 2000) - politics scholars mixed in are removed by human review.
            "School of Economics and Political Science",   # ~2000-2010
            # Department-level econometrics twin ~2000-2010 (2003 snapshot 10x); same as Monash EBS -> wide inclusion + matched_phrase can cut it.
            "Discipline of Econometrics and Business Statistics",
            # Higher-level Faculty of Economics and Business (2000-10) -> pending (faculty-level phrase).
        ]),
        _row("anu_econ", "Australian National University", "I118347636", [
            "Research School of Economics",  # 2011-2025 (2015 snapshot 6x + current live page 200)
            "School of Economics",           # 2000-2011 (2001 snapshot title; archive exists for the CBE period 2009-10)
            # 2000-2010 research-side predecessor at RSSS - two conditions: phrase + binding word RSSS (see byline
            # _PHRASE_REQUIRES), so that the bare "Economics Program" cannot collide with a same-named program at another school.
            "Economics Program",
            # Higher-level FEC (2000-~06)/CBE (~2006-) -> pending (faculty-level phrase).
            # The neighbouring units Crawford/Arndt-Corden do not belong to anu_econ -> isolated by the byline exclude token.
        ]),
        _row("uq_econ", "The University of Queensland", "I165143802", [
            "School of Economics",      # ~2001-2025 (the 2001-10 snapshot already has this name; current live page 200)
            "Department of Economics",  # 2000-~2001 old name (2000-08 snapshot 4x; the rename is pinned at ≈2001)
            "Economics Department",     # 2000-~2001 word-order variant (original 2000 snapshot title)
            # CEPA/CUBES count (research centres). Full-name phrases;
            # the abbreviation forms (bare CEPA/CUBES) are not registered - substring contamination risk (e.g. B. cepacia), to be backfilled from real data.
            "Centre for Efficiency and Productivity Analysis",       # CEPA (attached to the School of Economics)
            "Centre for Unified Behavioural and Economic Sciences",  # CUBES (verified on the web)
        ]),
        _row("uwa_econ", "The University of Western Australia", "I177877127", [
            "Department of Economics",  # 2000-~2004 (1998 department site STAFF.HTM; the current page still calls itself Department)
            "Economics Department",     # Word-order variant (customary in RePEc; wide inclusion by inference, rated low risk in the draft)
            # ~2004/05-~2008 middle-period name (2005 biz site snapshot); "and Commerce" also picks up commerce scholars, same as Monash EBS
            # -> wide inclusion + matched_phrase can cut it.
            "School of Economics and Commerce",
            # Business School period (~2008-2020): bylines often print only the school name without a department phrase -> systematic
            # misses are handled by backfilling from a real-data scan (same path as the works_affil variant completion for the two schools);
            # the higher-level "UWA Business School" phrase itself is not registered for wide inclusion -> pending (faculty-level phrase).
        ]),
        _row("adelaide_econ", "The University of Adelaide", "I5681781", [
            "School of Economics",                 # 2000-~2019 and 2026- (confirmed by 2003/2010 archives)
            "School of Economics and Public Policy",  # ~2019-2025 (2022 snapshot title 7x)
            # The merged university follows the old-name criterion: in the 2000-2025 window everything attaches to the old entity I5681781;
            # the new 2026 entity I4405259444 is only watched (ADELAIDE_WATCH_INST_ID).
            # Whether people of the former UniSA (I170239107) count is undecided and is not part of this row.
            # Higher-level ABLE (2019-25) -> pending (faculty-level phrase).
        ]),
        _row("deakin_econ", "Deakin University", "I149704539", [
            "School of Economics",      # 2000-~2003 early independent department (confirmed by the navigation of the 2003-04 snapshots;
                                        # 2000-02 has no direct snapshot = inferred, flagged as such in the draft)
            # ~2003-2013/14 AEF merger period (2004 staff page title) - the only economics-containing department name of that period; leaving it out would miss
            # the whole decade; the wide accounting/finance catch is the same as Monash EBS -> wide inclusion + matched_phrase can cut it.
            "School of Accounting, Economics and Finance",
            "Department of Economics",  # ~2014-2025 (staff listing returns 200 every year 2016-23)
            "Economics Discipline Group",  # Name on the 2025-26 experts portal (61/61 captured);
                                           # collides with the same name at UTS 2011-19 -> told apart by the binding token.
            # Higher-level Deakin Business School -> pending (faculty-level phrase).
            # No evidence yet of economics faculty listing the India GIFT City campus (2024-) -> no exclude token;
            # add one if real data of the expansion show "GIFT City"/"India" strings (same handling as the Monash Malaysia precedent).
        ]),
        _row("uts_econ", "University of Technology Sydney", "I114017466", [
            # 2000-~2011 the only department name of that period (2003 staff page title) - leaving it out would miss the whole 2000s;
            # the wide "Finance and" catch of finance people is the same as Monash EBS -> wide inclusion + matched_phrase can cut it.
            "School of Finance and Economics",
            "Economics Discipline Group",   # ~2011/12-~2019 (confirmed by the 2014-12 staff page)
            "Economics Department",         # ~2019-2024 transitional name (clue from 2024 URL variants;
            "Department of Economics",      #   no page-level phrase is pinned down, the draft honestly marks it as inferred -> wide inclusion against misses)
            "School of Economics and Marketing",  # 2025- (title of the current page, captured; Marketing people
                                                  # are filtered by U0.5 by section)
            # CHERE is added (health economics centre) - profiles group 206,
            # bylines often print "CHERE, University of Technology, Sydney" without a department name.
            "Centre for Health Economics Research and Evaluation",
            # Higher-level UTS Business School -> pending (faculty-level phrase).
        ]),
        _row("macquarie_econ", "Macquarie University", "I99043593", [
            "Department of Economics",  # Full 2000-2025 (2001 snapshot 6x -> 2013 our_staff ->
                                        # current MBS page returns 200 every year 2022-24) - the most stable department name of the 9 schools.
            # Higher-level EFS Division (2000-~08)/FBE (~2009-19)/MBS (2019-) -> pending (faculty-level phrases).
        ]),
    ]


def build_table_a_rows_all() -> List[dict]:
    """All 11 schools' registry rows = the frozen two-school rows (unchanged, first) + the 9 expansion rows. The expansion run uses this;
    the two-school production drivers (run_u0p5.main_table_a / main_byline_steps_0_2) still use build_table_a_rows()."""
    return build_table_a_rows() + build_expansion_table_a_rows()


_DETERMINISTIC_PARQUET_KW: dict = {
    "compression": "zstd",
    "use_dictionary": False,
    "write_statistics": False,
}


def write_table_a(rows, target) -> None:
    """Write the Table A rows as one deterministic parquet file; before writing every row is checked against the ECON_DEPT_REGISTRY schema (in the style of table_b).

    Steps: materialize -> per row assert_matches_schema(ECON_DEPT_REGISTRY) (extra/missing keys raise) -> canonical-sort by
    dept_key (None last) -> column order = schema key order (pinned) -> fixed write parameters (zstd/dictionary off/no
    statistics) -> the same content gives a byte-level equal sha. Empty rows -> still writes a 0-row parquet with the right column order.
    """
    from pathlib import Path

    import pyarrow as pa
    import pyarrow.parquet as pq
    from common.schema import ECON_DEPT_REGISTRY, assert_matches_schema

    materialized = [dict(r) for r in rows]
    for r in materialized:
        assert_matches_schema(r.keys(), ECON_DEPT_REGISTRY, label="econ_dept_registry")

    pk_cols = ("dept_key",)  # dept_key is unique -> the sort is deterministic
    materialized.sort(
        key=lambda r: tuple((r[c] is None, "" if r[c] is None else r[c]) for c in pk_cols)
    )
    col_order = list(ECON_DEPT_REGISTRY.keys())
    columns = {c: [r[c] for r in materialized] for c in col_order}
    table = pa.table({c: columns[c] for c in col_order})

    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        table, str(target), row_group_size=max(1, table.num_rows), **_DETERMINISTIC_PARQUET_KW
    )


def build_econ_dept_ids(table_a_rows, registry_by_id: Dict[str, dict]) -> set:
    """Table A rows -> econ_dept_ids: set[str] (the openalex_inst_id of each row is folded by fold_to_canonical to a bare
    canonical education id; one that cannot be folded (legitimately None) is dropped without error). Feeds the downstream
    pass_a_seed_authors directly.
    """
    ids = set()
    for r in table_a_rows:
        inst = {
            "openalex_id": r["openalex_inst_id"],  # ★ Key remap: fold path1 reads openalex_id
            "type": "education",
            "lineage": [],
            "associated_institutions": [],
        }
        canon = fold_to_canonical(inst, registry_by_id)
        if canon is not None:
            ids.add(canon)
    return ids
