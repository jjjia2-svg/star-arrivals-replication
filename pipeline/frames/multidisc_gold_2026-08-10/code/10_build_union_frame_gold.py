#!/usr/bin/env python3
"""10_build_frame_multidisc.py — chemistry/maths department-exposure output frame (ported from the economics v9 rules)

Base: frame_dept_2026-07-31/00_build_frame.py (the economics original, read-only).
Changes: 8 input substitutions + 2 code-block rewrites:
  A. Star exclusion ex_star = stars_excluded_multidisc ∪ event-ledger stars ∪ person_map alias closure;
     output y is read straight from the SSD works table (works already has an fwci column,
     so cited_by_count is not rebuilt)
  B. Star first-publication year = works_robust (identity.first_pub.robust_first_pub, GAP=10)
     Star edge source = SSD pedges ∪ star supplement jsonl (same merge as prodlib 07-24, so old
     and new rows of one event agree)

Rules (as in economics v9):
  population = roster members in post at arrival (year_start<=arrival<=year_end) ∪ relationships of
        the 07-24 network frame (that frame is the "2-hop pre-arrival co-authorship network of the
        star" — prodlib build_pairs deg1+deg2, SSD edge table frozen at t-1)
  person_map folds to canonical to prevent self-pairs / gate 4: a star is not counted as on the roster
  before arrival (Yves Zenou type) / alias dedup / dose_topic frozen at arrival-1 / y=fwci_frac
  (U6 R7 missing-value rule) / year window ±5 / age-gap guard: drop if |gap|>60 (applies only to the
  newly added dept_only relationships — old-frame rows are kept byte for byte; old-frame |gap|>60 is
  only logged for manual review, never dropped)

Roster cleaning --roster-clean {none, r1r2r3, r1v2} (default none):
  r1r2r3 (old tier, mode rule, behaviour kept as is for comparison):
    R1 drop people whose papers in the arrival window (±5) have a main subfield (modal subfield
       prefix) outside this field (chemistry=16 / maths-stats=26)
       — no window papers to judge from -> keep and log; mode tied and includes this field's prefix -> keep
    R2 drop suspected students/postdocs whose robust first-publication year is <3 years before the
       start of employment at the school (earliest year_start)
       — no first-publication year to judge from -> keep and log
    R3 end of employment = min(roster end year, year of last paper affiliated with the school + 1)
       (works_affil direct match on SCHOOL_INST, same source as the roster build; SSD has no
       "main affiliation" flag -> any affiliation is used, to be checked manually)
       — no paper affiliated with the school -> no truncation, and log
  r1v2 (the stricter and more reasonable tier):
    R1 share rule: keep if the share of window (±5) papers with this field's subfield prefix is
       >=25% (drop if <25%)
       — no window papers to judge from -> keep and log
    R2 unchanged; **no R3** (it measurably never changed anything, so it was removed; no year-segment patching)
  Cleaning acts on the roster (dept) channel only; 07-24 network-frame rows are still kept byte for byte.

Gold gates (any FAIL -> main frame not written, exit 2):
  G-ROW(=G-ANCHOR)  >=95% of the 07-24 network-frame relationships are found in the new frame
                    (each missing one listed with its reason)
  G-SUM  row-count identity total = old_rows + 11×new_rel
  funnel table funnel.json (candidates -> each exclusion step with reason and row count -> population)
Advisory checks (non-blocking, written to the report for manual review):
  G-DOSE recompute dose for 200 sampled old relationships and reconcile / G-VAL reconcile the
  values of 8 columns for 40 sampled both-channel relationships

Run: python3 10_build_frame_multidisc.py --field math_stats [--roster-clean r1r2r3|r1v2]
     (maths first, then chemistry; each cleaning tier writes its own frame, with file-name suffix
     _r1r2r3 / _r1v2)
"""
import argparse, csv as _csv, glob, json, math, os, random, sys

import duckdb
import pandas as pd

# --- M3 port: repo path resolution (legacy hard-coded the author's machine) — config/paths.yaml ---
import pathlib as _sar_pl, sys as _sar_sys
_sar_repo = next(p for p in _sar_pl.Path(__file__).resolve().parents if p.name == "frames").parents[1]
if str(_sar_repo) not in _sar_sys.path:
    _sar_sys.path.append(str(_sar_repo))
from pipeline.lib.paths import (derived_root as _sar_derived_root,  # noqa: E402,F401
                                snapshot_root as _sar_snapshot_root,
                                ssd_root as _sar_ssd_root,
                                legacy_thesis as _sar_legacy_thesis,
                                require_readable as _sar_rd,
                                require_writable as _sar_rw,
                                output_target as _sar_out,
                                deferred_output_target as _sar_lazyout,
                                staged_run_dir as _sar_staged)
ROOT = str(_sar_rd(_sar_legacy_thesis()))
BASE = os.path.dirname(os.path.abspath(__file__))
V2 = os.path.dirname(BASE)                       # multidisc_v2_2026-08-04
SSD = str(_sar_rd(_sar_derived_root() / "u1_edges_full_2026-07-05"))
MD24 = f"{ROOT}/v2_output/multidisc_2026-07-24/data"
PROD24 = f"{ROOT}/v2_output/multidisc_prod_2026-07-24/runs"

ap = argparse.ArgumentParser()
ap.add_argument("--field", required=True, choices=["chemistry", "math_stats"])
ap.add_argument("--roster-clean", default="none", choices=["none", "r1r2r3", "r1v2"])
args = ap.parse_args()
FIELD = args.field
CLEAN = args.roster_clean != "none"              # Enabled for either cleaning tier (r1r2r3 / r1v2)
R3_ON = args.roster_clean == "r1r2r3"            # r1v2 has no R3
R1_SHARE = args.roster_clean == "r1v2"           # r1v2: R1 = share rule (>=25%); r1r2r3: mode rule
SUF = "" if args.roster_clean == "none" else f"_{args.roster_clean}"   # Output-file suffix per cleaning tier (frames are written separately)

VAR = os.environ.get("GOLDVAR", "inc")
OLD_FRAME = f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/runs/{VAR}/{FIELD}/data/analysis_frame_p01_52ev_topicdose_2026-07-21.csv"
ROSTER = f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/{VAR}/roster_gold_{FIELD}.parquet"
_LSUF = {"ev20": ("ev20", "ev20base"), "noA5044701593": ("noA5044701593", "noA5044701593base"), "final": ("final", "finalbase"), "fnfix": ("fnfix", "fnfixbase")}.get(VAR, ("gold", "base"))
LEDGER = f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/events_{FIELD}_{_LSUF[0]}_2026-08-10.csv"
LEDGER_BASE = f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/events_{FIELD}_{_LSUF[1]}_2026-08-10.csv"
STARS_EXCL = f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/stars_excluded_{VAR}.parquet" if os.path.exists(f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/stars_excluded_{VAR}.parquet") else f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/stars_excluded_gold.parquet"   # Use the variant's own star-exclusion set if it has one (fnfix variant)
PMAP = f"{ROOT}/v2_output/multidisc_v2_2026-08-04/data/person_map_multidisc_seeds.parquet"
U1E = f"{SSD}/authorship_edges/**/*.parquet"
U1W = f"{SSD}/works/**/*.parquet"
U1WA = f"{SSD}/works_affil/**/*.parquet"
SUP = f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/edges_supplement_{VAR}.jsonl" if os.path.exists(f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/edges_supplement_{VAR}.jsonl") else f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/edges_supplement_gold.jsonl"   # Use the variant's own supplementary edges if it has any (fnfix variant)
OUT_DIR = _sar_staged(f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/{VAR}/union_frame_{FIELD}")
os.makedirs(OUT_DIR, exist_ok=True)

sys.path.insert(0, f"{ROOT}/multiplex_pipeline/units/u0_foundation/src")
sys.path.insert(0, f"{ROOT}/v2_output/multidisc_2026-07-24/code")
from identity import dose as identity_dose        # noqa: E402
from identity.first_pub import robust_first_pub   # noqa: E402
from common._redlines import RED                  # noqa: E402
from roster_lib import SCHOOL_INST, FIELD_PREFIX  # noqa: E402  constants shared with the roster build; not copied

W = 5
FP_GAP = int(RED["academic_age"]["robust_first_pub_max_gap"])   # =10 (fixed threshold)
AGE_GAP_MAX = 60
R2_MIN_YEARS = 3                                  # R2: first publication <3 years before the start of employment -> suspected student/postdoc
R1V2_SHARE_MIN = 0.25                             # r1v2 R1: keep if the share of this field's prefix is >=25%
FRAME_COLS = ["incumbent_person_id", "year", "star_person_id", "event_id", "treated",
              "post", "dose_coupling_baseline", "dose_topic", "dose_low_confidence",
              "age_gap", "fwci_frac", "pub_count", "fwci_frac_ex_star",
              "pub_count_ex_star", "fwci_mean", "fwci_mean_ex_star"]

con = duckdb.connect()
con.execute("SET memory_limit='8GB'")
con.execute("PRAGMA threads=8")
os.makedirs(f"{BASE}/../data/_duck_tmp", exist_ok=True)
con.execute(f"SET temp_directory='{BASE}/../data/_duck_tmp'")
canon_sf = lambda s: str(s).rsplit("/", 1)[-1]
report = {"caliber": f"dept-exposure multidisc {FIELD} (econ v9 移植) GOLD 2026-08-10",
          "roster_clean_variant": args.roster_clean,
          "fp_gap": FP_GAP, "age_gap_guard_max": AGE_GAP_MAX,
          "caliber_notes": [
              "老帧(07-24 网络帧)行逐字节保留=network/both 通道；新行=dept_only",
              "y 用 SSD works.fwci 现成列（老帧当年是 cited_by_count+基线重算——G-VAL 抽查对账）",
              "|gap|>60 护栏只剔新增 dept_only 关系；老帧超标关系记账不剔（人工决定）",
              "星本人只剔自身事件（econ v9 同款）；其他星可当同事，计数见 funnel",
              "arrival_corrected 空 = 维持 07-24 台账年（prodlib COALESCE 同规则）",
              "名册清洗只作用于 dept 通道；network 通道（老帧）不受清洗影响"]}
funnel = {"field": FIELD, "roster_clean_variant": args.roster_clean, "stages": []}
def stage(name, n, note=""):
    funnel["stages"].append({"stage": name, "n": int(n), "note": note})
    print(f"[funnel] {name}: {n} {note}", flush=True)

# ============ 1. Event ledger (event table; an empty arrival year falls back to the 07-24 ledger) ============
ev = con.execute(f"""
    SELECT v.author_id AS star, v.school,
           COALESCE(TRY_CAST(v.arrival_corrected AS INTEGER), b.arrival_year) AS arrival,
           (TRY_CAST(v.arrival_corrected AS INTEGER) IS NULL) AS used_fallback,
           v.author_id || ':' || v.school AS event_id
    FROM read_csv_auto('{LEDGER}') v
    LEFT JOIN read_csv_auto('{LEDGER_BASE}') b
      ON b.event_id = v.author_id || ':' || v.school
    WHERE v.field = '{FIELD}'
    ORDER BY v.school, v.author_id""").df()
if ev.arrival.isna().any():
    bad = ev[ev.arrival.isna()][["event_id"]].values.tolist()
    print(f"STOP: event arrival year is NULL (empty in the arrival table and the event ledger has no such event): {bad}", flush=True)
    sys.exit(3)
ev["arrival"] = ev.arrival.astype(int)
arrival_by_event = dict(zip(ev.event_id, ev.arrival))
star_by_event = dict(zip(ev.event_id, ev.star))
school_of_event = lambda e: e.rsplit(":", 1)[1]
report["events"] = {"n_events": len(ev),
                    "n_arrival_fallback_to_0724_ledger": int(ev.used_fallback.sum()),
                    "fallback_events": ev[ev.used_fallback].event_id.tolist()}
stage("signed_events", len(ev), f"到任年回落07-24台账 {int(ev.used_fallback.sum())} 起")

# ============ 2. Old frame (07-24 network frame) = network-channel anchor ============
with open(OLD_FRAME, newline="") as fin:
    hdr = next(_csv.reader([fin.readline()]))
assert hdr == FRAME_COLS, f"old frame column order mismatch: {hdr}"
old = pd.read_csv(OLD_FRAME)
old["pid"] = old.incumbent_person_id                 # the multidisc old frame has no P_ prefix
old_rel = set(map(tuple, old[["pid", "event_id"]].drop_duplicates().values))
stage("network_old_rel(07-24帧关系)", len(old_rel),
      f"{old.incumbent_person_id.nunique()}人/{old.event_id.nunique()}事件")
# Anchor consistency: old-frame events must be a subset of the ledger, and the arrival year implied by the window must equal the ledger arrival year (otherwise keeping the rows verbatim would be wrong)
old_arr = old.groupby("event_id")["year"].min().add(W).to_dict()
orphan = [e for e in old_arr if e not in arrival_by_event]
arr_mismatch = [(e, old_arr[e], arrival_by_event[e]) for e in old_arr
                if e in arrival_by_event and old_arr[e] != arrival_by_event[e]]
if orphan or arr_mismatch:
    print(f"STOP: old-frame anchors inconsistent orphan_events={orphan} arrival_mismatch={arr_mismatch}",
          flush=True)
    sys.exit(3)
report["anchor_check"] = {"old_events_all_in_ledger": True, "arrival_all_match": True}

# ============ 3. dept channel: roster members in post x events ============
con.execute(f"CREATE TEMP TABLE ev_t AS SELECT * FROM (VALUES %s) t(event_id, star, school, arrival)"
            % ",".join(f"('{r.event_id}','{r.star}','{r.school}',{r.arrival})"
                       for r in ev.itertuples()))
raw_n = con.execute(f"""
    SELECT count(*) FROM (
      SELECT DISTINCT r.author_id, e.event_id
      FROM read_parquet('{ROSTER}') r
      JOIN ev_t e ON r.school = e.school
                 AND e.arrival BETWEEN r.year_start AND r.year_end)""").fetchone()[0]
dept = con.execute(f"""
    SELECT DISTINCT r.author_id pid, e.event_id, e.star, e.arrival
    FROM read_parquet('{ROSTER}') r
    JOIN ev_t e ON r.school = e.school
               AND e.arrival BETWEEN r.year_start AND r.year_end
    WHERE r.author_id <> e.star""").df()
dept_rel = set(map(tuple, dept[["pid", "event_id"]].values))
stage("dept_candidates_raw(在职×事件)", raw_n)
stage("drop_self_star_authorid", raw_n - len(dept_rel), "author_id==本事件星")
stage("dept_rel_after_selfstar", len(dept_rel))

# ============ 3b. dose / first-publication-year prerequisites (R1/R2 cleaning and the later dose step share one SSD scan) ============
stars = sorted(set(star_by_event.values()))
need_persons = sorted({p for p, _ in dept_rel | old_rel} | set(stars))
con.execute("CREATE TEMP TABLE needp AS SELECT * FROM (VALUES %s) t(bare)"
            % ",".join(f"('{p}')" for p in need_persons))
alias = con.execute(f"""
    WITH canon AS (
        SELECT n.bare, m.person_id
        FROM needp n JOIN read_parquet('{PMAP}') m ON m.author_id = n.bare)
    SELECT c.bare AS person_id, m2.author_id
    FROM canon c JOIN read_parquet('{PMAP}') m2 ON m2.person_id = c.person_id""").df()
mapped = set(alias.person_id)
alias = pd.concat([alias, pd.DataFrame({"person_id": [p for p in need_persons if p not in mapped],
                                        "author_id": [p for p in need_persons if p not in mapped]})],
                  ignore_index=True)
report["alias"] = {"persons": int(alias.person_id.nunique()), "author_rows": len(alias),
                   "mapped_persons": len(mapped),
                   "selfrows_unmapped": len(need_persons) - len(mapped),
                   "multi_alias_persons": int((alias.groupby("person_id").size() > 1).sum())}
con.register("alias_df", alias)
# DISTINCT (pid,work) grain = same as the prodlib 07-24 anchor (the SSD edge table is already unique on (work,author))
pedges = con.execute(f"""
    SELECT DISTINCT a.person_id pid, e.publication_year yr, w.subfield_id sf, e.work_id
    FROM read_parquet('{U1E}', hive_partitioning=0) e
    JOIN alias_df a ON e.author_id = a.author_id
    JOIN read_parquet('{U1W}', hive_partitioning=0) w ON e.work_id = w.work_id
    WHERE e.publication_year IS NOT NULL""").df()
# Star supplement jsonl: merged with pedges on the star side (same as prodlib, so old and new rows of the same event agree);
# the non-star side has no supplement rows (every seed_author is a star)
sup_rows = []
star_set_l = set(stars)
for l in open(SUP):
    d = json.loads(l)
    if d["seed_author"] in star_set_l:
        sup_rows.append({"pid": d["seed_author"], "work_id": d["work_id"],
                         "yr": d.get("publication_year"), "sf": None})
sup_df = pd.DataFrame(sup_rows, columns=["pid", "work_id", "yr", "sf"])
if len(sup_df):
    sup_df = sup_df.drop_duplicates(["pid", "work_id"])
    have = pedges.groupby("pid").work_id.apply(set).to_dict()
    sup_df = sup_df[[w not in have.get(p, ()) for p, w in zip(sup_df.pid, sup_df.work_id)]]
    need_sf = sup_df.work_id.unique().tolist()
    if need_sf:
        con.execute("CREATE TEMP TABLE nsf AS SELECT * FROM (VALUES %s) t(w)"
                    % ",".join(f"('{w}')" for w in need_sf))
        u1sf = con.execute(f"""SELECT w.work_id, w.subfield_id, w.publication_year
            FROM read_parquet('{U1W}', hive_partitioning=0) w JOIN nsf ON w.work_id = nsf.w""").df()
        m2 = dict(zip(u1sf.work_id, u1sf.subfield_id))
        y2 = dict(zip(u1sf.work_id, u1sf.publication_year))
        sup_df["sf"] = [m2.get(w) for w in sup_df.work_id]
        sup_df["yr"] = [y if pd.notna(y) else y2.get(w)
                        for y, w in zip(sup_df.yr, sup_df.work_id)]
report["sup_merge"] = {"star_extra_works_from_supplement": len(sup_df)}
dose_src = pd.concat([pedges[["pid", "yr", "sf"]], sup_df[["pid", "yr", "sf"]]],
                     ignore_index=True)
dose_by = {p: g for p, g in dose_src.groupby("pid")}
report["dose_src"] = {"persons": len(dose_by), "rows": len(dose_src)}
# robust first-publication year (works_robust GAP=10) — shared by R2 and the age-gap guard
years_by_pid = {p: sorted(set(int(y) for y in g_.yr.dropna()))
                for p, g_ in dose_src.groupby("pid")}
pf = {p: robust_first_pub(ys, max_leading_gap=FP_GAP)
      for p, ys in years_by_pid.items() if ys}

# ============ 3c. Roster cleaning (r1r2r3 = R1 mode -> R2 -> R3; r1v2 = R1 share >=25% -> R2, no R3; touches the dept channel only) ============
roster_df = con.execute(
    f"SELECT author_id, school, year_start, year_end FROM read_parquet('{ROSTER}')").df()
spells_ps = {}                                   # (author, school) -> [(ys, ye), ...] original roster
for r in roster_df.itertuples():
    spells_ps.setdefault((r.author_id, r.school), []).append(
        (int(r.year_start), int(r.year_end)))
last_home = {}                                   # (pid, school) -> year of the last paper affiliated with the school (computed for r1r2r3 only)
if CLEAN:
    prefix = FIELD_PREFIX[FIELD]
    # ---- R1: r1r2r3 = mode rule (modal subfield prefix in the window != this field -> drop);
    #          r1v2 = share rule (share of this field's prefix in the window <25% -> drop, >=25% keep) ----
    r1_drop, r1_nojudge = [], 0
    for pid, evid in sorted(dept_rel):
        arr = arrival_by_event[evid]
        counts = {}
        g_ = dose_by.get(pid)
        if g_ is not None:
            s_ = g_[(g_.yr.notna()) & (g_.yr >= arr - W) & (g_.yr <= arr + W) & g_.sf.notna()]
            for x in s_.sf:
                k = canon_sf(x)
                if len(k) == 4 and k.isdigit():
                    counts[k[:2]] = counts.get(k[:2], 0) + 1
        if not counts:
            r1_nojudge += 1; continue            # no window papers to judge from -> keep and log
        if R1_SHARE:
            if counts.get(prefix, 0) / sum(counts.values()) < R1V2_SHARE_MIN:
                r1_drop.append((pid, evid,
                                max(counts, key=lambda k: counts[k]), counts.get(prefix, 0)))
        elif counts.get(prefix, 0) < max(counts.values()):
            r1_drop.append((pid, evid,
                            max(counts, key=lambda k: counts[k]), counts.get(prefix, 0)))
    dept_rel -= {(p, e) for p, e, *_ in r1_drop}
    stage("R1_drop_wrong_subfield", len(r1_drop),
          (f"窗口±{W}内{prefix}前缀占比<{R1V2_SHARE_MIN:.0%}(占比法)" if R1_SHARE else
           f"窗口±{W}内众数subfield前缀≠{prefix}") +
          f"；无窗口论文可判保留 {r1_nojudge} 人次" +
          ("" if R1_SHARE else f"；并列含{prefix}保留"))
    # ---- R2: robust first-publication year <3 years before the start of employment at the school -> suspected student/postdoc, drop ----
    emp_start = {ps: min(ys for ys, _ in sp) for ps, sp in spells_ps.items()}
    r2_drop, r2_nofp = [], 0
    for pid, evid in sorted(dept_rel):
        fp1 = pf.get(pid)
        if fp1 is None:
            r2_nofp += 1; continue               # no first-publication year to judge from -> keep and log
        es = emp_start.get((pid, school_of_event(evid)))
        if es is not None and es - fp1 < R2_MIN_YEARS:
            r2_drop.append((pid, evid, es, fp1))
    dept_rel -= {(p, e) for p, e, *_ in r2_drop}
    stage("R2_drop_earlycareer", len(r2_drop),
          f"该校最早year_start−robust首发年<{R2_MIN_YEARS}；无首发年可判保留 {r2_nofp} 人次")
    # ---- R3: end of employment = min(roster end year, year of last paper affiliated with the school + 1) -> drop if the arrival year falls outside
    #          (r1r2r3 only; r1v2 has no R3 because it never removed anyone, so it was deleted) ----
    if R3_ON:
        con.register("cand_alias", alias[alias.person_id.isin({p for p, _ in dept_rel})])
        inst_case = " ".join(f"WHEN wa.institution_id = '{iid}' THEN '{sch}'"
                             for sch, iid in SCHOOL_INST.items())
        inst_ids = ", ".join(f"'{iid}'" for iid in SCHOOL_INST.values())
        lh_df = con.execute(f"""
            SELECT a.person_id pid, CASE {inst_case} END school,
                   max(w.publication_year) last_home
            FROM read_parquet('{U1WA}', hive_partitioning=0) wa
            JOIN cand_alias a ON wa.author_id = a.author_id
            JOIN read_parquet('{U1W}', hive_partitioning=0) w ON wa.work_id = w.work_id
            WHERE wa.institution_id IN ({inst_ids}) AND w.publication_year IS NOT NULL
            GROUP BY 1, 2""").df()
        last_home = {(r.pid, r.school): int(r.last_home) for r in lh_df.itertuples()}
        r3_drop, r3_nohome = [], set()
        for pid, evid in sorted(dept_rel):
            sch, arr = school_of_event(evid), arrival_by_event[evid]
            lh = last_home.get((pid, sch))
            if lh is None:
                r3_nohome.add((pid, sch)); continue   # no paper affiliated with the school -> no truncation, and log
            if not any(ys <= arr <= min(ye, lh + 1)
                       for ys, ye in spells_ps.get((pid, sch), [])):
                r3_drop.append((pid, evid, lh))
        dept_rel -= {(p, e) for p, e, _ in r3_drop}
        stage("R3_drop_spell_truncated", len(r3_drop),
              f"到任年>min(名册终年,最后本校论文年+1)；无本校论文不截 {len(r3_nohome)} 人·校")
    stage("dept_rel_after_clean", len(dept_rel))
    report["roster_clean"] = {
        "variant": args.roster_clean,
        "R1": {"dropped": len(r1_drop), "unjudgeable_kept": r1_nojudge,
               "rule": (f"share of subfield prefix '{prefix}' in [arrival-{W},arrival+{W}]"
                        f" < {R1V2_SHARE_MIN} → drop（占比法，2026-08-06 人工签）"
                        if R1_SHARE else
                        f"modal subfield prefix in [arrival-{W},arrival+{W}] != '{prefix}'"
                        "（并列含本学科前缀=保留；口径解释待人工复核）"),
               "examples_pid_event_modalprefix_nfield": [list(map(str, x)) for x in r1_drop[:12]]},
        "R2": {"dropped": len(r2_drop), "no_first_pub_kept": r2_nofp,
               "rule": f"min(year_start@school) - robust_first_pub < {R2_MIN_YEARS}",
               "examples_pid_event_start_fp": [list(map(str, x)) for x in r2_drop[:12]]},
        "R3": ({"dropped": len(r3_drop),
                "no_home_paper_person_school_untruncated": len(r3_nohome),
                "rule": "arrival > min(year_end, last_home_affil_paper_year+1) 对该校全部 spell"
                        "（works_affil 直配 SCHOOL_INST 任一挂名，无主挂标记）",
                "examples_pid_event_lasthome": [list(map(str, x)) for x in r3_drop[:12]]}
               if R3_ON else
               {"disabled": True,
                "rule": "r1v2 无 R3（2026-08-06 人工签：实测结构性空转 0 人被修，删除；"
                        "年段拖尾作为已量化测量误差写进论文限制节）"})}
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if not kk.startswith("examples")}
                      if isinstance(v, dict) else v
                      for k, v in report["roster_clean"].items()},
                     ensure_ascii=False), flush=True)

# ---- canonical folding (the common v9 fix for three defects; multidisc person_id has no P_ prefix) ----
_all_bare = sorted({p for p, _ in dept_rel} | {p for p, _ in old_rel} |
                   set(star_by_event.values()))
con.execute("CREATE TEMP TABLE cb AS SELECT * FROM (VALUES %s) t(bare)"
            % ",".join(f"('{p}')" for p in _all_bare))
_cn = con.execute(f"""SELECT n.bare, m.person_id FROM cb n
    JOIN read_parquet('{PMAP}') m ON m.author_id = n.bare""").df()
canon = dict(zip(_cn.bare, _cn.person_id))       # not found = itself (the bare id is canonical)
canon_of = lambda x: canon.get(x, x)
# Gate 4: a star is not counted as on the roster before their arrival (a star's roster spells before their own arrival year trim relationships only, not events)
star_arrival_by_canon = {}
for e_id, s in star_by_event.items():
    c = canon_of(s)
    star_arrival_by_canon[c] = min(arrival_by_event[e_id],
                                   star_arrival_by_canon.get(c, 9999))
drop_self, drop_prearrival = [], []
dept_rel_v9 = set()
for pid, evid in dept_rel:
    cp, cs = canon_of(pid), canon_of(star_by_event[evid])
    if cp == cs:
        drop_self.append((pid, evid)); continue
    if cp in star_arrival_by_canon and arrival_by_event[evid] < star_arrival_by_canon[cp]:
        drop_prearrival.append((pid, evid)); continue
    dept_rel_v9.add((pid, evid))
dept_rel = dept_rel_v9
stage("drop_self_alias_canon", len(drop_self), "canonical 同人别名自配对")
stage("drop_star_prearrival(门4)", len(drop_prearrival), "星自身到任前的在职spell裁关系")
# canonical-level dedup: the same canonical person already entered the same event in the old frame under another author_id
old_canon = {(canon_of(p), e) for p, e in old_rel}
alias_dup = {(p, e) for p, e in dept_rel
             if (p, e) not in old_rel and (canon_of(p), e) in old_canon}
both_rel = (dept_rel & old_rel) | {(p, e) for p, e in old_rel
                                   if (canon_of(p), e) in {(canon_of(q), f) for q, f in dept_rel}}
new_rel = dept_rel - old_rel - alias_dup
stage("drop_alias_dup", len(alias_dup), "canonical 已以别名进老帧同事件")
stage("dept_only_new_rel(护栏前)", len(new_rel))
report["relationships_pre_guard"] = {
    "dept": len(dept_rel), "network_old": len(old_rel), "both": len(both_rel),
    "dept_only_new": len(new_rel), "union": len(new_rel | old_rel),
    "v9_drop_self_alias": len(drop_self),
    "v9_drop_star_prearrival": len(drop_prearrival),
    "v9_drop_alias_dup": len(alias_dup),
    "v9_dropped_examples": {"self": drop_self[:3], "prearrival": drop_prearrival[:6],
                            "alias_dup": sorted(alias_dup)[:6]}}
print(report["relationships_pre_guard"], flush=True)

def topic_vec(pid, t1):
    g = dose_by.get(pid)
    if g is None:
        return None
    v = {}
    s = g[(g.yr.notna()) & (g.yr <= t1) & g.sf.notna()]
    for x in s.sf:
        k = canon_sf(x); v[k] = v.get(k, 0.0) + 1.0
    return v

def dose_topic(pid, star, arrival):
    vi, vs = topic_vec(pid, arrival - 1), topic_vec(star, arrival - 1)
    if vi is None or vs is None:
        return None
    return identity_dose.topic_cos(vi, vs)

# ---- G-DOSE advisory (recompute dose for 200 sampled old relationships and reconcile; non-blocking — folding differences are logged) ----
g = old[["pid", "event_id", "dose_topic"]].drop_duplicates(["pid", "event_id"])
g = g.sample(n=min(200, len(g)), random_state=42)
diffs, missing, worst = [], 0, []
for r in g.itertuples():
    d = dose_topic(r.pid, star_by_event[r.event_id], arrival_by_event[r.event_id])
    if d is None: missing += 1; continue
    dd = abs(d - r.dose_topic)
    diffs.append(dd)
    if dd > 1e-9: worst.append((r.pid, r.event_id, r.dose_topic, d))
gd = {"n": len(diffs), "missing_side": missing,
      "max_abs_diff": max(diffs) if diffs else None,
      "share_exact_1e-9": (sum(x < 1e-9 for x in diffs) / len(diffs)) if diffs else 0,
      "share_le_0.01": (sum(x <= 0.01 for x in diffs) / len(diffs)) if diffs else 0,
      "worst": [list(map(str, w)) for w in sorted(worst, key=lambda x: -abs(x[2] - x[3]))[:8]]}
report["G_DOSE_advisory"] = gd
print("G-DOSE(advisory)", {k: gd[k] for k in ("n", "missing_side", "max_abs_diff",
                                              "share_exact_1e-9", "share_le_0.01")}, flush=True)

# ============ 5. First-publication year -> age-gap guard ============
star_first = {}
for e_id, s in star_by_event.items():
    if s not in pf:
        print(f"STOP: event star {e_id} has no dated work (SSD ∪ supplement) — first-publication year cannot be computed", flush=True)
        sys.exit(3)
    star_first[e_id] = pf[s]
report["first_pub"] = {"persons_with_fp": len(pf),
                       "new_rel_persons_no_fp": len({p for p, _ in new_rel} - set(pf))}

def age_gap_of(pid, evid):
    sf1, pf1 = star_first.get(evid), pf.get(pid)
    return float(sf1 - pf1) if (sf1 is not None and pf1 is not None) else None

# Guard: drop if |gap|>60 (new relationships only; NA gap is kept and logged)
drop_gap, na_gap = [], 0
new_rel_kept = set()
for pid, evid in sorted(new_rel):
    ag = age_gap_of(pid, evid)
    if ag is None:
        na_gap += 1; new_rel_kept.add((pid, evid)); continue
    if abs(ag) > AGE_GAP_MAX:
        drop_gap.append((pid, evid, ag)); continue
    new_rel_kept.add((pid, evid))
new_rel = new_rel_kept
stage("drop_age_gap_gt60(新增关系)", len(drop_gap),
      f"例: {[(p, e, g_) for p, e, g_ in drop_gap[:4]]}")
stage("dept_only_new_rel_final", len(new_rel), f"其中 age_gap NA {na_gap} 条(保留)")
# Old-frame |gap|>60 is logged, not dropped (old rows are kept byte for byte; flagged for manual review)
old_gap_rel = old[old.age_gap.abs() > AGE_GAP_MAX][["pid", "event_id"]].drop_duplicates()
report["age_gap_guard"] = {
    "new_rel_dropped": len(drop_gap), "new_rel_na_gap_kept": na_gap,
    "old_frame_rel_gt60_NOT_dropped": int(len(old_gap_rel)),
    "dropped_examples": [list(map(str, x)) for x in drop_gap[:10]]}

# ============ 6. Output (fwci read directly from SSD works.fwci; block A) ============
signed_star_all = set()
for f_ in ("chemistry", "math_stats"):
    p_ = f"{BASE}/../data/events_{f_}_gold_2026-08-10.csv"
    signed_star_all |= set(pd.read_csv(p_).author_id)
excl_authors = {t[0] for t in con.execute(
    f"SELECT author_id FROM read_parquet('{STARS_EXCL}')").fetchall()} | signed_star_all
con.execute("CREATE TEMP TABLE exa AS SELECT * FROM (VALUES %s) t(a)"
            % ",".join(f"('{s}')" for s in sorted(excl_authors)))
ship_alias = {r[0] for r in con.execute(f"""
    WITH canon AS (SELECT DISTINCT m.person_id FROM read_parquet('{PMAP}') m
                   JOIN exa ON m.author_id = exa.a)
    SELECT m2.author_id FROM read_parquet('{PMAP}') m2
    JOIN canon USING (person_id)""").fetchall()} | excl_authors
report["ship_alias"] = {"n_star_authors_excl_list": len(excl_authors),
                        "n_after_alias_closure": len(ship_alias)}
random.seed(42)
sample_both = random.sample(sorted(both_rel), min(40, len(both_rel)))
need_outcomes = sorted({p for p, _ in new_rel} | {p for p, _ in sample_both})
py_by = {}
if need_outcomes:
    con.execute("CREATE TEMP TABLE needo AS SELECT * FROM (VALUES %s) t(bare)"
                % ",".join(f"('{p}')" for p in need_outcomes))
    con.execute("CREATE TEMP TABLE ship AS SELECT * FROM (VALUES %s) t(a)"
                % ",".join(f"('{s}')" for s in sorted(ship_alias)))
    oc = con.execute(f"""
        WITH tgt AS (SELECT a.person_id, a.author_id FROM alias_df a
                     JOIN needo n ON a.person_id = n.bare),
        own AS (SELECT DISTINCT t.person_id pid, e.work_id, e.publication_year yr
                FROM read_parquet('{U1E}', hive_partitioning=0) e
                JOIN tgt t ON e.author_id = t.author_id
                WHERE e.publication_year IS NOT NULL),
        wa AS (SELECT e.work_id, count(DISTINCT e.author_id) n_auth,
                      max(CASE WHEN s.a IS NOT NULL THEN 1 ELSE 0 END) has_star
               FROM read_parquet('{U1E}', hive_partitioning=0) e
               LEFT JOIN ship s ON e.author_id = s.a
               WHERE e.work_id IN (SELECT work_id FROM own) GROUP BY 1)
        SELECT own.pid, own.yr, w.fwci, wa.n_auth, wa.has_star
        FROM own JOIN read_parquet('{U1W}', hive_partitioning=0) w ON own.work_id = w.work_id
        JOIN wa ON own.work_id = wa.work_id""").df()
    acc_by = {}
    for r in oc.itertuples():
        a = acc_by.setdefault((r.pid, int(r.yr)), {"ff": 0.0, "ffx": 0.0, "pc": 0,
                                                   "pcx": 0, "f": [], "fx": []})
        a["pc"] += 1
        fc = 1.0 / max(int(r.n_auth), 1)
        if pd.notna(r.fwci):
            a["ff"] += fc * r.fwci; a["f"].append(r.fwci)
        if not bool(r.has_star):
            a["pcx"] += 1
            if pd.notna(r.fwci):
                a["ffx"] += fc * r.fwci; a["fx"].append(r.fwci)
    for (pid, y), a in acc_by.items():
        py_by[(pid, y)] = {"fwci_frac": a["ff"], "fwci_frac_ex_star": a["ffx"],
                           "pub_count": a["pc"], "pub_count_ex_star": a["pcx"],
                           "fwci_mean": sum(a["f"]) / len(a["f"]) if a["f"] else None,
                           "fwci_mean_ex_star": sum(a["fx"]) / len(a["fx"]) if a["fx"] else None}
    report["outcome_src"] = {"persons_needed": len(need_outcomes),
                             "unit_rows": len(oc),
                             "person_years": len(py_by)}
# in_post spell: tiers none/r1v2 = original roster (r1v2 has no R3, so no truncation); tier r1r2r3 = spells after R3 truncation (spells truncated away are dropped)
spells = {}
n_spell_trunc, n_spell_gone = 0, 0
for (a_id, sch), sps in spells_ps.items():
    for ys, ye in sps:
        ye_adj = ye
        if R3_ON:
            lh = last_home.get((a_id, sch))
            if lh is not None and lh + 1 < ye:
                ye_adj = lh + 1; n_spell_trunc += 1
        if ye_adj < ys:
            n_spell_gone += 1; continue
        spells.setdefault(a_id, []).append((ys, ye_adj))
if R3_ON:
    report["roster_clean"]["R3"]["in_post_spells_truncated"] = n_spell_trunc
    report["roster_clean"]["R3"]["in_post_spells_dropped"] = n_spell_gone
in_post = lambda p, y: any(a <= y <= b for a, b in spells.get(p, []))
n_new_star_like = len({p for p, _ in new_rel} & excl_authors)
report["diag_new_rel_persons_in_star_excl_list"] = n_new_star_like

# ============ 7. Build rows (econ v9 build_rows verbatim; U6 R7 backfill) ============
def build_rows(pid, event_id):
    rows = []
    star, arrival = star_by_event[event_id], arrival_by_event[event_id]
    d = dose_topic(pid, star, arrival)
    ag = age_gap_of(pid, event_id)
    for y in range(arrival - W, arrival + W + 1):
        pyr = py_by.get((pid, y))
        if pyr is not None:
            vals = dict(pyr)
            if (pd.notna(vals["pub_count"]) and vals["pub_count"] > 0
                    and vals["fwci_frac"] == 0.0 and pd.isna(vals["fwci_mean"])):
                vals["fwci_frac"] = None
            if (pd.notna(vals["pub_count_ex_star"]) and vals["pub_count_ex_star"] > 0
                    and vals["fwci_frac_ex_star"] == 0.0
                    and pd.isna(vals["fwci_mean_ex_star"])):
                vals["fwci_frac_ex_star"] = None
        elif in_post(pid, y):
            vals = {"fwci_frac": 0.0, "fwci_frac_ex_star": 0.0, "pub_count": 0,
                    "pub_count_ex_star": 0, "fwci_mean": None, "fwci_mean_ex_star": None}
        else:
            vals = {c: None for c in ["fwci_frac", "fwci_frac_ex_star", "pub_count",
                    "pub_count_ex_star", "fwci_mean", "fwci_mean_ex_star"]}
        rows.append({"incumbent_person_id": pid, "year": y,
                     "star_person_id": star, "event_id": event_id,
                     "treated": True, "post": y >= arrival,
                     "dose_coupling_baseline": None, "dose_topic": d,
                     "dose_low_confidence": False, "age_gap": ag, **vals})
    return rows

# ---- G-VAL advisory (reconcile 8 columns of sampled both-channel relationships, fresh vs old frame; non-blocking) ----
mism, dose_tol, fill_div = [], [], []
old_idx = old.set_index(["pid", "event_id", "year"]).sort_index()
for pid, evid in sample_both:
    for m in build_rows(pid, evid):
        try:
            o = old_idx.loc[(pid, evid, m["year"])]
        except KeyError:
            mism.append((pid, evid, m["year"], "row_missing_in_old")); continue
        for c in ["dose_topic", "age_gap", "fwci_frac", "pub_count",
                  "fwci_frac_ex_star", "pub_count_ex_star", "fwci_mean", "fwci_mean_ex_star"]:
            ov, mv = o[c], m[c]
            na_o = pd.isna(ov); na_m = mv is None or (isinstance(mv, float) and math.isnan(mv))
            if na_o and na_m: continue
            if na_o != na_m:
                fill_div.append((pid, evid, m["year"], c,
                                 "old_NA" if na_o else "old_val", ov, mv)); continue
            d_ = abs(float(ov) - float(mv))
            if d_ > max(1e-4, 1e-6 * abs(float(ov))):
                if c == "dose_topic" and d_ <= 0.01:
                    dose_tol.append((pid, evid, c, float(ov), float(mv)))
                else:
                    mism.append((pid, evid, m["year"], c, float(ov), float(mv)))
report["G_VAL_advisory"] = {"sampled_both": len(sample_both), "mismatches": len(mism),
                            "dose_tolerated_le_0.01": len(dose_tol),
                            "fill_divergence": len(fill_div),
                            "fill_examples": [list(map(str, x)) for x in fill_div[:8]],
                            "examples": [list(map(str, x)) for x in mism[:12]]}
print("G-VAL(advisory) mism =", len(mism), " dose_tol =", len(dose_tol),
      " fill_div =", len(fill_div), flush=True)

# ============ 8. Assemble + gold gates ============
new_rows = [pd.DataFrame(build_rows(pid, evid)) for pid, evid in sorted(new_rel)]
new_df = pd.concat(new_rows, ignore_index=True) if new_rows else pd.DataFrame(columns=FRAME_COLS)
new_df["channel"] = "dept_only"
frame_rel = new_rel | old_rel
# G-ROW(=G-ANCHOR): >=95% of the 07-24 frame relationships are found in the new frame (old rows are kept verbatim, so structurally 100%)
found = old_rel & frame_rel
g_row_share = len(found) / len(old_rel) if old_rel else 1.0
g_row_missing = [{"pid": p, "event_id": e, "reason": "not_in_final_rel_set"}
                 for p, e in sorted(old_rel - frame_rel)]
report["G_ROW"] = {"old_rel": len(old_rel), "found": len(found),
                   "share": g_row_share, "missing": g_row_missing}
# G-SUM: row-count identity
total_rows = len(old) + len(new_df)
g_sum_ok = (len(new_df) == len(new_rel) * (2 * W + 1)) and \
           (total_rows == len(old) + len(new_rel) * (2 * W + 1))
report["G_SUM"] = {"total": total_rows, "old_rows": len(old),
                   "new_rows": len(new_df), "new_rel_x11": len(new_rel) * 11,
                   "ok": g_sum_ok}
frame_persons = {p for p, _ in frame_rel}
frame_events = {e for _, e in frame_rel}
per_event = {}
for e_id in sorted(arrival_by_event):
    per_event[e_id] = {"network": sum(1 for p, x in old_rel if x == e_id),
                       "dept_only": sum(1 for p, x in new_rel if x == e_id),
                       "both": sum(1 for p, x in both_rel if x == e_id)}
zero_dept = [e for e, v in per_event.items() if v["dept_only"] + v["both"] == 0]
report["frame"] = {"rows": total_rows, "relationships": len(frame_rel),
                   "persons": len(frame_persons), "events": len(frame_events),
                   "by_channel": {"network": len(old_rel - both_rel),
                                  "both": len(both_rel), "dept_only": len(new_rel)},
                   "events_zero_dept_members": zero_dept,
                   "dose_null_new_rows": int(new_df.dose_topic.isna().sum()) if len(new_df) else 0,
                   "age_gap_null_new_rows": int(new_df.age_gap.isna().sum()) if len(new_df) else 0}
report["per_event"] = per_event
stage("union_rel_final", len(frame_rel),
      f"{len(frame_persons)}人/{len(frame_events)}事件")
stage("frame_rows", total_rows)
funnel["final"] = {"relationships": len(frame_rel), "persons": len(frame_persons),
                   "events": len(frame_events), "rows": total_rows,
                   "events_zero_dept_members": zero_dept}
gate = (g_row_share >= 0.95) and g_sum_ok
report["GATE"] = "PASS" if gate else "FAIL"
json.dump(report, open(f"{OUT_DIR}/build_report{SUF}.json", "w"),
          indent=1, default=str, ensure_ascii=False)
json.dump(funnel, open(f"{OUT_DIR}/funnel{SUF}.json", "w"),
          indent=1, default=str, ensure_ascii=False)
print(json.dumps({k: report[k] for k in ("G_ROW", "G_SUM", "frame", "GATE")
                  if k != "G_ROW" or not report["G_ROW"]["missing"]},
                 indent=1, default=str)[:3000], flush=True)
if not gate:
    print("gold threshold not met — main frame not written", flush=True)
    sys.exit(2)

# ---- Write: old-frame rows kept verbatim + channel appended; new rows serialised by pandas ----
out_path = f"{OUT_DIR}/analysis_frame_{FIELD}{SUF}_2026-08-10.csv"
with open(out_path, "w", newline="") as fout:
    fout.write(",".join(FRAME_COLS + ["channel"]) + "\n")
    with open(OLD_FRAME, newline="") as fin:
        fin.readline()
        for line in fin:
            line = line.rstrip("\n")
            cells = next(_csv.reader([line]))
            key = (cells[0], cells[3])
            ch = "both" if key in both_rel else "network"
            fout.write(line + "," + ch + "\n")
    if len(new_df):
        new_df.to_csv(fout, index=False, header=False, columns=FRAME_COLS + ["channel"])
pd.DataFrame([{"pid": p, "event_id": e,
               "channel": ("both" if (p, e) in both_rel else
                           "dept_only" if (p, e) in new_rel else "network")}
              for p, e in sorted(frame_rel)]).to_csv(
    f"{OUT_DIR}/relationships{SUF}.csv", index=False)
print("DONE →", out_path, flush=True)
