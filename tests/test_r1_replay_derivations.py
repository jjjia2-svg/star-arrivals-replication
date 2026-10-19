# -*- coding: utf-8 -*-
"""pipeline/aws/r1/replay_derivations.py - the 10-02 heredoc derivation replay (job kind 'recder', plan V3-REC),
on toy histories, toy workflow results and toy recovered payloads. No real data, no network."""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import replay_derivations as rd           # noqa: E402

PROD_LINES = [2348, 2371, 2963, 3354, 3360, 3407, 3522, 3961, 4376, 4558, 4722, 4736, 4980]
TOY_ROWS = [{"key": "econ|t alpha", "Y": 2010}, {"key": "chem|t beta", "Y": 2012}]
TOY_WF = {"taskId": "wtoy", "status": "completed", "result": {"rows": TOY_ROWS}}
#: step 1 dumps the workflow result like T:4376; step 2 writes requests like T:3360 (json.dump indent=0)
BODY_DUMP = ("import sys,json\n"
             "F,K=sys.argv[1:3]\n"
             "t=open(F).read(); o=json.loads(t[t.find('{'):]); o=o.get('result',o)\n"
             "json.dump(o,open(K+'/c/full.json','w'),ensure_ascii=False)\n"
             "print('dumped',len(o['rows']))\n")
BODY_REQ = ("import sys,json\n"
            "K=sys.argv[1]\n"
            "o=json.load(open(K+'/c/full.json')); extra=json.load(open(K+'/in/extra.json'))\n"
            "req=[{'key':r['key']+'|Y'+str(r['Y']),'person':r['key'],'Y':r['Y'],'extra':extra} for r in o['rows']]\n"
            "json.dump(req,open(K+'/rk4in/requests.json','w'),indent=0)\n"
            "for r in req: print(r['key'])\n")
EXTRA = [7, 8]


def _sha(b) -> str:
    return hashlib.sha256(b if isinstance(b, bytes) else b.encode("utf-8")).hexdigest()


def _bash(cmd) -> str:
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash",
                                                                     "input": {"command": cmd}}]}})


def _heredoc(pre, py, args, body, post=""):
    return f"{pre}{py} - {' '.join(chr(34) + '$' + a + chr(34) for a in args)} <<'EOF'\n{body}EOF\n{post}".rstrip("\n")


def _evidence(root, cmds, workflows=None):
    """One single-line slice per recorded command, as recover_rk.history_lines reads them."""
    t = root / "history"
    t.mkdir(parents=True)
    for n, cmd in cmds.items():
        (t / f"T_{n:05d}-{n:05d}.jsonl").write_text(_bash(cmd) + "\n", encoding="utf-8")
    w = root / "workflows"
    w.mkdir()
    for name, obj in (workflows or {}).items():
        (w / name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return root


def _repo(root, bodies, steps, **gates):
    """A toy repo: the reviewed bodies under config/r1/derivations/ and the spec pinning them. `steps` is
    [(line, ((name, ref), ...))]: the spec's argv is the ordered names and args the name -> ref map, the
    shape of config/r1/derivations.json (load_spec refuses a step whose argv names differ from its args)."""
    d = root / "config" / "r1" / "derivations"
    d.mkdir(parents=True)
    for n, body in bodies.items():
        (d / f"T{n:05d}.py").write_bytes(body.encode("utf-8"))
    spec = {"schema": rd.SCHEMA, "mkdirs": gates.pop("mkdirs", []), "stage": gates.pop("stage", []),
            "steps": [{"line": n, "file": f"config/r1/derivations/T{n:05d}.py",
                       "sha256": _sha((d / f"T{n:05d}.py").read_bytes()), "argv": [name for name, _ref in args],
                       "args": dict(args)}
                      for n, args in steps],
            "bytes": gates.pop("bytes", []), "counts": gates.pop("counts", []), "notes": gates.pop("notes", []),
            "named": gates.pop("named", [])}
    assert not gates
    p = root / "config" / "r1" / "derivations.json"
    p.write_text(json.dumps(spec, indent=1) + "\n", encoding="utf-8")
    return p


def _run(tmp_path, spec, *, work=None):
    args = ["--spec", str(spec), "--evidence", str(tmp_path / "ev"), "--recovered", str(tmp_path / "rec"),
            "--repo", str(tmp_path / "repo"), "--legacy", str(tmp_path / "legacy"),
            "--work", str(work or tmp_path / "work"), "--out", str(tmp_path / "out"), "--python", sys.executable]
    rc = rd.main(args)
    out = tmp_path / "out"
    return rc, (out / "RESULT.txt").read_text(encoding="utf-8").strip(), json.loads((out / "summary.json").read_text(encoding="utf-8"))


@pytest.fixture
def on_host(monkeypatch):
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")


def _toy_chain(tmp_path, *, flip=False, drift=False):
    """Two steps (T:101 dump, T:102 requests) with the recorded shell around them, one staged input folder,
    and two byte gates against toy recovered payload copies."""
    cmds = {101: _heredoc("F=/scratch/tasks/wtoy.output; K=/scratch/k; ", "/opt/x/python-env/bin/python3",
                          ["F", "K"], BODY_DUMP, "echo done"),
            102: _heredoc("K=/scratch/k; mkdir -p $K/rk4in && ", '"$PY"', ["K"], BODY_REQ,
                          "cd $K && cp in/drops.csv rk4in/ && tar czf ../payload4.tar.gz rk4in")}
    _evidence(tmp_path / "ev", cmds, {"wf_toy.json": TOY_WF})
    rec = tmp_path / "rec"
    (rec / "rk1" / "payload" / "in").mkdir(parents=True)
    (rec / "rk1" / "payload" / "in" / "extra.json").write_text(json.dumps(EXTRA), encoding="utf-8")
    req = [{"key": r["key"] + "|Y" + str(r["Y"]), "person": r["key"], "Y": r["Y"], "extra": EXTRA} for r in TOY_ROWS]
    want_req = json.dumps(req, indent=0).encode("utf-8")
    if flip:
        want_req = want_req[:-1] + bytes([want_req[-1] ^ 1])
    for run, name, data in (("rk4", "requests.json", want_req),
                            ("rk5", "census_full.json", json.dumps(TOY_WF["result"], ensure_ascii=False).encode("utf-8"))):
        (rec / run / "payload" / "in").mkdir(parents=True)
        (rec / run / "payload" / "in" / name).write_bytes(data)
    (tmp_path / "legacy").mkdir()
    bodies = {101: BODY_DUMP + ("#" if drift else ""), 102: BODY_REQ}
    return _repo(tmp_path / "repo", bodies,
                 [(101, (("F", "evidence:workflows/wf_toy.json"), ("K", "replay:k"))), (102, (("K", "replay:k"),))],
                 mkdirs=["k/c", "k/rk4in"], stage=[["recovered:rk1/payload/in", "k/in"]],
                 bytes=[{"name": "rk4in_requests", "got": "k/rk4in/requests.json", "want": "recovered:rk4/payload/in/requests.json"},
                        {"name": "census_full", "got": "k/c/full.json", "want": "recovered:rk5/payload/in/census_full.json"}])


# ---- lift ----------------------------------------------------------------------------------------------------------

def test_lift_returns_the_python_heredoc_body_and_argv_names():
    cmd = "K=/x; mkdir -p $K/p; /p/python3 - \"$K\" \"$S\" <<'EOF'\nimport sys\nprint(sys.argv[1:])\nEOF\ncp a b"
    assert rd.lift(cmd) == (["K", "S"], "import sys\nprint(sys.argv[1:])\n")
    assert rd.lift("\"$PY\" - \"$K\" <<'EOF'\nx = 1\nEOF") == (["K"], "x = 1\n")
    quoted = ("R=\"/a b/repo\"; L=\"/a b/v2\"; \"$R/setup/.venv/bin/python\" - \"$K\" \"$S\" \"$R\" \"$L\" <<'EOF'\n"
              "a = 'EOF in a line'\nEOF\necho after")
    assert rd.lift(quoted) == (["K", "S", "R", "L"], "a = 'EOF in a line'\n")
    assert rd.lift("python3 - <<'EOF'\nprint(1)\nEOF") == ([], "print(1)\n")


def test_lift_refuses_zero_or_two_python_heredocs():
    with pytest.raises(RuntimeError):
        rd.lift("ls -la; echo nothing here")
    with pytest.raises(RuntimeError):
        rd.lift("cat > x.json <<'EOF'\n{}\nEOF")                      # a heredoc, but not python
    with pytest.raises(RuntimeError):
        rd.lift("python3 - \"$K\" <<'EOF'\nprint(1)\nEOF\n/p/python3 - \"$K\" <<'EOF'\nprint(2)\nEOF")


def test_a_step_whose_argv_names_differ_from_its_args_is_malformed(tmp_path):
    """load_spec takes argv as the ordered names and args as name -> ref (t-0023: the toy helper once wrote
    (name, ref) pairs into argv, and every replay test stopped here instead of where it meant to)."""
    spec = _repo(tmp_path / "repo", {701: "x = 1\n"}, [(701, (("K", "replay:k"),))])
    assert [(s["argv"], s["args"]) for s in rd.load_spec(spec)["steps"]] == [(["K"], {"K": "replay:k"})]
    good = json.loads(spec.read_text(encoding="utf-8"))
    for argv in ([["K", "replay:k"]], ["F"], ["K", "K2"]):
        s = json.loads(json.dumps(good))
        s["steps"][0]["argv"] = argv
        spec.write_text(json.dumps(s), encoding="utf-8")
        with pytest.raises(SystemExit, match="step T00701 is malformed"):
            rd.load_spec(spec)


def test_a_lift_that_differs_from_the_reviewed_copy_stops(tmp_path, on_host):
    spec = _toy_chain(tmp_path, drift=True)
    rc, result, summary = _run(tmp_path, spec)
    assert rc == 1 and result == "LIFT_DRIFT" and summary["result"] == "LIFT_DRIFT"
    assert summary["fail_codes"] == ["lift/T00101"]
    assert summary["steps"] == {"T00101": "not_run", "T00102": "not_run"}
    assert not (tmp_path / "work" / "steps").exists() or not any((tmp_path / "work" / "steps").iterdir())
    assert not (tmp_path / "work" / "root" / "k" / "c" / "full.json").exists()
    assert not list((tmp_path / "out" / "logs").glob("*.log"))


def test_a_pin_or_argv_mismatch_is_also_lift_drift(tmp_path, on_host):
    spec = _toy_chain(tmp_path)
    s = json.loads(spec.read_text(encoding="utf-8"))
    s["steps"][1]["sha256"] = "0" * 64
    s["steps"][0]["argv"], s["steps"][0]["args"] = ["K", "F"], {"K": "replay:k", "F": "evidence:workflows/wf_toy.json"}
    spec.write_text(json.dumps(s), encoding="utf-8")
    rc, result, summary = _run(tmp_path, spec)
    assert result == "LIFT_DRIFT" and summary["fail_codes"] == ["lift/T00101", "lift/T00102"]


# ---- replay and gates ------------------------------------------------------------------------------------------------

def test_replay_on_a_toy_history_reproduces_the_payload_copy(tmp_path, on_host):
    spec = _toy_chain(tmp_path)
    rc, result, summary = _run(tmp_path, spec)
    assert (rc, result) == (0, "OK"), (tmp_path / "out" / "checks.json").read_text()
    assert summary["bytes"] == {"rk4in_requests": "ok", "census_full": "ok"}
    assert summary["steps"] == {"T00101": "ok", "T00102": "ok"}
    checks = json.loads((tmp_path / "out" / "checks.json").read_text(encoding="utf-8"))
    assert checks["fails"] == []
    want = (tmp_path / "rec" / "rk4" / "payload" / "in" / "requests.json").read_bytes()
    derived = tmp_path / "out" / "derived"
    assert (derived / "k" / "rk4in" / "requests.json").read_bytes() == want
    assert summary["shas"]["k/rk4in/requests.json"] == _sha(want)
    assert not (derived / "k" / "in").exists()                        # staged inputs are not derived output
    man = (tmp_path / "out" / "derived_manifest.tsv").read_text(encoding="utf-8").splitlines()
    assert man[0] == "member\tbytes\tsha256" and len(man) - 1 == summary["derived_files"] == 2
    assert summary["lift_sha256"]["T00102"] == _sha(BODY_REQ)
    # the recovered payload is read, never written
    assert (tmp_path / "rec" / "rk1" / "payload" / "in" / "extra.json").read_text() == json.dumps(EXTRA)


def test_a_payload_copy_that_differs_stops(tmp_path, on_host):
    spec = _toy_chain(tmp_path, flip=True)
    rc, result, summary = _run(tmp_path, spec)
    assert rc == 1 and result == "DERIVE_FAIL"
    assert summary["fail_codes"] == ["bytes/rk4in_requests"]
    assert summary["bytes"] == {"rk4in_requests": "differs", "census_full": "ok"}


def test_a_step_that_exits_nonzero_stops_the_chain(tmp_path, on_host):
    cmds = {201: _heredoc("K=/s/k; ", "python3", ["K"], "import sys\nopen(sys.argv[1]+'/a','w').write('1')\nsys.exit(3)\n"),
            202: _heredoc("K=/s/k; ", "python3", ["K"], "import sys\nopen(sys.argv[1]+'/b','w').write('2')\n")}
    _evidence(tmp_path / "ev", cmds)
    spec = _repo(tmp_path / "repo", {n: c.split("<<'EOF'\n", 1)[1].rsplit("EOF", 1)[0] for n, c in cmds.items()},
                 [(201, (("K", "replay:k"),)), (202, (("K", "replay:k"),))], mkdirs=["k"])
    rc, result, summary = _run(tmp_path, spec)
    assert rc == 1 and result == "DERIVE_FAIL" and summary["fail_codes"] == ["step/T00201"]
    assert summary["steps"] == {"T00201": "fail", "T00202": "not_run"}
    assert not (tmp_path / "work" / "root" / "k" / "b").exists()


def _census_case(tmp_path, n_top, n_ev):
    body = ("import sys,csv\n"
            "K=sys.argv[1]\n"
            "w=csv.writer(open(K+'/census/census_ranked.csv','w',newline=''))\n"
            "w.writerow(['name','top10','is_event','decided_before'])\n"
            f"for i in range({n_top}): w.writerow(['p'+str(i), True, i < {n_ev}, False])\n"
            "for i in range(5): w.writerow(['q'+str(i), False, True, True])\n")
    _evidence(tmp_path / "ev", {301: _heredoc("K=/s/k; ", "python3", ["K"], body)})
    (tmp_path / "rec").mkdir()
    f = "k/census/census_ranked.csv"
    return _repo(tmp_path / "repo", {301: body}, [(301, (("K", "replay:k"),))], mkdirs=["k/census"],
                 counts=[{"code": "census_top10", "file": f, "true": ["top10"], "want": 845},
                         {"code": "census_events", "file": f, "true": ["top10", "is_event"], "want": 70}],
                 notes=[{"code": "matched", "file": f, "true": [], "want": 850},
                        {"code": "decided_before", "file": f, "true": ["top10", "decided_before"], "false": ["is_event"], "want": 0}])


@pytest.mark.parametrize("n_top, n_ev, result, codes", [
    (844, 69, "COUNT_FAIL", ["count/census_events", "count/census_top10"]),
    (845, 70, "OK", []),
    (845, 69, "COUNT_FAIL", ["count/census_events"])])
def test_a_census_count_off_by_one_stops(tmp_path, on_host, n_top, n_ev, result, codes):
    rc, got, summary = _run(tmp_path, _census_case(tmp_path, n_top, n_ev))
    assert got == result and summary["fail_codes"] == codes and rc == (0 if result == "OK" else 1)
    assert summary["counts"] == {"census_top10": n_top, "census_events": n_ev}
    assert summary["note_counts"] == {"matched": n_top + 5, "decided_before": 0}   # notes count, never gate
    assert "k/census/census_ranked.csv" in summary["shas"]


@pytest.mark.parametrize("value, ok", [(0.7179, True), (0.7181, True), (0.7174, False), (0.7186, False)])
def test_the_named_value_check_rounds_to_three_places(tmp_path, on_host, value, ok):
    key = "math|t gamma"
    body = ("import sys,csv\n"
            "K=sys.argv[1]\n"
            "w=csv.writer(open(K+'/rk4_cleaned.csv','w',newline=''))\n"
            "w.writerow(['person','decision','prod_clean_pct'])\n"
            f"w.writerow([{key!r}, 'needs_author_ruling', {value!r}])\n"
            "w.writerow(['econ|t delta', 'add', 0.95])\n")
    _evidence(tmp_path / "ev", {401: _heredoc("K=/s/k; ", "python3", ["K"], body)})
    (tmp_path / "rec").mkdir()
    spec = _repo(tmp_path / "repo", {401: body}, [(401, (("K", "replay:k"),))], mkdirs=["k"],
                 named=[{"code": "T00401", "file": "k/rk4_cleaned.csv", "key_column": "person",
                         "key_sha256": _sha(key), "column": "prod_clean_pct", "want": 0.718, "dp": 3}])
    rc, result, summary = _run(tmp_path, spec)
    assert result == ("OK" if ok else "COUNT_FAIL")
    assert summary["fail_codes"] == ([] if ok else ["named/T00401"])
    assert summary["named"] == {"T00401": "ok" if ok else "differs"}
    for text in (spec.read_text(encoding="utf-8"), (tmp_path / "out" / "summary.json").read_text(encoding="utf-8"),
                 (tmp_path / "out" / "checks.json").read_text(encoding="utf-8")):
        assert "gamma" not in text


def test_a_named_key_that_matches_no_row_fails(tmp_path, on_host):
    body = "import sys\nopen(sys.argv[1]+'/r.csv','w').write('person,v\\na,0.718\\n')\n"
    _evidence(tmp_path / "ev", {402: _heredoc("K=/s/k; ", "python3", ["K"], body)})
    (tmp_path / "rec").mkdir()
    spec = _repo(tmp_path / "repo", {402: body}, [(402, (("K", "replay:k"),))], mkdirs=["k"],
                 named=[{"code": "T00402", "file": "k/r.csv", "key_column": "person", "key_sha256": _sha("b"),
                         "column": "v", "want": 0.718, "dp": 3}])
    rc, result, summary = _run(tmp_path, spec)
    assert result == "COUNT_FAIL" and summary["fail_codes"] == ["named/T00402"]


def test_no_recorded_shell_runs(tmp_path, on_host):
    body = "import sys\nopen(sys.argv[1]+'/ran','w').write('x')\n"
    cmd = _heredoc("K=/s/k; touch $K/BEFORE; ", "python3", ["K"], body, "touch $K/AFTER\nrm -rf $K")
    _evidence(tmp_path / "ev", {501: cmd})
    (tmp_path / "rec").mkdir()
    spec = _repo(tmp_path / "repo", {501: body}, [(501, (("K", "replay:k"),))], mkdirs=["k"])
    rc, result, summary = _run(tmp_path, spec)
    assert result == "OK"
    assert (tmp_path / "work" / "root" / "k" / "ran").read_text() == "x"
    names = {p.name for p in tmp_path.rglob("*")}
    assert "BEFORE" not in names and "AFTER" not in names


def test_each_step_runs_isolated_in_a_fresh_root(tmp_path, on_host):
    body = ("import os,sys\n"
            "print('isolated', sys.flags.isolated)\n"
            "print('cwd', os.getcwd())\n"
            "print('entries', len(os.listdir('.')))\n"
            "print('argv0', sys.argv[0])\n"
            "open('scratch.txt','w').write('x')\n")
    _evidence(tmp_path / "ev", {601: _heredoc("K=/s/k; ", "python3", ["K"], body),
                                602: _heredoc("K=/s/k; ", "python3", ["K"], body)})
    (tmp_path / "rec").mkdir()
    spec = _repo(tmp_path / "repo", {601: body, 602: body}, [(601, (("K", "replay:k"),)), (602, (("K", "replay:k"),))],
                 mkdirs=["k"])
    rc, result, summary = _run(tmp_path, spec)
    assert result == "OK"
    for code in ("T00601", "T00602"):
        log = (tmp_path / "out" / "logs" / f"{code}.log").read_text(encoding="utf-8").splitlines()
        assert "isolated 1" in log
        assert f"cwd {(tmp_path / 'work' / 'steps' / code).resolve()}" in log
        assert "entries 0" in log and "argv0 -" in log
    with pytest.raises(SystemExit):
        _run(tmp_path, spec)                                         # the work folder is used now


def test_summary_carries_codes_counts_and_shas_only(tmp_path, on_host):
    allowed = {"result", "fail_codes", "fails", "steps", "lift_sha256", "bytes", "counts", "note_counts", "named",
               "shas", "derived_files", "derived_manifest_sha256"}
    for flip in (False, True):
        sub = tmp_path / str(flip)
        spec = _toy_chain(sub, flip=flip)
        _run(sub, spec)
        text = (sub / "out" / "summary.json").read_text(encoding="utf-8")
        summary = json.loads(text)
        assert set(summary) <= allowed
        assert "|" not in text and "alpha" not in text and "beta" not in text
        assert all(len(v) == 64 for v in summary["shas"].values())
        checks = (sub / "out" / "checks.json").read_text(encoding="utf-8")
        assert "alpha" not in checks and "beta" not in checks
        assert "alpha" in (sub / "out" / "logs" / "T00102.log").read_text(encoding="utf-8")   # names stay in logs


def test_refuses_off_an_r1_instance(tmp_path, monkeypatch):
    monkeypatch.delenv("SAR_HOST", raising=False)
    spec = _toy_chain(tmp_path)
    with pytest.raises(SystemExit):
        _run(tmp_path, spec)
    assert not (tmp_path / "work").exists() and not (tmp_path / "out").exists()


# ---- the committed spec ----------------------------------------------------------------------------------------------

def test_the_committed_spec_names_a_registered_file_for_every_step():
    path = REPO / "config" / "r1" / "derivations.json"
    text = path.read_text(encoding="utf-8")
    spec = rd.load_spec(path)
    assert [s["line"] for s in spec["steps"]] == PROD_LINES
    for s in spec["steps"]:
        f = REPO / s["file"]
        assert s["file"] == f"config/r1/derivations/T{s['line']:05d}.py" and f.is_file(), s["file"]
        assert _sha(f.read_bytes()) == s["sha256"], s["file"]
        compile(f.read_text(encoding="utf-8"), s["file"], "exec")
    assert sorted(p.name for p in (REPO / "config" / "r1" / "derivations").iterdir() if p.is_file()) == \
        [f"T{n:05d}.py" for n in PROD_LINES]
    assert not (REPO / "pipeline" / "aws" / "r1" / "derivations").exists()    # reviewed copies, never imported
    assert {g["name"]: (g["got"], g["want"]) for g in spec["bytes"]} == {
        "rk4in_requests": ("rk1/rk4in/requests.json", "recovered:rk4/payload/in/requests.json"),
        "census_full": ("rk1/census/census_full.json", "recovered:rk5/payload/in/census_full.json"),
        "rk5in_requests": ("rk1/rk5in/requests.json", "recovered:rk5/payload/in/requests.json"),
        "rk5in_extra_universe": ("rk1/rk5in/extra_universe.json", "recovered:rk5/payload/in/extra_universe.json")}
    assert {c["code"]: c["want"] for c in spec["counts"]} == {"census_top10": 845, "census_events": 70}
    assert {c["code"]: c["want"] for c in spec["notes"]} == {"matched": 1318, "decided_before": 245, "new": 530}
    [named] = spec["named"]
    assert (named["code"], named["file"], named["column"], named["want"], named["dp"]) == \
        ("T03407", "rk1/rk4_cleaned.csv", "prod_clean_pct", 0.718, 3)
    assert len(named["key_sha256"]) == 64
    assert "|" not in text                                       # no 'field|name' key is committed


def test_the_recder_job_spec_runs_the_replay_from_its_copy():
    job = json.loads((REPO / "config" / "r1" / "jobs" / "recder.json").read_text(encoding="utf-8"))
    assert job["kind"] == "recder" and job["sar_host"] == "ec2-r1" and job["env_layers"] == ["py"]
    assert job["pulls"] == [["r1/evidence/", "/work/evidence/"]] and job["required_dests"] == ["/work/recovered/"]
    assert ["pipeline/aws/r1/replay_derivations.py", "/work/replay_derivations.py"] in job["copy_from_tip"]
    assert ["pipeline/aws/r1/recover_rk.py", "/work/recover_rk.py"] in job["copy_from_tip"]
    steps = job["steps"]
    assert "verify_inputs.py recovered" in steps[0] and "recovered_pins.json" in steps[0]
    assert "verify_inputs.py data" in steps[1] and "jobs/recder.json" in steps[1]
    assert "/work/replay_derivations.py" in steps[-1] and "config/r1/derivations.json" in steps[-1]
    assert all("r1/recovered" not in d for _, d in job["data_sync"])        # rec-01 is pulled, never rewritten
