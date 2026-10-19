#!/usr/bin/env python3
"""R1 robustness job list (P3e F19, unit W1-ROB). Standard library only; reads small CSV/JSON only.

  rob_jobs_r1.py build --mode m --config config/r1/robustness_r1.json --repo DIR --work /work --j1a /work/j1a --out DIR
  rob_jobs_r1.py paths-m --base config/r1/paths_aws.yaml --frames DIR --output DIR --out FILE

`build` writes <out>/units.tsv (the unit list W1-PARPLAN's par_plan.py and run_units.py read) and
<out>/jobs_report.json. One unit = one command run with SAR_OUT=<rob root>/<outdir>, cwd = the repo.
TSV columns: group, name, kind, frame, threads, est_min, cmd, outdir, needs_control.

  kind           p1|p2|p3tp|perm_p1|perm_p2|perm_p3tp|null|p3full|build|control|post
  frame          the PARENT frame basename (memory prediction), '-' for post units
  needs_control  the unit (this group or an earlier one) that must have succeeded first; for a control
                 unit 'succeeded' means EQUAL. Control commands are run in-process by run_units.py:
                   compare whole|union_channel <new.json> <ref.json>
                   content_equal <a> <b> [<a> <b> ...]
                   filter_noop <filter_report.json>

Two modes. 'october' renders the October-grammar families (battery, leaver, loeo, predate_p1, predate_p2,
cut cells, cut predate, T5 perms, P3 perms, nulls) with October's roots, so tests can prove token for token
that the units ARE what October ran (run_all_battery.sh, run_leaver.sh, run_p1_predate.sh,
run_all_predate.sh, run_cuts.sh, cloudkit.parallel_jobs, the T5 progress log). 'm' renders the full catalogue
on the J1a products (/work/j1a/{frames,estimates,events,pairs}) with outputs under
$REPO_DIR/output/r1/robustness in October's relative layout. Controls are re-referenced to the same run's
J1a estimates. In 'm' a unit naming data/frames or cal2026-08-28 is a STOP (an October path left behind
would silently read October data).

Coverage STOPs ('m'): P05_MISSING <star> (an event star without a p05 flag), P05_NOT_SUBSET <field> <event>
(a p05 event outside the event table). Star departure (F20) is out of scope (since 2026-10-15).
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
FIELDS = ("econ", "chemistry", "math_stats")
COLUMNS = ("group", "name", "kind", "frame", "threads", "est_min", "cmd", "outdir", "needs_control")
KINDS = ("p1", "p2", "p3tp", "perm_p1", "perm_p2", "perm_p3tp", "null", "p3full", "build", "control", "post")
GROUPS = ("frames", "cells", "loeo", "perm", "null", "post")
FORBIDDEN = ("data/frames", "cal2026-08-28")
FAMILIES = ("cut_frames", "d7_frames", "doublestar_frames", "nocentre_frames",
            "battery", "leaver", "predate_p1", "predate_p2", "cuts", "cut_predate", "d7", "doublestar", "nocentre",
            "loeo", "perm_t5", "perm_p3", "null", "post")
OCTOBER_FAMILIES = ("battery", "leaver", "loeo", "predate_p1", "predate_p2", "cuts", "cut_predate",
                    "perm_t5", "perm_p3", "null")

DRV_VARIANT = "analysis/robustness/battery_2026-08-29/run_p1_variant.R"
DRV_PREDATE = "analysis/robustness/predate/run_predate.R"
DRV_PERM = "analysis/robustness/inference/run_perm.R"
DRV_NULL = "analysis/robustness/null_sim/run_null.R"
E = "analysis/estimation"
FILTER = "analysis/robustness/threshold_p05/filter_frames.py"
DS_BUILD = "analysis/robustness/sensitivity/build_doublestar.py"
DS_COMP = "analysis/robustness/sensitivity/build_doublestar_complement.py"


class RobStop(SystemExit):
    """A job list that must not be used; the message starts with the STOP code."""

    def __init__(self, msg: str):
        super().__init__(msg)


@dataclasses.dataclass(frozen=True)
class Unit:
    group: str
    name: str
    kind: str
    frame: str
    threads: int
    est_min: int
    cmd: str
    outdir: str
    needs_control: str = ""
    family: str = ""

    def row(self) -> dict:
        return {k: str(getattr(self, k)) for k in COLUMNS}


def load_config(path=None) -> dict:
    p = pathlib.Path(path) if path else HERE.parents[2] / "config" / "r1" / "robustness_r1.json"
    cfg = json.loads(p.read_text(encoding="utf-8"))
    if cfg.get("schema") != "sar.r1.robustness.v1":
        raise RobStop(f"BAD_CONFIG {p}: not sar.r1.robustness.v1")
    return cfg


# ---------------------------------------------------------------------------------------------
# roots
# ---------------------------------------------------------------------------------------------

def _tok(value: str, repo: str, work: str) -> str:
    if value.startswith("repo:"):
        return str(pathlib.Path(repo) / value[5:])
    if value.startswith("work:"):
        return str(pathlib.Path(work) / value[5:])
    return value


def m_roots(cfg: dict, *, repo: str, work: str = "/work", j1a: str | None = None) -> dict:
    """The M roots: J1a products in, outputs under <repo>/output/r1/robustness (absolute)."""
    r, lay = cfg["roots"], cfg["j1a_layout"]
    j = j1a or r["j1a"]
    rob = _tok(r["rob_root"], repo, work)
    sf = str(pathlib.Path(work) / "prod" / cfg["stage_of_group"]["frames"])
    return {"mode": "m", "repo": str(repo), "work": str(work), "j1a": j,
            "frames": str(pathlib.Path(j) / lay["frames"]), "refs": str(pathlib.Path(j) / lay["estimates"]),
            "events": str(pathlib.Path(j) / lay["events"]), "calls": str(pathlib.Path(j) / lay["calls"]),
            "pairs_econ": str(pathlib.Path(j) / lay["pairs_econ"]),
            "p05_flags": str(pathlib.Path(j) / lay["p05_flags"]),
            "map": _tok(r["map_dir"], repo, work), "bin": _tok(r["bin"], repo, work), "tmp": _tok(r["tmp"], repo, work),
            "rob": rob, "rob_rel": r["rob_root"][5:] if r["rob_root"].startswith("repo:") else rob,
            "stage_frames": sf}


def october_roots() -> dict:
    """October's roots: data/frames + analysis/expected, outdirs relative to the robustness root."""
    return {"mode": "october", "frames": "data/frames", "refs": "analysis/expected", "rob": ""}


def _p(root: str, *parts: str) -> str:
    return "/".join([root.rstrip("/")] + list(parts)) if root else "/".join(parts)


# ---------------------------------------------------------------------------------------------
# unit families
# ---------------------------------------------------------------------------------------------

class _B:
    """Unit factory bound to one config/roots/mode."""

    def __init__(self, cfg, R, mode):
        self.cfg, self.R, self.mode = cfg, R, mode
        self.units: list[Unit] = []

    def add(self, group, name, kind, frame, cmd, outdir, needs="", family="", est=None):
        th = int(self.cfg["threads"][kind])
        em = int(est if est is not None else self.cfg["est_min"][kind])
        self.units.append(Unit(group, name, kind, frame, th, em, cmd, outdir, needs, family))

    def fr(self, base):
        return _p(self.R["frames"], base)

    def ref(self, label):
        return _p(self.R["refs"], f"{label}.json")

    def out(self, *parts):
        return _p(self.R["rob"], *parts)

    def control(self, group, name, mode, outdir, label, ref_label, needs, family):
        self.add(group, name, "control", "-", f"compare {mode} {self.out(outdir, label + '.json')} {self.ref(ref_label)}",
                 outdir, needs, family)


def _battery(b: _B):
    g1, chk = b.cfg["golds"]["P1"], b.cfg["checks"]["battery"]
    var = dict(chk["variants"])
    b.add("cells", "ctlrun_battery_full", "p1", "p1_frame_econ.csv",
          f"Rscript {DRV_VARIANT} full {g1['econ']} {b.fr('p1_frame_econ.csv')} none", "battery/control/full", family="battery")
    b.control("cells", "ctl_battery_full", "whole", "battery/control/full", g1["econ"], g1["econ"], "ctlrun_battery_full", "battery")
    b.add("cells", "ctlrun_battery_loeo", "p1", "p1_frame_econ.csv",
          f"Rscript {DRV_VARIANT} loeo {g1['econ']} {b.fr('p1_frame_econ.csv')} NONE", "battery/control/loeo", family="battery")
    b.control("cells", "ctl_battery_loeo", "union_channel", "battery/control/loeo", g1["econ"], g1["econ"],
              "ctlrun_battery_loeo", "battery")
    for loop in chk["loop_order"]:
        for f in FIELDS:
            for pre in loop:
                b.add("cells", f"{pre}_{f}", "p1", f"p1_frame_{f}.csv",
                      f"Rscript {DRV_VARIANT} full {pre}_{f} {b.fr(f'p1_frame_{f}.csv')} {var[pre]}", "battery",
                      "ctl_battery_full", "battery")


def _leaver(b: _B):
    g1, v = b.cfg["golds"]["P1"], b.cfg["checks"]["leaver"]["variant"]
    b.add("cells", "ctlrun_leaver", "p1", "p1_frame_econ.csv",
          f"Rscript {DRV_VARIANT} full {g1['econ']} {b.fr('p1_frame_econ.csv')} none", "leaver/control", family="leaver")
    b.control("cells", "ctl_leaver", "whole", "leaver/control", g1["econ"], g1["econ"], "ctlrun_leaver", "leaver")
    for f in FIELDS:
        b.add("cells", f"P1leave_{f}", "p1", f"p1_frame_{f}.csv",
              f"Rscript {DRV_VARIANT} full P1leave_{f} {b.fr(f'p1_frame_{f}.csv')} {v}", "leaver", "ctl_leaver", "leaver")


def _predate_p1(b: _B):
    g1, chk = b.cfg["golds"]["P1"], b.cfg["checks"]["predate_p1"]
    for f in chk["fields_order"]:
        g, fr = g1[f], b.fr(f"p1_frame_{f}.csv")
        b.add("cells", f"ctlrun_predate_p1_{f}", "p1", f"p1_frame_{f}.csv",
              f"Rscript {DRV_PREDATE} p1 {g} {fr} 0", "predate_p1/control", family="predate_p1")
        b.control("cells", f"ctl_predate_p1_{f}", "whole", "predate_p1/control", g, g, f"ctlrun_predate_p1_{f}", "predate_p1")
        b.add("cells", f"P1pd2_{f}", "p1", f"p1_frame_{f}.csv",
              f"Rscript {DRV_PREDATE} p1 P1pd2_{f} {fr} {chk['shift']}", "predate_p1", f"ctl_predate_p1_{f}", "predate_p1")


def _predate_p2(b: _B):
    g2, chk = b.cfg["golds"]["P2"], b.cfg["checks"]["predate_p2"]
    cf = chk["control_field"]
    b.add("cells", "ctlrun_predate_p2", "p2", f"p2_becoming_{cf}.csv",
          f"Rscript {DRV_PREDATE} p2 {g2[cf]} {b.fr(f'p2_becoming_{cf}.csv')} 0", "predate/control", family="predate_p2")
    b.control("cells", "ctl_predate_p2", "whole", "predate/control", g2[cf], g2[cf], "ctlrun_predate_p2", "predate_p2")
    for f in FIELDS:
        b.add("cells", f"P2pd2_{f}", "p2", f"p2_becoming_{f}.csv",
              f"Rscript {DRV_PREDATE} p2 P2pd2_{f} {b.fr(f'p2_becoming_{f}.csv')} {chk['shift']}", "predate",
              "ctl_predate_p2", "predate_p2")


def _cuts(b: _B):
    chk = b.cfg["checks"]["cuts"]
    specs = (chk["specs_copied"] + chk["specs_estimated"]) if b.mode == "october" else chk["specs_estimated"]
    order = [specs[:2], specs[2:]] if b.mode == "october" else [specs]
    for group_specs in order:
        for f in chk["fields_order"]:
            for c in group_specs:
                needs = "" if b.mode == "october" else "cut_build_abs04p75"
                b.add("cells", f"P3cut_{c}_{f}", "p3tp", f"p3_afar_pos_{f}.parquet",
                      f"Rscript {E}/run_p3_tp.R P3cut_{c}_{f} {b.out('afar_cuts', 'frames', f'p3_afar_{c}_{f}.parquet')}",
                      "afar_cuts/estimates", needs, "cuts")


def _cut_predate(b: _B):
    chk, gp = b.cfg["checks"]["cut_predate"], b.cfg["golds"]["P3pos"]
    for f in chk["fields_order"]:
        b.add("cells", f"ctlrun_pdpos_{f}", "p3tp", f"p3_afar_pos_{f}.parquet",
              f"Rscript {DRV_PREDATE} p3tp P3cut_pos_{f} {b.fr(f'p3_afar_pos_{f}.parquet')} 0",
              "afar_cuts/predate/control", family="cut_predate")
        b.control("cells", f"ctl_pdpos_{f}", "whole", "afar_cuts/predate/control", f"P3cut_pos_{f}",
                  gp.format(field=f), f"ctlrun_pdpos_{f}", "cut_predate")
    for f in chk["fields_order"]:
        b.add("cells", f"P3pos_s2_{f}", "p3tp", f"p3_afar_pos_{f}.parquet",
              f"Rscript {DRV_PREDATE} p3tp P3pos_s2_{f} {b.fr(f'p3_afar_pos_{f}.parquet')} {chk['shift']}",
              "afar_cuts/predate", f"ctl_pdpos_{f}", "cut_predate")


def loeo_events(frame_csv) -> list[str]:
    """The event ids of a Panel 1 frame, sorted (run_all_battery.sh's heredoc: one unit per event)."""
    with open(frame_csv, newline="", encoding="utf-8") as fh:
        return sorted({r["event_id"] for r in csv.DictReader(fh)})


def _loeo(b: _B, frame_path: str):
    needs = "" if b.mode == "october" else "ctl_battery_loeo"
    fr = b.fr("p1_frame_econ.csv")
    for ev in loeo_events(frame_path):
        lab = f"P1loeo_{ev.replace(':', '_')}"
        b.add("loeo", lab, "p1", "p1_frame_econ.csv", f"Rscript {DRV_VARIANT} loeo {lab} {fr} {ev}", "battery/loeo",
              needs, "loeo")


def chunks(lo: int, hi: int, size: int) -> list[tuple[int, int]]:
    out, i = [], lo
    while i <= hi:
        j = min(i + size - 1, hi)
        out.append((i, j))
        i = j + 1
    return out


def _perm_t5(b: _B):
    pc, seed = b.cfg["perm"], b.cfg["seeds"]["perm_p1p2"]
    for mode, lab, frame, ref in pc["cells_p1p2"]:
        for a, z in [(0, 0)] + chunks(1, pc["B"], pc["chunk_p1p2"]):
            if b.mode == "october":
                cmd, od = f"Rscript run_perm.R {mode} {lab} {frame} {ref} {seed} {a} {z}", "out_perm"
            else:
                cmd = f"Rscript {DRV_PERM} {mode} {lab} {b.fr(frame)} {_p(b.R['refs'], ref)} {seed} {a} {z}"
                od = "cloud_t5/fetch/out_perm"
            b.add("perm", f"{lab}_perm_{a}_{z}", f"perm_{mode}", frame, cmd, od, family="perm_t5")


def _perm_p3_null(b: _B, families):
    """cloudkit.parallel_jobs order: per field the perm units, then the null units."""
    pc, nc, sd = b.cfg["perm"], b.cfg["null"], b.cfg["seeds"]
    gp = b.cfg["golds"]["P3pos"]
    for f in FIELDS:
        pq = f"p3_afar_pos_{f}.parquet"
        if "perm_p3" in families:
            lab = f"P3cutpos_{f}"
            for a, z in [(0, 0)] + chunks(1, pc["B"], pc["chunk_p3"][f]):
                if b.mode == "october":
                    cmd, od = f"Rscript run_perm.R p3tp {lab} {pq} P3cut_pos_{f}.json {sd['perm_p3']} {a} {z}", "out_perm"
                else:
                    cmd = (f"Rscript {DRV_PERM} p3tp {lab} {b.fr(pq)} {b.ref(gp.format(field=f))} "
                           f"{sd['perm_p3']} {a} {z}")
                    od = "cloud/fetch/out_perm"
                b.add("perm", f"{lab}_perm_{a}_{z}", "perm_p3tp", pq, cmd, od, family="perm_p3")
        if "null" in families:
            lab = f"NULLpos_{f}"
            for a, z in chunks(1, nc["nsim"], nc["chunk"][f]):
                if b.mode == "october":
                    cmd, od = f"Rscript run_null.R {lab} {pq} {sd['null']} {a} {z} out_null", "out_null"
                else:
                    od = "cloud/fetch/out_null"
                    cmd = f"Rscript {DRV_NULL} {lab} {b.fr(pq)} {sd['null']} {a} {z} {b.out(od)}"
                b.add("null", f"{lab}_null_{a}_{z}", "null", pq, cmd, od, family="null")


# ---- M-only families --------------------------------------------------------------------------

def _post_py(b: _B, sub: str, *args: str) -> str:
    return " ".join(["python3", _p(b.R["bin"], "rob_post_r1.py"), sub, "--repo", b.R["repo"]] + list(args))


def _cut_frames(b: _B):
    R = b.R
    common = ["--frames", R["frames"], "--pairs-econ", R["pairs_econ"], "--pairs-dir", R["frames"],
              "--fields", ",".join(FIELDS), "--out", b.out("afar_cuts", "frames"),
              "--report", b.out("afar_cuts", "cuts_build.json")]
    b.add("frames", "cut_build_posmed", "build", "p3_afar_pos_econ.parquet",
          _post_py(b, "build-cuts", "--specs", "pos,med", *common), "afar_cuts", family="cut_frames")
    pairs = []
    for f in FIELDS:
        for s in ("pos", "med"):
            pairs += [b.out("afar_cuts", "frames", f"p3_afar_{s}_{f}.parquet"), b.fr(f"p3_afar_{s}_{f}.parquet")]
    b.add("frames", "ctl_cut_frames", "control", "-", "content_equal " + " ".join(pairs), "afar_cuts",
          "cut_build_posmed", "cut_frames")
    b.add("frames", "cut_build_abs04p75", "build", "p3_afar_pos_econ.parquet",
          _post_py(b, "build-cuts", "--specs", "abs04,p75", *common), "afar_cuts", "ctl_cut_frames", "cut_frames")


def _d7_frames(b: _B):
    R = b.R
    ctl_rep = b.out("d7", "p05", "control", "filter_report_control_suffix_empty.json")
    b.add("frames", "d7_filter_control", "build", "p3_afar_pos_econ.parquet",
          _post_py(b, "filter-p05", "--frames", R["frames"], "--events-dir", R["events"], "--map-dir", R["map"],
                   "--suffix", "''", "--frames-out", _p(R["tmp"], "d7_control"), "--report", ctl_rep),
          "d7/p05/control", family="d7_frames")
    b.add("frames", "ctl_d7_filter", "control", "-", f"filter_noop {ctl_rep}", "d7/p05/control", "d7_filter_control",
          "d7_frames")
    b.add("frames", "d7_filter_p05", "build", "p3_afar_pos_econ.parquet",
          _post_py(b, "filter-p05", "--frames", R["frames"], "--events-dir", R["events"], "--map-dir", R["map"],
                   "--suffix", b.cfg["checks"]["d7_p05"]["suffix"], "--frames-out", _p(R["stage_frames"], "d7_p05"),
                   "--report", b.out("d7", "p05", "filter_report_p05.json")),
          "d7/p05", "ctl_d7_filter", "d7_frames")


def _doublestar_frames(b: _B):
    R, chk = b.R, b.cfg["checks"]["doublestar"]
    rel = R["rob_rel"]
    b.add("frames", "doublestar_build", "build", "p1_frame_econ.csv",
          f"SAR_ROBUST_OUTDIR={rel}/doublestar SAR_AFAR_MAP_DIR={R['map']} python3 {DS_BUILD} --spec {chk['spec']} "
          f"--fields {','.join(chk['frame_fields'])} --stage {_p(R['stage_frames'], 'doublestar')} "
          f"--events-dir {R['events']} --frames-dir {R['frames']} "
          f"--pairs-none-math {b.fr('pairs_none_math_stats.parquet')}",
          "doublestar", family="doublestar_frames")
    b.add("frames", "doublestar_complement_build", "build", "p1_frame_econ.csv",
          f"SAR_DS_DROPS_DIR={rel}/doublestar SAR_ROBUST_OUTDIR={rel}/doublestar/complement "
          f"python3 {DS_COMP} --stage {_p(R['stage_frames'], 'dscomp')}",
          "doublestar/complement", "doublestar_build", "doublestar_frames")


def nocentre_cmd(cfg: dict, R: dict) -> str:
    """The no-centre rebuild: J1a's frames_chemmath_m call on the incfel rosters, as one `bash -c` unit (run_units
    runs no shell) that sets up J1a's environment - the 11-school edge-table shadow and its paths file. A value is
    repo:<path>, work:<path> or a roots key in braces ({events}, {calls}: the restored J1a products)."""
    nb = cfg["nocentre_build"]
    vals = {k: _tok(v, R["repo"], R["work"]) for k, v in nb["values"].items()}
    unset = sorted(k for k, v in vals.items() if v == "UNSET")
    if unset:
        raise RobStop(f"NOCENTRE_INPUT_UNSET {','.join(unset)} (config/r1/robustness_r1.json nocentre_build.values)")
    vals = {k: v.format(**R) for k, v in vals.items()}
    return nb["cmd"].format(bin=R["bin"], repo=R["repo"], events=R["events"], work=R["work"], tmp=R["tmp"],
                            out=_p(R["stage_frames"], "nocentre"), **vals)


def exempt_paths(cfg: dict) -> tuple[str, ...]:
    """The repo paths an M unit may name although they hold a FORBIDDEN token (robustness_r1.json forbidden_exempt)."""
    return tuple((cfg.get("forbidden_exempt") or {}).get("paths") or ())


def forbidden_hits(text: str, exempt=()) -> list[str]:
    """The FORBIDDEN tokens `text` names once the exact exempt paths are taken out."""
    for p in exempt:
        text = text.replace(p, "")
    return [tok for tok in FORBIDDEN if tok in text]


def _nocentre_frames(b: _B):
    R = b.R
    b.add("frames", "nocentre_build", "build", "p1_frame_chemistry.csv", nocentre_cmd(b.cfg, R), "nocentre",
          family="nocentre_frames", est=b.cfg["est_min"]["build_nocentre"])
    nc = _p(R["stage_frames"], "nocentre", "frames_{field}")
    b.add("frames", "nocentre_pos_build", "build", "p3_afar_pos_chemistry.parquet",
          _post_py(b, "build-cuts", "--specs", "pos", "--frames", nc, "--pairs-dir", nc,
                   "--fields", ",".join(b.cfg["checks"]["nocentre"]["fields"]),
                   "--out", _p(R["stage_frames"], "nocentre_pos"),
                   "--report", b.out("nocentre", "p3pos", "nocentre_afar_pos_report.json")),
          "nocentre/p3pos", "nocentre_build", "nocentre_frames")


def _d7(b: _B):
    d = _p(b.R["stage_frames"], "d7_p05")
    for f in FIELDS:
        b.add("cells", f"P1p05_{f}", "p1", f"p1_frame_{f}.csv", f"Rscript {E}/run_p1.R P1p05_{f} {_p(d, f'p1_frame_{f}.csv')}",
              "d7/p05/estimates", "d7_filter_p05", "d7")
        b.add("cells", f"P2p05_{f}", "p2", f"p2_becoming_{f}.csv",
              f"Rscript {E}/run_p2.R P2p05_{f} {_p(d, f'p2_becoming_{f}.csv')}", "d7/p05/estimates", "d7_filter_p05", "d7")
        b.add("cells", f"P3p05pos_{f}_A_far", "p3tp", f"p3_afar_pos_{f}.parquet",
              f"Rscript {E}/run_p3_tp.R P3p05pos_{f}_A_far {_p(d, f'p3_afar_pos_{f}.parquet')}", "d7/p05/estimates",
              "d7_filter_p05", "d7")


def _doublestar(b: _B):
    sf = b.R["stage_frames"]
    b.add("cells", "P1ds_econ", "p1", "p1_frame_econ.csv", f"Rscript {E}/run_p1.R P1ds_econ {_p(sf, 'doublestar', 'p1_ds_econ.csv')}",
          "doublestar/estimates", "doublestar_build", "doublestar")
    b.add("cells", "P1dsC_econ", "p1", "p1_frame_econ.csv",
          f"Rscript {E}/run_p1.R P1dsC_econ {_p(sf, 'dscomp', 'p1_dsC_econ.csv')}", "doublestar/complement/estimates",
          "doublestar_complement_build", "doublestar")


def _nocentre(b: _B):
    nc = _p(b.R["stage_frames"], "nocentre")
    for f in b.cfg["checks"]["nocentre"]["fields"]:
        d = _p(nc, f"frames_{f}")
        b.add("cells", f"P1nc_{f}", "p1", f"p1_frame_{f}.csv", f"Rscript {E}/run_p1.R P1nc_{f} {_p(d, f'p1_frame_{f}.csv')}",
              "nocentre/estimates", "nocentre_build", "nocentre")
        b.add("cells", f"P2nc_{f}", "p2", f"p2_becoming_{f}.csv",
              f"Rscript {E}/run_p2.R P2nc_{f} {_p(d, f'p2_becoming_{f}.csv')}", "nocentre/estimates", "nocentre_build",
              "nocentre")
        b.add("cells", f"P3nc_pos_{f}_A_far", "p3tp", f"p3_afar_pos_{f}.parquet",
              f"Rscript {E}/run_p3_tp.R P3nc_pos_{f}_A_far "
              f"{_p(b.R['stage_frames'], 'nocentre_pos', f'p3_afar_pos_{f}.parquet')}",
              "nocentre/estimates", "nocentre_pos_build", "nocentre")


def _post(b: _B):
    R, cfg = b.R, b.cfg
    b.add("post", "copy_cuts", "post", "-", _post_py(b, "copy-cuts", "--refs", R["refs"], "--out", b.out("afar_cuts", "estimates")),
          "afar_cuts/estimates", family="post")
    b.add("post", "cut_grid", "post", "-",
          _post_py(b, "cut-grid", "--est", b.out("afar_cuts", "estimates"), "--frames", b.out("afar_cuts", "frames"),
                   "--build", b.out("afar_cuts", "cuts_build.json"), "--out", b.out("afar_cuts", "afar_cut_grid.csv")),
          "afar_cuts", "copy_cuts", "post")
    b.add("post", "loeo_rank", "post", "-",
          _post_py(b, "loeo-rank", "--loeo", b.out("battery", "loeo"), "--ledger", b.fr("p1_events_ledger_econ.csv"),
                   "--canon", b.ref(cfg["golds"]["P1"]["econ"]), "--frame", b.fr("p1_frame_econ.csv"),
                   "--out", b.out("battery", "loeo_ranked.csv")),
          "battery", family="post")
    # M review #11: every configured label and exactly draws 1..B, checked before anything is summarised
    t5_labels = ",".join(lab for _mode, lab, _frame, _ref in cfg["perm"]["cells_p1p2"])
    p3_labels = ",".join(f"P3cutpos_{f}" for f in FIELDS)
    b.add("post", "perm_summary_t5", "post", "-",
          _post_py(b, "perm-summary", "--units-out", b.out("cloud_t5", "fetch", "out_perm"), "--dest", b.out("cloud_t5", "perm"),
                   "--labels", t5_labels, "--B", str(cfg["perm"]["B"])),
          "cloud_t5/perm", family="post")
    b.add("post", "perm_summary_p3", "post", "-",
          _post_py(b, "perm-summary", "--units-out", b.out("cloud", "fetch", "out_perm"), "--dest", b.out("cloud", "perm"),
                   "--labels", p3_labels, "--B", str(cfg["perm"]["B"])),
          "cloud/perm", family="post")
    for f in FIELDS:
        b.add("post", f"null_merge_{f}", "post", "-",
              _post_py(b, "null-merge", "--slices", b.out("cloud", "fetch", "out_null"), "--label", f"NULLpos_{f}",
                       "--nsim", str(cfg["null"]["nsim"]), "--out", b.out("cloud", "null", f"NULLpos_{f}.json")),
              "cloud/null", family="post")
    b.add("post", "nocentre_report", "post", "-",
          _post_py(b, "nocentre-report", "--rob", R["rob"], "--canon-frames", R["frames"],
                   "--variant", _p(R["stage_frames"], "nocentre"),
                   "--fields", ",".join(cfg["checks"]["nocentre"]["fields"]),
                   "--out", b.out("nocentre", "nocentre_report.json")),
          "nocentre", family="post")
    b.add("post", "manifest", "post", "-", _post_py(b, "manifest", "--root", R["rob"]), ".", family="post")
    b.add("post", "report", "post", "-",
          _post_py(b, "report", "--root", R["rob"], "--units-out", _p(R["work"], "prod"),
                   "--out", b.out("rob_custody.json"), "--summary", b.out("rob_report.json")), ".", "manifest", "post")


# ---------------------------------------------------------------------------------------------
# coverage
# ---------------------------------------------------------------------------------------------

def _read_csv(p) -> list[dict]:
    with open(p, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _event_key(field: str, r: dict) -> str:
    return r["event_id"] if field == "econ" else f"{r['author_id']}:{r['school']}"


def _event_star(field: str, r: dict) -> str:
    return r["star_id"] if field == "econ" else r["author_id"]


def coverage(events_dir, p05_flags) -> dict:
    """Every M event star has a p05 flag (P05_MISSING), every p05 event is an event (P05_NOT_SUBSET)."""
    ev = pathlib.Path(events_dir)
    flags = {(r["field"], r["star_id"]) for r in _read_csv(p05_flags)}
    rep = {}
    for f in FIELDS:
        full = _read_csv(ev / f"events_{f}_cal2026-10.csv")
        sub = _read_csv(ev / f"events_{f}_cal2026-10_p05.csv")
        keys = {_event_key(f, r) for r in full}
        for r in full:
            star = _event_star(f, r)
            if (f, star) not in flags:
                raise RobStop(f"P05_MISSING {star} ({f}: no row in {p05_flags})")
        for r in sub:
            if _event_key(f, r) not in keys:
                raise RobStop(f"P05_NOT_SUBSET {f} {_event_key(f, r)}")
        rep[f] = {"events": len(full), "events_p05": len(sub)}
    return rep


# ---------------------------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------------------------

def build_units(cfg: dict, roots: dict, mode: str = "m", families=None, *, loeo_frame=None) -> list[Unit]:
    """The unit list. mode 'october' renders only OCTOBER_FAMILIES (October's grammar and roots)."""
    if mode not in ("m", "october"):
        raise ValueError(mode)
    allowed = OCTOBER_FAMILIES if mode == "october" else FAMILIES
    fam = tuple(allowed) if families is None else tuple(families)
    bad = [x for x in fam if x not in allowed]
    if bad:
        raise RobStop(f"UNKNOWN_FAMILY {bad} for mode {mode}")
    b = _B(cfg, roots, mode)
    steps = {"cut_frames": _cut_frames, "d7_frames": _d7_frames, "doublestar_frames": _doublestar_frames,
             "nocentre_frames": _nocentre_frames, "battery": _battery, "leaver": _leaver, "predate_p1": _predate_p1,
             "predate_p2": _predate_p2, "cuts": _cuts, "cut_predate": _cut_predate, "d7": _d7,
             "doublestar": _doublestar, "nocentre": _nocentre, "perm_t5": _perm_t5, "post": _post}
    p3_done = False
    for name in FAMILIES:            # fixed order (the TSV order); run_units.py selects a group by column
        if name not in fam:
            continue
        if name == "loeo":
            _loeo(b, loeo_frame or _p(roots["frames"], "p1_frame_econ.csv"))
        elif name in ("perm_p3", "null"):
            if not p3_done:          # cloudkit.parallel_jobs order: per field perm units then null units
                _perm_p3_null(b, fam)
                p3_done = True
        else:
            steps[name](b)
    units = list(b.units)
    check_units(units, mode, complete=families is None, exempt=exempt_paths(cfg))
    return units


def check_units(units: list[Unit], mode: str, complete: bool = True, exempt=()) -> None:
    """Unique names, known kinds/groups, needs that run earlier (a family subset may need a unit
    outside it), and - in 'm' - no October path (except the exact `exempt` paths)."""
    names = [u.name for u in units]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise RobStop(f"DUPLICATE_UNIT {dup}")
    known = set(names)
    for u in units:
        if u.kind not in KINDS or u.group not in GROUPS:
            raise RobStop(f"BAD_UNIT {u.name}: kind {u.kind} group {u.group}")
        if "\t" in u.cmd or "\n" in u.cmd:
            raise RobStop(f"BAD_UNIT {u.name}: tab or newline in cmd")
        if complete and u.needs_control and u.needs_control not in known:
            raise RobStop(f"BAD_NEEDS {u.name} -> {u.needs_control}")
        if mode == "m":
            for tok in forbidden_hits(u.cmd, exempt) + forbidden_hits(u.outdir):
                raise RobStop(f"FORBIDDEN_PATH {u.name}: names {tok!r}")
    pos = {n: i for i, n in enumerate(names)}
    for u in units:
        if u.needs_control in pos and GROUPS.index(units[pos[u.needs_control]].group) > GROUPS.index(u.group):
            raise RobStop(f"BAD_NEEDS {u.name} needs {u.needs_control}, which runs in a later group")


def write_tsv(units: list[Unit], path) -> str:
    """Write the unit TSV; returns its sha256 (the joblist digest N8's plan records)."""
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = ["\t".join(COLUMNS)] + ["\t".join(u.row()[k] for k in COLUMNS) for u in units]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read_tsv(path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))


def catalogue(cfg: dict) -> dict:
    """The products M writes (rob-root relative), as the ledgers read them, and the cut list with reasons."""
    F, NC = FIELDS, cfg["checks"]["nocentre"]["fields"]
    prod = []
    prod += [f"battery/{v}_{f}.json" for v, _ in cfg["checks"]["battery"]["variants"] for f in F]
    prod += [f"leaver/P1leave_{f}.json" for f in F]
    prod += [f"predate_p1/P1pd2_{f}.json" for f in F]
    prod += [f"predate/P2pd2_{f}.json" for f in F]
    prod += [f"afar_cuts/estimates/P3cut_{c}_{f}.json" for c in ("pos", "med", "abs04", "p75") for f in F]
    prod += [f"afar_cuts/predate/P3pos_s2_{f}.json" for f in F]
    prod += ["afar_cuts/afar_cut_grid.csv", "afar_cuts/cuts_build.json"]
    prod += [f"d7/p05/estimates/{c}" for f in F for c in (f"P1p05_{f}.json", f"P2p05_{f}.json", f"P3p05pos_{f}_A_far.json")]
    prod += ["d7/p05/filter_report_p05.json"]
    prod += ["doublestar/doublestar_build_report.json", "doublestar/doublestar_drops.csv",
             "doublestar/estimates/P1ds_econ.json", "doublestar/complement/estimates/P1dsC_econ.json",
             "doublestar/complement/dscomp_build_report.json"]
    prod += [f"nocentre/estimates/{c}" for f in NC for c in (f"P1nc_{f}.json", f"P2nc_{f}.json", f"P3nc_pos_{f}_A_far.json")]
    prod += ["nocentre/nocentre_report.json"]
    prod += ["battery/loeo", "battery/loeo_ranked.csv"]
    prod += ["cloud_t5/perm/perm_summary.json", "cloud/perm/perm_summary.json"]
    prod += [f"cloud/null/NULLpos_{f}.json" for f in F]
    return {"products": prod, "cut": cfg["cut"]}


def paths_m(base, frames, output, out) -> None:
    """paths_aws.yaml with frames and output re-pointed (line surgery: keeps every other key and comment)."""
    lines, seen = [], set()
    for ln in pathlib.Path(base).read_text(encoding="utf-8").splitlines():
        key = ln.split(":", 1)[0].strip()
        if key == "frames" and not ln.startswith("#"):
            ln, _ = f'frames: "{frames}"', seen.add(key)
        elif key == "output" and not ln.startswith("#"):
            ln, _ = f'output: "{output}"', seen.add(key)
        lines.append(ln)
    if seen != {"frames", "output"}:
        raise RobStop(f"PATHS_M {base}: keys frames/output not both found")
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(out).write_text("# R1 J1b robustness: paths_aws.yaml with frames -> J1a and output re-pointed "
                                 "(rob_jobs_r1.py paths-m)\n" + "\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1 robustness job list")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--mode", choices=("m",), default="m")
    b.add_argument("--config", required=True)
    b.add_argument("--repo", required=True)
    b.add_argument("--work", required=True)
    b.add_argument("--j1a", required=True)
    b.add_argument("--out", required=True)
    pm = sub.add_parser("paths-m")
    for k in ("--base", "--frames", "--output", "--out"):
        pm.add_argument(k, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "paths-m":
        paths_m(a.base, a.frames, a.output, a.out)
        return 0
    cfg = load_config(a.config)
    roots = m_roots(cfg, repo=os.path.abspath(a.repo), work=a.work, j1a=a.j1a)
    if not pathlib.Path(roots["rob"]).resolve().is_relative_to(pathlib.Path(a.repo).resolve()):
        raise RobStop(f"ROB_ROOT_OUTSIDE_REPO {roots['rob']}")
    cov = coverage(roots["events"], roots["p05_flags"])
    units = build_units(cfg, roots, "m")
    out = pathlib.Path(a.out)
    digest = write_tsv(units, out / "units.tsv")
    groups = {g: sum(u.group == g for u in units) for g in GROUPS}
    rep = {"schema": "sar.r1.rob_jobs.v1", "mode": "m", "roots": roots, "coverage": coverage_note(cov),
           "units": len(units), "groups": groups, "joblist_sha256": digest,
           "est_min_by_group": {g: sum(u.est_min for u in units if u.group == g) for g in GROUPS},
           "cut": cfg["cut"]}
    (out / "jobs_report.json").write_text(json.dumps(rep, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"ROB_JOBS_OK {len(units)} units {groups} sha256 {digest}")
    return 0


def coverage_note(cov: dict) -> dict:
    return {"p05": cov, "departure": "out of scope (author 2026-10-15: no star-departure number printed)"}


if __name__ == "__main__":
    sys.exit(main())
