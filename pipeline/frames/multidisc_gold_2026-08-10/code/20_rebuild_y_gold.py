#!/usr/bin/env python3
"""05_rebuild_multidisc_y.py — chemistry/maths frames: recompute y with a new denominator

Two differences from the 08-09 version 02_rebuild_frame_y.py:
  1. the denominator is the full-snapshot expected table (fwci_expected_fullsnapshot_2026-08-09.parquet)
  2. **all rows of all three channels are recomputed** (not only dept_only) — network/both rows also
     used a self-built FWCI, with the same old pop table (u1_edges_full_2026-07-05), so they need the
     new denominator too.

Each tier writes two versions of the frame (all other columns byte for byte unchanged, only the 4 y columns replaced):
  new         = this machinery + full-snapshot denominator  <- main specification
  machineold  = this machinery + old pop denominator        <- attribution comparison
How to read the attribution:
  08-09 old result -> machineold : machinery difference (network rows were computed then by the
                              07-24 prodlib; its alias closure / star-exclusion set / sup_pairs
                              supplementary edges come from a different source than this machinery)
  machineold  -> new        : **pure denominator difference** (the quantity of interest here)

Hard anchors:
  C-PC(dept)  pub_count/pub_count_ex_star of dept_only rows bit-identical (zero tolerance; verified earlier)
  C-PC(net)   the same items on network/both rows — record only (known source difference), no gate; counted as they are
  G-D hand    5 person-years recomputed by hand with independent SQL (works list -> fwci per paper -> weighted sum)

Run: python3 05_rebuild_multidisc_y.py --field chemistry|math_stats
Output: data/analysis_frame_{field}_{variant}_{new|machineold}_fullsnap_2026-08-09.csv
      data/g_multidisc_rebuild_{field}.json
"""
import argparse
import csv as _csv
import json
import math
import os
import random
import sys

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
SSD = str(_sar_rd(_sar_derived_root() / "u1_edges_full_2026-07-05"))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V2 = f"{ROOT}/v2_output/multidisc_v2_2026-08-04"
MD24 = f"{ROOT}/v2_output/multidisc_2026-07-24/data"
EXP_NEW = str(_sar_legacy_thesis() / "v2_output/fwci_fullsnapshot_rebuild_2026-08-09/data/fwci_expected_fullsnapshot_2026-08-09.parquet")
POP_OLD = f"{SSD}/fwci_baseline_pop/**/*.parquet"
U1E = f"{SSD}/authorship_edges/**/*.parquet"
U1W = f"{SSD}/works/**/*.parquet"
PMAP = f"{ROOT}/v2_output/multidisc_v2_2026-08-04/data/person_map_multidisc_seeds.parquet"
STARS_EXCL = f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/stars_excluded_{os.environ.get("GOLDVAR", "inc")}.parquet" if os.path.exists(f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/stars_excluded_{os.environ.get("GOLDVAR", "inc")}.parquet") else f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/stars_excluded_gold.parquet"   # Use the variant's own star-exclusion set if it has one (fnfix variant)

sys.path.insert(0, f"{ROOT}/multiplex_pipeline/units/u0_foundation/src")
sys.path.insert(0, f"{ROOT}/multiplex_pipeline/units/u4_output_star/src")
from m5_output.fwci_baseline_build import build_fwci_baseline  # noqa: E402
from m5_output.fwci_raw import compute_fwci                    # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--field", required=True, choices=["chemistry", "math_stats"])
args = ap.parse_args()
FIELD = args.field
VAR = os.environ.get("GOLDVAR", "inc")
FRAME_DIR = f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/{VAR}/union_frame_{FIELD}"
VARIANTS = {"gold": ""}   # Single version: hand-verified gold roster, no cleaning tiers
FRAME_COLS = ["incumbent_person_id", "year", "star_person_id", "event_id", "treated",
              "post", "dose_coupling_baseline", "dose_topic", "dose_low_confidence",
              "age_gap", "fwci_frac", "pub_count", "fwci_frac_ex_star",
              "pub_count_ex_star", "fwci_mean", "fwci_mean_ex_star", "channel"]
IDX = {c: i for i, c in enumerate(FRAME_COLS)}
Y_SWAP = ["fwci_frac", "fwci_frac_ex_star", "fwci_mean", "fwci_mean_ex_star"]

con = duckdb.connect()
con.execute("SET memory_limit='10GB'")
con.execute("PRAGMA threads=8")
os.makedirs(str(_sar_staged(_sar_legacy_thesis() / "v2_output/multidisc_gold_2026-08-10/data/_duck_tmp")), exist_ok=True)
con.execute(f"SET temp_directory='{_sar_staged(_sar_legacy_thesis() / "v2_output/multidisc_gold_2026-08-10/data/_duck_tmp")}'")
verif = {"field": FIELD, "date": "2026-08-09"}

# ============ 0. Two expected tables ============
expected_new = {(sf, int(yr), wt): e for sf, yr, wt, e in con.execute(
    f"SELECT subfield_id, year, work_type, expected_citations "
    f"FROM read_parquet('{EXP_NEW}')").fetchall()}
pop_rows = [dict(zip(("subfield_id", "year", "work_type", "work_count", "citation_sum"), t))
            for t in con.execute(
                f"SELECT subfield_id, year, work_type, work_count, citation_sum "
                f"FROM read_parquet('{POP_OLD}', hive_partitioning=0)").fetchall()]
expected_old = {(r["subfield_id"], r["year"], r["work_type"]): r["expected_citations"]
                for r in build_fwci_baseline(pop_rows)}
print(f"[expected] new={len(expected_new)} old={len(expected_old)}", flush=True)
verif["expected_cells"] = {"new": len(expected_new), "old": len(expected_old)}

# ============ 1. Read the three-channel frames (ALL rows, not only dept_only) ============
frames, all_pids = {}, set()
for v, suf in VARIANTS.items():
    fp = f"{FRAME_DIR}/analysis_frame_{FIELD}{suf}_2026-08-10.csv"
    with open(fp, "rb") as fh:      # Old-frame rows contain an embedded \r (CRLF leftover from 07-24) -> split lines on \n, then strip \r
        hdr = next(_csv.reader([fh.readline().decode().rstrip("\n").replace("\r", "")]))
        assert hdr == FRAME_COLS, f"{v} frame column order mismatch: {hdr}"
        rows = [next(_csv.reader([ln.decode().rstrip("\n").replace("\r", "")])) for ln in fh]
    frames[v] = (fp, rows)
    all_pids |= {r[IDX["incumbent_person_id"]] for r in rows}
    ch = {}
    for r in rows:
        ch[r[IDX["channel"]]] = ch.get(r[IDX["channel"]], 0) + 1
    print(f"[frame:{v}] rows={len(rows)} channels={ch}", flush=True)
need_persons = sorted(all_pids)
print(f"[persons] all frame persons = {len(need_persons)}", flush=True)
verif["frame_persons"] = len(need_persons)

# ============ 2. alias closure + star-exclusion set (replicates the 08-06 frame-build script verbatim) ============
con.execute("CREATE TEMP TABLE needp AS SELECT * FROM (VALUES %s) t(bare)"
            % ",".join(f"('{p}')" for p in need_persons))
alias = con.execute(f"""
    WITH canon AS (
        SELECT n.bare, m.person_id
        FROM needp n JOIN read_parquet('{PMAP}') m ON m.author_id = n.bare)
    SELECT c.bare AS person_id, m2.author_id
    FROM canon c JOIN read_parquet('{PMAP}') m2 ON m2.person_id = c.person_id""").df()
mapped = set(alias.person_id)
alias = pd.concat([alias, pd.DataFrame({
    "person_id": [p for p in need_persons if p not in mapped],
    "author_id": [p for p in need_persons if p not in mapped]})], ignore_index=True)
con.register("alias_df", alias)

signed_star_all = set()
for f_ in ("chemistry", "math_stats"):
    signed_star_all |= set(pd.read_csv(f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/events_{f_}_gold_2026-08-10.csv").author_id)
excl_authors = {t[0] for t in con.execute(
    f"SELECT author_id FROM read_parquet('{STARS_EXCL}')").fetchall()} | signed_star_all
con.execute("CREATE TEMP TABLE exa AS SELECT * FROM (VALUES %s) t(a)"
            % ",".join(f"('{s}')" for s in sorted(excl_authors)))
ship_alias = {r[0] for r in con.execute(f"""
    WITH canon AS (SELECT DISTINCT m.person_id FROM read_parquet('{PMAP}') m
                   JOIN exa ON m.author_id = exa.a)
    SELECT m2.author_id FROM read_parquet('{PMAP}') m2
    JOIN canon USING (person_id)""").fetchall()} | excl_authors
verif["ship_alias_n"] = len(ship_alias)

# ============ 3. Output-unit query (same as the 08-06/08-09 oc query) ============
con.execute("CREATE TEMP TABLE ship AS SELECT * FROM (VALUES %s) t(a)"
            % ",".join(f"('{s}')" for s in sorted(ship_alias)))
oc = con.execute(f"""
    WITH tgt AS (SELECT a.person_id, a.author_id FROM alias_df a),
    own AS (SELECT DISTINCT t.person_id pid, e.work_id, e.publication_year yr
            FROM read_parquet('{U1E}', hive_partitioning=0) e
            JOIN tgt t ON e.author_id = t.author_id
            WHERE e.publication_year IS NOT NULL),
    wa AS (SELECT e.work_id, count(DISTINCT e.author_id) n_auth,
                  max(CASE WHEN s.a IS NOT NULL THEN 1 ELSE 0 END) has_star
           FROM read_parquet('{U1E}', hive_partitioning=0) e
           LEFT JOIN ship s ON e.author_id = s.a
           WHERE e.work_id IN (SELECT work_id FROM own) GROUP BY 1)
    SELECT own.pid, own.yr, own.work_id, w.cited_by_count, w.work_type, w.subfield_id,
           w.is_paratext, w.publication_year AS wyr, wa.n_auth, wa.has_star
    FROM own JOIN read_parquet('{U1W}', hive_partitioning=0) w ON own.work_id = w.work_id
    JOIN wa ON own.work_id = wa.work_id""").df()
print(f"[oc] unit rows = {len(oc)}", flush=True)
verif["oc_unit_rows"] = len(oc)

# ============ 4. fwci per paper (new and old tracks) + person-year aggregation ============
cache_n, cache_o, reasons_n = {}, {}, {}


def fw(row, exp, cache, reasons=None):
    if row.work_id not in cache:
        o = compute_fwci(
            {"work_id": row.work_id, "work_type": row.work_type,
             "is_paratext": bool(row.is_paratext) if pd.notna(row.is_paratext) else False,
             "publication_year": int(row.wyr) if pd.notna(row.wyr) else None,
             "subfield_id": row.subfield_id if pd.notna(row.subfield_id) else None,
             "cited_by_count": int(row.cited_by_count)}, exp)
        cache[row.work_id] = o["fwci"]
        if reasons is not None and o["fwci"] is None:
            reasons[o["fwci_missing_reason"]] = reasons.get(o["fwci_missing_reason"], 0) + 1
    return cache[row.work_id]


acc = {}
for r in oc.itertuples():
    a = acc.setdefault((r.pid, int(r.yr)), {
        "pc": 0, "pcx": 0,
        "ff_n": 0.0, "ffx_n": 0.0, "f_n": [], "fx_n": [],
        "ff_o": 0.0, "ffx_o": 0.0, "f_o": [], "fx_o": []})
    a["pc"] += 1
    fc = 1.0 / max(int(r.n_auth), 1)
    non_star = not bool(r.has_star)
    if non_star:
        a["pcx"] += 1
    for kind, exp, cache, rs in (("n", expected_new, cache_n, reasons_n),
                                 ("o", expected_old, cache_o, None)):
        val = fw(r, exp, cache, rs)
        if val is None:
            continue
        a[f"ff_{kind}"] += fc * val
        a[f"f_{kind}"].append(val)
        if non_star:
            a[f"ffx_{kind}"] += fc * val
            a[f"fx_{kind}"].append(val)
n_na_new = sum(1 for r in oc.itertuples() if cache_n[r.work_id] is None)
verif["fwci_new_na"] = {"units_na": n_na_new, "units_total": len(oc),
                        "na_share": round(n_na_new / max(len(oc), 1), 4),
                        "reasons_by_distinct_work": reasons_n}
print(f"[fwci] units={len(oc)} new_NA={n_na_new} reasons={reasons_n}", flush=True)


def agg_vals(a, kind):
    ff, ffx = a[f"ff_{kind}"], a[f"ffx_{kind}"]
    f, fx = a[f"f_{kind}"], a[f"fx_{kind}"]
    mean = sum(f) / len(f) if f else None
    meanx = sum(fx) / len(fx) if fx else None
    if a["pc"] > 0 and ff == 0.0 and mean is None:
        ff = None
    if a["pcx"] > 0 and ffx == 0.0 and meanx is None:
        ffx = None
    return ff, ffx, mean, meanx


# ============ 5. Write frames (each tier x new/machineold) ============
def fnum(s):
    return None if s in ("", None) else float(s)


def fmt(v):
    return "" if v is None else str(float(v))


cpc_dept_bad, cpc_net_bad = [], []
gd_pairs, seen_py = [], set()
swap_stats = {}
for v, suf in VARIANTS.items():
    _, rows = frames[v]
    for kind, tag in (("n", "new"), ("o", "machineold")):
        out_path = _sar_staged(f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/{VAR}/analysis_frame_{FIELD}_{tag}_gold_2026-08-10.csv")
        trans = {"val2val": 0, "val2na": 0, "na2val": 0, "na2na": 0,
                 "zero_fill": 0, "row_na": 0, "agg_missing": 0, "pc_mismatch": 0}
        with open(out_path, "w", newline="") as fout:
            fout.write(",".join(FRAME_COLS) + "\n")
            for cells in rows:
                cells = list(cells)
                pid = cells[IDX["incumbent_person_id"]]
                yr = int(float(cells[IDX["year"]]))
                ch = cells[IDX["channel"]]
                old_pc, old_pcx = fnum(cells[IDX["pub_count"]]), fnum(cells[IDX["pub_count_ex_star"]])
                a = acc.get((pid, yr))
                if old_pc is None:
                    new = (None,) * 4
                    trans["row_na"] += 1
                elif old_pc == 0:
                    new = (0.0, 0.0, None, None)
                    trans["zero_fill"] += 1
                elif a is None:
                    new = (None,) * 4
                    trans["agg_missing"] += 1
                    if kind == "n":
                        (cpc_dept_bad if ch == "dept_only" else cpc_net_bad).append(
                            (v, pid, yr, ch, "agg_missing", old_pc))
                else:
                    if a["pc"] != int(old_pc) or a["pcx"] != int(old_pcx):
                        trans["pc_mismatch"] += 1
                        if kind == "n":
                            (cpc_dept_bad if ch == "dept_only" else cpc_net_bad).append(
                                (v, pid, yr, ch, "pc_mismatch",
                                 (old_pc, a["pc"], old_pcx, a["pcx"])))
                    new = agg_vals(a, kind)
                    if kind == "n":
                        old_ff = fnum(cells[IDX["fwci_frac"]])
                        k = ("na" if old_ff is None else "val") + "2" + \
                            ("na" if new[0] is None else "val")
                        trans[k] += 1
                        if v == "none" and (pid, yr) not in seen_py:
                            seen_py.add((pid, yr))
                            gd_pairs.append((old_ff, new[0], ch,
                                             agg_vals(a, "o")[0]))
                for c, val in zip(Y_SWAP, new):
                    cells[IDX[c]] = fmt(val)
                fout.write(",".join(cells) + "\n")
        swap_stats[f"{v}_{tag}"] = {"out": out_path, "transition": trans}
        print(f"[write:{v}/{tag}] {trans}", flush=True)
verif["swap"] = swap_stats
verif["C_PC_dept_only"] = {"bad_rows": len(cpc_dept_bad), "pass": not cpc_dept_bad,
                           "examples": [list(map(str, x)) for x in cpc_dept_bad[:20]]}
verif["C_PC_network_both_diagnostic"] = {
    "mismatch_rows": len(cpc_net_bad),
    "examples": [list(map(str, x)) for x in cpc_net_bad[:10]],
    "note": ("记录性，不设闸：network/both 行的 y 当年由 07-24 prodlib 算，"
             "别名闭包 / 剔星集(07-24 exclude_list) / sup_pairs 补数边与本机器不同源 → "
             "pub_count 少量不等属已知源差。machineold 帧就是为了把这部分差异隔离出来。")}
print(f"[C-PC] dept_bad={len(cpc_dept_bad)} net_diag={len(cpc_net_bad)}", flush=True)

# ============ 6. G-D: new vs old y correlation + quantiles + manual check ============
def corr(xs):
    n = len(xs)
    if n < 3:
        return None
    mx = sum(x for x, _ in xs) / n
    my = sum(y for _, y in xs) / n
    sxy = sum((x - mx) * (y - my) for x, y in xs)
    sx = math.sqrt(sum((x - mx) ** 2 for x, _ in xs))
    sy = math.sqrt(sum((y - my) ** 2 for _, y in xs))
    return sxy / (sx * sy) if sx > 0 and sy > 0 else None


def spearman(ps):
    def rank(vv):
        s = sorted(range(len(vv)), key=lambda i: vv[i])
        r = [0] * len(vv)
        for j, i in enumerate(s):
            r[i] = j
        return r
    xs, ys = [x for x, _ in ps], [y for _, y in ps]
    return corr(list(zip(rank(xs), rank(ys))))


def quantiles(vals):
    if not vals:
        return {}
    s = sorted(vals)

    def q(p):
        i = p * (len(s) - 1)
        lo = int(i)
        hi = min(lo + 1, len(s) - 1)
        return s[lo] + (s[hi] - s[lo]) * (i - lo)
    return {f"p{int(p*100):02d}": round(q(p), 4)
            for p in (0.05, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)}


gd = {}
for lbl, sel in (("all", lambda c: True), ("dept_only", lambda c: c == "dept_only"),
                 ("network_both", lambda c: c in ("network", "both"))):
    pairs = [(o, n) for o, n, c, _ in gd_pairs if sel(c) and o is not None and n is not None]
    pairs_mo = [(mo, n) for o, n, c, mo in gd_pairs if sel(c) and mo is not None and n is not None]
    gd[lbl] = {
        "n_both_nonNA_frame_vs_new": len(pairs),
        "corr_raw": round(corr(pairs), 4) if corr(pairs) else None,
        "corr_log1p": round(corr([(math.log1p(a), math.log1p(b)) for a, b in pairs]), 4)
                      if pairs else None,
        "spearman": round(spearman(pairs), 4) if spearman(pairs) else None,
        "quantiles_frame_old": quantiles([o for o, _ in pairs]),
        "quantiles_new": quantiles([n for _, n in pairs]),
        "n_machineold_vs_new": len(pairs_mo),
        "corr_machineold_vs_new_log1p": round(
            corr([(math.log1p(a), math.log1p(b)) for a, b in pairs_mo]), 4) if pairs_mo else None,
        "quantiles_machineold": quantiles([o for o, _ in pairs_mo]),
    }
    print(f"[G-D:{lbl}] n={len(pairs)} corr_raw={gd[lbl]['corr_raw']} "
          f"spearman={gd[lbl]['spearman']}")
    print(f"   frame_old {gd[lbl]['quantiles_frame_old']}")
    print(f"   new       {gd[lbl]['quantiles_new']}")
verif["G_D"] = gd

random.seed(42)
cand = sorted(k for k, a in acc.items() if a["pc"] >= 2 and k in seen_py)
picks = random.sample(cand, min(5, len(cand)))
hand, hand_ok = [], True
for pid, yr in picks:
    ws = con.execute(f"""
        WITH tgt AS (SELECT author_id FROM alias_df WHERE person_id = ?),
        own AS (SELECT DISTINCT e.work_id
                FROM read_parquet('{U1E}', hive_partitioning=0) e
                JOIN tgt t ON e.author_id = t.author_id
                WHERE e.publication_year = ?),
        wa AS (SELECT e.work_id, count(DISTINCT e.author_id) n_auth
               FROM read_parquet('{U1E}', hive_partitioning=0) e
               WHERE e.work_id IN (SELECT work_id FROM own) GROUP BY 1)
        SELECT own.work_id, w.cited_by_count, w.work_type, w.subfield_id, w.is_paratext,
               w.publication_year, wa.n_auth, b.expected_citations
        FROM own
        JOIN read_parquet('{U1W}', hive_partitioning=0) w ON own.work_id = w.work_id
        JOIN wa ON own.work_id = wa.work_id
        LEFT JOIN read_parquet('{EXP_NEW}') b
          ON b.subfield_id = w.subfield_id AND b.year = w.publication_year
         AND b.work_type = w.work_type
        ORDER BY own.work_id""", [pid, yr]).df()
    manual, nval, det = 0.0, 0, []
    for r in ws.itertuples():
        if (r.work_type in ("article", "review") and not bool(r.is_paratext)
                and pd.notna(r.subfield_id) and pd.notna(r.expected_citations)
                and r.expected_citations > 0):
            f = r.cited_by_count / r.expected_citations
            manual += (1.0 / int(r.n_auth)) * f
            nval += 1
        else:
            f = None
        det.append({"work_id": r.work_id, "cited": int(r.cited_by_count), "type": r.work_type,
                    "sf": str(r.subfield_id), "n_auth": int(r.n_auth),
                    "expected_new": None if pd.isna(r.expected_citations) else round(r.expected_citations, 4),
                    "fwci_new": None if f is None else round(f, 6)})
    mv = manual if nval else None
    sv = agg_vals(acc[(pid, yr)], "n")[0]
    ok = ((mv is None and sv is None) or
          (mv is not None and sv is not None and abs(mv - sv) < 1e-9))
    hand_ok &= ok
    hand.append({"pid": pid, "year": yr, "n_works": len(det), "manual": mv,
                 "script": sv, "match": ok, "works": det})
    print(f"[hand] {pid}x{yr} n={len(det)} manual={mv} script={sv} → {'MATCH' if ok else 'FAIL'}")
verif["G_D_hand_check"] = {"cells": hand, "pass": hand_ok}

verif["PASS"] = bool(not cpc_dept_bad and hand_ok)
json.dump(verif, open(_sar_staged(f"{_sar_legacy_thesis()}/v2_output/multidisc_gold_2026-08-10/data/{VAR}/g_yrebuild_{FIELD}.json"), "w"),
          indent=1, ensure_ascii=False, default=str)
print(f"→ {BASE}/data/g_multidisc_rebuild_{FIELD}.json  PASS={verif['PASS']}")
if not verif["PASS"]:
    raise SystemExit(2)
