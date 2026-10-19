# -*- coding: utf-8 -*-
"""config/r1/stages/j0.json + config/r1/chain.json (F23/F2/F30): the J0 table rebuilds October step by step
inside the sandbox and ends with gate 1; config/r1/stages/jp.json's compare row records a DIFF instead of
failing JP. Reads committed config files; the --help probes run each script's argument parser only."""
from __future__ import annotations

import csv
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import run_stages as rs     # noqa: E402

J0 = REPO / "config" / "r1" / "stages" / "j0.json"
JP = REPO / "config" / "r1" / "stages" / "jp.json"
CHAIN = REPO / "config" / "r1" / "chain.json"
REF = "/work/ref/october"
CHAIN_STEPS = ["restake_econ11_aug", "restake_econ11_aug_all", "write_events", "frames_econ920", "frames_chemmath",
               "afar", "p3_variants", "frames"]
ORDER = ["verify_inputs", "relink", "config", "sandbox", "restake_econ11_aug", "restake_econ11_aug_all",
         "write_events", "frames_econ920", "pairs_pin", "frames_chemmath", "afar", "p3_variants", "frames",
         "cells_rmac", "cells_rcloud", "sandbox_check", "gate1"]
SHELL_OPS = {">", ">>", "<", "&&", "||", ";", "|", "2>&1"}


def _table(p=J0):
    return rs.load_table(p)


def _rows(p=J0):
    return {s["name"]: s for s in _table(p)["stages"]}


def _chain():
    return json.loads(CHAIN.read_text(encoding="utf-8"))


def _steps():
    return {s["name"]: s for s in _chain()["steps"]}


def _repo_tokens(toks, kind="repo"):
    return [t.split(":", 1)[1] for t in toks if t.startswith(kind + ":")]


def test_rows_in_order_and_the_table_is_complete_after_f30():
    t = _table()
    assert [s["name"] for s in t["stages"]] == ORDER
    assert t["complete"] is True                        # F30 flipped it after the R7 review + AWS tests (6b6d434)
    assert [s["name"] for s in _chain()["steps"]] == CHAIN_STEPS
    assert _chain()["schema"] == "sar.r1.chain.v1"


def test_every_chain_step_has_a_row_whose_outputs_equal_its_writes():
    rows, steps = _rows(), _steps()
    for name, step in steps.items():
        row = rows[name]
        assert row["script"] == "pipeline/aws/r1/run_config.py", name
        argv = shlex.split(row["cmd"])
        assert argv[argv.index("--step") + 1] == name
        assert argv[argv.index("--config") + 1] == "$REPO_DIR/config/r1/B0.json"
        assert argv[argv.index("--chain") + 1] == "$REPO_DIR/config/r1/chain.json"
        assert sorted(_repo_tokens(row["outputs"])) == sorted(step["writes"]), name
        assert set(row["outputs"]) - {f"repo:{w}" for w in step["writes"]} == {f"work:prod/{name}"}, name
    run_config_rows = [n for n, r in rows.items() if r.get("script") == "pipeline/aws/r1/run_config.py"]
    assert run_config_rows == CHAIN_STEPS
    assert steps["frames"]["post"] == "copy_frames" and steps["frames"]["frames_dir"] == "data/cal2026-10/frames"
    assert "work:prod/frames" in rows["frames"]["outputs"]          # ruling R10: the cells read /work/prod/frames


def test_sandbox_precedes_every_chain_row_and_sandbox_check_and_gate1_are_last():
    names = [s["name"] for s in _table()["stages"]]
    assert names.index("config") < names.index("sandbox") < min(names.index(s) for s in CHAIN_STEPS)
    assert names[-2:] == ["sandbox_check", "gate1"]
    rows = _rows()
    for name in ("verify_inputs", "relink", "config", "sandbox", "sandbox_check", "gate1"):
        assert rows[name].get("resume") == "always", name
    sb = shlex.split(rows["sandbox"]["cmd"])
    assert sb[2] == "purge" and sb[sb.index("--config") + 1] == "B0" and sb[sb.index("--ref") + 1] == REF
    assert sb[sb.index("--table") + 1] == "$REPO_DIR/config/r1/stages/j0.json"
    ck = shlex.split(rows["sandbox_check"]["cmd"])
    assert ck[2] == "check" and [ck[i + 1] for i, x in enumerate(ck) if x == "--reads"] == ["/work/reads", "/work/resume/_reads"]
    cf = shlex.split(rows["config"]["cmd"])
    assert cf[2] == "check" and cf[cf.index("--config") + 1] == "$REPO_DIR/config/r1/B0.json"


def test_gold_reads_come_from_the_october_reference_copy():
    rows = _rows()
    pp = shlex.split(rows["pairs_pin"]["cmd"])
    assert pp[pp.index("--report") + 1].startswith(REF + "/")
    assert pp[pp.index("--report") + 1] == f"{REF}/data/cal2026-10/frames_econ/build_report_econ920_2026-10.json"
    assert rows["pairs_pin"]["needs"] == ["frames_econ920"]
    for name in ("cells_rmac", "cells_rcloud"):
        a = shlex.split(rows[name]["cmd"])
        assert a[a.index("--gold-dir") + 1] == f"{REF}/analysis/expected"
        assert a[a.index("--frames") + 1] == "$WORK/prod/frames"
        assert a[a.index("--cells") + 1] == "$REPO_DIR/config/r1/cells/oct29.tsv"   # all 29, old79/new37 included (C10)
        assert "stage:frames" in rows[name]["inputs"]
    g = shlex.split(rows["gate1"]["cmd"])
    assert g[2] == "gate1" and g[g.index("--ref") + 1] == REF and g[g.index("--jp") + 1] == "/work/jp"


def test_fingerprint_inputs_are_precise():
    rows, chain = _rows(), _chain()
    for name, row in rows.items():
        assert "stage:config" not in row["inputs"] and "stage:sandbox" not in row["inputs"], name
        for rel in _repo_tokens(row["inputs"]):
            p = REPO / rel
            assert p.exists(), (name, rel)
            assert not (rel.startswith("data/") and p.is_dir()), (name, rel)    # never a broad data dir
        if row.get("script"):
            assert (REPO / row["script"]).is_file(), name
    for name in CHAIN_STEPS:
        ins = rows[name]["inputs"]
        for common in ("repo:config/r1/chain.json", "repo:config/r1/B0.json", "repo:config/r1/paths_aws.yaml", "env:py"):
            assert common in ins, (name, common)
    for name in ("frames_econ920", "frames_chemmath"):                  # the in-chain R controls (Mac stack)
        assert "env:rmac" in rows[name]["inputs"], name


def test_every_resumable_data_reader_fingerprints_the_pinned_data_layer():
    """J0 review #4 (accepted in part, 2026-10-16). Resume stays (N13/R12), but a resumed J0 restored the
    products of an older data layer: no stage carried a data: token, so after a re-upload and repin the builders'
    fingerprints were unchanged. Every chain step resolves its paths through config/r1/paths_aws.yaml (ssd_root
    and the legacy roots on the synced /data), so each carries one data:<prefix> token per pinned data_sync
    prefix of config/r1/jobs/j0.json. pairs_pin and the cells read only earlier stages' products, which their
    stage: tokens already pin; a resumable stage with no stage: input must carry the data tokens too."""
    rows = _rows()
    job = json.loads((REPO / "config" / "r1" / "jobs" / "j0.json").read_text(encoding="utf-8"))
    pins = json.loads((REPO / "config" / "r1" / "input_pins.json").read_text(encoding="utf-8"))
    prefixes = sorted(src for src, _dest in job["data_sync"])
    assert len(prefixes) == 8 and set(prefixes) <= set(pins["pins"])
    for name, row in rows.items():
        if row.get("resume") == "always":
            continue
        data = sorted(t.split(":", 1)[1] for t in row["inputs"] if t.startswith("data:"))
        if name in CHAIN_STEPS or not any(t.startswith("stage:") for t in row["inputs"]):
            assert data == prefixes, name
        else:
            assert data == [], name
    # behaviour: a re-pinned prefix changes the fingerprint of exactly the data readers (rs.fingerprint, R12)
    env_pins = json.loads((REPO / "config" / "r1" / "env_pins.json").read_text(encoding="utf-8"))
    head = rs.git(REPO, "rev-parse", "HEAD")
    done = {n: {"outputs_digest": "0" * 64} for n in rows}
    resumable = {n: r for n, r in rows.items() if r.get("resume") != "always"}

    def fps(p):
        return {n: rs.fingerprint(r, repo=REPO, commit=head, pins=p, env_pins=env_pins, done=done)
                for n, r in resumable.items()}

    before = fps(pins)
    for prefix in prefixes:
        moved = json.loads(json.dumps(pins))
        moved["pins"][prefix]["manifest_sha256"] = "f" * 64
        after = fps(moved)
        assert {n for n in resumable if after[n] != before[n]} == set(CHAIN_STEPS), prefix


def test_b0_chain_paths_cover_every_repo_input_of_the_chain_rows():
    rows, chain = _rows(), _chain()
    paths = chain["b0_chain_paths"]
    assert paths == sorted(set(paths))
    for p in paths:
        assert (REPO / p).exists(), p
    covered = set(paths)
    for name in CHAIN_STEPS:
        for rel in _repo_tokens(rows[name]["inputs"]):
            assert rel in covered, (name, rel)
    assert "pipeline/aws/r1/run_config.py" in covered
    # robustness code frozen before J0 is only what the chain runs (ruling on analysis/robustness)
    rob = {p for p in paths if p.startswith("analysis/robustness/")}
    assert rob <= {"analysis/robustness/p3_afar_cuts/build_afar_cut.py", "analysis/robustness/p3_afar/build_afar.py",
                   "analysis/robustness/threshold_p05/build_p3_full_variants.py",
                   "analysis/robustness/threshold_p05/filter_frames.py"}


def test_chain_follows_octobers_recorded_runs():
    steps = _steps()
    every_argv = [" ".join(a) for s in steps.values() for a in s["argv"]]
    for not_a_step in ("run_caliber.py", "fetch_star_id_supplement.py", "run_cal_estimates.py", "afar_event_map.py",
                       "ledger_new_2026_10.py", "--tags"):
        assert not any(not_a_step in a for a in every_argv), not_a_step
    assert steps["restake_econ11_aug"]["env"]["SAR_ECON_CONVENTION"] == "aug"
    assert steps["restake_econ11_aug"]["env"].get("SAR_ECON_ALL", "0") == "0"
    assert steps["restake_econ11_aug_all"]["env"] == {**steps["restake_econ11_aug"]["env"], "SAR_ECON_ALL": "1"}
    assert steps["write_events"]["argv"] == [["{py}", "pipeline/stars/caliber_2026-10/write_events.py"]]
    e = steps["frames_econ920"]["argv"][-1]
    assert e[1] == "pipeline/frames/cal2026-10/econ920/run_econ920.py" and "--execute" in e and "--override-gdose-gate" in e
    assert e[e.index("--controls-report") + 1] == "{out}/controls_report_econ920.json"
    rep = json.loads((REPO / "data/cal2026-10/frames_econ/build_report_econ920_2026-10.json").read_text(encoding="utf-8"))
    assert e[e.index("--patch-supplement") + 1] == rep["october"]["shadow"]["patch_supplement"]["extra"]
    # afar: the four economics inputs October hand-staged, then run_cal_afar on them
    rep = json.loads((REPO / "data/cal2026-10/frames_afar/afar_run_report.json").read_text(encoding="utf-8"))
    staged = {pathlib.Path(v["from"]).name: v["sha256"] for k, v in rep["inputs"].items() if k.startswith("econ_fnfix")}
    cps = {pathlib.PurePosixPath(a[2]).name: a[1] for a in steps["afar"]["argv"] if a[0] == "cp"}
    assert set(cps) == set(staged) == {"pairs_unified.csv", "p1_frame_econ.csv", "p2_becoming_econ.csv", "relationships.csv"}
    a = steps["afar"]["argv"][-1]
    assert a[a.index("--econ-dir") + 1] == "{tmp}/afar_econ" and a[a.index("--out") + 1] == "data/cal2026-10/frames_afar"
    # p3_variants: one invocation per field with the inputs its October report records
    inv = steps["p3_variants"]["argv"]
    assert [x[x.index("--field") + 1] for x in inv] == ["econ", "chemistry", "math_stats"]
    for x in inv:
        f = x[x.index("--field") + 1]
        r = json.loads((REPO / f"data/cal2026-10/frames_variants/p3_full_variants_report_{f}.json").read_text(encoding="utf-8"))
        assert x[x.index("--pairs") + 1] == r["inputs"]["pairs"] and x[x.index("--frame") + 1] == r["inputs"]["frame"]
    # frames: every source October's assembly report names, and the pin of the run's own econ920 report
    fr = steps["frames"]["argv"][-1]
    asm = json.loads((REPO / "data/cal2026-10/frames/assembly_2026-10.json").read_text(encoding="utf-8"))
    dirs = {fr[i + 1] for i, x in enumerate(fr) if x.endswith("-dir")}
    srcs = {str(pathlib.PurePosixPath(v["source"]).parent) for v in asm["files"].values()} - {"data/frames"}
    assert srcs <= dirs
    assert fr[fr.index("--pairs-econ") + 1] == asm["pairs_unified_econ"]["source"]
    assert fr[fr.index("--pairs-pin") + 1] == "data/cal2026-10/frames_econ/build_report_econ920_2026-10.json#october.pairs_unified"
    assert fr[fr.index("--out") + 1] == "data/cal2026-10/frames"


def _usage(text):
    """The usage paragraph of an argparse help text, and its required flags (outside any [...] or (...))."""
    usage = text.split("\n\n", 1)[0]
    bare = usage
    while True:
        nxt = re.sub(r"\[[^\[\]]*\]|\([^()]*\)", " ", bare)
        if nxt == bare:
            break
        bare = nxt
    return set(re.findall(r"(?<![\w-])--[a-z0-9][a-z0-9-]*", bare))


def _help(script, sub):
    env = dict(os.environ, SAR_HOST="ec2-r1-test", PYTHONDONTWRITEBYTECODE="1")
    env.pop("SAR_OUT_ROOT", None)
    r = subprocess.run([sys.executable, str(REPO / script), *([sub] if sub else []), "--help"], cwd=REPO, env=env,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, (script, sub, r.stderr[-800:])
    return r.stdout


def _invocations():
    """(row or step, script, subcommand, flags) for every python invocation the J0 table and the chain make."""
    out = []
    for name, row in _rows().items():
        script = row.get("script", "")
        if not script.endswith(".py"):
            continue
        toks = shlex.split(row["cmd"])
        i = toks.index(f"$WORK/{pathlib.PurePosixPath(script).name}")
        args = []
        for t in toks[i + 1:]:
            if t in SHELL_OPS:
                break
            args.append(t)
        sub = args[0] if args and not args[0].startswith("-") else None
        out.append((name, script, sub, [a for a in args if a.startswith("--")]))
    for name, step in _steps().items():
        for argv in step["argv"]:
            flags = [a for a in argv[2:] if a.startswith("--")]
            # a flagless October script (restake_econ11.py, write_events.py) has no parser: `--help` would RUN it
            # and write into this checkout, so it is not probed (it has no flag to check either)
            if argv[0] == "{py}" and argv[1].endswith(".py") and flags:
                out.append((name, argv[1], None, flags))
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


def test_no_row_output_covers_a_base_input():
    with open(REPO / "config" / "r1" / "base_inputs.tsv", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    base = [r["path"] for r in rows if r["class"] in ("base", "r1_input")]
    products = {r["path"] for r in rows if r["class"] == "product"}
    assert base and products
    for name, row in _rows().items():
        for out in _repo_tokens(row["outputs"]):
            hit = [b for b in base if b == out or b.startswith(out.rstrip("/") + "/") or out.startswith(b + "/")]
            assert not hit, (name, out, hit[:3])
    for step in _steps().values():                      # a chain write under the roots is a classified product
        for w in step["writes"]:
            if w.startswith(("data/cal2026-10/", "data/frames/", "analysis/expected/")):
                assert w in products or any(p.startswith(w + "/") for p in products), w


def test_jobs_carry_the_config_and_need_the_jp_run():
    j0 = json.loads((REPO / "config" / "r1" / "jobs" / "j0.json").read_text(encoding="utf-8"))
    jp = json.loads((REPO / "config" / "r1" / "jobs" / "jp.json").read_text(encoding="utf-8"))
    assert j0["env"]["PYTHONDONTWRITEBYTECODE"] == "1" and jp["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
    assert j0["env"]["SAR_R1_CONFIG"] == "$REPO_DIR/config/r1/B0.json"
    assert j0["required_dests"] == ["/work/jp/"]
    assert "SAR_R1_CONFIG" not in jp["env"]                             # JP needs no run config (ruling F9)


def _jp_compare(tmp_path, compare_rc, with_estimates=True):
    repo, work = tmp_path / "repo", tmp_path / "work"
    (repo / "tools").mkdir(parents=True)
    (repo / "tools" / "compare_all.py").write_text(
        "import pathlib, sys\npathlib.Path('output').mkdir(exist_ok=True)\n"
        "pathlib.Path('output/compare_report.md').write_text('report\\n')\n"
        f"print('DIFF' if {compare_rc} else 'EQUAL')\nsys.exit({compare_rc})\n")
    for stack in ("cells_rmac", "cells_rcloud"):
        (work / "prod" / stack / "estimates").mkdir(parents=True)
        if with_estimates:
            (work / "prod" / stack / "estimates" / f"{stack}.json").write_text("{}\n")
    out = work / "prod" / "compare"
    cmd = _rows(JP)["compare"]["cmd"]
    env = dict(os.environ, PY=sys.executable, REPO_DIR=str(repo), WORK=str(work), STAGE_OUT=str(out), COMMIT="c" * 40)
    rc = subprocess.run(["bash", "-c", cmd], cwd=work, env=env, capture_output=True, text=True).returncode
    return rc, out


def test_jp_compare_row_exits_0_on_diff_and_records_the_rc(tmp_path):
    rc, out = _jp_compare(tmp_path / "diff", 1)
    assert rc == 0 and (out / "compare_rc.txt").read_text().strip() == "1"
    assert (out / "compare.txt").read_text().strip() == "DIFF"
    rc, out = _jp_compare(tmp_path / "equal", 0)
    assert rc == 0 and (out / "compare_rc.txt").read_text().strip() == "0"
    rc, _ = _jp_compare(tmp_path / "nocells", 0, with_estimates=False)       # a missing cell is still a failure
    assert rc != 0
    assert "work:prod/compare" in _rows(JP)["compare"]["outputs"]
