# -*- coding: utf-8 -*-
"""pipeline/aws/r1/recover_rk.py - the RK1-RK5 recovery job, on synthetic runs in a fake S3."""
from __future__ import annotations

import hashlib
import io
import json
import pathlib
import subprocess
import sys
import tarfile

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
sys.path.insert(0, str(REPO / "tests"))
import recover_rk as rr                   # noqa: E402
from r1_fakes import install_fake_aws     # noqa: E402

KIT = {"rk1.py": ("print('rk1')\nX = 0\n", "X = 0", "X = 1"),
       "rk2.py": ("print('rk2')\nY = 0\n", "Y = 0", "Y = 2"),
       "rk3.py": ("print('rk3')\n", None, None),
       "rk5_match.py": ("print('rk5 match')\n", None, None)}
SPANS = {"rk1.py": (2664, [2675]), "rk2.py": (3071, [3082]), "rk3.py": (3205, []), "rk5_match.py": (4546, [])}
#: a toy prep_rk1.py with the real one's shape: REPO constant, HERE/in, HERE.parent/sweep/v2, run_caliber calls
TOY_PREP = '''import csv, json, pathlib, sys
REPO = pathlib.Path({repo!r})
HERE = pathlib.Path(__file__).resolve().parent
V2 = HERE.parent / "sweep" / "v2"
IN = HERE / "in"; IN.mkdir(exist_ok=True)
sys.path.insert(0, str(REPO))
import run_caliber as rc
hd, ha, prov = rc.historical_calls()
od, _ = rc.october_calls()
for name, pairs in (("drops.csv", hd | od), ("adds.csv", ha)):
    with open(IN / name, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["aid", "wid"]); w.writerows(sorted(pairs))
o = json.load(open(V2 / "verify_result.json"))
json.dump([d["key"] for d in o["decisions"]], open(IN / "requests.json", "w"), indent=1)
json.dump([r["author_id"] for r in csv.DictReader(open(REPO / "ctrl.csv"))], open(IN / "control.json", "w"), indent=1)
'''
SWEEP_RESULT = {"decisions": [{"key": "econ|k one"}, {"key": "chem|k two"}]}
PREP_OUT = {"in/requests.json": json.dumps(["econ|k one", "chem|k two"], indent=1).encode(),
            "in/control.json": json.dumps(["A1000001"], indent=1).encode()}
USERDATA = "#!/bin/bash\nP=$B/rk1/20261002\necho RK1 instance rk1-boot\n/work/venv/bin/python /work/rk1.py\n"
LAUNCH_CMDS = {
    2783: 'K=/scratch/rk1; cat > $K/custody.json <<EOF\n{"job":"rk1","payload_sha256":"$(cut -d\' \' -f1 $K/payload.sha256)"}\nEOF\necho ok',
    3108: ("K=/scratch/rk1; cd $K && sed -e 's#rk1/20261002#rk2/20261002#' -e 's#/work/rk1.py#/work/rk2.py#' "
           "-e 's#RK1 instance#RK2 instance#' -e 's#rk1-boot#rk2-boot#g' userdata.sh > userdata2.sh && grep -c rk2 userdata2.sh"),
    3131: 'K=/scratch/rk1; cat > $K/custody_rk2.json <<EOF\n{"job":"rk2"}\nEOF\necho ok',
    3228: "K=/scratch/rk1; cd $K && cat > userdata3.sh <<'EOF'\n#!/bin/bash\nP=$B/rk3/20261002\n/work/venv/bin/python /work/rk3.py\nEOF\necho ok",
    3360: ("K=/scratch/rk1; cd $K && sed -e 's#rk1/20261002#rk4/20261002#' -e 's#rk1-boot#rk4-boot#g' "
           "-e 's#RK1 instance#RK4 instance#' userdata.sh > userdata4.sh && grep -c rk4 userdata4.sh"),
    4570: ("K=/scratch/rk1; cd $K && python3 - <<'EOF'\n"
           "s=open('userdata2.sh').read()\n"
           "s=s.replace('rk2/20261002','rk5/20261002').replace('rk2-boot','rk5-boot')\n"
           "old='/work/venv/bin/python /work/rk2.py'\n"
           "new='/work/venv/bin/python /work/rk5_match.py\\n/work/venv/bin/python /work/rk2.py'\n"
           "assert s.count(old)==1; s=s.replace(old,new)\n"
           "open('userdata5.sh','w').write(s); print('ok')\n"
           "EOF\nbash -n userdata5.sh")}


def _final(name):
    text, old, new = KIT[name]
    return text.replace(old, new, 1) if old else text


def _tar(path, members):
    with tarfile.open(path, "w:gz") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


def _untar(path):
    with tarfile.open(path, "r:gz") as tf:
        return {m.name: tf.extractfile(m).read() for m in tf.getmembers() if m.isfile()}


def _sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def _git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _history(ev, repo):
    """One 5-line slice around each recorded op: the kit Writes/Edits and the launch-side records."""
    d = ev / "history"
    d.mkdir(parents=True)

    def rec(tool, inp):
        return json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": tool, "input": inp}]}})
    recs = {}
    for name, (w, edits) in SPANS.items():
        text, old, new = KIT[name]
        recs[w] = rec("Write", {"file_path": f"/scratch/rk1/{name}", "content": text})
        for n in edits:
            recs[n] = rec("Edit", {"file_path": f"/scratch/rk1/{name}", "old_string": old, "new_string": new})
    recs[2683] = rec("Write", {"file_path": "/scratch/rk1/prep_rk1.py", "content": TOY_PREP.format(repo=str(repo))})
    recs[2724] = rec("Write", {"file_path": "/scratch/rk1/userdata.sh", "content": USERDATA})
    for n, cmd in LAUNCH_CMDS.items():
        recs[n] = rec("Bash", {"command": cmd})
    filler = json.dumps({"type": "user", "message": {"content": "x"}})
    for n, line in recs.items():
        a, b = n - 2, n + 2
        (d / f"T_{a:05d}-{b:05d}.jsonl").write_text("".join((line if k == n else filler) + "\n" for k in range(a, b + 1)))


def _runs(s3root, repo, base):
    arch = subprocess.run(["git", "-C", str(repo), "archive", base, "pipeline"], capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(arch)) as tf:
        repo_members = {"repo/" + m.name: tf.extractfile(m).read() for m in tf.getmembers() if m.isfile()}
    kits = {"rk1": ["rk1.py"], "rk2": ["rk2.py"], "rk3": ["rk3.py"], "rk4": ["rk1.py"], "rk5": ["rk5_match.py", "rk2.py"]}
    reports = {"rk1": ("rk1_report.json", "control_fail"), "rk2": ("rk2_report.json", "gate_fail"),
               "rk4": ("rk1_report.json", "control_fail"), "rk5": ("rk2_report.json", "gate_fail")}
    shas = {}
    for run, names in kits.items():
        d = s3root / "bkt" / run / "20261002"
        (d / "in").mkdir(parents=True)
        (d / "out").mkdir()
        members = {f"in/{run}_input.json": b"{}", **{k: _final(k).encode() for k in names}}
        if run == "rk1":
            members.update(PREP_OUT)                    # what the toy prep_rk1.py writes
        if run != "rk3":
            members.update(repo_members)
        _tar(d / "in" / "payload.tar.gz", members)
        shas[run] = _sha(d / "in" / "payload.tar.gz")
        (d / "in" / "payload.sha256").write_text(f"{shas[run]}  payload.tar.gz\n")
        outm = {"out/RESULT.txt": b"OK\n", f"out/{run}_table.csv": b"a,b\n1,2\n"}
        if run in reports:
            outm[f"out/{reports[run][0]}"] = json.dumps({reports[run][1]: [], "secs": 1}).encode()
        _tar(d / "out" / "out.tar.gz", outm)
        (d / "out" / "out.sha256").write_text(f"{_sha(d / 'out' / 'out.tar.gz')}  /work/out.tar.gz\n")
        (d / "out" / "boot.log").write_text("boot\n")
        (d / "status.txt").write_text("DONE rc=0 OK\n")
    return shas


@pytest.fixture
def world(tmp_path, monkeypatch):
    fake = install_fake_aws(tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "pipeline").mkdir()
    (repo / "pipeline" / "x.py").write_text("X = 1\n")
    (repo / "ctrl.csv").write_text("author_id\nA1000001\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD")
    shas = _runs(fake["s3root"], repo, base)
    ev = tmp_path / "evidence"
    _history(ev, repo)
    (ev / "workflows").mkdir()
    (ev / "workflows" / "wf_9b087077-158.json").write_text(json.dumps({"result": SWEEP_RESULT}))
    monkeypatch.setattr(rr, "KNOWN_PAYLOAD_SHA", {"rk1": shas["rk1"], "rk2": shas["rk2"]})
    monkeypatch.setattr(rr, "KNOWN_PAYLOAD_SHA_PREFIX", {"rk3": shas["rk3"][:16]})
    monkeypatch.setattr(rr, "BASE_COMMIT", base)
    monkeypatch.setattr(rr, "RK1_REPO_PATHS", ("pipeline",))
    return {"fake": fake, "repo": repo, "ev": ev, "tmp": tmp_path}


def _main(w, dest="r1/recovered/rec-t"):
    return rr.main(["--bucket", "s3://bkt", "--date", "20261002", "--evidence", str(w["ev"]), "--repo", str(w["repo"]),
                    "--work", str(w["tmp"] / "work"), "--out", str(w["tmp"] / "out"), "--dest", dest,
                    "--python", sys.executable])


def _fails(w):
    return json.loads((w["tmp"] / "out" / "checks.json").read_text())["fails"]


def test_full_recovery_passes_and_uploads_a_manifest(world):
    assert _main(world) == 0
    assert (world["tmp"] / "out" / "RESULT.txt").read_text().strip() == "OK" and _fails(world) == []
    dest = world["fake"]["s3root"] / "bkt" / "r1" / "recovered" / "rec-t"
    assert (dest / "rk1" / "payload" / "rk1.py").read_text() == _final("rk1.py")
    assert (dest / "rk4" / "out" / "rk1_report.json").is_file()
    assert not (dest / "rk1" / "payload" / "repo").exists()
    rows = (dest / "manifest.tsv").read_text().splitlines()
    assert rows[0] == "run\tpart\tmember\tbytes\tsha256"
    assert any(r.startswith("rk5\tpayload\trk2.py\t") for r in rows)
    assert any(r.startswith("kit\tlaunch_side\tprep_rk1.py\t") for r in rows)
    assert not any("\trepo/" in r for r in rows)
    s = json.loads((dest / "summary.json").read_text())
    assert s["result"] == "OK" and s["fail_codes"] == []
    assert set(s["pins"]) == {"rk1/payload/rk1.py", "manifest.tsv", "launch_side/prep_rk1.py"}
    assert s["pins"]["rk1/payload/rk1.py"] == hashlib.sha256(_final("rk1.py").encode()).hexdigest()


def test_launch_side_files_are_rebuilt_and_prep_rk1_reproduces_its_inputs(world):
    assert _main(world) == 0
    ls = world["fake"]["s3root"] / "bkt" / "r1" / "recovered" / "rec-t" / "launch_side"
    ud2 = (USERDATA.replace("rk1/2026", "rk2/2026").replace("/work/rk1.py", "/work/rk2.py")
           .replace("RK1 instance", "RK2 instance").replace("rk1-boot", "rk2-boot"))
    assert (ls / "userdata.sh").read_text() == USERDATA and (ls / "userdata2.sh").read_text() == ud2
    assert (ls / "userdata4.sh").read_text() == USERDATA.replace("rk1/2026", "rk4/2026").replace(
        "rk1-boot", "rk4-boot").replace("RK1 instance", "RK4 instance")
    assert (ls / "userdata5.sh").read_text() == ud2.replace("rk2/2026", "rk5/2026").replace("rk2-boot", "rk5-boot").replace(
        "/work/venv/bin/python /work/rk2.py", "/work/venv/bin/python /work/rk5_match.py\n/work/venv/bin/python /work/rk2.py")
    assert (ls / "userdata3.sh").read_text() == "#!/bin/bash\nP=$B/rk3/20261002\n/work/venv/bin/python /work/rk3.py\n"
    assert '"$(cut' in (ls / "custody.json").read_text()                      # the template, not re-filled
    assert (ls / "cmd_T03108.txt").read_text() == LAUNCH_CMDS[3108]
    notes = json.loads((world["tmp"] / "out" / "checks.json").read_text())["notes"]
    assert any("drops.csv/adds.csv" in n for n in notes)
    assert any(n.startswith("rk4 boot.log vs userdata4.sh: '/work/rk1.py' in user-data True") for n in notes)


def test_a_prep_rk1_that_does_not_reproduce_the_payload_fails(world):
    (world["ev"] / "workflows" / "wf_9b087077-158.json").write_text(json.dumps({"result": {"decisions": [{"key": "x"}]}}))
    assert _main(world) == 1
    assert any(f.startswith("launch_side/prep_rk1 | requests.json") for f in _fails(world))


def test_the_summary_carries_codes_not_fail_texts(world):
    d = world["fake"]["s3root"] / "bkt" / "rk1" / "20261002" / "out"
    _tar(d / "out.tar.gz", {"out/RESULT.txt": b"OK\n", "out/rk1_report.json": json.dumps({"control_fail": [["11", "A1000001"]]}).encode()})
    (d / "out.sha256").write_text(f"{_sha(d / 'out.tar.gz')}  out.tar.gz\n")
    assert _main(world) == 1
    s = (world["tmp"] / "out" / "summary.json").read_text()
    assert json.loads(s)["fail_codes"] == ["rk1/control_fail"] and "A1000001" not in s


def test_refuses_a_destination_outside_r1_and_refuses_off_aws(world, monkeypatch):
    with pytest.raises(SystemExit, match="outside r1/"):
        _main(world, dest="rk1/20261002")
    monkeypatch.delenv("SAR_HOST", raising=False)
    with pytest.raises(SystemExit, match="only on an R1 AWS instance"):
        _main(world)


def test_a_control_failure_fails_the_recovery(world):
    d = world["fake"]["s3root"] / "bkt" / "rk1" / "20261002" / "out"
    _tar(d / "out.tar.gz", {"out/RESULT.txt": b"OK\n", "out/rk1_report.json": json.dumps({"control_fail": [["11", "A1"]]}).encode()})
    (d / "out.sha256").write_text(f"{_sha(d / 'out.tar.gz')}  out.tar.gz\n")
    assert _main(world) == 1
    assert any("control_fail" in f for f in _fails(world))


def test_a_kit_copy_that_differs_from_the_history_fails(world):
    d = world["fake"]["s3root"] / "bkt" / "rk4" / "20261002" / "in"
    members = _untar(d / "payload.tar.gz")
    members["rk1.py"] = b"print('tampered')\n"
    _tar(d / "payload.tar.gz", members)
    (d / "payload.sha256").write_text(f"{_sha(d / 'payload.tar.gz')}  payload.tar.gz\n")
    assert _main(world) == 1
    assert any("rk1.py" in f and "rk4" in f for f in _fails(world))


def test_expected_sha_reads_a_work_prefixed_name(tmp_path):
    f = tmp_path / "out.sha256"
    f.write_text("ab" * 32 + "  /work/out.tar.gz\n")
    assert rr.expected_sha(f) == ("ab" * 32, "out.tar.gz")


def test_verify_names_a_wrong_hash(tmp_path):
    p = tmp_path / "out.tar.gz"
    p.write_bytes(b"x")
    s = tmp_path / "out.sha256"
    s.write_text("00" * 32 + "  out.tar.gz\n")
    assert "sha256" in rr.verify(p, s)
    s.write_text(_sha(p) + "  other.tar.gz\n")
    assert "names other.tar.gz" in rr.verify(p, s)
    s.write_text(_sha(p) + "  out.tar.gz\n")
    assert rr.verify(p, s) is None


def test_safe_extract_refuses_traversal_and_a_used_directory(tmp_path):
    bad = tmp_path / "bad.tar.gz"
    _tar(bad, {"../evil.txt": b"x"})
    with pytest.raises(Exception):
        rr.safe_extract(bad, tmp_path / "x")
    assert not (tmp_path / "evil.txt").exists()
    good = tmp_path / "good.tar.gz"
    _tar(good, {"a.txt": b"x"})
    (tmp_path / "used").mkdir()
    (tmp_path / "used" / "f").write_text("y")
    with pytest.raises(RuntimeError, match="not empty"):
        rr.safe_extract(good, tmp_path / "used")


def test_rebuild_applies_each_recorded_edit_exactly_once(tmp_path):
    _history(tmp_path / "ev", tmp_path)
    lines = rr.history_lines(tmp_path / "ev")
    assert rr.rebuild(lines, 2664, [2675], "rk1.py") == _final("rk1.py").encode()
    with pytest.raises(RuntimeError, match="names rk1.py"):
        rr.rebuild(lines, 2664, [], "rk2.py")
    lines[2675]["message"]["content"][0]["input"]["old_string"] = "absent"
    with pytest.raises(RuntimeError, match="occurs 0 times"):
        rr.rebuild(lines, 2664, [2675], "rk1.py")


def test_a_slice_with_the_wrong_number_of_lines_is_refused(tmp_path):
    d = tmp_path / "ev" / "history"
    d.mkdir(parents=True)
    (d / "T_00010-00012.jsonl").write_text('{"a": 1}\n{"a": 2}\n')
    with pytest.raises(RuntimeError, match="2 lines, want 3"):
        rr.history_lines(tmp_path / "ev")


def test_tree_diff_ignores_bytecode(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        (d / "p").mkdir(parents=True)
        (d / "p" / "x.py").write_text("1")
    (b / "p" / "__pycache__").mkdir()
    (b / "p" / "__pycache__" / "x.cpython-312.pyc").write_bytes(b"\0")
    assert rr.tree_diff(a, b) == []
    (b / "p" / "x.py").write_text("2")
    assert rr.tree_diff(a, b) == ["differs: p/x.py"]
