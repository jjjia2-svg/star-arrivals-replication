"""report_predate_cuts.py — assemble data/cal2026-10/robustness/predate_cuts_report.json for the
predate_cuts robustness group (October caliber, 2026-09-23) and write the MANIFEST.sha256 of each
product directory. Every control verdict is RECOMPUTED here with analysis.lib.compare_json (and
tools.content_equal for the frames), not parsed from the run logs. REPO-AUTHORED.

Usage: setup/.venv/bin/python analysis/robustness/predate/report_predate_cuts.py
"""
import csv, datetime, hashlib, json, pathlib, subprocess, sys

REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from analysis.lib.compare_json import compare                 # noqa: E402
from tools.content_equal import content_equal                 # noqa: E402
from tools.write_manifest import write as write_manifest      # noqa: E402

ROB = REPO / "data/cal2026-10/robustness"
PD, PD1, CUTS = ROB / "predate", ROB / "predate_p1", ROB / "afar_cuts"
X = REPO / "analysis/expected"; D = REPO / "data/frames"
FIELDS = ("econ", "chemistry", "math_stats")
FROZEN_PD, FROZEN_PD1, FROZEN_CUTS = (REPO / "data/predate_2026-08-28", REPO / "data/predate_p1_2026-08-30",
                                      REPO / "data/robustness_afar_cuts_2026-08-30")


def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def jl(p): return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
def rel(p): return pathlib.Path(p).resolve().relative_to(REPO).as_posix()
def verdict(new, exp):
    d = compare(jl(new), jl(exp)); return {"new": rel(new), "expected": rel(exp), "verdict": "EQUAL" if not d else "NOT_EQUAL", "diffs": d}


def r4(x): return None if x is None else round(float(x), 8)


def head_p2(j):   # run_predate.R p2 / p3 (single-cluster) shape
    pdb = j.get("predate", {})
    return {"status": j.get("status"), "ate": r4(j.get("ate")), "se": r4(j.get("se")), "p_joint_effects": j.get("p_joint_effects"),
            "p_joint_placebo": j.get("p_joint_placebo"), "rows": j.get("rows"), "rels_or_grps": j.get("rels", j.get("grps")),
            "events": j.get("events"), "first_ties": j.get("first_ties"),
            "predate": {"shift": pdb.get("shift"), "p_joint_shifted": pdb.get("p_joint_shifted"),
                        "shifted_effects": [{"k": e["k"], "est": r4(e["est"]), "se": r4(e["se"]), "n": e.get("n")} for e in pdb.get("shifted_effects", [])]}
            if pdb else None}


def head_p3tp(j):  # run_p3_tp.R / run_predate.R p3tp shape
    pc, ec, pdb = j.get("pair_cluster", {}), j.get("event_cluster", {}), j.get("predate", {})
    out = {"status": "OK" if "ate" in pc and "ate" in ec else f"pair:{pc.get('status')} event:{ec.get('status')}",
           "rows": j.get("rows"), "pairs": j.get("grps"), "events": j.get("events"), "first_ties": j.get("first_ties"),
           "ate": r4(pc.get("ate")), "se_pair": r4(pc.get("se")), "se_event": r4(ec.get("se")),
           "lb_pair": r4(pc.get("lb")), "ub_pair": r4(pc.get("ub")),
           "p_joint_effects_pair": pc.get("p_joint_effects"), "p_joint_effects_event": ec.get("p_joint_effects")}
    if pdb:
        out["predate"] = {"shift": pdb.get("shift"), "p_joint_shifted": pdb.get("p_joint_shifted"), "aux_status": pdb.get("aux_status"),
                          "shifted_effects": [{"k": e["k"], "est": r4(e["est"]), "se": r4(e["se"]), "n": e.get("n")} for e in pdb.get("shifted_effects", [])],
                          "p_joint_placebo_pair": pc.get("p_joint_placebo")}
    return out


def head_p1(j):
    ch = j.get("channels", {}); pdb = j.get("predate", {})
    out = {"status": "OK" if all(ch[c].get("status") == "OK" for c in ch) else {c: ch[c].get("status") for c in ch},
           "rows_raw": j.get("rows_raw"), "rows_kept": j.get("rows_kept"),
           "channels": {c: {"ate": r4(ch[c].get("ate")), "se": r4(ch[c].get("se")), "p_joint_effects": ch[c].get("p_joint_effects"),
                            "p_joint_placebo": ch[c].get("p_joint_placebo"), "obs": ch[c].get("obs"), "rels": ch[c].get("rels"),
                            "events": ch[c].get("events")} for c in ch}}
    if pdb:
        out["predate"] = {"shift": pdb.get("shift"), "p_joint_shifted": pdb.get("p_joint_shifted"),
                          "shifted_effects": {c: [{"k": e["k"], "est": r4(e["est"]), "se": r4(e["se"]), "n": e.get("n")} for e in v]
                                              for c, v in pdb.get("shifted_effects", {}).items()}}
    return out


def main():
    rep = {"group": "predate_cuts", "caliber": "cal2026-10", "generated": datetime.datetime.now().isoformat(timespec="seconds"),
           "authority": "the author's design record of 2026-09-22 (private archive) (D7; §四 controls first)",
           "r_env": subprocess.run(["Rscript", "-e", 'cat(as.character(getRversion()), as.character(packageVersion("DIDmultiplegtDYN")), as.character(packageVersion("polars")), as.character(packageVersion("data.table")))'],
                                   capture_output=True, text=True).stdout.strip(),
           "python": sys.version.split()[0], "runners": {}, "inputs": {}, "controls": [], "cells": {}, "old_vs_new": {}, "manifests": {}, "notes": []}
    # ---- runners (provenance) --------------------------------------------------------------
    for r in ("analysis/robustness/predate/run_predate.R", "analysis/robustness/predate/run_all_predate.sh",
              "analysis/robustness/predate/run_p1_predate.sh", "analysis/robustness/p3_afar_cuts/run_cuts.sh",
              "analysis/robustness/p3_afar_cuts/build_afar_cut.py", "analysis/robustness/p3_afar/build_afar.py",
              "analysis/estimation/run_p3_tp.R", "analysis/estimation/run_p1.R", "analysis/estimation/run_p2.R", "analysis/estimation/run_p3.R",
              "analysis/robustness/predate/report_predate_cuts.py"):
        rep["runners"][r] = sha(REPO / r)
    # ---- inputs ----------------------------------------------------------------------------
    inputs = [D / f"p1_frame_{f}.csv" for f in FIELDS] + [D / f"p2_becoming_{f}.csv" for f in FIELDS] + \
             [D / f"p3_afar_{f}.parquet" for f in FIELDS] + [D / f"p3_afar_pos_{f}.parquet" for f in FIELDS] + \
             [D / f"p3_afar_med_{f}.parquet" for f in FIELDS] + [D / "p3_slim_math_stats.parquet", D / "p3_slim_ev_math_stats.parquet"] + \
             [D / f"pairs_none_{f}.parquet" for f in ("chemistry", "math_stats")] + \
             [REPO / "output/cal_intermediates/cal2026-10/pairs_unified.csv"] + \
             [X / f"{g}.json" for g in ("P3lb_econ_A_far", "P2_econ_fnfix", "P3_fnfix_math_stats", "P1_econ_fnfix", "P1_fnfix_chemistry", "P1_fnfix_math_stats")] + \
             [X / f"P3{s}_{f}_A_far.json" for f in FIELDS for s in ("pos", "med")]
    for p in inputs:
        rep["inputs"][rel(p)] = sha(p)
    rep["inputs_note"] = ("output/cal_intermediates/cal2026-10/pairs_unified.csv is the October econ pair table (not shipped); "
                          "byte-identical to output/cal_intermediates/pairs_unified.csv (same sha) and to the sha recorded in "
                          "data/cal2026-10/robustness/afar_event_map_pos/afar_event_map_report.json")
    # ---- controls (recomputed) -------------------------------------------------------------
    C = rep["controls"]
    for g in ("P3lb_econ_A_far", "P2_econ_fnfix", "P3_fnfix_math_stats"):
        C.append({"battery": "predate (run_all_predate.sh)", "control": f"{g} shift-0", **verdict(PD / "control" / f"{g}.json", X / f"{g}.json")})
    for f, g in (("econ", "P1_econ_fnfix"), ("chemistry", "P1_fnfix_chemistry"), ("math_stats", "P1_fnfix_math_stats")):
        C.append({"battery": "predate_p1 (run_p1_predate.sh)", "control": f"{g} shift-0 (p1 mode)", **verdict(PD1 / "control" / f"{g}.json", X / f"{g}.json")})
    for f in FIELDS:
        for s in ("pos", "med"):
            name = f"p3_afar_{s}_{f}.parquet"; res = content_equal(CUTS / "frames" / name, D / name)
            C.append({"battery": "afar_cuts (run_cuts.sh)", "control": f"{name} rebuilt (October sources) vs data/frames", "new": rel(CUTS / "frames" / name),
                      "expected": rel(D / name), "verdict": "EQUAL" if res.equal else "NOT_EQUAL", "mode": res.mode, "detail": res.detail if not res.equal else ""})
            C.append({"battery": "afar_cuts (run_cuts.sh)", "control": f"P3cut_{s}_{f} re-run on the rebuilt frame", **verdict(CUTS / "estimates" / f"P3cut_{s}_{f}.json", X / f"P3{s}_{f}_A_far.json")})
        C.append({"battery": "afar_cuts predate (run_cuts.sh)", "control": f"P3cut_pos_{f} shift-0 (p3tp mode, canonical data/frames pos frame)",
                  **verdict(CUTS / "predate/control" / f"P3cut_pos_{f}.json", X / f"P3pos_{f}_A_far.json")})
    rep["controls_summary"] = {"n": len(C), "equal": sum(c["verdict"] == "EQUAL" for c in C), "not_equal": [c["control"] for c in C if c["verdict"] != "EQUAL"]}
    # ---- cells -----------------------------------------------------------------------------
    cells = rep["cells"]
    for f in FIELDS:
        cells[f"P2pd2_{f}"] = {"battery": "predate", "file": rel(PD / f"P2pd2_{f}.json"), "sha256": sha(PD / f"P2pd2_{f}.json"), **head_p2(jl(PD / f"P2pd2_{f}.json"))}
        cells[f"P3pd2_{f}_A_far"] = {"battery": "predate", "file": rel(PD / f"P3pd2_{f}_A_far.json"), "sha256": sha(PD / f"P3pd2_{f}_A_far.json"), **head_p3tp(jl(PD / f"P3pd2_{f}_A_far.json"))}
    cells["P3pd2_math_stats_full"] = {"battery": "predate", "file": rel(PD / "P3pd2_math_stats_full.json"), "sha256": sha(PD / "P3pd2_math_stats_full.json"), **head_p2(jl(PD / "P3pd2_math_stats_full.json"))}
    for f in FIELDS:
        cells[f"P1pd2_{f}"] = {"battery": "predate_p1", "file": rel(PD1 / f"P1pd2_{f}.json"), "sha256": sha(PD1 / f"P1pd2_{f}.json"), **head_p1(jl(PD1 / f"P1pd2_{f}.json"))}
    for f in FIELDS:
        for s in ("pos", "med", "abs04", "p75"):
            p = CUTS / "estimates" / f"P3cut_{s}_{f}.json"
            cells[f"P3cut_{s}_{f}"] = {"battery": "afar_cuts", "file": rel(p), "sha256": sha(p), "frame": rel(CUTS / "frames" / f"p3_afar_{s}_{f}.parquet"),
                                       "frame_sha256": sha(CUTS / "frames" / f"p3_afar_{s}_{f}.parquet"), **head_p3tp(jl(p))}
        p = CUTS / "predate" / f"P3pos_s2_{f}.json"
        cells[f"P3pos_s2_{f}"] = {"battery": "afar_cuts predate", "file": rel(p), "sha256": sha(p), "frame": rel(D / f"p3_afar_pos_{f}.parquet"), **head_p3tp(jl(p))}
    rep["cuts_build"] = jl(CUTS / "cuts_build.json")
    rep["grid"] = list(csv.DictReader(open(CUTS / "afar_cut_grid.csv")))
    aux_failed = [k for k, c in cells.items() if c.get("predate") and (c["predate"].get("aux_status") == "FAILED" or c["predate"].get("p_joint_shifted") is None)]
    rep["cells_summary"] = {"n": len(cells), "ok": sum(c["status"] == "OK" for c in cells.values()), "not_ok": [k for k, c in cells.items() if c["status"] != "OK"],
                            "aux_failed_no_p_joint_shifted": aux_failed}
    rep["notes"] += [
        "P2pd2_math_stats (October): main shifted run OK (ATE +0.000149, SE 0.000226) but its k=2 horizon is exactly 0 (n=4,025) and the auxiliary effects=2 run "
        "fails inside DIDmultiplegtDYN ('infinite or missing values in x'), so predate.p_joint_shifted is not computable for that cell; the October math becoming "
        "panel is the smallest (1,795 relations, 35 first ties vs 2,183/58 on 2026-08-28). Recorded, not patched.",
        "Frozen data/predate_p1_2026-08-30/control/P1_fnfix_math_stats.json was produced from the ECON frame (file=p1_frame_econ.csv, rows_raw=118,393): the producing "
        "heredoc used `declare -A`, which /bin/bash 3.2 does not support, so every field resolved to the last label. The October control uses the math frame (19,910 raw rows) and is EQUAL to its gold.",
        "The frozen P3pos_s0_<field>.json controls carry label P3pos_s0_<field>; compare_json compares `label`, so the October shift-0 control runs under the gold's own label "
        "P3cut_pos_<field> (as analysis/run_all.sh does) and is strictly EQUAL. The shifted cells keep the paper-facing name P3pos_s2_<field>.json.",
        "afar_cut_grid.csv: same columns as the frozen 2026-08-30 grid; `cut` is the full-precision cut for every row (the frozen grid left p75 empty and pinned med via PIN_CANON), "
        "and se_event_pp is the event-clustered SE (the frozen grid printed 0 there because its dig('se_ev') never matched a key). The ledger reads cut_spec/cut/pairs/ate_pp/se_pair_pp only.",
        "analysis/robustness/predate/run_all_predate.sh: one permitted edit (SAR_PREDATE_OUTDIR override, default unchanged; the MANIFEST root follows it) -> its REPO_AUTHORED pin in "
        "tests/test_verbatim_pipeline.py is stale until `tools/repin.sh` is run (tests not edited here).",
        "Not run here (cloud cells, pipeline/aws/cal2026-10): P3pd2_econ_full / P3pd2_chemistry_full and their shift-0 controls. Not regenerated here: data/cal2026-10/MANIFEST.sha256 (integration step).",
        "Chemistry and mathematics pos frames are unchanged by the October caliber (D2 removes network-only persons, never Panel 3 pairs), so P3cut_pos_* and P3pos_s2_* for those two fields reproduce the frozen 2026-08-30 numbers exactly; econ pos moved (88,176 -> 90,325 pairs, 108 -> 111 events).",
    ]
    # ---- old (frozen 08-28/08-30) vs new (October) -----------------------------------------
    ovn = rep["old_vs_new"]
    def pair(old, newk, oldf):
        o = jl(oldf); n = cells[newk]; pdb = n.get("predate") or {}
        return {"old_file": rel(oldf), "old": old(o), "new": {k: n.get(k, pdb.get(k)) for k in old(o)}}   # p_joint_shifted sits under predate
    for f in FIELDS:
        ovn[f"P2pd2_{f}"] = pair(lambda o: {"ate": r4(o["ate"]), "se": r4(o["se"]), "p_joint_shifted": o["predate"]["p_joint_shifted"], "rels_or_grps": o["rels"], "events": o["events"]},
                                 f"P2pd2_{f}", FROZEN_PD / f"P2pd2_{f}.json")
        ovn[f"P3pd2_{f}_A_far"] = pair(lambda o: {"ate": r4(o["pair_cluster"]["ate"]), "se_pair": r4(o["pair_cluster"]["se"]), "p_joint_shifted": o["predate"]["p_joint_shifted"], "pairs": o["grps"], "events": o["events"]},
                                       f"P3pd2_{f}_A_far", FROZEN_PD / f"P3pd2_{f}_A_far.json")
        ovn[f"P1pd2_{f}"] = pair(lambda o: {"p_joint_shifted": o["predate"]["p_joint_shifted"], "rows_kept": o["rows_kept"]}, f"P1pd2_{f}", FROZEN_PD1 / f"P1pd2_{f}.json")
        ovn[f"P3pos_s2_{f}"] = pair(lambda o: {"ate": r4(o["pair_cluster"]["ate"]), "se_pair": r4(o["pair_cluster"]["se"]), "p_joint_shifted": o["predate"]["p_joint_shifted"], "pairs": o["grps"], "events": o["events"]},
                                    f"P3pos_s2_{f}", FROZEN_CUTS / "predate" / f"P3pos_s2_{f}.json")
        for s in ("pos", "med", "abs04", "p75"):
            ovn[f"P3cut_{s}_{f}"] = pair(lambda o: {"ate": r4(o["pair_cluster"]["ate"]), "se_pair": r4(o["pair_cluster"]["se"]), "p_joint_effects_pair": o["pair_cluster"]["p_joint_effects"], "pairs": o["grps"], "events": o["events"]},
                                         f"P3cut_{s}_{f}", FROZEN_CUTS / "estimates" / f"P3cut_{s}_{f}.json")
    ovn["P3pd2_math_stats_full"] = pair(lambda o: {"ate": r4(o["ate"]), "se": r4(o["se"]), "p_joint_shifted": o["predate"]["p_joint_shifted"], "rels_or_grps": o["grps"]},
                                        "P3pd2_math_stats_full", FROZEN_PD / "P3pd2_math_stats_full.json")
    # ---- manifests (paths relative to the repo root) ----------------------------------------
    for d in (PD, PD1, CUTS):
        n = write_manifest(d); rep["manifests"][rel(d / "MANIFEST.sha256")] = {"files": n, "sha256": sha(d / "MANIFEST.sha256")}
    out = ROB / "predate_cuts_report.json"
    out.write_text(json.dumps(rep, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"report: {rel(out)}  controls {rep['controls_summary']['equal']}/{rep['controls_summary']['n']} EQUAL; cells {rep['cells_summary']['ok']}/{rep['cells_summary']['n']} OK")
    return 0 if not rep["controls_summary"]["not_equal"] and not rep["cells_summary"]["not_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
