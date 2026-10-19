# -*- coding: utf-8 -*-
"""pipeline/aws/r1/gates.py and config/r1/gate1_rules.tsv (F23): gate 1, the J1a link and custody.

Toy files in tmp_path only: toy CSV / parquet pairs, toy result JSONs, a toy git repo for the link.
The real repo is read for three things only: oct29.tsv (the 29 gold names), the committed rules TSV
against `git ls-files` + config/r1/base_inputs.tsv, and config/r1/B0.json (the B0-only refusal)."""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import random
import shutil
import struct
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for p in (REPO / "pipeline" / "aws" / "r1", REPO / "pipeline" / "stars" / "caliber_2026-08-28",
          REPO / "pipeline" / "frames" / "cal2026-10" / "econ920"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))
import gates as G   # noqa: E402

RULES = REPO / "config" / "r1" / "gate1_rules.tsv"
BASE_TSV = REPO / "config" / "r1" / "base_inputs.tsv"
OCT29 = REPO / "config" / "r1" / "cells" / "oct29.tsv"
B0 = REPO / "config" / "r1" / "B0.json"
ROOTS = ("data/cal2026-10", "data/frames", "analysis/expected")


def _nudge(x: float, n: int) -> float:
    """x moved by n units in the last place (the integer image frames_stage.ulps measures)."""
    return struct.unpack("<d", struct.pack("<q", struct.unpack("<q", struct.pack("<d", x))[0] + n))[0]


def _sha(p) -> str:
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def _w(p: pathlib.Path, text: str) -> pathlib.Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _wj(p: pathlib.Path, obj) -> pathlib.Path:
    return _w(p, json.dumps(obj, indent=1))


# ---------------------------------------------------------------------------------------------
# comparators
# ---------------------------------------------------------------------------------------------

P1_HDR = "incumbent_person_id,event_id,year,y,fwci_frac,fwci_frac_ex_star,dose_topic,age_gap\n"


def _p1(fwci=0.123456789, dose=0.25, extra_row=False) -> str:
    rows = [f"A100000001,A200000002:2005,2004,3,{fwci!r},0.5,{dose!r},4.0\n",
            "A100000003,A200000002:2005,2005,1,0.75,0.375,0.125,7.0\n"]
    if extra_row:
        rows.append("A100000004,A200000002:2005,2006,0,0.5,0.5,0.5,1.0\n")
    return P1_HDR + "".join(rows)


def test_byte_rule_passes_identical_and_stops_on_one_byte(tmp_path):
    a = _w(tmp_path / "ref" / "x.csv", "a,b\n1,2\n")
    b = _w(tmp_path / "new" / "x.csv", "a,b\n1,2\n")
    assert G.rule_byte(a, b)["ok"] is True
    _w(b, "a,b\n1,3\n")
    assert G.rule_byte(a, b)["ok"] is False
    _w(b, "a,b\r\n1,2\r\n")                       # line endings are bytes too
    assert G.rule_byte(a, b)["ok"] is False


def test_h1_fwci_3_ulp_passes_9_ulp_stops(tmp_path):
    ref = _w(tmp_path / "ref.csv", _p1())
    new = _w(tmp_path / "new.csv", _p1(fwci=_nudge(0.123456789, 3)))
    r = G.rule_h1_lines(ref, new, ("fwci_frac", "fwci_frac_ex_star"))
    assert r["ok"] is True and r["worst_ulp"] == 3
    _w(new, _p1(fwci=_nudge(0.123456789, 9)))
    r = G.rule_h1_lines(ref, new, ("fwci_frac", "fwci_frac_ex_star"))
    assert r["ok"] is False and r["worst_ulp"] == 9
    _w(new, _p1(fwci=_nudge(0.123456789, 8)))   # the bound itself is inside
    assert G.rule_h1_lines(ref, new, ("fwci_frac", "fwci_frac_ex_star"))["ok"] is True
    _w(new, _p1())
    r = G.rule_h1_lines(ref, new, ("fwci_frac", "fwci_frac_ex_star"))
    assert r["ok"] is True and r["worst_ulp"] == 0


def test_h1_non_fwci_column_one_ulp_stops(tmp_path):
    allowed = ("fwci_frac", "fwci_frac_ex_star")
    ref = _w(tmp_path / "ref.csv", _p1())
    new = _w(tmp_path / "new.csv", _p1(dose=_nudge(0.25, 1)))
    r = G.rule_h1_lines(ref, new, allowed)
    assert r["ok"] is False and r["unexpected_columns"] == ["dose_topic"]
    _w(new, _p1(extra_row=True))                                    # line count
    assert G.rule_h1_lines(ref, new, allowed)["ok"] is False
    _w(new, _p1().replace("age_gap", "age_gap2", 1))                # header only
    assert G.rule_h1_lines(ref, new, allowed)["ok"] is False
    _w(new, _p1().replace(",4.0\n", ",4.0,9\n", 1))                 # a field more on one line
    assert G.rule_h1_lines(ref, new, allowed)["ok"] is False
    _w(new, _p1().replace("0.5,0.25", "x,0.25", 1))                 # an allowed column that is no float
    assert G.rule_h1_lines(ref, new, allowed)["ok"] is False


ECON_HDR = ("incumbent_person_id,event_id,year,y,fwci_frac,fwci_frac_ex_star,fwci_mean,fwci_mean_ex_star,"
            "dose_topic,age_gap\n")


def _econ(fmean=0.625, dose=0.25, drop_last=False) -> str:
    rows = [f"P_A100000001,A200000002:2005,2004,3,0.5,0.5,{fmean!r},0.5,{dose!r},4.0\n",
            "P_A100000003,A200000002:2005,2005,1,0.75,0.375,0.25,0.125,0.125,7.0\n"]
    return ECON_HDR + "".join(rows[:1] if drop_last else rows)


def test_h1_econ_uses_characterise_frame(tmp_path):
    import econ920_lib as L                                          # October's own verdicts
    ref = _w(tmp_path / "ref.csv", _econ())
    new = _w(tmp_path / "new.csv", _econ())
    r = G.rule_h1_econ(ref, new)
    assert r["ok"] is True and r["verdict"] == "BYTE_EQUAL"
    _w(new, _econ(fmean=_nudge(0.625, 1)))                          # a Y_SWAPPED_BY_04 column, 1 ULP
    r = G.rule_h1_econ(ref, new)
    assert r["ok"] is True and r["verdict"] == "EQUAL_MODULO_Y_SWAPPED_BY_04"
    assert r["verdict"] == L.characterise_frame(ref, new)["verdict"]
    _w(new, _econ(dose=_nudge(0.25, 1)))                            # dose_topic, 1 ULP
    r = G.rule_h1_econ(ref, new)
    assert r["ok"] is False and r["verdict"] == "NOT_EQUAL" == L.characterise_frame(ref, new)["verdict"]
    _w(new, _econ(drop_last=True))                                  # a removed row
    r = G.rule_h1_econ(ref, new)
    assert r["ok"] is False and r["verdict"] == L.characterise_frame(ref, new)["verdict"]


def test_h1_econ_requires_the_same_header_and_line_count(tmp_path):
    """J0 review #3 (accepted in part, 2026-10-16): characterise_frame compares only the reference's
    columns, keyed, so a rebuilt econ frame with an added column came out EQUAL_MODULO_Y_SWAPPED_BY_04 and
    passed. NOT_REPRODUCIBLE H1 is 'row count and header identical' plus the ULP bound (as rule_h1_lines
    already checks), so rule_h1_econ first requires the same header line and line count, read as
    frames_stage.read_frame_rows reads them (\\r stripped). No byte rule: the econ frames stay under H1."""
    import econ920_lib as L                                          # October's own verdicts
    ref = _w(tmp_path / "ref.csv", _econ())
    leak = (_econ().replace(",age_gap\n", ",age_gap,leak\n", 1)
            .replace(",4.0\n", ",4.0,1\n", 1).replace(",7.0\n", ",7.0,1\n", 1))  # one column more, same values
    new = _w(tmp_path / "new.csv", leak)
    assert L.characterise_frame(ref, new)["verdict"] == "EQUAL_MODULO_Y_SWAPPED_BY_04"   # the hole, unchanged
    r = G.rule_h1_econ(ref, new)
    assert r["ok"] is False and r["reason"] == "header differs" and r["worst_ulp"] is None
    _w(new, _econ().replace("fwci_mean,fwci_mean_ex_star", "fwci_mean_ex_star,fwci_mean", 1))   # columns swapped
    assert G.rule_h1_econ(ref, new)["reason"] == "header differs"
    _w(new, _econ() + "P_A100000005,A200000002:2005,2006,0,0.5,0.5,0.5,0.5,0.5,1.0\n")       # a row more
    r = G.rule_h1_econ(ref, new)
    assert r["ok"] is False and r["reason"] == "line counts differ 3 vs 4"
    # what H1 allows still passes: a 1-ULP Y_SWAPPED_BY_04 difference, and CRLF line ends (stripped as
    # read_frame_rows strips them; the union frame's network rows carry legacy CRs)
    _w(new, _econ(fmean=_nudge(0.625, 1)))
    assert G.rule_h1_econ(ref, new)["ok"] is True
    new.write_bytes(_econ().replace("\n", "\r\n").encode("utf-8"))
    r = G.rule_h1_econ(ref, new)
    assert r["ok"] is True and r["verdict"] == "EQUAL_MODULO_Y_SWAPPED_BY_04"
    # through check_products with the committed rules: the leaking econ frame is a STOP
    rel = "data/cal2026-10/frames_econ/p1_frame_econ.csv"
    _w(tmp_path / "ref_tree" / rel, _econ())
    _w(tmp_path / "repo_tree" / rel, leak)
    rows, codes = G.check_products([rel], G.load_rules(RULES), repo=tmp_path / "repo_tree", ref=tmp_path / "ref_tree")
    assert [(r["rule"], r["status"]) for r in rows] == [("h1_econ", "STOP")] and codes == ["PRODUCT_STOP"]


def test_ulps_matches_frames_stage():
    import frames_stage as fs
    rnd = random.Random(20261015)
    pairs = [(1.0, 1.0), (0.1, _nudge(0.1, 1)), (0.1, _nudge(0.1, 8)), (2.5, _nudge(2.5, -9)), (-0.5, _nudge(-0.5, 3))]
    while len(pairs) < 20:
        x = rnd.uniform(-1e3, 1e3)
        pairs.append((x, _nudge(x, rnd.randint(-50, 50))) if rnd.random() < 0.5 else (x, rnd.uniform(-1e3, 1e3)))
    assert len(pairs) == 20
    for x, y in pairs:
        assert G.ulps(x, y) == fs.ulps(x, y), (x, y)
    assert G.ulps(0.1, _nudge(0.1, 7)) == 7


def test_parquet_rule_ignores_row_order_and_stops_on_a_value(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    ref, new = tmp_path / "ref.parquet", tmp_path / "new.parquet"
    pq.write_table(pa.table({"grp": [1, 2, 3], "y": [0.5, 0.25, 0.125]}), ref)
    pq.write_table(pa.table({"grp": [3, 1, 2], "y": [0.125, 0.5, 0.25]}), new)
    assert G.rule_content(ref, new)["ok"] is True
    pq.write_table(pa.table({"grp": [3, 1, 2], "y": [0.125, 0.5, _nudge(0.25, 1)]}), new)
    assert G.rule_content(ref, new)["ok"] is False
    pq.write_table(pa.table({"grp": [1, 2, 3, 3], "y": [0.5, 0.25, 0.125, 0.125]}), new)   # one duplicate row
    assert G.rule_content(ref, new)["ok"] is False


def test_json_except_compares_octobers_keys_but_the_named_ones(tmp_path):
    ref = _wj(tmp_path / "ref.json", {"generated": "2026-09-22T21:49:57", "control": {"n": 11}, "rows": [1, 2]})
    new = _wj(tmp_path / "new.json", {"generated": "2026-10-20T01:00:00", "control": {"n": 11}, "rows": [1, 2],
                                      "convention": "aug"})          # a key October's report predates
    assert G.rule_json_except(ref, new, ("generated",))["ok"] is True
    _wj(new, {"generated": "x", "control": {"n": 11.0}, "rows": [1, 2]})   # 11 vs 11.0 is a difference
    r = G.rule_json_except(ref, new, ("generated",))
    assert r["ok"] is False and r["changed"] == ["control"]
    _wj(new, {"generated": "x", "control": {"n": 11}})
    r = G.rule_json_except(ref, new, ("generated",))
    assert r["ok"] is False and r["changed"] == ["rows"]


# ---------------------------------------------------------------------------------------------
# the rules table
# ---------------------------------------------------------------------------------------------

def test_every_product_matches_a_rule_and_an_unmatched_product_stops(tmp_path):
    toy = _w(tmp_path / "rules.tsv", "pattern\trule\targ\treason\n"
             "data/x/frames*/**/*.csv\tbyte\t-\tCSV products of the toy frames dirs\n"
             "data/x/robustness/**\tnot_rebuilt\t-\tthe toy robustness tree is not rebuilt in B0\n")
    rules = G.load_rules(toy)
    assert G.match_rule(rules, "data/x/frames_econ/sub/a.csv").rule == "byte"
    assert G.match_rule(rules, "data/x/frames/a.csv").rule == "byte"
    assert G.match_rule(rules, "data/x/framesfoo.csv") is None
    assert G.match_rule(rules, "data/x/robustness/d7/a/b.json").rule == "not_rebuilt"
    assert G.match_rule(rules, "data/x/other.csv") is None
    repo, ref = tmp_path / "repo", tmp_path / "ref"
    for root in (repo, ref):
        _w(root / "data/x/frames/a.csv", "a\n1\n")
        _w(root / "data/x/other.csv", "o\n")
    rows, codes = G.check_products(["data/x/frames/a.csv", "data/x/other.csv"], rules, repo=repo, ref=ref)
    assert {r["path"]: r["status"] for r in rows} == {"data/x/frames/a.csv": "PASS", "data/x/other.csv": "NO_RULE"}
    assert "NO_RULE" in codes
    bad = _w(tmp_path / "bad.tsv", "pattern\trule\targ\treason\ndata/**\tnot_rebuilt\t-\tshort\n")
    with pytest.raises(ValueError):                                  # a not_rebuilt reason must be > 20 chars
        G.load_rules(bad)

    # the committed table against every tracked file under the roots that F2 does not class as base
    rules = G.load_rules(RULES)
    assert all(len(r.reason) > 20 for r in rules if r.rule in ("not_rebuilt", "record"))
    with open(BASE_TSV, encoding="utf-8", newline="") as fh:
        base = list(csv.DictReader(fh, delimiter="\t"))
    not_product = {r["path"] for r in base if r["class"] != "product"}
    tracked = subprocess.run(["git", "ls-files", *ROOTS], cwd=REPO, capture_output=True, text=True,
                             check=True).stdout.splitlines()
    products = [p for p in tracked if p not in not_product]
    assert len(products) > 500
    unmatched = [p for p in products if G.match_rule(rules, p) is None]
    assert not unmatched, unmatched[:20]
    tsv_products = [r["path"] for r in base if r["class"] == "product"]
    assert [p for p in tsv_products if G.match_rule(rules, p) is None] == []
    # what J0 rebuilds is compared, never waved through
    want = {"data/cal2026-10/frames/p1_frame_chemistry.csv": "h1", "data/cal2026-10/frames_math_stats/p1_frame_math_stats.csv": "h1",
            "data/cal2026-10/frames/p1_frame_econ_old79.csv": "h1_econ", "data/cal2026-10/frames_econ/p1_frame_econ.csv": "h1_econ",
            "data/cal2026-10/frames/p3_slim_econ.parquet": "content", "data/cal2026-10/frames_afar/p3_afar_econ.parquet": "content",
            "data/cal2026-10/frames/p2_becoming_econ.csv": "byte", "data/cal2026-10/restake_econ11_aug_all_2026-10.csv": "byte",
            "data/cal2026-10/restake_econ11_control_aug_2026-10.csv": "byte", "data/cal2026-10/events_econ_cal2026-10_p05.csv": "byte",
            "data/cal2026-10/events_decision_2026-10.json": "json_except", "data/cal2026-10/restake_econ11_report_aug_2026-10.json": "json_except",
            "data/cal2026-10/frames/MANIFEST.sha256": "record", "data/cal2026-10/frames_econ/build_report_econ920_2026-10.json": "record",
            "data/cal2026-10/restake_econ11_july_2026-10.csv": "not_rebuilt", "data/frames/p1_frame_econ.csv": "not_rebuilt",
            "analysis/expected/P1_econ_fnfix.json": "not_rebuilt", "data/cal2026-10/robustness/battery_report.json": "not_rebuilt"}
    assert {p: G.match_rule(rules, p).rule for p in want} == want
    assert G.match_rule(rules, "data/cal2026-10/frames/p1_frame_chemistry.csv").arg == "fwci_frac,fwci_frac_ex_star"


# ---------------------------------------------------------------------------------------------
# a toy J0 world: repo + ref + B0 cells + JP stage set + frames + sandbox verdict
# ---------------------------------------------------------------------------------------------

def _gold_names():
    with open(OCT29, encoding="utf-8", newline="") as fh:
        return [r["out_name"] for r in csv.DictReader(fh, delimiter="\t")]


def _md5(p) -> str:
    return hashlib.md5(pathlib.Path(p).read_bytes()).hexdigest()


def _world(tmp_path, golds=None):
    golds = golds or ["A.json", "B.json"]
    repo, ref, work, jp = tmp_path / "repo", tmp_path / "ref" / "october", tmp_path / "work", tmp_path / "jp"
    products = {
        "data/cal2026-10/frames/p1_frame_chemistry.csv": (_p1(), _p1(fwci=_nudge(0.123456789, 2))),
        "data/cal2026-10/events_econ_cal2026-10.csv": ("event_id\nA200000002:2005\n",) * 2,
        "data/cal2026-10/frames/MANIFEST.sha256": ("aa  x\n", "bb  x\n"),          # recorded, not compared
    }
    for path, (old, new) in products.items():
        _w(ref / path, old)
        _w(repo / path, new)
    _w(ref / "data/cal2026-10/robustness/battery_report.json", "{}")              # not rebuilt in B0
    _w(repo / "data/cal2026-10/calls_2026-10.csv", "base\n")                      # a base input: never compared
    tsv = tmp_path / "base_inputs.tsv"
    lines = ["path\tclass\tgit_blob\tproducer\treason"]
    lines += [f"{p}\tproduct\t-\ttoy\ttoy product" for p in [*products, "data/cal2026-10/robustness/battery_report.json"]]
    lines.append("data/cal2026-10/calls_2026-10.csv\tbase\t-\thand\ttoy base input")
    _w(tsv, "\n".join(lines) + "\n")
    frames = work / "prod" / "frames"
    _w(frames / "p1_frame_econ.csv", "toy frame\n")
    _w(frames / "p3_slim_econ.parquet", "toy parquet bytes\n")
    _w(frames / "MANIFEST.sha256", "".join(f"{_sha(frames / n)}  data/cal2026-10/frames/{n}\n"
                                           for n in ("p1_frame_econ.csv", "p3_slim_econ.parquet")))
    gold = {n: {"label": n[:-5], "ATE": 1.0, "se": 0.5, "secs": 3} for n in golds}
    for n, g in gold.items():
        _wj(ref / "analysis" / "expected" / n, g)
    _w(ref / "analysis" / "expected" / "SOURCES.md", "toy\n")
    cells = work / "prod" / "cells_rmac"
    rep = {}
    for i, n in enumerate(golds):
        fr = "p1_frame_econ.csv" if i % 2 == 0 else "p3_slim_econ.parquet"
        _wj(cells / "estimates" / n, dict(gold[n], secs=99))                      # secs is not compared
        rep[n[:-5]] = {"rc": 0, "status": "EQUAL", "secs": 1.0, "peak_gib": None, "first_diff": None,
                       "inputs": {"frame": {"name": fr, "sha256": _sha(frames / fr), "md5": _md5(frames / fr)},
                                  "ref": None, "driver": {"name": "analysis/estimation/run_p1.R", "sha256": "0" * 64}}}
    _wj(cells / "cells_report_rmac.json", rep)
    jcells = jp / "cells_rmac" / "files" / "work" / "prod" / "cells_rmac"
    for n in golds:
        _wj(jcells / "estimates" / n, dict(gold[n], secs=7))
    _wj(jcells / "cells_report_rmac.json", {n[:-5]: {"rc": 0, "status": "EQUAL"} for n in golds})
    sandbox = _wj(work / "prod" / "sandbox_check" / "sandbox_check.json",
                  {"verdict": "OK", "rewritten": [], "gread": [], "unused_allowlist": [], "audited_stages": ["gate1"]})
    out = work / "prod" / "gate1"
    kw = dict(cells_reports=[cells], jp=jp, ref=ref, rules=RULES, tsv=tsv, frames_manifest=frames / "MANIFEST.sha256",
              sandbox=sandbox, repo=repo, out=out)
    return kw


def _report(kw) -> dict:
    return json.loads((pathlib.Path(kw["out"]) / "gate_report_1.json").read_text(encoding="utf-8"))


def test_gate1_passes_on_a_clean_toy_world(tmp_path):
    kw = _world(tmp_path)
    rep = G.gate1(**kw)
    assert rep["verdict"] == "PASS" and rep["mode"] == "exact" and rep["codes"] == [], rep
    on_disk = _report(kw)
    assert on_disk["verdict"] == "PASS" and on_disk["counts"]["n_golds"] == 2
    assert on_disk["counts"]["n_products_record"] == 1 and on_disk["counts"]["n_products_not_rebuilt"] == 1


def test_b0_estimates_need_all_29_equal(tmp_path):
    names = _gold_names()
    assert len(names) == 29 and "P1_econ_fnfix_old79.json" in names
    kw = _world(tmp_path, golds=names)
    assert G.gate1(**kw)["verdict"] == "PASS"
    assert _report(kw)["counts"]["n_cells_equal"] == 29
    est = pathlib.Path(kw["cells_reports"][0]) / "estimates"
    one = json.loads((est / "P2_econ_fnfix.json").read_text())
    _wj(est / "P2_econ_fnfix.json", dict(one, ATE=_nudge(1.0, 1)))             # one DIFF, one ULP
    rep = G.gate1(**kw)
    assert rep["verdict"] == "FAIL" and "CELL_DIFF" in rep["codes"]
    assert {r["label"]: r["status"] for r in rep["rows_cells"]} == {"P2_econ_fnfix.json": "DIFF"}
    _wj(est / "P2_econ_fnfix.json", one)
    (est / "P1_econ_fnfix_old79.json").unlink()                                 # old79 missing (C10: B0 runs it)
    rep = G.gate1(**kw)
    assert rep["verdict"] == "FAIL" and "CELL_MISSING" in rep["codes"]
    shutil.rmtree(pathlib.Path(kw["ref"]) / "analysis" / "expected")
    assert "NO_GOLDS" in G.gate1(**kw)["codes"]


def test_gate1_refuses_config_m(tmp_path, monkeypatch):
    kw = _world(tmp_path)
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")
    argv = ["gate1", "--cells-reports", str(kw["cells_reports"][0]), "--jp", str(kw["jp"]), "--ref", str(kw["ref"]),
            "--rules", str(kw["rules"]), "--tsv", str(kw["tsv"]), "--frames-manifest", str(kw["frames_manifest"]),
            "--sandbox", str(kw["sandbox"]), "--repo", str(kw["repo"]), "--out", str(kw["out"])]
    m = _wj(tmp_path / "M.json", {"schema": "sar.r1.run_config.v1", "name": "M", "config": "M"})
    monkeypatch.setenv("SAR_R1_CONFIG", str(m))
    with pytest.raises(SystemExit) as e:
        G.main(argv)
    assert "B0" in str(e.value) and not (pathlib.Path(kw["out"]) / "gate_report_1.json").exists()
    monkeypatch.delenv("SAR_R1_CONFIG")
    with pytest.raises(SystemExit):
        G.main(argv)
    assert not (pathlib.Path(kw["out"]) / "gate_report_1.json").exists()
    monkeypatch.setenv("SAR_R1_CONFIG", str(B0))                               # the real B0 config is accepted
    assert G.main(argv) == 0 and _report(kw)["verdict"] == "PASS"
    monkeypatch.setenv("SAR_HOST", "laptop")
    with pytest.raises(SystemExit):
        G.main(argv)


def test_parity_exact_when_jp_all_equal_else_ec2_compares_to_jp_estimates(tmp_path):
    kw = _world(tmp_path)
    jcells = pathlib.Path(kw["jp"]) / "cells_rmac" / "files" / "work" / "prod" / "cells_rmac"
    assert G.gate1(**kw)["mode"] == "exact"
    # JP missed parity on B: EC2 gives another ATE. gate 1 now compares B0's cells to JP's EC2 JSONs.
    jrep = json.loads((jcells / "cells_report_rmac.json").read_text())
    jrep["B"]["status"] = "DIFF"
    _wj(jcells / "cells_report_rmac.json", jrep)
    jb = json.loads((jcells / "estimates" / "B.json").read_text())
    _wj(jcells / "estimates" / "B.json", dict(jb, ATE=1.25))
    rep = G.gate1(**kw)                         # B0 = October gold, but not JP's EC2 cell -> STOP
    assert rep["mode"] == "ec2" and rep["verdict"] == "FAIL" and "CELL_DIFF" in rep["codes"]
    assert {r["label"]: r["status"] for r in rep["rows_cells"]} == {"B.json": "DIFF"}
    assert {r["label"]: r["status"] for r in rep["rows_jp"]} == {"B": "DIFF"}     # the October-vs-EC2 table
    est = pathlib.Path(kw["cells_reports"][0]) / "estimates"
    _wj(est / "B.json", dict(json.loads((est / "B.json").read_text()), ATE=1.25))
    rep = G.gate1(**kw)                         # B0 = JP's EC2 cell -> PASS; the data layer stayed exact
    assert rep["mode"] == "ec2" and rep["verdict"] == "PASS", rep
    _w(pathlib.Path(kw["repo"]) / "data/cal2026-10/events_econ_cal2026-10.csv", "event_id\nA200000002:2006\n")
    rep = G.gate1(**kw)
    assert rep["verdict"] == "FAIL" and "PRODUCT_STOP" in rep["codes"]
    assert {r["path"]: r["status"] for r in rep["rows_products"]} == {"data/cal2026-10/events_econ_cal2026-10.csv": "STOP"}
    shutil.rmtree(kw["jp"])
    rep = G.gate1(**kw)
    assert rep["verdict"] == "FAIL" and "JP_MISSING" in rep["codes"]


def test_custody_cell_input_sha_must_equal_manifest(tmp_path):
    kw = _world(tmp_path)
    cells = pathlib.Path(kw["cells_reports"][0])
    good = json.loads((cells / "cells_report_rmac.json").read_text())
    bad = json.loads(json.dumps(good))
    bad["A"]["inputs"]["frame"]["sha256"] = "f" * 64
    _wj(cells / "cells_report_rmac.json", bad)
    rep = G.gate1(**kw)
    assert rep["verdict"] == "FAIL" and rep["codes"] == ["CUSTODY_SHA"]
    bad = json.loads(json.dumps(good))
    bad["B"]["inputs"]["frame"]["name"] = "p1_frame_unlisted.csv"
    _wj(cells / "cells_report_rmac.json", bad)
    assert G.gate1(**kw)["codes"] == ["CUSTODY_UNLISTED"]
    bad = json.loads(json.dumps(good))
    del bad["A"]["inputs"]
    _wj(cells / "cells_report_rmac.json", bad)
    assert G.gate1(**kw)["codes"] == ["CUSTODY_NO_INPUTS"]
    _wj(cells / "cells_report_rmac.json", good)
    _w(pathlib.Path(kw["frames_manifest"]).parent / "p1_frame_econ.csv", "changed after the MANIFEST\n")
    assert G.gate1(**kw)["codes"] == ["MANIFEST_STALE"]          # the MANIFEST no longer describes the frames
    # the custody subcommand (J1a's M cells): every listed cell must be there
    frames = pathlib.Path(kw["frames_manifest"]).parent
    _w(frames / "p1_frame_econ.csv", "toy frame\n")
    tsv = _w(tmp_path / "M.tsv", "label\tdriver\tframe\tref\tout_name\tstack\n"
             "A\tanalysis/estimation/run_p1.R\tp1_frame_econ.csv\t-\tA.json\trmac\n"
             "B\tanalysis/estimation/run_p3.R\tp3_slim_econ.parquet\t-\tB.json\trmac\n")
    out = tmp_path / "custody"
    assert G.custody_main(cells=[tsv], reports=[cells], manifest=kw["frames_manifest"], out=out) == 0
    assert json.loads((out / "gate_report_custody.json").read_text())["verdict"] == "PASS"
    _w(tsv, tsv.read_text() + "C\tanalysis/estimation/run_p1.R\tp1_frame_econ.csv\t-\tC.json\trmac\n")
    assert G.custody_main(cells=[tsv], reports=[cells], manifest=kw["frames_manifest"], out=out) == 1
    assert json.loads((out / "gate_report_custody.json").read_text())["codes"] == ["CUSTODY_NO_CELL"]


def test_sandbox_verdict_rewritten_or_gread_or_missing_stops(tmp_path):
    kw = _world(tmp_path)
    sb = pathlib.Path(kw["sandbox"])
    ok = json.loads(sb.read_text())
    for verdict in ("STOP_REWRITE", "G_READ_FAIL", "AUDIT_LOST"):
        _wj(sb, dict(ok, verdict=verdict))
        rep = G.gate1(**kw)
        assert rep["verdict"] == "FAIL" and f"SANDBOX_{verdict}" in rep["codes"]
    _wj(sb, dict(ok, rewritten=[["data/cal2026-10/calls_2026-10.csv", "sha256"]]))   # an OK that lists a rewrite
    assert "SANDBOX_REWRITTEN" in G.gate1(**kw)["codes"]
    _wj(sb, dict(ok, gread=[["frames_chemmath", "data/cal2026-08-28/frames/x.csv"]]))
    assert "SANDBOX_GREAD" in G.gate1(**kw)["codes"]
    sb.unlink()
    rep = G.gate1(**kw)
    assert rep["verdict"] == "FAIL" and "SANDBOX_MISSING" in rep["codes"]


def test_gate_report_is_name_free(tmp_path):
    import run_stages as rs
    kw = _world(tmp_path)
    for p in (pathlib.Path(kw["ref"]) / "analysis" / "expected" / "A.json", pathlib.Path(kw["cells_reports"][0]) / "estimates" / "A.json"):
        _wj(p, dict(json.loads(p.read_text()), star="Yves Zenou"))
    p = pathlib.Path(kw["cells_reports"][0]) / "estimates" / "A.json"
    _wj(p, dict(json.loads(p.read_text()), star="Zenou, Yves"))               # the diff text names him
    rep = G.gate1(**kw)
    assert rep["verdict"] == "FAIL"
    text = (pathlib.Path(kw["out"]) / "gate_report_1.json").read_text(encoding="utf-8")
    assert "Zenou" not in text and "CELL_DIFF" in text
    details = (pathlib.Path(kw["out"]) / "details_1.json").read_text(encoding="utf-8")
    assert "Zenou" in details                                                  # full detail stays in the stage files
    work = pathlib.Path(kw["out"]).parents[1]
    summ = rs._reports(work, "gate1")                                          # what summary.json carries
    assert "gate_report_1.json" in summ and "Zenou" not in json.dumps(summ)


# ---------------------------------------------------------------------------------------------
# the J1a link
# ---------------------------------------------------------------------------------------------

def _git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def test_link_ok_wrong_verdict_and_changed_b0_chain_path(tmp_path, monkeypatch):
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")
    repo = tmp_path / "toy repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _w(repo / "pipeline" / "frames" / "build.py", "print(1)\n")
    _w(repo / "config" / "r1" / "M.json", "{}\n")
    chain = _wj(repo / "config" / "r1" / "chain.json", {"schema": "sar.r1.chain.v1",
                                                         "b0_chain_paths": ["pipeline/frames", "config/r1/B0.json"], "steps": []})
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "j0")
    c0 = _git(repo, "rev-parse", "HEAD")
    _w(repo / "config" / "r1" / "M.json", '{"m": 1}\n')                        # an M-only change
    _git(repo, "commit", "-qam", "m")
    c1 = _git(repo, "rev-parse", "HEAD")
    _w(repo / "pipeline" / "frames" / "build.py", "print(2)\n")                # a B0-chain change
    _git(repo, "commit", "-qam", "b0")
    c2 = _git(repo, "rev-parse", "HEAD")

    j0 = tmp_path / "j0"
    gate = {"gate": "gate1", "verdict": "PASS", "mode": "exact", "codes": []}
    summary = {"table": "j0", "result": "OK", "commit": c0, "stages": [],
               "reports": {"gate1": {"gate_report_1.json": gate}}}
    _wj(j0 / "summary.json", summary)
    _w(j0 / "RESULT.txt", "OK\n")
    out = tmp_path / "link"

    def link(commit):
        return G.main(["link", "--j0", str(j0), "--chain", str(chain), "--repo", str(repo), "--commit", commit, "--out", str(out)])

    assert link(c0) == 0                                        # same commit
    assert link(c1) == 0                                        # later commit, no B0-chain path touched
    rep = json.loads((out / "gate_report_link.json").read_text())
    assert rep["verdict"] == "PASS" and rep["changed"] == []
    assert link(c2) == 1
    rep = json.loads((out / "gate_report_link.json").read_text())
    assert rep["verdict"] == "FAIL" and rep["changed"] == ["pipeline/frames/build.py"] and "B0_CHAIN_CHANGED" in rep["codes"]
    _wj(j0 / "summary.json", dict(summary, reports={"gate1": {"gate_report_1.json": dict(gate, verdict="FAIL")}}))
    assert link(c0) == 1
    _wj(j0 / "summary.json", dict(summary, reports={}))
    assert link(c0) == 1                                        # no gate report at all
    _wj(j0 / "summary.json", dict(summary, result="STAGE_FAIL"))
    assert link(c0) == 1
    _wj(j0 / "summary.json", dict(summary, commit="0" * 40))
    assert link(c1) == 1                                        # an unknown J0 commit cannot be diffed: fail closed
    monkeypatch.setenv("SAR_HOST", "laptop")
    with pytest.raises(SystemExit):
        link(c0)
