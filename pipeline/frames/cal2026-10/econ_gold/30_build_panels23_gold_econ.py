#!/usr/bin/env python3
# cal2026-10 econ_gold clone of pipeline/frames/multidisc_gold_2026-08-10/code/30_build_panels23_gold.py
# (verbatim pin 453b0f7da4d878b51d37ff5fe6a22003e7e16168a5319ef5549a750a90c381c9).
# Repo-authored, 2026-09-22. The ONLY changes are field/path wiring so the same machine accepts
# economics: `--field econ` is admitted, the person map for economics is the U2 11-school map
# (the multidisc seeds map holds no economics author), and the signed-star set read for the
# ex-star exclusion is the field's own signed table. Every computation line is byte-identical to
# the pinned original; the exact hunks are listed in DIFF.md next to this file. Economics inputs
# are staged by run_econ_gold.py at the gold layout's fnfix names inside a private shadow of the
# legacy tree (the 2026-08-28 caliber staging mechanism, frames_stage.py), so no other path line
# had to move. Assumptions of the economics run are written in run_econ_gold.py's docstring.
"""20_build_panels23_multidisc.py — chemistry/maths-stats panel 2 (first link with a star) + panel 3 (colleague-pair interconnection)

Ported from the economics original frame_dept_2026-07-31/10_build_panels23.py (v9-corrected, read-only).
Every rule is copied; only the input sources and the event_id form change:

  Economics                            -> Multidisc
  event_id = star:arrival_year         -> event_id = star:school (arrival year looked up in the event
                                          ledger; arrival_corrected empty -> falls back to the 07-24
                                          ledger, same COALESCE as 10_build_frame_multidisc.py)
  person_map u2_..._11school           -> person_map_multidisc_seeds.parquet
  u1_full_11school edges ∪ sup133/11   -> u1_edges_full_2026-07-05 edges ∪
                                          edges_supplement_multidisc_stars.jsonl
  pid has a P_ prefix                  -> no prefix (canon not found = itself)

Rules (aligned item by item with economics v9):
  Panel 2 becoming: one row = person x star x year; y = the year the two first co-author (work level:
    over common works take max(the two persons' years), then min); exit once they have co-authored;
    **risk-set exclusion = ft < arrival − PRE** (not ft < arrival, which produces a spurious result);
    canonical same-person self-pairs dropped; window τ ∈ [−6, +10].
  Panel 3 pairs: one row = pair of people in the event population x year; canonical dedup (for each
    canonical take the lexicographically smallest bare id as representative), drop the event's star,
    unit = pair x event;
    y_any = first-link year after dropping papers co-signed by the event star; y_raw = not dropped;
    exit at min(ft, ft_ex); the same ft < arrival − PRE risk-set exclusion; same window.

Scope:
  Maths tiers = panel 2 + panel 3 both fully built (pairs parquet + slim)
  Chemistry tiers = panel 2 fully built + panel 3 only down to pairs_slim (four integer columns
            grp/year/y/D), streamed to parquet+csv with DuckDB COPY; never load the whole table into
            memory, never run regressions locally.
  The cleaning tier --roster-clean supports none / r1r2r3 / r1v2 (r1v2: R1 share rule >=25%, R2 as
  before, no R3 — the upstream 10_build_frame already writes a relationships table per tier).

Baseline-rate audit (hard check against spurious results): for each tier and each panel, if the number
of first links in the pre-arrival window is exactly 0 -> exit 4 immediately.

Run: python3 20_build_panels23_multidisc.py --field math_stats --roster-clean none
     (maths first, then chemistry; --panel3 full|slim|none, default chosen by field: maths full / chemistry slim)
"""
import argparse, glob, json, os, sys, time

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
V2 = os.path.dirname(BASE)
SSD = str(_sar_rd(_sar_derived_root() / "u1_edges_full_2026-07-05"))
MD24 = f"{ROOT}/v2_output/multidisc_2026-07-24/data"

ap = argparse.ArgumentParser()
ap.add_argument("--field", required=True, choices=["chemistry", "math_stats", "econ"])
ap.add_argument("--roster-clean", default="none", choices=["none", "r1r2r3", "r1v2"])
ap.add_argument("--panel3", default="auto", choices=["auto", "full", "slim", "none"])
args = ap.parse_args()
FIELD, CLEAN = args.field, args.roster_clean
if FIELD == "econ":   # cal2026-10 econ_gold wiring (see header): U2 person map (set after PMAP below)
    _ECON_PMAP = str(_sar_derived_root() / "u2_person_map_11school_2026-07-16/person_map/data.parquet")
SUF = "" if CLEAN == "none" else f"_{CLEAN}"     # Read the relationships table of the matching cleaning tier
P3MODE = args.panel3 if args.panel3 != "auto" else ("slim" if FIELD == "chemistry" else "full")

VAR = os.environ.get("GOLDVAR", "inc")
FRAME_DIR = f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/{VAR}/union_frame_{FIELD}"
REL = f"{FRAME_DIR}/relationships{SUF}.csv"
_LSUF = {"ev20": ("ev20", "ev20base"), "noA5044701593": ("noA5044701593", "noA5044701593base"), "final": ("final", "finalbase"), "fnfix": ("fnfix", "fnfixbase")}.get(VAR, ("gold", "base"))
LEDGER = f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/events_{FIELD}_{_LSUF[0]}_2026-08-10.csv"
LEDGER_BASE = f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/events_{FIELD}_{_LSUF[1]}_2026-08-10.csv"
PMAP = f"{ROOT}/v2_output/multidisc_v2_2026-08-04/data/person_map_multidisc_seeds.parquet"
if FIELD == "econ":
    PMAP = _ECON_PMAP   # cal2026-10 econ_gold wiring
U1E = f"{SSD}/authorship_edges/**/*.parquet"
SUP = f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/edges_supplement_{VAR}.jsonl" if os.path.exists(f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/edges_supplement_{VAR}.jsonl") else f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/edges_supplement_gold.jsonl"   # Use the variant's own supplementary edges if it has any (fnfix variant)
OUT = _sar_staged(f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/{VAR}/panels23_{FIELD}_gold")
TMP = _sar_staged(f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/_duck_tmp")
os.makedirs(OUT, exist_ok=True); os.makedirs(TMP, exist_ok=True)

PRE, POST = 6, 10
T0 = time.time()
def log(*a):
    print(f"[{time.time()-T0:7.1f}s]", *a, flush=True)

con = duckdb.connect()
con.execute("SET memory_limit='8GB'")
con.execute("PRAGMA threads=8")
con.execute(f"SET temp_directory='{TMP}'")
con.execute("SET preserve_insertion_order=false")

report = {"field": FIELD, "roster_clean_variant": CLEAN, "panel3_mode": P3MODE,
          "window": {"PRE": PRE, "POST": POST},
          "caliber": "econ v9 10_build_panels23.py 逐条移植 (risk-set drop = ft < arrival-PRE)",
          "inputs": {"relationships": REL, "ledger_signed": LEDGER,
                     "ledger_base_fallback": LEDGER_BASE, "person_map": PMAP,
                     "edges": U1E, "star_supplement": SUP}}

# ---------- 1. Event ledger -> arrival year ----------
ev = con.execute(f"""
    SELECT v.author_id AS star, v.school,
           COALESCE(TRY_CAST(v.arrival_corrected AS INTEGER), b.arrival_year) AS arrival,
           (TRY_CAST(v.arrival_corrected AS INTEGER) IS NULL) AS used_fallback,
           v.author_id || ':' || v.school AS event_id
    FROM read_csv_auto('{LEDGER}') v
    LEFT JOIN read_csv_auto('{LEDGER_BASE}') b
      ON b.event_id = v.author_id || ':' || v.school
    WHERE v.field = '{FIELD}'""").df()
if ev.arrival.isna().any():
    log("STOP arrival year NULL:", ev[ev.arrival.isna()].event_id.tolist()); sys.exit(3)
ev["arrival"] = ev.arrival.astype(int)

rel = pd.read_csv(REL)
miss_ev = sorted(set(rel.event_id) - set(ev.event_id))
if miss_ev:
    log("STOP relationship-table event not in the event ledger:", miss_ev); sys.exit(3)
ev = ev[ev.event_id.isin(set(rel.event_id))].reset_index(drop=True)
con.register("ev_df", ev[["event_id", "star", "arrival"]])
con.execute("CREATE TABLE ev AS SELECT * FROM ev_df")
con.register("rel_df", rel)
con.execute("CREATE TABLE rel AS SELECT pid, event_id, channel FROM rel_df")
report["population"] = {"rel_rows": len(rel), "persons": int(rel.pid.nunique()),
                        "events": int(rel.event_id.nunique()),
                        "arrival_fallback_events": int(ev.used_fallback.sum())}
log("population:", report["population"])

# ---------- 2. canonical + alias closure ----------
bares = sorted(set(rel.pid) | set(ev.star))
con.execute("CREATE TEMP TABLE cb AS SELECT * FROM (VALUES %s) t(bare)"
            % ",".join(f"('{p}')" for p in bares))
con.execute(f"""CREATE TABLE canon AS
    SELECT n.bare, COALESCE(m.person_id, n.bare) AS cid
    FROM cb n LEFT JOIN read_parquet('{PMAP}') m ON m.author_id = n.bare""")
con.execute(f"""CREATE TABLE al AS
    WITH c AS (SELECT n.bare, m.person_id FROM cb n
               JOIN read_parquet('{PMAP}') m ON m.author_id = n.bare)
    SELECT DISTINCT c.bare, m2.author_id FROM c
    JOIN read_parquet('{PMAP}') m2 USING (person_id)
    UNION
    SELECT n.bare, n.bare FROM cb n""")
report["alias"] = {"bares": len(bares),
                   "alias_rows": con.execute("SELECT count(*) FROM al").fetchone()[0],
                   "bares_mapped_to_person_map": con.execute(
                       "SELECT count(*) FROM canon WHERE cid <> bare").fetchone()[0],
                   "canonical_collapse_pairs": con.execute(
                       "SELECT count(*) FROM (SELECT cid FROM canon GROUP BY 1 HAVING count(*)>1)"
                   ).fetchone()[0]}
log("aliases:", report["alias"])

# ---------- 3. Work set wk(pid, work_id, yr): SSD edge table (aliases folded) ∪ star supplement ----------
con.execute(f"""CREATE TABLE wk_ssd AS
    SELECT a.bare AS pid, e.work_id, min(e.publication_year) AS yr
    FROM read_parquet('{U1E}', hive_partitioning=0) e
    JOIN al a ON e.author_id = a.author_id
    WHERE e.publication_year IS NOT NULL
    GROUP BY 1,2""")
# Star supplement: as in the economics original, exact match on the bare id (seed_author ∪ authors)
bare_set = set(bares)
sup_rows, sup_alias_only = [], 0
alias_to_bare = dict(con.execute("SELECT author_id, bare FROM al").fetchall())
for line in open(SUP):
    d = json.loads(line)
    yr = d.get("publication_year")
    if yr is None:
        continue
    cand = set(d.get("authors") or []) | {d.get("seed_author")}
    for a in cand:
        if a in bare_set:
            sup_rows.append((a, d["work_id"], int(yr)))
        elif a in alias_to_bare:           # Only matches under the alias convention — logged only, not added to the table
            sup_alias_only += 1
sup = pd.DataFrame(sup_rows, columns=["pid", "work_id", "yr"]).drop_duplicates(["pid", "work_id"])
con.register("sup_df", sup)
con.execute("""CREATE TABLE wk AS
    SELECT pid, work_id, min(yr) AS yr FROM (
      SELECT pid, work_id, yr FROM wk_ssd
      UNION ALL SELECT pid, work_id, CAST(yr AS BIGINT) FROM sup_df)
    GROUP BY 1,2""")
con.execute("CREATE INDEX wk_pid ON wk(pid)")
report["works"] = {
    "rows_ssd": con.execute("SELECT count(*) FROM wk_ssd").fetchone()[0],
    "rows_supplement_bare_match": len(sup),
    "supplement_alias_only_NOT_added": sup_alias_only,
    "rows_union": con.execute("SELECT count(*) FROM wk").fetchone()[0],
    "persons_with_works": con.execute("SELECT count(DISTINCT pid) FROM wk").fetchone()[0]}
stars_no_works = con.execute(
    "SELECT star FROM ev WHERE star NOT IN (SELECT pid FROM wk)").df().star.tolist()
report["works"]["stars_without_any_work"] = stars_no_works
log("works:", report["works"])

# Event-star works (used to drop the star in panel 3 and for the first link in panel 2)
con.execute("""CREATE TABLE sw AS
    SELECT e.event_id, w.work_id, w.yr FROM ev e JOIN wk w ON w.pid = e.star""")

# ---------- 4. Panel 2: person x star x year ----------
con.execute("""CREATE TABLE p2ft AS
    SELECT r.pid, r.event_id, min(greatest(m.yr, s.yr)) AS ft
    FROM rel r
    JOIN sw s ON s.event_id = r.event_id
    JOIN wk m ON m.pid = r.pid AND m.work_id = s.work_id
    GROUP BY 1,2""")
con.execute("""CREATE TABLE p2base AS
    SELECT r.pid, e.star, r.event_id, r.channel, e.arrival, f.ft,
           (c1.cid = c2.cid) AS is_self
    FROM rel r JOIN ev e USING (event_id)
    LEFT JOIN p2ft f ON f.pid = r.pid AND f.event_id = r.event_id
    JOIN canon c1 ON c1.bare = r.pid
    JOIN canon c2 ON c2.bare = e.star""")
self2 = con.execute("SELECT count(*) FROM p2base WHERE is_self").fetchone()[0]
being2 = con.execute(f"SELECT count(*) FROM p2base WHERE NOT is_self AND ft IS NOT NULL"
                     f" AND ft < arrival - {PRE}").fetchone()[0]
con.execute(f"""CREATE TABLE p2 AS
    WITH k AS (
      SELECT *, CASE WHEN ft IS NOT NULL AND ft <= arrival + {POST}
                     THEN ft - arrival ELSE {POST} END AS end_tau
      FROM p2base
      WHERE NOT is_self AND (ft IS NULL OR ft >= arrival - {PRE}))
    SELECT k.pid, k.star, k.event_id, k.channel, k.arrival + t.tau AS year, t.tau,
           CAST(t.tau >= 0 AS INTEGER) AS post,
           CAST(k.ft IS NOT NULL AND k.arrival + t.tau = k.ft AS INTEGER) AS y
    FROM k, UNNEST(generate_series(-{PRE}, k.end_tau)) AS t(tau)""")
p2s = con.execute("""SELECT count(*) AS n_rows, count(DISTINCT pid || '@' || event_id) AS rels,
    sum(y) AS n_ties, sum(CASE WHEN post=0 THEN y ELSE 0 END) AS n_ties_pre,
    sum(CASE WHEN post=1 THEN y ELSE 0 END) AS n_ties_post,
    count(DISTINCT event_id) AS n_events, count(DISTINCT pid) AS n_persons FROM p2""").df().iloc[0]
# Self-check: no rows after the first link / at most one y=1 per relationship
bad_tail = con.execute("""SELECT count(*) FROM p2 JOIN
    (SELECT pid, event_id, min(year) ty FROM p2 WHERE y=1 GROUP BY 1,2) v
    USING (pid, event_id) WHERE p2.year > v.ty""").fetchone()[0]
bad_multi = con.execute("""SELECT count(*) FROM
    (SELECT pid, event_id FROM p2 WHERE y=1 GROUP BY 1,2 HAVING count(*)>1)""").fetchone()[0]
assert bad_tail == 0, f"panel 2: {bad_tail} rows remain after the first tie"
assert bad_multi == 0, f"panel 2: {bad_multi} relationships have more than one y=1"
report["panel2"] = {"rows": int(p2s.n_rows), "relationships": int(p2s.rels),
                    "persons": int(p2s.n_persons), "events": int(p2s.n_events),
                    "first_ties": int(p2s.n_ties), "first_ties_pre_arrival": int(p2s.n_ties_pre),
                    "first_ties_post_arrival": int(p2s.n_ties_post),
                    "risk_set_drops": {"being_pre_window_cowrite(ft<arrival-6)": int(being2),
                                       "self_canonical": int(self2)},
                    "self_check": {"rows_after_first_tie": int(bad_tail),
                                   "rels_with_multiple_ties": int(bad_multi)}}
p2_path = f"{OUT}/becoming_{CLEAN}.csv"
con.execute(f"COPY (SELECT * FROM p2 ORDER BY event_id, pid, year) TO '{p2_path}' (HEADER, DELIMITER ',')")
report["panel2"]["file"] = p2_path
report["panel2"]["file_bytes"] = os.path.getsize(p2_path)
log("panel 2:", report["panel2"])

# ---------- 5. Panel 3: pairs within an event x year ----------
if P3MODE != "none":
    con.execute("""CREATE TABLE mem AS
        SELECT r.event_id, c.cid, min(r.pid) AS rep
        FROM rel r JOIN canon c ON c.bare = r.pid
        JOIN ev e ON e.event_id = r.event_id
        JOIN canon cs ON cs.bare = e.star
        WHERE c.cid <> cs.cid
        GROUP BY 1,2""")
    memstat = con.execute("SELECT count(*) AS n, count(DISTINCT event_id) AS n_ev FROM mem").df().iloc[0]
    con.execute("""CREATE TABLE memw AS
        SELECT m.event_id, m.rep AS pid, w.work_id, w.yr
        FROM mem m JOIN wk w ON w.pid = m.rep""")
    log("mem rows =", int(memstat.n), " memw rows =",
        con.execute("SELECT count(*) FROM memw").fetchone()[0])
    # Pairs with common works (only pairs that really co-authored are computed; other pairs have y always 0 and a full window)
    con.execute("""CREATE TABLE sp AS
        SELECT a.event_id, a.pid AS i_id, b.pid AS j_id,
               min(greatest(a.yr, b.yr)) AS ft,
               min(CASE WHEN s.work_id IS NULL THEN greatest(a.yr, b.yr) END) AS ft_ex
        FROM memw a
        JOIN memw b ON b.event_id = a.event_id AND b.work_id = a.work_id AND b.pid > a.pid
        LEFT JOIN sw s ON s.event_id = a.event_id AND s.work_id = a.work_id
        GROUP BY 1,2,3""")
    log("co-authored pairs =", con.execute("SELECT count(*) FROM sp").fetchone()[0])
    con.execute("""CREATE TABLE prs AS
        SELECT a.event_id, a.rep AS i_id, b.rep AS j_id, e.arrival, s.ft, s.ft_ex
        FROM mem a JOIN mem b ON b.event_id = a.event_id AND b.rep > a.rep
        JOIN ev e ON e.event_id = a.event_id
        LEFT JOIN sp s ON s.event_id = a.event_id AND s.i_id = a.rep AND s.j_id = b.rep""")
    pairs_all = con.execute("SELECT count(*) FROM prs").fetchone()[0]
    being3 = con.execute(f"SELECT count(*) FROM prs WHERE ft IS NOT NULL"
                         f" AND ft < arrival - {PRE}").fetchone()[0]
    con.execute(f"""CREATE TABLE prs2 AS
        SELECT row_number() OVER (ORDER BY event_id, i_id, j_id) AS grp, *,
               CASE WHEN stop IS NOT NULL AND stop <= arrival + {POST}
                    THEN stop - arrival ELSE {POST} END AS end_tau
        FROM (SELECT *, CASE WHEN ft IS NULL AND ft_ex IS NULL THEN NULL
                             ELSE least(COALESCE(ft, 999999), COALESCE(ft_ex, 999999)) END AS stop
              FROM prs WHERE ft IS NULL OR ft >= arrival - {PRE})""")
    pairs_kept = con.execute("SELECT count(*) FROM prs2").fetchone()[0]
    log(f"pairs: all {pairs_all} / dropped (already co-authored before window entry) {being3} / in risk set {pairs_kept}")

    slim_sql = f"""
        SELECT CAST(p.grp AS INTEGER) AS grp,
               CAST(p.arrival + t.tau AS INTEGER) AS year,
               CAST(CASE WHEN p.ft_ex IS NOT NULL AND p.arrival + t.tau = p.ft_ex
                         THEN 1 ELSE 0 END AS INTEGER) AS y,
               CAST(CASE WHEN t.tau >= 0 THEN 1 ELSE 0 END AS INTEGER) AS D
        FROM prs2 p, UNNEST(generate_series(-{PRE}, p.end_tau)) AS t(tau)"""
    slim_pq = f"{OUT}/pairs_slim_{CLEAN}.parquet"
    slim_csv = f"{OUT}/pairs_slim_{CLEAN}.csv"
    con.execute(f"COPY ({slim_sql}) TO '{slim_pq}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    log("slim parquet written →", slim_pq)
    con.execute(f"COPY ({slim_sql}) TO '{slim_csv}' (HEADER, DELIMITER ',')")
    log("slim csv written →", slim_csv)
    s = con.execute(f"""SELECT count(*) AS n_rows, count(DISTINCT grp) AS grps, sum(y) AS n_ties,
        sum(CASE WHEN D=0 THEN y ELSE 0 END) AS n_ties_pre,
        sum(CASE WHEN D=1 THEN y ELSE 0 END) AS n_ties_post
        FROM read_parquet('{slim_pq}')""").df().iloc[0]
    report["panel3"] = {
        "mode": P3MODE, "rows": int(s.n_rows), "pairs": int(s.grps),
        "events": int(con.execute("SELECT count(DISTINCT event_id) FROM prs2").fetchone()[0]),
        "members_total_event_person": int(memstat.n),
        "pairs_before_risk_set_drop": int(pairs_all),
        "risk_set_drops": {"being_pre_window_cowrite(ft<arrival-6)": int(being3)},
        "first_ties_ex_star": int(s.n_ties),
        "first_ties_ex_star_pre_arrival": int(s.n_ties_pre),
        "first_ties_ex_star_post_arrival": int(s.n_ties_post),
        "files": {"pairs_slim_parquet": slim_pq, "pairs_slim_csv": slim_csv},
        "file_bytes": {"pairs_slim_parquet": os.path.getsize(slim_pq),
                       "pairs_slim_csv": os.path.getsize(slim_csv)}}
    if P3MODE == "full":
        full_sql = f"""
            SELECT p.i_id, p.j_id, p.event_id, p.arrival + t.tau AS year, t.tau,
                   CAST(t.tau >= 0 AS INTEGER) AS post,
                   CAST(p.ft_ex IS NOT NULL AND p.arrival + t.tau = p.ft_ex AS INTEGER) AS y_any,
                   CAST(p.ft IS NOT NULL AND p.arrival + t.tau = p.ft AS INTEGER) AS y_raw
            FROM prs2 p, UNNEST(generate_series(-{PRE}, p.end_tau)) AS t(tau)"""
        full_pq = f"{OUT}/pairs_{CLEAN}.parquet"
        full_csv = f"{OUT}/pairs_{CLEAN}.csv"
        con.execute(f"COPY ({full_sql}) TO '{full_pq}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        con.execute(f"COPY ({full_sql}) TO '{full_csv}' (HEADER, DELIMITER ',')")
        f = con.execute(f"""SELECT count(*) AS n_rows, sum(y_raw) AS traw,
            sum(CASE WHEN post=0 THEN y_raw ELSE 0 END) AS traw_pre,
            sum(CASE WHEN post=1 THEN y_raw ELSE 0 END) AS traw_post
            FROM read_parquet('{full_pq}')""").df().iloc[0]
        # Self-check: no rows after the first link
        tail3 = con.execute(f"""SELECT count(*) FROM read_parquet('{full_pq}') a JOIN
            (SELECT i_id, j_id, event_id, min(year) ty FROM read_parquet('{full_pq}')
             WHERE y_any=1 GROUP BY 1,2,3) v USING (i_id, j_id, event_id)
            WHERE a.year > v.ty""").fetchone()[0]
        assert tail3 == 0, f"panel 3: {tail3} rows remain after the first tie (star excluded)"
        report["panel3"].update({
            "first_ties_raw": int(f.traw), "first_ties_raw_pre_arrival": int(f.traw_pre),
            "first_ties_raw_post_arrival": int(f.traw_post),
            "self_check_rows_after_first_tie": int(tail3)})
        report["panel3"]["files"].update({"pairs_parquet": full_pq, "pairs_csv": full_csv})
        report["panel3"]["file_bytes"].update({
            "pairs_parquet": os.path.getsize(full_pq),
            "pairs_csv": os.path.getsize(full_csv)})
    log("panel 3:", {k: v for k, v in report["panel3"].items() if k != "files"})

# ---------- 6. Baseline-rate audit (hard check against spurious results) ----------
audit = {"panel2_pre_arrival_first_ties": report["panel2"]["first_ties_pre_arrival"]}
fails = []
if audit["panel2_pre_arrival_first_ties"] == 0:
    fails.append("panel2 到任前窗口首连数 = 0（机械清零信号）")
if "panel3" in report:
    audit["panel3_pre_arrival_first_ties_ex_star"] = \
        report["panel3"]["first_ties_ex_star_pre_arrival"]
    if audit["panel3_pre_arrival_first_ties_ex_star"] == 0:
        fails.append("panel3 到任前窗口首连数(剔星) = 0（机械清零信号）")
audit["verdict"] = "PASS" if not fails else "FAIL"
audit["failures"] = fails
report["baseline_rate_audit"] = audit

rp = f"{OUT}/panels23_report{'' if CLEAN == 'none' else '_' + CLEAN}.json"
json.dump(report, open(rp, "w"), indent=1, default=str, ensure_ascii=False)
report["report_file"] = rp
print(json.dumps(report, indent=1, default=str, ensure_ascii=False))
if fails:
    log("base-rate check FAIL:", fails); sys.exit(4)
log("DONE →", OUT)
