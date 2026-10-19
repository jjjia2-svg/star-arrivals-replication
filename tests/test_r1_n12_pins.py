# -*- coding: utf-8 -*-
"""R1 P3 N12 parts 2-3 (W2-SENTINEL): the Section 2-3 numbers of the paper are generator-backed.

Part 2: six sentinel pins on sec2_data.tex's empty-row / missing-output shares (Section 2.4), computed
like the funnel tab:na shares from the existing frame-derived keys econ_py_decomp (main ledger) and
chem/math_py_decomp (carried ledger). No new ledger key.
Part 3: analysis/paper/sec23_number_audit.tsv lists every numeral the base tree's sec2_data.tex and
sec3_strategy.tex print, with a category; its key_needs_pin rows are pinned by check_paper's
BASE_TREE_CLAIMS, which run only under --tree base_2026_10_11.

Small runner: toy texts and toy ledgers in tmp_path (October values typed in below), no thesis tree.
The NEWPIN cross-check against the base tree's own sec3_strategy.tex runs only where that tree exists.
"""
from __future__ import annotations

import csv
import importlib.util
import io
import math
import re
import sys
import tokenize
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from analysis.lib.paths import load_paths  # noqa: E402

CHECK_PAPER = REPO / "tools" / "check_paper.py"
AUDIT = REPO / "analysis" / "paper" / "sec23_number_audit.tsv"
CATEGORIES = {"pinned", "key_needs_pin", "design_constant", "needs_key"}

# October py_decomp (thesis ledger data_numbers_2026-10-23.json): rows / empty_no_record / genuine_missing
PY = {"econ": (73073, 5891, 3773), "chem": (30635, 2098, 423), "math": (19910, 2085, 987)}
SEC2 = r"""\REV{Three limitations of the data should be stated up front. First, some Panel 1 rows have no output
value. In economics, 8.1 percent are empty by design: the incumbent was not % src: econ_py_decomp
in post that year and published nothing. Another 5.2 percent have % src: econ_py_decomp
publications, but none with an FWCI value, so output cannot be measured. The
shares are 6.8 and 1.4 percent in chemistry and % src: chem_py_decomp
10.5 and 5.0 percent in mathematics. Years without an FWCI value may have % src: math_py_decomp
higher or lower output than years with one.}
"""


@pytest.fixture
def cp(tmp_path, monkeypatch):
    cfg = {k: str(v) for k, v in load_paths().items()}
    cfg["repo_root"] = "."
    cfg["output"] = str(tmp_path / "out")
    p = tmp_path / "paths_tmp.yaml"
    p.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("SAR_PATHS_CONFIG", str(p))
    spec = importlib.util.spec_from_file_location("check_paper_n12_mod", CHECK_PAPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)   # type: ignore[union-attr]
    return mod


def _decomp(rows, empty, genuine):
    return {"rows": rows, "y_val": rows - empty - genuine, "empty_no_record": empty,
            "genuine_missing": genuine, "pub0_na": 0}


def _main_carried():
    main = {"econ_py_decomp": _decomp(*PY["econ"])}
    carried = {"chem_py_decomp": _decomp(*PY["chem"]), "math_py_decomp": _decomp(*PY["math"])}
    return main, carried


def _grade(cp, pins, files: dict):
    cp.checks.clear()
    cp.grade_pins(pins, {f: re.sub(r"\s+", " ", re.sub(r"(?<!\\)%.*", " ", t)) for f, t in files.items()},
                  set(files))
    return [(c["name"], c["ok"]) for c in cp.checks]


# ---- part 2: the six Section 2.4 shares ------------------------------------------------------------
def test_sec2_empty_share_pins_pass_on_october_values_and_one_digit_fails(cp):
    main, carried = _main_carried()
    pins = cp.sec2_empty_share_claims(main, carried)
    assert len(pins) == 6 and {p[1] for p in pins} == {"sec2_data.tex"}
    assert [p[0] for p in pins] == list(cp.SEC2_EMPTY_SHARE_NAMES)
    assert not any(re.search(r"[0-9]", p[0].replace("sec2", "", 1)) for p in pins)   # no value in the names
    got = _grade(cp, pins, {"sec2_data.tex": SEC2})
    assert len(got) == 6 and all(ok for _, ok in got), got
    # expected values computed exactly like the funnel tab:na shares
    assert [p[3] for p in pins] == [8.1, 5.2, 6.8, 1.4, 10.5, 5.0]
    for old, new in (("8.1 percent", "8.2 percent"), ("Another 5.2", "Another 5.3"), ("6.8 and", "6.9 and"),
                     ("and 1.4 percent", "and 1.5 percent"), ("10.5 and", "10.4 and"), ("and 5.0 percent", "and 5.1 percent")):
        bad = _grade(cp, pins, {"sec2_data.tex": SEC2.replace(old, new, 1)})
        assert sum(not ok for _, ok in bad) == 1, (old, bad)
    # the shares follow the ledger (a changed frame changes the expected value)
    main2 = {"econ_py_decomp": _decomp(73073, 6000, 3773)}
    assert cp.sec2_empty_share_claims(main2, carried)[0][3] == round(100 * 6000 / 73073, 1)
    # the pins are part of claims_table (so the re-pin tools see them) and nowhere duplicated
    src = CHECK_PAPER.read_text(encoding="utf-8")
    body = src[src.index("def claims_table("):src.index("def section_d(")]
    assert "sec2_empty_share_claims(main, carried)" in body


def test_sec2_empty_share_pins_prefer_the_out_of_employment_key(cp):
    main, carried = _main_carried()
    d = main["econ_py_decomp"]
    d["empty_out_of_employment"] = d.pop("empty_no_record")
    assert cp.sec2_empty_share_claims(main, carried)[0][3] == 8.1


# ---- part 3: base-tree claims only under the base tree ---------------------------------------------
BASE_SEC2 = r"""\REV{For every arrival ... All five come from the fixed 26 June 2026 release of OpenAlex, an open
bibliographic database.}
The analysis uses the 26 June 2026 release, which contains 510 million work
\caption{\REV{... The dots are
illustrative; the counts are for Yves Z\'enou's 2016 arrival at Monash
(Section~\ref{sec:panels}).}}
arrival,\footnote{\REV{Panel 1 uses output up to 2026 (up to 2025 in mathematics), and the 26 June 2026 release covers only the first half of 2026.}} % src: x
because its first joint paper is already written.\footnote{\REV{For an arrival
in 2016, as in the Z\'enou example below, pairs are followed from 2010. A pair
whose first joint paper appears in 2013 is followed from 2010 to 2013 and then
leaves. A pair whose first joint paper appeared in 2009 is not followed.}}} % src: y
twice.}} In 2 of the 113 economics arrivals and 1 of the 33 mathematics % src: z
arrivals, fewer than two colleagues qualify, so those arrivals add no pairs.
Yves Z\'enou joined Monash University in 2016 from outside Australia. His
cell, so he meets the star criteria. The Monash economics roster for 2016
lists 60 incumbents; his coauthorship network within two hops reaches 66 % src: a
with a median similarity dose of 0.51. Panel 1 follows all 102; Panel 2 follows 100 of % src: b
them (two had already published with him before 2010), and 6 first publish % src: c
with him after his arrival. Of the 60 on the roster, 36 are outside the % src: d
network, and all 36 share at least one subfield with him. They form 630 % src: e
possible pairs, and Panel 3 follows 624 (the other six had already published % src: f
together before 2010).}
"""
BASE_SEC3 = r"""relations' average dose (0.38 in economics, 0.40 in chemistry, % NEWPIN: x
0.19 in mathematics). The result is on the per-unit scale of $\beta_\ell$: the
With \REV{113} events in economics \REV{(111 of them
contributing pairs to Panel 3)} \REV{the event-clustered errors are informative
too. But} with
\REV{38} events in chemistry and \REV{33} in mathematics \REV{(32 in Panel 3)} % NEWPIN: y
events and re-estimate the model 500 times, leaving samples, doses and each % NEWPIN: z
\REV{As 95 of the 113 economics arrivals follow an earlier star at the same % NEWPIN: w
department within five years (Section~\ref{sec:rob_pre}), (A4) is unlikely to hold in full.
\subsection{How the Coefficients Are Computed: The 2016 Arrivals}\label{sec:example}
\REV{This subsection uses one example, the economics arrivals of 2016, among % NEWPIN: v
them Z\'enou's at Monash (Section~\ref{sec:panels}), to show how each model's
coefficients are computed. For these arrivals 2016 is $\ell=0$ and 2015, the % NEWPIN: u
year before arrival, is $\ell=-1$; each coefficient below averages their part
\REV{The 2016 arrivals' part of the 2018 coefficient is the average change in
log output from 2015 to 2018 among their switching relations, minus the same
change among comparison relations: zero-dose relations and relations whose % src: t
star arrives in 2019 or 2020. % NEWPIN: s
2015, so its star arrives in 2020 at the latest; one whose star arrives in 2021
appears in Panel 1 only from 2016. The 2016 coefficient can use relations whose
star arrives in 2017 to 2020, the 2019 coefficient only those of 2020, and in 2020 and 2021, % NEWPIN: r
four and five years after the arrival, only zero-dose comparisons remain. The
same holds for the 2012 and 2011 placebos: the comparisons of their paired 2018
and 2019 coefficients, with stars arriving in 2019 or 2020, are followed only % NEWPIN: q
from 2014 or 2015, not back to 2012 or 2011.}
whatever their dose, minus that of comparison relations, whose star
arrives in 2019 to 2021, each among relations with no joint paper by 2017.
compare zeros with zeros. The estimates stop at 2020: the last comparisons, % NEWPIN: p
relations whose star arrives in 2021 (followed from 2015), are treated from % NEWPIN: o
2021, so none is left (Figure~\ref{fig:comparison_pools}).} % NEWPIN: n
together in 2018, minus the same share among comparison pairs, at departments
whose star arrives in 2019 to 2021, each among pairs with no joint paper by 2017.}
"""
BASE_SEC4_P3 = r"""Shuffled arrival years give $p=0.235$, and the % src: P3 econ.randomization_inference.p_two_sided
"""


def _pools():
    """fig_comparison_pools.json for the October economics arrivals (2016 cohort)."""
    m1 = {"2011": [], "2012": [], "2013": [2017, 2018, 2019, 2020], "2014": [2017, 2018, 2019, 2020],
          "2016": [2017, 2018, 2019, 2020], "2017": [2018, 2019, 2020], "2018": [2019, 2020], "2019": [2020],
          "2020": [], "2021": []}
    m23 = {"2016": [2017, 2018, 2019, 2020, 2021], "2017": [2018, 2019, 2020, 2021], "2018": [2019, 2020, 2021],
           "2019": [2020, 2021], "2020": [2021], "2021": []}
    cells_m1 = {y: ("used" if v else "none") for y, v in m1.items()}
    cells_m23 = {**{y: "not_reported" for y in ("2011", "2012", "2013", "2014")},
                 **{y: ("used" if v else "no_estimate") for y, v in m23.items()}}
    return {"cohort": 2016, "base": 2015,
            "cells": {"M1_zero": {y: "used" for y in m1}, "M1_pos": cells_m1, "M23": cells_m23},
            "pools": {"M1_pos": {y: {"arrival_years": v, "n_events": len(v)} for y, v in m1.items()},
                      "M23": {y: {"arrival_years": v, "n_events": len(v)} for y, v in m23.items()}}}


def _base_led():
    """The ledger values the base tree prints (October)."""
    return {"zenou": {"roster": 60, "union": 102, "p2_followed": 100, "pairs": 624, "pairs_possible": 630,
                      "pairs_excluded_prewindow": 6, "outside_network": 36, "same_topic_outside": 36,
                      "_event": "A5017376589:2016"},
            "switchers_p1p2": {"p1": {"econ": {"avg_dose_switchers": 0.38333469113},
                                      "chemistry": {"avg_dose_switchers": 0.40452},
                                      "math_stats": {"avg_dose_switchers": 0.19003}}},
            "p3afar": {"econ": {"events_with_pairs": 111, "randomization_inference": {"p_two_sided": 0.2355}},
                       "chemistry": {"events_with_pairs": 38}, "math_stats": {"events_with_pairs": 32}},
            "p1p2": {"perm_pvalues": {"B": 500}, "p1_doublestar_econ": {"events_dropped": 95},
                     "p1_econ": {"events": 113}},
            "main": {"econ_events": 113, "chem_events": 38, "math_events": 33},
            "funnel": {"snapshot_release_date": "2026-06-26"},
            "pools": _pools()}


def _base_tree(root: Path, sec2=BASE_SEC2, sec3=BASE_SEC3, sec4=BASE_SEC4_P3) -> Path:
    (root / "sections").mkdir(parents=True, exist_ok=True)
    (root / "sections" / "sec2_data.tex").write_text(sec2, encoding="utf-8")
    (root / "sections" / "sec3_strategy.tex").write_text(sec3, encoding="utf-8")
    (root / "sections" / "sec4_p3.tex").write_text(sec4, encoding="utf-8")
    return root


def _fails(cp):
    return [c for c in cp.checks if not c["ok"] and not c["retired"] and not c["unrep"]]


def test_base_tree_claims_only_with_base_tree(cp, tmp_path):
    root = _base_tree(tmp_path / "base")
    led = _base_led()
    # default tree: not evaluated at all (thesis_report stays as it is)
    cp.configure(tree_root=root)
    cp.checks.clear()
    cp.section_d_base_tree(led)
    assert cp.checks == []
    # base tree: every claim evaluated, all PASS on the October values
    cp.configure(tree_root=root, tree="base_2026_10_11")
    cp.checks.clear()
    cp.section_d_base_tree(led)
    names = [c["name"] for c in cp.checks]
    assert sorted(names) == sorted(cp.BASE_TREE_CLAIM_NAMES) and len(set(names)) == len(names)
    assert not _fails(cp), [(c["name"], c["detail"]) for c in _fails(cp)]
    assert all(c["file"] in ("sec2_data.tex", "sec3_strategy.tex", "sec4_p3.tex") for c in cp.checks)


@pytest.mark.parametrize("fname, old, new, name_part", [
    ("sec3_strategy.tex", "0.40 in chemistry", "0.41 in chemistry", "average dose"),
    ("sec3_strategy.tex", "(32 in Panel 3)", "(31 in Panel 3)", "Panel 3 events"),
    ("sec3_strategy.tex", "the model 500 times", "the model 1000 times", "shuffled runs"),
    ("sec3_strategy.tex", "As 95 of the 113", "As 96 of the 113", "earlier star"),
    ("sec3_strategy.tex", "arrivals of 2016, among", "arrivals of 2017, among", "example arrivals year"),
    ("sec3_strategy.tex", "and 2015, the", "and 2014, the", "ell=-1"),
    ("sec3_strategy.tex", "star arrives in 2017 to 2020", "star arrives in 2018 to 2020", "M1 2016"),
    ("sec3_strategy.tex", "The estimates stop at 2020", "The estimates stop at 2021", "stop"),
    ("sec4_p3.tex", "$p=0.235$", "$p=0.236$", "shuffled arrival years p"),
    ("sec2_data.tex", "Panel 1 follows all 102", "Panel 1 follows all 101", "Panel 1 follows all"),
    ("sec2_data.tex", "(two had already", "(three had already", "(word)"),
    ("sec2_data.tex", "and 1 of the 33 mathematics", "and 2 of the 33 mathematics", "no-pair math"),
    ("sec2_data.tex", "followed from 2010. A pair", "followed from 2011. A pair", "first followed"),
])
def test_one_changed_base_number_gives_exactly_one_fail(cp, tmp_path, fname, old, new, name_part):
    texts = {"sec2_data.tex": BASE_SEC2, "sec3_strategy.tex": BASE_SEC3, "sec4_p3.tex": BASE_SEC4_P3}
    assert old in texts[fname]
    texts[fname] = texts[fname].replace(old, new, 1)
    root = _base_tree(tmp_path / "base", texts["sec2_data.tex"], texts["sec3_strategy.tex"], texts["sec4_p3.tex"])
    cp.configure(tree_root=root, tree="base_2026_10_11")
    cp.checks.clear()
    cp.section_d_base_tree(_base_led())
    bad = _fails(cp)
    assert len(bad) == 1 and name_part in bad[0]["name"], [(c["name"], c["detail"]) for c in bad]


def test_base_tree_claims_follow_the_ledgers(cp, tmp_path):
    root = _base_tree(tmp_path / "base")
    cp.configure(tree_root=root, tree="base_2026_10_11")
    led = _base_led()
    led["p3afar"]["econ"]["randomization_inference"]["p_two_sided"] = 118 / 501   # N12 full precision -> 0.236
    led["pools"]["pools"]["M1_pos"]["2019"]["arrival_years"] = []                  # no 2020 econ arrival left
    cp.checks.clear()
    cp.section_d_base_tree(led)
    assert sorted(c["name"] for c in _fails(cp)) == sorted(
        n for n in cp.BASE_TREE_CLAIM_NAMES if "shuffled arrival years p" in n or "M1 2019 comparisons" in n)
    # a missing ledger is a FAIL per claim it would have fed, never a silent skip
    led = _base_led()
    del led["pools"]
    cp.checks.clear()
    cp.section_d_base_tree(led)
    assert {c["name"] for c in _fails(cp)} == {n for n in cp.BASE_TREE_CLAIM_NAMES if n in cp.BASE_TREE_POOL_CLAIMS}
    assert all("not evaluated" in c["detail"] for c in _fails(cp))


def test_the_zenou_all_share_sentence_holds_only_while_the_two_counts_are_equal(cp, tmp_path):
    """final-06: under M 117 incumbents are outside Z\\'enou's network and 103 of them share a subfield with him;
    the sentence '..., and all 103 share at least one subfield' kept its 'all' and no check saw it. The claim
    holds while same_topic_outside equals outside_network; when it does not, its anchor is found, so gate 2
    sends the sentence to the author (CLAIM_FALSE) instead of failing hard."""
    name = cp.BASE_TREE_ZENOU_CLAIMS[16]
    assert "all" in name and name in cp.BASE_TREE_CLAIM_NAMES
    cp.configure(tree_root=_base_tree(tmp_path / "base"), tree="base_2026_10_11")
    for same, ok in ((36, True), (30, False)):
        led = _base_led()
        led["zenou"]["same_topic_outside"] = same
        cp.checks.clear()
        cp.section_d_base_tree(led)
        c = next(c for c in cp.checks if c["name"] == name)
        assert (c["ok"], c["kind"], c["anchor_found"]) == (ok, "claim", True), c
        assert ("30" in c["detail"]) is not ok and "36" in c["detail"], c


# ---- part 3: the audit table ------------------------------------------------------------------------
def _audit_rows():
    lines = [ln for ln in AUDIT.read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#")]
    rows = list(csv.DictReader(io.StringIO("\n".join(lines)), delimiter="\t"))
    assert rows and list(rows[0]) == ["file", "line", "numeral", "category", "ref", "newpin_line", "note"]
    return rows


def _literals(src: str):
    """Plain string literals and f-string heads of check_paper.py (pin names are built from these)."""
    lits, heads = set(), set()
    toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    fs_start = getattr(tokenize, "FSTRING_START", None)
    fs_mid = getattr(tokenize, "FSTRING_MIDDLE", None)
    for i, t in enumerate(toks):
        if t.type == tokenize.STRING:
            m = re.match(r"^([A-Za-z]*)('''|\"\"\"|'|\")", t.string)
            val = t.string[m.end():len(t.string) - len(m.group(2))]
            (heads.add(val.split("{", 1)[0]) if "f" in m.group(1).lower() else lits.add(val))
        elif fs_mid is not None and t.type == fs_mid and toks[i - 1].type == fs_start:
            heads.add(t.string)
    return lits, heads


def test_audit_rows_are_backed(cp):
    rows = _audit_rows()
    lits, heads = _literals(CHECK_PAPER.read_text(encoding="utf-8"))
    for r in rows:
        # sec2/sec3 of the base tree, plus the one base sec4_p3 sentence N12 names (shuffled-years p)
        assert r["file"] in ("sec2_data.tex", "sec3_strategy.tex", "sec4_p3.tex"), r
        assert r["line"].isdigit() and r["numeral"] and r["category"] in CATEGORIES, r
        assert r["note"].strip(), r
        if r["category"] == "pinned":
            ref = r["ref"]
            assert ref in lits or any(h and ref.startswith(h) and ref[len(h):] in lits for h in heads), r
        elif r["category"] == "key_needs_pin":
            assert r["ref"] in cp.BASE_TREE_CLAIM_NAMES, r
        elif r["category"] == "needs_key":
            assert re.fullmatch(r"data_numbers_r1_counts:[a-z0-9_]+", r["ref"]), r
        else:
            assert r["ref"] == "-", r
    # every base-tree claim answers at least one audit row, and every needs_key key is distinct per number
    assert set(cp.BASE_TREE_CLAIM_NAMES) <= {r["ref"] for r in rows if r["category"] == "key_needs_pin"}
    # the six Section 2.4 shares are pinned rows
    assert set(cp.SEC2_EMPTY_SHARE_NAMES) <= {r["ref"] for r in rows if r["category"] == "pinned"}
    # every sec3 NEWPIN marker has at least one row
    marks = {int(r["newpin_line"]) for r in rows if r["newpin_line"] != "-"}
    assert marks == set(cp.BASE_TREE_SEC3_NEWPIN_LINES) and len(marks) == 22
    assert all(r["file"] == "sec3_strategy.tex" for r in rows if r["newpin_line"] != "-")


def test_audit_newpin_lines_match_the_base_tree_when_present(cp):
    sec3 = load_paths()["legacy_thesis"] / cp.BASE_TREE_REL / "sections" / "sec3_strategy.tex"
    if not sec3.is_file():
        pytest.skip(f"base tree not on this machine ({cp.BASE_TREE_REL})")
    lines = sec3.read_text(encoding="utf-8").splitlines()
    marks = {i for i, ln in enumerate(lines, start=1) if re.search(r"(?<!\\)% NEWPIN:", ln)}
    assert marks == set(cp.BASE_TREE_SEC3_NEWPIN_LINES)
    # each audited numeral is printed on its line (comments stripped)
    for r in _audit_rows():
        if r["file"] != "sec3_strategy.tex" or not re.match(r"^[-$0-9.,{}]+$", r["numeral"]):
            continue
        live = re.sub(r"(?<!\\)%.*", "", lines[int(r["line"]) - 1])
        assert r["numeral"] in live, r


# ---- review R7 #8: claim records carry kind/anchor_found (gate 2 routes a flipped claim to the author,
# a lost sentence stays a hard failure); Table 3's n.a. cell is checked by its structure -----------------
def test_base_tree_word_and_phrase_claims_carry_kind_and_anchor(cp, tmp_path):
    words = {cp.BASE_TREE_ZENOU_CLAIMS[10], cp.BASE_TREE_ZENOU_CLAIMS[11]}
    phrases = set(cp.BASE_TREE_POOL_CLAIMS[17:20]) | {cp.BASE_TREE_ZENOU_CLAIMS[16]}
    cp.configure(tree_root=_base_tree(tmp_path / "base"), tree="base_2026_10_11")
    cp.checks.clear()
    cp.section_d_base_tree(_base_led())
    by = {c["name"]: c for c in cp.checks}
    for n in words | phrases:
        assert (by[n]["ok"], by[n]["kind"], by[n]["anchor_found"]) == (True, "claim", True), n
    assert all(by[n].get("kind") is None for n in set(cp.BASE_TREE_CLAIM_NAMES) - words - phrases)
    led = _base_led()
    led["zenou"]["p2_followed"] = 99                       # 102 - 99 = 3; the sentence says "two"
    cp.checks.clear()
    cp.section_d_base_tree(led)
    c = next(c for c in cp.checks if c["name"] == cp.BASE_TREE_ZENOU_CLAIMS[10])
    assert (c["ok"], c["kind"], c["anchor_found"]) == (False, "claim", True)
    cp.configure(tree_root=_base_tree(tmp_path / "b2", sec3=BASE_SEC3.replace("not back to 2012 or 2011", "earlier")),
                 tree="base_2026_10_11")
    cp.checks.clear()
    cp.section_d_base_tree(_base_led())
    c = next(c for c in cp.checks if c["name"] == cp.BASE_TREE_POOL_CLAIMS[18])
    assert (c["ok"], c["kind"], c["anchor_found"]) == (False, "claim", False)


NA_ROW = r"\REV{\quad date-shift test} & \REV{0.697} & \REV{0.156} & \REV{n.a.} & \REV{Econ., Chem.} \\"
P1_DS_ROW = r"\REV{\quad date-shift test} & \REV{0.199} & \REV{0.590} & \REV{0.126} & \REV{All} \\"


@pytest.mark.parametrize("row, found", [
    (NA_ROW, True),                                                          # the base row
    (NA_ROW.replace("0.697", "0.512").replace("0.156", "$<$0.001"), True),   # other P2 p values (M)
    (NA_ROW.replace("n.a.", "0.420"), False)])                               # the math cell is numeric
def test_table3_math_p2_na_is_checked_by_structure(cp, row, found):
    for status in ("AUX_FAILED", "OK"):
        cp.checks.clear()
        cp.claim_tab3_math_p2_na(P1_DS_ROW + " " + row, status)
        (c,) = cp.checks
        assert c["name"] == "r4 Table 3 math P2 date-shift prints n.a."
        assert c["ok"] is (found and status == "AUX_FAILED"), (row, status)
        assert (c["kind"], c["anchor_found"], c["file"]) == ("claim", found, "tab_robustness.tex")
    src = CHECK_PAPER.read_text(encoding="utf-8")
    body = src[src.index("def section_d_r4_claims("):src.index("def _nan_unless(")]
    assert "claim_tab3_math_p2_na(" in body and r"\REV{0.697} & \REV{0.156}" not in body


def test_claim_and_word_checks_pass_kind_and_anchor():
    """The r4 claim() helper, the two-hop share and the 'about three times' word check record kind='claim'
    and anchor_found (read from the source: their inputs are whole ledgers)."""
    src = CHECK_PAPER.read_text(encoding="utf-8")
    body = src[src.index("    def claim(name, fname, phrase, ok"):src.index("    def spans0(")]
    assert body.count('kind="claim"') == 2 and body.count("anchor_found=") == 2
    for name in ("r4 sec2 footnote econ two-hop share 99 percent",
                 "rob missing-output econ fillings ratio (about three times)"):
        i = src.index(f'"{name}"')
        call = src[i:src.index("\n\n", i)]
        assert 'kind="claim"' in call and "anchor_found=" in call, name
