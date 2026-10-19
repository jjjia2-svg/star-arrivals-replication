# -*- coding: utf-8 -*-
"""R1 V3-FINAL.d (unit W2-FINALJOB): the final job (M) and its twin finalb0 (October data, the switch-off
proof). pipeline/aws/r1/final_stage.py's pure helpers, its canon assembly on a toy stage set, the two stage
tables, the two job specs and the four config files it reads.

Toy data in tmp_path only: no vault, no frames, no LaTeX, no R. The canon tests run the repo's own
restore_upstream.py and tools/r1_canon.py as subprocesses on a three-file toy stage set; the paper row's
command names analysis/run_all.sh but nothing here runs it.
"""
from __future__ import annotations

import fnmatch
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for _p in (REPO / "pipeline" / "aws" / "r1", REPO / "tools", REPO):
    sys.path.insert(0, str(_p))
import final_stage as fs            # noqa: E402
import r1kit                        # noqa: E402
import run_stages as rs             # noqa: E402
from analysis.lib import canon      # noqa: E402

PY = sys.executable
STAGES = REPO / "config" / "r1" / "stages"
JOBS = REPO / "config" / "r1" / "jobs"


def _table(job):
    return rs.load_table(STAGES / f"{job}.json")


def _rows(job):
    return {s["name"]: s for s in _table(job)["stages"]}


# ---- the stage tables and the job specs -----------------------------------------------------------
def test_final_and_finalb0_tables_load_and_name_existing_scripts():
    for job, first in (("final", "verify_inputs"), ("finalb0", "verify_inputs")):
        t = _table(job)
        assert t["job"] == job and t["stages"][0]["name"] == first
        names = [s["name"] for s in t["stages"]]
        assert names[:3] == ["verify_inputs", "config", "tree_unpack"]
        # gate2 grades the paper last; only final's canon_pack (public package step 13) runs after it
        assert names[-1] == "gate2" or (job == "final" and names[-2:] == ["gate2", "canon_pack"])
        for need in r1kit.REQUIRED_STAGES[job]:
            assert need in names, (job, need)
        probs = r1kit.check_stage_table({"stages": f"config/r1/stages/{job}.json"}, "c" * 40,
                                        show=lambda p: (REPO / p).read_text(encoding="utf-8"),
                                        exists=lambda p: (REPO / p).exists())
        assert t["complete"] is True                                       # W3-FLIPS (F30) after the final Codex review
        if t.get("complete"):
            assert probs == [], probs
        else:
            assert len(probs) == 1 and "incomplete" in probs[0], probs
        for s in t["stages"]:
            assert s["outputs"] and all(o.startswith(("work:prod/", "repo:output/", "work:out/")) for o in s["outputs"])
            if s.get("script") == "pipeline/aws/r1/final_stage.py":
                assert s["cmd"].startswith('"$PY" "$WORK/final_stage.py" ')
                sub = s["cmd"].split()[2]
                assert sub in fs.SUBCOMMANDS, (job, s["name"], sub)
    rows = _rows("final")
    assert "--run-stages 1,3est,3light" in rows["paper"]["cmd"] and "analysis/run_all.sh" in rows["paper"]["requires"]
    assert "config/r1/paths_aws_m.yaml" in rows["paper"]["cmd"]
    assert {"tools/r1_custody_spec.py", "tools/verify_cloud_custody.py", "tools/verify_manifest.py"} <= set(
        rows["custody"]["requires"])
    assert rows["custody"]["owner"] == "F26"
    assert "grep -qx CUSTODY_OK" in rows["custody"]["cmd"] and "/work/j1a_out/RESULT.txt" in rows["custody"]["cmd"]
    assert "work:out/final" in rows["gate2"]["outputs"]
    # the sentinel never runs inside the paper row (run_all stage 4check is not asked for)
    assert "4check" not in rows["paper"]["cmd"]
    # no row writes the repo's check_paper.py, analysis/expected or data/cal2026-10
    for s in _table("final")["stages"] + _table("finalb0")["stages"]:
        for o in s["outputs"]:
            assert not o.startswith(("repo:tools", "repo:analysis", "repo:data")), (s["name"], o)


def test_the_final_job_packs_the_canon_it_ran_on_for_the_repository():
    """Plan step 13: the last row packs /work/canon_m -- the canon every paper row read -- into
    out/canon/canon_r1.tar (fetchable: out/MANIFEST.sha256 lists it) for data/report/, after proving its top
    MANIFEST is stage:canon's."""
    rows = _rows("final")
    assert list(rows)[-1] == "canon_pack"
    r = rows["canon_pack"]
    assert r["needs"] == ["canon"] and "stage:canon" in r["inputs"] and "repo:tools/r1_canon_pack.py" in r["inputs"]
    assert "/work/canon_m" in r["cmd"] and "/work/prod/canon/canon_manifest.sha256" in r["cmd"]
    assert "--xz cal_intermediates/pairs_unified.csv" in r["cmd"] and "--out /work/out/canon" in r["cmd"]
    assert r["outputs"] == ["work:out/canon"]
    # public step 13 also needs the J1a cell records the custody stage reads, to rebuild the custody folder with
    # repo-relative paths (r1_custody_spec.py): they ride in the same fetchable folder
    for rel in ("work/j1a/cells_rmac/files/work/prod/cells_rmac", "work/j1a/cells_rcloud/files/work/prod/cells_rcloud",
                "work/j1a/cells_rmac_evcl/files/work/prod/cells_rmac_evcl",
                "work/j1a/cells_rcloud_evcl/files/work/prod/cells_rcloud_evcl", "work/j1a_out/RESULT.txt"):
        assert rel in r["cmd"], rel
    assert "/work/out/canon/custody_inputs_r1.tar" in r["cmd"] and "--sort=name" in r["cmd"]


def _subst(text: str) -> str:
    for m, b in fs.B0_SUBST:
        text = text.replace(m, b)
    return text


def test_finalb0_differs_from_final_only_in_mode_canon_and_custody():
    """finalb0 = final.json minus its M-only rows (including the author-tree sentinel), plus its B0-only rows (pairs_b0:
    J0's October pairs_unified.csv, the counterpart of the canon's cal_intermediates; review R7 #1)."""
    m, b = _rows("final"), _rows("finalb0")
    assert [n for n in b if n not in fs.B0_ONLY_STAGES] == [n for n in m if n not in fs.M_ONLY_STAGES]
    assert set(fs.M_ONLY_STAGES) == {"canon", "custody", "canon_pack", "tree_unpack_r1", "sentinel_r1"}
    assert set(fs.B0_ONLY_STAGES) == {"pairs_b0"}
    assert set(fs.B0_ONLY_STAGES) <= set(b) and not set(fs.B0_ONLY_STAGES) & set(m)
    for name, sb in b.items():
        if name in fs.B0_ONLY_STAGES:
            continue
        sm = m[name]
        assert sb["cmd"] == _subst(sm["cmd"]), name
        assert sb.get("script") == sm.get("script") and sb.get("requires", []) == sm.get("requires", []), name
        assert sb["outputs"] == sm["outputs"] and sb.get("resume") == sm.get("resume"), name
        assert [n for n in sb["needs"] if n not in fs.B0_ONLY_STAGES] == \
            [n for n in sm["needs"] if n not in fs.M_ONLY_STAGES], name
        im = {_subst(t) for t in sm["inputs"]} - set(fs.CANON_INPUTS["M"])
        ib = set(sb["inputs"]) - set(fs.CANON_INPUTS["B0"])
        assert im == ib, name
        # a stage reads the canon in M iff it reads the October roots in B0
        assert bool(set(sm["inputs"]) & set(fs.CANON_INPUTS["M"])) == bool(set(sb["inputs"]) & set(fs.CANON_INPUTS["B0"])), name
        if "--mode" in sm["cmd"]:
            assert "--mode M" in sm["cmd"] and "--mode B0" in sb["cmd"], name
    assert "--mode M" in m["canon"]["cmd"]


def test_job_specs_final_and_finalb0():
    jm, jb = r1kit.load_job("final"), r1kit.load_job("finalb0")
    assert jm["env"]["SAR_R1_CONFIG"] == "$REPO_DIR/config/r1/M.json"
    assert jb["env"]["SAR_R1_CONFIG"] == "$REPO_DIR/config/r1/B0.json"
    assert set(jm["required_dests"]) == {"/work/j1a/", "/work/j1b/", "/work/j1a_out/"}
    assert jb["required_dests"] == ["/work/j0/"]          # J0's stage set: October pairs_unified.csv (pairs_b0)
    assert jb["pulls"] == jm["pulls"] == []
    assert jm["env_layers"] == jb["env_layers"] == ["py", "rmac", "tex"]
    assert jm["est_min"] == 120 and jm["root_gb"] >= 100 and jb["root_gb"] >= 100
    assert jm["stages"] == "config/r1/stages/final.json" and jb["stages"] == "config/r1/stages/finalb0.json"
    assert jb["data_sync"] == jm["data_sync"]
    same = {k: v for k, v in jm.items() if k not in fs.TWIN_JOB_KEYS}
    assert same == {k: v for k, v in jb.items() if k not in fs.TWIN_JOB_KEYS}
    assert jb["steps"] == [s.replace("stages/final.json", "stages/finalb0.json") for s in jm["steps"]]
    assert {k: v for k, v in jb["env"].items() if k != "SAR_R1_CONFIG"} == \
           {k: v for k, v in jm["env"].items() if k != "SAR_R1_CONFIG"}
    assert jm["kind"] == "final" and jb["kind"] == "finalb0"


# ---- finalb0's October pairs_unified.csv (review R7 #1) -------------------------------------------
FINALB0_LAYOUT = REPO / "config" / "r1" / "layouts" / "finalb0_from_j0.json"
PAIRS_TOKEN = "repo:output/cal_intermediates/cal2026-10/pairs_unified.csv"


def _flag(argv, flag, start=0):
    return argv[argv.index(flag, start) + 1]


def _pairs_b0_parts():
    """shlex-split of pairs_b0's cmd into its restore_upstream and check_pin halves."""
    import shlex
    argv = shlex.split(_rows("finalb0")["pairs_b0"]["cmd"])
    r = argv.index("$WORK/restore_upstream.py")
    c = argv.index("$WORK/check_pin.py", r)
    return argv[r:c], argv[c:]


def test_finalb0_restores_october_pairs_from_j0():
    """gaps_zenou.py (run_all 3est) needs the October pairs_unified.csv, which is git-ignored and never
    uploaded (ruling R2): finalb0's pairs_b0 restores J0's rebuilt file from J0's stage set (digest-checked
    against J0's marker), checks it against the October pin and declares it as an input of every row that
    reads the October roots."""
    import yaml
    lay = json.loads(FINALB0_LAYOUT.read_text(encoding="utf-8"))
    assert lay["schema"] == "sar.r1.layout.v1" and len(lay["rows"]) == 1
    row = lay["rows"][0]
    j0 = _rows("j0")
    assert row == {"dest": "pairs_unified.csv",
                   "from": {"job": "j0", "stage": "frames_econ920", "token": PAIRS_TOKEN, "rel": ""}}
    assert row["from"]["token"] in j0["frames_econ920"]["outputs"]
    b = _rows("finalb0")
    s = b["pairs_b0"]
    assert s["owner"] == "V3-FINAL" and s["needs"] == ["config"] and s.get("resume") is None
    assert s["script"] == "pipeline/aws/r1/restore_upstream.py"
    assert s["requires"] == ["pipeline/aws/r1/check_pin.py"]
    assert s["outputs"] == [PAIRS_TOKEN, "work:prod/pairs_b0"]
    assert {"repo:config/r1/layouts/finalb0_from_j0.json", "repo:pipeline/aws/r1/restore_upstream.py",
            "repo:pipeline/aws/r1/check_pin.py", "repo:data/cal2026-10/MANIFEST.sha256"} <= set(s["inputs"])
    rest, pin = _pairs_b0_parts()
    assert _flag(rest, "--stages") == "j0=/work/j0" and _flag(rest, "--layout") == \
        "$REPO_DIR/config/r1/layouts/finalb0_from_j0.json"
    cal = yaml.safe_load((REPO / "config" / "r1" / "paths_aws.yaml").read_text(encoding="utf-8"))["cal_intermediates"]
    want = f"$REPO_DIR/{cal}/pairs_unified.csv"
    assert f"{_flag(rest, '--dest')}/{row['dest']}" == want == "$REPO_DIR/" + PAIRS_TOKEN.split(":", 1)[1]
    import shlex
    jp = shlex.split(j0["pairs_pin"]["cmd"])
    assert _flag(pin, "--file") == _flag(jp, "--file") == want
    assert _flag(pin, "--key") == _flag(jp, "--key") == "october.pairs_unified"
    rep = _flag(pin, "--report")
    assert pathlib.PurePosixPath(rep).name == pathlib.PurePosixPath(_flag(jp, "--report")).name \
        == "build_report_econ920_2026-10.json"
    assert rep == "$REPO_DIR/data/cal2026-10/frames_econ/build_report_econ920_2026-10.json"   # the committed October one
    man = (REPO / "data" / "cal2026-10" / "MANIFEST.sha256").read_text(encoding="utf-8")
    assert re.search(r"^[0-9a-f]{64}\s+(?:\S*/)?frames_econ/build_report_econ920_2026-10\.json$", man, re.M)
    # the B0 counterpart of stage:canon: every row that reads the October roots reads it, paper waits for it
    assert "stage:pairs_b0" in fs.CANON_INPUTS["B0"]
    october = set(fs.CANON_INPUTS["B0"]) - {"stage:pairs_b0"}
    for name, st in b.items():
        if october <= set(st["inputs"]):
            assert "stage:pairs_b0" in st["inputs"], name
    assert {n for n, st in b.items() if "stage:pairs_b0" in st["inputs"]} == \
        {"paper", "sentinel_pre", "repin", "sentinel_post", "numbers", "gate2"}
    assert b["paper"]["needs"] == ["config", "pairs_b0"]


def _toy_pairs_b0(tmp_path, *, tamper=False, pin_sha=None):
    """Run pairs_b0's own cmd on a toy J0 stage set, in a toy repo dir (never the real repo)."""
    import hashlib
    repo, work, j0 = tmp_path / "repo", tmp_path / "work", tmp_path / "j0"
    (repo / "config" / "r1" / "layouts").mkdir(parents=True)
    shutil.copyfile(FINALB0_LAYOUT, repo / "config" / "r1" / "layouts" / FINALB0_LAYOUT.name)
    (repo / "pipeline" / "aws" / "r1").mkdir(parents=True)
    shutil.copyfile(REPO / "pipeline" / "aws" / "r1" / "check_pin.py", repo / "pipeline" / "aws" / "r1" / "check_pin.py")
    work.mkdir()
    for f in ("restore_upstream.py", "run_stages.py"):      # run_one's script copy and the job's copy_from_tip
        shutil.copyfile(REPO / "pipeline" / "aws" / "r1" / f, work / f)
    data = b"pair_id,a,b\n1,x,y\n2,y,z\n"
    tok = j0 / "frames_econ920" / "files" / "repo" / PAIRS_TOKEN.split(":", 1)[1]
    tok.parent.mkdir(parents=True)
    tok.write_bytes(data)
    (j0 / "frames_econ920.done.json").write_text(json.dumps({"outputs": {PAIRS_TOKEN: rs.digest_of(tok)}}))
    if tamper:
        tok.write_bytes(data + b"3,z,w\n")
    rp = repo / "data" / "cal2026-10" / "frames_econ" / "build_report_econ920_2026-10.json"
    rp.parent.mkdir(parents=True)
    rp.write_text(json.dumps({"october": {"pairs_unified": {"sha256": pin_sha or hashlib.sha256(data).hexdigest(),
                                                            "bytes": len(data)}}}))
    out = work / "prod" / "pairs_b0"
    out.mkdir(parents=True)
    cmd = _rows("finalb0")["pairs_b0"]["cmd"].replace("/work/j0", str(j0))
    env = dict(os.environ, PY=PY, WORK=str(work), REPO_DIR=str(repo), STAGE_OUT=str(out), COMMIT="c" * 40,
               SAR_HOST="ec2-r1-test")
    r = subprocess.run(["bash", "-c", cmd], cwd=str(work), env=env, capture_output=True, text=True)
    return r, repo / PAIRS_TOKEN.split(":", 1)[1], out, data


def test_pairs_b0_lays_out_and_pins_the_j0_pairs_file(tmp_path):
    r, dest, out, data = _toy_pairs_b0(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert dest.read_bytes() == data and not dest.is_symlink() and not dest.parent.is_symlink()
    assert dest.stat().st_nlink == 1                              # check_pin refuses a hard link
    assert json.loads((out / "report_restore.json").read_text())["result"] == "OK"
    assert json.loads((out / "pin_check.json").read_text())["verdict"] == "MATCH"


def test_pairs_b0_refuses_a_file_off_its_j0_marker_or_off_the_october_pin(tmp_path):
    r, dest, out, _ = _toy_pairs_b0(tmp_path / "a", tamper=True)
    assert r.returncode != 0 and not dest.exists()
    assert json.loads((out / "report_restore.json").read_text())["code"] == "DIGEST_MISMATCH"
    r, dest, out, _ = _toy_pairs_b0(tmp_path / "b", pin_sha="0" * 64)
    assert r.returncode != 0
    assert json.loads((out / "pin_check.json").read_text())["verdict"] == "SHA_DIFF"


def test_launching_finalb0_without_the_j0_pull_is_refused():
    env = {"SAR_S3_BUCKET": "fake-bucket", "AWS_REGION": "us-east-1"}
    with pytest.raises(r1kit.KitError, match=r"needs pulls into \['/work/j0/'\]"):
        r1kit.launch("finalb0", "finalb0-99", "HEAD", env=env, dry_run=True, now=1_800_000_000)


def test_final_paper_and_b0_expected_configs_load():
    pc = fs.load_paper_config(REPO / "config" / "r1" / "final_paper.json")
    assert pc["words_limit"] == 12000 and len(pc["figures"]) == 9 and len(set(pc["figures"])) == 9
    assert {"fig_star_origins", "fig_compare_years", "fig_comparison_pools"} <= set(pc["figures"])
    assert pc["rearchive"] == "2026-10-23_pre_r1_ledgers"
    # the date label the M ledgers are installed under: later than the tree's own ledgers, or repin stops
    # (LEDGER_DATE_NOT_LATER); J1b's RESULT OK date (2026-10-17) is earlier than the tree's 2026-10-23
    tree_date = json.loads((REPO / "config" / "r1" / "final_tree.json").read_text(encoding="utf-8"))["current"]["ledger_date"]
    assert isinstance(pc["ledger_date"], str) and pc["ledger_date"] > tree_date
    stages = set(_rows("final"))
    for d in pc["deliver"]:
        assert d["from"].split("/")[0] in stages, d
    assert len({d["name"] for d in pc["deliver"]}) == len(pc["deliver"])
    exp = fs.load_expected_b0(REPO / "config" / "r1" / "final_b0_expected.json")
    assert set(exp) == set(fs.B0_SECTIONS) | {"output_paper_reference_only"}       # R7 #15: kept apart
    assert len(exp["output_paper_reference_only"]) == 6
    bad = {"schema": fs.B0_SCHEMA, **{k: [] for k in fs.B0_SECTIONS}}
    bad["output_paper"] = [{"path": "x.json", "what": "x", "owner": "N12"}]          # no reason
    with pytest.raises(ValueError):
        fs.load_expected_b0(bad)
    ok_row = {"path": "x.md", "sha256": "a" * 64, "what": "w", "owner": "F1", "reason": "r"}
    for row in ({**ok_row, "sha256": "A" * 64}, {**ok_row, "path": "../x.md"}, {**ok_row, "path": "/x.md"},
                {k: v for k, v in ok_row.items() if k != "reason"}, {**ok_row, "extra": 1}):
        with pytest.raises(ValueError):
            fs.load_expected_b0({"schema": fs.B0_SCHEMA, **{k: [] for k in fs.B0_SECTIONS},
                                 "output_paper_reference_only": [row]})
    assert fs.load_expected_b0({"schema": fs.B0_SCHEMA, **{k: [] for k in fs.B0_SECTIONS}})[
        "output_paper_reference_only"] == []
    with pytest.raises(ValueError):
        fs.load_paper_config({**json.loads((REPO / "config/r1/final_paper.json").read_text()), "words_limit": "12000"})


# ---- canon layout --------------------------------------------------------------------------------
def _layout():
    return json.loads((REPO / "config" / "r1" / "canon_layout.json").read_text(encoding="utf-8"))


def test_canon_layout_covers_every_canon_read_and_carries_october_files():
    lay = _layout()
    assert lay["schema"] == "sar.r1.layout.v1"
    dests = [r["dest"] for r in lay["rows"]]
    for i, d in enumerate(dests):
        p = pathlib.PurePosixPath(d)
        assert p.parts[0] in canon.KEYS and not p.is_absolute() and ".." not in p.parts, d
        for e in dests[i + 1:]:
            q = pathlib.PurePosixPath(e)
            assert p != q and p not in q.parents and q not in p.parents, (d, e)
    for r in lay["rows"]:
        f = r["from"]
        if "repo" in f:
            # every repo source exists (a missing one would stop the final job's canon stage: MISSING_FILE)
            assert set(f) == {"repo"} and ".." not in f["repo"].split("/") and not f["repo"].startswith("/"), r
            assert (REPO / f["repo"]).is_file(), r
        else:
            assert f["job"] in ("j1a", "j1b") and rs.TOKEN.match(f["token"]) and rs.NAME.match(f["stage"]), r
    import r1_canon
    for row in r1_canon.read_tsv():
        if row["key"] not in canon.KEYS or row["kind"] == "optional":
            continue
        want = f"{row['key']}/{row['rel']}"
        hit = [r for r in lay["rows"] if want == r["dest"] or want.startswith(r["dest"] + "/")
               or fnmatch.fnmatchcase(r["dest"], want)]
        assert hit, f"canon_reads row {want} ({row['generator']}) has no canon_layout row"
        if row["kind"] == "carried":
            for r in hit:
                assert r["from"] == {"repo": f"{canon.OCTOBER[row['key']]}/{row['rel']}"}, r


def test_canon_layout_names_only_outputs_of_complete_upstream_tables():
    """Active once W3-FLIPS marks j1a/j1b complete: every stage row of the layout must name a stage of that
    table and one of its declared output tokens (W2-TJ1A / W2-TJ1B own those tables)."""
    for job in ("j1a", "j1b"):
        t = _table(job)
        if not t.get("complete"):
            continue
        outs = {s["name"]: set(s["outputs"]) for s in t["stages"]}
        for r in _layout()["rows"]:
            f = r["from"]
            if f.get("job") == job:
                assert f["stage"] in outs and f["token"] in outs[f["stage"]], r


def _toy_econ_products(d: pathlib.Path, em) -> dict:
    d.mkdir(parents=True)
    keys = {*em.FRAMES_ECON, *em.FRAMES_ECON_EXTRA, *em.AFAR_ECON, *em.PAIRS}
    out = {}
    for k in sorted(keys):
        (d / f"{k}.bin").write_text(f"{k}\n", encoding="utf-8")
        out[k] = d / f"{k}.bin"
    return out


def test_canon_layout_rels_are_published_by_their_producers(tmp_path):
    """M review #8: every J1a row of the canon layout names a file its producer publishes under STAGE_OUT,
    under October's basename and with the report keys the canon readers use (gaps_zenou: october.pairs_unified;
    ledger_carried: october.regeneration.roster_pool, october.accounting). Before the fix: star_set_econ_m.parquet,
    no frames_econ/build_report_econ920_2026-10.json, no yrebuild_chemmath/, and a star-id supplement row naming a
    file frames_econ920 never writes. Not gated on complete=true."""
    import econ920_m as em
    import chemmath_m as cm
    import r1_canon
    prods = _toy_econ_products(tmp_path / "chain", em)
    report = {"config": "M", "m": {"regeneration": {"roster_pool": {"source_sha256": "0" * 64, "rows_in": 3}},
                                   "accounting": {"rows": {"pre_y_frame_rows": 2}, "p2_rows": 1, "slim": {"rows": 4}}}}
    econ_out = tmp_path / "frames_econ920"
    em.freeze_m(econ_out, prods, report, staging=[])
    view = json.loads((econ_out / "frames_econ" / "build_report_econ920_2026-10.json").read_text(encoding="utf-8"))
    pairs = prods["pairs"].read_bytes()
    import hashlib                                                              # noqa: PLC0415
    assert view["october"]["pairs_unified"] == {"sha256": hashlib.sha256(pairs).hexdigest(), "bytes": len(pairs)}
    assert view["october"]["regeneration"]["roster_pool"]["rows_in"] == 3
    assert view["october"]["accounting"]["rows"]["pre_y_frame_rows"] == 2
    assert (econ_out / "frames_econ" / "star_set_econ_cal2026-10.parquet").is_file()
    assert "frames_econ/build_report_econ920_2026-10.json" in (econ_out / "frames_econ" / "MANIFEST.sha256").read_text()
    assert json.loads((econ_out / em.BUILD_REPORT).read_text())["m"]["pairs_unified"] == view["october"]["pairs_unified"]
    cm_out = tmp_path / "frames_chemmath_m"
    p1 = {}
    for f in ("chemistry", "math_stats"):
        p1[f] = tmp_path / "p1" / f
        p1[f].mkdir(parents=True)
        (p1[f] / f"g_yrebuild_{f}.json").write_text(json.dumps({"swap": {"gold_new": {"transition": {}}}}))
    rec = cm.publish_yrebuild(p1, ("chemistry", "math_stats"), cm_out)
    assert set(rec) == {"chemistry", "math_stats"}
    with pytest.raises(cm.Stop) as e:
        cm.publish_yrebuild({"chemistry": tmp_path / "nowhere"}, ("chemistry",), tmp_path / "x")
    assert e.value.code == "YREBUILD_REPORT_MISSING"
    published = {"frames_econ920": {p.relative_to(econ_out).as_posix() for p in econ_out.rglob("*")},
                 "frames_chemmath_m": {p.relative_to(cm_out).as_posix() for p in cm_out.rglob("*")}
                 | {"frames_chemistry", "frames_math_stats"}}           # run_cal_frames_chemmath.freeze's dirs
    seen = 0
    for r in _layout()["rows"]:
        f = r["from"]
        if f.get("job") == "j1a" and f["stage"] in published:
            assert f["rel"] in published[f["stage"]], r
            seen += 1
    assert seen == 5                      # frames_econ, pairs_unified, frames_chemistry/_math_stats, yrebuild
    for row in r1_canon.read_tsv():                                   # the econ / y-rebuild files the readers open
        if row["key"] == "cal" and row["kind"] == "product":
            if row["rel"].startswith("frames_econ/"):
                assert (econ_out / row["rel"]).is_file(), row
            elif row["rel"].startswith("yrebuild_chemmath/"):
                assert (cm_out / row["rel"]).is_file(), row


def test_chemmath_m_build_report_carries_octobers_reader_keys(tmp_path):
    """M review #8: frames_<field>/build_report_<field>.json gives ledger_carried october.inpost.spells and
    ledger_main / ledger_carried October's new-side accounting counts, on this run's products."""
    import chemmath_m as cm
    import pyarrow as pa
    import pyarrow.parquet as pq
    f = "chemistry"
    rel = tmp_path / "relationships.csv"
    rel.write_text("pid,event_id,channel\nA1,E1,network\nA2,E1,both\nA2,E2,dept_only\n", encoding="utf-8")
    p1 = tmp_path / "p1.csv"
    p1.write_text("h\n1\n2\n3\n", encoding="utf-8")
    p2 = tmp_path / "p2.csv"
    p2.write_text("h\n1\n", encoding="utf-8")
    slim = tmp_path / "slim.parquet"
    pq.write_table(pa.table({"x": [1, 2, 3, 4, 5]}), slim)
    prod = {f"relationships_{f}.csv": rel, f"p1_frame_{f}.csv": p1, f"p2_becoming_{f}.csv": p2,
            f"p3_slim_{f}.parquet": slim}
    filt = {"report": {"spells": {"roster_sha256": "ab" * 32, "roster_rows": 2}}}
    F = {"inpost": {"relations_by_class": {"kept": 3}}, "accounting": {"rows_p1": 3}}
    cm.canon_schema(f, prod, filt, F)
    assert F["october"]["inpost"]["spells"]["roster_sha256"] == "ab" * 32
    assert F["october"]["inpost"]["relations_by_class"] == {"kept": 3}
    acc = F["accounting"]
    assert acc["relationships"] == {"relations_new": 3, "by_channel_new": {"network": 1, "both": 1, "dept_only": 1},
                                    "persons_new": 2, "events_new": 2}
    assert acc["p1_frame"]["rows_new"] == 3 and acc["p2_becoming"]["rows_new"] == 1
    assert acc["slim"]["slim"]["rows"] == 5 and acc["rows_p1"] == 3      # M's own keys stay


def test_econ_m_accounting_carries_octobers_reader_keys(tmp_path):
    """M review #8: the econ build report's accounting carries October's relationships / p2_rows / slim keys that
    ledger_main and ledger_carried read, counted on this run's products."""
    import econ920_m as em
    rel = tmp_path / "relationships.csv"
    rel.write_text("pid,event_id,channel\nA1,E1,network\nA2,E1,both\nA3,E2,dept_only\nA4,E2,dept_only\n",
                   encoding="utf-8")
    p2 = tmp_path / "p2.csv"
    p2.write_text("h\n1\n2\n", encoding="utf-8")
    pairs = tmp_path / "pairs.csv"
    pairs.write_text("h\n" + "x\n" * 7, encoding="utf-8")
    ub = {"relationships": {"dept": 5}, "frame": {"persons": 4, "events": 2, "rows": 9}}
    keys = em.october_accounting_keys(rel=rel, ub=ub, p2_frame=p2, pairs=pairs, slim_stats={"rows": 11},
                                      relations_dropped=1)
    assert keys["relationships"]["after_post_filter_total"] == 4
    assert keys["relationships"]["after_post_filter_by_channel"] == {"network": 1, "both": 1, "dept_only": 2}
    assert keys["relationships"]["union_output_by_channel"] == {"dept": 5}
    assert keys["relationships"]["relations_dropped_incumbent_is_star_r1"] == 1
    assert (keys["p2_rows"], keys["pairs_rows"], keys["slim"]) == (2, 7, {"rows": 11})


# ---- canon assembly (toy stage set; restore_upstream.py and r1_canon.py run for real) ------------------
@pytest.fixture
def toy_canon(tmp_path, monkeypatch):
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")
    monkeypatch.setattr(fs, "canon_switches", lambda config, repo: {"p_full_precision": True, "dose_mode": True})
    sets = tmp_path / "j1b"
    prod = sets / "s1" / "files" / "work" / "prod" / "s1"
    (prod / "x").mkdir(parents=True)
    (prod / "x" / "a.csv").write_text("a,b\n1,2\n")
    (prod / "x" / "b.csv").write_text("c\n3\n")
    (sets / "s1.done.json").write_text(json.dumps({"outputs": {"work:prod/s1": rs.digest_of(prod)}}))
    layout = tmp_path / "layout.json"
    layout.write_text(json.dumps({"schema": "sar.r1.layout.v1", "rows": [
        {"dest": "frames", "from": {"job": "j1b", "stage": "s1", "token": "work:prod/s1", "rel": "x"}},
        {"dest": "paper_inputs/attrition.csv", "from": {"repo": "data/paper_inputs/attrition.csv"}}]}))
    tsv = tmp_path / "reads.tsv"
    tsv.write_text("generator\tkey\trel\tkind\treason\n"
                   "g.py\tframes\ta.csv\tproduct\ttoy product\n"
                   "g.py\tframes\t*.csv\tproduct\ttoy products\n"
                   "g.py\tpaper_inputs\tattrition.csv\tcarried\ttoy carried\n")
    dest = tmp_path / "canon_m"
    paths = tmp_path / "paths_m.yaml"
    paths.write_text(f'cal: "{dest}/cal"\nframes: "{dest}/frames"\n')
    argv = ["canon", "--mode", "M", "--repo", str(REPO), "--stages", f"j1b={sets}", "--layout", str(layout),
            "--config", str(tmp_path / "M.json"), "--paths", str(paths), "--dest", str(dest),
            "--bin", str(tmp_path / "bin"), "--tsv", str(tsv), "--out", str(tmp_path / "out")]
    return {"argv": argv, "sets": sets, "prod": prod, "dest": dest, "out": tmp_path / "out", "tsv": tsv}


def test_canon_assembly_verifies_upstream_digests(toy_canon):
    t = toy_canon
    assert fs.main(t["argv"]) == 0
    dest = t["dest"]
    assert (dest / "frames" / "a.csv").read_text() == "a,b\n1,2\n"
    meta = json.loads((dest / "CANON.json").read_text())
    canon._check_meta(meta, dest / "CANON.json")
    assert meta["switches"] == {"p_full_precision": True, "dose_mode": True} and meta["prefix"] == canon.DEFAULT_PREFIX
    assert "frames/a.csv" in (dest / "frames" / "MANIFEST.sha256").read_text()
    r = subprocess.run([PY, str(REPO / "tools" / "verify_manifest.py"), str(dest / "MANIFEST.sha256")],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "MANIFEST_OK" in r.stdout, r.stdout
    rep = json.loads((t["out"] / "canon.json").read_text())
    assert rep["result"] == "OK" and rep["code"] == "OK" and rep["counts"]["files"] >= 3
    assert rs.name_free(rep) == rep


@pytest.mark.parametrize("case,code", [("tamper", "DIGEST_MISMATCH"), ("rel", "MISSING_FILE"),
                                       ("marker", "MISSING_MARKER"), ("read", "CANON_FAIL")])
def test_canon_assembly_refuses_a_tampered_file_a_missing_row_and_a_missing_marker(toy_canon, case, code):
    t = toy_canon
    if case == "tamper":
        (t["prod"] / "x" / "a.csv").write_text("a,b\n1,999\n")
    elif case == "rel":
        lay = json.loads(pathlib.Path(t["argv"][t["argv"].index("--layout") + 1]).read_text())
        lay["rows"][0]["from"]["rel"] = "y"
        pathlib.Path(t["argv"][t["argv"].index("--layout") + 1]).write_text(json.dumps(lay))
    elif case == "marker":
        (t["sets"] / "s1.done.json").unlink()
    else:
        t["tsv"].write_text(t["tsv"].read_text() + "g.py\tframes\tmissing.parquet\tproduct\tabsent product\n")
    assert fs.main(t["argv"]) == 1
    rep = json.loads((t["out"] / "canon.json").read_text())
    assert rep["result"] == "STOP" and rep["code"] == code
    log = (t["out"] / "canon.log").read_text()
    if code != "CANON_FAIL":
        assert rep["stage"] == "s1"
        if code != "MISSING_MARKER":
            assert "work:prod/s1" in log
        assert not (t["dest"] / "CANON.json").exists()
    else:
        assert "missing.parquet" in log


# ---- pure helpers --------------------------------------------------------------------------------
MAIN = "\n".join([
    r"\documentclass{article}",
    r"% Toggle to \newcommand{\BOR}[1]{#1} to flatten.",
    r"\newcommand{\BOR}[1]{{\color{blue}#1}}",
    r"\begin{document}",
    r"\pagestyle{empty}",
    r"The effect is $-$0.133 per year.",
    r"\input{sections/sec2}",
    r"\end{document}", ""])
CLEAN = "\n".join([
    r"\documentclass{article}",
    r"\newcommand{\BOR}[1]{#1}",
    r"\begin{document}",
    r"The effect is $-$0.133 per year.",
    r"\section*{Acknowledgements}",
    r"I thank my supervisor.",
    r"\input{sections/sec2}",
    r"\end{document}", ""])


def test_sync_clean_carries_main_edits_and_keeps_the_october_difference():
    new_main = MAIN.replace("0.133", "0.128")
    new_clean = fs.sync_clean(MAIN, new_main, CLEAN)
    assert new_clean == CLEAN.replace("0.133", "0.128")
    assert fs.diff_signature(new_main, new_clean) == fs.diff_signature(MAIN, CLEAN)
    assert fs.sync_clean(MAIN, MAIN, CLEAN) == CLEAN
    # a line inserted between two shared, adjacent lines is carried at the same place
    ins = MAIN.replace(r"\input{sections/sec2}", r"\input{sections/sec2}" + "\nNew sentence.")
    assert r"\input{sections/sec2}" + "\nNew sentence.\n" + r"\end{document}" in fs.sync_clean(MAIN, ins, CLEAN)
    # an insertion where main_clean.tex has its own lines (the acknowledgements) is ambiguous: stop
    amb = MAIN.replace(r"\input{sections/sec2}", "Between.\n" + r"\input{sections/sec2}")
    with pytest.raises(fs.SyncStop):
        fs.sync_clean(MAIN, amb, CLEAN)
    # an edit on a line where main.tex and main_clean.tex differ stops, with a reason
    bad = MAIN.replace(r"{{\color{blue}#1}}", r"{{\color{red}#1}}")
    with pytest.raises(fs.SyncStop, match="differ"):
        fs.sync_clean(MAIN, bad, CLEAN)


def test_scan_log_flags_errors_undefined_references_and_citations():
    clean = "This is pdfTeX\nOutput written on main.pdf (30 pages).\n"
    r = fs.scan_log(clean)
    assert r["ok"] and r["errors"] == r["undefined_refs"] == r["undefined_cites"] == 0
    log = ("! Undefined control sequence.\nl.12 \\foo\n"
           "LaTeX Warning: Reference `fig:p1' on page 3 undefined on input line 40.\n"
           "LaTeX Warning: Citation `toyref2020' on page 4 undefined on input line 50.\n"
           "Package natbib Warning: Citation `azoulay2010' on page 5 undefined on input line 51.\n")
    r = fs.scan_log(log)
    assert not r["ok"] and r["errors"] == 1 and r["undefined_refs"] == 1 and r["undefined_cites"] == 2
    assert fs.scan_log("LaTeX Warning: There were undefined references.\n")["undefined_refs"] == 1
    # TeX hard-wraps log lines at 79 characters
    wrapped = "LaTeX Warning: Reference `sec:a_very_long_label_name_that_wraps_the_log_line_at" + \
              "\n_sixty' on page 3 undefined on input line 40.\n"
    assert len(wrapped.split("\n")[0]) == 79
    assert fs.scan_log(wrapped)["undefined_refs"] == 1


def test_parse_words_reads_the_total_and_the_gate():
    w = fs.parse_words("sec 1  400\nTOTAL 12001  (limit 12,000; margin -1)\n")
    assert w == {"total": 12001, "limit": 12000, "margin": -1, "over": True}
    assert fs.parse_words("TOTAL 11990  (limit 12,000; margin +10)\n")["over"] is False
    for bad in ("", "TOTAL abc", "TOTAL 100  (limit 12,000; margin +5)\n"):
        with pytest.raises(ValueError):
            fs.parse_words(bad)


def test_parse_hits_counts_draft_text_phrases():
    assert fs.parse_hits("PASS: no process-note, retired or placeholder text in main_clean.pdf\n") == {}
    out = ("FAIL: 3 hit(s) in main_clean.pdf\n  p.3  'to be checked'  ...a b to be checked c...\n"
           "  p.9  'to be checked'  ...x to be checked y...\n  p.9  '[bracket placeholder]'  ...[TBD]...\n")
    assert fs.parse_hits(out) == {"to be checked": 2, "[bracket placeholder]": 1}
    with pytest.raises(ValueError):
        fs.parse_hits("FAIL: 2 hit(s) in x.pdf\n  p.1  'a'  ...a...\n")


def test_printed_entries_map_pin_provenance_to_number_diff_ledgers():
    keys = ["p3afar:econ.ate_pp", "carried:n_events", "main:x[0].y", "zenou:arrival",
            "switchers_p1p2:cells[2]", "gold_p1_union:[0].est", "zero:share"]
    assert fs.printed_entries(keys) == ["gaps_switchers_p1p2\tcells[2]", "gaps_zenou\tarrival",
                                        "gaps_zero_dose\tshare", "main\tn_events", "main\tx[0].y",
                                        "p3afar\tecon.ate_pp"]


def test_scratch_paths_keep_the_canon_keys_and_pin_everything_else_to_the_clone(tmp_path):
    src = tmp_path / "p.yaml"
    src.write_text('repo_root: "."\nframes: data/frames\ncal: "/work/canon_m/cal"\noutput: output\n'
                   'fwci: data/fwci\nlegacy_thesis: "/data/legacy/t"\n')
    repo = tmp_path / "clone"
    got = fs.scratch_paths(src, repo)
    assert got["repo_root"] == "." and got["frames"] == "data/frames" and got["cal"] == "/work/canon_m/cal"
    assert got["output"] == str((repo / "output").resolve()) and got["fwci"] == str((repo / "data/fwci").resolve())
    assert got["legacy_thesis"] == "/data/legacy/t"


def test_b0_tree_diff_excuses_only_the_rearchived_ledgers(tmp_path):
    cur, scr = tmp_path / "cur", tmp_path / "scr"
    for root in (cur, scr):
        (root / "sections").mkdir(parents=True)
        (root / "sections" / "s.tex").write_text("x 0.235\n")
        (root / "data_numbers_2026-10-23.json").write_text("{}\n")
    (cur / "data_numbers_2026-08-16.json").write_text("old\n")
    (scr / "_archive" / "A").mkdir(parents=True)
    (scr / "_archive" / "A" / "data_numbers_2026-10-23.json").write_text("{}\n")
    (scr / "_archive" / "A" / "data_numbers_2026-08-16.json").write_text("old\n")
    assert fs.b0_tree_diff(cur, scr, "A") == []
    (scr / "sections" / "s.tex").write_text("x 0.236\n")
    (scr / "new.tex").write_text("n\n")
    (scr / "_archive" / "A" / "data_numbers_2026-08-16.json").write_text("changed\n")
    assert fs.b0_tree_diff(cur, scr, "A") == ["_archive/A/data_numbers_2026-08-16.json", "new.tex", "sections/s.tex"]
    assert fs.dir_diff(cur / "sections", scr / "sections") == ["s.tex"]


# ---- review R7 #13: matplotlib's wall-clock CreationDate is masked in the B0 comparison ---------------
def _toy_pdf(date=None, stream=b"0 0 m 10 10 l S"):
    """A matplotlib-shaped PDF: objects, then the Info object last, xref, trailer without /ID, startxref."""
    head = b"%PDF-1.4\n%\xac\xdc \xc2\xcd\n"
    obj1 = b"1 0 obj\n<< /Length %d >>\nstream\n%s\nendstream\nendobj\n" % (len(stream), stream)
    info = b"2 0 obj\n<< /Producer (Matplotlib pdf backend v3.11.1)" + \
        (b" /CreationDate (D:" + date + b")" if date else b"") + b" >>\nendobj\n"
    o1, o2 = len(head), len(head) + len(obj1)
    xref = len(head) + len(obj1) + len(info)
    tail = (b"xref\n0 3\n0000000000 65535 f \n%010d 00000 n \n%010d 00000 n \n" % (o1, o2)
            + b"trailer\n<< /Size 3 /Info 2 0 R >>\nstartxref\n%d\n%%%%EOF\n" % xref)
    return head + obj1 + info + tail


MAC = b"20261001143641+11'00'"
EC2 = b"20261017020304Z"


def _pdf_trees(tmp_path, a, b, name="fig_hops.pdf"):
    ta, tb = tmp_path / "new", tmp_path / "ref"
    for t, data in ((ta, a), (tb, b)):
        (t / "figures").mkdir(parents=True, exist_ok=True)
        (t / "figures" / name).write_bytes(data)
    return ta, tb


def test_b0_comparison_masks_only_the_pdf_render_date(tmp_path):
    a, b = _toy_pdf(EC2), _toy_pdf(MAC)
    assert a != b and a.replace(EC2, MAC).rsplit(b"startxref", 1)[0] == b.rsplit(b"startxref", 1)[0]
    assert fs.same_file_bytes("x.pdf", a, b) == (True, True) and fs.same_file_bytes("x.pdf", b, b) == (True, False)
    new, ref = _pdf_trees(tmp_path, a, b)
    masked = []
    assert fs.dir_diff(new, ref, masked=masked) == [] and masked == ["figures/fig_hops.pdf"]
    masked = []
    assert fs.b0_tree_diff(ref, new, "A", masked=masked) == [] and masked == ["figures/fig_hops.pdf"]
    assert fs.dir_diff(new, ref) == []                         # the list is optional


@pytest.mark.parametrize("case", ["stream", "one_side", "tex", "json"])
def test_b0_comparison_still_reports_every_other_difference(tmp_path, case):
    if case == "stream":                                       # one byte of a drawn path
        a, b, name = _toy_pdf(EC2, stream=b"0 0 m 10 11 l S"), _toy_pdf(MAC), "fig_hops.pdf"
    elif case == "one_side":                                   # a date on one side only
        a, b, name = _toy_pdf(None), _toy_pdf(MAC), "fig_hops.pdf"
    else:                                                      # a non-PDF file with the same date string
        name = f"x.{case}"
        a, b = b"/CreationDate (D:" + EC2 + b")\n", b"/CreationDate (D:" + MAC + b")\n"
    new, ref = _pdf_trees(tmp_path, a, b, name)
    masked = []
    assert fs.dir_diff(new, ref, masked=masked) == [f"figures/{name}"] and masked == []
    assert fs.b0_tree_diff(ref, new, "A") == [f"figures/{name}"]


# ---- finalb0-02: EC2 (x86_64) against the October run (Mac, arm64): noise of the last digits ------------
def _png(px):
    import io
    from PIL import Image
    im = Image.new("RGBA", (4, 3), (10, 20, 30, 255))
    for xy, v in px.items():
        im.putpixel(xy, v)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _diag(v, key="max_abs_diff_effects", n=1):
    return json.dumps({"coef_check": {"pass": True, key: v, "n": n}}, indent=1).encode()


def test_noise_rule_takes_only_tolerance_level_diagnostics_and_one_level_pixels():
    assert fs.same_within_noise("g.json", _diag(4.8313946593e-09), _diag(4.8313946732e-09)) == "float_noise"
    assert fs.same_within_noise("g.json", _diag(4.8e-09, "ate"), _diag(4.9e-09, "ate")) is None     # other key
    assert fs.same_within_noise("g.json", _diag(2e-06), _diag(3e-06)) is None                      # above 1e-6
    assert fs.same_within_noise("g.json", _diag(1e-09), _diag(2e-09, n=2)) is None                 # n moved too
    base = _png({})
    assert fs.same_within_noise("f.png", base, _png({(1, 1): (11, 20, 30, 255)})) == "png_noise"
    assert fs.same_within_noise("f.png", base, _png({(1, 1): (12, 20, 30, 255)})) is None
    assert fs.same_within_noise("f.tex", b"a 1e-9\n", b"a 2e-9\n") is None


def test_the_b0_comparison_lists_noise_equal_files_only_when_asked(tmp_path):
    new, ref = tmp_path / "new", tmp_path / "ref"
    for d, v in ((new, 4.8313946732e-09), (ref, 4.8313946593e-09)):
        d.mkdir()
        (d / "gaps_switchers.json").write_bytes(_diag(v))
    noise = []
    assert fs.dir_diff(new, ref, noise=noise) == [] and noise == ["gaps_switchers.json (float_noise)"]
    assert fs.dir_diff(new, ref) == ["gaps_switchers.json"]                     # strict without the list
    noise = []
    assert fs.output_paper_diff(new, ref, [], noise=noise) == [] and len(noise) == 1
    noise = []
    assert fs.b0_tree_diff(ref, new, "A", noise=noise) == [] and len(noise) == 1


def test_noise_rule_masks_only_the_diagnostic_numbers(tmp_path):
    """Codex delta-2 #4: a JSON file is noise-equal only when its bytes are equal once the max_abs_diff*
    numbers are masked; a re-serialisation (whitespace, key order) stays a difference."""
    a, b = _diag(4.8313946593e-09), _diag(4.8313946732e-09)
    assert fs.same_within_noise("g.json", a, b) == "float_noise"
    assert fs.same_within_noise("g.json", a, json.dumps(json.loads(b)).encode()) is None      # whitespace
    assert fs.same_within_noise("g.json", a, json.dumps(json.loads(b), sort_keys=True, indent=1).encode()) is None
    assert fs.same_within_noise("g.json", b"{}", b"{ }") is None                            # nothing to mask


def test_archived_originals_and_reference_only_files_stay_exact(tmp_path):
    """Codex delta-2 #2-#3: an archived original is a copy (never noise-excused); a reference-only file the
    run writes must have the pinned bytes."""
    import hashlib
    cur, scr = tmp_path / "cur", tmp_path / "scr"
    (scr / "_archive" / "A").mkdir(parents=True)
    cur.mkdir()
    (cur / "g.json").write_bytes(_diag(4.8313946593e-09))
    (scr / "_archive" / "A" / "g.json").write_bytes(_diag(4.8313946732e-09))
    noise = []
    assert fs.b0_tree_diff(cur, scr, "A", noise=noise) == ["_archive/A/g.json"] and noise == []
    out, ref = tmp_path / "out", tmp_path / "ref"
    out.mkdir(), ref.mkdir()
    (ref / "fig_hops.png").write_bytes(_png({}))
    (out / "fig_hops.png").write_bytes(_png({(1, 1): (11, 20, 30, 255)}))
    pin = [{"path": "fig_hops.png", "sha256": hashlib.sha256((ref / "fig_hops.png").read_bytes()).hexdigest()}]
    noise = []
    assert fs.output_paper_diff(out, ref, pin, noise=noise) == ["fig_hops.png"]


def test_gate2_b0_reports_the_noise_equal_files_and_still_passes(b0_inputs):
    exp = fs.load_expected_b0(B0_EXPECTED)
    inp = dict(b0_inputs, noise_masked=["output_paper/gaps_switchers.json (float_noise)"])
    v, codes, det = fs.gate2(inp, "B0", exp)
    assert (v, codes) == ("B0_PASS", []) and det["noise_masked"] == inp["noise_masked"]


# ---- review R7 #15: snapshot files no staged stage writes are pinned reference-only ---------------------
REF_ONLY_FILES = {"LEDGER_DIFF_main_funnel.md": b"# diff\n", "SYNC_PLAN_2026-10.md": b"# plan\n",
                  "fig_hops.png": b"\x89PNG toy\n"}


def _ref_only_trees(tmp_path):
    import hashlib
    out, ref = tmp_path / "out", tmp_path / "ref"
    for t in (out, ref):
        t.mkdir()
        (t / "fig_p1.pdf").write_bytes(b"%PDF-1.4 same\n")
    for name, data in REF_ONLY_FILES.items():
        (ref / name).write_bytes(data)
    pins = [{"path": n, "sha256": hashlib.sha256(d).hexdigest(), "what": "w", "owner": "F1", "reason": "r"}
            for n, d in REF_ONLY_FILES.items()]
    return out, ref, pins


@pytest.mark.parametrize("case", ["pass", "altered", "absent", "generated_missing", "extra", "present_in_out"])
def test_output_paper_diff_excuses_only_the_pinned_reference_only_files(tmp_path, b0_inputs, case):
    out, ref, pins = _ref_only_trees(tmp_path)
    if case == "altered":
        (ref / "SYNC_PLAN_2026-10.md").write_bytes(b"# plan, edited\n")
    elif case == "absent":
        (ref / "fig_hops.png").unlink()
    elif case == "generated_missing":
        (out / "fig_p1.pdf").unlink()
    elif case == "extra":
        (out / "data_numbers_new.json").write_bytes(b"{}\n")
    elif case == "present_in_out":                 # a run that does write it must write the same bytes
        (out / "fig_hops.png").write_bytes(b"\x89PNG other\n")
    got = fs.output_paper_diff(out, ref, pins)
    assert "LEDGER_DIFF_main_funnel.md" in fs.dir_diff(out, ref)          # a plain dir_diff lists them
    want = {"pass": [], "altered": ["SYNC_PLAN_2026-10.md"], "absent": ["fig_hops.png"],
            "generated_missing": ["fig_p1.pdf"], "extra": ["data_numbers_new.json"],
            "present_in_out": ["fig_hops.png"]}[case]
    assert got == want, got
    exp = fs.load_expected_b0(B0_EXPECTED)
    declared = sorted(r["path"] for r in exp["output_paper"])
    v, codes, _ = fs.gate2(dict(b0_inputs, output_paper_diff=sorted(set(got) | set(declared))), "B0", exp)
    assert (v == "B0_PASS") is (case == "pass") and (("B0_OUTPUT_DIFF" in codes) is (case != "pass")), codes


def test_gate2_b0_reports_the_masked_pdfs_and_still_passes(b0_inputs):
    exp = fs.load_expected_b0(B0_EXPECTED)
    inp = dict(b0_inputs, pdf_date_masked=["output_paper/fig_hops.pdf", "scratch/figures/fig_hops.pdf"])
    v, codes, det = fs.gate2(inp, "B0", exp)
    assert (v, codes) == ("B0_PASS", []) and det["pdf_date_masked"] == inp["pdf_date_masked"]
    rep = fs.final_report("B0", v, codes, det, {"pdf_date_masked": len(det["pdf_date_masked"])})
    assert rep["counts"]["pdf_date_masked"] == 2


# ---- review R7 #14: the October provenance strings carry the Mac repo root; B0 maps it, nothing else ------
def _rooted_ledger(root: str, n: int, value="0.396", source="cal2026-10 ledger"):
    prov = {f"k{i}": f"{root}/data/frames/p{i}.csv" for i in range(n)}
    return json.dumps({"_source": source, "econ_rate": float(value), "_provenance": prov}, indent=1) + "\n"


WORK = "/work/repo"


def _rooted_trees(tmp_path, ref_text, new_text, name="data_numbers_main.json"):
    ref, new = tmp_path / "ref", tmp_path / "new"
    for t, text in ((ref, ref_text), (new, new_text)):
        t.mkdir(parents=True, exist_ok=True)
        (t / name).write_text(text, encoding="utf-8")
    return ref, new


def test_b0_rooted_ledgers_equal_after_the_root_map(tmp_path):
    assert fs.OCTOBER_REPO_ROOT.endswith("/star_arrivals_replication")   # the checkout beside legacy_thesis
    assert fs.B0_ROOTED == {"data_numbers_main.json": 30, "gaps_zenou.json": 13, "gaps_zero_dose.json": 3}
    assert fs.b0_rooted_scratch("2026-10-23") == {"data_numbers_2026-10-23.json": 30,
                                                  "data_numbers_2026-10-23_gaps_zenou.json": 13,
                                                  "data_numbers_2026-10-23_gaps_zero_dose.json": 3}
    ref, new = _rooted_trees(tmp_path, _rooted_ledger(fs.OCTOBER_REPO_ROOT, 3), _rooted_ledger(WORK, 3))
    assert fs.rooted_equal((ref / "data_numbers_main.json").read_bytes(),
                           (new / "data_numbers_main.json").read_bytes(), WORK, 3)
    assert fs.dir_diff(new, ref, rooted={"data_numbers_main.json": 3}, new_root=WORK) == []
    assert fs.dir_diff(new, ref) == ["data_numbers_main.json"]                 # no map: a difference
    # the scratch tree's dated copy against the current tree's
    cur, scr = _rooted_trees(tmp_path / "t", _rooted_ledger(fs.OCTOBER_REPO_ROOT, 3), _rooted_ledger(WORK, 3),
                             "data_numbers_2026-10-23.json")
    assert fs.b0_tree_diff(cur, scr, "A", rooted={"data_numbers_2026-10-23.json": 3}, new_root=WORK) == []
    # on the Mac the map is the identity
    ref2, new2 = _rooted_trees(tmp_path / "mac", _rooted_ledger(fs.OCTOBER_REPO_ROOT, 3),
                               _rooted_ledger(fs.OCTOBER_REPO_ROOT, 3))
    assert fs.dir_diff(new2, ref2, rooted={"data_numbers_main.json": 3}, new_root=fs.OCTOBER_REPO_ROOT) == []


@pytest.mark.parametrize("case", ["value", "source", "count", "other_root", "not_rooted", "relative_root"])
def test_b0_root_map_keeps_every_other_difference(tmp_path, case):
    ref_text, new_text, rooted, root = _rooted_ledger(fs.OCTOBER_REPO_ROOT, 3), _rooted_ledger(WORK, 3), 3, WORK
    if case == "value":
        new_text = _rooted_ledger(WORK, 3, value="0.397")
    elif case == "source":
        new_text = _rooted_ledger(WORK, 3, source="cal2026-10 ledger.")
    elif case == "count":
        rooted = 2                                              # the reference holds 3, the pin says 2
    elif case == "other_root":
        new_text = _rooted_ledger(WORK, 3).replace(f"{WORK}/data/frames/p0.csv", "/tmp/x/data/frames/p0.csv")
    elif case == "relative_root":
        root = "work/repo"
    ref, new = _rooted_trees(tmp_path, ref_text, new_text)
    pins = {} if case == "not_rooted" else {"data_numbers_main.json": rooted}
    assert fs.dir_diff(new, ref, rooted=pins, new_root=root) == ["data_numbers_main.json"]


def test_b0_root_map_never_excuses_an_archived_copy(tmp_path):
    cur, scr = tmp_path / "cur", tmp_path / "scr"
    cur.mkdir()
    (cur / "data_numbers_2026-10-23.json").write_text(_rooted_ledger(fs.OCTOBER_REPO_ROOT, 3))
    (scr / "_archive" / "A").mkdir(parents=True)
    (scr / "_archive" / "A" / "data_numbers_2026-10-23.json").write_text(_rooted_ledger(WORK, 3))
    (scr / "data_numbers_2026-10-23.json").write_text(_rooted_ledger(WORK, 3))
    got = fs.b0_tree_diff(cur, scr, "A", rooted={"data_numbers_2026-10-23.json": 3}, new_root=WORK)
    assert got == ["_archive/A/data_numbers_2026-10-23.json"]


def test_the_pdf_date_masking_is_registered():
    reg = (REPO / "pipeline" / "NOT_REPRODUCIBLE.md").read_text(encoding="utf-8")
    rows = [ln for ln in reg.splitlines() if ln.startswith("| ") and "CreationDate" in ln]
    assert len(rows) == 1 and "NOT BYTE-REPRODUCIBLE" in rows[0] and "[package]" not in rows[0]
    for fig in ("fig_dose_distribution", "fig_exposure_population", "fig_hops", "fig_p1", "fig_p2", "fig_p3_afar"):
        assert fig in reg.split("CreationDate", 1)[1], fig


def _repin_install_argvs(tmp_path, monkeypatch, mode):
    """The install.py ledgers argv cmd_repin builds (every subprocess faked; the toy stops at REPLACE_FAIL)."""
    import argparse
    calls = []

    def fake_run(argv, *, log=None, cwd=None, env=None):
        calls.append([str(x) for x in argv])
        return 0, ""
    monkeypatch.setattr(fs, "_run", fake_run)
    tree = tmp_path / "tree"
    (tree / "tables").mkdir(parents=True)
    (tree / "tables" / "t.tex").write_text("x\n")
    rec = tmp_path / "rec.json"
    rec.write_text(json.dumps({"current": {"ledger_date": "2026-10-23"}}))
    pc = json.loads((REPO / "config" / "r1" / "final_paper.json").read_text(encoding="utf-8"))
    pc["ledger_date"] = "2027-01-05"
    paper = tmp_path / "paper.json"
    paper.write_text(json.dumps(pc))
    out = tmp_path / "out"
    out.mkdir()
    a = argparse.Namespace(mode=mode, repo=str(REPO), out=str(out), scratch=str(tmp_path / "scratch"), tree=str(tree),
                           paper=str(paper), record=str(rec), role="current", paths=str(tmp_path / "p.yaml"),
                           commit="c" * 40, out_dir=str(tmp_path / "od"), old_gold="g", new_gold="g")
    assert fs.cmd_repin(a) == 1
    assert json.loads((out / "repin.json").read_text())["code"] == "REPLACE_FAIL"
    return [c for c in calls if len(c) > 2 and c[1].endswith("install.py") and c[2] == "ledgers"]


def test_b0_repin_installs_the_ledgers_under_the_trees_own_date_with_keep_date(tmp_path, monkeypatch):
    """review R7 #2: finalb0 repins under the tree's own ledger date, which install.py --rearchive alone refuses
    (not later); --keep-date archives the originals first and keeps their _source. M is unchanged."""
    (b0,) = _repin_install_argvs(tmp_path / "b0", monkeypatch, "B0")
    (m,) = _repin_install_argvs(tmp_path / "m", monkeypatch, "M")
    assert "--keep-date" in b0 and "--keep-date" not in m
    assert b0[b0.index("--date") + 1] == "2026-10-23" and m[m.index("--date") + 1] == "2027-01-05"
    assert m[3:] == ["--thesis-root", str(tmp_path / "m" / "scratch" / "tree"), "--draft-root", "none", "--out-dir",
                     str(tmp_path / "m" / "od"), "--date", "2027-01-05", "--rearchive", "2026-10-23_pre_r1_ledgers",
                     "--write"]
    assert [x for x in b0 if x != "--keep-date"][3:] == \
        [x.replace("/m/", "/b0/").replace("2027-01-05", "2026-10-23") for x in m[3:]]


# ---- gate 2 --------------------------------------------------------------------------------------
def _chk(section, name, ok=False, file="", retired=False):
    return {"section": section, "name": name, "ok": ok, "retired": retired, "unrep": False, "file": file, "detail": ""}


@pytest.fixture
def m_inputs():
    pre = [_chk("A", "[p3afar] econ"), _chk("A", "[main] econ_events", ok=True),
           _chk("A", "[carried] chem_events"),
           _chk("B", "tab_main_results.tex"), _chk("B", "tab_disciplines.tex", ok=True),
           _chk("C", "gaps_zenou.json flags", ok=True),
           _chk("D", "p3 econ ATE 0.044pp", file="sections/sec4_p3.tex"),
           _chk("D", "p1 chem ATE $-$0.02", file="sections/sec4_p1.tex"),
           _chk("D", "p2 math share 0.31", file="sections/sec4_p2.tex"),
           _chk("D", "tab_main_results econ P1 cell", file="tables/tab_main_results.tex"),
           _chk("D", "old Zénou pin", ok=True, retired=True)]
    post = [dict(c, ok=True) for c in pre if not c["retired"]]
    for c in post:
        c["name"] = {"p3 econ ATE 0.044pp": "p3 econ ATE 0.039pp"}.get(c["name"], c["name"])
    return {
        "pre": pre, "post": post,
        "number_diff": [{"ledger": "p3afar", "key": "econ.ate_pp", "status": "changed"},
                        {"ledger": "main", "key": "chem_events", "status": "changed"},
                        {"ledger": "main", "key": "econ_events", "status": "unchanged"},
                        {"ledger": "gaps_zenou", "key": "arrival", "status": "changed"}],
        "changed_tables": ["tab_main_results.tex"],
        "edits": [{"pin": "p3 econ ATE 0.044pp", "file": "sections/sec4_p3.tex", "status": "EDIT"},
                  # M2: a SIGN_CHANGED edit goes to the author (PRINTED_SIGN_CHANGED; its own test below)
                  {"pin": "p1 chem ATE $-$0.02", "file": "sections/sec4_p1.tex", "status": "EDIT"},
                  {"pin": "p2 math share 0.31", "file": "sections/sec4_p2.tex", "status": "DECIMALS_CHANGED"},
                  {"pin": None, "file": "sections/sec2_data.tex", "status": "EDIT"},
                  {"pin": "p1 econ n 113", "file": "sections/sec4_p1.tex", "status": "ALREADY_NEW"}],
        "renamed": {"p3 econ ATE 0.044pp": "p3 econ ATE 0.039pp"},
        "bor_equal": True, "custody_ok": True, "canon_ok": True,
        "compile": {t: {"ok": True} for t in fs.COMPILE_TARGETS},
        "draft_hits": {"october": {"to be checked": 1}, "new": {"to be checked": 1}},
        "words": {"october": 11980, "new": 11990, "reference": 11980}, "words_limit": 12000,
        "reports_missing": [], "deliverables_missing": [], "pack_ok": True, "main_clean_invariant": True,
        "numbers_rc": 0,
        "red": {"build_ok": True, "verify_ok": True, "reference_equal": True, "red_runs": ["0.039"]},
        "note_checks": [NOTE_OK],
    }


NOTE_OK = {"table": "tab:robustness", "claim": "the t-statistic version passes for chemistry Panel 1", "holds": True,
           "detail": "p1_chemistry 0.031"}
NOTE_FALSE = {"table": "tab:robustness", "claim": "the shuffled p is ... for mathematics in Panel 2 (now below 0.05)",
              "holds": False, "detail": "p2_math_stats 0.100"}


def test_gate2_pending_author_on_false_note_claims(m_inputs):
    """review R7 #16: a table-note claim the generator flags (never rewords) goes to the author."""
    v, codes, det = fs.gate2(dict(m_inputs, note_checks=[NOTE_OK, NOTE_FALSE]), "M", None)
    assert (v, codes) == ("PENDING_AUTHOR", ["NOTE_CLAIMS_FALSE"]), det
    assert det["note_flags"] == [{k: NOTE_FALSE[k] for k in ("table", "claim", "detail")}]
    assert fs.final_report("M", v, codes, det)["counts"]["note_flags"] == 1
    assert fs.gate2(m_inputs, "M", None)[:2] == ("PASS", [])
    for bad in (None, [], [{"table": "t", "claim": "c", "holds": "yes", "detail": "d"}]):
        v, codes, _ = fs.gate2(dict(m_inputs, note_checks=bad), "M", None)
        assert v == "GATE2_FAIL" and "REPORT_MISSING" in codes, bad


def test_gate2_b0_fails_on_a_flagged_note(b0_inputs):
    exp = fs.load_expected_b0(B0_EXPECTED)
    assert fs.gate2(b0_inputs, "B0", exp)[:2] == ("B0_PASS", [])
    v, codes, det = fs.gate2(dict(b0_inputs, note_checks=[NOTE_OK, NOTE_FALSE]), "B0", exp)
    assert v == "B0_FAIL" and "B0_NOTE_FLAG" in codes and len(det["note_flags"]) == 1
    v, codes, _ = fs.gate2(dict(b0_inputs, note_checks=None), "B0", exp)
    assert v == "B0_FAIL" and "REPORT_MISSING" in codes


def test_gate2_stage_reads_and_delivers_the_note_checks(tmp_path, monkeypatch):
    """_collect reads output_paper/draft_2026_09_13/NOTE_CHECKS.json; cmd_gate2 puts the flags into
    change_facts.json and delivers the file as note_checks.json; without the file: REPORT_MISSING."""
    import argparse
    monkeypatch.setattr(fs, "_run", lambda argv, **kw: (1, ""))          # no packer here: PACK_FAIL, fine
    prod, op = tmp_path / "prod", tmp_path / "output_paper"
    (op / "draft_2026_09_13").mkdir(parents=True)
    (op / "draft_2026_09_13" / "NOTE_CHECKS.json").write_text(json.dumps([NOTE_OK, NOTE_FALSE]))
    prod.mkdir()
    a = argparse.Namespace(mode="M", repo=str(REPO), paper=str(REPO / "config" / "r1" / "final_paper.json"),
                           expected_b0=str(REPO / "config" / "r1" / "final_b0_expected.json"), prod=str(prod),
                           output_paper=str(op), ref_output_paper=str(tmp_path / "ref"),
                           tree_current=str(tmp_path / "cur"), scratch=str(tmp_path / "scr"),
                           final_dir=str(tmp_path / "final"), out=str(tmp_path / "out"))
    (tmp_path / "out").mkdir()
    inp = fs._collect(a, "M")
    assert inp["note_checks"] == [NOTE_OK, NOTE_FALSE]
    assert "output_paper/draft_2026_09_13/NOTE_CHECKS.json" not in inp["reports_missing"]
    assert fs.cmd_gate2(a) == 1                                        # many reports absent in this toy
    facts = json.loads((tmp_path / "out" / "change_facts.json").read_text())
    assert facts["note_flags"] == [{k: NOTE_FALSE[k] for k in ("table", "claim", "detail")}]
    assert json.loads((tmp_path / "final" / "note_checks.json").read_text()) == [NOTE_OK, NOTE_FALSE]
    (op / "draft_2026_09_13" / "NOTE_CHECKS.json").unlink()
    assert "output_paper/draft_2026_09_13/NOTE_CHECKS.json" in fs._collect(a, "M")["reports_missing"]


def test_gate2_pass_when_pre_fails_are_exactly_the_changed_numbers(m_inputs):
    verdict, codes, det = fs.gate2(m_inputs, "M", None)
    assert (verdict, codes) == ("PASS", []), det
    assert det["sign_changed"] == []
    assert det["unexplained"] == det["missing"] == []


def test_gate2_fails_on_an_unexplained_fail_and_on_a_missing_fail(m_inputs):
    extra = dict(m_inputs, pre=m_inputs["pre"] + [_chk("D", "sec2 roster count 994", file="sections/sec2_data.tex")])
    v, codes, det = fs.gate2(extra, "M", None)
    assert v == "GATE2_FAIL" and "FAIL_SET_MISMATCH" in codes and det["unexplained"] == ["D:sec2 roster count 994"]
    lost = dict(m_inputs, edits=m_inputs["edits"] + [{"pin": "p2 econ ATE 0.27", "file": "sections/sec4_p2.tex",
                                                      "status": "EDIT"}])
    v, codes, det = fs.gate2(lost, "M", None)
    assert v == "GATE2_FAIL" and "FAIL_SET_MISMATCH" in codes and det["missing"] == ["D:p2 econ ATE 0.27"]
    nd = dict(m_inputs, number_diff=m_inputs["number_diff"] + [{"ledger": "p1p2", "key": "econ.ate", "status": "changed"}])
    v, codes, det = fs.gate2(nd, "M", None)
    assert v == "GATE2_FAIL" and det["missing"] == ["A:p1p2 econ"]
    tb = dict(m_inputs, changed_tables=["tab_main_results.tex", "tab_disciplines.tex"])
    v, codes, det = fs.gate2(tb, "M", None)
    assert v == "GATE2_FAIL" and det["missing"] == ["B:tab_disciplines.tex"]
    c = dict(m_inputs, pre=m_inputs["pre"] + [_chk("C", "fig pdf present")])
    assert "SECTION_C_FAIL" in fs.gate2(c, "M", None)[1]


def test_gate2_pending_author_on_refusals_sign_changes_and_words_over(m_inputs):
    ref = dict(m_inputs)
    ref["pre"] = m_inputs["pre"] + [_chk("D", "p3 chem p<0.001", file="sections/sec4_p3.tex")]
    ref["post"] = m_inputs["post"] + [_chk("D", "p3 chem p<0.001", file="sections/sec4_p3.tex")]
    ref["edits"] = m_inputs["edits"] + [{"pin": "p3 chem p<0.001", "file": "sections/sec4_p3.tex", "status": "NEEDS_MANUAL",
                                        "reason": "printed threshold no longer holds"}]
    v, codes, det = fs.gate2(ref, "M", None)
    assert (v, codes) == ("PENDING_AUTHOR", ["REFUSED_SPANS"])
    assert [e["pin"] for e in det["refused"]] == ["p3 chem p<0.001"]
    words = dict(m_inputs, words={"october": 11980, "new": 12001, "reference": 11980})
    assert fs.gate2(words, "M", None)[:2] == ("PENDING_AUTHOR", ["WORDS_OVER"])
    # a post FAIL anywhere else is not a refusal: hard fail
    other = dict(m_inputs, post=m_inputs["post"] + [_chk("D", "p2 math share 0.31")])
    v, codes, _ = fs.gate2(other, "M", None)
    assert v == "GATE2_FAIL" and "POST_FAIL" in codes


def _claim(name, anchor, file="sections/sec4_causal.tex"):
    return dict(_chk("D", name, file=file), kind="claim", anchor_found=anchor)


def test_gate2_sends_a_flipped_claim_to_the_author_and_fails_a_lost_sentence(m_inputs):
    """review R7 #8: a claim (a sentence whose meaning follows the ledger; replace.py never rewrites words)
    that FAILs with its sentence found goes to the author (REFUSED_SPANS -> PENDING_AUTHOR), and the same
    name may FAIL after the repin; a claim whose sentence is not found is unexplained (hard)."""
    flip = dict(m_inputs, pre=m_inputs["pre"] + [_claim("r4 4.3 P2 lead", True)],
                post=m_inputs["post"] + [_claim("r4 4.3 P2 lead", True)])
    v, codes, det = fs.gate2(flip, "M", None)
    assert (v, codes) == ("PENDING_AUTHOR", ["REFUSED_SPANS"]), det
    assert [r.get("claim") for r in det["refused"]] == ["r4 4.3 P2 lead"]
    assert det["unexplained"] == det["post_unexplained"] == []
    assert fs.final_report("M", v, codes, det)["counts"]["refused"] == 1
    lost = dict(m_inputs, pre=m_inputs["pre"] + [_claim("r4 4.3 P2 lead", False)],
                post=m_inputs["post"] + [_claim("r4 4.3 P2 lead", False)])
    v, codes, det = fs.gate2(lost, "M", None)
    assert v == "GATE2_FAIL" and "FAIL_SET_MISMATCH" in codes and "POST_FAIL" in codes
    assert det["unexplained"] == ["D:r4 4.3 P2 lead"]
    # a claim FAIL only after the repin is not a refusal either
    late = dict(m_inputs, post=m_inputs["post"] + [_claim("r4 4.3 P2 lead", True)])
    v, codes, _ = fs.gate2(late, "M", None)
    assert v == "GATE2_FAIL" and "POST_FAIL" in codes


CELL = "tab_p1_main P1 ATE (log points) [econ]"


def test_gate2_explains_a_table_cell_fail_by_its_tree_path(m_inputs):
    """review R7 #10: check_paper names a check on the tree's tables/ 'tables/<name>'; such a FAIL is explained
    when install changed that table."""
    inp = dict(m_inputs, pre=m_inputs["pre"] + [_chk("D", CELL, file="tables/tab_p1_main.tex")],
               changed_tables=m_inputs["changed_tables"] + ["tab_p1_main.tex"])
    assert fs.gate2(inp, "M", None)[:2] == ("PASS", [])


@pytest.mark.parametrize("name,file,changed", [
    (CELL, None, ["tab_p1_main.tex"]),                                  # no file: never a table cell
    (CELL, "tab_p1_main.tex", ["tab_p1_main.tex"]),                    # a bare name is not a tree path
    (CELL, "output/paper/tables/tab_p1_main.tex", ["tab_p1_main.tex"]),  # only the tree's tables/ counts
    (CELL, "tables/tab_p1_main.tex", []),                              # the table did not change
    ("rob P1 main [econ] est", None, ["tab_robustness.tex"])])         # output/paper's tab_robustness.tex
def test_gate2_does_not_explain_a_cell_off_the_trees_changed_tables(m_inputs, name, file, changed):
    inp = dict(m_inputs, pre=m_inputs["pre"] + [_chk("D", name, file=file)],
               changed_tables=m_inputs["changed_tables"] + changed)
    v, codes, det = fs.gate2(inp, "M", None)
    assert v == "GATE2_FAIL" and "FAIL_SET_MISMATCH" in codes and det["unexplained"] == [f"D:{name}"]


ROB_PIN = "rob overlap: economics events on all 113"
ROB_SRC = "src:sections/sec4_robustness.tex:53 p1p2:p1_econ.events"


def _report_edit(sources, status="EDIT", with_list=True):
    e = {"root": "/work/scratch/tree", "file": "sections/sec4_robustness.tex", "start": 10, "end": 13, "old": "113",
         "new": "118", "status": status, "reason": "", "source": " + ".join(sources), "old_value": 113,
         "new_value": 118}
    if with_list:
        e["sources"] = list(sources)
    return e


@pytest.mark.parametrize("with_list", [True, False])
def test_gate2_joins_every_pin_of_a_merged_replace_edit(m_inputs, with_list):
    """review R7 #9: replace.py merges a pin and a same-span '% src:' literal into one edit whose source is
    'pin:<name> + src:...'. The edit row keeps one row per edit and lists its pins, so the pin's pre FAIL is
    explained and the pin is not 'missing'; an old report without 'sources' is split on ' + '."""
    rows = fs.edit_rows({"edits": [_report_edit(["pin:" + ROB_PIN, ROB_SRC], with_list=with_list)]})
    assert len(rows) == 1 and rows[0]["pins"] == [ROB_PIN] and rows[0]["pin"] == ROB_PIN
    inp = dict(m_inputs, pre=m_inputs["pre"] + [_chk("D", ROB_PIN, file="sections/sec4_robustness.tex")],
               post=m_inputs["post"] + [_chk("D", ROB_PIN, ok=True, file="sections/sec4_robustness.tex")],
               edits=m_inputs["edits"] + rows)
    v, codes, det = fs.gate2(inp, "M", None)
    assert (v, codes) == ("PASS", []), det
    assert det["unexplained"] == det["missing"] == []
    # two pins on one edit, both with their pre FAIL
    two = fs.edit_rows({"edits": [_report_edit(["pin:a 1", "pin:b 2"], with_list=with_list)]})
    assert two[0]["pins"] == ["a 1", "b 2"] and len(two) == 1
    inp2 = dict(m_inputs, pre=m_inputs["pre"] + [_chk("D", "a 1"), _chk("D", "b 2")],
                post=m_inputs["post"] + [_chk("D", "a 1", ok=True), _chk("D", "b 2", ok=True)],
                edits=m_inputs["edits"] + two)
    assert fs.gate2(inp2, "M", None)[:2] == ("PASS", [])
    # a missing FAIL of the second pin still shows
    inp3 = dict(inp2, pre=m_inputs["pre"] + [_chk("D", "a 1")])
    v, codes, det = fs.gate2(inp3, "M", None)
    assert v == "GATE2_FAIL" and det["missing"] == ["D:b 2"]


def test_a_merged_sign_change_counts_once(m_inputs):
    rows = fs.edit_rows({"edits": [_report_edit(["pin:" + ROB_PIN, ROB_SRC], status="SIGN_CHANGED")]})
    inp = dict(m_inputs, pre=m_inputs["pre"] + [_chk("D", ROB_PIN)], edits=rows,
               post=m_inputs["post"])
    _, _, det = fs.gate2(inp, "M", None)
    assert len(det["sign_changed"]) == 1 and det["sign_changed"][0]["pins"] == [ROB_PIN]


# ---- M2 (audit final_stage.py): the printed numbers whose meaning may flip, and replace.py's own check ------
def _nd(ledger, key, old, new, *, sign="false", p="false", printed="true", status="changed"):
    """One ledger_diff.csv row (tools/r1_number_diff.py HEADER) as _collect reads it."""
    return {"ledger": ledger, "key": key, "old": old, "new": new, "status": status, "same_at_3dp": "false",
            "sign_change": sign, "p_crosses_005": p, "printed": printed}


#: M's P1 economics placebo: 0.003 -> 0.073 (sec4_p1.tex '... but fails in economics')
P_CROSS = _nd("p1p2", "p1_econ.p_joint_placebo_person", "0.00277", "0.0732", p="true")
#: a printed number whose sign flips (number only; the sentence carries the direction)
S_FLIP = _nd("p3afar", "chemistry.ate_pp", "-0.466", "0.012", sign="true")
FLAG_KEYS = ("ledger", "key", "old", "new", "printed")


def _with_rows(m, *rows):
    """m_inputs plus number_diff rows, each changed key with its section-A FAIL (so none is 'missing')."""
    tops = sorted({(r["ledger"], fs._top(r["key"])) for r in rows if r["status"] != "unchanged"})
    return dict(m, number_diff=m["number_diff"] + list(rows),
                pre=m["pre"] + [_chk("A", f"[{led}] {top}") for led, top in tops])


def test_gate2_sends_printed_p_values_that_cross_005_to_the_author(m_inputs):
    """replace.py rewrites the number only; the words around a p that crosses 0.05 ('passes', 'fails in
    economics') may now be wrong, and no tool rewrites words: PENDING_AUTHOR, with the rows listed."""
    v, codes, det = fs.gate2(_with_rows(m_inputs, P_CROSS), "M", None)
    assert (v, codes) == ("PENDING_AUTHOR", ["PRINTED_P_CROSSES_005"]), det
    assert det["p_crossings"] == [{k: P_CROSS[k] for k in FLAG_KEYS}]
    assert fs.final_report("M", v, codes, det)["counts"]["p_crossings"] == 1
    # a crossing that is not printed stays in number_table.md only
    quiet = _nd("p1p2", "p1_econ.p_joint_effects_event", "0.04", "0.06", p="true", printed="false")
    v, codes, det = fs.gate2(_with_rows(m_inputs, quiet), "M", None)
    assert (v, codes, det["p_crossings"]) == ("PASS", [], [])
    # printed unknown ('': numbers could not list the printed keys): listed, never guessed away
    v, codes, det = fs.gate2(_with_rows(m_inputs, dict(P_CROSS, printed="")), "M", None)
    assert codes == ["PRINTED_P_CROSSES_005"] and [r["printed"] for r in det["p_crossings"]] == [""]
    assert "PRINTED_P_CROSSES_005" in fs.PENDING_CODES and "PRINTED_P_CROSSES_005" not in fs.HARD_CODES


def test_gate2_sends_sign_changes_to_the_author(m_inputs):
    """A SIGN_CHANGED edit (replace.py writes '$-$0.02' -> '$+$0.01') and a printed ledger key whose sign flips
    are pending: the sentence may say 'a fall of'."""
    edits = [dict(e, status="SIGN_CHANGED") if e["pin"] == "p1 chem ATE $-$0.02" else e for e in m_inputs["edits"]]
    v, codes, det = fs.gate2(dict(m_inputs, edits=edits), "M", None)
    assert (v, codes) == ("PENDING_AUTHOR", ["PRINTED_SIGN_CHANGED"]), det
    assert [e["pin"] for e in det["sign_changed"]] == ["p1 chem ATE $-$0.02"]
    v, codes, det = fs.gate2(_with_rows(m_inputs, S_FLIP), "M", None)
    assert (v, codes) == ("PENDING_AUTHOR", ["PRINTED_SIGN_CHANGED"]), det
    assert det["printed_sign_changes"] == [{k: S_FLIP[k] for k in FLAG_KEYS}]
    assert fs.final_report("M", v, codes, det)["counts"]["printed_sign_changes"] == 1
    v, codes, det = fs.gate2(_with_rows(m_inputs, dict(S_FLIP, printed="false")), "M", None)
    assert (v, codes, det["printed_sign_changes"]) == ("PASS", [], [])
    # both kinds at once, in CODES order
    both = fs.gate2(_with_rows(dict(m_inputs, edits=edits), P_CROSS, S_FLIP), "M", None)
    assert both[:2] == ("PENDING_AUTHOR", [c for c in fs.CODES if c in ("PRINTED_P_CROSSES_005", "PRINTED_SIGN_CHANGED")])


def test_gate2_hard_fails_when_replace_py_post_write_verification_fails(m_inputs):
    """replace.py exits 0 even when its own post-write check fails (a pin that does not print the new value,
    a second new->new pass that still edits, a written '% src:' literal off its key): GATE2_FAIL."""
    for rv in ({"pins_not_new": ["p3 econ ATE 0.044pp"]},
               {"edits_left_new_to_new": [{"file": "sections/sec4_p1.tex", "old": "0.009", "new": "0.010"}]},
               {"src_literals_not_matching_new_key": [{"file": "sections/sec4_p1.tex", "line": 27, "key": "k",
                                                       "new": "0.000"}]},
               {"draft_verify_absent": ["replace_report.json has no draft_verify"]}):
        v, codes, det = fs.gate2(dict(m_inputs, replace_verify=rv), "M", None)
        assert (v, codes) == ("GATE2_FAIL", ["REPLACE_VERIFY_FAIL"]), rv
        assert det["replace_verify"] == rv
    clean = {"pins_not_new": [], "edits_left_new_to_new": [], "src_literals_not_matching_new_key": []}
    v, codes, det = fs.gate2(dict(m_inputs, replace_verify=clean), "M", None)
    assert (v, codes, det["replace_verify"]) == ("PASS", [], {})
    assert "REPLACE_VERIFY_FAIL" in fs.HARD_CODES


def test_gate2_hard_fails_when_repin_py_label_verification_fails(m_inputs):
    """repin.py's own check after renaming the pin labels: a renamed pin missing from the rewritten
    check_paper.py (its check would silently be gone after the repin), or a vault-overlay key naming no pin."""
    for rv in ({"renamed_missing": ["p3 econ ATE 0.051pp"]}, {"overlay_keys_unmatched": ["p3 econ ATE 0.044pp"]}):
        v, codes, det = fs.gate2(dict(m_inputs, repin_verify=rv), "M", None)
        assert (v, codes) == ("GATE2_FAIL", ["REPIN_VERIFY_FAIL"]), rv
        assert det["repin_verify"] == rv
    v, codes, det = fs.gate2(dict(m_inputs, repin_verify={"renamed_missing": [], "overlay_keys_unmatched": []}), "M", None)
    assert (v, codes, det["repin_verify"]) == ("PASS", [], {})
    assert "REPIN_VERIFY_FAIL" in fs.HARD_CODES


def test_gate2_b0_ignores_the_m_only_flags(m_inputs):
    """finalb0 compares October with October (no crossings, no edits); its verdict, codes and counts are
    unchanged by the M-only flags."""
    exp = fs.load_expected_b0(B0_EXPECTED)
    b0 = _b0_from(m_inputs)
    base = fs.gate2(b0, "B0", exp)
    flagged = dict(b0, number_diff=[P_CROSS, S_FLIP], replace_verify={"pins_not_new": ["x 1"]},
                   repin_verify={"overlay_keys_unmatched": ["x 1"]})
    v, codes, det = fs.gate2(flagged, "B0", exp)
    assert (v, codes) == base[:2] == ("B0_PASS", [])
    assert not {"p_crossings", "printed_sign_changes", "replace_verify", "repin_verify"} & set(det)
    assert fs.final_report("B0", v, codes, det) == fs.final_report("B0", *base)


# ---- M2 round 2: '% src:' p-literals that cross 0.05 (review 3 important 2) --------------------------------------
def _src_edit(src, status, old, new, file="sections/sec4_p1.tex", pins=()):
    """One edit_rows row of a replace.py edit whose sources include a '% src:' literal."""
    sources = [f"pin:{p}" for p in pins] + [src]
    return {"pin": pins[0] if pins else None, "pins": list(pins), "source": " + ".join(sources), "file": file,
            "status": status, "reason": "", "old": "x", "new": None if status in fs.REFUSED else "y",
            "old_value": old, "new_value": new}


def test_gate2_sends_src_p_literals_that_cross_005_to_the_author(m_inputs):
    """The base tree prints p-values through '% src:' literals no check_paper pin reads, so their ledger_diff rows
    are not 'printed' and never reach p_crossings. Every replace.py edit, written or refused, whose source names
    a p key (r1_number_diff.is_p_key) and whose old and new values lie on opposite sides of 0.05 is a printed p
    crossing too: listed with its file, source and status. No crossing, no p key, a span replace.py neither
    writes nor refuses (ALREADY_NEW), or a value that is no number: not listed."""
    placebo = "src:sections/sec4_p1.tex:50 p1p2:p1_econ.p_joint_placebo_person"
    pair = "src:sections/sec4_p3.tex:9 p3afar:chemistry.p_joint_effects_pair"
    merged = "src:sections/sec4_p2.tex:31 carried:econ_fellow_placebo_p"
    edits = m_inputs["edits"] + [
        _src_edit(placebo, "EDIT", 0.00277, 0.0732),
        _src_edit(pair, "NEEDS_MANUAL", 0.2, 0.012, file="sections/sec4_p3.tex"),
        _src_edit(merged, "EDIT", 0.04, 0.06, file="sections/sec4_p2.tex", pins=("p2 econ placebo p=0.04",)),
        _src_edit("src:sections/sec4_p1.tex:3 p1p2:p1_econ.p_joint_effects_event", "EDIT", 0.01, 0.02),
        _src_edit("src:sections/sec4_p1.tex:4 p1p2:p1_econ.ate_log", "EDIT", 0.01, 0.2),
        _src_edit("src:sections/sec4_p1.tex:5 p1p2:p1_math_stats.p_joint_effects_event", "ALREADY_NEW", 0.01, 0.2),
        _src_edit("src:sections/sec4_p1.tex:6 p1p2:p1_chemistry.p_joint_effects_event", "NEEDS_MANUAL", 0.01, None)]
    pre = m_inputs["pre"] + [_chk("D", "p2 econ placebo p=0.04", file="sections/sec4_p2.tex")]
    v, codes, det = fs.gate2(dict(m_inputs, edits=edits, pre=pre), "M", None)
    assert (v, codes) == ("PENDING_AUTHOR", ["REFUSED_SPANS", "PRINTED_P_CROSSES_005"]), det
    assert det["p_crossings"] == [
        {"ledger": "p1p2", "key": "p1_econ.p_joint_placebo_person", "old": 0.00277, "new": 0.0732, "printed": "true",
         "file": "sections/sec4_p1.tex", "source": placebo, "status": "EDIT"},
        {"ledger": "p3afar", "key": "chemistry.p_joint_effects_pair", "old": 0.2, "new": 0.012, "printed": "true",
         "file": "sections/sec4_p3.tex", "source": pair, "status": "NEEDS_MANUAL"},
        {"ledger": "main", "key": "econ_fellow_placebo_p", "old": 0.04, "new": 0.06, "printed": "true",
         "file": "sections/sec4_p2.tex", "source": merged, "status": "EDIT"}]
    assert fs.final_report("M", v, codes, det)["counts"]["p_crossings"] == 3
    # the ledger_diff rows are still listed first, as before
    v, codes, det = fs.gate2(_with_rows(dict(m_inputs, edits=edits, pre=pre), P_CROSS), "M", None)
    # the ledger_diff rows are listed first; an edit of a key a printed row already lists is not listed twice
    assert det["p_crossings"][0] == {k: P_CROSS[k] for k in FLAG_KEYS} and len(det["p_crossings"]) == 3
    assert [(c["ledger"], c["key"]) for c in det["p_crossings"]].count(("p1p2", "p1_econ.p_joint_placebo_person")) == 1
    # B0 reads none of this
    exp = fs.load_expected_b0(B0_EXPECTED)
    b0 = _b0_from(m_inputs)
    assert "p_crossings" not in fs.gate2(dict(b0, edits=b0["edits"] + [_src_edit(placebo, "ALREADY_NEW", 0.003, 0.07)]),
                                         "B0", exp)[2]



# ---- M2 round 3 (Codex STOP 3): a '% src:' p that crosses 0.05 while its printed digits stay ------------------------
DSHIFT = "robustness:p3_date_shift.math_stats.p_joint_shifted"


def _src_lit(key=DSHIFT, old=0.0504, new=0.0496, status="UNCHANGED", file="sections/sec4_causal.tex", line=79,
             token="0.050"):
    """One replace_report.json src_p_literals row (replace.py: every '% src:' literal on a p key)."""
    return {"file": file, "line": line, "key": key, "token": token, "old_value": old, "new_value": new,
            "status": status, "source": f"src:{file}:{line} {key}"}


def test_gate2_flags_a_src_p_crossing_whose_printed_digits_do_not_change(m_inputs):
    """Mathematics' date-shift p 0.0504 -> 0.0496 prints '0.050' both times: replace.py makes no edit and
    ledger_diff marks the key unprinted (no pin reads it), so the crossing reached no one. Gate 2 reads every
    '% src:' p-literal replace.py recorded (written, refused or unchanged) and lists each that crosses 0.05,
    once per literal: a literal that also has an edit is listed from the edit, and a key a printed ledger_diff
    row lists is not listed again. No crossing, no p key, no number: not listed. B0 reads none of this."""
    lit = _src_lit()
    v, codes, det = fs.gate2(dict(m_inputs, src_p_literals=[lit]), "M", None)
    assert (v, codes) == ("PENDING_AUTHOR", ["PRINTED_P_CROSSES_005"]), det
    assert det["p_crossings"] == [{"ledger": "robustness", "key": "p3_date_shift.math_stats.p_joint_shifted",
                                   "old": 0.0504, "new": 0.0496, "printed": "true", "file": "sections/sec4_causal.tex",
                                   "source": lit["source"], "status": "UNCHANGED"}]
    quiet = [_src_lit(new=0.0507), _src_lit(key="robustness:p3_date_shift.econ.ate_pp", old=0.01, new=0.2),
             _src_lit(new=None), _src_lit(status="ALREADY_NEW")]   # ALREADY_NEW: as for an edit, not listed
    assert fs.gate2(dict(m_inputs, src_p_literals=quiet), "M", None)[:2] == ("PASS", [])
    # the same literal edited (a crossing whose digits did change): listed once, from the edit
    edited = _src_lit(key="p1p2:p1_econ.p_joint_placebo_person", old=0.00277, new=0.0732, status="EDIT",
                      file="sections/sec4_p1.tex", line=50, token="0.003")
    edits = m_inputs["edits"] + [_src_edit(edited["source"], "EDIT", 0.00277, 0.0732)]
    v, codes, det = fs.gate2(dict(m_inputs, edits=edits, src_p_literals=[edited, lit]), "M", None)
    assert [c["source"] for c in det["p_crossings"]] == [edited["source"], lit["source"]], det["p_crossings"]
    assert [c["status"] for c in det["p_crossings"]] == ["EDIT", "UNCHANGED"]
    # a key a printed ledger_diff row already lists
    row = _nd("robustness", "p3_date_shift.math_stats.p_joint_shifted", "0.0504", "0.0496", p="true")
    v, codes, det = fs.gate2(_with_rows(dict(m_inputs, src_p_literals=[lit]), row), "M", None)
    assert det["p_crossings"] == [{k: row[k] for k in FLAG_KEYS}]
    # B0 reads none of this
    exp = fs.load_expected_b0(B0_EXPECTED)
    assert "p_crossings" not in fs.gate2(dict(_b0_from(m_inputs), src_p_literals=[lit]), "B0", exp)[2]


def test_gate2_stage_reads_the_src_p_literals_and_requires_them_in_m(tmp_path, monkeypatch):
    """_collect hands replace_report.json's src_p_literals to gate 2; in M a report without the list is
    REPORT_MISSING (the final job always runs a replace.py that writes it), so a crossing is never dropped
    unseen."""
    a = _stage_args(tmp_path)
    prod = pathlib.Path(a.prod)
    (prod / "repin").mkdir(parents=True)
    lit = _src_lit()
    (prod / "repin" / "replace_report.json").write_text(json.dumps(
        {"edits": [], "verify": [], "src_p_literals": [lit],
         "draft_verify": {"edits_left_new_to_new": [], "src_literals_not_matching_new_key": []}}))
    inp = fs._collect(a, "M")
    assert inp["src_p_literals"] == [lit] and not any("src_p_literals" in m for m in inp["reports_missing"])
    (prod / "repin" / "replace_report.json").write_text(json.dumps(
        {"edits": [], "verify": [], "draft_verify": {"edits_left_new_to_new": [], "src_literals_not_matching_new_key": []}}))
    inp = fs._collect(a, "M")
    assert "repin/replace_report.json src_p_literals" in inp["reports_missing"]


# ---- M2 round 2: ledger keys a generator lists as unreproducible go to the author, not FAIL_SET_MISMATCH --------
CENTRE_WHY = ("prep_final_report.json (2026-08-10) counts another chemistry roster (518 people, 533 spells) than "
              "the one in force; the no-research-centre roster leaves out 2 of those 1,010 people")
FELLOW_WHY = "cal/roster_added_2026-10.csv has no evidence columns (no evidence_url)"


def _unrep_chk(label, key, reason):
    """A section-A line check_paper writes for a key a generated ledger lists in _unreproducible (check_unreproducible)."""
    return {"section": "A", "name": f"[{label}] {key}", "ok": True, "retired": False, "unrep": True, "file": None,
            "detail": f"UNREPRODUCIBLE (asserted only): {key} — {reason}", "note": ""}


def test_gate2_reads_the_reason_check_paper_writes_for_an_unreproducible_key():
    """The section-A line gate 2 parses is check_paper's own (check_unreproducible, and its --json report keeps
    'unrep' and 'detail'): the ledger's reason comes back whole, a dash inside it included."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("cp_for_gate2_unrep", REPO / "tools" / "check_paper.py")
    cp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cp)   # type: ignore[union-attr]
    cp.checks.clear()
    why = CENTRE_WHY + " — the footnote is the author's call"
    cp.check_unreproducible("chem_centre_added", why, "carried")
    cp.check_unreproducible("pre_topic_pairs", "no October producer", "funnel")   # no thesis ledger: not read
    assert fs._unrep_a(cp.checks) == {("main", "chem_centre_added"): why}
    src = (REPO / "tools" / "check_paper.py").read_text(encoding="utf-8")
    assert '"unrep": c["unrep"], "file": c.get("file"), "detail": c["detail"]' in src


def _unrep_inputs(m):
    rows = [_nd("main", "chem_centre_added", "134", "", status="dropped"),
            _nd("main", "econ_fellow_evidence_rows", "205", "", status="dropped")]
    return dict(m, number_diff=m["number_diff"] + rows,
                pre=m["pre"] + [_unrep_chk("carried", "chem_centre_added", CENTRE_WHY),
                                _unrep_chk("carried", "econ_fellow_evidence_rows", FELLOW_WHY)])


def test_gate2_sends_ledger_keys_listed_unreproducible_to_the_author(m_inputs):
    """M: ledger_carried lists the centre and fellowship keys in _unreproducible (no source in force), so the
    merged ledger drops them and check_paper records UNREPRODUCIBLE (ok, never FAIL) for each. Such a dropped key
    is not a missing FAIL: it goes to the author with the ledger's reason (LEDGER_KEYS_UNREPRODUCIBLE, pending).
    A dropped key with no such line, or a listed key whose value changed instead of dropping, is still missing."""
    v, codes, det = fs.gate2(_unrep_inputs(m_inputs), "M", None)
    assert (v, codes) == ("PENDING_AUTHOR", ["LEDGER_KEYS_UNREPRODUCIBLE"]), det
    assert det["missing"] == [] and det["unexplained"] == []
    assert det["unreproducible"] == [{"ledger": "main", "key": "chem_centre_added", "reason": CENTRE_WHY},
                                     {"ledger": "main", "key": "econ_fellow_evidence_rows", "reason": FELLOW_WHY}]
    assert fs.final_report("M", v, codes, det)["counts"]["unreproducible"] == 2
    assert "LEDGER_KEYS_UNREPRODUCIBLE" in fs.PENDING_CODES and "LEDGER_KEYS_UNREPRODUCIBLE" not in fs.HARD_CODES
    # a dropped key nothing lists: still FAIL_SET_MISMATCH
    lost = dict(m_inputs, number_diff=m_inputs["number_diff"] + [_nd("main", "math_centre_added", "28", "",
                                                                      status="dropped")])
    v, codes, det = fs.gate2(lost, "M", None)
    assert v == "GATE2_FAIL" and "FAIL_SET_MISMATCH" in codes and det["missing"] == ["A:main math_centre_added"]
    # a listed key whose value changed (the merged ledger still holds a value): not this case, still missing
    moved = _unrep_inputs(m_inputs)
    moved["number_diff"] = [dict(r, status="changed", new="7") if r["key"] == "chem_centre_added" else r
                            for r in moved["number_diff"]]
    v, codes, det = fs.gate2(moved, "M", None)
    assert v == "GATE2_FAIL" and det["missing"] == ["A:main chem_centre_added"], det
    assert [u["key"] for u in det["unreproducible"]] == ["econ_fellow_evidence_rows"]
    # B0: the M-only list does not exist and the verdict is unchanged
    exp = fs.load_expected_b0(B0_EXPECTED)
    b0 = _b0_from(m_inputs)
    v, codes, det = fs.gate2(dict(b0, pre=b0["pre"] + [_unrep_chk("carried", "chem_centre_added", CENTRE_WHY)]),
                             "B0", exp)
    assert (v, codes) == ("B0_PASS", []) and "unreproducible" not in det
    assert "unreproducible" not in fs.final_report("B0", v, codes, det)["counts"]


def _stage_args(tmp_path):
    import argparse
    return argparse.Namespace(mode="M", repo=str(REPO), paper=str(REPO / "config" / "r1" / "final_paper.json"),
                              expected_b0=str(REPO / "config" / "r1" / "final_b0_expected.json"),
                              prod=str(tmp_path / "prod"), output_paper=str(tmp_path / "output_paper"),
                              ref_output_paper=str(tmp_path / "ref"), tree_current=str(tmp_path / "cur"),
                              scratch=str(tmp_path / "scr"), final_dir=str(tmp_path / "final"),
                              out=str(tmp_path / "out"))


def test_gate2_stage_reads_the_number_flags_and_replace_verification(tmp_path, monkeypatch):
    """_collect keeps ledger_diff.csv's flag columns and reads replace_report.json's verify / draft_verify;
    cmd_gate2 puts the flagged rows and the verification failures into change_facts.json."""
    import csv
    import r1_number_diff as nd
    monkeypatch.setattr(fs, "_run", lambda argv, **kw: (1, ""))          # no packer here: PACK_FAIL, fine
    a = _stage_args(tmp_path)
    prod, op = pathlib.Path(a.prod), pathlib.Path(a.output_paper)
    (op / "draft_2026_09_13").mkdir(parents=True)
    (op / "draft_2026_09_13" / "NOTE_CHECKS.json").write_text(json.dumps([NOTE_OK]))
    (prod / "numbers").mkdir(parents=True)
    quiet = _nd("p1p2", "p1_econ.n", "113", "118")
    with open(prod / "numbers" / "ledger_diff.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=nd.HEADER, lineterminator="\n")
        w.writeheader()
        for r in (P_CROSS, S_FLIP, quiet):
            w.writerow(r)
    (prod / "repin").mkdir()
    off_key = {"file": "sections/sec4_p1.tex", "line": 27, "key": "p1p2:p1_math_stats.p_joint_effects_person",
               "new": "0.000"}
    (prod / "repin" / "replace_report.json").write_text(json.dumps(
        {"edits": [], "verify": [{"pin": "a 1", "ok": False}, {"pin": "b 2", "ok": True}],
         "draft_verify": {"edits_left_new_to_new": [], "written_src_literals": 3,
                          "src_literals_not_matching_new_key": [off_key]}}))
    (prod / "repin" / "repin_report.json").write_text(json.dumps(
        {"label_edits": [], "verify": {"parses": True, "all_renamed_present": False,
                                       "renamed_missing": ["p3 econ ATE 0.051pp"], "overlay_keys_unmatched": []}}))
    (tmp_path / "out").mkdir()
    inp = fs._collect(a, "M")
    assert [{k: r[k] for k in nd.HEADER if k in r} for r in inp["number_diff"]] == \
        [{k: r[k] for k in nd.HEADER if k != "same_at_3dp"} for r in (P_CROSS, S_FLIP, quiet)]
    assert inp["replace_verify"] == {"pins_not_new": ["a 1"], "edits_left_new_to_new": [],
                                     "src_literals_not_matching_new_key": [off_key]}
    assert inp["repin_verify"] == {"renamed_missing": ["p3 econ ATE 0.051pp"], "overlay_keys_unmatched": []}
    assert fs.cmd_gate2(a) == 1
    facts = json.loads((tmp_path / "out" / "change_facts.json").read_text())
    assert facts["p_crossings"] == [{k: P_CROSS[k] for k in FLAG_KEYS}]
    assert facts["printed_sign_changes"] == [{k: S_FLIP[k] for k in FLAG_KEYS}]
    assert facts["replace_verify"] == {"pins_not_new": ["a 1"], "src_literals_not_matching_new_key": [off_key]}
    assert facts["repin_verify"] == {"renamed_missing": ["p3 econ ATE 0.051pp"]}
    assert {"REPLACE_VERIFY_FAIL", "REPIN_VERIFY_FAIL", "PRINTED_P_CROSSES_005",
            "PRINTED_SIGN_CHANGED"} <= set(facts["codes"])
    # a report without draft_verify is a failed verification too (the final job always passes --write); an
    # older repin report with only the flag still counts
    (prod / "repin" / "replace_report.json").write_text(json.dumps({"edits": [], "verify": []}))
    (prod / "repin" / "repin_report.json").write_text(json.dumps(
        {"label_edits": [], "verify": {"parses": True, "all_renamed_present": False, "overlay_keys_unmatched": []}}))
    inp = fs._collect(a, "M")
    assert inp["replace_verify"]["draft_verify_absent"] and inp["repin_verify"]["renamed_missing"]
    # a pin that replace.py refused still prints its old value: its failed verify is the refusal, not a fault
    (prod / "repin" / "replace_report.json").write_text(json.dumps(
        {"edits": [{"source": "pin:a 1", "sources": ["pin:a 1"], "file": "sections/sec4_p1.tex", "status": "NEEDS_MANUAL"}],
         "verify": [{"pin": "a 1", "ok": False}], "draft_verify": {"edits_left_new_to_new": [],
                                                                 "src_literals_not_matching_new_key": []}}))
    assert fs._collect(a, "M")["replace_verify"] == {"pins_not_new": [], "edits_left_new_to_new": [],
                                                     "src_literals_not_matching_new_key": []}


def test_gate2_stage_reads_label_conflicts_as_repin_writes_them(tmp_path, monkeypatch):
    """Round-4 review #3: repin.py writes each LabelEdit with dataclasses.asdict (lineno, reason); _collect read
    'line' and 'note' and passed nulls on, and change_facts.json left the conflicts out. Each conflict reaches
    gate 2 and change_facts.json with the line and the reason repin.py wrote."""
    import dataclasses
    import importlib.util
    spec = importlib.util.spec_from_file_location("r1_final_repin", REPO / "tools" / "repin_thesis_2026-10" / "repin.py")
    R = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO / "tools" / "repin_thesis_2026-10"))
    monkeypatch.setitem(sys.modules, spec.name, R)          # dataclasses look the module up while it loads
    spec.loader.exec_module(R)
    monkeypatch.setattr(fs, "_run", lambda argv, **kw: (1, ""))
    a = _stage_args(tmp_path)
    prod, op = pathlib.Path(a.prod), pathlib.Path(a.output_paper)
    (op / "draft_2026_09_13").mkdir(parents=True)
    (op / "draft_2026_09_13" / "NOTE_CHECKS.json").write_text(json.dumps([NOTE_OK]))
    (prod / "numbers").mkdir(parents=True)
    import csv
    import r1_number_diff as nd
    with open(prod / "numbers" / "ledger_diff.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=nd.HEADER, lineterminator="\n")
        w.writeheader()
        w.writerow(_nd("p1p2", "p1_econ.n", "113", "118"))
    (prod / "repin").mkdir()
    (prod / "repin" / "replace_report.json").write_text(json.dumps(
        {"edits": [], "verify": [], "draft_verify": {"edits_left_new_to_new": [], "src_literals_not_matching_new_key": []}}))
    conflict = R.LabelEdit(812, "events 113", None, "CONFLICT", ["sec2 caption events 113", "sec3 caption events 113"],
                           "pins disagree on the new label")
    rename = R.LabelEdit(90, "p3 econ ATE 0.044pp", "p3 econ ATE 0.051pp", "EDIT", ["p3 econ ATE 0.044pp"])
    (prod / "repin" / "repin_report.json").write_text(json.dumps(
        {"label_edits": [dataclasses.asdict(conflict), dataclasses.asdict(rename)],
         "verify": {"parses": True, "all_renamed_present": True, "renamed_missing": [], "overlay_keys_unmatched": []}}))
    (tmp_path / "out").mkdir()
    want = [{"line": 812, "old": "events 113", "pins": ["sec2 caption events 113", "sec3 caption events 113"],
             "reason": "pins disagree on the new label"}]
    inp = fs._collect(a, "M")
    assert inp["label_conflicts"] == want and inp["renamed"] == {"p3 econ ATE 0.044pp": "p3 econ ATE 0.051pp"}
    fs.cmd_gate2(a)
    facts = json.loads((tmp_path / "out" / "change_facts.json").read_text())
    assert facts["label_conflicts"] == want and "PIN_LABEL_CONFLICT" in facts["codes"]


def test_gate2_stage_puts_the_unreproducible_keys_into_change_facts(tmp_path, monkeypatch):
    """cmd_gate2 (M): the dropped keys check_paper recorded as UNREPRODUCIBLE reach change_facts.json with the
    ledger's reason, next to the other lists the author gets."""
    import csv
    import r1_number_diff as nd
    monkeypatch.setattr(fs, "_run", lambda argv, **kw: (1, ""))          # no packer here: PACK_FAIL, fine
    a = _stage_args(tmp_path)
    prod, op = pathlib.Path(a.prod), pathlib.Path(a.output_paper)
    (op / "draft_2026_09_13").mkdir(parents=True)
    (op / "draft_2026_09_13" / "NOTE_CHECKS.json").write_text(json.dumps([NOTE_OK]))
    (prod / "numbers").mkdir(parents=True)
    with open(prod / "numbers" / "ledger_diff.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=nd.HEADER, lineterminator="\n")
        w.writeheader()
        w.writerow(_nd("main", "chem_centre_added", "134", "", status="dropped"))
    (prod / "sentinel_pre").mkdir()
    (prod / "sentinel_pre" / "vault.json").write_text(json.dumps(
        {"checks": [_unrep_chk("carried", "chem_centre_added", CENTRE_WHY)]}))
    (tmp_path / "out").mkdir()
    assert fs.cmd_gate2(a) == 1                                        # many reports absent in this toy
    facts = json.loads((tmp_path / "out" / "change_facts.json").read_text())
    assert facts["unreproducible"] == [{"ledger": "main", "key": "chem_centre_added", "reason": CENTRE_WHY}]
    assert "LEDGER_KEYS_UNREPRODUCIBLE" in facts["codes"]
    rep = json.loads((tmp_path / "out" / "final_report_gate2.json").read_text())
    assert rep["counts"]["unreproducible"] == 1 and CENTRE_WHY not in json.dumps(rep)


def test_printed_keys_on_the_scratch_tree_include_the_base_tree_claims(tmp_path, monkeypatch):
    """review R7 #8: numbers' --printed column comes from the pins on the scratch tree (a packed base tree:
    'vault' profile, base-tree claims included) plus the ledger keys of the base-tree word claims and untraced
    pins (check_paper.BASE_TREE_PRINTED_KEYS)."""
    import yaml
    from analysis.lib.paths import load_paths
    cfg = {k: str(v) for k, v in load_paths().items()}
    cfg.update(repo_root=".", output=str(tmp_path / "out"))
    (tmp_path / "p.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("SAR_PATHS_CONFIG", str(tmp_path / "p.yaml"))
    tree = tmp_path / "scratch_tree"
    shutil.copytree(REPO / "tests" / "fixtures" / "r1_paper" / "base_tree_2026-10-11" / "ledgers", tree)
    (tree / "TREE_MANIFEST.sha256").write_text("0" * 64 + "  main.tex\n", encoding="ascii")
    zen = {"star_percentile": 99.7, "roster": 60, "network": 66, "network_only": 42, "union": 102,
           "dose_below_01": 26, "dose_ge_05": 63, "dose_median": 0.51, "p2_followed": 100, "p2_first_ties_post": 6,
           "outside_network": 36, "same_topic_outside": 36, "pairs": 624, "pairs_possible": 630,
           "pairs_excluded_prewindow": 6, "_event": "A5017376589:2016"}
    swp = {"p1": {f: {"avg_dose_switchers": v} for f, v in (("econ", 0.3833), ("chemistry", 0.4045),
                                                             ("math_stats", 0.19))}}
    (tree / "data_numbers_2026-10-23_gaps_zenou.json").write_text(json.dumps(zen), encoding="utf-8")
    (tree / "data_numbers_2026-10-23_gaps_switchers_p1p2.json").write_text(json.dumps(swp), encoding="utf-8")
    got = fs._printed_keys(REPO, tree, REPO / "tools" / "check_paper.py", REPO / "analysis" / "expected" / "P1_econ_fnfix.json")
    assert "gaps_switchers_p1p2\tp1.econ.avg_dose_switchers" in got and "gaps_zenou\tunion" in got
    for k in ("p2_followed", "pairs_excluded_prewindow", "roster"):
        assert f"gaps_zenou\t{k}" in got, k
    assert "p3afar\tecon.randomization_inference.p_two_sided" in got
    assert "funnel\tsnapshot_release_date" in got
    assert got == sorted(set(got))


@pytest.mark.parametrize("key,value,code", [
    ("bor_equal", False, "BOR_CHANGED"), ("custody_ok", False, "CUSTODY_FAIL"), ("canon_ok", False, "CANON_FAIL"),
    ("compile", {**{t: {"ok": True} for t in fs.COMPILE_TARGETS}, "scratch/main_clean": {"ok": False}}, "COMPILE_FAIL"),
    ("draft_hits", {"october": {"to be checked": 1}, "new": {"to be checked": 2}}, "DRAFT_TEXT_NEW"),
    ("reports_missing", ["texts/texts.json"], "REPORT_MISSING"), ("main_clean_invariant", False, "MAIN_CLEAN_DRIFT"),
    ("deliverables_missing", ["thesis_r1_red.pdf"], "DELIVERABLE_MISSING"), ("numbers_rc", 2, "NUMBERS_FAIL"),
    ("red", {"build_ok": True, "verify_ok": False, "reference_equal": True, "red_runs": []}, "RED_VERIFY_FAIL"),
])
def test_gate2_hard_fails_on_bor_custody_and_compile(m_inputs, key, value, code):
    v, codes, _ = fs.gate2(dict(m_inputs, **{key: value}), "M", None)
    assert v == "GATE2_FAIL" and code in codes and set(codes) <= set(fs.CODES)


@pytest.fixture
def b0_inputs(m_inputs):
    return _b0_from(m_inputs)


def _b0_from(m_inputs):
    d = {k: v for k, v in m_inputs.items() if k not in ("custody_ok", "canon_ok")}
    d.update(pre=[_chk("A", "[main] econ_events", ok=True), _chk("D", "sec3 reworded pin", file="sections/sec3_strategy.tex")],
             post=[_chk("A", "[main] econ_events", ok=True)], number_diff=[], changed_tables=[],
             edits=[{"pin": "p1 econ n 113", "file": "sections/sec4_p1.tex", "status": "ALREADY_NEW"}], renamed={},
             output_paper_diff=["fig_compare_years.pdf"],
             thesis_default=[_chk("B", "tab_robustness.tex")], thesis_root=[_chk("B", "tab_robustness.tex")],
             scratch_diff=[], words={"october": 12038, "new": 12038, "reference": 12038},
             red={"build_ok": True, "verify_ok": True, "reference_equal": True, "red_runs": []})
    return d


B0_EXPECTED = {
    "schema": "sar.r1.final_b0_expected.v1",
    "output_paper": [{"path": "fig_compare_years.pdf", "what": "new figure file", "owner": "N9", "reason": "N9 adds the figure"}],
    "vault_sentinel_fail": [{"name": "sec3 reworded pin", "what": "vault rewording", "owner": "W3-OVERLAY",
                             "reason": "the vault tree rewords this sentence"}],
    "thesis_report_sentinel_fail": [{"name": "tab_robustness.tex", "what": "base-variant table", "owner": "N10",
                                     "reason": "the draft table is generated for the vault tree"}],
    "scratch_edits": [], "red_runs": []}


def test_gate2_b0_accepts_only_the_declared_differences(b0_inputs):
    exp = fs.load_expected_b0(B0_EXPECTED)
    v, codes, det = fs.gate2(b0_inputs, "B0", exp)
    assert (v, codes) == ("B0_PASS", []), det
    for change, code in ((dict(output_paper_diff=["fig_compare_years.pdf", "data_numbers_p3afar.json"]), "B0_OUTPUT_DIFF"),
                         (dict(output_paper_diff=[]), "B0_OUTPUT_DIFF"),
                         (dict(pre=b0_inputs["pre"] + [_chk("D", "sec4 other pin")]), "B0_SENTINEL_DIFF"),
                         (dict(post=[_chk("D", "sec3 reworded pin")]), "POST_FAIL"),
                         (dict(scratch_diff=["sections/sec4_p3.tex"]), "B0_SCRATCH_DIFF"),
                         (dict(edits=[{"pin": "p3 econ p 0.235", "file": "sections/sec4_p3.tex", "status": "NEEDS_MANUAL"}]),
                          "B0_SCRATCH_DIFF"),
                         (dict(thesis_root=[]), "B0_THESIS_ROOT_DIFF"),
                         (dict(thesis_default=[], thesis_root=[]), "B0_THESIS_REPORT_DIFF"),
                         (dict(words={"october": 12038, "new": 12038, "reference": 12040}), "B0_WORDS_DIFF"),
                         (dict(red={"build_ok": True, "verify_ok": True, "reference_equal": False, "red_runs": []}),
                          "REFERENCE_PDF_DIFF"),
                         (dict(red={"build_ok": True, "verify_ok": True, "reference_equal": True, "red_runs": ["0.236"]}),
                          "B0_RED_DIFF"),
                         (dict(bor_equal=False), "BOR_CHANGED")):
        v, codes, _ = fs.gate2(dict(b0_inputs, **change), "B0", exp)
        assert v == "B0_FAIL" and code in codes, (change, codes)
    # B0 measures the base: being over the word limit is not a B0 failure
    assert fs.gate2(dict(b0_inputs, words={"october": 12038, "new": 12038, "reference": 12038}), "B0", exp)[0] == "B0_PASS"


def test_final_report_carries_codes_and_counts_only(m_inputs):
    ref = dict(m_inputs, words={"october": 11980, "new": 12001, "reference": 11980})
    verdict, codes, det = fs.gate2(ref, "M", None)
    rep = fs.final_report("M", verdict, codes, det)
    assert set(rep) == {"mode", "verdict", "codes", "counts"}
    assert rep["mode"] in fs.MODES and rep["verdict"] in fs.VERDICTS and all(c in fs.CODES for c in rep["codes"])
    for k, v in rep["counts"].items():
        assert rs.SAFE_KEY.match(k) and isinstance(v, (int, bool)) and not isinstance(v, str), (k, v)
    assert rs.name_free(rep) == rep
    text = json.dumps(rep, ensure_ascii=False)
    for name in ("Zénou", "p3 econ ATE", "chem_events", "to be checked"):
        assert name not in text


def test_red_verify_gets_only_the_figures_the_document_includes(tmp_path, monkeypatch):
    """review R7 #12: verify --figures means the figure files the new PDF includes (red_diff's own help and
    build report), never every PDF in scratch/figures (the base tree also holds unused and dated copies,
    whose drawings would break the bw drawing-count equality)."""
    import argparse
    scratch = tmp_path / "scratch"
    (scratch / "figures").mkdir(parents=True)
    for f in ("fig_a.pdf", "fig_b.pdf", "fig_unused.pdf", "fig_a_2026-08-14.pdf"):
        (scratch / "figures" / f).write_bytes(b"%PDF-1.4\n")
    calls = []

    def fake_run(argv, *, log=None, cwd=None, env=None):
        argv = [str(x) for x in argv]
        calls.append(argv)
        if argv[2] == "build":
            b = pathlib.Path(argv[argv.index("--build") + 1])
            b.mkdir(parents=True, exist_ok=True)
            (b / f"{argv[argv.index('--stem') + 1]}_red_report.json").write_text(json.dumps(
                {"figures": [{"file": "figures/fig_a.pdf"}, {"file": "figures/fig_b.pdf"}], "red_runs_text": []}))
        return 0, ""
    monkeypatch.setattr(fs, "_run", fake_run)
    out = tmp_path / "out"
    out.mkdir()
    a = argparse.Namespace(mode="M", repo=str(REPO), out=str(out), compile=str(tmp_path / "comp"),
                           build=str(tmp_path / "build"), october=str(tmp_path / "oct"), scratch=str(scratch),
                           reference=str(tmp_path / "ref.pdf"), stem="thesis_r1")
    assert fs.cmd_red(a) == 0
    verifies = [c for c in calls if c[2] == "verify"]
    first = verifies[0]
    figs = first[first.index("--figures") + 1:first.index("--reference")]
    assert figs == [str(scratch / "figures" / "fig_a.pdf"), str(scratch / "figures" / "fig_b.pdf")]
    assert "--figures" not in verifies[1]                    # the reference verify of the October PDF
    # no build report: no figure is passed (build_ok is then False, so RED_VERIFY_FAIL fires anyway)
    calls.clear()
    monkeypatch.setattr(fs, "_run", lambda argv, **kw: calls.append([str(x) for x in argv]) or (1, ""))
    out2 = tmp_path / "out2"
    out2.mkdir()
    fs.cmd_red(argparse.Namespace(**{**vars(a), "out": str(out2), "build": str(tmp_path / "build2")}))
    first = [c for c in calls if c[2] == "verify"][0]
    assert first[first.index("--figures") + 1:first.index("--reference")] == []
    assert json.loads((out2 / "red.json").read_text())["build_ok"] is False


# ---- finalb0-03: the October PDF compiled here against the author's reference PDF ----------------------
#: what red_diff verify measured (reference_verify.json "bw_vs_reference"): words differ on the contents page,
#: glyph boxes on it and on the three pages with typewriter text
MEASURED_REF = {"pages": [42, 42], "same_page_count": True, "words": [12960, 12960],
                "pages_with_different_words": [4], "pages_with_different_glyph_positions": [4, 11, 40, 42],
                "first_difference": [["replace", ["11"], ["10"]], ["replace", ["12"], ["11"]],
                                     ["replace", ["12"], ["11"]], ["replace", ["17"], ["16"]],
                                     ["replace", ["21"], ["20"]]], "identical": False}
STALE = [("Limitations of the Data", "10", "11"), ("Empirical Strategy", "11", "12"),
         ("Comparison, Models, and Estimation", "11", "12"),
         ("Assumptions, Concerns, and What the Estimates Do Not Identify", "16", "17"),
         ("How the Coefficients Are Computed: The 2016 Arrivals", "20", "21")]
EXPLAINED_REF = {"explained": True, "contents_page": 4,
                 "stale_contents_entries": [{"entry": e, "reference": r, "bw": b, "heading_page": b}
                                            for e, r, b in STALE],
                 "bitmap_typewriter_pages": [11, 40, 42], "bitmap_typewriter_glyphs": 625, "unexplained": []}


def _ref_verify(identical=False, explained=None):
    """A reference_verify.json: red_diff verify --reference (the October PDF here vs the author's)."""
    rep = {"bw_vs_reference": dict(MEASURED_REF, identical=identical),
           "checks": {"bw_same_pages_words_positions_as_reference": identical}}
    if explained is not None:
        rep["bw_vs_reference_explained"] = explained
        rep["checks"]["bw_same_as_reference_except_explained_differences"] = identical or explained["explained"]
    return rep


def test_reference_equal_only_when_identical_or_explained():
    """The author's TinyTeX PDF has a contents page one pass stale and bitmap typewriter glyphs; these, and only
    these, are explained (red_diff explain_reference_diff); anything else is still REFERENCE_PDF_DIFF."""
    assert fs.reference_equal(_ref_verify(identical=True)) is True
    assert fs.reference_equal(_ref_verify(explained=EXPLAINED_REF)) is True
    assert fs.reference_equal(_ref_verify()) is False                         # finalb0-03 as it ran
    left = dict(EXPLAINED_REF, explained=False, unexplained=["page 20: the words differ"])
    assert fs.reference_equal(_ref_verify(explained=left)) is False
    # the check alone, or the explanation alone, is not enough
    rep = _ref_verify(explained=EXPLAINED_REF)
    rep["bw_vs_reference_explained"] = dict(EXPLAINED_REF, unexplained=["page 4: x"])
    assert fs.reference_equal(rep) is False
    rep = _ref_verify(explained=EXPLAINED_REF)
    del rep["checks"]["bw_same_as_reference_except_explained_differences"]
    assert fs.reference_equal(rep) is False
    assert fs.reference_equal({}) is False


def test_red_records_the_explained_reference_difference(tmp_path, monkeypatch):
    import argparse

    def fake_run(argv, *, log=None, cwd=None, env=None):
        argv = [str(x) for x in argv]
        if argv[2] == "verify" and argv[argv.index("--report") + 1].endswith("reference_verify.json"):
            pathlib.Path(argv[argv.index("--report") + 1]).write_text(json.dumps(rep))
        return 0, ""
    monkeypatch.setattr(fs, "_run", fake_run)
    for rep, equal in ((_ref_verify(explained=EXPLAINED_REF), True), (_ref_verify(), False),
                       (_ref_verify(explained=dict(EXPLAINED_REF, explained=False, unexplained=["p"])), False)):
        out = tmp_path / f"out{int(equal)}{len(rep)}"
        out.mkdir()
        a = argparse.Namespace(mode="B0", repo=str(REPO), out=str(out), compile=str(tmp_path / "comp"),
                               build=str(tmp_path / "build"), october=str(tmp_path / "oct"),
                               scratch=str(tmp_path / "scr"), reference=str(tmp_path / "ref.pdf"), stem="thesis_r1")
        assert fs.cmd_red(a) == 0
        red = json.loads((out / "red.json").read_text())
        assert red["reference_equal"] is equal, rep
        assert red["reference_explained"] == rep.get("bw_vs_reference_explained")


def test_gate2_reports_the_explained_reference_difference_in_both_modes(m_inputs, b0_inputs):
    red = {"build_ok": True, "verify_ok": True, "reference_equal": True, "red_runs": [],
           "reference_explained": EXPLAINED_REF}
    for mode, inp, exp in (("M", dict(m_inputs, red=dict(red, red_runs=["0.039"])), None),
                           ("B0", dict(b0_inputs, red=red), fs.load_expected_b0(B0_EXPECTED))):
        v, codes, det = fs.gate2(inp, mode, exp)
        assert "REFERENCE_PDF_DIFF" not in codes and v in ("PASS", "PENDING_AUTHOR", "B0_PASS"), (mode, codes)
        assert det["reference_explained"] == EXPLAINED_REF
        v, codes, _ = fs.gate2(dict(inp, red=dict(inp["red"], reference_equal=False)), mode, exp)
        assert "REFERENCE_PDF_DIFF" in codes, mode


def test_a_failed_subcommand_prints_its_report_and_log_tail(toy_canon, capsys):
    """finalb0-01: a failed stage keeps no STAGE_OUT on S3, so its report and log must reach logs/<stage>.log."""
    t = toy_canon
    (t["sets"] / "s1.done.json").unlink()
    assert fs.main(t["argv"]) == 1
    printed = capsys.readouterr().out
    assert "--- canon.json" in printed and "MISSING_MARKER" in printed
    assert "--- canon.log" in printed


def test_final_stage_refuses_off_aws(monkeypatch, tmp_path):
    monkeypatch.delenv("SAR_HOST", raising=False)
    with pytest.raises(SystemExit, match="R1 rule"):
        fs.main(["gate2", "--mode", "M", "--out", str(tmp_path)])
    monkeypatch.setenv("SAR_HOST", "laptop")
    with pytest.raises(SystemExit, match="R1 rule"):
        fs.main(["texts", "--mode", "B0", "--out", str(tmp_path)])


# ---- the October replay keeps its own current tree (Codex fig7 #1, 2026-10-18) ------------------------------
OLD_CURRENT_SHA = "0bd23cbbcf8a39611c68fd94db5b1e31d782df15db2c9d50543bb77345ad2a13"   # tree_current before the edit


def test_finalb0_reads_its_own_pinned_current_tree():
    """The R1 Figure 7 caption edit (b5d2288a) is for canon M only. finalb0 replays October, whose numbers draw the
    arrow the old caption describes and whose expected red diff (final_b0_expected.json) is the old tree's, so its
    unpack, sentinel, repin and texts read role current_b0 (the 0bd23cbb tree); final keeps role current."""
    rec = json.loads((REPO / "config" / "r1" / "final_tree.json").read_text(encoding="utf-8"))
    assert rec["current_b0"]["tar_sha256"] == OLD_CURRENT_SHA != rec["current"]["tar_sha256"]
    assert {f: (v["BOR"], v["BORdel"]) for f, v in rec["current_b0"]["bor"]["files"].items()} == \
           {f: (v["BOR"], v["BORdel"]) for f, v in rec["current"]["bor"]["files"].items()}
    m, b = _rows("final"), _rows("finalb0")

    def sub_of(cmd):                                     # the final_stage.py subcommand a row runs
        return cmd.split('final_stage.py" ', 1)[1].split()[0] if 'final_stage.py" ' in cmd else None
    for job, rows, role in (("final", m, "current"), ("finalb0", b, "current_b0")):
        rows = {n: s for n, s in rows.items() if n not in ("tree_unpack_r1", "sentinel_r1")}
        unpack = [s for s in rows.values() if sub_of(s["cmd"]) == "unpack"]
        assert len(unpack) == 1 and f"--current-role {role} " in unpack[0]["cmd"], job
        roles = [s["cmd"].split("--role ", 1)[1].split()[0] for s in rows.values() if "--role " in s["cmd"]]
        assert len(roles) == 3 and set(roles) == {role}, (job, roles)     # sentinel, repin, texts




def test_paper_stage_keeps_going_and_keeps_each_failed_log(tmp_path, monkeypatch):
    """final-02: the paper stage runs run_all with KEEP_GOING=1, and on a failure it copies the tail of every
    failed step's log into failures.log, which the stage log prints in full (a failed stage pushes nothing else)."""
    import argparse
    repo, out = tmp_path / "repo", tmp_path / "out"
    (repo / "output" / "logs").mkdir(parents=True)
    out.mkdir()
    (repo / "output" / "logs" / "paper_x.log").write_text("Traceback\nAssertionError: boom\n", encoding="utf-8")
    calls = []

    def fake_run(argv, *, log=None, cwd=None, env=None):
        calls.append((list(map(str, argv)), env))
        if str(argv[0]) == "bash":
            return 2, "== x\nFAILED, see output/logs/paper_x.log\nFAILED_STEPS paper_x\n"
        return 0, "M\n"
    monkeypatch.setattr(fs, "_run", fake_run)
    a = argparse.Namespace(mode="M", repo=str(repo), out=str(out), paths=str(tmp_path / "p.yaml"),
                           run_stages="1,3est,3light")
    assert fs.cmd_paper(a) == 1
    assert calls[1][0][:2] == ["bash", "analysis/run_all.sh"] and calls[1][1]["KEEP_GOING"] == "1"
    fl = (out / "failures.log").read_text(encoding="utf-8")
    assert "output/logs/paper_x.log" in fl and "AssertionError: boom" in fl
    big = out / "failures.log"
    big.write_text("\n".join(f"line {i}" for i in range(300)) + "\n", encoding="utf-8")
    import contextlib, io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fs.echo_failure(out)
    assert "line 0" in buf.getvalue() and "line 299" in buf.getvalue()      # printed whole, not the last 60



def test_gate2_p_keys_are_read_from_the_checkout_when_final_stage_runs_as_a_copy(tmp_path, monkeypatch):
    """Round-2 review #1: on an instance run_stages copies final_stage.py to $WORK (/work), so the checkout's
    tools/r1_number_diff.py is found from $REPO_DIR, never from the copy's own parents; without either it stops
    with a plain message."""
    import importlib.util
    work = tmp_path / "work"
    work.mkdir()
    shutil.copy2(REPO / "pipeline" / "aws" / "r1" / "final_stage.py", work / "final_stage.py")
    spec = importlib.util.spec_from_file_location("final_stage_copy", work / "final_stage.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setenv("REPO_DIR", str(REPO))
    assert mod._is_p_key("p1_econ.p_joint_placebo_person") and not mod._is_p_key("p1_econ.ate_log")
    mod._NUMBER_DIFF = None
    monkeypatch.delenv("REPO_DIR")
    with pytest.raises(FileNotFoundError, match="r1_number_diff.py"):
        mod._is_p_key("p1_econ.p_joint_placebo_person")


def test_gate2_rows_list_the_number_diff_they_read():
    """Round-2 review #2: gate 2 reads tools/r1_number_diff.py (is_p_key), so the file is an input and a
    requirement of the gate2 row in both twins; its fingerprint follows the file."""
    for job in ("final", "finalb0"):
        g = _rows(job)["gate2"]
        assert "repo:tools/r1_number_diff.py" in g["inputs"] and "tools/r1_number_diff.py" in g["requires"], job


# ---- M2 round 3 (Codex STOP 2): Figure 1's blocks leave the caption's 'rows of ten' -------------------------------
BASE_SEC2 = REPO / "tests" / "fixtures" / "r1_paper" / "base_tree_2026-10-11" / "sections" / "sec2_data.tex"
FIG_EXC = {"rows_of": 10, "serpentine": ["CA", "CH", "DE", "FR", "NZ"], "wide": {"GB": 20}}
FIG_CAP = {"file": "sections/sec2_data.tex", "line": 77,
           "sentence": "Each dot is one star, placed on the country of their last post abroad and grouped in rows of ten; "
                       "the boxed area is enlarged below, and triangles mark the Australian cities they moved to."}


def test_gate2_sends_a_changed_figure_rule_to_the_author(m_inputs):
    """At M's counts Figure 1 draws the UK block in rows of 20 (and fills five blocks serpentine), but the caption
    says 'grouped in rows of ten'. The figure ledger lists the exceptions; gate 2 sends them, with the caption
    sentence, to the author (FIGURE_RULE_CHANGED, pending) and never rewrites the caption. No exceptions (October):
    nothing. B0 reads none of this."""
    v, codes, det = fs.gate2(dict(m_inputs, figure_exceptions=FIG_EXC, figure_caption=FIG_CAP), "M", None)
    assert (v, codes) == ("PENDING_AUTHOR", ["FIGURE_RULE_CHANGED"]), det
    assert det["figure_rule"] == [{"caption": FIG_CAP, "exceptions": FIG_EXC}]
    assert fs.final_report("M", v, codes, det)["counts"]["figure_rule"] == 1
    assert "FIGURE_RULE_CHANGED" in fs.PENDING_CODES and "FIGURE_RULE_CHANGED" not in fs.HARD_CODES
    v, codes, det = fs.gate2(m_inputs, "M", None)
    assert (v, codes, det["figure_rule"]) == ("PASS", [], [])
    exp = fs.load_expected_b0(B0_EXPECTED)
    v, codes, det = fs.gate2(dict(_b0_from(m_inputs), figure_exceptions=FIG_EXC, figure_caption=FIG_CAP), "B0", exp)
    assert (v, codes) == ("B0_PASS", []) and "figure_rule" not in det


def test_figure_caption_names_the_rows_sentence_of_the_base_tree(tmp_path):
    """figure_caption finds the caption of the figure that includes fig_star_origins and names its sentence about
    the rows; a tree without the figure gives None."""
    tree = tmp_path / "tree"
    (tree / "sections").mkdir(parents=True)
    (tree / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    assert fs.figure_caption(tree) is None
    shutil.copy2(BASE_SEC2, tree / "sections" / "sec2_data.tex")
    assert fs.figure_caption(tree) == FIG_CAP
    # the ledger key gate 2 reads is the one the figure generator writes
    src = (REPO / "analysis" / "paper" / "fig_star_origins.py").read_text(encoding="utf-8")
    assert re.search(r'^FIGURE_EXCEPTIONS_KEY = "([^"]+)"', src, re.M).group(1) == fs.FIGURE_EXC_KEY


def test_gate2_stage_reads_the_figure_ledger_and_never_rewrites_the_caption(tmp_path, monkeypatch):
    """_collect (M) reads output_paper/data_numbers_star_origins.json and, when it lists exceptions, the caption from
    the scratch tree; cmd_gate2 puts both into change_facts.json. The caption file is left as it was. October's
    ledger (no key) gives nothing; a missing ledger or a malformed key is REPORT_MISSING."""
    monkeypatch.setattr(fs, "_run", lambda argv, **kw: (1, ""))          # no packer here: PACK_FAIL, fine
    a = _stage_args(tmp_path)
    op, scr = pathlib.Path(a.output_paper), pathlib.Path(a.scratch)
    (op / "draft_2026_09_13").mkdir(parents=True)
    (op / "draft_2026_09_13" / "NOTE_CHECKS.json").write_text(json.dumps([NOTE_OK]))
    (scr / "sections").mkdir(parents=True)
    shutil.copy2(BASE_SEC2, scr / "sections" / "sec2_data.tex")
    before = (scr / "sections" / "sec2_data.tex").read_bytes()
    led = op / "data_numbers_star_origins.json"
    october = {"_figure_rule": "rows of 10", "figure_text": [], "figure_size_cm": [15.0, 12.0]}
    led.write_text(json.dumps(dict(october, figure_block_exceptions=FIG_EXC)))
    (tmp_path / "out").mkdir()
    inp = fs._collect(a, "M")
    assert (inp["figure_exceptions"], inp["figure_caption"]) == (FIG_EXC, FIG_CAP)
    assert "output_paper/data_numbers_star_origins.json" not in inp["reports_missing"]
    assert fs.cmd_gate2(a) == 1                                        # many reports absent in this toy
    facts = json.loads((tmp_path / "out" / "change_facts.json").read_text())
    assert facts["figure_rule"] == [{"caption": FIG_CAP, "exceptions": FIG_EXC}] and "FIGURE_RULE_CHANGED" in facts["codes"]
    assert (scr / "sections" / "sec2_data.tex").read_bytes() == before
    led.write_text(json.dumps(october))
    inp = fs._collect(a, "M")
    assert "figure_exceptions" not in inp and "output_paper/data_numbers_star_origins.json" not in inp["reports_missing"]
    led.write_text(json.dumps(dict(october, figure_block_exceptions={"rows_of": 10, "wide": ["GB"], "serpentine": []})))
    assert "output_paper/data_numbers_star_origins.json" in fs._collect(a, "M")["reports_missing"]
    led.unlink()
    assert "output_paper/data_numbers_star_origins.json" in fs._collect(a, "M")["reports_missing"]



def test_gate2_flags_the_figure_rule_only_when_a_block_leaves_rows_of_ten(m_inputs):
    """Round-3 review #2: a serpentine fill keeps the caption's 'grouped in rows of ten' true, so a run whose only
    exceptions are serpentine blocks sends nothing; a block in wider rows (M's UK block, 20 per row) does."""
    serp = {"rows_of": 10, "serpentine": ["CA", "NZ"], "wide": {}}
    v, codes, det = fs.gate2(dict(m_inputs, figure_exceptions=serp, figure_caption=FIG_CAP), "M", None)
    assert (v, codes, det["figure_rule"]) == ("PASS", [], [])
    v, codes, det = fs.gate2(dict(m_inputs, figure_exceptions=FIG_EXC, figure_caption=FIG_CAP), "M", None)
    assert codes == ["FIGURE_RULE_CHANGED"] and det["figure_rule"][0]["exceptions"]["wide"] == FIG_EXC["wide"]


def test_gate2_sends_check_paper_label_conflicts_to_the_author(m_inputs):
    """final-05: repin.py exits 1 when two check_paper pins want different new numbers in one pin label. A label
    is a pin's name, not paper text, so the stage goes on (as with replace.py's rc 1) and gate 2 lists each
    conflict as pending (PIN_LABEL_CONFLICT); B0 has no changed pin, so no conflict."""
    conf = [{"line": 620, "old": "sec2_data subfields per discipline: chem 6", "pins": ["a", "b"],
             "reason": "pins disagree on the new label"}]
    v, codes, det = fs.gate2(dict(m_inputs, label_conflicts=conf), "M", None)
    assert (v, codes) == ("PENDING_AUTHOR", ["PIN_LABEL_CONFLICT"]) and det["label_conflicts"] == conf
    assert "PIN_LABEL_CONFLICT" in fs.PENDING_CODES and fs.final_report("M", v, codes, det)["counts"]["label_conflicts"] == 1
    v, codes, det = fs.gate2(m_inputs, "M", None)
    assert (v, codes, det["label_conflicts"]) == ("PASS", [], [])


def test_repin_rc_1_with_a_report_is_gate2s_call(tmp_path):
    """repin.py's rc 1 (label CONFLICT) with its report written goes on to gate 2; any other rc, or no report,
    stops the stage."""
    rep = tmp_path / "repin_report.json"
    assert not fs.repin_rc_ok(0, rep) and not fs.repin_rc_ok(1, rep)
    rep.write_text("{}", encoding="utf-8")
    assert fs.repin_rc_ok(0, rep) and fs.repin_rc_ok(1, rep) and not fs.repin_rc_ok(2, rep)
