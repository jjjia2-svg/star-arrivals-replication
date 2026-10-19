#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""caliber_2026-10/run_caliber.py — re-rank every event star of the 2026-08-28 caliber on the
snapshot with ALL per-paper identity cleanups (2026-08-10, 08-15, 08-28 and the 2026-09-22
recheck of 17 economics stars), decide each event with the signed predicates, emit the top-5% flag
the machine always carried but never wrote, and write the October event tables. Repo-authored
launcher; edits no ported file and no frozen artifact.

    export SAR_OUT_ROOT=/private/tmp/<empty dir>
    python3 pipeline/stars/caliber_2026-10/run_caliber.py --execute     # ~10 min, data disk

Phases
  E1  control: the 71 candidates of 2026-08-28 with that caliber's drops and anchors — every row
      must be byte-identical to data/cal2026-08-28/restake_2026-08-28.csv (proves this driver
      IS the 08-28 machine).
  E2  control: the 42 original chemistry/mathematics stars with the 2026-08-10/13 drops+adds —
      pct_after must equal data/star_threshold_restake_final_2026-08-13.csv (legacy) to 4 dp.
  R   the October re-rank: 187 event stars (A5091326353 on his correct id), drops = union of every
      call ever made, adds = the 2026-08-13 split-id adds only (the 08-28 policy: later merges
      are fetch merges, never restake adds), anchors = the 08-28 first_pub anchors.
  V   verdicts: event_cal2026_10 = restake_pass AND gate_age AND in_window (caliber.py); the
      top-5% subset flag event_p05 = pass_p05 AND gate_age AND in_window.
  F   freeze into data/cal2026-10/: restake, verdicts, event tables (08-28 shapes), report, MANIFEST.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import io
import json
import os
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))

from pipeline.lib.paths import PathUnresolved, require_readable, configured   # noqa: E402

OLD_LAYER = REPO / "pipeline" / "stars" / "caliber_2026-08-28"
if str(OLD_LAYER) not in sys.path:
    sys.path.insert(0, str(OLD_LAYER))
import caliber                     # noqa: E402  (the signed predicates, 2026-08-28 layer)
import cleaned_works               # noqa: E402  (calls-table reader)
import restake_equiv               # noqa: E402  (the 72-equivalent ranking machine)

OUT_ROOT_ENV = "SAR_OUT_ROOT"
CAL_OLD = REPO / "data" / "cal2026-08-28"
CAL_NEW = REPO / "data" / "cal2026-10"
RV = REPO / "data" / "raw_verified"
# the 187-row departure-verification ledger: not shipped (names, quoted evidence; restricted deposit)
DEP = REPO / "data" / "departure_verification_2026-09-10" / "departure_verified_2026-09-10.csv"
FIELDS = ("econ", "chemistry", "math_stats")


def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _read_csv(p: pathlib.Path) -> list[dict]:
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_dict_csv(path: pathlib.Path, rows: list[dict], cols: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def _stop(msg: str) -> None:
    print("STOP: " + msg, file=sys.stderr)
    raise SystemExit(3)


def legacy_gold() -> pathlib.Path:
    root, _ = configured("legacy_v2_output")
    return require_readable(pathlib.Path(root) / "multidisc_gold_2026-08-10")


# ---------------------------------------------------------------------------------------------
# historical per-paper calls (drops and adds), read from the frozen tables — nothing hand-typed
# ---------------------------------------------------------------------------------------------
def historical_calls() -> tuple[set, set, dict]:
    """Return (drops, adds, provenance): drops = every (author_id, work_id) adjudicated not the
    star's in 2026-08-10 (3,873 calls), 08-13 surgery preview, 08-15 (385 fnfix calls) and 08-28
    (calls_2026-08-28 exclusions); adds = the 2026-08-13 split-id adds (author-signed merges)."""
    gold = legacy_gold()
    wl = gold / "verify" / "star_work_level_calls_2026-08-10.csv"
    sp = gold / "data" / "_surgery_preview.json"
    fn = gold / "verify" / "fnfix_work_level_calls.csv"
    prov = {"star_work_level_calls_2026-08-10.csv": _sha(wl), "_surgery_preview.json": _sha(sp),
            "fnfix_work_level_calls.csv": _sha(fn), "calls_2026-08-28.csv": _sha(cleaned_works.CALLS_CSV)}
    drops, adds = set(), set()
    for r in _read_csv(wl):
        if r["is_mine"].strip().lower() == "false":
            drops.add((r["author_id"], r["work_id"]))
        main = (r.get("belongs_to_main_id") or "").strip()
        if main and r["is_mine"].strip().lower() == "true":
            adds.add((main, r["work_id"]))
    p = json.load(open(sp, encoding="utf-8"))
    drops |= {tuple(x) for x in p["new_false"]}
    adds |= {tuple(x) for x in p["adds"]}
    for r in _read_csv(fn):
        if r["is_mine"].strip().lower() == "false":
            drops.add((r["author_id"], r["work_id"]))
    drops |= cleaned_works.exclusions()
    return drops, adds, prov


def october_calls() -> tuple[set, list[dict]]:
    rows = cleaned_works.load_calls(CAL_NEW / "calls_2026-10.csv")
    return cleaned_works.exclusions(rows), rows


# ---------------------------------------------------------------------------------------------
# candidates
# ---------------------------------------------------------------------------------------------
def event_star_candidates() -> tuple[list[dict], dict]:
    """The 187 event stars of cal2026-08-28 as restake candidates (author_id, name, field, school,
    arrival_true), with the star-id corrections applied. Names come from the departure table
    (the only shipped file naming every event star)."""
    corr = {r["old_id"]: r for r in _read_csv(CAL_NEW / "star_id_corrections_2026-10.csv")}
    names = {}
    for r in _read_csv(DEP):
        names[(r["star_author_id"], r["discipline"], r["arrival_year"])] = r["star_display_name"]
    cands = []
    for r in _read_csv(RV / "events_econ_cal2026-08-28.csv"):
        sid, arr = r["star_id"], r["arrival_year"]
        nm = names.get((sid, "econ", arr), sid)
        if sid in corr:
            nm = f"{nm} [id corrected {sid}->{corr[sid]['new_id']}]"
            sid = corr[sid]["new_id"]
        cands.append({"author_id": sid, "name": nm, "field": "econ", "school": r["school"],
                      "arrival_true": arr, "event_id_old": r["event_id"]})
    for field in ("chemistry", "math_stats"):
        for r in _read_csv(RV / f"events_{field}_cal2026-08-28.csv"):
            sid = r["author_id"]
            if sid in corr:
                sid = corr[sid]["new_id"]
            cands.append({"author_id": sid, "name": r["display_name"], "field": field,
                          "school": r["school"], "arrival_true": r["arrival_corrected"],
                          "event_id_old": f"{r['author_id']}:{r['school']}"})
    return cands, corr


# ---------------------------------------------------------------------------------------------
# restake with adds (the ported 72 / 50 add-branch; restake_equiv only carries drops)
# ---------------------------------------------------------------------------------------------
def restake_with_adds(con, cands, drop_pairs, add_pairs, out_csv, overrides=None):
    """72_…py:97-116 plus the 50_…py add branch (:118-131): after = aw_raw − drops ∪ adds."""
    L, pool_sql = restake_equiv._screening_modules()
    con.execute("CREATE OR REPLACE TEMP TABLE aw AS SELECT aid, yr, c, sf FROM aw_raw")
    before = restake_equiv._stats(con, cands, "before", L, pool_sql)
    con.execute("CREATE OR REPLACE TEMP TABLE dropt(aid VARCHAR, wid VARCHAR)")
    if drop_pairs:
        con.executemany("INSERT INTO dropt VALUES (?,?)", sorted(drop_pairs))
    con.execute("CREATE OR REPLACE TEMP TABLE addt(aid VARCHAR, wid VARCHAR)")
    if add_pairs:
        con.executemany("INSERT INTO addt VALUES (?,?)", sorted(set(add_pairs)))
    con.execute("""CREATE OR REPLACE TEMP TABLE aw AS
        SELECT aid, yr, c, sf FROM aw_raw r
        WHERE NOT EXISTS (SELECT 1 FROM dropt d WHERE d.aid=r.aid AND d.wid=r.wid)
        UNION ALL
        SELECT DISTINCT a.aid, w.yr, w.c, w.sf
        FROM addt a JOIN (SELECT DISTINCT wid, yr, c, sf FROM aw_raw) w ON w.wid = a.wid
        WHERE NOT EXISTS (SELECT 1 FROM aw_raw r WHERE r.aid=a.aid AND r.wid=a.wid)""")
    after = restake_equiv._stats(con, cands, "after", L, pool_sql, overrides=overrides)
    rows = []
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(restake_equiv.RESTAKE_HEADER)
        for c in cands:
            b, a = before[c["author_id"]], after[c["author_id"]]
            row = [c["author_id"], c["name"], c["field"], c["school"], c["arrival_true"],
                   b["stock"], b["cell"], b["pct"], b["pass_p10"], a["stock"], a["cell"],
                   a["cell_n"], a["pct"], a["pass_p10"], a["note"] or b["note"], a["aage"]]
            w.writerow(row)
            rows.append(row)
    return rows, after


def pass_p05(after: dict, L) -> bool | None:
    """72's rounding convention (pct to 4 dp, cell floor 30) applied at the 5% cut — the signed
    gate for p05 is max(CELL_MIN_N['pct_5'], floor) = 30 (screening_lib.py:33)."""
    if after["pct"] is None:
        return None
    return (after["pct"] >= 1 - L.P05) and after["cell_n"] >= max(L.CELL_MIN_N["pct_5"], L.CELL_MIN_N["floor"])


# ---------------------------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args(argv)
    if not args.execute:
        print("Re-ranks 187 stars on the 24 GB snapshot (minutes, data disk). Re-run with --execute.",
              file=sys.stderr)
        return 2
    out_root = pathlib.Path(os.environ.get(OUT_ROOT_ENV, "").strip() or "")
    if not str(out_root) or not out_root.is_absolute():
        raise PathUnresolved(f"set ${OUT_ROOT_ENV} to an empty absolute directory under /private/tmp")
    out_root.mkdir(parents=True, exist_ok=True)
    if any(out_root.iterdir()):
        raise PathUnresolved(f"${OUT_ROOT_ENV} must be empty: {out_root}")
    report: dict = {"generated": datetime.datetime.now().isoformat(timespec="seconds"),
                    "authority": "the author's design record of 2026-09-22 (private archive) (D5, D7)"}
    L, _ = restake_equiv._screening_modules()

    hist_drops, hist_adds, prov = historical_calls()
    oct_drops, oct_rows = october_calls()
    report["inputs_sha256"] = prov | {"calls_2026-10.csv": _sha(CAL_NEW / "calls_2026-10.csv")}
    report["drops"] = {"historical": len(hist_drops), "october_new": len(oct_drops - hist_drops),
                       "total": len(hist_drops | oct_drops)}
    report["adds_2026-08-13"] = len(hist_adds)
    print(f"[run_caliber] drops historical {len(hist_drops)} + october {len(oct_drops - hist_drops)}; "
          f"adds(08-13) {len(hist_adds)}")

    t0 = time.time()
    con = restake_equiv.connect(out_root / "duck_tmp")
    n_aw = restake_equiv.load_aw_raw(con)
    report["aw_raw_rows"] = n_aw
    print(f"[run_caliber] aw_raw {n_aw:,} rows in {time.time() - t0:.0f} s", flush=True)

    # ---- E1: the 08-28 machine, byte for byte ---------------------------------------------------
    old_cands = _read_csv(CAL_OLD / "candidates_2026-08-28.csv")
    old_lines = restake_equiv.csv_lines_by_author(CAL_OLD / "restake_2026-08-28.csv")
    gold = legacy_gold()
    fn_pairs = {(r["author_id"], r["work_id"]) for r in _read_csv(gold / "verify" / "fnfix_work_level_calls.csv")
                if r["is_mine"].strip().lower() == "false"}
    e1_pairs = fn_pairs | cleaned_works.exclusions()
    e1_csv = out_root / "e1_control.csv"
    restake_equiv.restake(con, old_cands, e1_pairs, e1_csv, overrides=cleaned_works.first_pub_overrides())
    e1_lines = restake_equiv.csv_lines_by_author(e1_csv)
    bad = [a for a in old_lines if e1_lines.get(a) != old_lines[a]]
    report["E1_control"] = {"candidates": len(old_cands), "byte_identical": len(old_cands) - len(bad), "mismatch": bad}
    print(f"[run_caliber] E1: {len(old_cands) - len(bad)}/{len(old_cands)} byte-identical to restake_2026-08-28.csv")
    if bad:
        _stop(f"E1 control mismatch for {bad[:5]}")

    # ---- E2: the 08-13 chemistry/mathematics machine (drops + adds) -----------------------------
    e2_ref = {r["author_id"]: r for r in _read_csv(gold / "data" / "star_threshold_restake_final_2026-08-13.csv")}
    e2_cands = [{"author_id": a, "name": r["name"], "field": r["field"], "school": r["school"],
                 "arrival_true": r["arrival"]} for a, r in e2_ref.items()]
    e2_drops = {(r["author_id"], r["work_id"]) for r in _read_csv(gold / "verify" / "star_work_level_calls_2026-08-10.csv")
                if r["is_mine"].strip().lower() == "false"}
    e2_drops |= {tuple(x) for x in json.load(open(gold / "data" / "_surgery_preview.json"))["new_false"]}
    _, e2_after = restake_with_adds(con, e2_cands, e2_drops, hist_adds, out_root / "e2_control.csv")
    e2_bad = []
    for a, r in e2_ref.items():
        got = e2_after[a]["pct"]
        if got is None or abs(float(r["pct_after"]) - got) > 5e-5:
            e2_bad.append((a, r["pct_after"], got))
    report["E2_control"] = {"candidates": len(e2_ref), "pct_equal_4dp": len(e2_ref) - len(e2_bad), "mismatch": e2_bad}
    print(f"[run_caliber] E2: {len(e2_ref) - len(e2_bad)}/{len(e2_ref)} pct_after equal to the 08-13 table")
    if e2_bad:
        _stop(f"E2 control mismatch: {e2_bad[:5]}")

    # ---- R: the October re-rank -----------------------------------------------------------------
    cands, corr = event_star_candidates()
    assert len(cands) == 187, len(cands)
    all_drops = hist_drops | oct_drops
    rows, after = restake_with_adds(con, cands, all_drops, hist_adds, out_root / "restake_2026-10.csv",
                                    overrides=cleaned_works.first_pub_overrides())
    con.close()

    # ---- V: verdicts ----------------------------------------------------------------------------
    verdicts, dropped = [], []
    for c, row in zip(cands, rows):
        a = after[c["author_id"]]
        ev = caliber.event_verdict(after_pass=a["pass_p10"], aage=a["aage"], arrival_true=c["arrival_true"])
        p05 = pass_p05(a, L)
        ev05 = bool(p05) and caliber.gate_age(a["aage"]) and caliber.in_window(c["arrival_true"])
        reason = "" if ev else ("not_in_pool" if a["pct"] is None else
                                ("below_top10" if not a["pass_p10"] else
                                 ("aage<2" if not caliber.gate_age(a["aage"]) else "outside_window")))
        v = {"author_id": c["author_id"], "name": c["name"], "field": c["field"], "school": c["school"],
             "arrival_true": c["arrival_true"], "event_id_old": c["event_id_old"],
             "before_pct": row[7], "after_pct": a["pct"], "after_cell_n": a["cell_n"], "after_pass": a["pass_p10"],
             "pass_p05": p05, "aage": a["aage"], "gate_age": caliber.gate_age(a["aage"]),
             "in_window": caliber.in_window(c["arrival_true"]), "event_cal2026_10": ev, "event_p05": ev05,
             "reason_if_out": reason, "note": a["note"]}
        verdicts.append(v)
        if not ev:
            dropped.append(v)
    report["events"] = {f: {"in": sum(v["event_cal2026_10"] for v in verdicts if v["field"] == f),
                            "p05": sum(v["event_p05"] for v in verdicts if v["field"] == f),
                            "out": [v["author_id"] for v in dropped if v["field"] == f]} for f in FIELDS}
    print("[run_caliber] events:", json.dumps({f: (d["in"], d["p05"], len(d["out"])) for f, d in report["events"].items()}))

    # ---- F: freeze --------------------------------------------------------------------------------
    CAL_NEW.mkdir(parents=True, exist_ok=True)
    (CAL_NEW / "restake_2026-10.csv").write_bytes((out_root / "restake_2026-10.csv").read_bytes())
    (CAL_NEW / "restake_control_e1_2026-10.csv").write_bytes(e1_csv.read_bytes())
    (CAL_NEW / "restake_control_e2_2026-10.csv").write_bytes((out_root / "e2_control.csv").read_bytes())
    _write_dict_csv(CAL_NEW / "verdicts_2026-10.csv", verdicts, list(verdicts[0].keys()))
    _write_dict_csv(CAL_NEW / "candidates_2026-10.csv", cands, list(cands[0].keys()))
    keep = {v["event_id_old"] for v in verdicts if v["event_cal2026_10"]}
    keep05 = {v["event_id_old"] for v in verdicts if v["event_p05"]}
    for field, src in (("econ", "events_econ_cal2026-08-28.csv"), ("chemistry", "events_chemistry_cal2026-08-28.csv"),
                       ("math_stats", "events_math_stats_cal2026-08-28.csv")):
        text = (RV / src).read_bytes().decode("utf-8")
        lines = [ln for ln in text.split("\n") if ln]
        hdr, body = lines[0], lines[1:]
        def key(ln: str) -> str:
            f = next(csv.reader([ln]))
            return f[0] if field == "econ" else f"{f[2]}:{f[1]}"
        def fix(ln: str) -> str:
            f = next(csv.reader([ln]))
            old = f[1] if field == "econ" else f[2]
            if old in corr:
                new = corr[old]["new_id"]
                if field == "econ":
                    f[0] = f[0].replace(old, new); f[1] = new
                else:
                    f[2] = new
                buf = io.StringIO(); csv.writer(buf, lineterminator="").writerow(f)
                return buf.getvalue()
            return ln
        for name, ks in ((f"events_{field}_cal2026-10.csv", keep), (f"events_{field}_cal2026-10_p05.csv", keep05)):
            out = [hdr] + [fix(ln) for ln in body if key(ln) in ks]
            (CAL_NEW / name).write_text("\n".join(out) + "\n", encoding="utf-8")
    (CAL_NEW / "run_report_2026-10.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    files = sorted(p for p in CAL_NEW.iterdir() if p.is_file() and p.name != "MANIFEST.sha256")
    (CAL_NEW / "MANIFEST.sha256").write_text("".join(f"{_sha(p)}  {p.relative_to(REPO)}\n" for p in files), encoding="utf-8")
    print(f"[run_caliber] frozen {len(files)} files in {CAL_NEW}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
