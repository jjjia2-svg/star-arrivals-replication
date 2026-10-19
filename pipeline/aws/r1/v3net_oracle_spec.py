#!/usr/bin/env python3
"""R1 V3-NET oracle spec (batch B4): rebuild October's oracle inputs on the big host and write the spec that
network_freeze.oracle() reads (schema sar.r1.v3net_oracle_spec.v1; tests/test_r1_network_freeze_real.py reads
it from $SAR_V3NET_ORACLE). Runs on an R1 instance only; every location comes from $SAR_PATHS_CONFIG.

    v3net_oracle_spec.py build --work DIR --spec FILE --report FILE [--config config/r1/B0.json]
                               [--parts chemmath,econ]

Why a builder. The oracle classifies October's own prodlib runs and frames. Their inputs - the rendered
prodlib configs, the D2-filtered chemistry / mathematics frames, the economics network frame after filters
(c)+(d) - are scratch of the October chains: no job keeps them (J0's run_config.py keeps only a step's
top-level reports). They are rebuilt here, in config B0, by the very functions J1a's M drivers run:

  chemmath  chemmath_m.py's b0 setup (the October shadow: stage.build_shadow, October tables, the 08-28
            stars_excluded list, the frozen rosters), then its steps 1-2 per field: run_prodlib_m
            (stage.render_config + stage.run_prodlib) and d2_step (the in-post filter).
              observe {label: <field>, field, config: <mirror>/config_<field>.json, event_table: the table}
              frames  {label: <field>, frame: the D2-filtered frame, config: the same, event_table: the same}
  econ      econ920_m.py's October plan (plan_october + make_ctx, exactly as run_october_plan) through its
            first five M-phase steps: shadow, ledger, star_set, regenerate, events_filter (star_set only writes
            the run's star set in B0; REGEN-AGE moved it ahead of regenerate). October's five controls are
            not re-run here (tests/test_r1_econ920_m_real.py runs them on the same host).
              observe {label: econ, config: the regeneration prodlib config = the all-events economics
                       prodlib run on the October econ table, event_table: data/cal2026-10's econ table}
              frames  net1 split as econ920_m's network_freeze step splits it (econ920_m.split_net1), each part
                      with the graph that step gives it (econ920_m.freeze_graphs): 'econ' = the July rows (graph =
                      the regeneration config's edges / works globs + the econ shadow's concatenated supplement +
                      the U2 person map; u5_dose = U5's dose_p01 table when present), 'econ_fnfix' = the
                      2026-08-15 prodlib rows of the fn-fix events (graph = that run's own frozen config: its
                      snapshot copy with the 07-24 overlay, its person map with the 07-24 'P_<author id>'
                      singletons, the fnfix supplement), 'econ_regenerated' = the regenerated rows (A5091326353's event in
                      October) with the regeneration config.
The graph per row is the default the M code implements (decision sheet: "which graph classifies a
relation" = the row's builder's graph); this file chooses nothing new. t-big-04: classifying the 08-15 rows on
the July graph left two relations UNEXPLAINED - incumbents that exist only in the 08-15 run's person map.

Each part runs in its own process (`part NAME`), so a part's failure leaves the others. The spec is always
written with the parts that succeeded (the oracle test then names the missing labels); --report records each
part's result, rc and counts (ids and counts only). Exit 0 iff every part succeeded.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
_MARK = pathlib.Path("pipeline/aws/r1/chemmath_m.py")
HOSTS = ("ec2-r1-test", "ec2-r1")
SCHEMA = "sar.r1.v3net_oracle_spec.v1"
REPORT_SCHEMA = "sar.r1.v3net_oracle_spec_build.v1"
PARTS = ("chemmath", "econ")
CHEMMATH_FIELDS = ("chemistry", "math_stats")
#: econ920_m.ORDER's first five steps: the network frame after filters (c)+(d), nothing after it
ECON_STEPS = ("shadow", "ledger", "star_set", "regenerate", "events_filter")
ECON_TABLE = "events_econ_cal2026-10.csv"
#: U5's frozen dose_p01 table under the derived root (the July econ rows' degree2_bridge_frozen, when it carries it)
U5_DOSE_REL = "u5_ship_11school_p10_80ev_2026-07-22/dose_p01/_frozen/dose.parquet"
PATCH_OCTOBER_REL = "patch_supplement_2026-10/works_by_author_supplement_2026-10.jsonl"
#: econ920_m.FREEZE_PARTS -> the oracle's frame labels
ECON_LABELS = {"july": "econ", "fnfix": "econ_fnfix", "regenerated": "econ_regenerated"}


def _find_repo() -> pathlib.Path:
    """The checkout this file sits in, else $REPO_DIR (the B4 job runs a copy at /work/)."""
    cands = []
    if len(HERE.parents) >= 3 and (HERE.parents[2] / _MARK).is_file():
        cands.append(HERE.parents[2])
    env = os.environ.get("REPO_DIR", "").strip()
    if env:
        cands.append(pathlib.Path(env))
    for c in cands:
        if (c / _MARK).is_file():
            return c.resolve()
    raise SystemExit("v3net_oracle_spec: cannot find the repository (run it from the checkout or set $REPO_DIR)")


def _drivers_on_path(repo: pathlib.Path) -> None:
    for p in (str(repo), str(repo / "pipeline" / "aws" / "r1")):
        if p not in sys.path:
            sys.path.insert(0, p)


# ---------------------------------------------------------------------------------------------
# the two parts (each in its own process)
# ---------------------------------------------------------------------------------------------

def part_chemmath(work: pathlib.Path, config: pathlib.Path, fields=CHEMMATH_FIELDS, cm=None) -> dict:
    if cm is None:
        import chemmath_m as cm                                          # noqa: PLC0415
    cfg = cm.load_config(config)
    cm.check_mode(cfg, "b0")
    scratch = work / "chemmath"
    scratch.mkdir(parents=True, exist_ok=False)
    R = {"edges": cm.edge_env(cfg)}
    ctx = cm.setup_b0(cfg, None, scratch, R)
    observe, frames, counts = [], [], {}
    for f in fields:
        table = pathlib.Path(ctx["tables"][f])
        rec: dict = {}
        frame, _pcfg = cm.run_prodlib_m(f, scratch, ctx["sh"].root.parent, ctx["tag"], rec,
                                        real_derived=ctx["real_derived"], n_events=len(cm.read_csv(table)))
        config_json = rec["prodlib"][f]["config"]
        filt = cm.d2_step(f, frame, ctx["rosters"][f], ctx["sh"], scratch, ctx["tag"])
        observe.append({"label": f, "field": f, "config": str(config_json), "event_table": str(table)})
        frames.append({"label": f, "frame": str(filt["output"]), "config": str(config_json),
                       "event_table": str(table)})
        counts[f] = {"rows_prodlib": rec.get("frame_rows"), "rows_after_d2": cm._lines(filt["output"])}
    return {"observe": observe, "frames": frames, "counts": counts}


def part_econ(work: pathlib.Path, config: pathlib.Path, em=None) -> dict:
    if em is None:
        import econ920_m as em                                           # noqa: PLC0415
    if tuple(em.ORDER[:len(ECON_STEPS)]) != ECON_STEPS:
        raise RuntimeError(f"econ920_m.ORDER starts {em.ORDER[:len(ECON_STEPS)]}, not {ECON_STEPS}")
    L = em.L
    cfg = em.r1_config.load(config)
    if cfg.name != "B0":
        raise RuntimeError(f"the econ part rebuilds October: config {cfg.name} is not B0")
    root = work / "econ"
    root.mkdir(parents=True, exist_ok=False)
    v2 = L.real_v2()
    stage_cfg = cfg.resolved("stage")
    names = em.pa_stage._names(em.pa_stage.stage_value(stage_cfg, "names_csvs"))
    plan = em.plan_october(v2, names=names)
    report: dict = {"m": {}}
    ctx = em.make_ctx(root=root, v2=v2, cfg=cfg, plan=plan, src=None, stage_cfg=stage_cfg, out=root / "out",
                      roster=L.ROSTER_1008, events_dir=L.CAL10, rank_tables=None, calls_dir=None,
                      patch_october=L.CAL10 / PATCH_OCTOBER_REL, patch_r1=None, exclusion_base_path=None,
                      report=report)
    steps = em.Steps()
    for name in ECON_STEPS:
        getattr(steps, name)(ctx)
    config_json = str(report["m"]["regeneration"]["prodlib"]["config"])
    table = str(L.CAL10 / ECON_TABLE)
    split = em.split_net1(ctx.net1, regen=set(ctx.plan.regen), fnfix=em.fnfix_events(ctx.v2),
                          out_dir=root / "net1_parts")
    graphs, grec = em.freeze_graphs(ctx, need_fnfix=split["fnfix"][1] > 0)
    u5 = pathlib.Path(em.pa_stage.derived_root()) / U5_DOSE_REL
    frames = []
    for part in em.FREEZE_PARTS:
        path, n = split[part]
        if n == 0 and part != "july":
            continue
        item = {"label": ECON_LABELS[part], "frame": str(path), "event_table": table}
        if part == "regenerated":
            item["config"] = config_json
        else:
            g = graphs[part]
            item["graph"] = {"edges_glob": g.edges_glob, "works_glob": g.works_glob,
                             "supplement_jsonl": g.supplement_jsonl, "person_map": g.person_map_parquet}
        if part == "july" and u5.is_file():
            item["u5_dose"] = str(u5)
        frames.append(item)
    fx = grec.get("fnfix") or {}
    return {"observe": [{"label": "econ", "field": "econ", "config": config_json, "event_table": table}],
            "frames": frames,
            "counts": {"econ": {**{f"net1_rows_{k}": n for k, (_p, n) in split.items()},
                                "regenerated_events": sorted(ctx.plan.regen),
                                "fnfix_config_sha256": fx.get("config_sha256"),
                                "u5_dose": "present" if u5.is_file() else "absent"}}}


PART_FNS = {"chemmath": part_chemmath, "econ": part_econ}


# ---------------------------------------------------------------------------------------------
# the builder
# ---------------------------------------------------------------------------------------------

def assemble(fragments: dict) -> dict:
    """{part: fragment | None} -> the spec (labels unique; parts in PARTS order)."""
    spec = {"schema": SCHEMA, "observe": [], "frames": []}
    for part in PARTS:
        frag = fragments.get(part)
        if frag:
            spec["observe"] += frag["observe"]
            spec["frames"] += frag["frames"]
    for key in ("observe", "frames"):
        labels = [x["label"] for x in spec[key]]
        if len(labels) != len(set(labels)):
            raise ValueError(f"duplicate {key} labels {labels}")
    return spec


def build(work: pathlib.Path, spec_path: pathlib.Path, report_path: pathlib.Path, config: pathlib.Path,
          parts=PARTS, run_part=None) -> int:
    work = pathlib.Path(work)
    if work.exists() and any(work.iterdir()):
        raise SystemExit(f"--work {work} must be empty or absent")
    work.mkdir(parents=True, exist_ok=True)
    run_part = run_part or _run_part_process
    fragments, rep = {}, {"schema": REPORT_SCHEMA, "config": pathlib.Path(config).name, "parts": {}}
    for part in parts:
        t0 = time.time()
        rc, frag = run_part(part, work, config)
        ok = rc == 0 and frag is not None
        fragments[part] = frag if ok else None
        rep["parts"][part] = {"result": "OK" if ok else "FAIL", "rc": rc, "secs": round(time.time() - t0, 1),
                              "labels": sorted({x["label"] for x in (frag or {}).get("observe", []) +
                                                (frag or {}).get("frames", [])}) if ok else [],
                              "counts": (frag or {}).get("counts") if ok else None}
    spec = assemble(fragments)
    rep["result"] = "OK" if all(r["result"] == "OK" for r in rep["parts"].values()) else "INCOMPLETE"
    for path, body in ((spec_path, spec), (report_path, rep)):
        path = pathlib.Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"V3NET_SPEC {rep['result']} {json.dumps({k: v['result'] for k, v in rep['parts'].items()})}", flush=True)
    return 0 if rep["result"] == "OK" else 1


def _run_part_process(part: str, work: pathlib.Path, config: pathlib.Path):
    frag = work / f"part_{part}.json"
    log = work / f"part_{part}.log"
    with open(log, "wb") as fh:
        rc = subprocess.run([sys.executable, str(pathlib.Path(__file__).resolve()), "part", part, "--work", str(work),
                             "--config", str(config), "--out", str(frag)], stdout=fh, stderr=subprocess.STDOUT).returncode
    return rc, (json.loads(frag.read_text(encoding="utf-8")) if rc == 0 and frag.is_file() else None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--work", required=True, type=pathlib.Path)
    b.add_argument("--spec", required=True, type=pathlib.Path)
    b.add_argument("--report", required=True, type=pathlib.Path)
    b.add_argument("--config", type=pathlib.Path, default=None, help="default: config/r1/B0.json")
    b.add_argument("--parts", default=",".join(PARTS))
    p = sub.add_parser("part")
    p.add_argument("name", choices=PARTS)
    p.add_argument("--work", required=True, type=pathlib.Path)
    p.add_argument("--config", required=True, type=pathlib.Path)
    p.add_argument("--out", required=True, type=pathlib.Path)
    a = ap.parse_args(argv)
    if os.environ.get("SAR_HOST", "").strip() not in HOSTS:
        raise SystemExit("R1 rule: v3net_oracle_spec.py runs only on an R1 instance ($SAR_HOST)")
    repo = _find_repo()
    if a.cmd == "build":
        parts = tuple(x for x in a.parts.split(",") if x)
        if not parts or not set(parts) <= set(PARTS):
            ap.error(f"--parts {a.parts!r}: choose from {','.join(PARTS)}")
        return build(a.work, a.spec, a.report, a.config or repo / "config" / "r1" / "B0.json", parts=parts)
    _drivers_on_path(repo)
    frag = PART_FNS[a.name](a.work, a.config)
    a.out.write_text(json.dumps(frag, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
