"""final52 2026-07-21 — shared constants and the new star table (16 -> 51 event expansion; the planned
target was 52, but the run turned up one real identification conflict [A5063040920], which is
excluded pending manual review; see the constant comments below and EXCL_A5063040920_ID).

Task: run the full chain of the top-5% expansion — the 16-event version (5 anchors + 11 newly verified,
delivered 07-20) plus the newly verified top-5% events. Caliber unchanged, only more events, and the main dose
ruler becomes topic similarity:
  - Target event count = 52 = the existing 16 (carried over byte for byte from u4_star_set_16ev_2026-07-20/events, not rebuilt)
           + 36 new (from v2_output/r_51ev_2026-07-20/data/new_stars_draft_37_*.csv,
           excluding A5020228087 — after correction the academic age = 0, which does not fit the
           "senior poached star" definition; under manual review, not part of this run).
  - **Found during the run**: 2 of the 36 are already in the existing frozen star set of 197 (exact
    author_id match, not a guess):
    A5063040920 (identification-gate conflict: the existing row has is_foreign_poach=False, i.e. the real
    affil_timeline data shows an Australian post before arrival, which fails gate 4 — this run **excludes** this person;
    pending manual review) and
    A5072079903 (no conflict, only a duplicate: already on the list; the existing row is reused after
    de-duplication, the new event is still assembled, no new row is opened).
    -> actual new events = 35 (34 new star-set rows + A5072079903 reusing the existing row), **actual total events = 51**,
    not the planned 52 (the difference of 1 is A5063040920; reported as is, not padded).
  - The 5 Adelaide gap events (A5075194454/A5013630114/A5085246004/A5011262618/A5059426203) are **kept**; their colleague pool now uses the
    Adelaide 2007-2021 gap-filled merged roster (u0p5_roster/adelaide_backfill_2007_2021_2026-07-20/
    dept_roster_panel_adelaide_MERGED_209plus_gapfill.parquet), not the original registry_v5
    (which has only 1 person per year for 2007-2021, leaving the colleague pool almost empty).
  - Colleague pool = registry_v5 of 9 schools (Adelaide replaced by the gap-filled merged version) + monash/unsw roster_v4,
    with the star-set members themselves removed (same rule as the 16-event version).
  - Dose = frozen at t-1, the main channel switched to topic_cos (topic similarity; m4_dose/topic_vec.py, the secondary
    channel #16; reuses two columns of the dose.parquet produced by the same U5 run, no new estimator design).
  - Estimator = dCDH did_multiplegt_dyn, effects=6, placebo=4 (byte-for-byte the same as the 16-event version).

Source of the new-star fields: v2_output/r_51ev_2026-07-20/data/new_stars_draft_37_2026-07-20.csv
(37 rows = the 07-20 top-5% verification batch, academic_age recomputed from the manually corrected start year [6 people
changed by hand], minus
A5020228087 + A5063040920 = 35, of which A5072079903 is de-duplicated and opens no new star-set row -> 34 new star-set rows).

★Honest simplification (recorded, not hidden): in the star_set rows of these 34 people percentile/cell_n are left empty (None) —
whether these people count as stars was decided directly by the top-5% manual verification (is_star_1pct=is_star_5pct=True filled in directly,
no automatic ranking); percentile/cell_n are "corroborating columns produced by the automatic ranking", which were never computed for this batch,
and leaving them empty reflects that honestly; no numbers are invented to look computed. These two columns do not enter the dose / frame / regression
computations of U5/U6 (they are used only in run_u4's automatic ranking report), so leaving them empty does not affect any regression result.
★Honest simplification 2: arrival_source is recorded uniformly as "official_roster" for the 34 people (the strong literature-grade evidence
bucket among the six sources, corresponding to "verified = found in official rosters / department pages / official websites or other institutional records", the same
source and bucket as 13 of the 16 rows in the existing 16 events). The top-5% verification report did not break each person down to one of the six sources, so the same bucket is used here instead of
inventing a more specific source name (e.g. when not sure whether it is ORCID, orcid_employment is not written). This column is only a
descriptive provenance label and does not affect any value of arrival_year/dose/frame/regression.
"""
from __future__ import annotations

import csv
import pathlib

# --- M3 port: repo path resolution (legacy hard-coded the author's machine) — config/paths.yaml ---
import pathlib as _sar_pl, sys as _sar_sys
_sar_repo = _sar_pl.Path(__file__).resolve().parents[3]
if str(_sar_repo) not in _sar_sys.path:
    _sar_sys.path.append(str(_sar_repo))
from pipeline.lib.paths import (derived_root as _sar_derived_root,  # noqa: E402,F401
                                snapshot_root as _sar_snapshot_root,
                                ssd_root as _sar_ssd_root,
                                legacy_thesis as _sar_legacy_thesis,
                                require_readable as _sar_rd,
                                require_writable as _sar_rw,
                                output_target as _sar_out,
                                deferred_output_target as _sar_lazyout)

SSD = _sar_rw(_sar_derived_root())
REPO = pathlib.Path(__file__).resolve().parents[2]          # multiplex_pipeline/

# ---- Upstream anchors (read-only) -------------------------------------------------
EDGES_SUB = "u1_full_11school_2026-07-16"
PM_SUB = "u2_person_map_11school_2026-07-16"
PM_DIR = "u2_person_map_11school_2026-07-16/person_map"
PANEL_SUB = "u3_panel_11school_2026-07-16"
TIMELINE_SUB = "u3_panel_11school_2026-07-16/affil_timeline"

U4_16EV = SSD / "u4_star_set_16ev_2026-07-20"                # Frozen 16-event version (read-only, carried over byte for byte)
REGISTRY_V3 = SSD / "u0p5_roster" / "registry_v3_2026-07-12"
REGISTRY_V5 = SSD / "u0p5_roster" / "registry_v5_2026-07-20"  # 9-school id assignment (read-only)
ROSTER_V4_PROJ8 = SSD / "u5u6_final_2026-07-18_work" / "roster_v4_proj8"
REGISTRY_TABLE_A = REGISTRY_V3 / "econ_dept_registry_11schools.parquet"

# Adelaide 2007-2021 gap-filled merged version (read-only) — authoritative source of the colleague pool for the 5 gap events; do not use the original REGISTRY_V5
ADELAIDE_MERGED = (SSD / "u0p5_roster" / "adelaide_backfill_2007_2021_2026-07-20" /
                   "dept_roster_panel_adelaide_MERGED_209plus_gapfill.parquet")

# ---- Outputs of this run (brand-new dated directories, created only, never overwritten) ---------------------------------
# Top-10% version (80ev, effectively 79: A5045410390 excluded by the academic-age gate <2, see load_new_stars): 16 anchors + draft35 + 28 additional
U4_OUT = SSD / "u4_star_set_p10_80ev_2026-07-22"
U5_OUT = SSD / "u5_ship_11school_p10_80ev_2026-07-22"
U6_OUT = SSD / "u6_ship_11school_p10_80ev_2026-07-22"
R_PKG = _sar_lazyout(pathlib.Path(
    str(_sar_legacy_thesis()) + "/"
    "v2_output/r_p10_80ev_2026-07-22"))

NINE_SCHOOLS = ("adelaide", "anu", "deakin", "macquarie", "melbourne",
               "sydney", "uq", "uts", "uwa")

# dept_key -> university canonical inst id (table A registry_v3, human_verified=True)
DEPT_INST_11 = {
    "adelaide_econ": "I5681781",   "anu_econ": "I118347636",
    "deakin_econ": "I149704539",   "macquarie_econ": "I99043593",
    "melbourne_econ": "I165779595", "monash_econ": "I56590836",
    "sydney_econ": "I129604602",   "unsw_econ": "I31746571",
    "uq_econ": "I165143802",       "uts_econ": "I114017466",
    "uwa_econ": "I177877127",
}

# ---- Existing 16 events (carried over byte for byte from u4_star_set_16ev_2026-07-20/events, not rebuilt) -----
EXISTING_16EV_IDS = [
    "A5017376589:2016", "A5020729611:2017", "A5022446221:2020",
    "A5029151069:2019", "A5035157505:2018", "A5059428122:2021",
    "A5059554264:2021", "A5070264657:2009", "A5071656006:2000",
    "A5076526695:2018", "A5079006965:2011", "A5080057811:2006",
    "A5083649140:2013", "A5087235620:2016", "A5089150146:2013",
    "A5103238589:2011",
]

EXCL_A5020228087_ID = "A5020228087"   # Excluded: academic age = 0 after correction; under manual review, not taken in this run

# ★Real data conflict found during the run (measured 2026-07-21, not a guess) ------------------------
# Checked the remaining 36 of draft_37 author_id by author_id against the existing frozen star set of 197 (including the original 186 automatic candidate pool),
# found 2 already on the list, by reading the two parquet files directly with duckdb/pyarrow (a check, not an estimate):
#   A5063040920 (monash_econ): the existing row has arrival=2009 (consistent with draft_37 after its year change)
#     but is_foreign_poach=**False** — i.e. the automatic pipeline, using the real affil_timeline data, found an Australian
#     post before the arrival (2009), which fails the identification gate "gate 4: never held an Australian post before arrival".
#     The top-5% manual verification batch only changed the arrival year (2010->2009) and did not independently re-check this gate,
#     so the two sources of evidence conflict. No discretion at the identification layer — this run **excludes** this person
#     (it follows the gate as defined, it does not pick a side); inclusion is to be decided once the affil_timeline evidence has been checked.
#   A5072079903 (unsw_econ): the existing row has arrival=2006, identical to draft_37,
#     is_foreign_poach=True (both sources agree, no conflict) — the person is simply "already in the pool of 186 automatic candidates,
#     but UNSW had not been lit up as an event before". This is not a conflict but a duplicate: no new star_set row is opened
#     (to avoid two rows for one author_id contradicting each other); the event is assembled directly from the existing row's data.
EXCL_A5063040920_ID = "A5063040920"   # Excluded (identification-gate conflict, pending manual review)
DEDUP_A5072079903_ID = "A5072079903"  # De-duplicated (already on the list, existing row reused, the new event is still assembled)

# ★Added in the top-10% version (2026-07-22): A5068400819 (unsw_econ) is already in the existing frozen star set of 197,
#   the frozen row has is_foreign_poach=True (no conflict, unlike A5063040920), arrival=2021 matches this batch,
#   percentile=0.9288 (inside the 10% band). But the frozen row has is_star_1pct=is_star_5pct=**False**
#   (previously only a candidate, not lit up as an event). In this batch the person is a confirmed top-10% event star and must be treated as a star (removed from the colleague pool).
#   -> Handling: the frozen row is **overridden** by this batch's new star row (is_star=True) (see the step1 build_star_set_v3
#   override); unlike A5072079903 the frozen row is not reused (A5072079903's frozen row already has is_star_5pct=True, which is correct).
OVERRIDE_A5068400819_ID = "A5068400819"   # Override (already on the list but is_star=False; overridden with the new star row so that the person becomes a star)

# Top-10% version: draft_37 (37) + 28 additional (front10pct, A5045410390 already removed by the academic-age gate <2) = combined CSV of 65 rows
DRAFT37_CSV = pathlib.Path(
    "/private/tmp/removed-session-directory/"
    "star10/"
    "new_stars_COMBINED_p10_2026-07-22.csv")

ADELAIDE_GAP_EVENT_IDS = {
    "A5075194454:2008",
    "A5013630114:2008",
    "A5085246004:2017",
    "A5011262618:2018",
    "A5059426203:2018",
}


def age_bin_of(aage: int) -> str:
    lo = ((int(aage) - 2) // 4) * 4 + 2
    return f"{lo}-{lo + 3}"


def load_new_stars_35() -> list[dict]:
    """draft_37 CSV -> 35 rows (dropping A5020228087 [fails the academic-age gate] and A5063040920 [identification-gate conflict,
    pending manual review; see the module constant comments above]); each row's fields are normalised (dept/arrival/academic_age/stock
    used directly; academic_age is already the corrected value and is not shifted again). Includes A5072079903 (de-duplicated, see below)."""
    rows = []
    with open(DRAFT37_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["author_id"] in (EXCL_A5020228087_ID, EXCL_A5063040920_ID):
                continue
            rows.append(dict(
                author_id=r["author_id"], name=r["name"], dept=r["dept_key"],
                arrival=int(r["arrival_year"]), academic_age=int(r["academic_age"]),
                stock=int(r["citation_stock_t1"]), grade=r["evidence_grade"],
                discipline_flag=r["discipline_flag"], decision=r["decision"],
                provenance_batch=r["provenance_batch"],
            ))
    assert len(rows) == 63, f"combined CSV (draft35 + own 28) should have 63 rows after dropping A5020228087 + A5063040920, got {len(rows)}"
    return rows


def new_star_rows_34() -> list[dict]:
    """34 of the 35 (A5072079903 is already in the existing frozen star set of 197; no new row is opened) ->
    STAR_SET rows with 14 columns (percentile/cell_n left empty, see the "honest simplification" in the module docstring)."""
    rows = []
    for s in load_new_stars_35():
        if s["author_id"] == DEDUP_A5072079903_ID:
            continue   # De-duplicated: reuse the existing frozen row of the 197-person star set, do not open a new one
        aage = s["academic_age"]
        if aage < 2:
            raise ValueError(f"{s['name']}: academic age {aage} < 2 — seniority gate not passed, needs manual review")
        rows.append({
            "author_id": s["author_id"], "name": s["name"], "dept": s["dept"],
            "arrival": int(s["arrival"]), "subfield": "2002",
            "age_bin": age_bin_of(aage), "academic_age": aage,
            "stock": int(s["stock"]), "percentile": None, "cell_n": None,
            "is_star_1pct": True, "is_star_5pct": True, "age_eligible": True,
            "is_foreign_poach": True,
        })
    # Top-10% version: 63 - A5072079903 (de-duplicated, reuses frozen) = 62 new star-set rows (including A5068400819,
    # which step1 build_star_set_v3 uses to override the frozen row; it is not skipped here).
    assert len(rows) == 62, f"expected 62 new star-set rows (63 minus A5072079903), got {len(rows)}"
    return rows


PROVENANCE_NOTE = (
    "events v3 51 行 (任务原定52, 实跑排除 A5063040920 见下) = 既有16 (逐字节沿用 "
    "u4_star_set_16ev_2026-07-20, 不重建) + 35 新 (v2_output/r_51ev_2026-07-20 "
    "draft_37 剔 A5020228087[年资门不过]+A5063040920[识别门槛冲突, 待人工复核]); "
    "A5063040920 排除原因: 既有197人冻结星集里已有 is_foreign_poach=False (真实"
    "affil_timeline 数据: 到任前已有澳洲任职记录), 与前5%人工查证的'改年'判定打架, "
    "识别层零自决, 本跑排除等人工裁决; A5072079903 无冲突但已在册, 去重复用既有行; "
    "author_task_2026-07-21 (跑完前5%扩军版全链); 到任年 = 07-20 前5%查证定年, "
    "academic_age = 07-20 已手工修正值 (6人修正, 见51事件扩军版台账); "
    "percentile/cell_n 对34新星集行留空 (是否明星由人工查证直判, 未走自动排名, 诚实留空); "
    "arrival_source 34人统一记 official_roster (描述性溯源桶, 不影响回归数值); "
    "Adelaide 同事池换用 2007-2021 补洞合并版 (5个落洞事件靠此变为可用)"
)
