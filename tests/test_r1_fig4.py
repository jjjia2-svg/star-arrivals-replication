# -*- coding: utf-8 -*-
"""R1 N5 (W1-FIG4): Figure 4 comparison-relation counts from did_multiplegt_dyn(save_sample=TRUE).

Small-runner tests (no R): the J1b cell list, the text proof that the save_sample driver is a
line-for-line copy of the three verbatim drivers, a hand-counted toy sample, and parity with the
author's 2026-10-03 rule as figB.py writes it. The estimator-level checks are in test_r1_fig4_r.py.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import pathlib
import subprocess
import sys

import pandas as pd
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
CELLS = REPO / "config" / "r1" / "cells"
DRIVER = REPO / "analysis" / "robustness" / "figure4" / "run_save_sample.R"
FIG4_COUNTS = REPO / "pipeline" / "aws" / "r1" / "fig4_counts.py"
LABELS = ("P1_econ_fnfix", "P1_fnfix_chemistry", "P1_fnfix_math_stats",
          "P2_econ_fnfix", "P2_fnfix_chemistry", "P2_fnfix_math_stats",
          "P3cut_pos_math_stats", "P3cut_pos_chemistry", "P3cut_pos_econ")
COPY = "# ---- copied from analysis/estimation/"
TOKEN = ", save_sample=TRUE"


def _fc():
    spec = importlib.util.spec_from_file_location("fig4_counts_under_test", FIG4_COUNTS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tsv(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


# ---------------------------------------------------------------------------------------------
# 1. the J1b cell list
# ---------------------------------------------------------------------------------------------
def test_fig4_cells_mirror_m_tsv():
    """fig4_M.tsv = the nine Figure 4 rows of the M cell list with the driver swapped. M.tsv copies
    oct29.tsv byte for byte for these rows (W1-CELLSM), so oct29.tsv is checked always and M.tsv
    whenever it is in the tree."""
    fig4 = CELLS / "fig4_M.tsv"
    head = (CELLS / "oct29.tsv").read_text(encoding="utf-8").splitlines()[0]
    assert fig4.read_text(encoding="utf-8").splitlines()[0] == head
    rows = _tsv(fig4)
    assert [r["label"] for r in rows] == list(LABELS)
    for src in (CELLS / "oct29.tsv", CELLS / "M.tsv"):
        if src.name == "M.tsv" and not src.is_file():
            continue
        ref = {r["label"]: r for r in _tsv(src)}
        for r in rows:
            want = dict(ref[r["label"]], driver="analysis/robustness/figure4/run_save_sample.R")
            assert r == want, (src.name, r["label"])
    assert {r["stack"] for r in rows} == {"rmac"} and {r["ref"] for r in rows} == {"-"}
    assert len({r["out_name"] for r in rows}) == 9


# ---------------------------------------------------------------------------------------------
# 2. the driver is the verbatim drivers plus save_sample=TRUE and a writer block
# ---------------------------------------------------------------------------------------------
def _copied_blocks(text):
    """{verbatim driver name: [copied non-blank lines, in file order]} and the other lines."""
    copied, other, cur = {}, [], None
    for line in text.split("\n"):
        if line.startswith("# ---- "):
            cur = line[len(COPY):] if line.startswith(COPY) else None
            if cur is not None:
                copied.setdefault(cur, [])
            continue
        if not line.strip():
            continue
        (copied[cur] if cur is not None else other).append(line)
    return copied, other


def _body(name):
    lines = (REPO / "analysis" / "estimation" / name).read_text(encoding="utf-8").split("\n")
    start = next(i for i, ln in enumerate(lines) if ln.startswith("suppressMessages("))
    return [ln for ln in lines[start:] if ln.strip()]


def test_driver_prep_is_a_line_for_line_copy():
    text = DRIVER.read_text(encoding="utf-8")
    copied, other = _copied_blocks(text)
    assert sorted(copied) == ["run_p1.R", "run_p2.R", "run_p3_tp.R"]
    for name, lines in copied.items():
        body = _body(name)
        calls = sum(ln.count("did_multiplegt_dyn(") for ln in body)
        assert sum(ln.count(TOKEN) for ln in lines) == calls, name   # every call, and only once
        assert [ln.replace(TOKEN, "") for ln in lines] == body, (
            f"{name}: the copied blocks are not the verbatim driver line for line "
            f"(the only permitted change is '{TOKEN}' in each did_multiplegt_dyn call)")
        for ln in lines:
            if TOKEN in ln:
                assert ln.rstrip().endswith("graph_off=TRUE" + TOKEN + "),"), ln
    # the repo-authored lines (dispatch + sample writer) estimate nothing and set no seed
    joined = "\n".join(other)
    for banned in ("did_multiplegt_dyn(", "set.seed", "toJSON", '".json"'):
        assert banned not in joined, banned
    assert "save_sample" in joined and "_sample.csv.gz" in joined and "_switchers.csv" in joined
    # one model per run, chosen from the label prefix
    assert 'MODEL == "P1"' in text and 'MODEL == "P2"' in text and 'MODEL == "P3"' in text


# ---------------------------------------------------------------------------------------------
# 3. the counting rule on a hand-counted toy sample
# ---------------------------------------------------------------------------------------------
#: grp_id -> (rows, first year with D>0 or None, zero_dose, {year: did_effect})
TOY = {
    1: (range(2013, 2020), 2016, False, {2016: 1, 2017: 2, 2018: 3}),
    2: ((2014, 2015, 2016, 2018), 2016, False, {2016: 1, 2018: 3}),
    3: (range(2014, 2020), 2017, False, {2017: 1, 2018: 2, 2019: 3}),
    4: ((2016, 2017, 2018), 2017, False, {2017: 1, 2018: 2}),
    5: (range(2013, 2021), 2018, False, {2018: 1, 2019: 2, 2020: 3}),
    6: ((2013, 2015, 2016, 2017), None, False, {}),       # positive dose, star after its last row
    7: (range(2013, 2021), None, True, {}),
    8: ((2015, 2016, 2017), None, True, {}),
    9: ((2014, 2016, 2018), None, True, {}),
    10: ((2015, 2017, 2019), None, True, {}),
    11: (range(2013, 2019), 2014, False, {2014: 1, 2015: 2, 2016: 3}),
    12: (range(2014, 2021), 2019, False, {2019: 1, 2020: 2}),
}


def _toy(zero=True):
    rows = []
    for g, (years, first, z, eff) in TOY.items():
        for y in years:
            rows.append({"channel": "union", "grp_id": g, "year": y,
                         "D": 0.5 if first is not None and y >= first else 0.0,
                         "did_sample": "Switcher-in" if first is not None else "Control",
                         "did_effect": eff.get(y), "arrival": first,
                         "zero_dose": z if zero else None})
    return pd.DataFrame(rows)


def _pick(rows, **kw):
    hit = [r for r in rows if all(r[k] == v for k, v in kw.items())]
    assert len(hit) == 1, (kw, hit)
    return hit[0]


# (cohort, kind, k) -> (year, zero_dose, pos_not_yet, switchers), counted by hand from TOY
HAND = {
    (2016, "effect", 1): (2016, 2, 4, 2), (2016, "effect", 2): (2017, 3, 3, 1),
    (2016, "effect", 3): (2018, 1, 1, 2),
    (2016, "placebo", 1): (2014, 1, 3, 2), (2016, "placebo", 2): (2013, 1, 2, 1),
    (2017, "effect", 1): (2017, 2, 3, 2), (2017, "effect", 2): (2018, 2, 1, 2),
    (2017, "effect", 3): (2019, 1, 0, 1),
    (2017, "placebo", 1): (2015, 2, 3, 1), (2017, "placebo", 2): (2014, 2, 1, 1),
}


def test_hand_counted_toy_sample():
    fc = _fc()
    rows = fc.count(_toy(), n_effects=3, n_placebos=2)
    assert {r["cohort"] for r in rows} == {2014, 2016, 2017, 2018, 2019}
    assert {r["pool"] for r in rows} == {"zero_dose", "pos_not_yet"}
    for (g, kind, k), (year, zd, pos, sw) in HAND.items():
        a = _pick(rows, cohort=g, kind=kind, k=k, pool="zero_dose")
        b = _pick(rows, cohort=g, kind=kind, k=k, pool="pos_not_yet")
        assert (a["year"], a["n_relations"], b["n_relations"], a["n_switchers"]) == (year, zd, pos, sw), (g, kind, k)
        assert a["ell"] == year - g and a["channel"] == "union" and b["n_switchers"] == sw
    # without a zero_dose flag (Models 2 and 3) the two pools are one 'not yet' pool
    flat = fc.count(_toy(zero=False), n_effects=3, n_placebos=2)
    assert {r["pool"] for r in flat} == {"not_yet"}
    for (g, kind, k), (year, zd, pos, sw) in HAND.items():
        r = _pick(flat, cohort=g, kind=kind, k=k)
        assert (r["year"], r["n_relations"], r["n_switchers"]) == (year, zd + pos, sw)
    # the switcher cross-check counts groups tagged did_effect == k, per channel
    table = pd.DataFrame({"channel": ["union"] * 3, "kind": ["effect"] * 3, "k": [1, 2, 3],
                          "n": [9, 9, 9], "switchers": [7, 6, 5]})
    assert fc.switcher_check(_toy(), table) == {"union": "MATCH"}
    bad = fc.switcher_check(_toy(), table.assign(switchers=[7, 5, 5]))
    assert bad["union"].startswith("MISMATCH") and "k=2" in bad["union"]
    assert fc.switcher_check(_toy(), None) == {"union": "NOT_REPORTED"}


# ---------------------------------------------------------------------------------------------
# 4. parity with the original rule (figB.py, the 2026-10-03 figure version)
# ---------------------------------------------------------------------------------------------
# Copied from the original drawing script figB.py (third version, 2026-10-03; not shipped).
# If this test fails, the counting rule differs from the original one: stop and reconcile;
# never adjust these numbers.
ARRIVALS = {2016: 6, 2017: 13, 2018: 10, 2019: 8, 2020: 3, 2021: 4}
EXPECTED_M1 = {2011: None, 2012: None, 2013: 10, 2014: 31,
               2016: 34, 2017: 21, 2018: 11, 2019: 3, 2020: None, 2021: None}
EXPECTED_M23 = {2016: 38, 2017: 25, 2018: 15, 2019: 7, 2020: 4, 2021: None}


def _synthetic(lo, hi, zero):
    """One positive-dose relation per event, full window [a-lo, a+hi]. Four 2015 arrivals are added
    (figB: they exist and are never a comparison, since they are treated in the base year)."""
    rows, g = [], 0
    for a, n in sorted({**ARRIVALS, 2015: 4}.items()):
        for _ in range(n):
            g += 1
            for y in range(a - lo, a + hi + 1):
                rows.append({"channel": "union", "grp_id": g, "year": y, "D": 1.0 if y >= a else 0.0,
                             "did_sample": "Switcher-in", "did_effect": None, "arrival": a,
                             "zero_dose": False if zero else None})
    return pd.DataFrame(rows)


def test_rule_parity_with_figB():
    fc = _fc()
    m1 = [r for r in fc.count(_synthetic(5, 5, True), n_effects=6, n_placebos=4) if r["cohort"] == 2016]
    got = {r["year"]: r["n_relations"] or None for r in m1 if r["pool"] == "pos_not_yet"}
    assert got == EXPECTED_M1
    assert all(r["n_relations"] == 0 for r in m1 if r["pool"] == "zero_dose")
    m23 = [r for r in fc.count(_synthetic(6, 10, False), n_effects=5, n_placebos=4)
           if r["cohort"] == 2016 and r["kind"] == "effect"]
    got = {r["year"]: r["n_relations"] or None for r in m23}
    assert got == {y: v for y, v in EXPECTED_M23.items() if y <= 2020}   # Model 2/3 has 5 effects
    assert EXPECTED_M23[2021] is None


# ---------------------------------------------------------------------------------------------
# 5. the CLI over a run_cells stage directory
# ---------------------------------------------------------------------------------------------
def _stage(tmp_path, switchers):
    out = tmp_path / "stage" / "work" / "P1_toy_econ" / "out"
    out.mkdir(parents=True)
    t = _toy()
    lines = ["channel,grp_id,year,D,did_sample,did_effect,arrival,zero_dose"]
    for r in t.itertuples():
        eff = "" if pd.isna(r.did_effect) else str(int(r.did_effect))
        arr = "" if pd.isna(r.arrival) else str(int(r.arrival))
        lines.append(f"{r.channel},{r.grp_id},{r.year},{r.D},{r.did_sample},{eff},{arr},"
                     f"{'TRUE' if r.zero_dose else 'FALSE'}")
    import gzip
    with gzip.open(out / "P1_toy_econ_sample.csv.gz", "wt", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    (out / "P1_toy_econ_switchers.csv").write_text(
        "channel,kind,k,n,switchers\n" + "".join(f"union,effect,{k},9,{s}\n" for k, s in enumerate(switchers, 1))
        + "union,placebo,1,9,2\n", encoding="utf-8")
    return tmp_path / "stage"


def _cli(stage, out):
    return subprocess.run([sys.executable, str(FIG4_COUNTS), "--cells-out", str(stage), "--out", str(out)],
                          capture_output=True, text=True)


def test_cli_writes_counts_and_fails_on_a_switcher_mismatch(tmp_path):
    stage = _stage(tmp_path, [7, 6, 5, 0, 0, 0])
    r = _cli(stage, tmp_path / "o")
    assert r.returncode == 0, r.stdout + r.stderr
    got = json.loads((tmp_path / "o" / "fig4_counts.json").read_text(encoding="utf-8"))
    e = got["P1_toy_econ/union"]
    assert (e["label"], e["model"], e["channel"], e["field"]) == ("P1_toy_econ", "M1", "union", "econ")
    assert e["switcher_check"] == "MATCH"
    cell = e["cohorts"]["2016"]["2016"]
    assert (cell["kind"], cell["k"], cell["zero_dose"], cell["pos_not_yet"], cell["not_yet"], cell["switchers"]) == \
        ("effect", 1, 2, 4, None, 2)
    assert e["cohorts"]["2016"]["2014"]["kind"] == "placebo"
    with open(tmp_path / "o" / "fig4_counts.csv", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0]) == ["label", "field", "model", "channel", "cohort", "year", "ell", "kind", "k",
                             "pool", "n_relations", "n_switchers"]
    hit = [x for x in rows if (x["cohort"], x["kind"], x["k"], x["pool"]) == ("2017", "placebo", "2", "zero_dose")]
    assert len(hit) == 1 and hit[0]["n_relations"] == "2" and hit[0]["year"] == "2014"
    # a sample whose effect tags disagree with the estimator's Switchers column fails the stage
    bad = _cli(_stage(tmp_path / "b", [7, 6, 4, 0, 0, 0]), tmp_path / "ob")
    assert bad.returncode == 1 and "MISMATCH" in bad.stdout
    assert (tmp_path / "ob" / "fig4_counts.json").is_file()
    # no sample at all is an error, not an empty success
    (tmp_path / "empty").mkdir()
    assert _cli(tmp_path / "empty", tmp_path / "oe").returncode != 0


def test_model_and_field_come_from_the_label():
    fc = _fc()
    assert [fc.model_of(x) for x in LABELS] == [("M1", 6, 4)] * 3 + [("M2", 5, 4)] * 3 + [("M3", 5, 4)] * 3
    # LABELS is the figure's row order: P1 and P2 run econ, chemistry, maths; the P3 cut rows run maths first
    assert [fc.field_of(x) for x in LABELS] == ["econ", "chemistry", "math_stats"] * 2 + ["math_stats", "chemistry", "econ"]
    with pytest.raises(ValueError):
        fc.model_of("P4_x")
