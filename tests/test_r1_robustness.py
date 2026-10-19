# -*- coding: utf-8 -*-
"""R1 robustness driver (P3e F19, unit W1-ROB): pipeline/aws/r1/rob_jobs_r1.py, rob_post_r1.py,
run_robustness_r1.sh and config/r1/robustness_r1.json.

Switch-off proof without a B0 rerun: in mode 'october' the unit list IS October's commands (parsed from the
committed October scripts, runlogs, cloudkit.parallel_jobs and the T5 progress log), and the post steps
turn committed October inputs into byte-equal October products. No R runs here (the Rscript tokens below
are parsed text); the cut-grid test reads the small committed parquet frames with duckdb.
"""
from __future__ import annotations

import copy
import csv
import glob
import hashlib
import importlib.util
import json
import pathlib
import re
import shlex
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
R1 = REPO / "pipeline" / "aws" / "r1"
sys.path.insert(0, str(R1))
import rob_jobs_r1 as rj    # noqa: E402
import rob_post_r1 as rp    # noqa: E402
import restore_upstream as ru   # noqa: E402
import run_stages as rs    # noqa: E402

CAL = REPO / "data" / "cal2026-10"
ROB = CAL / "robustness"
FIELDS = ("econ", "chemistry", "math_stats")


# ---------------------------------------------------------------------------------------------
# a small bash expander for the October scripts: for-loops (also nested on one line), ${V}/$V, and
# `X=$(fn "$V")` assignments; it never executes anything
# ---------------------------------------------------------------------------------------------
_FOR = re.compile(r"^for (\w+) in ([^;]+); do\s*")
_ASSIGN_FN = re.compile(r'^(\w+)=\$\((\w+) "\$(\w+)"\)$')


def _stmts(text: str) -> list[tuple]:
    out = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        while True:
            m = _FOR.match(s)
            if not m:
                break
            out.append(("for", m.group(1), m.group(2).split()))
            s = s[m.end():].strip()
        if re.fullmatch(r"done(;\s*done)*;?", s):
            out += [("done",)] * s.count("done")
            continue
        if s:
            out.append(("cmd", s))
    return out


def _sub(s: str, env: dict) -> str:
    for k in sorted(env, key=len, reverse=True):
        s = s.replace("${%s}" % k, env[k]).replace("$" + k, env[k])
    return s


def _expand(stmts, env, fns) -> list[str]:
    res, i, env = [], 0, dict(env)
    while i < len(stmts):
        st = stmts[i]
        if st[0] == "for":
            depth, j = 1, i + 1
            while depth:
                depth += {"for": 1, "done": -1}.get(stmts[j][0], 0)
                j += 1
            for v in st[2]:
                res += _expand(stmts[i + 1:j - 1], {**env, st[1]: v}, fns)
            i = j
            continue
        if st[0] == "cmd":
            m = _ASSIGN_FN.match(st[1])
            if m and m.group(2) in fns:
                env[m.group(1)] = fns[m.group(2)](env[m.group(3)])
            else:
                res.append(_sub(st[1], env))
        i += 1
    return res


def _script(rel: str, env: dict, fns=None) -> list[str]:
    return _expand(_stmts((REPO / rel).read_text(encoding="utf-8")), env, fns or {})


def _r_units(units) -> list[tuple[str, list[str]]]:
    return [(u.outdir, shlex.split(u.cmd)) for u in units if u.kind not in ("control", "build", "post")]


@pytest.fixture(scope="module")
def cfg():
    return rj.load_config(REPO / "config" / "r1" / "robustness_r1.json")


def _october(cfg, *families):
    return rj.build_units(cfg, rj.october_roots(), "october", families=families)


# ---------------------------------------------------------------------------------------------
# 1-4: mode 'october' emits October's unit commands
# ---------------------------------------------------------------------------------------------

def test_october_mode_battery_units_equal_the_october_scripts(cfg):
    drv = "analysis/robustness/battery_2026-08-29/run_p1_variant.R"
    want = []
    for line in _script("analysis/robustness/battery_2026-08-29/run_all_battery.sh",
                        {"OUTDIR": "battery", "D": "data/frames", "DRV": drv}):
        if line.startswith("run "):
            t = shlex.split(line)                         # run <out> <mode> <label> <frame> <variant>
            want.append((t[1], ["Rscript", drv] + t[2:]))
    for line in _script("analysis/robustness/battery_2026-08-29/run_leaver.sh",
                        {"OUTDIR": "leaver", "D": "data/frames", "DRV": drv}):
        if line.startswith("run "):
            t = shlex.split(line)                         # run <out> <label> <frame> <variant>
            want.append((t[1], ["Rscript", drv, "full"] + t[2:]))
    assert len(want) == 2 + 12 + 1 + 3
    got = _r_units(_october(cfg, "battery", "leaver"))
    assert got == want
    # and the order October actually ran (the '== <label>' lines of the committed runlogs)
    bat = [ln[3:].strip() for ln in (ROB / "battery" / "runlog_2026-08-29.log").read_text(encoding="utf-8").splitlines()
           if ln.startswith("== ") and not ln.startswith("== LOEO")]
    lev = [ln[3:].split(" (")[0] for ln in (ROB / "leaver" / "runlog.log").read_text(encoding="utf-8").splitlines()
           if ln.startswith("== ")]
    assert [t[3] for _o, t in got] == bat + lev


def test_october_mode_predate_units_equal_the_october_scripts(cfg):
    pr = "analysis/robustness/predate/run_predate.R"
    sh = (REPO / "analysis/robustness/predate/run_p1_predate.sh").read_text(encoding="utf-8")
    gold = dict(re.findall(r"(\w+)\) echo (\w+);;", sh))
    want_p1 = []
    for line in _script("analysis/robustness/predate/run_p1_predate.sh", {"OUT": "predate_p1"}, {"gold": gold.get}):
        if f"Rscript {pr}" in line:
            t = shlex.split(line.split(">>")[0])
            want_p1.append((t[0].split("=", 1)[1], t[1:]))
    assert len(want_p1) == 6
    assert _r_units(_october(cfg, "predate_p1")) == want_p1

    want_p2 = []
    for line in _script("analysis/robustness/predate/run_all_predate.sh",
                        {"OUTDIR": "predate", "D": "data/frames", "X": "analysis/expected", "R": pr}):
        t = shlex.split(line) if line.startswith("run ") else []
        if t and t[2] == "p2":                            # run <out> p2 <label> <frame> <shift>
            want_p2.append((t[1], ["Rscript", pr] + t[2:]))
    assert len(want_p2) == 4
    assert _r_units(_october(cfg, "predate_p2")) == want_p2

    env = {"OUTDIR": "afar_cuts", "PD": "afar_cuts/predate", "FR": "afar_cuts/frames", "D": "data/frames"}
    want_pd, want_cells = [], []
    for line in _script("analysis/robustness/p3_afar_cuts/run_cuts.sh", env):
        if line.startswith("pdcell "):
            t = shlex.split(line)                         # pdcell <out> <label> <frame> <shift>
            want_pd.append((t[1], ["Rscript", pr, "p3tp"] + t[2:]))
        elif line.startswith("cell "):
            t = shlex.split(line)                         # cell <label> <frame>  (SAR_OUT=$EST)
            want_cells.append(("afar_cuts/estimates", ["Rscript", "analysis/estimation/run_p3_tp.R"] + t[1:]))
    assert len(want_pd) == 6 and len(want_cells) == 12
    assert _r_units(_october(cfg, "cut_predate")) == want_pd
    assert _r_units(_october(cfg, "cuts")) == want_cells


def _cloudkit():
    spec = importlib.util.spec_from_file_location("ck_r1rob", REPO / "pipeline/aws/cal2026-10/cloudkit.py")
    ck = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ck)
    src = (REPO / "pipeline/aws/cal2026-10/cloudkit.py").read_text(encoding="utf-8")
    d = {k: int(v) for k, v in re.findall(r'"--([\w-]+)", type=int, default=(\d+)', src)}
    return ck, d


def test_october_mode_p3_perm_null_units_equal_cloudkit(cfg):
    ck, d = _cloudkit()
    chunk = {"perm_econ": d["perm-chunk-econ"], "perm_chemistry": d["perm-chunk-other"],
             "perm_math_stats": d["perm-chunk-other"], "null_econ": d["null-chunk-econ"],
             "null_chemistry": d["null-chunk-other"], "null_math_stats": d["null-chunk-other"]}
    want = ck.parallel_jobs({"perm", "null"}, ck.FIELDS, d["perm-b"], d["null-n"], d["perm-seed"], d["null-seed"], chunk)
    got = [(u.name, u.outdir, u.cmd) for u in _october(cfg, "perm_p3", "null")]
    assert got == want
    assert len(got) == (1 + 100) + 4 * 10 + 4 + 4 + 2 * (1 + 10)   # econ perm/null, chem, maths


def test_october_mode_p1p2_perm_units_equal_the_t5_batch(cfg):
    log = (CAL / "cloud_t5" / "fetch" / "progress.log").read_text(encoding="utf-8")
    hits = re.findall(r"^PAR u(\d+)_(\S+) rc=(\d+)", log, re.M)
    assert len(hits) == 66 and {rc for _n, _x, rc in hits} == {"0"}
    want = [name for _n, name, _rc in sorted(hits, key=lambda h: int(h[0]))]
    units = _october(cfg, "perm_t5")
    assert [u.name for u in units] == want
    seed = re.search(r"^permutation_seed:\s*(\d+)", (REPO / "config/seeds.yaml").read_text(), re.M).group(1)
    for u in units:      # the prep_t5_batch.sh grammar: Rscript run_perm.R MODE LAB FRAME REF SEED a b, flat payload
        assert re.fullmatch(rf"Rscript run_perm\.R p[12] \S+ \S+\.csv \S+\.json {seed} \d+ \d+", u.cmd), u.cmd
        assert u.outdir == "out_perm" and u.kind in ("perm_p1", "perm_p2")


# ---------------------------------------------------------------------------------------------
# 5-6: the M catalogue
# ---------------------------------------------------------------------------------------------

def _toy_m(tmp_path, cfg, events=("A1:2001", "A2:2003", "A3:2003", "A4:2010", "A5:2012", "A6:2015", "A7:2020")):
    repo = tmp_path / "repo"
    (repo / "config" / "r1").mkdir(parents=True)
    j1a = tmp_path / "work" / "j1a"
    (j1a / "frames").mkdir(parents=True)
    with open(j1a / "frames" / "p1_frame_econ.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["incumbent_person_id", "year", "event_id", "post"])
        for i, ev in enumerate(events):
            for y in (2000, 2001):
                w.writerow([f"P_{i}", y, ev, "false"])
    c = copy.deepcopy(cfg)
    c["nocentre_build"]["values"] = {k: (v if v != "UNSET" else f"work:prod/toy_{k}")
                                     for k, v in c["nocentre_build"]["values"].items()}
    roots = rj.m_roots(c, repo=str(repo), work=str(tmp_path / "work"), j1a=str(j1a))
    return c, roots


def _json_product(u) -> str | None:
    t = shlex.split(u.cmd)
    if t and t[0] == "Rscript" and pathlib.Path(t[1]).name not in ("run_perm.R", "run_null.R"):
        lab = t[3] if pathlib.Path(t[1]).name in ("run_p1_variant.R", "run_predate.R") else t[2]
        return f"{u.outdir}/{lab}.json"
    return None


def _under(p, q) -> bool:
    a, b = pathlib.PurePosixPath(p).parts, pathlib.PurePosixPath(q).parts
    return a[:len(b)] == b


def _products(units, roots) -> tuple[set, set]:
    """(JSON cells the R units write, rob-root paths the build/post units name in flags or env)."""
    rob, rel = roots["rob"].rstrip("/") + "/", roots["rob_rel"].rstrip("/") + "/"
    cells, paths = set(), set()
    for u in units:
        j = _json_product(u)
        if j:
            cells.add(j)
        for tok in shlex.split(u.cmd):
            val = tok.split("=", 1)[1] if re.match(r"^[A-Z_]+=", tok) else tok
            for pre in (rob, rel):
                if val.startswith(pre):
                    paths.add(val[len(pre):])
    return cells, paths


def test_m_catalogue_is_what_the_paper_prints(tmp_path, cfg):
    cat = rj.catalogue(cfg)["products"]
    must = ([f"battery/{p}_{f}.json" for p in ("P1bnd0", "P1bndmean", "P1lvl", "P1nex") for f in FIELDS]
            + [f"leaver/P1leave_{f}.json" for f in FIELDS] + [f"predate_p1/P1pd2_{f}.json" for f in FIELDS]
            + [f"predate/P2pd2_{f}.json" for f in FIELDS]
            + [f"afar_cuts/estimates/P3cut_{c}_{f}.json" for c in ("pos", "med", "abs04", "p75") for f in FIELDS]
            + [f"afar_cuts/predate/P3pos_s2_{f}.json" for f in FIELDS] + ["afar_cuts/afar_cut_grid.csv"]
            + [f"d7/p05/estimates/P1p05_{f}.json" for f in FIELDS] + [f"d7/p05/estimates/P2p05_{f}.json" for f in FIELDS]
            + [f"d7/p05/estimates/P3p05pos_{f}_A_far.json" for f in FIELDS] + ["d7/p05/filter_report_p05.json"]
            + ["doublestar/doublestar_build_report.json", "doublestar/doublestar_drops.csv",
               "doublestar/estimates/P1ds_econ.json", "doublestar/complement/estimates/P1dsC_econ.json"]
            + [f"nocentre/estimates/{p}" for f in ("chemistry", "math_stats")
               for p in (f"P1nc_{f}.json", f"P2nc_{f}.json", f"P3nc_pos_{f}_A_far.json")]
            + ["nocentre/nocentre_report.json", "battery/loeo_ranked.csv",
               "cloud_t5/perm/perm_summary.json", "cloud/perm/perm_summary.json"]
            + [f"cloud/null/NULLpos_{f}.json" for f in FIELDS])
    assert set(must) <= set(cat)
    never = re.compile(r"P[12]ver_|dosebin3|P3dose3|P3p05_|P3nc_math_stats_full|P1ds_(chemistry|math)|P[23]ds|"
                       r"P3pd2_|dep[AB]|departure|P3lb_")
    assert not [p for p in cat if never.search(p)]
    # every catalogued product is written by a unit of the M list (a JSON cell or a path a build/post unit names)
    c, roots = _toy_m(tmp_path, cfg)
    units = rj.build_units(c, roots, "m")
    cells, paths = _products(units, roots)
    missing = [p for p in cat if p not in cells and not any(_under(p, q) for q in paths)]
    assert not missing, missing
    names = [u.name for u in units]
    assert not [n for n in names if never.search(n)]
    assert {x["cell"].split()[0] for x in cfg["cut"]} >= {"P1ver_econ", "P1dosebin3_<field>", "P3p05_<field>",
                                                           "P3nc_math_stats_full", "P3pd2_<field>_full"}


def test_loeo_units_follow_the_frame(tmp_path, cfg):
    c, roots = _toy_m(tmp_path, cfg)
    units = rj.build_units(c, roots, "m", families=("loeo",))
    assert len(units) == 7                                # the toy frame's events, not 113 or 173
    fr = f"{roots['frames']}/p1_frame_econ.csv"
    for u, ev in zip(units, sorted({"A1:2001", "A2:2003", "A3:2003", "A4:2010", "A5:2012", "A6:2015", "A7:2020"})):
        lab = f"P1loeo_{ev.replace(':', '_')}"
        assert u.name == lab and u.group == "loeo" and u.outdir == "battery/loeo"
        assert u.cmd == f"Rscript analysis/robustness/battery_2026-08-29/run_p1_variant.R loeo {lab} {fr} {ev}"
        assert u.needs_control == "ctl_battery_loeo"


# ---------------------------------------------------------------------------------------------
# 7-9: post steps reproduce the committed October products byte for byte
# ---------------------------------------------------------------------------------------------

def test_loeo_rank_reproduces_the_october_csv(tmp_path):
    out = tmp_path / "loeo_ranked.csv"
    rows = rp.loeo_rank(str(ROB / "battery" / "loeo"), str(REPO / "data/frames/p1_events_ledger_econ.csv"),
                        str(REPO / "analysis/expected/P1_econ_fnfix.json"), str(out),
                        frame_csv=str(REPO / "data/frames/p1_frame_econ.csv"))
    assert len(rows) == 113
    assert out.read_bytes() == (ROB / "battery" / "loeo_ranked.csv").read_bytes()


def test_loeo_rank_stops_when_a_removal_is_missing(tmp_path):
    loeo = tmp_path / "loeo"
    loeo.mkdir()
    files = sorted((ROB / "battery" / "loeo").glob("P1loeo_*.json"))
    for f in files[1:]:
        (loeo / f.name).write_bytes(f.read_bytes())
    with pytest.raises(SystemExit):
        rp.loeo_rank(str(loeo), str(REPO / "data/frames/p1_events_ledger_econ.csv"),
                     str(REPO / "analysis/expected/P1_econ_fnfix.json"), str(tmp_path / "x.csv"),
                     frame_csv=str(REPO / "data/frames/p1_frame_econ.csv"))


def test_cut_grid_reproduces_the_october_csv(tmp_path):
    out = tmp_path / "grid.csv"
    rows = rp.cut_grid(ROB / "afar_cuts" / "estimates", ROB / "afar_cuts" / "frames", ROB / "afar_cuts" / "cuts_build.json", out)
    assert out.read_bytes() == (ROB / "afar_cuts" / "afar_cut_grid.csv").read_bytes()
    med = [r for r in rows if r["cut_spec"] == "med"]
    assert med and all(r["se_event_pp"] != 0 for r in med)   # the median-cut 'interval includes zero' sentence


def _perm_labels(cfg, batch):
    if batch == "cloud_t5":
        return [lab for _mode, lab, _frame, _ref in cfg["perm"]["cells_p1p2"]]
    return [f"P3cutpos_{f}" for f in FIELDS]


@pytest.mark.parametrize("complete", [False, True])
@pytest.mark.parametrize("batch", ["cloud_t5", "cloud"])
def test_perm_summary_reproduces_october(tmp_path, cfg, batch, complete):
    """Byte-equal October summaries; with the M completeness check (every configured label, draws exactly 1..B=500,
    FAILED rows counting as present: M review #11) as without it."""
    dest = tmp_path / batch
    kw = {"labels": _perm_labels(cfg, batch), "B": cfg["perm"]["B"]} if complete else {}
    n = rp.perm_summary(REPO, CAL / batch / "fetch" / "out_perm", dest, **kw)
    for sub in ("raw", "control"):
        assert sorted(p.name for p in (dest / sub).iterdir()) == sorted(p.name for p in (CAL / batch / "perm" / sub).glob("*.csv"))
    assert n["control"] == len(list((CAL / batch / "perm" / "control").glob("*.csv")))
    for name in ("perm_summary.json", "perm_summary.csv"):
        assert (dest / name).read_bytes() == (CAL / batch / "perm" / name).read_bytes(), name


@pytest.mark.parametrize("field", FIELDS)
def test_null_merge_reproduces_october(tmp_path, field):
    out = tmp_path / f"NULLpos_{field}.json"
    rp.null_merge(REPO, CAL / "cloud" / "fetch" / "out_null", f"NULLpos_{field}", 200, out)
    assert out.read_bytes() == (CAL / "cloud" / "null" / f"NULLpos_{field}.json").read_bytes()


def test_nocentre_population_counts_reproduce_the_october_canon():
    rep = json.loads((ROB / "nocentre" / "nocentre_report.json").read_text(encoding="utf-8"))
    for f in ("chemistry", "math_stats"):
        p = rp.p1_population(REPO / "data" / "frames" / f"p1_frame_{f}.csv")
        r = rep["population"][f]["relationships"]
        assert (len(p["relations"]), len(p["persons"]), len(p["events"])) == (
            r["relations_canon"], r["persons_canon"], r["events_canon"]), f


# ---------------------------------------------------------------------------------------------
# 10-12: coverage, config, entry point
# ---------------------------------------------------------------------------------------------

def _toy_events(tmp_path, *, flag_missing=None, extra_p05=False):
    ev = tmp_path / "events"
    ev.mkdir(parents=True)
    econ_hdr = ["event_id", "star_id", "school", "arrival_year"]
    cm_hdr = ["field", "school", "author_id", "display_name", "arrival_corrected"]
    tables = {"econ": [econ_hdr, ["S1:2005", "S1", "monash", "2005"], ["S2:2010", "S2", "uq", "2010"]],
              "chemistry": [cm_hdr, ["chemistry", "unsw", "C1", "", "2008"]],
              "math_stats": [cm_hdr, ["math_stats", "uq", "M1", "", "2012"], ["math_stats", "anu", "M2", "", "2014"]]}
    for f, rows in tables.items():
        for suffix, keep in (("", rows), ("_p05", rows[:2])):
            with open(ev / f"events_{f}_cal2026-10{suffix}.csv", "w", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                w.writerows(keep + ([["S9:2001", "S9", "anu", "2001"]] if extra_p05 and f == "econ" and suffix else []))
    flags = [("econ", "S1"), ("econ", "S2"), ("chemistry", "C1"), ("math_stats", "M1"), ("math_stats", "M2")]
    with open(ev / "p05_flags_r1.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["star_id", "field", "p05", "basis", "pct", "cell_n"])
        for f, s in flags:
            if s != flag_missing:
                w.writerow([s, f, "True", "own", "0.97", "40"])
    return ev


def test_coverage_stops(tmp_path):
    ok = _toy_events(tmp_path / "a")
    assert rj.coverage(ok, ok / "p05_flags_r1.csv")["math_stats"] == {"events": 2, "events_p05": 1}
    miss = _toy_events(tmp_path / "b", flag_missing="M2")
    with pytest.raises(SystemExit, match=r"^P05_MISSING M2"):
        rj.coverage(miss, miss / "p05_flags_r1.csv")
    extra = _toy_events(tmp_path / "c", extra_p05=True)
    with pytest.raises(SystemExit, match=r"^P05_NOT_SUBSET econ S9:2001"):
        rj.coverage(extra, extra / "p05_flags_r1.csv")


def test_seeds_and_grammar_come_from_config(tmp_path, cfg):
    perm_sh = (REPO / "analysis/robustness/inference/run_all_perm.sh").read_text(encoding="utf-8")
    seeds_yaml = (REPO / "config/seeds.yaml").read_text(encoding="utf-8")
    s = cfg["seeds"]
    assert s["perm_p1p2"] == int(re.search(r"^permutation_seed:\s*(\d+)", seeds_yaml, re.M).group(1))
    assert s["perm_p1p2"] == int(re.search(r"^SEED=(\d+)", perm_sh, re.M).group(1))
    _ck, d = _cloudkit()
    assert (s["perm_p3"], s["null"]) == (d["perm-seed"], d["null-seed"]) == (20260830, 20260830)
    assert cfg["perm"]["B"] == int(re.search(r"^B=\$\{SAR_PERM_B:-(\d+)\}", perm_sh, re.M).group(1)) == d["perm-b"]
    assert cfg["perm"]["chunk_p1p2"] == int(re.search(r"^CHUNK=(\d+)", perm_sh, re.M).group(1))
    assert cfg["perm"]["chunk_p3"] == {"econ": d["perm-chunk-econ"], "chemistry": d["perm-chunk-other"],
                                       "math_stats": d["perm-chunk-other"]}
    assert cfg["null"]["chunk"] == {"econ": d["null-chunk-econ"], "chemistry": d["null-chunk-other"],
                                    "math_stats": d["null-chunk-other"]}
    assert cfg["null"]["nsim"] == d["null-n"]
    rows = [r.split() for r in re.findall(r'^\s*"(p[12] [^"]+)"', perm_sh, re.M)]
    assert [[m, lab, pathlib.Path(fr).name, pathlib.Path(ref).name] for m, lab, fr, ref in rows] == cfg["perm"]["cells_p1p2"]
    # the unit list reads them from the config (a changed seed reaches every permutation unit)
    c = copy.deepcopy(cfg)
    c["seeds"]["perm_p1p2"] = 11
    assert all(" 11 " in u.cmd for u in rj.build_units(c, rj.october_roots(), "october", families=("perm_t5",)))


def test_entry_point_and_rob_root(tmp_path, cfg):
    sh = R1 / "run_robustness_r1.sh"
    assert subprocess.run(["bash", "-n", str(sh)]).returncode == 0
    text = sh.read_text(encoding="utf-8")
    assert 'ROB_ROOT="$REPO_DIR/output/r1/robustness"' in text
    assert subprocess.run(["bash", str(sh), "bogus"], capture_output=True).returncode == 2
    for f in ("rob_jobs_r1.py", "run_units.py", "rob_post_r1.py"):
        assert f in text and (R1 / f).is_file()
    c, roots = _toy_m(tmp_path, cfg)
    assert pathlib.Path(roots["rob"]).is_relative_to(pathlib.Path(roots["repo"]))   # DS_DIR.relative_to(REPO)
    assert roots["rob_rel"] == "output/r1/robustness"


def test_generated_units_never_name_october_paths(tmp_path, cfg):
    c, roots = _toy_m(tmp_path, cfg)
    units = rj.build_units(c, roots, "m")
    ex = rj.exempt_paths(c)
    assert ex == ("data/cal2026-08-28/stars_excluded_cal2026-08-28.parquet",)      # M review #7: the one exception
    assert units and not [u.name for u in units if rj.forbidden_hits(u.cmd, ex) or rj.forbidden_hits(u.outdir)]
    assert [u.name for u in units if rj.forbidden_hits(u.cmd)] == ["nocentre_build"]   # only through that path
    bad = dict(roots, frames=str(tmp_path / "data" / "frames"))
    with pytest.raises(SystemExit, match=r"^FORBIDDEN_PATH"):
        rj.build_units(c, bad, "m", loeo_frame=f"{roots['frames']}/p1_frame_econ.csv")
    other = copy.deepcopy(c)                              # the exemption is the exact path, not the 08-28 tree
    other["nocentre_build"]["values"]["stars_excluded_base"] = "repo:data/cal2026-08-28/verdicts_2026-08-28.csv"
    with pytest.raises(SystemExit, match=r"^FORBIDDEN_PATH nocentre_build"):
        rj.build_units(other, roots, "m", families=("nocentre_frames",))


def test_unset_nocentre_inputs_stop(tmp_path, cfg):
    _c, roots = _toy_m(tmp_path, cfg)
    c = copy.deepcopy(cfg)
    c["nocentre_build"]["values"]["calls"] = "UNSET"
    with pytest.raises(SystemExit, match=r"^NOCENTRE_INPUT_UNSET calls"):
        rj.build_units(c, roots, "m")


def _sh_tokens(script):
    lex = shlex.shlex(script, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    return list(lex)


_OPS = {"&&", "||", ";", "|", ">", ">>", "<", "(", ")", "&"}


def _flags_after(toks, i):
    """{flag: value} of the argv after toks[i] up to the next shell operator (every flag here takes one value)."""
    args = []
    for x in toks[i + 1:]:
        if x in _OPS:
            break
        args.append(x)
    sub = [a for a in args[:1] if not a.startswith("-")]
    rest = args[len(sub):]
    assert len(rest) % 2 == 0 and all(f.startswith("--") for f in rest[::2]), rest
    return sub, dict(zip(rest[::2], rest[1::2]))


def test_m_nocentre_unit_matches_the_j1a_chemmath_row(cfg):
    """M review #7: from the REAL config (no UNSET override) the no-centre unit is J1a's frames_chemmath_m call on the
    incfel rosters, in J1a's environment: the 11-school edge-table shadow paths file exported before chemmath_m
    (chemmath_m.edge_env STOPs EDGE_ENV otherwise), --calls / --event-tables-all from the restored J1a products, and
    the 08-28 stars_excluded base J1a reads, without a FORBIDDEN_PATH stop. Before the fix: NOCENTRE_INPUT_UNSET."""
    roots = rj.m_roots(cfg, repo="/repo", work="/work", j1a="/work/j1a")
    assert roots["calls"] == "/work/j1a/calls" and roots["events"] == "/work/j1a/events"
    units = {u.name: u for u in rj.build_units(cfg, roots, "m", families=("nocentre_frames",))}
    argv = shlex.split(units["nocentre_build"].cmd)
    assert argv[:2] == ["bash", "-c"] and len(argv) == 3                  # run_units runs no shell: one bash -c unit
    script = argv[2]
    assert subprocess.run(["bash", "-n", "-c", script]).returncode == 0
    toks = _sh_tokens(script)
    i_edge, i_cm = toks.index("/repo/pipeline/aws/r1/edge_table.py"), toks.index("/work/bin/chemmath_m.py")
    exp = [k for k, x in enumerate(toks) if x.startswith("SAR_PATHS_CONFIG=")]
    assert toks.index("unset") < i_edge < exp[0] < i_cm and toks[toks.index("unset") + 1] == "SAR_SSD_ROOT"
    sub, edge = _flags_after(toks, i_edge)
    paths_txt = toks[toks.index(">", i_edge) + 1]
    assert toks[exp[0]] == f"SAR_PATHS_CONFIG=$(tail -n 1 {paths_txt})" and toks[exp[0] - 1] == "export"
    _sub, cm = _flags_after(toks, i_cm)
    assert cm["--calls"] == "/work/j1a/calls" and cm["--event-tables-all"] == "/work/j1a/events"
    assert cm["--roster-variant"] == "incfel" and cm["--fields"] == "chemistry,math_stats"
    assert cm["--roster-chemistry"].endswith("/roster_gold_chemistry_r1_incfel.parquet")
    assert cm["--roster-math-stats"].endswith("/roster_gold_math_stats_r1_incfel.parquet")
    assert cm["--out"] == "/work/prod/rob_frames/nocentre"
    j1a = {s["name"]: s for s in json.loads((REPO / "config" / "r1" / "stages" / "j1a.json").read_text(encoding="utf-8"))
           ["stages"]}["frames_chemmath_m"]["cmd"]
    jt = [x.replace("$WORK/prod/", "/work/j1a/").replace("$REPO_DIR", "/repo") for x in _sh_tokens(j1a)]
    j_sub, j_edge = _flags_after(jt, jt.index("/repo/pipeline/aws/r1/edge_table.py"))
    assert sub == j_sub == ["shadow"]
    assert {k: v for k, v in edge.items() if k != "--out"} == {k: v for k, v in j_edge.items() if k != "--out"}
    _s, j_cm = _flags_after(jt, jt.index("$WORK/chemmath_m.py"))
    skip = {"--roster-chemistry", "--roster-math-stats", "--roster-variant", "--out", "--fields"}
    assert {k: v for k, v in cm.items() if k not in skip} == {k: v for k, v in j_cm.items() if k not in skip}
    assert j_cm["--roster-variant"] == "fnfix"                       # J1a: the fnfix rosters; J1b: incfel


def test_tsv_round_trip_and_group_outputs(tmp_path, cfg):
    c, roots = _toy_m(tmp_path, cfg)
    units = rj.build_units(c, roots, "m")
    digest = rj.write_tsv(units, tmp_path / "units.tsv")
    rows = rj.read_tsv(tmp_path / "units.tsv")
    assert [r["name"] for r in rows] == [u.name for u in units] and len(digest) == 64
    assert list(rows[0]) == list(rj.COLUMNS)
    assert {r["group"] for r in rows} == set(cfg["groups"]) and {r["kind"] for r in rows} <= set(rj.KINDS)
    # every R unit writes under one of its group's declared outputs; groups' outputs are disjoint
    go = cfg["group_outputs"]
    for u in units:
        if u.cmd.startswith("Rscript"):
            prod = _json_product(u) or u.outdir
            assert any(_under(prod, q) for q in go[u.group]), (u.name, prod)
    flat = [(g, q) for g in cfg["groups"] for q in go[g]]
    for g1, q1 in flat:
        for g2, q2 in flat:
            if g1 != g2:
                assert not _under(q1, q2), (g1, q1, g2, q2)


# ---------------------------------------------------------------------------------------------
# M review #9: the post stage leaves canon M's J1b tree where FINAL's canon layout reads it
# ---------------------------------------------------------------------------------------------

def _toy_rob_root(root: pathlib.Path) -> None:
    """One file per J1b canon_reads product glob (not the custody records: canon-pack writes them); every draw the
    perm summaries copied also sits under <batch>/fetch/out_perm, byte for byte, as the perm units leave it."""
    for r in rp.canon_rows(REPO):
        if r["rel"].endswith(rp.CANON_CUSTODY):
            continue
        top, rest = r["rel"].split("/", 1)
        dest = pathlib.Path(str((root / rest) if top == "robustness" else (root / top / rest)).replace("*", "toy"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f"{r['rel']}\n", encoding="utf-8")
    for b in rp.CANON_BATCHES:
        for sub in ("raw", "control"):
            for f in (root / b / "perm" / sub).glob("*.csv"):
                (root / b / "fetch" / "out_perm").mkdir(parents=True, exist_ok=True)
                (root / b / "fetch" / "out_perm" / f.name).write_bytes(f.read_bytes())


def _sha(p) -> str:
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def _packed(tmp_path):
    root = tmp_path / "out" / "r1" / "robustness"
    _toy_rob_root(root)
    (tmp_path / "units").mkdir()
    rp.report(REPO, root=root, units_out=tmp_path / "units", out=root / "rob_custody.json", summary=root / "rob_report.json")
    return root


def test_rob_post_packs_the_canon_tree_final_restores(tmp_path, monkeypatch):
    """canon_layout.json maps cal/{robustness,cloud,cloud_t5} from work:prod/rob_post/canon/...; before the fix no
    J1b step wrote that tree and FINAL's restore_upstream refused MISSING_FILE. canon-pack writes it with October's
    custody records; restore_upstream (j1b rows of the real layout) then lays out every J1b canon_reads product."""
    root = _packed(tmp_path)
    sets = tmp_path / "j1b"
    stage_out = sets / "rob_post" / "files" / "work" / "prod" / "rob_post"
    rec = rp.canon_pack(REPO, root=root, out=stage_out / "canon")
    (sets / "rob_post.done.json").write_text(json.dumps({"outputs": {"work:prod/rob_post": rs.digest_of(stage_out)}}))
    lay = json.loads((REPO / "config" / "r1" / "canon_layout.json").read_text(encoding="utf-8"))
    rows = [r for r in lay["rows"] if r["from"].get("job") == "j1b"]
    assert sorted(r["dest"] for r in rows) == ["cal/cloud", "cal/cloud_t5", "cal/robustness"]
    assert {(r["from"]["stage"], r["from"]["token"]) for r in rows} == {("rob_post", "work:prod/rob_post")}
    layout = tmp_path / "layout_j1b.json"
    layout.write_text(json.dumps({"schema": lay["schema"], "rows": rows}))
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")
    dest = tmp_path / "canon_m"
    assert ru.main(["--stages", f"j1b={sets}", "--layout", str(layout), "--dest", str(dest),
                    "--out", str(tmp_path / "restore")]) == 0
    assert len(rp.canon_rows(REPO)) >= 30
    for r in rp.canon_rows(REPO):
        assert glob.glob(str(dest / "cal" / r["rel"])), r["rel"]
    for b in rp.CANON_BATCHES:
        cust = json.loads((dest / "cal" / b / rp.CANON_CUSTODY).read_text(encoding="utf-8"))
        assert cust["ok"] is True and cust["problems"] == [] and rec[b] == len(cust["fetch_sha256"]) > 0
        for sub in ("raw", "control"):                      # the key ledger_p1p2 / ledger_p3afar custody_pinned use
            for f in (dest / "cal" / b / "perm" / sub).glob("*.csv"):
                assert cust["fetch_sha256"][f"out_perm/{f.name}"] == _sha(f)
    assert not (dest / "cal" / "robustness" / "cloud").exists() and (dest / "cal" / "robustness" / "rob_custody.json").is_file()


@pytest.mark.parametrize("case", ["tampered_fetch", "unpinned_fetch", "missing_product", "out_not_empty"])
def test_canon_pack_stops(tmp_path, case):
    root = _packed(tmp_path)
    out = tmp_path / "canon"
    if case == "tampered_fetch":
        f = next((root / "cloud" / "fetch" / "out_null").glob("*.csv"))
        f.write_text("changed after the custody record\n", encoding="utf-8")
    elif case == "unpinned_fetch":
        (root / "cloud_t5" / "fetch" / "out_perm" / "late_perm_1_5.csv").write_text("x\n", encoding="utf-8")
    elif case == "missing_product":
        for f in (root / "nocentre" / "estimates").glob("P2nc_*.json"):
            f.unlink()
    else:
        out.mkdir()
        (out / "stale").write_text("x\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        rp.canon_pack(REPO, root=root, out=out)


def test_the_post_stage_runs_canon_pack_into_its_declared_output():
    text = (R1 / "run_robustness_r1.sh").read_text(encoding="utf-8")
    assert re.search(r'if \[ "\$GROUP" = post \]; then\n\s+"\$PY" "\$BIN/rob_post_r1.py" canon-pack --repo "\$REPO_DIR" '
                     r'--root "\$ROB_ROOT" --out "\$STAGE_OUT/canon"\nfi', text)
    # order of the two COMMANDS: the header comment also names canon-pack, so locate the invocations, not the word
    units, pack = '"$BIN/run_units.py" --units', '"$BIN/rob_post_r1.py" canon-pack'
    assert text.count(units) == 1 and text.count(pack) == 1
    assert text.index(units) < text.index(pack)


# ---------------------------------------------------------------------------------------------
# M review #11: a contiguous but incomplete permutation run is not summarised
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("case", ["truncated_tail", "missing_control", "label_without_draws", "duplicate_draws",
                                  "unexpected_label"])
def test_perm_summary_stops_on_an_incomplete_p3_run(tmp_path, cfg, case):
    """October's summarize_perm checks only 1..len(draws): without the last chunk P3cutpos_econ would be summarised
    with B_requested 495 and ledger_p3afar would print its p unchanged. Now: ROB_POST_STOP PERM_INCOMPLETE, and
    nothing is written."""
    src = tmp_path / "out_perm"
    shutil.copytree(CAL / "cloud" / "fetch" / "out_perm", src)
    labels = _perm_labels(cfg, "cloud")
    if case == "truncated_tail":
        (src / "P3cutpos_econ_perm_496_500.csv").unlink()
    elif case == "missing_control":
        (src / "P3cutpos_chemistry_perm_0_0.csv").unlink()
    elif case == "label_without_draws":
        for f in src.glob("P3cutpos_math_stats_perm_*.csv"):
            if not f.name.endswith("_0_0.csv"):
                f.unlink()
    elif case == "duplicate_draws":
        shutil.copyfile(src / "P3cutpos_econ_perm_1_5.csv", src / "P3cutpos_econ_perm_1_5b.csv")
    else:
        labels = labels[:2]
    dest = tmp_path / "perm"
    with pytest.raises(SystemExit):
        rp.perm_summary(REPO, src, dest, labels=labels, B=cfg["perm"]["B"])
    assert not dest.exists()
    with pytest.raises(SystemExit):                                # a half-given expectation is refused too
        rp.perm_summary(REPO, CAL / "cloud" / "fetch" / "out_perm", tmp_path / "half", labels=labels)


def test_m_perm_summary_units_carry_the_configured_labels_and_b(tmp_path, cfg):
    c, roots = _toy_m(tmp_path, cfg)
    units = {u.name: u for u in rj.build_units(c, roots, "m")}
    for name, batch in (("perm_summary_t5", "cloud_t5"), ("perm_summary_p3", "cloud")):
        t = shlex.split(units[name].cmd)
        assert t[t.index("--labels") + 1].split(",") == _perm_labels(cfg, batch), name
        assert t[t.index("--B") + 1] == str(cfg["perm"]["B"]) == "500", name
        assert set(_perm_labels(cfg, batch)) == {u.name.rsplit("_perm_", 1)[0] for u in units.values()
                                                 if u.group == "perm" and u.outdir == f"{batch}/fetch/out_perm"}


def test_perm_summary_records_an_unknown_treated_count_as_null(tmp_path, cfg):
    """j1b-08: in R1 every permuted P1 econ draw wrote n_treated_events NA (an event whose permuted arrival leaves
    only NA doses has any() = NA), and October's summarize_perm stopped on int('NA'). The count is descriptive
    only: the p-values use ate and t. Now mean_treated_events is null when a draw's count is unknown, and every
    other field, and every other label, is what it was."""
    src = tmp_path / "out_perm"
    shutil.copytree(CAL / "cloud_t5" / "fetch" / "out_perm", src)
    labels, B = _perm_labels(cfg, "cloud_t5"), cfg["perm"]["B"]
    rp.perm_summary(REPO, src, tmp_path / "before", labels=labels, B=B)
    lab = "P1_econ_fnfix"
    for f in src.glob(f"{lab}_perm_*.csv"):
        if f.name.endswith("_0_0.csv"):
            continue
        rows = list(csv.DictReader(f.open(newline="", encoding="utf-8")))
        with f.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows({**r, "n_treated_events": "NA"} for r in rows)
    rp.perm_summary(REPO, src, tmp_path / "after", labels=labels, B=B)
    before, after = ({c["label"]: c for c in json.loads((tmp_path / d / "perm_summary.json").read_text())["cells"]}
                     for d in ("before", "after"))
    assert after[lab]["mean_treated_events"] is None and before[lab]["mean_treated_events"] is not None
    assert {k: v for k, v in after[lab].items() if k != "mean_treated_events"} == \
           {k: v for k, v in before[lab].items() if k != "mean_treated_events"}
    assert all(after[k] == before[k] for k in before if k != lab)
