#!/usr/bin/env python3
"""04_rebuild_econ_y.py — economics frame: recompute y with a new denominator (2026-08-09)

Prerequisite: all three anchors of 03 passed (A1 per-paper fwci bit for bit / A2 five shared columns / A3 four ex_star columns,
      all with 0 mismatches) -> "we can recompute output_star1pct with the production parts" is proven, so changing the denominator is an isolated change.

This script produces two versions of the economics frame (other columns byte for byte unchanged, only the 4 y columns are replaced):
  A. unified   = main caliber: everyone uses self-built FWCI + the full-snapshot denominator
     (including the 101 API-supplemented people — mixed calibers are unified when rebuilding)
  B. denomonly = for attribution: only the denominator is changed, the 101 supplemented people still use OpenAlex's native fwci (same source as the old frame)
     -> difference A - B = contribution of unifying the supplemented people's caliber; difference B - old frame = pure denominator contribution

Machine (verbatim replica of the production chain, replacing only the expected dictionary):
  units (work x incumbent, saved by 03) -> compute_fwci(work, expected_NEW)
    -> identity.output_rule.aggregate_output -> person x year
  supplemented people: frac=1/n_authors, isc=author_ids∩ship_alias from patch/works_by_author.jsonl
    (word for word the same as 00_build_frame.py:246-273), with fwci replaced by the self-built one (work_type/is_paratext/
     cited_by_count/subfield taken from the 11school works table — same source and same snapshot as everyone else; a
     work missing from the table -> fwci=NA with the reason recorded, never filled with 0)

Frame writing rules (same as 00_build_frame.py v9 + 02_rebuild_frame_y.py):
  pub_count empty in the frame -> all 4 y NA; pub_count==0 (in post, no publication that year) -> (0,0,NA,NA);
  otherwise look up the new table, first pass the C-PC structural anchor (pub_count / pub_count_ex_star must be equal bit for bit),
  then apply U6-R7: pub>0 and fwci baseline fully missing -> fwci_frac recorded as NA, not 0.

Products: data/analysis_frame_dept_p01_{unified,denomonly}_fullsnap_2026-08-09.csv
      data/g_econ_rebuild.json
"""
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
SSD = str(_sar_rd(_sar_derived_root()))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDGES_SUB = "u1_full_11school_2026-07-16"
FRAME_DIR = str(_sar_legacy_thesis() / "v2_output/frame_dept_2026-07-31")   # patch data is still read from the old directory
FRAME_IN = str(_sar_legacy_thesis() / "v2_output/econ_fnfix_2026-08-15/data/analysis_frame_dept_p01_econ920_2026-08-13.csv")
PATCH_A = str(_sar_legacy_thesis() / "v2_output/econ_final_2026-08-13/patch/works_by_author.jsonl")
UNITS = str(_sar_legacy_thesis() / "v2_output/fwci_fullsnapshot_rebuild_2026-08-09/data/econ_units_2026-08-09.parquet")
EXP_NEW = f"{_sar_legacy_thesis()}/v2_output/fwci_fullsnapshot_rebuild_2026-08-09/data/fwci_expected_fullsnapshot_2026-08-09.parquet"
POP_OLD = f"{SSD}/{EDGES_SUB}/fwci_baseline_pop/**/*.parquet"
WORKS = f"{SSD}/{EDGES_SUB}/works/**/*.parquet"
STAR_SET = f"{SSD}/u4_star_set_p10_80ev_2026-07-22/star_set/star_set.parquet"
PMAP = f"{SSD}/u2_person_map_11school_2026-07-16/person_map/**/*.parquet"
OUT_JSON = str(_sar_staged(_sar_legacy_thesis() / "v2_output/econ_fnfix_2026-08-15/data/g_econ_rebuild.json"))

sys.path.insert(0, f"{ROOT}/multiplex_pipeline/units/u0_foundation/src")
sys.path.insert(0, f"{ROOT}/multiplex_pipeline/units/u4_output_star/src")
from m5_output.fwci_baseline_build import build_fwci_baseline  # noqa: E402
from m5_output.fwci_raw import compute_fwci                    # noqa: E402
from identity.output_rule import aggregate_output              # noqa: E402

import csv as _csv0
_NEW_EV = {f"{r['author_id']}:{int(r['arrival'])}" for r in _csv0.DictReader(open(str(_sar_legacy_thesis() / "v2_output/econ_fnfix_2026-08-15/data/new_events_econ.csv")))}
cpc_tol = []
cpc_new_missing = []
cpc_exstar_tol = []
FRAME_COLS = ["incumbent_person_id", "year", "star_person_id", "event_id", "treated",
              "post", "dose_coupling_baseline", "dose_topic", "dose_low_confidence",
              "age_gap", "fwci_frac", "pub_count", "fwci_frac_ex_star",
              "pub_count_ex_star", "fwci_mean", "fwci_mean_ex_star", "channel"]
IDX = {c: i for i, c in enumerate(FRAME_COLS)}
Y_SWAP = ["fwci_frac", "fwci_frac_ex_star", "fwci_mean", "fwci_mean_ex_star"]

con = duckdb.connect()
con.execute("SET memory_limit='10GB'")
con.execute("PRAGMA threads=8")
rep = {"date": "2026-08-09", "edges_sub": EDGES_SUB}

# ============ 0. two expected tables ============
expected_new = {(sf, int(yr), wt): e for sf, yr, wt, e in con.execute(
    f"SELECT subfield_id, year, work_type, expected_citations "
    f"FROM read_parquet('{EXP_NEW}')").fetchall()}
pop_rows = [dict(zip(("subfield_id", "year", "work_type", "work_count", "citation_sum"), t))
            for t in con.execute(
                f"SELECT subfield_id, year, work_type, work_count, citation_sum "
                f"FROM read_parquet('{POP_OLD}', hive_partitioning=0)").fetchall()]
expected_old = {(r["subfield_id"], r["year"], r["work_type"]): r["expected_citations"]
                for r in build_fwci_baseline(pop_rows)}
print(f"[expected] new={len(expected_new)} old_11school={len(expected_old)}", flush=True)

# ============ 1. main population: units -> new fwci -> aggregation ============
u = con.execute(f"SELECT * FROM read_parquet('{UNITS}')").df()
print(f"[units] {len(u)} rows", flush=True)


def fwci_of(row, exp):
    return compute_fwci(
        {"work_id": row.work_id, "work_type": row.work_type,
         "is_paratext": bool(row.is_paratext),
         "publication_year": int(row.publication_year) if pd.notna(row.publication_year) else None,
         "subfield_id": row.subfield_id if pd.notna(row.subfield_id) else None,
         "cited_by_count": int(row.cited_by_count) if pd.notna(row.cited_by_count) else 0},
        exp)


cache_new, reasons_new = {}, {}
contrib_new, contrib_old = [], []
per_work_pairs = []          # (work_id, fwci_old, fwci_new) for G-D
for r in u.itertuples():
    if pd.isna(r.publication_year):
        continue                                   # same as production: years with missing values are removed from the aggregation
    if r.work_id not in cache_new:
        o = fwci_of(r, expected_new)
        cache_new[r.work_id] = o["fwci"]
        if o["fwci"] is None:
            reasons_new[o["fwci_missing_reason"]] = reasons_new.get(o["fwci_missing_reason"], 0) + 1
    fw_new = cache_new[r.work_id]
    fw_old = None if pd.isna(r.fwci_old) else float(r.fwci_old)
    base = {"incumbent_person_id": r.incumbent_person_id, "year": int(r.publication_year),
            "frac_credit": float(r.frac_credit),
            "is_star_coauthored": bool(r.is_star_coauthored_p01)}
    contrib_new.append({**base, "fwci": fw_new})
    contrib_old.append({**base, "fwci": fw_old})
    per_work_pairs.append((r.work_id, fw_old, fw_new))
print(f"[main] contribs={len(contrib_new)} new_NA_reasons={reasons_new}", flush=True)
rep["main_population"] = {"contrib_units": len(contrib_new),
                          "distinct_works": len(cache_new),
                          "new_fwci_na_reasons_by_work": reasons_new}

agg_new = {(r["incumbent_person_id"], r["year"]): r for r in aggregate_output(contrib_new)}
agg_old = {(r["incumbent_person_id"], r["year"]): r for r in aggregate_output(contrib_old)}

# ============ 2. supplemented people (101 in the frame): three tracks native / self_new / self_old ============
pa = pd.DataFrame([json.loads(l) for l in open(PATCH_A)])
sp01 = [r[0] for r in con.execute(
    f"SELECT author_id FROM read_parquet('{STAR_SET}') WHERE is_star_1pct").fetchall()]
con.execute("CREATE TEMP TABLE sp01 AS SELECT * FROM (VALUES %s) t(a)"
            % ",".join(f"('{s}')" for s in sp01))
ship_alias = {r[0] for r in con.execute(f"""
    WITH canon AS (SELECT DISTINCT m.person_id FROM read_parquet('{PMAP}', hive_partitioning=0) m
                   JOIN sp01 ON m.author_id = sp01.a)
    SELECT m2.author_id FROM read_parquet('{PMAP}', hive_partitioning=0) m2
    JOIN canon USING (person_id)""").fetchall()} | set(sp01)
rep["ship_alias_n"] = len(ship_alias)

pw = sorted(set(pa.work_id))
con.execute("CREATE TEMP TABLE pw2 AS SELECT * FROM (VALUES %s) t(w)"
            % ",".join(f"('{w}')" for w in pw))
wmeta = {r[0]: r[1:] for r in con.execute(f"""
    SELECT w.work_id, w.publication_year, w.subfield_id, w.work_type,
           w.cited_by_count, w.is_paratext
    FROM read_parquet('{WORKS}', hive_partitioning=0) w JOIN pw2 ON w.work_id = pw2.w""").fetchall()}
rep["patch"] = {"rows": len(pa), "authors": int(pa.author_id.nunique()),
                "distinct_works": len(pw), "works_with_snapshot_meta": len(wmeta)}

patch_reasons = {}
pc_native, pc_self_new, pc_self_old = [], [], []
for r in pa.itertuples():
    if pd.isna(r.publication_year):
        continue                                   # same as 00_build_frame.py:249
    key = {"incumbent_person_id": f"P_{r.author_id}", "year": int(r.publication_year),
           "frac_credit": 1.0 / max(int(r.n_authors), 1),
           "is_star_coauthored": bool(set(r.author_ids) & ship_alias)}
    pc_native.append({**key, "fwci": None if pd.isna(r.fwci) else float(r.fwci)})
    m = wmeta.get(r.work_id)
    if m is None:
        patch_reasons["missing_snapshot_meta"] = patch_reasons.get("missing_snapshot_meta", 0) + 1
        fw_n = fw_o = None
    else:
        wyr, wsf, wtype, wcit, wpara = m
        w = {"work_id": r.work_id, "work_type": wtype, "is_paratext": bool(wpara) if wpara is not None else False,
             "publication_year": int(wyr) if wyr is not None else None,
             "subfield_id": wsf, "cited_by_count": int(wcit) if wcit is not None else 0}
        on = compute_fwci(w, expected_new)
        oo = compute_fwci(w, expected_old)
        fw_n, fw_o = on["fwci"], oo["fwci"]
        if fw_n is None:
            patch_reasons[on["fwci_missing_reason"]] = patch_reasons.get(on["fwci_missing_reason"], 0) + 1
    pc_self_new.append({**key, "fwci": fw_n})
    pc_self_old.append({**key, "fwci": fw_o})
rep["patch"]["new_fwci_na_reasons"] = patch_reasons
patch_native = {(r["incumbent_person_id"], r["year"]): r for r in aggregate_output(pc_native)}
patch_new = {(r["incumbent_person_id"], r["year"]): r for r in aggregate_output(pc_self_new)}
patch_old = {(r["incumbent_person_id"], r["year"]): r for r in aggregate_output(pc_self_old)}
print(f"[patch] py_native={len(patch_native)} na_reasons={patch_reasons}", flush=True)

# main-population keys use the P_ prefix; the incumbent_person_id of units already carries P_
PY_OLD = dict(agg_old); PY_OLD.update(patch_native)          # = old-frame caliber (should reproduce the frame values)
PY_NEW_UNI = dict(agg_new); PY_NEW_UNI.update(patch_new)     # A: main caliber
PY_NEW_DEN = dict(agg_new); PY_NEW_DEN.update(patch_native)  # B: denominator change only


def y4(a):
    """OUTPUT row -> (fwci_frac, fwci_frac_ex_star, fwci_mean, fwci_mean_ex_star) including U6-R7"""
    ff, ffx = a["fwci_frac"], a["fwci_frac_ex_star"]
    mean, meanx = a["fwci_mean"], a["fwci_mean_ex_star"]
    if a["pub_count"] > 0 and ff == 0.0 and mean is None:
        ff = None
    if a["pub_count_ex_star"] > 0 and ffx == 0.0 and meanx is None:
        ffx = None
    return ff, ffx, mean, meanx


# ============ 3. write the frames (two versions) + C-PC structural anchor + old-value reproduction anchor ============
def fnum(s):
    return None if s in ("", None) else float(s)


def fmt(v):
    return "" if v is None else str(float(v))


with open(FRAME_IN, "rb") as fh:
    hdr = next(_csv.reader([fh.readline().decode().rstrip("\n").replace("\r", "")]))
    assert hdr == FRAME_COLS, f"frame column order mismatch: {hdr}"
    raw_rows = [next(_csv.reader([ln.decode().rstrip("\n").replace("\r", "")])) for ln in fh]
print(f"[frame] rows={len(raw_rows)}", flush=True)

# ★Tolerance caliber of the old-value reproduction anchor (fixed after the first-run diagnosis of 2026-08-09):
#   the y columns of the 07-21 old frame were written to CSV **after a float32 round trip** (measured
#   1.4859622716903687 = float32(1.4859622905472003)), so a bit-for-bit comparison is necessarily all red.
#   -> three classes: (1) NA / has-value status mismatch = hard FAIL (zero tolerance)
#              (2) relative difference > 1e-6 (8x the float32 eps of 1.19e-7) = hard FAIL
#              (3) relative difference <= 1e-6 = float32 round trip, the maximum is recorded as is and does not count as FAIL
REPRO_F32_TOL = 1e-6
cpc_bad, repro_bad, repro_f32, seen_py = [], [], [], set()
repro_max_rel = [0.0]
gd_pairs = []           # (old_ff, new_ff) person x year level (for G-D)
gd_pairs_mean = []
variants = {"unified": (PY_NEW_UNI, {}), "denomonly": (PY_NEW_DEN, {})}
outs = {}
for vname, (PY, stats) in variants.items():
    out_path = _sar_staged(f"{_sar_legacy_thesis()}/v2_output/econ_fnfix_2026-08-15/data/analysis_frame_econ920_{vname}_fullsnap_2026-08-13.csv")
    trans = {"val2val": 0, "val2na": 0, "na2val": 0, "na2na": 0,
             "zero_fill": 0, "row_na": 0, "py_missing": 0}
    with open(out_path, "w", newline="") as fout:
        fout.write(",".join(FRAME_COLS) + "\n")
        for cells in raw_rows:
            cells = list(cells)
            pid, yr = cells[IDX["incumbent_person_id"]], int(float(cells[IDX["year"]]))
            old_pc = fnum(cells[IDX["pub_count"]])
            old_pcx = fnum(cells[IDX["pub_count_ex_star"]])
            a = PY.get((pid, yr))
            if cells[IDX["event_id"]] in _NEW_EV:
                if a is None and old_pc == 0:
                    new = (0.0, 0.0, None, None); trans["zero_fill"] += 1   # same rule as old rows: frame pub_count=0 -> zero fill
                elif a is None and old_pc is None:
                    new = (None, None, None, None); trans["row_na"] += 1    # same rule as old rows: not in post / not computable -> NA
                elif a is None:
                    new = (None,) * 4; trans["py_missing"] += 1; cpc_new_missing.append((vname, pid, yr, cells[IDX["event_id"]], old_pc))
                else:
                    new = y4(a); cpc_tol.append((vname, pid, yr, cells[IDX["event_id"]], old_pc, a["pub_count"]))
                    k = ("na" if fnum(cells[IDX["fwci_frac"]]) is None else "val") + "2" + ("na" if new[0] is None else "val"); trans[k] += 1
            elif old_pc is None:
                new = (None, None, None, None); trans["row_na"] += 1
                if a is not None and vname == "unified":
                    cpc_bad.append((vname, pid, yr, "old_NA_but_agg_present", a["pub_count"]))
            elif old_pc == 0:
                new = (0.0, 0.0, None, None); trans["zero_fill"] += 1
                if a is not None and vname == "unified":
                    cpc_bad.append((vname, pid, yr, "old_0_but_agg_present", a["pub_count"]))
            elif a is None:
                new = (None,) * 4; trans["py_missing"] += 1
                cpc_bad.append((vname, pid, yr, "agg_missing", old_pc))
            elif a["pub_count"] == int(old_pc) and a["pub_count_ex_star"] != int(old_pcx):
                new = y4(a); cpc_exstar_tol.append((vname, pid, yr, cells[IDX["event_id"]], old_pcx, a["pub_count_ex_star"]))
                k = ("na" if fnum(cells[IDX["fwci_frac"]]) is None else "val") + "2" + ("na" if new[0] is None else "val"); trans[k] += 1
            elif a["pub_count"] != int(old_pc) or a["pub_count_ex_star"] != int(old_pcx):
                new = (None,) * 4
                cpc_bad.append((vname, pid, yr, "pc_mismatch",
                                (old_pc, a["pub_count"], old_pcx, a["pub_count_ex_star"])))
            else:
                new = y4(a)
                old_ff = fnum(cells[IDX["fwci_frac"]])
                if vname == "unified":
                    # old-value reproduction anchor: the old-caliber values recomputed with PY_OLD must equal the values written in the frame
                    ao = PY_OLD.get((pid, yr))
                    if ao is not None:
                        yo = y4(ao)
                        for j, c in enumerate(Y_SWAP):
                            ov, rv = fnum(cells[IDX[c]]), yo[j]
                            na_o, na_r = ov is None, rv is None
                            if na_o != na_r:
                                repro_bad.append((pid, yr, c, ov, rv, "NA_status"))
                            elif not na_o:
                                rel = abs(ov - rv) / max(abs(ov), 1e-12)
                                if abs(ov - rv) > 1e-12:
                                    repro_max_rel[0] = max(repro_max_rel[0], rel)
                                    if rel > REPRO_F32_TOL:
                                        repro_bad.append((pid, yr, c, ov, rv, f"rel={rel:.2e}"))
                                    else:
                                        repro_f32.append(1)
                    if (pid, yr) not in seen_py:
                        seen_py.add((pid, yr))
                        gd_pairs.append((old_ff, new[0]))
                        gd_pairs_mean.append((fnum(cells[IDX["fwci_mean"]]), new[2]))
                k = ("na" if fnum(cells[IDX["fwci_frac"]]) is None else "val") + "2" + \
                    ("na" if new[0] is None else "val")
                trans[k] += 1
            for c, val in zip(Y_SWAP, new):
                cells[IDX[c]] = fmt(val)
            fout.write(",".join(cells) + "\n")
    stats.update({"out": out_path, "transition": trans})
    outs[vname] = out_path
    print(f"[write:{vname}] {trans}", flush=True)

rep["variants"] = {k: v[1] for k, v in variants.items()}
rep["C_PC_fnfix_newevent_rows"] = {"rows_written_from_agg": len(cpc_tol), "rows_agg_missing_NA": len(cpc_new_missing),
    "examples_missing": [list(map(str, x)) for x in cpc_new_missing[:20]],
    "note": "新事件行不进老帧复现锚（prodlib 行 y/pub_count 与 U5 冻结口径不同源）；一律写本脚本统一口径 agg 值，无 agg 写 NA"}
rep["C_PC_fnfix_exstar_only_tolerated_old_rows"] = {"n": len(cpc_exstar_tol), "examples": [list(map(str, x)) for x in cpc_exstar_tol[:10]],
    "note": "老事件行、在职者=补漏新星：帧 ex_star 按增量 star_set 为 0，agg 按原 star_set；pub_count 相等 → 写 agg，全帧 ex_star 统一为老 79 星口径"}
rep["C_PC_structural_anchor"] = {"bad_rows": len(cpc_bad),
                                 "examples": [list(map(str, x)) for x in cpc_bad[:20]],
                                 "pass": not cpc_bad}
rep["old_value_reproduction_anchor"] = {
    "hard_fail_cells": len(repro_bad),
    "float32_roundtrip_cells": len(repro_f32),
    "max_relative_deviation": repro_max_rel[0],
    "tolerance": REPRO_F32_TOL,
    "examples": [list(map(str, x)) for x in repro_bad[:20]],
    "pass": not repro_bad,
    "note": ("用同一机器 + 老 expected 重算，须复现 07-31 帧里写死的 y。"
             "老帧 y 是 float32 往返值，故 ≤1e-6 相对差判为存储精度、非口径差；"
             "NA/有值状态与 >1e-6 的差 = 硬 FAIL")}
print(f"[C-PC] bad={len(cpc_bad)}  [repro] hard_fail={len(repro_bad)} "
      f"f32_roundtrip={len(repro_f32)} max_rel={repro_max_rel[0]:.3e}", flush=True)

# ============ 4. G-D: correlation of old vs new y + quantiles ============
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
    def rank(v):
        s = sorted(range(len(v)), key=lambda i: v[i])
        r = [0] * len(v)
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


both = [(o, n) for o, n in gd_pairs if o is not None and n is not None]
bothm = [(o, n) for o, n in gd_pairs_mean if o is not None and n is not None]
logs = [(math.log1p(o), math.log1p(n)) for o, n in both]
rep["G_D"] = {
    "person_years_compared": len(gd_pairs), "both_nonNA_ff": len(both),
    "corr_ff_raw": round(corr(both), 4) if corr(both) else None,
    "corr_ff_log1p": round(corr(logs), 4) if corr(logs) else None,
    "spearman_ff": round(spearman(both), 4) if spearman(both) else None,
    "quantiles_ff_old": quantiles([o for o, _ in both]),
    "quantiles_ff_new": quantiles([n for _, n in both]),
    "median_ratio_old_over_new": round(
        sorted(o / n for o, n in both if n > 0)[len([1 for o, n in both if n > 0]) // 2], 4)
        if any(n > 0 for _, n in both) else None,
    "mean_old": round(sum(o for o, _ in both) / len(both), 4) if both else None,
    "mean_new": round(sum(n for _, n in both) / len(both), 4) if both else None,
    "corr_mean_raw": round(corr(bothm), 4) if corr(bothm) else None,
    "quantiles_mean_old": quantiles([o for o, _ in bothm]),
    "quantiles_mean_new": quantiles([n for _, n in bothm]),
}
print(f"[G-D] n={len(both)} corr_raw={rep['G_D']['corr_ff_raw']} "
      f"log1p={rep['G_D']['corr_ff_log1p']} spearman={rep['G_D']['spearman_ff']}")
print(f"[G-D] old {rep['G_D']['quantiles_ff_old']}")
print(f"[G-D] new {rep['G_D']['quantiles_ff_new']}")

# ============ 5. G-D (2): manual check of 10 person-years (recomputed by an independent path) ============
random.seed(42)
cand = sorted(k for k, a in agg_new.items() if a["pub_count"] >= 2)
picks = random.sample(cand, min(10, len(cand)))
hand, hand_ok = [], True
uidx = {}
for r in u.itertuples():
    if pd.notna(r.publication_year):
        uidx.setdefault((r.incumbent_person_id, int(r.publication_year)), []).append(r)
for pid, yr in picks:
    ws = uidx[(pid, yr)]
    manual_ff, n_val, details = 0.0, 0, []
    for r in ws:
        exp = expected_new.get((r.subfield_id, int(r.publication_year), r.work_type))
        if (r.work_type in ("article", "review") and not bool(r.is_paratext)
                and pd.notna(r.subfield_id) and exp is not None and exp > 0):
            f = int(r.cited_by_count) / exp
            manual_ff += float(r.frac_credit) * f
            n_val += 1
        else:
            f = None
        details.append({"work_id": r.work_id, "cited": int(r.cited_by_count),
                        "type": r.work_type, "sf": str(r.subfield_id),
                        "expected_new": None if exp is None else round(exp, 4),
                        "frac": round(float(r.frac_credit), 6),
                        "fwci_new": None if f is None else round(f, 6)})
    manual = manual_ff if n_val else None
    script = y4(agg_new[(pid, yr)])[0]
    ok = ((manual is None and script is None) or
          (manual is not None and script is not None and abs(manual - script) < 1e-9))
    hand_ok &= ok
    hand.append({"pid": pid, "year": yr, "n_works": len(ws),
                 "manual_fwci_frac": manual, "script_fwci_frac": script,
                 "match": ok, "works": details})
    print(f"[hand] {pid}x{yr} n={len(ws)} manual={manual} script={script} "
          f"→ {'MATCH' if ok else 'FAIL'}")
rep["G_D_hand_check_10py"] = {"cells": hand, "pass": hand_ok}

rep["PASS"] = bool(not cpc_bad and not repro_bad and hand_ok)
json.dump(rep, open(OUT_JSON, "w"), indent=1, ensure_ascii=False, default=str)
print(f"→ {OUT_JSON}\nPASS={rep['PASS']}")
if not rep["PASS"]:
    raise SystemExit(2)
