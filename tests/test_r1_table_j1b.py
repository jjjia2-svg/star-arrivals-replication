# -*- coding: utf-8 -*-
"""config/r1/stages/j1b.json + config/r1/jobs/j1b.json + config/r1/layouts/j1b_from_j1a.json (P3e W2-TJ1B: F19, N8,
N5, F6). J1b runs on config M only: it lays out J1a's pushed stage set under /work/j1a (digest-checked), builds the
robustness unit list, plans the parallel width (N8), maps the A_far events (F6), runs the robustness groups (F19) and
the Figure 4 sample cells (N5), and ends with the sandbox check. Star departure (F20) is out of scope (author
2026-10-15: the paper prints no star-departure robustness), so the table has no departure row.

Reads committed config files. The toy tests run a row's own bash on a tmp WORK; the --help probes run each script's
argument parser only. Nothing reads October products."""
from __future__ import annotations

import csv
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import r1kit               # noqa: E402
import restore_upstream as ru   # noqa: E402
import run_stages as rs    # noqa: E402
import sandbox as sb       # noqa: E402

J1B = REPO / "config" / "r1" / "stages" / "j1b.json"
J1A = REPO / "config" / "r1" / "stages" / "j1a.json"
JOB = REPO / "config" / "r1" / "jobs" / "j1b.json"
LAYOUT = REPO / "config" / "r1" / "layouts" / "j1b_from_j1a.json"
ROBCFG = REPO / "config" / "r1" / "robustness_r1.json"
ENTRY = "pipeline/aws/r1/run_robustness_r1.sh"
J1A_DIR = "/work/j1a"
J1A_STAGES = "/work/j1a_stages"
REF = "/work/ref/october"

ORDER = ["verify_inputs", "config", "restore_j1a", "sandbox", "rob_jobs", "par_plan", "afar_event_map",
         "rob_frames", "rob_cells", "rob_loeo", "rob_perm", "rob_null", "fig4_m", "fig4_counts", "rob_post",
         "sandbox_check"]
#: run_units groups in table order (rob_jobs builds the list; there is no rob_controls stage: W1-ROB)
GROUP_STAGES = {"rob_frames": "frames", "rob_cells": "cells", "rob_loeo": "loeo", "rob_perm": "perm",
                "rob_null": "null", "rob_post": "post"}
ROB_SCRIPTS = ("repo:pipeline/aws/r1/rob_jobs_r1.py", "repo:pipeline/aws/r1/run_units.py",
               "repo:pipeline/aws/r1/rob_post_r1.py", "repo:config/r1/robustness_r1.json")
SHELL_OPS = {">", ">>", "<", "&&", "||", ";", "|", "2>&1"}
FIELDS = ("econ", "chemistry", "math_stats")
#: October products and the October canon: J1b compares only with J1a's own M products
FORBIDDEN = ("data/frames", "cal2026-08-28", "analysis/expected", "data/cal2026-10/", "/work/ref/october/")


def _table(p=J1B):
    return rs.load_table(p)


def _rows(p=J1B):
    return {s["name"]: s for s in _table(p)["stages"]}


def _job():
    return json.loads(JOB.read_text(encoding="utf-8"))


def _pinned():
    return json.loads((REPO / "config" / "r1" / "input_pins.json").read_text(encoding="utf-8"))["pins"]


def _layout():
    return ru.load_rows(LAYOUT)


def _robcfg():
    return json.loads(ROBCFG.read_text(encoding="utf-8"))


def _argv(row):
    return shlex.split(row["cmd"])


def _flag(argv, flag):
    assert argv.count(flag) == 1, (flag, argv)
    return argv[argv.index(flag) + 1]


def _closure(rows, name):
    """Every stage `name` needs, directly or through another need."""
    seen, todo = set(), list(rows[name]["needs"])
    while todo:
        n = todo.pop()
        if n not in seen:
            seen.add(n)
            todo += rows[n]["needs"] if n in rows else []
    return seen


def _entry(group):
    return f'bash "$WORK/run_robustness_r1.sh" {group}'


def _guard(row):
    """The split guard in front of a run_units group's entry call (N8 split_after -> a second launch)."""
    head, sep, tail = row["cmd"].rpartition(" && " + _entry(GROUP_STAGES[row["name"]]))
    assert sep and tail == "", row["cmd"]
    return head


# ---------------------------------------------------------------------------------------------------------------
# order, isolation rows, job spec
# ---------------------------------------------------------------------------------------------------------------

def test_rows_in_order_with_valid_needs_and_the_table_is_complete():
    t = _table()                                        # load_table: every need runs earlier, tokens are valid
    assert t["job"] == "j1b" and [s["name"] for s in t["stages"]] == ORDER
    assert t["complete"] is True                        # W3-FLIPS set it after the M Codex review fixes (#7, #9, #10, #12)
    rows = _rows()
    for name in ORDER:
        for n in rows[name]["needs"]:
            assert n in rows and ORDER.index(n) < ORDER.index(name), (name, n)
    assert set(r1kit.REQUIRED_STAGES["j1b"]) <= set(ORDER)
    complete = dict(t, complete=True)                   # a flip to complete would pass r1kit's launch check
    assert r1kit.check_stage_table({"stages": "config/r1/stages/j1b.json"}, "c" * 40,
                                   show=lambda p: json.dumps(complete), exists=lambda p: True) == []


def test_isolation_rows_are_m_and_always_rerun():
    rows = _rows()
    for name in ("verify_inputs", "config", "restore_j1a", "sandbox", "sandbox_check"):
        assert rows[name].get("resume") == "always", name
    cf = _argv(rows["config"])
    assert cf[2] == "check" and _flag(cf, "--config") == "$REPO_DIR/config/r1/M.json"
    assert "repo:config/r1/M.json" in rows["config"]["inputs"] and "config/r1/M.json" in rows["config"]["requires"]
    sb = _argv(rows["sandbox"])
    assert sb[2] == "purge" and _flag(sb, "--config") == "M" and _flag(sb, "--ref") == REF
    assert _flag(sb, "--table") == "$REPO_DIR/config/r1/stages/j1b.json"
    ck = _argv(rows["sandbox_check"])
    assert ck[2] == "check" and _flag(ck, "--config") == "M"
    assert [ck[i + 1] for i, x in enumerate(ck) if x == "--reads"] == ["/work/reads", "/work/resume/_reads"]
    assert _flag(ck, "--record") == "$WORK/prod/sandbox/base_record.json"
    assert ORDER[-1] == "sandbox_check" and set(ORDER[:-1]) <= _closure(rows, "sandbox_check") | {"sandbox_check"}
    vi = _argv(rows["verify_inputs"])
    assert vi[2] == "data" and _flag(vi, "--job-spec") == "$REPO_DIR/config/r1/jobs/j1b.json"


def test_job_spec_carries_m_and_pulls_the_j1a_stage_set():
    job = r1kit.load_job("j1b")                         # schema, est/hard minutes, host, env layers
    assert job["env"]["SAR_R1_CONFIG"] == "$REPO_DIR/config/r1/M.json"
    assert job["env"]["PYTHONDONTWRITEBYTECODE"] == "1" and job["env"]["PYTHONHASHSEED"] == "0"
    assert job["required_dests"] == [J1A_STAGES + "/"]   # launch --pull r1/runs/<j1a>/stages/=/work/j1a_stages/
    assert job["stages"] == "config/r1/stages/j1b.json"
    cft = {src: dst for src, dst in job["copy_from_tip"]}
    assert cft["pipeline/aws/r1/run_stages.py"] == "/work/run_stages.py"
    assert cft[ENTRY] == "/work/run_robustness_r1.sh"
    assert {"py", "rmac", "rcloud"} <= set(job["env_layers"])
    # 2880: a 48 h backstop, so a J1b launch runs to its end (perm alone ~10-11 h, j1b-03 2026-10-17)
    assert job["instance_type"] == "r6i.16xlarge" and job["hard_min"] == 2880
    assert job["est_min"] < job["hard_min"]


def test_stage_minutes_fit_one_launch_or_n8_splits():
    rows = _rows()
    total = sum(int(r["est_min"]) for r in rows.values())
    assert 0 < total <= 540, total                      # above 540 N8's split_after runs J1b as two launches
    assert all(int(r["est_min"]) >= 1 for r in rows.values())


def test_no_departure_rows_f20_is_out_of_scope():
    """Author ruling 2026-10-15: the paper prints no star-departure robustness."""
    for name, row in _rows().items():
        text = json.dumps(row)
        assert "departure" not in name and "build_departure" not in text and "departure_ledger" not in text, name
    assert "departure" not in LAYOUT.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------------------------------------
# restore_j1a + the layout
# ---------------------------------------------------------------------------------------------------------------

def test_restore_j1a_row_lays_out_the_pulled_stage_set():
    row = _rows()["restore_j1a"]
    assert row["script"] == "pipeline/aws/r1/restore_upstream.py"
    a = _argv(row)
    assert a[1] == "$WORK/restore_upstream.py"
    assert _flag(a, "--stages") == J1A_STAGES and _flag(a, "--dest") == J1A_DIR
    assert _flag(a, "--layout") == "$REPO_DIR/config/r1/layouts/j1b_from_j1a.json"
    assert _flag(a, "--out") == "$STAGE_OUT"
    assert "--manifest" not in a                       # frames/ carries J1a's own MANIFEST; nothing is invented
    assert "repo:config/r1/layouts/j1b_from_j1a.json" in row["inputs"]
    assert "repo:pipeline/aws/r1/run_stages.py" in row["inputs"]      # restore_upstream digests with it
    assert row["outputs"] == ["work:prod/restore_j1a"]                 # /work/j1a itself is never re-pushed
    assert row["needs"] == ["config"]
    assert _robcfg()["roots"]["j1a"] == J1A_DIR


def test_restore_j1a_precedes_every_reader_and_its_fingerprint_follows_j1a():
    rows = _rows()
    readers = [n for n, r in rows.items() if J1A_DIR + "/" in r["cmd"] or "run_robustness_r1.sh" in r["cmd"]]
    assert set(readers) == {"rob_jobs", "par_plan", "afar_event_map", "rob_frames", "rob_cells", "rob_loeo",
                            "rob_perm", "rob_null", "fig4_m", "rob_post"}
    for n in readers:
        assert ORDER.index("restore_j1a") < ORDER.index(n), n
        assert "restore_j1a" in _closure(rows, n), n
        assert "stage:restore_j1a" in rows[n]["inputs"], n
    for n in ORDER[ORDER.index("restore_j1a") + 1:]:      # sandbox purge runs before any reader
        if n in readers:
            assert ORDER.index("sandbox") < ORDER.index(n) and "sandbox" in _closure(rows, n), n


def test_layout_rows_are_j1a_stage_products_with_disjoint_dests():
    rows = _layout()
    j1a = _rows(J1A)
    dests = []
    for r in rows:
        assert set(r) == {"dest", "from"}, r
        f = r["from"]
        assert f["job"] == "j1a" and set(f) <= {"job", "stage", "token", "rel"}, r
        tok = f["token"]
        assert rs.NAME.match(f["stage"]) and tok.startswith("work:prod/"), r
        assert tok[len("work:prod/"):] and "/" not in tok[len("work:prod/"):], r    # one top-level prod dir
        # R10 product tokens: a stage's product dir is work:prod/<stage>, unless the J1a table declares another
        # prod dir as that stage's output. W2-TJ1A: estimates_m declares only work:prod/estimates_M (the flat 27
        # cells); its STAGE_OUT work/prod/estimates_m holds only its own report and is not an output, so
        # restore_upstream would refuse work:prod/estimates_m with MISSING_TOKEN (t-0024 fix 400f7af).
        assert tok == f"work:prod/{f['stage']}" or tok in j1a.get(f["stage"], {}).get("outputs", []), r
        d = pathlib.PurePosixPath(r["dest"])
        assert not d.is_absolute() and ".." not in d.parts and d.parts, r
        dests.append(d)
    for i, d in enumerate(dests):
        for e in dests[i + 1:]:
            assert d != e and d not in e.parents and e not in d.parents, (d, e)
    assert json.loads(LAYOUT.read_text(encoding="utf-8"))["schema"] == "sar.r1.layout.v1"


def _covered(rel, dests):
    """A laid-out path, a file inside a laid-out dir, or a dir that holds laid-out files."""
    rel = pathlib.PurePosixPath(rel)
    return any(rel == d or d in rel.parents or rel in d.parents for d in dests)


def test_every_j1a_path_a_reader_names_is_laid_out():
    dests = [pathlib.PurePosixPath(r["dest"]) for r in _layout()]
    need = set()
    for row in _rows().values():
        need |= {m.rstrip("/") for m in re.findall(r"/work/j1a/([^\s\"']+)", row["cmd"])}
    cfg = _robcfg()
    lay = cfg["j1a_layout"]
    need |= {lay["pairs_econ"], lay["p05_flags"]}
    need |= {f"{lay['events']}/events_{f}_cal2026-10.csv" for f in FIELDS}          # rob_jobs_r1.coverage
    need |= {f"{lay['events']}/events_{f}_cal2026-10_p05.csv" for f in FIELDS}
    need |= {"pairs/becoming_unified.csv"}                 # afar_event_map's mandatory econ becoming check
    need |= {f"pairs/pairs_none_{f}.parquet" for f in ("chemistry", "math_stats")}
    need |= {lay["calls"]}                                 # the no-centre rebuild's --calls (M review #7)
    for v in cfg["nocentre_build"]["values"].values():
        if v.startswith("work:j1a/"):
            need.add(v[len("work:j1a/"):])
    for n in sorted(need):
        assert _covered(n, dests), n
    for whole in (lay["frames"], lay["estimates"]):        # dirs read whole (frames by basename, golds by out_name)
        assert pathlib.PurePosixPath(whole) in dests, whole


def test_layout_names_only_outputs_the_j1a_table_declares():
    rows = _rows(J1A)
    if "frames" not in rows:
        pytest.skip("config/r1/stages/j1a.json is still the P3b table; W2-TJ1A lands the M rows")
    for r in _layout():
        f = r["from"]
        assert f["stage"] in rows, f
        assert f["token"] in rows[f["stage"]]["outputs"], f


def _toy_stage_set(root):
    """A pulled J1a stage set for every (stage, token) the layout reads: rel files written, markers digested."""
    toks = {}
    for r in _layout():
        f = r["from"]
        toks.setdefault((f["stage"], f["token"]), set()).add(f.get("rel", ""))
    for (stage, tok), rels in toks.items():
        d = root / stage / "files" / "work" / tok.split(":", 1)[1]
        d.mkdir(parents=True, exist_ok=True)
        (d / "other.txt").write_text(f"{stage}\n")
        for rel in rels:
            if rel:
                (d / rel).parent.mkdir(parents=True, exist_ok=True)
                (d / rel).write_text(f"{stage}:{rel}\n")
        (root / f"{stage}.done.json").write_text(json.dumps({"outputs": {tok: rs.digest_of(d)}}) + "\n")
    return toks


def _run_restore(tmp_path, tamper=False):
    work = tmp_path / "work"
    stages = work / "j1a_stages"
    toks = _toy_stage_set(stages)
    if tamper:
        stage, tok = sorted(toks)[0]
        (stages / stage / "files" / "work" / tok.split(":", 1)[1] / "other.txt").write_text("changed\n")
    shutil.copyfile(REPO / "pipeline" / "aws" / "r1" / "restore_upstream.py", work / "restore_upstream.py")
    out = work / "prod" / "restore_j1a"
    out.mkdir(parents=True)
    cmd = _rows()["restore_j1a"]["cmd"].replace("/work/", f"{work}/")
    env = dict(os.environ, SAR_HOST="ec2-r1-test", PY=sys.executable, REPO_DIR=str(REPO), WORK=str(work),
               STAGE_OUT=str(out), COMMIT="c" * 40, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run(["bash", "-c", cmd], cwd=work, env=env, capture_output=True, text=True, timeout=300)
    return r, work, out, toks


def test_restore_j1a_cmd_on_a_toy_stage_set(tmp_path):
    r, work, out, toks = _run_restore(tmp_path)
    assert r.returncode == 0, r.stderr[-800:]
    for row in _layout():
        assert (work / "j1a" / row["dest"]).exists(), row["dest"]
    rel = {row["dest"]: row["from"].get("rel", "") for row in _layout()}
    for dest, x in rel.items():
        if x:
            stage = next(row["from"]["stage"] for row in _layout() if row["dest"] == dest)
            assert (work / "j1a" / dest).read_text() == f"{stage}:{x}\n", dest
    rep = json.loads((out / "report_restore.json").read_text())
    assert rep["result"] == "OK" and rep["counts"]["rows"] == len(_layout())
    # the J1a markers ride in the stage output, so stage:restore_j1a changes whenever a J1a product does
    assert sorted(p.name for p in (out / "upstream").iterdir()) == sorted({f"{s}.done.json" for s, _ in toks})


def test_restore_j1a_cmd_refuses_a_tampered_stage_set(tmp_path):
    r, work, out, _ = _run_restore(tmp_path, tamper=True)
    assert r.returncode != 0
    assert json.loads((out / "report_restore.json").read_text())["code"] == "DIGEST_MISMATCH"
    assert not (work / "j1a").exists()


# ---------------------------------------------------------------------------------------------------------------
# F6 afar_event_map, N8 par_plan, F19 robustness groups, N5 Figure 4
# ---------------------------------------------------------------------------------------------------------------

def test_j1b_map_stage_precedes_its_readers():
    rows = _rows()
    m = rows["afar_event_map"]
    assert m["script"] == "analysis/robustness/sensitivity/afar_event_map.py"
    a = _argv(m)
    assert a[1] == "$REPO_DIR/analysis/robustness/sensitivity/afar_event_map.py"     # REPO-relative helpers
    assert _flag(a, "--spec") == "pos" and "--regen-econ" not in a
    assert _flag(a, "--frames-dir") == f"{J1A_DIR}/frames" and _flag(a, "--pairs-dir") == f"{J1A_DIR}/pairs"
    assert _flag(a, "--pairs-econ") == f"{J1A_DIR}/{_robcfg()['j1a_layout']['pairs_econ']}"
    assert _flag(a, "--outdir") == "$STAGE_OUT" and _flag(a, "--tmpdir") == "$WORK/tmp/afar_map"
    assert _flag(a, "--threads") == "16" and _flag(a, "--memory-limit") == "64GB"
    assert m["outputs"] == ["work:prod/afar_event_map"]
    assert _robcfg()["roots"]["map_dir"] == "work:prod/afar_event_map"   # the D7 and double-star units read it
    readers = [n for n, r in rows.items() if n != "afar_event_map" and
               ("prod/afar_event_map" in r["cmd"] or "stage:afar_event_map" in r["inputs"])]
    assert "rob_frames" in readers                       # d7 filter + double-star build units (group frames)
    for n in readers:
        assert "afar_event_map" in rows[n]["needs"], n


def test_par_plan_row_plans_the_unit_list_before_any_group():
    rows = _rows()
    p = rows["par_plan"]
    assert p["script"] == "pipeline/aws/r1/par_plan.py"
    a = _argv(p)
    assert a[1] == "$WORK/par_plan.py"
    assert _flag(a, "--jobs") == "$WORK/prod/rob_jobs/units.tsv"
    assert _flag(a, "--frames") == f"{J1A_DIR}/frames"
    assert _flag(a, "--calib") == f"{J1A_DIR}/mem_probe/mem_report.json"
    assert _flag(a, "--calib-cells") == f"{J1A_DIR}/cells_rcloud/cells_report_rcloud.json"
    assert _flag(a, "--out") == "$STAGE_OUT"                # run_robustness_r1.sh reads $WORK/prod/par_plan/plan.json
    assert p["outputs"] == ["work:prod/par_plan"]
    assert set(p["needs"]) >= {"restore_j1a", "rob_jobs"} and "stage:rob_jobs" in p["inputs"]
    for name in GROUP_STAGES:
        assert ORDER.index("par_plan") < ORDER.index(name) and "par_plan" in rows[name]["needs"], name
        assert "stage:par_plan" in rows[name]["inputs"], name


def test_robustness_rows_call_the_entry_with_their_group_and_name_their_outputs():
    rows, cfg = _rows(), _robcfg()
    assert cfg["stage_of_group"] == {"jobs": "rob_jobs", **{g: s for s, g in GROUP_STAGES.items()}}
    assert "rob_controls" not in rows
    jobs = rows["rob_jobs"]
    assert jobs["cmd"] == _entry("jobs") and jobs["script"] == ENTRY and jobs["outputs"] == ["work:prod/rob_jobs"]
    for tok in ROB_SCRIPTS + ("repo:config/r1/paths_aws.yaml", "stage:restore_j1a"):
        assert tok in jobs["inputs"], tok
    prev = {n: ORDER[ORDER.index(n) - 1] for n in GROUP_STAGES}
    for name, group in GROUP_STAGES.items():
        r = rows[name]
        assert r["script"] == ENTRY and r["cmd"].endswith(" && " + _entry(group)), name
        for tok in ROB_SCRIPTS + (f"stage:{prev[name]}", "stage:rob_jobs", "env:py"):
            assert tok in r["inputs"], (name, tok)
        assert prev[name] in r["needs"] and "rob_jobs" in r["needs"], name
        want = {f"work:prod/{name}"} | {f"repo:output/r1/robustness/{p}" for p in cfg["group_outputs"][group]}
        assert set(r["outputs"]) == want and len(r["outputs"]) == len(want), name
    for name in ("rob_cells", "rob_loeo"):
        assert {"env:rmac", "repo:analysis/estimation", "repo:analysis/robustness"} <= set(rows[name]["inputs"])
    for name in ("rob_perm", "rob_null"):                 # permutations and nulls run on the cloud R (config stacks)
        assert {"env:rcloud", "repo:analysis/robustness"} <= set(rows[name]["inputs"])
    post = rows["rob_post"]
    assert {"rob_frames", "rob_cells", "rob_loeo", "rob_perm", "rob_null", "fig4_counts"} <= _closure(rows, "rob_post")
    assert "repo:tools/write_manifest.py" in post["inputs"]


def test_rob_frames_fingerprint_follows_the_nocentre_build_inputs():
    """The no-research-centre frames are rebuilt in group frames by W2-CHEMM's chemmath_m.py on the incfel rosters."""
    r = _rows()["rob_frames"]
    want = {"repo:pipeline/aws/r1/chemmath_m.py", "repo:config/r1/M.json",
            "repo:data/cal2026-10r1/inputs/rosters/roster_gold_chemistry_r1_incfel.parquet",
            "repo:data/cal2026-10r1/inputs/rosters/roster_gold_math_stats_r1_incfel.parquet"}
    assert want <= set(r["inputs"])
    assert {t.split(":", 1)[1] for t in want} <= set(r["requires"])      # r1kit refuses a launch without them
    vals = _robcfg()["nocentre_build"]["values"]
    for k in ("roster_chemistry", "roster_math_stats"):
        assert f"repo:{vals[k][5:]}" in r["inputs"], k
    # M review #7: the unit builds the 11-school edge-table shadow from paths_aws.yaml, as J1a's row does
    assert {"repo:pipeline/aws/r1/edge_table.py", "repo:config/r1/paths_aws.yaml"} <= set(r["inputs"])
    assert vals["calls"] == "{calls}" and vals["event_tables_all"] == "{events}"
    assert {"stars_excluded_cal2026-08-28.parquet", "MANIFEST.sha256"} <= {
        pathlib.PurePosixPath(x.glob).name for x in sb.load_allowlist(REPO / "config" / "r1" / "read_allowlist_0828.txt")
        if x.configs == ("M",) and x.stages is not None and "rob_frames" in x.stages}
    # M review #10: the fingerprint follows every code / config input of J1a's chemmath_m row (the incfel rosters
    # replace the fnfix ones; the 08-28 canon is frozen and may not be named in a J1b row), so a relaunch with
    # --resume-from never reuses no-centre frames built by older builder code
    j1a = {s["name"]: s for s in json.loads(J1A.read_text(encoding="utf-8"))["stages"]}["frames_chemmath_m"]
    want = {t for t in j1a["inputs"] if t.startswith("repo:") and "roster_gold_" not in t and "cal2026-08-28" not in t}
    assert want - set(r["inputs"]) == set()
    assert len(want) >= 20
    covered = [t[5:] for t in r["inputs"] if t.startswith("repo:")]
    mods = re.findall(r"^import (\w+)(?: as \w+)?\s", (REPO / "pipeline/aws/r1/chemmath_m.py").read_text(encoding="utf-8"), re.M)
    for mod in mods:                                   # chemmath_m's own sibling / October-layer imports
        for d in ("pipeline/aws/r1", "pipeline/frames/cal2026-10"):
            if (REPO / d / f"{mod}.py").is_file():
                rel = f"{d}/{mod}.py"
                assert any(rel == c or rel.startswith(c.rstrip("/") + "/") for c in covered), rel


def test_entry_script_accepts_every_group_the_table_names():
    text = (REPO / ENTRY).read_text(encoding="utf-8")
    case = re.search(r"^\s*([a-z|]+)\)\s*;;", text, re.M).group(1).split("|")
    assert {"jobs", *GROUP_STAGES.values()} <= set(case)
    for name, row in _rows().items():
        if row.get("script") == ENTRY:
            assert subprocess.run(["bash", "-n", "-c", row["cmd"]]).returncode == 0, name


def _plan(tmp_path, split_after, launches):
    work = tmp_path / "work"
    (work / "prod" / "par_plan").mkdir(parents=True, exist_ok=True)
    (work / "prod" / "par_plan" / "plan.json").write_text(json.dumps(
        {"schema": "sar.r1.par_plan.v1", "verdict": "OK", "split_after": split_after, "launches": launches}))
    return work


def _run_guard(work, name, resume=None):
    out = work / "prod" / name
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PY=sys.executable, WORK=str(work), STAGE_OUT=str(out), REPO_DIR=str(REPO))
    env.pop("SAR_RESUME_DIR", None)
    if resume is not None:
        env["SAR_RESUME_DIR"] = str(resume)
    r = subprocess.run(["bash", "-c", _guard(_rows()[name])], cwd=work, env=env, capture_output=True, text=True)
    return r, out


def test_split_guard_ends_launch_one_after_n8s_split_group(tmp_path):
    groups = list(GROUP_STAGES.values())
    work = _plan(tmp_path / "nosplit", None, [groups])
    for name in GROUP_STAGES:                             # no split: every group runs
        assert _run_guard(work, name)[0].returncode == 0, name
    work = _plan(tmp_path / "split", "cells", [groups[:2], groups[2:]])
    for name in ("rob_frames", "rob_cells"):
        assert _run_guard(work, name)[0].returncode == 0, name
    r, out = _run_guard(work, "rob_loeo")                 # launch 1: stop before the first launch-2 group
    assert r.returncode != 0 and "SPLIT_STOP" in r.stderr
    rep = json.loads((out / "stop_report_split.json").read_text())
    assert rep == {"code": "SPLIT_STOP", "stage": "rob_loeo", "gate": "rob_cells"}
    assert rs.name_free(rep) == rep                       # reaches summary.json whole
    resume = tmp_path / "resume"                          # a resume dir without the split group's marker: still stop
    resume.mkdir()
    assert _run_guard(work, "rob_perm", resume)[0].returncode != 0
    (resume / "rob_cells.done.json").write_text("{}\n")   # launch 2 (--resume-from launch 1): the groups run
    for name in ("rob_loeo", "rob_perm", "rob_null", "rob_post"):
        assert _run_guard(work, name, resume)[0].returncode == 0, name


def test_fig4_rows_compare_with_j1a_and_count_the_samples():
    rows = _rows()
    m = rows["fig4_m"]
    assert m["script"] == "pipeline/aws/r1/run_cells.py"
    a = _argv(m)
    assert _flag(a, "--cells") == "$REPO_DIR/config/r1/cells/fig4_M.tsv" and _flag(a, "--stack") == "rmac"
    assert _flag(a, "--frames") == f"{J1A_DIR}/frames" and _flag(a, "--gold-dir") == f"{J1A_DIR}/estimates"
    assert "--compare" in a and "--require-equal" in a          # the save_sample neutrality proof on M (N5)
    assert int(_flag(a, "--par")) * int(_flag(a, "--threads")) <= 64
    assert _flag(a, "--out") == "$STAGE_OUT" and m["outputs"] == ["work:prod/fig4_m"]
    for tok in ("repo:config/r1/cells/fig4_M.tsv", "repo:analysis/robustness/figure4/run_save_sample.R",
                "repo:analysis/lib/compare_json.py", "repo:analysis/lib/__init__.py", "env:rmac", "env:py",
                "stage:restore_j1a"):
        assert tok in m["inputs"], tok
    with open(REPO / "config" / "r1" / "cells" / "fig4_M.tsv", encoding="utf-8", newline="") as fh:
        cells = list(csv.DictReader(fh, delimiter="\t"))
    assert cells and {c["stack"] for c in cells} == {"rmac"} and {c["ref"] for c in cells} == {"-"}
    c = rows["fig4_counts"]
    assert c["script"] == "pipeline/aws/r1/fig4_counts.py"
    b = _argv(c)
    assert _flag(b, "--cells-out") == "$WORK/prod/fig4_m"
    assert _flag(b, "--out") == "$REPO_DIR/output/r1/robustness/fig4"
    assert c["outputs"] == ["repo:output/r1/robustness/fig4"] and c["needs"] == ["fig4_m"]
    assert "stage:fig4_m" in c["inputs"]


# ---------------------------------------------------------------------------------------------------------------
# hygiene: scripts, inputs, outputs, October paths, flags
# ---------------------------------------------------------------------------------------------------------------

def test_every_script_exists_and_inputs_are_precise():
    for name, row in _rows().items():
        if row.get("script"):
            assert (REPO / row["script"]).is_file(), name
        assert "stage:config" not in row["inputs"] and "stage:sandbox" not in row["inputs"], name
        req = set(row.get("requires", []))
        for tok in row["inputs"]:
            kind, val = tok.split(":", 1)
            if kind == "repo":
                p = REPO / val
                assert p.exists() or val in req, (name, val)          # absent until its unit lands: launch refuses
                assert not (val.startswith("data/") and p.is_dir()), (name, val)
            elif kind == "stage":
                assert val in _closure(_rows(), name), (name, val)
            elif kind == "env":
                assert val in ("py", "rmac", "rcloud"), (name, val)
            elif kind == "data":                                    # W2-INT: J0 review #4 carried to J1b
                assert val in _pinned() and val in {s for s, _d in _job()["data_sync"]}, (name, val)
            else:
                pytest.fail(f"{name}: unexpected input {tok}")


def test_output_tokens_are_product_level_and_disjoint_across_stages():
    toks = [(n, rs.resolve_out(t, work="/work", repo="/repo")) for n, r in _rows().items() for t in r["outputs"]]
    for i, (n, p) in enumerate(toks):
        for m, q in toks[i + 1:]:
            assert p != q and p not in q.parents and q not in p.parents, (n, p, m, q)   # run_one clears outputs
    for n, r in _rows().items():
        assert f"work:prod/{n}" in r["outputs"] or r["outputs"] == ["repo:output/r1/robustness/fig4"], n
        for t in r["outputs"]:
            if t.startswith("repo:"):
                assert t.startswith("repo:output/r1/robustness/"), (n, t)


def test_no_row_output_covers_a_base_input():
    with open(REPO / "config" / "r1" / "base_inputs.tsv", encoding="utf-8", newline="") as fh:
        base = [r["path"] for r in csv.DictReader(fh, delimiter="\t") if r["class"] in ("base", "r1_input")]
    assert base
    for name, row in _rows().items():
        for out in (t.split(":", 1)[1] for t in row["outputs"] if t.startswith("repo:")):
            hit = [b for b in base if b == out or b.startswith(out.rstrip("/") + "/") or out.startswith(b + "/")]
            assert not hit, (name, out, hit[:3])


def test_no_row_names_october_products():
    texts = {"table": J1B.read_text(encoding="utf-8"), "layout": LAYOUT.read_text(encoding="utf-8"),
             "job_env": json.dumps(_job()["env"]), "job_copy": json.dumps(_job()["copy_from_tip"])}
    for what, text in texts.items():
        for tok in FORBIDDEN:                             # the sandbox's --ref /work/ref/october names no file in it
            assert tok not in text, (what, tok)
    sb = _argv(_rows()["sandbox"])
    assert _flag(sb, "--ref") == REF


def _help(script, sub):
    env = dict(os.environ, SAR_HOST="ec2-r1-test", PYTHONDONTWRITEBYTECODE="1")
    env.pop("SAR_OUT_ROOT", None)
    r = subprocess.run([sys.executable, str(REPO / script), *([sub] if sub else []), "--help"], cwd=REPO, env=env,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, (script, sub, r.stderr[-800:])
    return r.stdout


def _usage(text):
    usage = text.split("\n\n", 1)[0]
    bare = usage
    while True:
        nxt = re.sub(r"\[[^\[\]]*\]|\([^()]*\)", " ", bare)
        if nxt == bare:
            break
        bare = nxt
    return set(re.findall(r"(?<![\w-])--[a-z0-9][a-z0-9-]*", bare))


def _invocations():
    out = []
    for name, row in _rows().items():
        script = row.get("script", "")
        if not script.endswith(".py"):
            continue
        toks = shlex.split(row["cmd"])
        where = [i for i, t in enumerate(toks) if t in (f"$WORK/{pathlib.PurePosixPath(script).name}",
                                                        f"$REPO_DIR/{script}")]
        assert where, (name, row["cmd"])
        args = []
        for t in toks[where[0] + 1:]:
            if t in SHELL_OPS:
                break
            args.append(t)
        sub = args[0] if args and not args[0].startswith("-") else None
        out.append((name, script, sub, [x for x in args if x.startswith("--")]))
    return out


def test_every_flag_in_a_py_row_exists_in_its_scripts_help():
    seen = {}
    for name, script, sub, flags in _invocations():
        key = (script, sub)
        if key not in seen:
            seen[key] = _help(script, sub)
        text = seen[key]
        for f in flags:
            assert re.search(rf"(?<![\w-]){re.escape(f)}(?![\w-])", text), (name, script, f)
        missing = _usage(text) - set(flags) - {"--help"}
        assert not missing, (name, script, f"required flags not passed: {sorted(missing)}")


# ---- W2-INT: the J0 review #4 and #5 fixes carried to J1b ------------------------------------------------------
#: the run_robustness_r1.sh group rows: the robustness drivers resolve paths through paths_m.yaml / paths_aws.yaml
#: and the no-centre rebuild reads the synced u1/U2 tables and legacy trees
DATA_ROWS = ("rob_frames", "rob_cells", "rob_loeo", "rob_perm", "rob_null", "rob_post")


def test_every_data_reading_row_fingerprints_the_pinned_data_layer():
    """J0 review #4, carried to J1b as bc077d9 did for j0.json: one data:<prefix> token per pinned data_sync
    prefix of config/r1/jobs/j1b.json on every row that reads /data, none elsewhere; re-pinning any one prefix
    changes exactly those rows' fingerprints."""
    rows = _rows()
    pins = json.loads((REPO / "config" / "r1" / "input_pins.json").read_text(encoding="utf-8"))
    prefixes = sorted(src for src, _dest in _job()["data_sync"] if src in pins["pins"])
    assert len(prefixes) >= 8
    for name, row in rows.items():
        data = sorted(t.split(":", 1)[1] for t in row["inputs"] if t.startswith("data:"))
        assert data == (prefixes if name in DATA_ROWS else []), name
    env_pins = json.loads((REPO / "config" / "r1" / "env_pins.json").read_text(encoding="utf-8"))
    head = rs.git(REPO, "rev-parse", "HEAD")
    done = {n: {"outputs_digest": "0" * 64} for n in rows}
    tracked = set(subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True,
                                 check=True).stdout.splitlines())

    def known(val):
        return any(t == val or t.startswith(val.rstrip("/") + "/") for t in tracked)

    rows = {n: dict(r, inputs=[t for t in r["inputs"] if not (t.startswith("repo:") and not known(t[5:]))])
            for n, r in rows.items() if r.get("resume") != "always"}

    def fps(p):
        return {n: rs.fingerprint(r, repo=REPO, commit=head, pins=p, env_pins=env_pins, done=done) for n, r in rows.items()}

    before = fps(pins)
    for prefix in prefixes:
        moved = json.loads(json.dumps(pins))
        moved["pins"][prefix]["manifest_sha256"] = "f" * 64
        after = fps(moved)
        assert {n for n in rows if after[n] != before[n]} == set(DATA_ROWS), prefix


def test_sandbox_check_audits_the_span_of_its_own_table():
    """J0 review #5 made `sandbox.py check --table` required (aae00b5): without it J1b's last row exits at once."""
    import sandbox as sb                                                    # noqa: PLC0415
    toks = shlex.split(_rows()["sandbox_check"]["cmd"])
    assert toks[toks.index("--table") + 1] == "$REPO_DIR/config/r1/stages/j1b.json"
    span = sb.audited_span(J1B)
    assert span and span[0] == "rob_jobs" and span[-1] == "rob_post"
