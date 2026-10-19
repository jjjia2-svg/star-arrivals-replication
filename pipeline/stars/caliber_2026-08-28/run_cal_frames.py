#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""caliber_2026-08-28/run_cal_frames.py — Task-3 driver: the frames rebuild under the author-signed
caliber, all three disciplines, through the PORTED builders (verbatim) with the caliber staging
layer. Repo-authored launcher (declared in `pipeline.lib.paths.LAUNCHERS`).

    export SAR_OUT_ROOT=/private/tmp/<empty dir>       # scratch, NEVER under ~/Documents
    python3 "pipeline/stars/caliber_2026-08-28/run_cal_frames.py" --execute

Phases:
  C  controls — the two rungs this task drives for the first time, re-run on FROZEN inputs first:
     prodlib (staged verbatim) must reproduce the frozen `runs/fnfix` network frames byte for
     byte; the ported union builder must reproduce the frozen union frames up to the documented
     H1 characterisation (only fwci_frac / fwci_frac_ex_star, last-bit ULPs) with a byte-identical
     relationships.csv. A control that fails STOPS the run — a cal build on an uncontrolled rung
     would attribute machine noise to the caliber.
  S  the shadow legacy tree (`frames_stage.build_shadow`): cal event tables + supplement +
     exclusions + derived companions at the exact paths the ported builders resolve, frozen links
     for everything the caliber does not change; $SAR_LEGACY_THESIS points the builders at it.
  G  chemistry / math_stats: prodlib(cal) -> union-gold(cal) -> p1-gold(cal) -> p2-gold(cal)
     -> make_slim(cal), each stage's output installed into the shadow where the next resolves it.
  E  economics: ledger -> p1-econ -> split -> p2-econ -> make_slim on the surgered inputs
     (econ's un-ported rungs change by A5044432173's event REMOVAL only — register ruling R-T3-1).
  A  the A_far build (50_leftbehind + 60_lb_tau) over all three disciplines from the shadow.
  X  the row-level accounting: every produced frame against its frozen counterpart, every row
     in/out/changed attributed to a NAMED cause; T2's pinned expectations evaluated verbatim —
     any deviation is REPORTED as a deviation, never absorbed into a widened expectation.
  F  freeze into data/cal2026-08-28/frames/ + MANIFEST. An accounting that does not CLOSE
     (unaccounted rows) freezes NOTHING for that discipline and stops with samples.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import io
import json
import os
import pathlib
import re
import runpy
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))

from pipeline.lib.paths import OUT_ROOT_ENV, PathUnresolved, staged_run  # noqa: E402

sys.path.insert(0, str(HERE))
import frames_stage as fs         # noqa: E402

PY = sys.executable
GOLD = "multidisc_gold_2026-08-10"
ECON = "econ_fnfix_2026-08-15"
FIELDS_GOLD = ("chemistry", "math_stats")

STOPS: list[str] = []
PIN_DEVIATIONS: list[dict] = []


def stop(msg: str) -> None:
    STOPS.append(msg)
    print(f"\n*** STOP: {msg}", flush=True)


def log(msg: str) -> None:
    print(f"[run_cal_frames] {msg}", flush=True)


# ---------------------------------------------------------------------------------------------
# stage runners
# ---------------------------------------------------------------------------------------------

def run_stage(stage: str, scratch: pathlib.Path, args: tuple[str, ...] = (),
              execute: bool = False, shadow: pathlib.Path | None = None) -> dict:
    """One run_frames stage in a subprocess (the M3 acceptance pattern): returns the run dir and
    the launcher's own produced-report {abs path: sha256}."""
    scratch.mkdir(parents=True, exist_ok=False)
    cmd = [PY, str(REPO / "pipeline/frames/run_frames.py"), stage]
    if execute:
        cmd.append("--execute")
    if args:
        cmd += ["--", *args]
    env = {**os.environ, OUT_ROOT_ENV: str(scratch)}
    env.pop("SAR_LEGACY_THESIS", None)
    if shadow is not None:
        env["SAR_LEGACY_THESIS"] = str(shadow)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, env=env)
    out = proc.stdout + proc.stderr
    if proc.returncode != 0:
        raise RuntimeError(f"run_frames.py {stage} {args} failed ({proc.returncode}):\n{out[-4000:]}")
    m = re.search(r"run directory -> (.+)", proc.stdout)
    produced = {p: s for p, s in
                re.findall(r"^\s+OK\s+(/.+?)\s+\(\d[\d,]* B, sha256 ([0-9a-f]{64})\)$",
                           proc.stdout, re.M)}
    assert m and produced, f"launcher reported no run dir / outputs:\n{out[-2000:]}"
    log(f"stage {stage} {' '.join(args)} finished in {time.time() - t0:.1f} s "
        f"({len(produced)} outputs)" + (" [shadow]" if shadow else " [real tree]"))
    return {"run_dir": pathlib.Path(m.group(1).strip()), "produced": produced,
            "secs": round(time.time() - t0, 1), "stage": stage, "args": list(args)}


def run_prodlib(field: str, mirror: pathlib.Path, shadow_root: pathlib.Path | None,
                report: dict) -> pathlib.Path:
    """Stage the prodlib trio verbatim and run build_frame.py on a control or cal config,
    IN PROCESS with this repository's unit modules pre-imported and origin-asserted."""
    shas = fs.stage_prodlib(mirror)
    run_dir = mirror / "runs" / field
    cfg = fs.prodlib_config(field, shadow_root or mirror, run_dir, cal=shadow_root is not None)
    cfg_p = mirror / f"config_{field}.json"
    cfg_p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    for line in fs.preimport_prodlib_units():
        report.setdefault("unit_modules", []).append(line)
    target = mirror / "code" / "build_frame.py"
    argv0 = sys.argv
    t0 = time.time()
    try:
        sys.argv = [str(target), str(cfg_p)]
        buf = io.StringIO()
        from contextlib import redirect_stdout                       # noqa: PLC0415
        with staged_run(target), redirect_stdout(buf):
            runpy.run_path(str(target), run_name="__main__")
    finally:
        sys.argv = argv0
    tail = buf.getvalue().strip().splitlines()
    assert tail and tail[-1].startswith("BUILD_DONE"), tail[-3:]
    out = run_dir / "data" / "analysis_frame_p01_52ev_topicdose_2026-07-21.csv"
    assert out.is_file(), out
    report.setdefault("prodlib", {})[f"{field}:{'cal' if shadow_root else 'control'}"] = {
        "code_sha256": shas, "secs": round(time.time() - t0, 1),
        "frame": str(out), "frame_sha256": fs.sha(out)}
    log(f"prodlib {field} ({'cal' if shadow_root else 'control'}) finished in "
        f"{time.time() - t0:.1f} s")
    return out


def run_make_slim(field: str, src: pathlib.Path, out_dir: pathlib.Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=False)
    ev = out_dir / f"p3_slim_ev_{field}.parquet"
    noev = out_dir / f"p3_slim_{field}.parquet"
    proc = subprocess.run([PY, str(REPO / "pipeline/frames/make_slim.py"), field, str(src),
                           str(ev), "--noev", str(noev)],
                          cwd=REPO, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    stats = eval(proc.stdout.strip().splitlines()[-1], {"__builtins__": {}}, {})  # noqa: S307
    return {"ev": ev, "noev": noev, "stats": stats}


# ---------------------------------------------------------------------------------------------
# controls (phase C)
# ---------------------------------------------------------------------------------------------

def union_characterise(frozen: pathlib.Path, rebuilt: pathlib.Path) -> dict:
    """The H1 characterisation: same line count, only fwci_frac / fwci_frac_ex_star may differ,
    every difference within 8 ULP (the M3 bound for the sibling builder)."""
    fa = open(frozen, newline="", encoding="utf-8").readlines()
    fb = open(rebuilt, newline="", encoding="utf-8").readlines()
    if len(fa) != len(fb):
        return {"ok": False, "reason": f"line counts differ {len(fa)} vs {len(fb)}"}
    cols = next(csv.reader([fa[0]]))
    n, worst, badcols = 0, 0, set()
    for a, b in zip(fa[1:], fb[1:]):
        if a == b:
            continue
        n += 1
        ca, cb = next(csv.reader([a])), next(csv.reader([b]))
        for j, (x, y) in enumerate(zip(ca, cb)):
            if x != y:
                if cols[j] not in ("fwci_frac", "fwci_frac_ex_star"):
                    badcols.add(cols[j])
                else:
                    try:
                        worst = max(worst, fs.ulps(float(x), float(y)))
                    except ValueError:
                        badcols.add(cols[j])
    ok = not badcols and worst <= 8
    return {"ok": ok, "differing_lines": n, "of": len(fa) - 1, "worst_ulp": worst,
            "unexpected_columns": sorted(badcols)}


def phase_controls(root: pathlib.Path, report: dict) -> None:
    v2 = fs.real_v2()
    for field in FIELDS_GOLD:
        out = run_prodlib(field, root / f"ctl_prodlib_{field}", None, report)
        frozen = v2 / GOLD / "runs/fnfix" / field / "data" / \
            "analysis_frame_p01_52ev_topicdose_2026-07-21.csv"
        equal = fs.sha(out) == fs.sha(frozen)
        report.setdefault("controls", {})[f"prodlib_{field}"] = \
            "BYTE_EQUAL" if equal else "NOT_EQUAL"
        if not equal:
            stop(f"prodlib control ({field}) is NOT byte-equal to the frozen runs/fnfix frame — "
                 f"a cal run on this rung would mix machine noise into the caliber accounting")
    for field in FIELDS_GOLD:
        st = run_stage("union-gold", root / f"ctl_union_{field}", ("--field", field), execute=True)
        rd = st["run_dir"]
        frozen_dir = v2 / GOLD / "data/fnfix" / f"union_frame_{field}"
        rel_equal = fs.sha(rd / f"data/fnfix/union_frame_{field}/relationships.csv") == \
            fs.sha(frozen_dir / "relationships.csv")
        ch = union_characterise(frozen_dir / f"analysis_frame_{field}_2026-08-10.csv",
                                rd / f"data/fnfix/union_frame_{field}/analysis_frame_{field}_2026-08-10.csv")
        report["controls"][f"union_{field}"] = {
            "relationships": "BYTE_EQUAL" if rel_equal else "NOT_EQUAL",
            "frame": ch}
        if not rel_equal:
            stop(f"union control ({field}): relationships.csv is not byte-equal to the frozen one")
        if not ch["ok"]:
            stop(f"union control ({field}): the frame differs beyond the documented H1 "
                 f"characterisation: {ch}")


# ---------------------------------------------------------------------------------------------
# accounting helpers (phase X)
# ---------------------------------------------------------------------------------------------

def pin_eval(name: str, expected, measured, note: str = "") -> None:
    """Evaluate one T2 pin verbatim; a mismatch is recorded as a DEVIATION (loudly), never
    absorbed."""
    ok = expected == measured
    entry = {"pin": name, "expected": expected, "measured": measured,
             "status": "PASS" if ok else "DEVIATION", "note": note}
    if not ok:
        PIN_DEVIATIONS.append(entry)
        print(f"  !! T2-PIN DEVIATION {name}: expected {expected}, measured {measured}"
              + (f"  ({note})" if note else ""), flush=True)
    else:
        print(f"  ok T2 pin {name}: {measured}", flush=True)
    REPORT.setdefault("t2_pin_evaluation", []).append(entry)


REPORT: dict = {}


# ---------------------------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--execute", action="store_true",
                    help="required: many SSD-scanning builder runs (minutes, data disk)")
    args = ap.parse_args(argv)
    if not args.execute:
        print("This drives every frame builder several times against the data disk (minutes). "
              "Re-run with --execute.", file=sys.stderr)
        return 2
    out_root = os.environ.get(OUT_ROOT_ENV, "").strip()
    if not out_root:
        raise PathUnresolved(f"set ${OUT_ROOT_ENV} to an empty absolute directory under /private/tmp")
    root = pathlib.Path(out_root)
    if any(root.iterdir()):
        raise PathUnresolved(f"${OUT_ROOT_ENV} must be empty: {root}")
    REPORT.update({"generated": datetime.datetime.now().isoformat(timespec="seconds"),
                   "authority": "the author's decision record of 2026-08-28 (private archive)",
                   "task": "T3 frames rebuild under cal2026-08-28"})
    t_all = time.time()
    v2 = fs.real_v2()

    # ---- C: controls ----------------------------------------------------------------------------
    log("phase C: controls")
    phase_controls(root, REPORT)
    if STOPS:
        return finish(root, ok=False)

    # ---- S: the shadow --------------------------------------------------------------------------
    log("phase S: shadow legacy tree")
    shadow_root = root / "shadow"
    sh, surgery = fs.build_shadow(shadow_root)
    REPORT["surgery"] = surgery
    log(f"shadow built: {len(sh.entries)} entries "
        f"(econ surgery: {surgery['pre_y_frame_rows_removed']} pre-y rows, "
        f"{surgery['prodlib_frame_rows_removed']} prodlib rows, "
        f"{surgery['relationships_rows_removed']} relationships rows removed)")

    # ---- G: chemistry / math_stats --------------------------------------------------------------
    stages: dict[str, dict] = {}
    for field in FIELDS_GOLD:
        log(f"phase G [{field}]: prodlib(cal)")
        out = run_prodlib(field, root / f"cal_prodlib_{field}", shadow_root, REPORT)
        sh.install(f"{GOLD}/runs/fnfix/{field}/data/analysis_frame_p01_52ev_topicdose_2026-07-21.csv",
                   out, f"cal-stage:prodlib {field}")
        st = run_stage("union-gold", root / f"cal_union_{field}", ("--field", field),
                       execute=True, shadow=shadow_root)
        stages[f"union_{field}"] = st
        for name in (f"analysis_frame_{field}_2026-08-10.csv", "relationships.csv",
                     "build_report.json", "funnel.json"):
            sh.install(f"{GOLD}/data/fnfix/union_frame_{field}/{name}",
                       st["run_dir"] / f"data/fnfix/union_frame_{field}/{name}",
                       f"cal-stage:union-gold {field}")
        st = run_stage("p1-gold", root / f"cal_p1_{field}", ("--field", field),
                       execute=True, shadow=shadow_root)
        stages[f"p1_{field}"] = st
        sh.install(f"{GOLD}/data/fnfix/analysis_frame_{field}_new_gold_2026-08-10.csv",
                   st["run_dir"] / f"data/fnfix/analysis_frame_{field}_new_gold_2026-08-10.csv",
                   f"cal-stage:p1-gold {field}")
        st = run_stage("p2-gold", root / f"cal_p2_{field}", ("--field", field, "--panel3", "full"),
                       execute=True, shadow=shadow_root)
        stages[f"p2_{field}"] = st
        for name in ("becoming_none.csv", "pairs_none.parquet", "pairs_slim_none.parquet"):
            sh.install(f"{GOLD}/data/fnfix/panels23_{field}_gold/{name}",
                       st["run_dir"] / f"data/fnfix/panels23_{field}_gold/{name}",
                       f"cal-stage:p2-gold {field}")
        stages[f"slim_{field}"] = run_make_slim(
            field, sh.path(f"{GOLD}/data/fnfix/panels23_{field}_gold/pairs_none.parquet"),
            root / f"cal_slim_{field}")

    # ---- E: economics ---------------------------------------------------------------------------
    log("phase E [econ]")
    st = run_stage("ledger", root / "cal_ledger", (), shadow=shadow_root)
    stages["ledger"] = st
    st = run_stage("p1-econ", root / "cal_p1_econ", (), execute=True, shadow=shadow_root)
    stages["p1_econ"] = st
    sh.install(f"{ECON}/data/analysis_frame_econ920_unified_fullsnap_2026-08-13.csv",
               st["run_dir"] / "data/analysis_frame_econ920_unified_fullsnap_2026-08-13.csv",
               "cal-stage:p1-econ")
    st = run_stage("split", root / "cal_split", (), shadow=shadow_root)
    stages["split"] = st
    st = run_stage("p2-econ", root / "cal_p2_econ", (), execute=True, shadow=shadow_root)
    stages["p2_econ"] = st
    for name in ("becoming_unified.csv", "pairs_unified.csv"):
        sh.install(f"{ECON}/data/{name}", st["run_dir"] / f"data/{name}", "cal-stage:p2-econ")
    stages["slim_econ"] = run_make_slim("econ", sh.path(f"{ECON}/data/pairs_unified.csv"),
                                        root / "cal_slim_econ")

    # ---- A: the A_far build over all three disciplines ------------------------------------------
    log("phase A [afar]")
    st = run_stage("afar", root / "cal_afar", (), shadow=shadow_root)
    stages["afar"] = st

    REPORT["stages"] = {k: {kk: (str(vv) if isinstance(vv, pathlib.Path) else vv)
                            for kk, vv in v.items() if kk != "produced"}
                        for k, v in stages.items()}
    REPORT["staging_manifest_entries"] = len(sh.entries)

    # ---- X: the accounting ----------------------------------------------------------------------
    log("phase X: row-level accounting")
    from cal_accounting import run_accounting                        # noqa: PLC0415
    accounting = run_accounting(REPO, v2, root, shadow_root, stages, pin_eval, stop, log)
    REPORT["accounting"] = accounting

    # ---- F: freeze ------------------------------------------------------------------------------
    REPORT["total_secs"] = round(time.time() - t_all, 1)
    return finish(root, ok=not STOPS, shadow=sh, stages=stages, shadow_root=shadow_root)


def finish(root: pathlib.Path, ok: bool, shadow=None, stages=None,
           shadow_root: pathlib.Path | None = None) -> int:
    REPORT["pin_deviations"] = PIN_DEVIATIONS
    REPORT["stops"] = STOPS
    if not ok:
        (root / "frames_run_report_FAILED.json").write_text(
            json.dumps(REPORT, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        log(f"{len(STOPS)} STOP condition(s) — NOTHING frozen. Report at "
            f"{root / 'frames_run_report_FAILED.json'}")
        return 1
    out = fs.FRAMES_OUT
    out.mkdir(parents=True, exist_ok=True)
    collect = _collection_map(stages, shadow_root)
    for dest_name, src in collect.items():
        (out / dest_name).write_bytes(pathlib.Path(src).read_bytes())
    (out / "staging_manifest_2026-08-28.json").write_text(
        json.dumps({"entries": shadow.manifest()}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    (out / "frames_run_report_2026-08-28.json").write_text(
        json.dumps(REPORT, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    manifest = "".join(
        f"{fs.sha(f)}  data/cal2026-08-28/{f.relative_to(fs.CAL_DIR).as_posix()}\n"
        for f in sorted(fs.CAL_DIR.rglob("*"))
        if f.is_file() and f.name != "MANIFEST.sha256")
    (fs.CAL_DIR / "MANIFEST.sha256").write_text(manifest, encoding="utf-8")
    log(f"frozen {len(collect) + 2} files into {out}; MANIFEST regenerated "
        f"({manifest.count(chr(10))} entries)")
    if PIN_DEVIATIONS:
        log(f"NOTE: {len(PIN_DEVIATIONS)} T2-pin DEVIATION(s) recorded — see the report; the "
            f"chem/math acceptance is OPEN pending the author's ruling (NOT absorbed).")
    return 0


def _collection_map(stages: dict, shadow_root: pathlib.Path) -> dict[str, pathlib.Path]:
    """frozen-set basename -> produced file. Same basenames as data/frames/ (the caliber dir
    carries the caliber); econ's new-events split is honestly named new37."""
    rd = {k: v["run_dir"] for k, v in stages.items() if "run_dir" in v}
    m = {
        "p1_events_ledger_econ.csv": rd["ledger"] / "data/event_ledger_fnfix.csv",
        "p1_frame_econ.csv":
            rd["p1_econ"] / "data/analysis_frame_econ920_unified_fullsnap_2026-08-13.csv",
        "p1_frame_econ_old79.csv": rd["split"] / "data/analysis_frame_econ_fnfix_old79.csv",
        "p1_frame_econ_new37.csv": rd["split"] / "data/analysis_frame_econ_fnfix_new38.csv",
        "p2_becoming_econ.csv": rd["p2_econ"] / "data/becoming_unified.csv",
        "p3_afar_counts.csv": rd["afar"] / "data/lb_counts.csv",
        "p3_afar_tau_profile.csv": rd["afar"] / "data/lb_tau_profile.csv",
        # the surgered econ relationship table (the caliber's population record for econ)
        "relationships_econ.csv": shadow_root / "v2_output" / ECON / "data/relationships.csv",
    }
    for field in FIELDS_GOLD:
        short = field
        m[f"p1_frame_{short}.csv"] = \
            rd[f"p1_{field}"] / f"data/fnfix/analysis_frame_{field}_new_gold_2026-08-10.csv"
        m[f"p2_becoming_{short}.csv"] = \
            rd[f"p2_{field}"] / f"data/fnfix/panels23_{field}_gold/becoming_none.csv"
        m[f"pairs_none_{short}.parquet"] = \
            rd[f"p2_{field}"] / f"data/fnfix/panels23_{field}_gold/pairs_none.parquet"
        m[f"relationships_{short}.csv"] = \
            rd[f"union_{field}"] / f"data/fnfix/union_frame_{field}/relationships.csv"
        m[f"union_build_report_{short}.json"] = \
            rd[f"union_{field}"] / f"data/fnfix/union_frame_{field}/build_report.json"
    for field in ("econ",) + FIELDS_GOLD:
        m[f"p3_slim_ev_{field}.parquet"] = stages[f"slim_{field}"]["ev"]
        m[f"p3_slim_{field}.parquet"] = stages[f"slim_{field}"]["noev"]
        m[f"p3_afar_{field}.parquet"] = rd["afar"] / f"data/pairs_slim_lb_{field}_A_far.parquet"
    return m


if __name__ == "__main__":
    raise SystemExit(main())
