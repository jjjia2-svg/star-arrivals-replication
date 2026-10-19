# -*- coding: utf-8 -*-
"""pipeline/lib/r1_config.py + pipeline/aws/r1/config_check.py - F9: one run config, and a STOP on any
missing, unsigned or contradicted ruling, an unknown or missing switch, or a B0 switch at its on value.

B0.json is October: every switch at its off value. The M fixture (tests/fixtures/r1_config/M_min.json)
stands in for W2-CONFIGM's M.json. Tests that change a signed list do it in a tmp copy of the files the
config names (`_repo_copy`) and load against that copy with `load(..., repo=tmp)`.
"""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import re
import shutil
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from pipeline.lib import r1_config as rc  # noqa: E402

B0 = REPO / "config" / "r1" / "B0.json"
COUNTS_B0 = REPO / "config" / "r1" / "counts_B0.json"
M_FIXTURE = REPO / "tests" / "fixtures" / "r1_config" / "M_min.json"
INPUTS = "data/cal2026-10r1/inputs"
FLIPS = REPO / INPUTS / "flips_r1.json"
SUMMARY_REL = f"{INPUTS}/add_list_r1_summary.json"
FIELDS = ("econ", "chemistry", "math_stats")
B0_DECIDED = "B0: October (tag cal-2026-10)"
H8_STAR, H9_STAR = "A5008470795", "A5001177483"

#: the frozen registry (this wave): name -> (B0 off value, M on value, owner). A rename or a new row
#: is a J0 rerun, so this test spells the registry out rather than reading it back from the module.
EXPECTED_SWITCHES = {
    "verdict_source": ("october", "signed", "F16/F17/F10"),
    "own_field_rank": ("off", "field_topic", "V3-RANK"),
    "label_fix": ("off", "pass_C", "V3-RANK/F17"),
    "p05_label_fix": ("off", "pctC_0.95_celln_30", "F17"),
    "network_freeze": ("off", "both_hops_le_T-1", "V3-NET"),
    "chemmath_edges": ("u1_edges_full_2026-07-05", "u1_full_11school_2026-07-16", "N2"),
    "new_stars": ("off", "add_list_r1", "F10"),
    "redates": ("off", "signed", "F10/F11"),
    "calls": ("october", "r1", "F8"),
    "dose_excludes": ("off", "not_this_person", "F8/F13/F14"),
    "dose_mode": ("october", "delta", "F13/F14"),
    "add_backs": ("off", "on", "F13/F14"),
    "rosters": ("october", "r1", "P3a/F11/F14"),
    "departure_ledger": ("0910", "r1", "F20"),
    "agg_missing": ("report", "stop", "N3"),
    "patch_raw": ("none", "r1", "F18"),
    "p_full_precision": ("off", "on", "N12"),
}
EXPECTED_RULINGS = ("h1", "h2", "h3", "h4", "h5", "h6", "h7", "h8", "h9", "h12", "h15", "C5", "C7", "C10",
                    "C11", "C13", "F12", "M_rerun", "own_field", "label_fix", "decision_2", "decision_3",
                    "decision_4", "decision_5", "gdose_override")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("SAR_R1_CONFIG", "SAR_R1_COUNTS"):
        monkeypatch.delenv(k, raising=False)


def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _json(p: pathlib.Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _b0() -> dict:
    return _json(B0)


def _write(tmp_path, cfg, name="cfg.json") -> pathlib.Path:
    p = tmp_path / name
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def _ruling(cfg, rid) -> dict:
    return next(r for r in cfg["rulings"] if r["id"] == rid)


def _switch_row(cfg, name) -> dict:
    return next(r for r in cfg["switches"] if r["switch"] == name)


def _stop(path, repo=REPO) -> str:
    with pytest.raises(rc.ConfigStop) as e:
        rc.load(path, repo=repo)
    return e.value.code


def _rels(cfg) -> set[str]:
    """Every repo file a config names: pins, signed lists and inputs."""
    rels = set(cfg.get("pins", {}))
    for tok in list(cfg.get("inputs", [])) + list(cfg.get("signed", {}).values()):
        rels.add(tok.split(":", 1)[1])
    return rels


def _repo_copy(tmp_path, cfg, name="repo") -> pathlib.Path:
    """A tmp repo holding a copy of every file the config names, at the same relative paths."""
    root = tmp_path / name
    for rel in _rels(cfg):
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / rel, dst)
    return root


def _repin(cfg, root) -> dict:
    cfg["pins"] = {rel: _sha(root / rel) for rel in cfg["pins"]}
    return cfg


def _edit_json(path: pathlib.Path, fn) -> None:
    d = _json(path)
    fn(d)
    path.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def _m(root=REPO) -> dict:
    """The M fixture with B0's rulings and pins computed on the files under `root`."""
    cfg = _json(M_FIXTURE)
    cfg["rulings"] = _b0()["rulings"]
    return _repin(cfg, root)


def _m_ok_repo(tmp_path, name="repo") -> tuple[dict, pathlib.Path]:
    """A tmp repo whose add-list summary says OK (what P3a's rosters will produce), and M pinned to it."""
    cfg = _m()
    root = _repo_copy(tmp_path, cfg, name)
    _edit_json(root / SUMMARY_REL, lambda d: d.update(result="OK", roster_gaps=[]))
    return _repin(cfg, root), root


# --- B0 ---------------------------------------------------------------------------------------------
def test_b0_loads_with_every_switch_off_and_every_ruling_signed(monkeypatch):
    assert {k: (v["off"], v["on"], v["owner"]) for k, v in rc.SWITCHES.items()} == EXPECTED_SWITCHES
    assert tuple(rc.REQUIRED_RULINGS) == EXPECTED_RULINGS

    c = rc.load(B0)
    raw = _b0()
    assert raw["schema"] == "sar.r1.run_config.v1" and c.name == "B0" and c.sha256 == _sha(B0)
    assert [r["switch"] for r in raw["switches"]] == list(EXPECTED_SWITCHES)
    for name, (off, _on, owner) in EXPECTED_SWITCHES.items():
        assert c.switch(name) == off and not c.is_on(name), name
        row = _switch_row(raw, name)
        assert row["decided"] == B0_DECIDED and row["owner"] == owner, name
    for rid in EXPECTED_RULINGS:
        r = _ruling(raw, rid)
        assert r["value"] and r["decided"].strip() and r["source"].strip(), rid
    assert (c.ruling("h5"), c.ruling("h6"), c.ruling("gdose_override")) == ("dropped", "delta", "pass_h4")
    assert (c.ruling("F12"), c.ruling("M_rerun")) == ("no", "no")
    assert c.ruling("h8") == c.ruling("h9") == "superseded by flips_r1.json"

    # decisions 2-5 name their entry in the R1 decision record (not shipped)
    for n in (2, 3, 4, 5):
        assert f"decision {n}" in _ruling(raw, f"decision_{n}")["source"], n

    # the signed files B0 cross-checks are exactly what it pins
    assert set(raw["pins"]) == {v.split(":", 1)[1] for v in raw["signed"].values()}
    assert raw["expect"]["counts"] == _json(COUNTS_B0)["events"]

    # load_env: $SAR_R1_CONFIG unset is a STOP, never a default
    with pytest.raises(rc.ConfigStop) as e:
        rc.load_env()
    assert e.value.code == "UNSET"
    monkeypatch.setenv("SAR_R1_CONFIG", str(B0))
    assert rc.load_env().name == "B0"
    monkeypatch.setenv("SAR_R1_CONFIG", "config/r1/B0.json")      # repo-relative works too
    assert rc.load_env().sha256 == _sha(B0)


def test_an_unsigned_or_missing_ruling_stops(tmp_path):
    for rid in ("h1", "h15", "C10", "decision_5", "gdose_override"):
        cfg = _b0()
        _ruling(cfg, rid)["decided"] = "  "
        assert _stop(_write(tmp_path, cfg)) == "UNSIGNED", rid
        cfg = _b0()
        _ruling(cfg, rid)["value"] = ""
        assert _stop(_write(tmp_path, cfg)) == "UNSIGNED", rid
        cfg = _b0()
        del _ruling(cfg, rid)["source"]
        assert _stop(_write(tmp_path, cfg)) == "UNSIGNED", rid
        cfg = _b0()
        cfg["rulings"] = [r for r in cfg["rulings"] if r["id"] != rid]
        assert _stop(_write(tmp_path, cfg)) == "MISSING_RULING", rid
    cfg = _b0()
    _switch_row(cfg, "calls")["decided"] = ""
    assert _stop(_write(tmp_path, cfg)) == "UNSIGNED"
    cfg = _b0()
    _switch_row(cfg, "calls")["decided"] = "someone thought October was fine"
    assert _stop(_write(tmp_path, cfg)) == "UNSIGNED"
    assert rc.load(_write(tmp_path, _b0())).name == "B0"          # control: the unedited copy loads


def test_a_ruling_that_contradicts_the_signed_file_stops(tmp_path):
    edits = {
        "C10": lambda r: r.update(value="old79/new37 run in B0 and M"),
        "C5": lambda r: r.update(value="second hop any year"),
        "F12": lambda r: r.update(value="yes"),
        "M_rerun": lambda r: r.update(value="yes"),
        "label_fix": lambda r: r.update(value="pass_B"),
    }
    for rid, fn in edits.items():
        cfg = _b0()
        fn(_ruling(cfg, rid))
        assert _stop(_write(tmp_path, cfg)) == "MISMATCH_SIGNED", rid
    for key, bad in (("scope", "star_only"), ("age_basis", "pre_arrival"), ("rank", "option_b")):
        cfg = _b0()
        _ruling(cfg, "own_field")["value"][key] = bad
        assert _stop(_write(tmp_path, cfg)) == "MISMATCH_SIGNED", key
    for f, code in (("econ", "14"), ("math_stats", "17")):
        cfg = _b0()
        _ruling(cfg, "own_field")["value"]["field_code"][f] = code
        assert _stop(_write(tmp_path, cfg)) == "MISMATCH_SIGNED", f

    # the signed file changes under an unchanged config: C10 is no longer the v3 ruling
    cfg = _b0()
    root = _repo_copy(tmp_path, cfg)
    assert rc.load(_write(tmp_path, cfg), repo=root).name == "B0"   # control: the untouched copy loads
    _edit_json(root / INPUTS / "p2_decisions.json", lambda d: d["c_rulings"].update(C10="v2"))
    assert _stop(_write(tmp_path, cfg), repo=root) == "PIN_MISMATCH"   # not re-pinned: the pin catches it
    assert _stop(_write(tmp_path, _repin(cfg, root)), repo=root) == "MISMATCH_SIGNED"

    # rulings_p1 says another field code for chemistry
    cfg = _b0()
    root = _repo_copy(tmp_path, cfg, "repo2")
    _edit_json(root / INPUTS / "rulings_p1.json", lambda d: d["own_field"]["field_code"].update(chemistry="15"))
    assert _stop(_write(tmp_path, _repin(cfg, root)), repo=root) == "MISMATCH_SIGNED"

    # a signed file that is not pinned is refused
    cfg = _b0()
    cfg["pins"].pop(f"{INPUTS}/rulings_p1.json")
    assert _stop(_write(tmp_path, cfg)) == "PIN_MISMATCH"


def test_unknown_missing_or_b0_on_switch_stops(tmp_path):
    cfg = _b0()
    cfg["switches"].append({"switch": "anu_centres", "value": "off", "decided": B0_DECIDED, "owner": "P3a"})
    assert _stop(_write(tmp_path, cfg)) == "UNKNOWN_SWITCH"
    cfg = _b0()
    cfg["switches"].append(dict(_switch_row(cfg, "calls")))
    assert _stop(_write(tmp_path, cfg)) == "UNKNOWN_SWITCH"           # a duplicate row
    cfg = _b0()
    _switch_row(cfg, "dose_mode")["value"] = "sometimes"
    assert _stop(_write(tmp_path, cfg)) == "UNKNOWN_SWITCH"           # neither the off nor the on value
    cfg = _b0()
    _switch_row(cfg, "dose_mode")["owner"] = "F99"
    assert _stop(_write(tmp_path, cfg)) == "UNKNOWN_SWITCH"           # the row is not the registry's
    cfg = _b0()
    cfg["switches"] = [r for r in cfg["switches"] if r["switch"] != "calls"]
    assert _stop(_write(tmp_path, cfg)) == "MISSING_SWITCH"
    for name, (_off, on, _owner) in EXPECTED_SWITCHES.items():
        cfg = _b0()
        _switch_row(cfg, name)["value"] = on
        assert _stop(_write(tmp_path, cfg)) == "B0_SWITCH_ON", name
    c = rc.load(B0)
    with pytest.raises(rc.ConfigStop) as e:
        c.switch("anu_centres")
    assert e.value.code == "UNKNOWN_SWITCH"


# --- M ----------------------------------------------------------------------------------------------
def test_m_refuses_an_add_list_that_is_not_ok(tmp_path):
    committed = _json(REPO / SUMMARY_REL)["result"]
    cfg = _write(tmp_path, _m(), "m_committed.json")
    if committed == "OK":
        assert rc.load(cfg).name == "M"
    else:                                                             # today: ROSTER_GAP (7 gaps)
        assert _stop(cfg) == "ADD_LIST_NOT_OK"

    cfg, root = _m_ok_repo(tmp_path)
    c = rc.load(_write(tmp_path, cfg), repo=root)
    assert c.name == "M"
    for name, (off, on, _owner) in EXPECTED_SWITCHES.items():
        assert c.switch(name) == on and c.is_on(name), name

    for result in ("ROSTER_GAP", "", None):
        _edit_json(root / SUMMARY_REL, lambda d: d.update(result=result))
        assert _stop(_write(tmp_path, _repin(cfg, root)), repo=root) == "ADD_LIST_NOT_OK", result
    _edit_json(root / SUMMARY_REL, lambda d: d.pop("result"))
    assert _stop(_write(tmp_path, _repin(cfg, root)), repo=root) == "ADD_LIST_NOT_OK"

    cfg, root = _m_ok_repo(tmp_path, "repo_unsigned")
    del cfg["signed"]["add_list_summary"]
    assert _stop(_write(tmp_path, cfg), repo=root) == "ADD_LIST_NOT_OK"   # M without its summary


def test_m_refuses_an_undecided_verdict_row(tmp_path):
    cfg, root = _m_ok_repo(tmp_path)
    assert rc.load(_write(tmp_path, cfg), repo=root).name == "M"        # control
    flips = root / INPUTS / "flips_r1.json"
    adds = root / INPUTS / "add_list_r1.json"
    i = next(k for k, r in enumerate(_json(flips)["rows"]) if r["person_id"] not in (H8_STAR, H9_STAR))
    original_flips, original_adds = flips.read_bytes(), adds.read_bytes()
    cases = [
        (flips, lambda d: d["rows"][i].update(decided="")),
        (flips, lambda d: d["rows"][i].pop("decided")),
        (flips, lambda d: d["rows"][i].update(verdict="MAYBE")),
        (flips, lambda d: d["rows"][i].update(verdict="ACCEPT")),       # the add-list vocabulary
        (adds, lambda d: d["rows"][0].update(decided="  ")),
        (adds, lambda d: d["rows"][-1].update(verdict="KEEP")),         # the flips vocabulary
    ]
    for path, fn in cases:
        flips.write_bytes(original_flips)
        adds.write_bytes(original_adds)
        _edit_json(path, fn)
        assert _stop(_write(tmp_path, _repin(cfg, root)), repo=root) == "UNDECIDED_ROW", path.name


# --- h8 / h9 ----------------------------------------------------------------------------------------
def test_h8_h9_are_the_signed_flips(tmp_path):
    raw = _b0()
    rows = {r["person_id"]: r for r in _json(FLIPS)["rows"]}
    for rid, pid in (("h8", H8_STAR), ("h9", H9_STAR)):
        r = _ruling(raw, rid)
        assert r["value"] == "superseded by flips_r1.json", rid
        assert "flips_r1.json" in r["source"] and pid in r["source"], rid
        assert rows[pid]["verdict"] == "KEEP", rid
    assert raw["signed"]["flips"] == f"repo:{INPUTS}/flips_r1.json"

    cfg = _b0()
    _ruling(cfg, "h9")["value"] = "drop A5001177483 at 0.927"
    assert _stop(_write(tmp_path, cfg)) == "MISMATCH_SIGNED"

    for pid, name in ((H8_STAR, "repo_h8"), (H9_STAR, "repo_h9")):
        cfg = _b0()
        root = _repo_copy(tmp_path, cfg, name)

        def drop(d, pid=pid):
            next(r for r in d["rows"] if r["person_id"] == pid).update(verdict="DROP")
        _edit_json(root / INPUTS / "flips_r1.json", drop)
        assert _stop(_write(tmp_path, _repin(cfg, root)), repo=root) == "MISMATCH_SIGNED", pid


# --- counts -----------------------------------------------------------------------------------------
def test_counts_b0_matches_the_october_tables(tmp_path, monkeypatch):
    counts = _json(COUNTS_B0)
    assert counts == {"schema": "sar.r1.counts.v1", "config": "B0",
                      "events": {"econ": 113, "chemistry": 38, "math_stats": 33},
                      "events_total": 184, "candidates": 187}
    for f in FIELDS:
        with open(REPO / "data" / "cal2026-10" / f"events_{f}_cal2026-10.csv", newline="", encoding="utf-8") as fh:
            assert counts["events"][f] == sum(1 for _ in csv.DictReader(fh)), f
    assert counts["events_total"] == sum(counts["events"].values())
    assert counts["candidates"] == len(_json(FLIPS)["rows"])

    assert rc.counts() == counts                                       # default: the committed B0 file
    other = dict(counts, config="M", events={"econ": 1, "chemistry": 2, "math_stats": 3}, events_total=6)
    p = _write(tmp_path, other, "counts_M.json")
    monkeypatch.setenv("SAR_R1_COUNTS", str(p))
    assert rc.counts() == other
    assert rc.counts(COUNTS_B0) == counts                              # an explicit path wins

    for bad in (dict(other, events_total=7), dict(other, schema="sar.r1.counts.v0"),
                {k: v for k, v in other.items() if k != "candidates"}):
        monkeypatch.setenv("SAR_R1_COUNTS", str(_write(tmp_path, bad, "counts_bad.json")))
        with pytest.raises(rc.ConfigStop) as e:
            rc.counts()
        assert e.value.code == "BAD_SCHEMA"
    monkeypatch.setenv("SAR_R1_COUNTS", str(tmp_path / "absent.json"))
    with pytest.raises(rc.ConfigStop) as e:
        rc.counts()
    assert e.value.code == "MISSING_INPUT"


# --- paths ------------------------------------------------------------------------------------------
def test_paths_resolve_repo_and_work_tokens_and_refuse_absolute(tmp_path, monkeypatch):
    cfg = _b0()
    cfg["sections"]["probe"] = {"a": "repo:data/cal2026-10", "b": ["repo:x/y.csv", "work:prod/z"],
                                "nested": {"c": "work:tmp/q"}, "label": "plain text (returned raw)", "n": 3}
    p = _write(tmp_path, cfg)
    monkeypatch.delenv("SAR_HOST", raising=False)
    c = rc.load(p)                                                     # loading resolves nothing on $WORK
    assert c.section("probe")["b"] == ["repo:x/y.csv", "work:prod/z"]  # raw
    assert c.path("probe", "a") == REPO / "data" / "cal2026-10"
    with pytest.raises(rc.ConfigStop) as e:                            # work: is refused off an R1 host
        c.resolved("probe")
    assert e.value.code == "BAD_PATH"
    monkeypatch.setenv("SAR_HOST", "laptop")
    with pytest.raises(rc.ConfigStop) as e:
        c.resolved("probe")
    assert e.value.code == "BAD_PATH"

    work = tmp_path / "w"
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")
    monkeypatch.setenv("WORK", str(work))
    r = c.resolved("probe")
    assert r == {"a": REPO / "data" / "cal2026-10", "b": [REPO / "x" / "y.csv", work / "prod" / "z"],
                 "nested": {"c": work / "tmp" / "q"}, "label": "plain text (returned raw)", "n": 3}
    for key in ("label", "nested", "n"):
        with pytest.raises(rc.ConfigStop) as e:
            c.path("probe", key)                                       # a label (or a dict, a number) is not a path
        assert e.value.code == "BAD_PATH", key
    monkeypatch.delenv("WORK")
    with pytest.raises(rc.ConfigStop) as e:
        c.resolved("probe")
    assert e.value.code == "BAD_PATH"

    # load(repo=...) resolves repo: tokens against that root
    root = _repo_copy(tmp_path, cfg)
    assert rc.load(p, repo=root).path("probe", "a") == root / "data" / "cal2026-10"

    for bad in ("repo:/etc/hosts", "repo:../outside", "work:a/../../b", "/abs/path", "~/x", "repo:",
                "x/../y", "file:data/x", "wrok:prod/x"):
        cfg2 = _b0()
        cfg2["sections"]["probe"] = {"x": [bad]}
        assert _stop(_write(tmp_path, cfg2)) == "BAD_PATH", bad
    cfg2 = _b0()
    cfg2["inputs"].append("repo:../x")
    assert _stop(_write(tmp_path, cfg2)) == "BAD_PATH"
    cfg2 = _b0()
    cfg2["inputs"].append("work:prod/x")                               # inputs live in the repo
    assert _stop(_write(tmp_path, cfg2)) == "BAD_PATH"
    cfg2 = _b0()
    cfg2["pins"]["/etc/hosts"] = "0" * 64
    assert _stop(_write(tmp_path, cfg2)) == "BAD_PATH"
    cfg2 = _b0()
    cfg2["inputs"].append("repo:data/no/such/file.csv")
    assert _stop(_write(tmp_path, cfg2)) == "MISSING_INPUT"
    assert _stop(tmp_path / "no_such_config.json") == "MISSING_INPUT"


def test_b0_stage_section_matches_octobers_restake_source():
    c = rc.load(B0)
    st = c.resolved("stage")                                           # B0's stage section has no work: token
    report = _json(REPO / "data/cal2026-10/frames_econ/build_report_econ920_2026-10.json")
    recorded = report["october"]["regeneration"]["u4_aug"]["restake_source"]
    assert st["restake_label"] == recorded
    assert recorded.split(" ", 1)[0] == st["restake_csv"].relative_to(REPO).as_posix()
    assert st == {
        "restake_csv": REPO / "data/cal2026-08-28/restake_2026-08-28.csv",
        "restake_label": recorded,
        "names_csvs": [REPO / "data/cal2026-08-28/verdicts_2026-08-28.csv"],
        "events_root": REPO / "data/cal2026-10",
        "restake_econ_aug": REPO / "data/cal2026-10/restake_econ11_aug_2026-10.csv",
        "roster_added": REPO / "data/cal2026-10/roster_added_2026-10.csv",
    }
    for k in ("restake_csv", "restake_econ_aug", "roster_added"):
        assert st[k].is_file(), k
    assert all(p.is_file() for p in st["names_csvs"])
    for f in FIELDS:
        assert (st["events_root"] / f"events_{f}_cal2026-10.csv").is_file(), f
    # October chose the 08-28 tables because the October ones were absent; B0 names that choice
    assert not (REPO / "data/cal2026-10/restake_2026-10.csv").exists()
    assert not (REPO / "data/cal2026-10/verdicts_2026-10.csv").exists()
    # every stage file is a declared input, so a missing one STOPs at load
    declared = {t.split(":", 1)[1] for t in _b0()["inputs"]}
    for v in (st["restake_csv"], st["restake_econ_aug"], st["roster_added"], *st["names_csvs"]):
        assert v.relative_to(REPO).as_posix() in declared


# --- the instance CLI -------------------------------------------------------------------------------
def test_config_check_cli_refuses_off_host_and_writes_resolved(tmp_path, monkeypatch):
    sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
    try:
        import config_check as cc
    finally:
        sys.path.remove(str(REPO / "pipeline" / "aws" / "r1"))

    out = tmp_path / "out"
    monkeypatch.delenv("SAR_HOST", raising=False)
    with pytest.raises(SystemExit):
        cc.main(["check", "--config", str(B0), "--out", str(out), "--repo", str(REPO)])
    assert not out.exists()

    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")
    monkeypatch.setenv("WORK", str(tmp_path / "w"))
    assert cc.main(["check", "--config", str(B0), "--out", str(out), "--repo", str(REPO)]) == 0
    resolved = _json(out / "resolved.json")
    assert resolved["config"] == "B0" and resolved["sha256"] == _sha(B0)
    stage = resolved["sections"]["stage"]
    assert stage["restake_csv"] == str(REPO / "data/cal2026-08-28/restake_2026-08-28.csv")
    assert stage["names_csvs"] == [str(REPO / "data/cal2026-08-28/verdicts_2026-08-28.csv")]
    report = _json(out / "config_report.json")
    assert report["result"] == "OK" and report["code"] is None and report["config"] == "B0"
    assert report["counts"]["switches"] == len(EXPECTED_SWITCHES) and report["counts"]["switches_on"] == 0
    assert report["counts"]["rulings"] >= len(EXPECTED_RULINGS)
    names = [r["name"] for r in _json(FLIPS)["rows"] if r.get("name")]
    text = (out / "resolved.json").read_text(encoding="utf-8") + (out / "config_report.json").read_text(encoding="utf-8")
    assert names and sum(n in text for n in names) == 0

    bad = _b0()
    _switch_row(bad, "network_freeze")["value"] = "both_hops_le_T-1"
    out2 = tmp_path / "out2"
    assert cc.main(["check", "--config", str(_write(tmp_path, bad)), "--out", str(out2), "--repo", str(REPO)]) == 3
    report = _json(out2 / "config_report.json")
    assert report["result"] == "STOP" and report["code"] == "B0_SWITCH_ON"
    assert not (out2 / "resolved.json").exists()
