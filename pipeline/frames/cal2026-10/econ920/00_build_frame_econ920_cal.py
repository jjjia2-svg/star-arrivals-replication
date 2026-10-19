#!/usr/bin/env python3
# cal2026-10 econ920 clone of <legacy>/v2_output/econ_fnfix_2026-08-15/code/00_build_frame_econ920.py
# (the machine-generated clone the 2026-08-15 chain ran; verbatim pin 233485392b8e9ca7c17e3f5b72c7a66c347ef3b60aefdf81c50699f740dda4c3).
# Repo-authored 2026-09-22 by make_clone.py (textual substitution, hit counts asserted). The ONLY
# changes are path wiring: the inputs/outputs come from the JSON config named by sys.argv[1], the
# data-disk root and the legacy root resolve through pipeline.lib.paths. Every computation line is
# byte-identical to the pinned original; DIFF.md next to this file lists every changed line. The
# launcher (run_econ920.py) pre-imports identity.dose from this repository's ported units, so the
# original sys.path insert on the legacy units tree is inert. Public copy: three comment lines of the
# original carry reworded process wording (make_clone.WORDING_RX); no code line is affected.
#!/usr/bin/env python3
"""00_build_frame.py — department-exposure output frame (new population caliber: exposure at the department level) · v2

Caliber (original wording): when a star lands in this department, every incumbent of the department that year is switched to treated,
intensity = topic relatedness. At least the whole roster of incumbents; the co-authorship-network population is kept as a supplementary channel.

v2 fixes (the three root causes of the v1 gold-standard FAIL):
  1. dose vector source: person_map (11school 07-16) folds all author aliases -> u1 edge table
     (keeping the multiplicity of edge rows, same as U5 person_level_edges), no longer paper_contrib
  2. first-publication-year chain: U3 panel first_pub_year first + u1 work_first_pub as fallback + API min year for the supplemented people
  3. age_gap = star's first-publication year − the person's own first-publication year (direction of the identity.cohort.academic_age_gap interface)

Gold standards as in v1: G-DOSE >=95% bit for bit / G-ROW all 'both' relations equal / G-SUM row-count identity.
"""
import glob, json, math, os, random, sys

import duckdb
import pandas as pd

# --- cal2026-10 econ920 wiring (repo-authored; see the header and DIFF.md) --------------------------
import pathlib as _sar_pl, sys as _sar_sys
_sar_repo = next((p for p in _sar_pl.Path(__file__).resolve().parents
                  if (p / "pipeline" / "lib" / "paths.py").is_file()), None)
if _sar_repo is not None and str(_sar_repo) not in _sar_sys.path:
    _sar_sys.path.append(str(_sar_repo))
from pipeline.lib.paths import (derived_root as _sar_derived_root,  # noqa: E402
                                legacy_thesis as _sar_legacy_thesis,
                                require_readable as _sar_rd)
_CFG = json.load(open(_sar_sys.argv[1]))
ROOT = str(_sar_rd(_sar_legacy_thesis()))
BASE = os.path.dirname(os.path.abspath(__file__))
SSD = str(_sar_rd(_sar_derived_root()))
OLD_FRAME = _CFG["OLD_FRAME"]   # fnfix: the original 79 byte for byte + the prodlib rows of the new events (cal2026-10: the FILTERED network frame)
ROSTER = _CFG["ROSTER"]   # 2026-08-13: 920 people, verified gold roster (AWS rerun) (cal2026-10: the verified October roster, 1,008)
LEDGER = _CFG["LEDGER"]
OUT_TBL = f"{SSD}/u5_ship_11school_p10_80ev_2026-07-22/output/_frozen/output_star1pct.parquet"
STAR_SET = _CFG["STAR_SET"]   # fnfix: U4 frozen table ∪ synthesised / flipped-on rows for the stars recovered by the false-negative fix
PMAP = glob.glob(f"{SSD}/u2_person_map_11school_2026-07-16/person_map/**/*.parquet", recursive=True)
# ★The edge table anchored by the U5 p10 run = u1_full_11school_2026-07-16 (common80.py EDGES_SUB),
#   not u1_edges_full_2026-07-05 — the root cause of the v3 gold-standard FAIL
U1E = glob.glob(f"{SSD}/u1_full_11school_2026-07-16/authorship_edges/**/*.parquet", recursive=True)
U1W = glob.glob(f"{SSD}/u1_full_11school_2026-07-16/works/**/*.parquet", recursive=True)
U1FP = glob.glob(f"{SSD}/u1_full_11school_2026-07-16/work_first_pub/**/*.parquet", recursive=True)
U3P = f"{SSD}/u3_panel_11school_2026-07-16/panel/data.parquet"
SUP11 = _CFG["SUP11"]
PATCH_A = _CFG["PATCH_A"]   # 2026-08-13: old package + 4 new people added
PATCH_B = _CFG["PATCH_B"]

sys.path.insert(0, f"{ROOT}/multiplex_pipeline/units/u0_foundation/src")
from identity import dose as identity_dose  # noqa: E402

FRAME_COLS = ["incumbent_person_id", "year", "star_person_id", "event_id", "treated",
              "post", "dose_coupling_baseline", "dose_topic", "dose_low_confidence",
              "age_gap", "fwci_frac", "pub_count", "fwci_frac_ex_star",
              "pub_count_ex_star", "fwci_mean", "fwci_mean_ex_star"]
W = 5

con = duckdb.connect()
con.execute("PRAGMA threads=8")
strip = lambda x: x.replace("P_", "", 1)
canon_sf = lambda s: str(s).rsplit("/", 1)[-1]
report = {"caliber": "dept-exposure v2 2026-07-31"}

# ============ 1. Events + roster + relations of the old frame ============
old = pd.read_csv(OLD_FRAME)
old["pid"] = old.incumbent_person_id.map(strip)
old_rel = set(map(tuple, old[["pid", "event_id"]].drop_duplicates().values))
roster = con.execute(f"SELECT * FROM read_parquet('{ROSTER}')").df()
dept = con.execute(f"""
    SELECT DISTINCT r.author_id pid, e.event_id, e.star, e.arrival
    FROM read_parquet('{ROSTER}') r
    JOIN (SELECT event_id, school, CAST(split_part(event_id,':',2) AS INT) arrival,
                 split_part(event_id,':',1) star FROM read_csv_auto('{LEDGER}')) e
      ON r.school = e.school AND e.arrival BETWEEN r.year_start AND r.year_end
    WHERE r.author_id <> e.star""").df()
dept_rel = set(map(tuple, dept[["pid", "event_id"]].values))

# ---- v9: everything folded by canonical person (the single fix for the 3 alias defects found by the audit) ----
_all_bare = sorted({p for p, _ in dept_rel} | {p for p, _ in old_rel} |
                   {e.split(":")[0] for _, e in dept_rel | old_rel})
con.execute("CREATE TEMP TABLE cb AS SELECT * FROM (VALUES %s) t(bare)"
            % ",".join(f"('{p}')" for p in _all_bare))
_cn = con.execute(f"""SELECT n.bare, m.person_id FROM cb n
    JOIN read_parquet({PMAP!r}) m ON m.author_id = n.bare""").df()
canon = dict(zip(_cn.bare, _cn.person_id))          # bare -> P_canon; if not found = itself
canon_of = lambda x: canon.get(x, f"P_{x}")
# The star's own arrival year (gate 4: never in Australia before arrival -> the star cannot be an incumbent colleague before the star's own arrival)
star_arrival_by_canon = {}
for _, e in dept_rel | old_rel:
    s, a = e.split(":")[0], int(e.split(":")[1])
    c = canon_of(s)
    star_arrival_by_canon[c] = min(a, star_arrival_by_canon.get(c, 9999))
drop_self, drop_prearrival = [], []
dept_rel_v9 = set()
for pid, evid in dept_rel:
    star, arr = evid.split(":")[0], int(evid.split(":")[1])
    cp, cs = canon_of(pid), canon_of(star)
    if cp == cs:                                     # Audit defect 1: alias self-pairing
        drop_self.append((pid, evid)); continue
    if cp in star_arrival_by_canon and arr < star_arrival_by_canon[cp]:
        drop_prearrival.append((pid, evid)); continue  # Yves Zenou type: the star does not count as in post before arrival
    dept_rel_v9.add((pid, evid))
dept_rel = dept_rel_v9
# Audit defect 2: canonical-level duplicate check — the same canonical person already entered the same event in the old frame under another author_id
old_canon = {(canon_of(p), e) for p, e in old_rel}
alias_dup = {(p, e) for p, e in dept_rel
             if (p, e) not in old_rel and (canon_of(p), e) in old_canon}
both_rel = (dept_rel & old_rel) | {(p, e) for p, e in old_rel
                                   if (canon_of(p), e) in {(canon_of(q), f) for q, f in dept_rel}}
new_rel = dept_rel - old_rel - alias_dup
report["relationships"] = {"dept": len(dept_rel), "network_old": len(old_rel),
                           "both": len(both_rel), "dept_only_new": len(new_rel),
                           "union": len(new_rel | old_rel),
                           "v9_drop_self_alias": len(drop_self),
                           "v9_drop_star_prearrival": len(drop_prearrival),
                           "v9_drop_alias_dup": len(alias_dup),
                           "v9_dropped_examples": {"self": drop_self[:3],
                                                   "prearrival": drop_prearrival[:6],
                                                   "alias_dup": sorted(alias_dup)[:6]}}
print(report["relationships"], flush=True)

# ============ 2. dose side: person_map folds aliases -> u1 edges x works (multiplicity kept) ============
pa = pd.DataFrame([json.loads(l) for l in open(PATCH_A)]) if os.path.exists(PATCH_A) else pd.DataFrame()
patched_people = set(pa.author_id) if len(pa) else set()
stars = sorted({e.split(":")[0] for _, e in (dept_rel | old_rel)})
# ★v7: supplemented people are not excluded in advance — someone can be both a star and a colleague (dropped from paper_contrib, hence "missing data"),
#   yet u1_full_11school holds all of their edges. Everyone goes through pedges first; the API only covers those with truly no edges.
need_persons = sorted({p for p, _ in dept_rel | old_rel} | set(stars))
con.execute("CREATE TEMP TABLE needp AS SELECT * FROM (VALUES %s) t(bare)"
            % ",".join(f"('{p}')" for p in need_persons))
# Two-step alias resolution (person_map's person_id has the P_ prefix):
#   (1) look up the bare id as author_id -> canonical person_id (e.g. P_A5029151069)
#   (2) canonical person_id -> all author aliases of that person
# if the map has no entry (stray people outside the supplement) -> a singleton of itself
alias = con.execute(f"""
    WITH canon AS (
        SELECT n.bare, m.person_id
        FROM needp n JOIN read_parquet({PMAP!r}) m ON m.author_id = n.bare)
    SELECT c.bare AS person_id, m2.author_id
    FROM canon c JOIN read_parquet({PMAP!r}) m2 ON m2.person_id = c.person_id""").df()
mapped = set(alias.person_id)
alias = pd.concat([alias, pd.DataFrame({"person_id": [p for p in need_persons if p not in mapped],
                                        "author_id": [p for p in need_persons if p not in mapped]})],
                  ignore_index=True)
report["alias"] = {"persons": int(alias.person_id.nunique()),
                   "author_rows": len(alias),
                   "mapped_persons": len(mapped),
                   "selfrows_unmapped": len(need_persons) - len(mapped),
                   "multi_alias_persons": int((alias.groupby("person_id").size() > 1).sum())}
con.register("alias_df", alias)
# Edges (with multiplicity) x works subfield; the cutoff year is the **edge table's** publication_year (the U5 person_edges
# rows carry the edge-table year and the cutoff cuts by it; the works table supplies only subfield — root cause of the v4 tail difference)
pedges = con.execute(f"""
    SELECT a.person_id pid, e.publication_year yr, w.subfield_id sf, e.work_id
    FROM read_parquet({U1E!r}) e
    JOIN alias_df a ON e.author_id = a.author_id
    JOIN read_parquet({U1W!r}) w ON e.work_id = w.work_id
    WHERE e.publication_year IS NOT NULL""").df()
# stars11 supplemented stars: supplement list + metadata from (u1 works ∪ API)
meta_b = {}
if os.path.exists(PATCH_B):
    for l in open(PATCH_B):
        d = json.loads(l); meta_b[d["work_id"]] = d
sup_rows = []
SUP_FNFIX = _CFG["SUP_FNFIX"]
for l in (list(open(SUP11)) + list(open(SUP_FNFIX))):
    d = json.loads(l)
    m = meta_b.get(d["work_id"], {})
    sup_rows.append({"pid": d["seed_author"], "work_id": d["work_id"],
                     "yr": d.get("publication_year") or m.get("publication_year"),
                     "sf": m.get("subfield_id")})
sup_df = pd.DataFrame(sup_rows)
need_sf = sup_df[sup_df.sf.isna()].work_id.unique().tolist()
if need_sf:
    con.execute("CREATE TEMP TABLE nsf AS SELECT * FROM (VALUES %s) t(w)"
                % ",".join(f"('{w}')" for w in need_sf))
    u1sf = con.execute(f"""SELECT w.work_id, w.subfield_id, w.publication_year
        FROM read_parquet({U1W!r}) w JOIN nsf ON w.work_id = nsf.w""").df()
    m2 = dict(zip(u1sf.work_id, u1sf.subfield_id)); y2 = dict(zip(u1sf.work_id, u1sf.publication_year))
    sup_df["sf"] = sup_df.apply(lambda r: r.sf if pd.notna(r.sf) else m2.get(r.work_id), axis=1)
    sup_df["yr"] = sup_df.apply(lambda r: r.yr if pd.notna(r.yr) else y2.get(r.work_id), axis=1)
# Supplemented people (API)
if len(pa):
    pa_d = pa.rename(columns={"author_id": "pid", "publication_year": "yr",
                              "subfield_id": "sf"})[["pid", "work_id", "yr", "sf"]]
else:
    pa_d = pd.DataFrame(columns=["pid", "work_id", "yr", "sf"])
# Source priority (prevents double counting / path forks — the gold standard is anchored on pedges):
#   for a pid covered by pedges -> use pedges only; supplement/API only cover those with no pedges at all
pids_in_pedges = set(pedges.pid)
sup_only = sup_df[~sup_df.pid.isin(pids_in_pedges)][["pid", "yr", "sf"]]
pa_only = pa_d[~pa_d.pid.isin(pids_in_pedges)][["pid", "yr", "sf"]]
report["sup_fallback_stars"] = sorted(set(sup_only.pid))
report["api_only_pids"] = sorted(set(pa_only.pid))
dose_src = pd.concat([pedges[["pid", "yr", "sf"]],
                      sup_only,
                      pa_only], ignore_index=True)
dose_by = {p: g for p, g in dose_src.groupby("pid")}
report["dose_src"] = {"persons": len(dose_by), "rows": len(dose_src)}

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

# ---- G-DOSE ----
import csv as _csv0
_NEW_EV = {f"{r['author_id']}:{int(r['arrival'])}" for r in _csv0.DictReader(open(_CFG["NEW_EVENTS"]))}
g_all = old[["pid", "event_id", "dose_topic"]].drop_duplicates(["pid", "event_id"])
g_new = g_all[g_all.event_id.isin(_NEW_EV)].copy()
g = g_all[~g_all.event_id.isin(_NEW_EV)]
g = g.sample(n=min(200, len(g)), random_state=42)
g["arr"] = g.event_id.str.split(":").str[1].astype(int)
g["star"] = g.event_id.str.split(":").str[0]
diffs, missing = [], 0
worst = []
for r in g.itertuples():
    d = dose_topic(r.pid, r.star, r.arr)
    if d is None: missing += 1; continue
    dd = abs(d - r.dose_topic)
    diffs.append(dd)
    if dd > 1e-9: worst.append((r.pid, r.event_id, r.dose_topic, d))
gd = {"n": len(diffs), "missing_side": missing,
      "max_abs_diff": max(diffs) if diffs else None,
      "share_exact_1e-9": (sum(x < 1e-9 for x in diffs) / len(diffs)) if diffs else 0,
      "worst": [list(map(str, w)) for w in sorted(worst, key=lambda x: -abs(x[2] - x[3]))[:8]]}
report["G_DOSE"] = gd
# ---- G-DOSE-NEW (full reconciliation of the new events, advisory) ----
g_new["arr"] = g_new.event_id.str.split(":").str[1].astype(int); g_new["star"] = g_new.event_id.str.split(":").str[0]
_dn, _mn, _wn = [], 0, []
_dose_override = {}
for r in g_new.itertuples():
    d = dose_topic(r.pid, r.star, r.arr)
    if d is None or pd.isna(r.dose_topic): _mn += 1; continue
    dd = abs(d - r.dose_topic); _dn.append(dd)
    if dd > 1e-9: _wn.append((r.pid, r.event_id, r.dose_topic, d))
    _dose_override[(r.pid, r.event_id)] = d
report["G_DOSE_NEW"] = {"n": len(_dn), "missing_side": _mn, "max_abs_diff": max(_dn) if _dn else None,
    "share_exact_1e-9": (sum(x < 1e-9 for x in _dn) / len(_dn)) if _dn else None,
    "worst": [list(map(str, w)) for w in sorted(_wn, key=lambda x: -abs(x[2] - x[3]))[:8]]}
print("G-DOSE-NEW", {k: report["G_DOSE_NEW"][k] for k in ("n", "missing_side", "max_abs_diff", "share_exact_1e-9")}, flush=True)
# fnfix: the dose_topic of the new events' network rows is uniformly replaced by this script's recomputed value (design caliber = the star side's SSD edges ∪ the supplement edges; when prodlib ran econ the star vector did not contain the supplement's subfields),
# so the network rows and department rows of the same event use the same ruler; the original 79 are untouched. The number of overwrites is recorded in report["dose_override_new_rows"].
_ov_mask = old.event_id.isin(_NEW_EV)
_ov_vals = [ _dose_override.get((p_, e_)) for p_, e_ in zip(old.pid[_ov_mask], old.event_id[_ov_mask]) ]
_ov_ok = [v is not None for v in _ov_vals]
old.loc[_ov_mask, "dose_topic"] = [v if v is not None else o for v, o in zip(_ov_vals, old.loc[_ov_mask, "dose_topic"])]
report["dose_override_new_rows"] = {"rows": int(_ov_mask.sum()), "overridden": int(sum(_ov_ok)), "note": "prodlib dose → 00 重算 dose（含补数星边）"}
print("dose_override_new_rows", report["dose_override_new_rows"], flush=True)
print("G-DOSE", {k: gd[k] for k in ("n", "missing_side", "max_abs_diff", "share_exact_1e-9")}, flush=True)

# ============ 3. person-year output table (OUTPUT used directly + aggregation for the supplemented people) ============
out_py = con.execute(f"""SELECT regexp_replace(incumbent_person_id,'^P_','') pid, year,
    fwci_frac, fwci_frac_ex_star, pub_count, pub_count_ex_star, fwci_mean, fwci_mean_ex_star
    FROM read_parquet('{OUT_TBL}')""").df()
# People missing output = relation population − OUTPUT coverage (108 people: outside the paper_contrib pool)
need_outcomes = sorted(({p for p, _ in dept_rel | old_rel}) - set(out_py.pid))
report["need_outcomes"] = len(need_outcomes)
# All author aliases of the p01 ship stars (the ex_star exclusion set, as in U4: the star_set p01 flag folded through pm)
sp01 = [r[0] for r in con.execute(
    f"SELECT author_id FROM read_parquet('{STAR_SET}') WHERE is_star_1pct").fetchall()]
con.execute("CREATE TEMP TABLE sp01 AS SELECT * FROM (VALUES %s) t(a)"
            % ",".join(f"('{s}')" for s in sp01))
ship_alias = {r[0] for r in con.execute(f"""
    WITH canon AS (SELECT DISTINCT m.person_id FROM read_parquet({PMAP!r}) m
                   JOIN sp01 ON m.author_id = sp01.a)
    SELECT m2.author_id FROM read_parquet({PMAP!r}) m2
    JOIN canon USING (person_id)""").fetchall()} | set(sp01)
contrib = []   # (pid, yr, fwci, n_auth, isc)
# ★v9: for people outside the pool, output always takes the API first — the audit found that the u1 edge table is trimmed by seed and its per-paper author counts are incomplete,
#   which inflates frac_credit by ~2x; the API carries the true full author count of each paper. The u1 edge table only covers people the API lacks.
if need_outcomes:
    api_pids = set(pa.author_id) if len(pa) else set()
    for r in (pa[pa.author_id.isin(need_outcomes)].itertuples() if len(pa) else []):
        if pd.isna(r.publication_year): continue
        contrib.append((r.author_id, int(r.publication_year), r.fwci,
                        max(int(r.n_authors), 1),
                        bool(set(r.author_ids) & ship_alias)))
    leftover = sorted(set(need_outcomes) - api_pids)
    if leftover:
        con.execute("CREATE TEMP TABLE needo AS SELECT * FROM (VALUES %s) t(bare)"
                    % ",".join(f"('{p}')" for p in leftover))
        oc = con.execute(f"""
            WITH tgt AS (SELECT a.person_id, a.author_id FROM alias_df a
                         JOIN needo n ON a.person_id = n.bare),
            own AS (SELECT DISTINCT t.person_id pid, e.work_id, e.publication_year yr
                    FROM read_parquet({U1E!r}) e JOIN tgt t ON e.author_id = t.author_id
                    WHERE e.publication_year IS NOT NULL),
            wa AS (SELECT e.work_id, count(DISTINCT e.author_id) n_auth,
                          max(CASE WHEN s.a IS NOT NULL THEN 1 ELSE 0 END) has_star
                   FROM read_parquet({U1E!r}) e
                   LEFT JOIN (SELECT DISTINCT a FROM (VALUES %s) t(a)) s ON e.author_id = s.a
                   WHERE e.work_id IN (SELECT work_id FROM own) GROUP BY 1)
            SELECT own.pid, own.yr, w.fwci, wa.n_auth, wa.has_star
            FROM own JOIN read_parquet({U1W!r}) w ON own.work_id = w.work_id
            JOIN wa ON own.work_id = wa.work_id"""
            % ",".join(f"('{s}')" for s in sorted(ship_alias))).df()
        for r in oc.itertuples():
            contrib.append((r.pid, int(r.yr), r.fwci, int(r.n_auth), bool(r.has_star)))
        report["outcome_src"] = {"api_persons": len(api_pids & set(need_outcomes)),
                                 "edges_fallback_persons": len(set(oc.pid))}
    else:
        report["outcome_src"] = {"api_persons": len(api_pids & set(need_outcomes)),
                                 "edges_fallback_persons": 0}
if contrib:
    rows, acc_by = [], {}
    for pid, y, fw, na, isc in contrib:
        a = acc_by.setdefault((pid, y), {"ff": 0.0, "ffx": 0.0, "pc": 0, "pcx": 0,
                                         "f": [], "fx": []})
        a["pc"] += 1
        fc = 1.0 / na
        if pd.notna(fw):
            a["ff"] += fc * fw; a["f"].append(fw)
        if not isc:
            a["pcx"] += 1
            if pd.notna(fw):
                a["ffx"] += fc * fw; a["fx"].append(fw)
    for (pid, y), a in acc_by.items():
        rows.append({"pid": pid, "year": y, "fwci_frac": a["ff"],
                     "fwci_frac_ex_star": a["ffx"], "pub_count": a["pc"],
                     "pub_count_ex_star": a["pcx"],
                     "fwci_mean": sum(a["f"]) / len(a["f"]) if a["f"] else None,
                     "fwci_mean_ex_star": sum(a["fx"]) / len(a["fx"]) if a["fx"] else None})
    out_py = pd.concat([out_py, pd.DataFrame(rows)], ignore_index=True)
py_by = {(r.pid, int(r.year)): r for r in out_py.itertuples()}
spells = {}
for r in roster.itertuples():
    spells.setdefault(r.author_id, []).append((int(r.year_start), int(r.year_end)))
in_post = lambda p, y: any(a <= y <= b for a, b in spells.get(p, []))

# ============ 4. first-publication-year chain: U3 panel first + u1 work_first_pub fallback + API for the supplemented people ============
u3fp = con.execute(f"""SELECT DISTINCT regexp_replace(person_id,'^P_','') pid, first_pub_year
    FROM read_parquet('{U3P}') WHERE first_pub_year IS NOT NULL""").df()
pf = dict(zip(u3fp.pid, u3fp.first_pub_year.astype(int)))
need_fp = sorted(({p for p, _ in dept_rel | old_rel}) - set(pf))
if need_fp:
    con.execute("CREATE TEMP TABLE nfp AS SELECT * FROM (VALUES %s) t(a)"
                % ",".join(f"('{p}')" for p in need_fp))
    fb = con.execute(f"""SELECT author_id, first_pub_year FROM read_parquet({U1FP!r})
        JOIN nfp ON author_id = nfp.a WHERE first_pub_year IS NOT NULL""").df()
    for r in fb.itertuples():
        pf.setdefault(r.author_id, int(r.first_pub_year))
if len(pa):
    for pid, gdf in pa.groupby("author_id"):
        yy = gdf.publication_year.dropna()
        if len(yy): pf.setdefault(pid, int(yy.min()))
ss = con.execute(f"SELECT author_id, arrival, academic_age FROM read_parquet('{STAR_SET}')").df()
star_first = {r.author_id: int(r.arrival) - 1 - int(r.academic_age)
              for r in ss.itertuples() if pd.notna(r.arrival) and pd.notna(r.academic_age)}
report["first_pub"] = {"persons": len(pf), "stars_with_first": len(star_first)}

# ============ 5. build rows ============
def build_rows(pid, event_id, star, arrival):
    rows = []
    d = dose_topic(pid, star, arrival)
    sf1, pf1 = star_first.get(star), pf.get(pid)
    ag = float(sf1 - pf1) if (sf1 is not None and pf1 is not None) else None
    for y in range(arrival - W, arrival + W + 1):
        pyr = py_by.get((pid, y))
        if pyr is not None:
            vals = {c: getattr(pyr, c) for c in ["fwci_frac", "fwci_frac_ex_star",
                    "pub_count", "pub_count_ex_star", "fwci_mean", "fwci_mean_ex_star"]}
            # ★v9 U6-R7 rule backfill (audit defect 3): years with publications but a fully missing FWCI baseline
            #   (pub>0 ∧ fwci_frac==0 ∧ fwci_mean missing) -> fwci_frac recorded as NA, not 0
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
        rows.append({"incumbent_person_id": f"P_{pid}", "year": y,
                     "star_person_id": f"P_{star}", "event_id": event_id,
                     "treated": True, "post": y >= arrival,
                     "dose_coupling_baseline": None, "dose_topic": d,
                     "dose_low_confidence": False, "age_gap": ag, **vals})
    return rows

# ---- G-ROW ----
random.seed(42)
sample_both = random.sample(sorted(both_rel), min(60, len(both_rel)))
mism = []
old_idx = old.set_index(["pid", "event_id", "year"]).sort_index()
fill_div = []   # Old NA / new 0 divergence: U6 roster source vs the new caliber's roster_clean spell — recorded, not a hard stop
exstar_tol = []   # fnfix: caliber difference of ex_star for the new events (recorded)
dose_tol = []   # Generator residual of dose <=0.005 (small U5 implementation difference; cause not traced to the last digit) — recorded, not a hard stop
for pid, evid in sample_both:
    star, arr = evid.split(":")[0], int(evid.split(":")[1])
    for m in build_rows(pid, evid, star, arr):
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
                if c in ("dose_topic", "age_gap"):
                    mism.append((pid, evid, m["year"], c, "NA_mismatch", ov, mv))
                else:
                    fill_div.append((pid, evid, m["year"], c,
                                     "old_NA" if na_o else "old_val", ov, mv))
                continue
            d_ = abs(float(ov) - float(mv))
            if d_ > max(1e-4, 1e-6 * abs(float(ov))):
                if evid in _NEW_EV and c.endswith("_ex_star"):
                    exstar_tol.append((pid, evid, m["year"], c, float(ov), float(mv)))   # fnfix: caliber difference in excluding co-authorship with the new star; recorded, not blocking
                elif c == "dose_topic" and d_ <= 0.01:
                    dose_tol.append((pid, evid, c, float(ov), float(mv)))
                else:
                    mism.append((pid, evid, m["year"], c, float(ov), float(mv)))
report["G_ROW_fnfix_exstar_tolerated"] = {"n": len(exstar_tol), "examples": [list(map(str, x)) for x in exstar_tol[:8]]}
report["G_ROW"] = {"sampled_both": len(sample_both), "mismatches": len(mism),
                   "dose_tolerated_le_0.01": len(dose_tol),
                   "fill_divergence": len(fill_div),
                   "fill_examples": [list(map(str, x)) for x in fill_div[:8]],
                   "examples": [list(map(str, x)) for x in mism[:12]]}
print("G-ROW mism =", len(mism), " dose_tol =", len(dose_tol),
      " fill_div =", len(fill_div), flush=True)

# ============ 6. assembly + gates ============
new_rows = []
dept_map = {(r.pid, r.event_id): (r.star, int(r.arrival)) for r in dept.itertuples()}
for pid, evid in sorted(new_rel):
    star, arr = dept_map[(pid, evid)]
    new_rows.append(pd.DataFrame(build_rows(pid, evid, star, arr)))
new_df = pd.concat(new_rows, ignore_index=True) if new_rows else pd.DataFrame(columns=FRAME_COLS)
new_df["channel"] = "dept_only"
old_out = old.copy()
old_out["channel"] = ["both" if (p, e) in both_rel else "network"
                      for p, e in zip(old_out.pid, old_out.event_id)]
old_out = old_out.drop(columns=["pid"])
frame = pd.concat([old_out[FRAME_COLS + ["channel"]],
                   new_df[FRAME_COLS + ["channel"]]], ignore_index=True)
ok = len(frame) == len(old) + len(new_rel) * 11
report["G_SUM"] = {"total": len(frame), "old": len(old), "new": len(new_rel) * 11, "ok": ok}
report["frame"] = {"rows": len(frame),
                   "relationships": int(frame[["incumbent_person_id", "event_id"]]
                                        .drop_duplicates().shape[0]),
                   "persons": int(frame.incumbent_person_id.nunique()),
                   "events": int(frame.event_id.nunique()),
                   "by_channel": frame.channel.value_counts().to_dict(),
                   "dose_null_new_rows": int(new_df.dose_topic.isna().sum()) if len(new_df) else 0,
                   "age_gap_null_new_rows": int(new_df.age_gap.isna().sum()) if len(new_df) else 0}
gate = (gd["share_exact_1e-9"] >= 0.90
        and (gd["max_abs_diff"] or 0) <= 0.01
        and len(mism) == 0 and ok)
report["GATE"] = "PASS" if gate else "FAIL"
json.dump(report, open(_CFG["OUT_REPORT"], "w"), indent=1, default=str)
print(json.dumps({k: report[k] for k in ("G_DOSE", "G_ROW", "G_SUM", "frame", "GATE")},
                 indent=1, default=str), flush=True)
if not gate:
    print("gold standard not passed — main frame not written", flush=True)
    sys.exit(2)
# ★v9 writing to disk: old rows are kept **verbatim** (audit defect: a pandas round-trip causes 1-ULP floating-point drift),
#   channel appended at the end of the row; new rows are serialised by pandas.
import csv as _csv
out_path = _CFG["OUT_FRAME"]
with open(out_path, "w", newline="") as fout:
    fout.write(",".join(FRAME_COLS + ["channel"]) + "\n")
    with open(OLD_FRAME, newline="") as fin:
        hdr = next(_csv.reader([fin.readline()]))
        assert hdr == FRAME_COLS, f"old frame column order mismatch: {hdr}"
    with open(OLD_FRAME, newline="") as fin:
        fin.readline()
        for line in fin:
            line = line.rstrip("\n")
            cells = next(_csv.reader([line]))
            key = (strip(cells[0]), cells[3])
            ch = "both" if key in both_rel else "network"
            if cells[3] in _NEW_EV and key in _dose_override and _dose_override[key] is not None:
                cells[7] = repr(float(_dose_override[key])); line = ",".join(cells)
            fout.write(line + "," + ch + "\n")
    new_df.to_csv(fout, index=False, header=False, columns=FRAME_COLS + ["channel"])
pd.DataFrame([{"pid": p, "event_id": e,
               "channel": ("both" if (p, e) in both_rel else
                           "dept_only" if (p, e) in new_rel else "network")}
              for p, e in sorted(new_rel | old_rel)]).to_csv(
    _CFG["OUT_REL"], index=False)
print("DONE →", out_path, flush=True)
