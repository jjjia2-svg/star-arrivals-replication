# -*- coding: utf-8 -*-
"""config/r1/stages/j1a.json + config/r1/jobs/j1a.json + config/r1/read_allowlist_0828.txt (W2-TJ1A): the J1a
table builds config M inside the F2 sandbox, end to end: link to the passed J0, the rank (RK6b rerun, gate,
rank tables), calls, events, the outcome patch, the econ and chem/maths frames, A_far, the assembled frames,
the paper-side extractions, the memory probe, the 27 M cells, the M estimates dir, promotion and the sandbox
check. Reads committed config files; the --help probes run each script's argument parser only; the bash probes
run single rows on a toy WORK with stand-in scripts (no data, no network).

Runs on the integrated wave-2 tip: econ920_m.py, chemmath_m.py, dose_chemmath.py (W2-ECONM / W2-CHEMM) and
config/r1/M.json (W2-CONFIGM) are named by the table and must exist there. The merged roster parquets arrive
later (P3a / W3-MPIN): each row that reads one lists it in `requires`, so the kit refuses a launch until it is
committed (LATE_INPUTS)."""
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
import tempfile

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import run_stages as rs     # noqa: E402
import sandbox as sb        # noqa: E402

J1A = REPO / "config" / "r1" / "stages" / "j1a.json"
J1B = REPO / "config" / "r1" / "stages" / "j1b.json"
JOB = REPO / "config" / "r1" / "jobs" / "j1a.json"
RANKREPRO = REPO / "config" / "r1" / "jobs" / "rankrepro.json"
ALLOW = REPO / "config" / "r1" / "read_allowlist_0828.txt"
CELLS = REPO / "config" / "r1" / "cells"
REF = "/work/ref/october"
M_JSON = "$REPO_DIR/config/r1/M.json"
ORDER = ["verify_inputs", "relink", "config", "sandbox", "gate1_link", "rank_requests", "rank_m", "rank_gate",
         "rank_tables", "calls", "events", "patch_assemble", "frames_econ920", "frames_chemmath_m", "afar_m", "frames",
         "new_numbers", "star_origins_extract", "mem_probe", "cells_rmac", "cells_rcloud", "cells_rmac_evcl",
         "cells_rcloud_evcl", "estimates_m", "promote", "sandbox_check"]
#: rows that only set up or check isolation and custody; every other row builds M and runs after `sandbox`
SETUP = ("verify_inputs", "relink", "config", "sandbox")
ALWAYS = ("verify_inputs", "relink", "config", "sandbox", "gate1_link", "sandbox_check")
#: the merged R1 rosters (P3a rostermerge-03, committed in d124ed7 and pinned in config/r1/M.json by W3-MPIN): a row
#: that reads one must still `require` it, so r1kit.check_stage_table refuses a launch from a tree without them
LATE_INPUTS = {
    "data/cal2026-10r1/inputs/rosters/roster_econ_verified_r1.parquet",
    "data/cal2026-10r1/inputs/rosters/roster_gold_chemistry_r1.parquet",
    "data/cal2026-10r1/inputs/rosters/roster_gold_math_stats_r1.parquet",
}
#: the rows that run the chem/maths M build on the 11-school edge table (N2 shadow); econ rows never do
N2_ROWS = {"frames_chemmath_m", "new_numbers"}
TABLE_11 = "/data/openalex_pipeline/derived/u1_full_11school_2026-07-16"
#: rows whose October-product reads go through a per-stage view of the clone (rk6b_rank and restake_r1 read
#: <repo>/data/cal2026-10/<file> by path; the sandbox moved those files to the reference copy)
VIEW_FILES = {"rank_m": ["events_econ_cal2026-10.csv", "events_econ_cal2026-10_p05.csv",
                         "events_chemistry_cal2026-10.csv", "events_chemistry_cal2026-10_p05.csv",
                         "events_math_stats_cal2026-10.csv", "events_math_stats_cal2026-10_p05.csv"],
              "rank_tables": ["restake_econ11_aug_2026-10.csv"]}
#: what M does not build (C10: old79/new37 run in B0 only; no p05/dosebin3 variant slims in J1a)
ALLOWED_MISSING = ["p1_frame_econ_old79.csv", "p1_frame_econ_new37.csv"] + [
    f"p3_slim_{f}_{v}.parquet" for f in ("econ", "chemistry", "math_stats") for v in ("p05", "dosebin3")]
OPS = {"&&", "||", ";", "|", ">", ">>", "<", "(", ")", "&", ";;"}


def _table(p=J1A):
    return rs.load_table(p)


def _rows(p=J1A):
    return {s["name"]: s for s in _table(p)["stages"]}


def _job():
    return json.loads(JOB.read_text(encoding="utf-8"))


def _tokens(cmd):
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    return list(lex)


def _argv(cmd, script_token):
    """The argument list after `script_token` in cmd, up to the next shell operator."""
    toks = _tokens(cmd)
    i = toks.index(script_token)
    out = []
    for t in toks[i + 1:]:
        if t in OPS:
            break
        out.append(t)
    return out


def _flag(cmd, script_token, flag, n=1):
    a = _argv(cmd, script_token)
    i = a.index(flag)
    return a[i + 1] if n == 1 else a[i + 1:i + 1 + n]


def _repo_tokens(toks, kind="repo"):
    return [t.split(":", 1)[1] for t in toks if t.startswith(kind + ":")]


def _py_calls(name, row):
    """(script repo path, subcommand, flags) for every `"$PY" <script>.py ...` invocation in a row's cmd: a
    `$WORK/<basename>` script is the row's own `script` (run_stages copies it there), a `$REPO_DIR/<path>`
    script runs in place (October launchers and libraries that locate the repo from their own path)."""
    toks, out = _tokens(row["cmd"]), []
    for i, t in enumerate(toks[:-1]):
        nxt = toks[i + 1]
        if t != "$PY" or not nxt.endswith(".py"):
            continue
        if nxt.startswith("$WORK/"):
            assert row.get("script") and pathlib.PurePosixPath(row["script"]).name == nxt[len("$WORK/"):], (name, nxt)
            script = row["script"]
        else:
            assert nxt.startswith("$REPO_DIR/"), (name, nxt)
            script = nxt[len("$REPO_DIR/"):]
        args = []
        for x in toks[i + 2:]:
            if x in OPS:
                break
            args.append(x)
        sub = args[0] if args and not args[0].startswith("-") and not args[0].startswith("$") else None
        out.append((script, sub, [a for a in args if a.startswith("--")]))
    return out


# ---- shape -------------------------------------------------------------------------------------------------
def test_rows_in_order_with_valid_needs_and_the_table_is_complete_after_f30():
    t = _table()                                        # load_table refuses a need that runs later
    assert t["job"] == "j1a" and t["complete"] is True    # W3-FLIPS set it after the R7 reviews (46a2333)
    assert [s["name"] for s in t["stages"]] == ORDER
    names = [s["name"] for s in t["stages"]]
    for s in t["stages"]:
        assert set(s["needs"]) <= set(names[:names.index(s["name"])]), s["name"]
        for tok in s["inputs"]:                         # a stage: input is a need, so its done marker exists
            if tok.startswith("stage:"):
                assert tok[len("stage:"):] in s["needs"], (s["name"], tok)
        assert s["outputs"] and all(o.startswith(("work:prod/", "repo:output/")) for o in s["outputs"]), s["name"]
    assert "coverage_chemmath" not in names              # chem/maths coverage runs inside chemmath_m (W2-CHEMM)


def test_sandbox_precedes_every_m_row_and_sandbox_check_is_last():
    names, rows = [s["name"] for s in _table()["stages"]], _rows()
    assert names[:4] == list(SETUP) and names[-1] == "sandbox_check"
    for name in ALWAYS:
        assert rows[name].get("resume") == "always", name
    for name in set(names) - set(ALWAYS):
        assert rows[name].get("resume") is None, name
    sb_cmd, ck, cf = rows["sandbox"]["cmd"], rows["sandbox_check"]["cmd"], rows["config"]["cmd"]
    s = '$WORK/sandbox.py'
    assert _argv(sb_cmd, s)[0] == "purge" and _flag(sb_cmd, s, "--config") == "M" and _flag(sb_cmd, s, "--ref") == REF
    assert _flag(sb_cmd, s, "--table") == "$REPO_DIR/config/r1/stages/j1a.json"
    assert _flag(sb_cmd, s, "--allowlist") == "$REPO_DIR/config/r1/read_allowlist_0828.txt"
    a = _argv(ck, s)
    assert a[0] == "check" and _flag(ck, s, "--config") == "M"
    assert [a[i + 1] for i, x in enumerate(a) if x == "--reads"] == ["/work/reads", "/work/resume/_reads"]
    assert _flag(ck, s, "--record") == "$WORK/prod/sandbox/base_record.json"
    assert set(rows["sandbox_check"]["needs"]) >= {"sandbox", "promote"}
    assert _argv(cf, "$WORK/config_check.py")[0] == "check" and _flag(cf, "$WORK/config_check.py", "--config") == M_JSON
    assert "config/r1/M.json" in rows["config"].get("requires", [])
    lk = rows["gate1_link"]["cmd"]
    assert _argv(lk, "$WORK/gates.py")[0] == "link" and _flag(lk, "$WORK/gates.py", "--j0") == "/work/j0"
    assert _flag(lk, "$WORK/gates.py", "--commit") == "$COMMIT"
    assert names.index("gate1_link") < names.index("rank_requests")


def test_every_script_exists_and_every_repo_input_is_tracked_or_a_required_late_input():
    tracked = set(subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True,
                                 check=True).stdout.splitlines())
    for name, row in _rows().items():
        if row.get("script"):
            assert (REPO / row["script"]).is_file(), (name, row["script"])
        for rel in row.get("requires", []):
            assert (REPO / rel).exists() or rel in LATE_INPUTS, (name, rel)
        for rel in _repo_tokens(row["inputs"]):
            p = REPO / rel
            if rel in LATE_INPUTS:
                assert rel in row.get("requires", []), (name, rel, "a late input must be required")
                continue
            assert p.exists(), (name, rel)
            assert p.is_dir() or rel in tracked, (name, rel)
            if p.is_dir() and rel.startswith("data/"):           # a data dir input is a precise R1 input set
                assert rel.startswith(("data/cal2026-10r1/inputs/", "data/paper_inputs/")), (name, rel)
        for script, _, _ in _py_calls(name, row):
            assert (REPO / script).is_file(), (name, script)
        assert "stage:config" not in row["inputs"] and "stage:sandbox" not in row["inputs"], name


def test_data_and_env_inputs_have_pins():
    pins = json.loads((REPO / "config" / "r1" / "input_pins.json").read_text(encoding="utf-8"))["pins"]
    layers = json.loads((REPO / "config" / "r1" / "env_pins.json").read_text(encoding="utf-8"))["layers"]
    for name, row in _rows().items():
        for val in _repo_tokens(row["inputs"], "data"):
            assert val in pins, (name, val)                         # run_stages.fingerprint would stop otherwise
        for val in _repo_tokens(row["inputs"], "env"):
            assert val in layers and val in _job()["env_layers"], (name, val)


def test_every_repo_output_is_product_level():
    with open(REPO / "config" / "r1" / "base_inputs.tsv", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    base = [r["path"] for r in rows if r["class"] in ("base", "r1_input")]
    assert base
    for name, row in _rows().items():
        for out in _repo_tokens(row["outputs"]):
            assert out.startswith("output/"), (name, out)          # never data/, data/frames or analysis/expected
            hit = [b for b in base if b == out or b.startswith(out.rstrip("/") + "/") or out.startswith(b + "/")]
            assert not hit, (name, out, hit[:3])
        for out in row["outputs"]:
            assert out != "repo:output/cal_intermediates/cal2026-10" and "analysis/expected" not in out, (name, out)


# ---- the --help probes ---------------------------------------------------------------------------------------
def _usage(text):
    """The required flags of an argparse usage paragraph (those outside any [...] or (...))."""
    bare = text.split("\n\n", 1)[0]
    while True:
        nxt = re.sub(r"\[[^\[\]]*\]|\([^()]*\)", " ", bare)
        if nxt == bare:
            break
        bare = nxt
    return set(re.findall(r"(?<![\w-])--[a-z0-9][a-z0-9-]*", bare))


def _help(script, sub, staged=False):
    """`script --help`. staged: run a copy at <tmp>/work/<basename> with $REPO_DIR set, the way run_stages runs a
    `"$PY" "$WORK/<basename>"` row (M review #1: econ920_m.py found the repo from its own path and died there)."""
    env = dict(os.environ, SAR_HOST="ec2-r1-test", PYTHONDONTWRITEBYTECODE="1")
    for k in ("SAR_OUT_ROOT", "SAR_R1_CONFIG", "SAR_SSD_ROOT"):
        env.pop(k, None)
    with tempfile.TemporaryDirectory() as tmp:
        target = REPO / script
        if staged:
            target = pathlib.Path(tmp) / "work" / pathlib.PurePosixPath(script).name
            target.parent.mkdir()
            shutil.copyfile(REPO / script, target)
            env["REPO_DIR"] = str(REPO)
        r = subprocess.run([sys.executable, str(target), *([sub] if sub else []), "--help"], cwd=REPO, env=env,
                           capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, (script, sub, staged, r.stderr[-800:])
    return r.stdout


def test_every_flag_in_a_py_row_exists_in_its_scripts_help():
    seen, n = {}, 0
    for name, row in _rows().items():
        for script, sub, flags in _py_calls(name, row):
            if not flags:                     # rk6b_rank.py takes its paths from RK_* env and has no parser:
                continue                      # `--help` would RUN it, and it has no flag to check
            key = (script, sub)
            staged = script == row.get("script") and f"$WORK/{pathlib.PurePosixPath(script).name}" in _tokens(row["cmd"])
            if key not in seen:
                seen[key] = _help(script, sub, staged=staged)
            text = seen[key]
            for f in flags:
                assert re.search(rf"(?<![\w-]){re.escape(f)}(?![\w-])", text), (name, script, f)
            missing = _usage(text) - set(flags) - {"--help"}
            assert not missing, (name, script, f"required flags not passed: {sorted(missing)}")
            n += 1
    assert n >= 20
    assert re.search(r"(?<![\w-])--raw(?![\w-])", seen[("pipeline/aws/r1/patch_assemble.py", None)])
    assert re.search(r"(?<![\w-])--manifest(?![\w-])", seen[("pipeline/aws/r1/patch_assemble.py", None)])


# ---- the rank rows: the rankrepro commands, run on a view of the clone -----------------------------------------
def _rankrepro_inner():
    steps = json.loads(RANKREPRO.read_text(encoding="utf-8"))["steps"]
    out = {}
    for s in steps:
        m = re.match(r'^export STAGE_OUT=/work/prod/([a-z0-9_]+) && mkdir -p "\$STAGE_OUT" && \{ (.*); \}; rc=\$\?;', s)
        if m:
            out[m.group(1)] = m.group(2)
    assert set(out) >= {"rank_requests", "rank_m", "rank_gate", "rank_tables"}
    return out


def test_rank_rows_run_the_rankrepro_commands():
    rows, inner = _rows(), _rankrepro_inner()
    assert rows["rank_requests"]["cmd"] == inner["rank_requests"]
    assert rows["rank_gate"]["cmd"] == inner["rank_gate"]
    assert 'RK_REPO="$REPO_DIR"' in inner["rank_m"] and '--repo "$REPO_DIR"' in inner["rank_tables"]
    assert rows["rank_m"]["cmd"].endswith(" && " + inner["rank_m"].replace('RK_REPO="$REPO_DIR"', 'RK_REPO="$V"'))
    assert rows["rank_tables"]["cmd"].endswith(" && " + inner["rank_tables"].replace('--repo "$REPO_DIR"', '--repo "$V"'))
    for name in ("rank_m", "rank_tables"):
        assert rows[name]["cmd"].startswith(f'V="$WORK/tmp/view_{name}" && '), name
    assert rows["rank_requests"]["script"] == "pipeline/aws/r1/rk6_requests.py"
    assert rows["rank_m"]["script"] == "pipeline/aws/r1/rk6b_rank.py"
    assert rows["rank_gate"]["script"] == "pipeline/aws/r1/rank_r1.py"
    assert rows["rank_tables"]["script"] == "pipeline/aws/r1/restake_r1.py"
    # calls must fold the very REF4 copies rank_requests used (else its fold-equality STOP fires)
    rq, cl = rows["rank_requests"]["cmd"], rows["calls"]["cmd"]
    assert _flag(cl, "$WORK/calls_lib.py", "--merged") == _flag(rq, "$WORK/rk6_requests.py", "--merged")
    assert _flag(cl, "$WORK/calls_lib.py", "--recovered") == _flag(rq, "$WORK/rk6_requests.py", "--recovered")
    assert _flag(cl, "$WORK/calls_lib.py", "--rk6a") == _flag(rq, "$WORK/rk6_requests.py", "--rk6a-out")
    assert _flag(cl, "$WORK/calls_lib.py", "--requests") == "$WORK/prod/rank_requests/in6"
    assert _flag(cl, "$WORK/calls_lib.py", "--config") == M_JSON
    assert "SAR_SSD_ROOT=/data/openalex_pipeline" in _tokens(cl)


def _fake(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("import json, os, pathlib, sys\n" + body, encoding="utf-8")


def _bash(cmd, *, repo, work, stage):
    out = work / "prod" / stage
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PY=sys.executable, REPO_DIR=str(repo), WORK=str(work), STAGE_OUT=str(out), COMMIT="c" * 40)
    r = subprocess.run(["bash", "-c", cmd], cwd=work, env=env, capture_output=True, text=True)
    return r, out


def _toy_repo(tmp_path):
    repo = tmp_path / "toy repo"
    for rel in ("pipeline/x.py", "config/r1/a.json", "data/cal2026-10/_invalid_run2/candidates_2026-10.csv",
                "data/cal2026-10/calls_2026-10.csv", "data/cal2026-10r1/inputs/flips_r1.json", ".git/HEAD"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("x\n")
    return repo


#: a stand-in that records what the view looks like (top level, data/, data/cal2026-10/ with link targets)
VIEW_PROBE = ("def look(v):\n"
              "    v = pathlib.Path(v)\n"
              "    def ent(d): return {p.name: (os.readlink(p) if p.is_symlink() else 'DIR' if p.is_dir() else 'FILE')"
              " for p in sorted(d.iterdir())}\n"
              "    return {'top': ent(v), 'data': ent(v / 'data'), 'cal': ent(v / 'data' / 'cal2026-10')}\n")


@pytest.mark.parametrize("stage", ["rank_m", "rank_tables"])
def test_the_view_links_the_clone_and_only_the_named_reference_files(tmp_path, stage):
    repo, work = _toy_repo(tmp_path), tmp_path / "work"
    if stage == "rank_m":
        _fake(work / "rk6b_rank.py", VIEW_PROBE +
              "out = pathlib.Path(os.environ['RK_OUT']); out.mkdir(parents=True, exist_ok=True)\n"
              "(out / 'summary.json').write_text(json.dumps(look(os.environ['RK_REPO'])))\n"
              "(out / 'duck_11').write_text('db')\n(out / 'RESULT.txt').write_text('OK\\n')\n")
    else:
        _fake(work / "restake_r1.py", VIEW_PROBE +
              "a = sys.argv; out = pathlib.Path(a[a.index('--out') + 1]); out.mkdir(parents=True, exist_ok=True)\n"
              "(out / 'summary.json').write_text(json.dumps(look(a[a.index('--repo') + 1])))\n")
    r, out = _bash(_rows()[stage]["cmd"], repo=repo, work=work, stage=stage)
    assert r.returncode == 0, r.stderr[-800:]
    seen = json.loads((out / "summary.json").read_text())
    assert seen["data"]["cal2026-10"] == "DIR" and seen["top"]["data"] == "DIR"
    assert seen["top"]["pipeline"] == str(repo / "pipeline") and seen["top"][".git"] == str(repo / ".git")
    assert seen["data"]["cal2026-10r1"] == str(repo / "data" / "cal2026-10r1")
    want = {f: f"{REF}/data/cal2026-10/{f}" for f in VIEW_FILES[stage]}
    assert {k: v for k, v in seen["cal"].items() if v.startswith(REF)} == want
    assert seen["cal"]["_invalid_run2"] == str(repo / "data/cal2026-10/_invalid_run2")
    assert seen["cal"]["calls_2026-10.csv"] == str(repo / "data/cal2026-10/calls_2026-10.csv")
    if stage == "rank_m":                                 # only the seven named files leave /work/tmp
        assert not (out / "duck_11").exists() and (out / "RESULT.txt").read_text() == "OK\n"
        assert not (work / "tmp" / "rank_m").exists()
    # a second run rebuilds the view from scratch (a left-over view would make `ln -s` fail)
    for p in out.iterdir():
        p.unlink()
    r2, _ = _bash(_rows()[stage]["cmd"], repo=repo, work=work, stage=stage)
    assert r2.returncode == 0, r2.stderr[-800:]


# ---- the sandbox allowlist for M -------------------------------------------------------------------------------
def _allow_m():
    return [r for r in sb.load_allowlist(ALLOW) if "M" in r.configs or "*" in r.configs]


def _allowed(path, stage):
    """True when an M allowlist row admits `path` ('ref:<p>' or a repo path) read by `stage`."""
    for r in _allow_m():
        ref = r.glob.startswith("ref:")
        if ref != path.startswith("ref:"):
            continue
        pat = sb.glob_re(r.glob[4:] if ref else r.glob)
        if pat.fullmatch(path[4:] if ref else path) and (r.stages is None or stage in r.stages):
            return True
    return False


def test_every_reference_read_of_an_m_row_is_allowlisted_for_that_stage():
    rows = _rows()
    for stage, files in VIEW_FILES.items():
        m = re.search(r'for f in ([^;]*); do ln -s "' + re.escape(REF) + r'/data/cal2026-10/\$f"', rows[stage]["cmd"])
        assert m and m.group(1).split() == files, stage                  # the view links exactly these files
        for f in files:
            assert _allowed(f"ref:data/cal2026-10/{f}", stage), (stage, f)
    ev = rows["events"]["cmd"]
    assert _flag(ev, "$WORK/events_r1.py", "--october") == f"{REF}/data/cal2026-10"
    for f in VIEW_FILES["rank_m"] + ["events_decision_2026-10.json"]:
        assert _allowed(f"ref:data/cal2026-10/{f}", "events"), f
    for fld in ("econ", "chemistry", "math_stats"):
        assert _allowed(f"data/raw_verified/events_{fld}_cal2026-08-28.csv", "events"), fld
    pr = rows["promote"]["cmd"]
    assert _flag(pr, "$WORK/promote_r1.py", "--october-golds") == f"{REF}/analysis/expected"
    assert _flag(pr, "$WORK/promote_r1.py", "--october-frames") == f"{REF}/data/frames"
    assert _allowed("ref:analysis/expected/P1_econ_fnfix.json", "promote")
    assert _allowed("ref:data/frames/p1_frame_econ.csv", "promote")
    for stage in ("frames_econ920", "frames_chemmath_m"):
        assert _allowed("data/cal2026-08-28/stars_excluded_cal2026-08-28.parquet", stage), stage
        assert _allowed("data/raw_verified/events_econ_cal2026-08-28.csv", stage), stage
    for p in ("data/cal2026-08-28/frames/p1_frame_econ.csv", "data/cal2026-08-28/estimates/P1_econ_fnfix.json",
              "data/cal2026-08-28/MANIFEST.sha256"):
        assert _allowed(p, "frames_econ920"), p
    assert _allowed("data/cal2026-08-28/calls_2026-08-28.csv", "calls")
    assert _allowed("data/cal2026-08-28/edges_supplement_cal2026-08-28.jsonl", "new_numbers")
    # nothing else in M may read the reference copy: no '*' stage list on an M ref row, no M row for gate stages
    for r in _allow_m():
        if r.glob.startswith("ref:"):
            assert r.stages and "*" not in r.configs, r.glob
    assert not _allowed("ref:analysis/expected/P1_econ_fnfix.json", "cells_rmac")
    assert not _allowed("ref:data/cal2026-10/events_econ_cal2026-10.csv", "frames_econ920")


def test_m_allowlist_rows_name_j1a_or_j1b_stages():
    names = set(_rows())
    if J1B.is_file():
        names |= {s["name"] for s in json.loads(J1B.read_text(encoding="utf-8"))["stages"]}
    for r in sb.load_allowlist(ALLOW):
        if r.configs == ("M",) and r.stages is not None:
            assert set(r.stages) <= names, (r.glob, sorted(set(r.stages) - names))


# ---- calls, events, patch, econ, chem/maths, afar, frames --------------------------------------------------------
def test_m_rows_take_every_path_as_a_flag():
    rows = _rows()
    ev = rows["events"]["cmd"]
    e = "$WORK/events_r1.py"
    assert _flag(ev, e, "--mode") == "m" and _flag(ev, e, "--rank-tables") == "$WORK/prod/rank_tables"
    assert _flag(ev, e, "--calls") == "$WORK/prod/calls" and _flag(ev, e, "--raw-0828") == "$REPO_DIR/data/raw_verified"
    assert _flag(ev, e, "--addlist-summary") == "$REPO_DIR/data/cal2026-10r1/inputs/add_list_r1_summary.json"
    assert set(rows["events"]["needs"]) >= {"rank_tables", "calls"}
    ec = rows["frames_econ920"]["cmd"]
    x = "$WORK/econ920_m.py"
    assert rows["frames_econ920"]["script"] == "pipeline/aws/r1/econ920_m.py" and "--execute" in _argv(ec, x)
    assert _flag(ec, x, "--config") == M_JSON and _flag(ec, x, "--events") == "$WORK/prod/events"
    assert _flag(ec, x, "--rank-tables") == "$WORK/prod/rank_tables" and _flag(ec, x, "--calls") == "$WORK/prod/calls"
    assert _flag(ec, x, "--roster-econ") == "$REPO_DIR/data/cal2026-10r1/inputs/rosters/roster_econ_verified_r1.parquet"
    assert _flag(ec, x, "--patch-extra") == "$WORK/prod/patch_assemble/works_by_author_supplement_r1.jsonl"
    oct_patch = "data/cal2026-10/patch_supplement_2026-10/works_by_author_supplement_2026-10.jsonl"
    assert _flag(ec, x, "--patch-october") == f"$REPO_DIR/{oct_patch}"      # W2-ECONM: October's supplement first
    assert f"repo:{oct_patch}" in rows["frames_econ920"]["inputs"]
    assert _flag(ec, x, "--out") == "$STAGE_OUT"
    assert set(rows["frames_econ920"]["needs"]) >= {"events", "rank_tables", "calls", "patch_assemble"}
    cm = rows["frames_chemmath_m"]["cmd"]
    c = "$WORK/chemmath_m.py"
    assert rows["frames_chemmath_m"]["script"] == "pipeline/aws/r1/chemmath_m.py"
    assert _flag(cm, c, "--mode") == "m" and _flag(cm, c, "--roster-variant") == "fnfix"
    assert _flag(cm, c, "--config") == M_JSON and _flag(cm, c, "--events-dir") == "$WORK/prod/events"
    for f in ("chemistry", "math_stats"):
        flag = "--roster-" + f.replace("_", "-")
        assert _flag(cm, c, flag) == f"$REPO_DIR/data/cal2026-10r1/inputs/rosters/roster_gold_{f}_r1.parquet"
    assert _flag(cm, c, "--stars-excluded-base") == "$REPO_DIR/data/cal2026-08-28/stars_excluded_cal2026-08-28.parquet"
    af = rows["afar_m"]["cmd"]
    a = "$REPO_DIR/pipeline/frames/cal2026-10/run_cal_afar.py"
    assert "--execute" in _argv(af, a) and _flag(af, a, "--out") == "$STAGE_OUT"
    assert _flag(af, a, "--econ-dir") == "$WORK/prod/frames_econ920/afar_econ"
    assert _flag(af, a, "--chem-dir") == "$WORK/prod/frames_chemmath_m/frames_chemistry"
    assert _flag(af, a, "--math-dir") == "$WORK/prod/frames_chemmath_m/frames_math_stats"
    assert 'rm -rf "$WORK/tmp/afar_m"' in af and 'SAR_OUT_ROOT="$WORK/tmp/afar_m"' in af   # a fresh scratch root
    for name in ("frames_econ920", "frames_chemmath_m"):                                  # the run_config.py env
        cmd = rows[name]["cmd"]
        assert f'rm -rf "$WORK/tmp/{name}"' in cmd and f'SAR_OUT_ROOT="$WORK/tmp/{name}"' in cmd, name
        assert 'R_LIBS="$SAR_RLIB_RMAC"' in cmd and 'cd "$REPO_DIR"' in cmd and "env:rmac" in rows[name]["inputs"], name


def test_frames_assembles_the_m_stage_dirs_into_the_cells_frames_dir():
    row = _rows()["frames"]
    a = "$REPO_DIR/pipeline/frames/cal2026-10/assemble_frames.py"
    cmd = row["cmd"]
    assert row["script"] == "pipeline/frames/cal2026-10/assemble_frames.py" and "--execute" in _argv(cmd, a)
    assert _flag(cmd, a, "--econ-dir") == _flag(cmd, a, "--econ-p1-dir") == "$WORK/prod/frames_econ920/frames_econ"
    assert _flag(cmd, a, "--chem-dir") == "$WORK/prod/frames_chemmath_m/frames_chemistry"
    assert _flag(cmd, a, "--math-dir") == "$WORK/prod/frames_chemmath_m/frames_math_stats"
    assert _flag(cmd, a, "--afar-dir") == "$WORK/prod/afar_m"
    assert _flag(cmd, a, "--pairs-econ") == "$WORK/prod/frames_econ920/pairs/pairs_unified.csv"
    assert _flag(cmd, a, "--pairs-pin") == "$WORK/prod/frames_econ920/build_report_econ_m.json#m.pairs_unified"
    assert _flag(cmd, a, "--out") == "$STAGE_OUT"       # STAGE_OUT = $WORK/prod/frames: what the cells read (R10)
    args = _argv(cmd, a)
    i = args.index("--allow-missing")
    assert args[i + 1:i + 1 + len(ALLOWED_MISSING)] == ALLOWED_MISSING
    assert not _flag(cmd, a, "--variants-dir").startswith(("$REPO_DIR", REF))     # M builds no variant slims
    assert row["outputs"] == ["work:prod/frames", "repo:output/cal_intermediates/pairs_unified.csv"]
    assert row["needs"] == ["frames_econ920", "frames_chemmath_m", "afar_m"]


# ---- Figure 1 star origins: every star re-extracted on the complete U1 tables ----------------------------------
ORIGINS_X = "$REPO_DIR/tools/star_origins_extract_2026-10.py"
#: the data the full scan reads (paths_aws.yaml ssd_root /data/openalex_pipeline): snapshot authors/institutions,
#: works_affil + authorship_edges of both U1 tables (u1_sources), the U2 person map (econ fragments)
_D = "/data/openalex_pipeline/derived/"
ORIGINS_DATA = {"r1/snapshot/authors/": "/data/openalex_pipeline/snapshot/authors/",
                "r1/snapshot/institutions/": "/data/openalex_pipeline/snapshot/institutions/",
                "u1_edges_full_2026-07-05/": f"{_D}u1_edges_full_2026-07-05/",
                "u1_full_11school_2026-07-16/": f"{_D}u1_full_11school_2026-07-16/",
                "u2_person_map_11school_2026-07-16/": f"{_D}u2_person_map_11school_2026-07-16/"}


def _origins_extractor():
    import importlib.util                                                   # noqa: PLC0415
    spec = importlib.util.spec_from_file_location("star_origins_extract_j1a", REPO / "tools" / "star_origins_extract_2026-10.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_star_origins_extract_rescans_every_star_and_merges_the_overrides(tmp_path):
    """pipeline/NOT_REPRODUCIBLE.md entry 18: October's frozen n_works were counted on a partial U1 works_affil (120
    of 256 files), so the --from-frozen reuse would keep partial-table counts for reused stars while new stars got
    complete ones. Ruling 2026-10-16 (R1 orchestrator, ledger): in M every star's machine origin is re-extracted on
    the complete tables - no --from-frozen / --frozen-events / --stars / --u1-view (the U1_PARTIAL guard then reads
    every file). The human overrides apply as before (R1P3-44: October's table and the r1 table, keyed by
    (discipline, star_id, arrival_year), re-dates through the run's events_decision), and the name-free report
    carries the missing / ambiguous ids for the F21 Mac reading. The row also passes the extractor's own CLI rules
    for a run's events (before: no override flags and --from-frozen without --frozen-events, both SystemExit)."""
    row = _rows()["star_origins_extract"]
    cmd = row["cmd"]
    a = _argv(cmd, ORIGINS_X)
    for f in ("--from-frozen", "--frozen-events", "--stars", "--u1-view", "--overrides-only"):
        assert f not in a, f
    assert _flag(cmd, ORIGINS_X, "--events-dir") == "$WORK/prod/events"
    assert _flag(cmd, ORIGINS_X, "--out-dir") == "$STAGE_OUT"                 # the canon takes the whole stage dir
    assert _flag(cmd, ORIGINS_X, "--events-decision") == "$WORK/prod/events/events_decision_2026-10.json"
    oct_ovr = "data/paper_inputs/star_origins_2026-10/human_origin_overrides.csv"
    r1_ovr = "data/cal2026-10r1/inputs/star_origins/human_origin_overrides_r1.csv"
    corr = "data/cal2026-10/star_id_corrections_2026-10.csv"
    assert _flag(cmd, ORIGINS_X, "--october-overrides") == f"$REPO_DIR/{oct_ovr}"
    assert _flag(cmd, ORIGINS_X, "--r1-overrides") == f"$REPO_DIR/{r1_ovr}"
    assert _flag(cmd, ORIGINS_X, "--id-corrections") == f"$REPO_DIR/{corr}"
    assert _flag(cmd, ORIGINS_X, "--report") == "$STAGE_OUT/report_star_origins.json"   # reaches summary.json
    # the frozen extraction is no longer an input (only its hand-curated override table is)
    assert "repo:data/paper_inputs/star_origins_2026-10" not in row["inputs"]
    assert row["script"] == "tools/star_origins_extract_2026-10.py"          # its blob is in the fingerprint
    assert {f"repo:{oct_ovr}", f"repo:{r1_ovr}", f"repo:{corr}", "repo:analysis/paper/fig_star_origins.py",
            "stage:events"} <= set(row["inputs"])
    assert row["outputs"] == ["work:prod/star_origins_extract"] and row["needs"] == ["events"]
    lay = json.loads((REPO / "config" / "r1" / "canon_layout.json").read_text(encoding="utf-8"))["rows"]
    assert {"dest": "paper_inputs/star_origins_2026-10", "from": {"job": "j1a", "stage": "star_origins_extract",
                                                               "token": "work:prod/star_origins_extract",
                                                               "rel": ""}} in lay
    # the argv passes the extractor's CLI rules for a run's events (toy paths; nothing is read)
    X = _origins_extractor()
    sub = {"WORK": str(tmp_path / "work"), "STAGE_OUT": str(tmp_path / "work" / "prod" / "star_origins_extract"),
           "REPO_DIR": str(REPO)}
    ns = X.parse_args([re.sub(r"\$(WORK|STAGE_OUT|REPO_DIR)\b", lambda m: sub[m.group(1)], t) for t in a])
    events_dir, out_dir, october = X.check_args(ns, {"cal": REPO / "data" / "cal2026-10"})
    assert october is False and ns.from_frozen is None and ns.u1_view is None
    assert events_dir == tmp_path / "work" / "prod" / "events" and out_dir == pathlib.Path(sub["STAGE_OUT"])


def test_star_origins_extract_data_is_synced_and_the_pinned_part_fingerprinted():
    """The full scan reads ORIGINS_DATA: each is a data_sync pair of the J1a job (r1_input_inventory.JOB_EXTRA j1a
    carries the two snapshot prefixes the scanner cannot see as tables), each pinned prefix is a data: token of the
    row, and a prefix without a pin yet (the snapshot until pin-02) is covered by the job-spec stand-in
    repo:config/r1/jobs/j1a.json (test_every_data_reading_row_fingerprints_the_pinned_data_layer adds the token
    requirement the moment pin-02 pins it)."""
    sync = dict(map(tuple, _job()["data_sync"]))
    for src, dest in ORIGINS_DATA.items():
        assert sync.get(src) == dest, src
    sys.path.insert(0, str(REPO / "tools"))
    import r1_input_inventory as inv                                        # noqa: PLC0415
    snap = {(s, d) for s, d in ORIGINS_DATA.items() if s.startswith("r1/snapshot/")}
    assert snap <= set(inv.JOB_EXTRA["j1a"])
    pins = json.loads((REPO / "config" / "r1" / "input_pins.json").read_text(encoding="utf-8"))["pins"]
    row = _rows()["star_origins_extract"]
    for src in ORIGINS_DATA:
        if src in pins:
            assert f"data:{src}" in row["inputs"], src
        else:
            assert "repo:config/r1/jobs/j1a.json" in row["inputs"], src


def test_n2_env_is_set_by_the_chemmath_and_new_numbers_rows_only():
    rows = _rows()
    for name, row in rows.items():
        cmd = row["cmd"]
        has = "edge_table.py" in cmd or "SAR_PATHS_CONFIG" in cmd
        assert has == (name in N2_ROWS), name
        if name in N2_ROWS:
            et = "$REPO_DIR/pipeline/aws/r1/edge_table.py"
            assert _argv(cmd, et)[0] == "shadow" and _flag(cmd, et, "--target") == TABLE_11, name
            assert _flag(cmd, et, "--out") == "$WORK/edge_table", name                # one shared shadow
            assert _flag(cmd, et, "--base-paths") == "$REPO_DIR/config/r1/paths_aws.yaml", name
            assert "repo:pipeline/aws/r1/edge_table.py" in row["inputs"], name
            assert cmd.index("edge_table.py") < cmd.index("export SAR_PATHS_CONFIG"), name
            body = cmd[cmd.index("export SAR_PATHS_CONFIG"):]
            assert '"$PY" "$' in body, name                                          # the M process runs after it
    nn = rows["new_numbers"]["cmd"]
    ln = "$REPO_DIR/analysis/paper/ledger_new_2026_10.py"
    assert _flag(nn, ln, "--frames") == "$WORK/prod/frames" and _flag(nn, ln, "--events-dir") == "$WORK/prod/events"
    assert _flag(nn, ln, "--out") == "$STAGE_OUT/data_numbers_new_2026-10.json"


def test_the_shadow_paths_file_is_exported_only_when_it_exists(tmp_path):
    work = tmp_path / "work"
    for good in (True, False):
        repo = tmp_path / f"repo_{good}"
        _fake(repo / "pipeline" / "aws" / "r1" / "edge_table.py",
              f"p = pathlib.Path(os.environ['WORK']) / 'edge_table' / 'paths_edge_table.yaml'\n"
              f"p.parent.mkdir(parents=True, exist_ok=True)\n"
              f"{'p.write_text(chr(115))' if good else 'pass'}\nprint('building'); print(p)\n")
        _fake(work / "chemmath_m.py", "pathlib.Path(sys.argv[sys.argv.index('--out') + 1], 'env.txt')"
                                      ".write_text(os.environ.get('SAR_PATHS_CONFIG', ''))\n")
        (work / "edge_table").mkdir(parents=True, exist_ok=True)
        for p in (work / "edge_table").iterdir():
            p.unlink()
        r, out = _bash(_rows()["frames_chemmath_m"]["cmd"], repo=repo, work=work, stage=f"frames_chemmath_m_{good}")
        if good:
            assert r.returncode == 0, r.stderr[-800:]
            assert (out / "env.txt").read_text() == str(work / "edge_table" / "paths_edge_table.yaml")
        else:
            assert r.returncode != 0 and not (out / "env.txt").exists()


def test_patch_assemble_takes_its_tags_from_config_m(tmp_path):
    rec = ("a = sys.argv[1:]; out = pathlib.Path(a[a.index('--out') + 1]); out.mkdir(parents=True, exist_ok=True)\n"
           "(out / 'argv.json').write_text(json.dumps(a))\n")
    for tags, ok in (([], True), (["fetch-01", "fetch-02"], True), (["Bad Tag"], False), (None, False)):
        repo, work = tmp_path / f"r{len(tags or [])}{ok}", tmp_path / f"w{len(tags or [])}{ok}"
        _fake(work / "patch_assemble.py", rec)
        cfg = {"schema": "sar.r1.run_config.v1", "sections": {"patch": {"tags": tags}} if tags is not None else {}}
        (repo / "config" / "r1").mkdir(parents=True)
        (repo / "config" / "r1" / "M.json").write_text(json.dumps(cfg))
        r, out = _bash(_rows()["patch_assemble"]["cmd"], repo=repo, work=work, stage="patch_assemble")
        if not ok:
            assert r.returncode != 0 and not (out / "argv.json").exists(), tags
            continue
        assert r.returncode == 0, r.stderr[-800:]
        a = json.loads((out / "argv.json").read_text())
        raws = [a[i + 1] for i, x in enumerate(a) if x == "--raw"]
        mans = [a[i + 1] for i, x in enumerate(a) if x == "--manifest"]
        assert raws == [f"/work/patch_raw/{t}" for t in tags]
        assert mans == [f"{repo}/data/cal2026-10r1/aws/uploads/patch_raw_{t}.json" for t in tags]
        kp = [a[i + 1] for i, x in enumerate(a) if x == "--known-patches"]
        assert kp == ["/data/legacy/thesis/v2_output/econ_final_2026-08-13/patch/works_by_author.jsonl",
                      f"{repo}/data/cal2026-10/patch_supplement_2026-10/works_by_author_supplement_2026-10.jsonl"]
        assert a[a.index("--out") + 1] == str(out)


# ---- cells, the M estimates dir, promotion ---------------------------------------------------------------------
def test_cells_never_read_october_golds_and_evcl_reads_its_main_stage():
    rows, names = _rows(), ORDER
    cell_rows = {n: r for n, r in rows.items() if r.get("script") == "pipeline/aws/r1/run_cells.py"}
    assert set(cell_rows) == {"cells_rmac", "cells_rcloud", "cells_rmac_evcl", "cells_rcloud_evcl"}
    for name, row in cell_rows.items():
        cmd, s = row["cmd"], "$WORK/run_cells.py"
        assert "analysis/expected" not in cmd and "--compare" not in cmd and REF not in cmd, name
        assert _flag(cmd, s, "--frames") == "$WORK/prod/frames" and "stage:frames" in row["inputs"], name
        stack = _flag(cmd, s, "--stack")
        if name.endswith("_evcl"):
            main = name[:-len("_evcl")]
            assert stack == _flag(rows[main]["cmd"], s, "--stack"), name
            assert _flag(cmd, s, "--cells") == "$REPO_DIR/config/r1/cells/M_evcl.tsv", name
            assert _flag(cmd, s, "--gold-dir") == f"$WORK/prod/{main}/estimates", name
            assert main in row["needs"] and f"stage:{main}" in row["inputs"], name
            assert names.index(main) < names.index(name)
        else:
            assert _flag(cmd, s, "--cells") == "$REPO_DIR/config/r1/cells/M.tsv", name
            assert _flag(cmd, s, "--gold-dir") == "$STAGE_OUT", name           # M.tsv refs are all '-'
        assert f"env:{stack}" in row["inputs"] and stack in name, name
    assert names.index("mem_probe") < names.index("cells_rmac")                 # 3k: after frames, before the cells
    mp = rows["mem_probe"]["cmd"]
    assert _flag(mp, "$WORK/mem_probe.py", "--frames") == "$WORK/prod/frames"
    assert _flag(mp, "$WORK/mem_probe.py", "--stack") == "rcloud" and _flag(mp, "$WORK/mem_probe.py", "--threads") == "4"


def _cells(tsv):
    with open(CELLS / tsv, encoding="utf-8", newline="") as fh:
        return [r for r in csv.DictReader(fh, delimiter="\t")]


def _toy_estimates(tmp_path, *, drop=None, extra=None, evcl_value="MATCH", evcl_key=True, dup=False):
    repo, work = tmp_path / "repo", tmp_path / "work"
    (repo / "config" / "r1" / "cells").mkdir(parents=True)
    for t in ("M.tsv", "M_evcl.tsv"):
        (repo / "config" / "r1" / "cells" / t).write_bytes((CELLS / t).read_bytes())
    for tsv, suffix in (("M.tsv", ""), ("M_evcl.tsv", "_evcl")):
        for r in _cells(tsv):
            if r["out_name"] == drop:
                continue
            d = work / "prod" / f"cells_{r['stack']}{suffix}" / "estimates"
            d.mkdir(parents=True, exist_ok=True)
            body = {"label": r["label"], "ate": 0.1}
            if suffix and evcl_key:
                body["point_estimate_check"] = ({"union": "MATCH", "network": evcl_value} if r["label"].startswith("P1")
                                                else evcl_value)
            (d / r["out_name"]).write_text(json.dumps(body))
    for s in ("cells_rmac", "cells_rcloud", "cells_rmac_evcl", "cells_rcloud_evcl"):
        (work / "prod" / s / "estimates").mkdir(parents=True, exist_ok=True)
    if extra:
        (work / "prod" / "cells_rmac" / "estimates" / extra).write_text("{}")
    if dup:
        name = _cells("M.tsv")[0]["out_name"]
        (work / "prod" / "cells_rcloud" / "estimates" / name).write_text("{}")
    return repo, work


def test_estimates_m_stage_accepts_exactly_the_m_cells(tmp_path):
    row = _rows()["estimates_m"]
    assert row["outputs"] == ["work:prod/estimates_M"] and "script" not in row
    assert set(row["needs"]) == {"cells_rmac", "cells_rcloud", "cells_rmac_evcl", "cells_rcloud_evcl"}
    names = sorted(r["out_name"] for t in ("M.tsv", "M_evcl.tsv") for r in _cells(t))
    assert len(names) == len(set(names)) == 27
    repo, work = _toy_estimates(tmp_path / "ok")
    r, _ = _bash(row["cmd"], repo=repo, work=work, stage="estimates_m")
    assert r.returncode == 0, r.stderr[-800:]
    got = work / "prod" / "estimates_M"
    assert sorted(p.name for p in got.iterdir()) == names                       # flat, exactly the 27, nothing else
    rep = json.loads((work / "prod" / "estimates_m" / "report_estimates_m.json").read_text())
    assert rep["result"] == "OK" and rep["n_cells"] == 27
    bad = {"missing": dict(drop=_cells("M.tsv")[3]["out_name"]), "extra": dict(extra="P9_extra.json"),
           "mismatch": dict(evcl_value="MISMATCH ate 0.1 vs 0.2"), "no_check": dict(evcl_key=False),
           "duplicate": dict(dup=True)}
    for case, kw in bad.items():
        repo, work = _toy_estimates(tmp_path / case, **kw)
        r, _ = _bash(row["cmd"], repo=repo, work=work, stage="estimates_m")
        assert r.returncode != 0, case
        assert not (work / "prod" / "estimates_M").exists() or not any((work / "prod" / "estimates_M").iterdir()), case
        stop = json.loads((work / "prod" / "estimates_m" / "stop_report_estimates_m.json").read_text())
        assert stop["result"] == "STOP" and stop["code"], case


def test_promote_packages_the_m_estimates_and_frames():
    row = _rows()["promote"]
    cmd, p = row["cmd"], "$WORK/promote_r1.py"
    toks = _tokens(cmd)
    subs = [toks[i + 1] for i, t in enumerate(toks[:-1]) if t == p]
    assert subs == ["run", "check"]
    for sub_cmd in cmd.split(" && "):
        assert _flag(sub_cmd, p, "--frames") == "$WORK/prod/frames"
        assert _flag(sub_cmd, p, "--estimates") == "$WORK/prod/estimates_M"
        assert _flag(sub_cmd, p, "--cells", 2) == ["$REPO_DIR/config/r1/cells/M.tsv", "$REPO_DIR/config/r1/cells/M_evcl.tsv"]
        assert _flag(sub_cmd, p, "--out") == "$STAGE_OUT"
    assert set(row["needs"]) == {"frames", "estimates_m"} and row["outputs"] == ["work:prod/promote"]


# ---- the job spec ------------------------------------------------------------------------------------------------
def test_job_runs_config_m_after_a_passed_j0():
    job, rows = _job(), _rows()
    assert job["env"]["SAR_R1_CONFIG"] == "$REPO_DIR/config/r1/M.json"
    assert job["env"]["PYTHONDONTWRITEBYTECODE"] == "1" and job["env"]["PYTHONHASHSEED"] == "0"
    assert job["env"]["SAR_PATHS_CONFIG"] == "$REPO_DIR/config/r1/paths_aws.yaml"      # econ rows: the 07-05 table
    assert "SAR_SSD_ROOT" not in job["env"]                        # edge_table refuses it; rank rows set it inline
    assert job["required_dests"] == ["/work/j0/"]
    assert job["copy_from_tip"] == [["pipeline/aws/r1/run_stages.py", "/work/run_stages.py"]]
    assert job["stages"] == "config/r1/stages/j1a.json" and job["hard_min"] == 600
    assert set(job["env_layers"]) == {"py", "rmac", "rcloud"}
    assert sum(r["est_min"] for r in rows.values()) <= job["est_min"] < job["hard_min"]
    assert all(r.get("owner") != "J0-MEAS.3a" for r in rows.values())
    for name, row in rows.items():                                # no departure (F20) row: out of scope (2026-10-15)
        assert "depart" not in name and "departure" not in row["cmd"], name


# ---- W2-INT: the J0 review #4 and #5 fixes carried to J1a ------------------------------------------------------
#: the rows whose code reads the synced /data trees (paths through config/r1/paths_aws.yaml, SAR_SSD_ROOT or a /data
#: path), as J0's chain rows do. rank_requests and rank_gate read the REF4 copies under /data/ref/r1; until pin-02
#: pinned them the repo:config/r1/jobs/j1a.json stand-in covered those two, and W3-MPIN swapped it for the tokens.
DATA_ROWS = ("rank_requests", "rank_m", "rank_gate", "calls", "patch_assemble", "frames_econ920", "frames_chemmath_m",
             "afar_m", "frames", "new_numbers", "star_origins_extract")
JOB_SPEC = "repo:config/r1/jobs/j1a.json"


def test_every_j1a_prefix_is_pinned_and_the_job_spec_stand_in_is_gone():
    """W3-MPIN after pin-02: every data_sync prefix of J1a has a pin (J1a's verify_inputs row fails otherwise, and
    rank_requests / rank_gate fingerprint the REF4 copies through them), so the job-spec stand-in for unpinned
    prefixes is gone; only verify_inputs, which reads the job spec itself (--job-spec), still names it."""
    pins = json.loads((REPO / "config" / "r1" / "input_pins.json").read_text(encoding="utf-8"))["pins"]
    assert [src for src, _dest in _job()["data_sync"] if src not in pins] == []
    rows = _rows()
    assert {n for n, r in rows.items() if JOB_SPEC in r["inputs"]} == {"verify_inputs"}
    assert '--job-spec "$REPO_DIR/config/r1/jobs/j1a.json"' in rows["verify_inputs"]["cmd"]


def _tracked(path):
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "--", path], capture_output=True, text=True, check=True)
    return bool(out.stdout.strip())


def test_every_data_reading_row_fingerprints_the_pinned_data_layer():
    """J0 review #4, carried to J1a exactly as bc077d9 did for j0.json: a resumed J1a must not restore products
    built from an older data layer. Each data-reading row carries one data:<prefix> token per PINNED data_sync
    prefix of config/r1/jobs/j1a.json (a token for a prefix without a pin would stop fingerprint() before pin-02);
    every other row carries none, and re-pinning any one prefix changes exactly the data rows' fingerprints."""
    rows = _rows()
    pins = json.loads((REPO / "config" / "r1" / "input_pins.json").read_text(encoding="utf-8"))
    prefixes = sorted(src for src, _dest in _job()["data_sync"] if src in pins["pins"])
    assert len(prefixes) >= 8
    for name, row in rows.items():
        data = sorted(_repo_tokens(row["inputs"], "data"))
        assert data == (prefixes if name in DATA_ROWS else []), name
    env_pins = json.loads((REPO / "config" / "r1" / "env_pins.json").read_text(encoding="utf-8"))
    head = rs.git(REPO, "rev-parse", "HEAD")
    done = {n: {"outputs_digest": "0" * 64} for n in rows}
    # a repo: input not tracked at HEAD would not resolve; none is left since the rosters were committed (d124ed7)
    rows = {n: dict(r, inputs=[t for t in r["inputs"] if not (t.startswith("repo:") and not _tracked(t[5:]))])
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
    """J0 review #5 made `sandbox.py check --table` required (aae00b5): without it J1a's last row exits at once."""
    cmd = _rows()["sandbox_check"]["cmd"]
    toks = shlex.split(cmd)
    assert toks[toks.index("--table") + 1] == "$REPO_DIR/config/r1/stages/j1a.json"
    span = sb.audited_span(J1A)
    assert span and span[0] == "gate1_link" and "sandbox" not in span and "sandbox_check" not in span


def test_frames_econ920_fingerprints_the_fnfix_graph_dependencies():
    """M delta review #2: econ920_m.fnfix_graph imports run_cal_frames_chemmath.rebase_recorded_roots, which
    reads config/paths.yaml; both must be stage inputs so a change to either rebuilds the economics frames."""
    rows = {s["name"]: s for s in json.loads(J1A.read_text(encoding="utf-8"))["stages"]}
    for dep in ("repo:pipeline/frames/cal2026-10/run_cal_frames_chemmath.py", "repo:config/paths.yaml"):
        assert dep in rows["frames_econ920"]["inputs"], dep


def test_j1a_reads_j0s_summary_so_its_j0_pull_must_be_j0s_out_files():
    """j1a-02: a pull of J0's stages/ into /work/j0/ has no summary.json, and gate1_link failed on the instance.
    The job spec names /work/j0/ an upstream destination; the kit refuses any other kind of pull into it."""
    import r1kit                                                         # noqa: PLC0415
    job = json.loads((REPO / "config" / "r1" / "jobs" / "j1a.json").read_text(encoding="utf-8"))
    assert job["upstream_dests"] == ["/work/j0/"]
    env = {"SAR_S3_BUCKET": "fake-bucket", "AWS_REGION": "us-east-1"}
    with pytest.raises(r1kit.KitError, match="out/files"):
        r1kit.launch("j1a", "j1a-99", "HEAD", env=env, dry_run=True, now=1_800_000_000,
                     extra_pulls=[("r1/runs/j0-06/stages/", "/work/j0/")])


def test_the_reads_j1a_19s_sandbox_check_listed_are_allowlisted_for_m():
    """j1a-19 ran every stage and stopped at sandbox_check (G_READ_FAIL, 6 reads). Each read is legitimate: the
    chem/maths build compares the M event tables' header line with the 08-28 tables (chemmath_m.check_tables,
    also in J1b's no-centre rebuild); the econ build's V3-NET imports run_cal_frames_chemmath, which imports
    cal_accounting; restake_r1 m checks the 187 against October's candidate rows and copies the run-2 verdicts
    header. The same check sandbox_check runs must admit all six."""
    rows = [r for r in sb.load_allowlist(ALLOW) if r.applies("M")]
    reads = [("frames_chemmath_m", f"data/cal2026-08-28/events_{f}_cal.csv") for f in ("chemistry", "econ", "math_stats")]
    reads += [("rob_frames", f"data/cal2026-08-28/events_{f}_cal.csv") for f in ("chemistry", "econ", "math_stats")]
    reads += [("frames_econ920", "pipeline/stars/caliber_2026-08-28/cal_accounting.py"),
              ("rank_tables", "data/cal2026-10/_invalid_run2/candidates_2026-10.csv"),
              ("rank_tables", "data/cal2026-10/_invalid_run2/verdicts_2026-10.csv")]
    refused = [(s, p) for s, p in reads if not any(r.allows(s, p) for r in rows)]
    assert refused == []
    # still refused: any other run-2 file, and the 08-28 event tables for a stage that does not check headers
    assert not any(r.allows("rank_tables", "data/cal2026-10/_invalid_run2/events_econ_cal2026-10.csv") for r in rows)
    assert not any(r.allows("frames_econ920", "data/cal2026-08-28/events_econ_cal.csv") for r in rows)



def test_the_econ_build_s_cal_accounting_read_is_m_only():
    """Codex delta-3 #8: econ920_m's V3-NET import is M; B0's frozen economics chain does not read the module."""
    allow = sb.load_allowlist(ALLOW)
    p, st = "pipeline/stars/caliber_2026-08-28/cal_accounting.py", "frames_econ920"
    assert any(r.applies("M") and r.allows(st, p) for r in allow)
    assert not any(r.applies("B0") and r.allows(st, p) for r in allow)
