# -*- coding: utf-8 -*-
"""R1 P3 V3-FINAL.c follow-up (W3-OVERLAY): the sentinel's 'vault' profile pins the base tree's reworded text.

tools/check_paper.py keeps the measured overlay in three committed tables:
  VAULT_OVERLAY_REANCHOR  pin name -> (file, regex[, group]) on the base tree's sentence or table row
                          that prints the same ledger number;
  VAULT_OVERLAY_RETIRE    pin name -> reason, only for a number the base tree prints nowhere;
  VAULT_OVERLAY_REPHRASE  section_d_r4_claims claim name -> (file, sentence) stating the same claim.
configure(profile='vault') binds them into VAULT_REANCHOR / VAULT_RETIRE / VAULT_REPHRASE; any other
profile leaves those empty, so the default ('thesis') run is today's, byte for byte.

The base-tree text is the fixture tests/fixtures/r1_paper/base_tree_2026-10-11/ (sections/ + main.tex
from this unit, tables/ + ledgers/ from W1-PTABLES; byte copies, md5 in each SOURCE.md). The ledgers
are the October thesis ledgers the base tree carries. Small runner: nothing outside the repo is read,
nothing is written, no generator runs ($SAR_PATHS_CONFIG points `output` at an empty tmp dir).
"""
from __future__ import annotations

import importlib.util
import json
import math
import re
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from analysis.lib.paths import load_paths  # noqa: E402

CHECK_PAPER = REPO / "tools" / "check_paper.py"
FIX = REPO / "tests" / "fixtures" / "r1_paper" / "base_tree_2026-10-11"
if not FIX.is_dir():   # public copy: the manuscript fixtures are not shipped
    pytest.skip("needs the manuscript fixtures in tests/fixtures/r1_paper/ (not shipped)", allow_module_level=True)
DATE = "2026-10-23"

# The measured sizes (2026-10-16, read-only Mac measurement; tests/fixtures/.../sections/SOURCE.md).
N_REANCHOR, N_RETIRE, N_REPHRASE = 75, 3, 7

# Every place the base tree prints the digits of a retired pin's number is a different quantity; each
# such place is named here by a phrase around it. A new occurrence, or a phrase no longer found, fails.
COINCIDENCES = {
    "p3 econ headline permutation 24 percent": ("24 percent in chemistry", "(23 of 38 and 24 of 33)"),
    "p3 perm pct econ 24": ("24 percent in chemistry", "(23 of 38 and 24 of 33)"),
    "rob star threshold math P2 first ties 25": (),
}


def _tmp_config(tmp_path: Path) -> Path:
    """The paths config in force, written absolute, with `output` moved to an empty tmp dir."""
    cfg = {k: str(v) for k, v in load_paths().items()}
    cfg["repo_root"] = "."
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    cfg["output"] = str(out)
    p = tmp_path / "paths_tmp.yaml"
    p.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return p


@pytest.fixture
def cp(tmp_path, monkeypatch):
    """A fresh tools/check_paper.py module loaded under the tmp config."""
    monkeypatch.setenv("SAR_PATHS_CONFIG", str(_tmp_config(tmp_path)))
    spec = importlib.util.spec_from_file_location("check_paper_vault_mod", CHECK_PAPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)   # type: ignore[union-attr]
    return mod


def _led(cp):
    """The ledgers section D reads, from the base tree's October thesis ledgers. The main thesis ledger
    holds the main and carried keys merged; the gap/funnel ledgers are not in the fixture, so their pin
    blocks are absent (none of the overlay's pins is in them)."""
    def lj(name):
        return json.loads((FIX / "ledgers" / name).read_text(encoding="utf-8"))
    main = lj(f"data_numbers_{DATE}.json")
    gold = json.loads((cp.P["expected"] / "P1_econ_fnfix.json").read_text(encoding="utf-8"))
    return {"main": main, "carried": main, "funnel": None, "zenou": None, "zero": None, "switchers": None,
            "toy": None, "switchers_p1p2": None, "p3afar": lj(f"data_numbers_{DATE}_p3afar.json"),
            "p1p2": lj(f"data_numbers_{DATE}_p1p2.json"), "robustness": lj(f"data_numbers_{DATE}_robustness.json"),
            "gold_p1_union": gold["channels"]["union"]}


def _configure(cp, profile):
    cp.configure(thesis_root=FIX, ledger_date=DATE, profile=profile, tree="base_2026_10_11")


def _tex(cp):
    tex = {f: cp.norm_tex(FIX / "sections" / f) for f in cp.D_SECTION_FILES}
    tex.update({f: cp.norm_tex(FIX / "tables" / f) for f in cp.D_TABLE_FILES})
    tex["main.tex"] = cp.norm_tex(FIX / "sections" / "main.tex")
    return tex


def _grade(cp, profile):
    _configure(cp, profile)
    pins = cp.apply_profile(cp.claims_table(_led(cp)), profile)
    cp.checks.clear()
    tex = _tex(cp)
    cp.grade_pins(pins, tex, set(tex))
    return {c["name"]: c for c in cp.checks}


# ---- the overlay names real pins and claims --------------------------------------------------------
def test_overlay_keys_name_existing_pins_and_claims(cp):
    assert (len(cp.VAULT_OVERLAY_REANCHOR), len(cp.VAULT_OVERLAY_RETIRE), len(cp.VAULT_OVERLAY_REPHRASE)) \
        == (N_REANCHOR, N_RETIRE, N_REPHRASE)
    _configure(cp, "vault")
    assert cp.VAULT_REANCHOR == cp.VAULT_OVERLAY_REANCHOR and cp.VAULT_RETIRE == cp.VAULT_OVERLAY_RETIRE
    assert cp.VAULT_REPHRASE == cp.VAULT_OVERLAY_REPHRASE
    led = _led(cp)
    pins = cp.claims_table(led)
    names = {p[0] for p in pins}
    assert sorted((set(cp.VAULT_REANCHOR) | set(cp.VAULT_RETIRE)) - names) == []
    cp.apply_profile(pins, "vault")
    assert cp.VAULT_UNMATCHED == []
    cp.checks.clear()
    cp.section_d_r4_claims(led)
    claimed = {c["name"] for c in cp.checks}
    assert set(cp.VAULT_REPHRASE) <= claimed
    assert not [c for c in cp.checks if c["name"].startswith("vault overlay entry")]
    for name, spec in cp.VAULT_REANCHOR.items():
        assert len(spec) in (2, 3) and spec[0] in cp.D_SECTION_FILES + cp.D_TABLE_FILES, name
    for name, (fname, phrase) in cp.VAULT_REPHRASE.items():
        assert fname.endswith(".tex") and len(phrase) > 30, name


def test_an_overlay_name_that_names_no_claim_fails(cp, monkeypatch):
    _configure(cp, "vault")
    monkeypatch.setattr(cp, "VAULT_REPHRASE", {**cp.VAULT_REPHRASE, "no such claim": ("sec4_p3.tex", "x" * 40)})
    cp.checks.clear()
    cp.section_d_r4_claims(_led(cp))
    bad = [c for c in cp.checks if c["name"] == "vault overlay entry 'no such claim'"]
    assert len(bad) == 1 and not bad[0]["ok"]


# ---- the overlay is exactly the measured FAIL list, and fixes it ------------------------------------
def test_the_overlay_is_exactly_the_base_trees_fail_list_and_every_pin_passes_under_vault(cp):
    thesis = _grade(cp, "thesis")
    fails = {n for n, c in thesis.items() if not c["ok"]}
    assert fails == set(cp.VAULT_OVERLAY_REANCHOR) | set(cp.VAULT_OVERLAY_RETIRE)
    assert all(thesis[n]["detail"].startswith("pattern not found") for n in fails)
    vault = _grade(cp, "vault")
    assert [n for n, c in vault.items() if not c["ok"]] == []
    for name in cp.VAULT_OVERLAY_REANCHOR:
        assert vault[name]["ok"] and not vault[name]["retired"], (name, vault[name]["detail"])
    for name in cp.VAULT_OVERLAY_RETIRE:
        assert vault[name]["retired"], name
    # pins outside the overlay grade the same under both profiles
    for name in set(thesis) - fails:
        assert (thesis[name]["ok"], thesis[name]["retired"]) == (vault[name]["ok"], vault[name]["retired"]), name


def test_r4_rephrasings_are_exactly_the_base_trees_missing_sentences(cp):
    led = _led(cp)
    _configure(cp, "thesis")
    cp.checks.clear()
    cp.section_d_r4_claims(led)
    fails = {c["name"]: c for c in cp.checks if not c["ok"]}
    assert set(fails) == set(cp.VAULT_OVERLAY_REPHRASE)
    assert all(c["detail"].startswith("sentence not found") for c in fails.values())
    _configure(cp, "vault")
    cp.checks.clear()
    cp.section_d_r4_claims(led)
    assert [(c["name"], c["detail"]) for c in cp.checks if not c["ok"]] == []
    graded = {c["name"] for c in cp.checks}
    assert set(cp.VAULT_OVERLAY_REPHRASE) <= graded


# ---- a retirement only for a number the base tree does not print ------------------------------------
def _number_rx(value):
    f = float(value)
    if f.is_integer():
        return r"(?<![0-9A-Za-z.,}])" + str(int(f)) + r"(?![0-9]|\.[0-9]|\{,\})"
    return r"(?<![0-9.])" + re.escape(repr(f)) + r"0*(?![0-9])"


def test_every_retired_pin_number_is_absent_from_the_base_tree(cp):
    _configure(cp, "vault")
    pins = {p[0]: p for p in cp.claims_table(_led(cp))}
    texts = {f"sections/{p.name}": cp.norm_tex(p) for p in sorted((FIX / "sections").glob("*.tex"))}
    texts.update({f"tables/{p.name}": cp.norm_tex(p) for p in sorted((FIX / "tables").glob("*.tex"))})
    assert len(texts) == 14 + 13
    assert set(cp.VAULT_OVERLAY_RETIRE) == set(COINCIDENCES)
    for name, why in cp.VAULT_OVERLAY_RETIRE.items():
        assert len(why.strip()) > 30 and ".tex" in why, name
        _, fname, _, expected, _, _ = pins[name]
        assert not isinstance(expected, tuple), name
        rx = _number_rx(expected)
        own = ("tables/" if fname.startswith("tab_") else "sections/") + fname
        assert not re.search(rx, texts[own]), (name, "printed in its own file")
        seen = set()
        for rel, t in texts.items():
            for m in re.finditer(rx, t):
                ctx = t[max(0, m.start() - 60): m.end() + 60]
                hit = [ph for ph in COINCIDENCES[name] if ph in ctx]
                assert hit, (name, rel, ctx)
                seen.update(hit)
        assert seen == set(COINCIDENCES[name]), (name, "stale coincidence phrase")
    # the rule is real: a re-anchored number is printed, so the same scan finds it
    _, _, _, expected, _, _ = pins["p2 prose path chem ell=4"]
    assert re.search(_number_rx(expected), texts["sections/sec4_p2.tex"])


# ---- switch-off: the 'thesis' profile is today's sentinel ---------------------------------------------
def test_the_thesis_profile_binds_no_overlay_and_stays_the_identity(cp):
    for _ in range(2):
        assert cp.VAULT_REANCHOR == {} and cp.VAULT_RETIRE == {} and cp.VAULT_REPHRASE == {}
        assert cp.PROFILE == "thesis"
        cp.configure(profile="vault")
        assert cp.VAULT_REANCHOR == cp.VAULT_OVERLAY_REANCHOR
        assert cp.VAULT_REANCHOR is not cp.VAULT_OVERLAY_REANCHOR      # a copy: the table is never mutated
        cp.configure()
    led = _led(cp)
    pins = cp.claims_table(led)
    assert cp.apply_profile(pins, "thesis") is pins
    assert cp.claims_for_profile(led, "thesis") == pins
    assert cp.VAULT_REANCHOR == {} and cp.PROFILE == "thesis"


def test_claims_for_profile_gives_the_repin_tools_the_vault_pins(cp):
    led = _led(cp)
    vault = {p[0]: p for p in cp.claims_for_profile(led, "vault")}
    thesis = {p[0]: p for p in cp.claims_table(led)}
    assert set(vault) == set(thesis)
    moved = {n for n in vault if vault[n][1:3] != thesis[n][1:3] or vault[n][4] != thesis[n][4]}
    assert moved == set(cp.VAULT_OVERLAY_REANCHOR)
    name, fname, rx, expected, group, note = vault["p2 prose joint econ event p=0.003"]
    assert (fname, group, expected) == ("tab_main_results.tex", 4, thesis[name][3])
    assert all(vault[n][3] == thesis[n][3] for n in vault)          # ledger expressions never move
    retired = {n for n in vault if vault[n][5].startswith(cp.RETIRED_TAG) and not thesis[n][5].startswith(cp.RETIRED_TAG)}
    assert retired == set(cp.VAULT_OVERLAY_RETIRE)


# ---- M: carried keys the ledger lists as unreproducible ----------------------------------------------
def test_unreproducible_carried_keys_keep_the_pins_and_send_the_printed_sentence_to_the_author(cp):
    """M (ledger_carried, final-03 follow-up): the econ evidence counts and the centre counts have no source
    in force, so the M carried ledger lists them in _unreproducible instead of deriving them. claims_table
    still builds; their pins carry NaN (the repin tools send a NaN span to the author and never edit it); on
    the base tree the retired fellowship pin stays retired and the centre footnote, still printed, FAILs."""
    led = _led(cp)
    gone = ("econ_arc_evidence_people", "econ_fellow_evidence_rows", "chem_centre_added", "math_centre_added")
    carried = {k: v for k, v in led["carried"].items() if k not in gone}
    carried["_unreproducible"] = {k: "no source in force" for k in gone}
    led = {**led, "carried": carried}
    _configure(cp, "vault")
    pins = cp.apply_profile(cp.claims_table(led), "vault")
    by_name = {p[0]: p for p in pins}
    centre = ("sec2 centre roster added chem 134", "sec2 centre roster added math 28")
    for name in ("sec2 fellowship entries 205",) + centre:
        assert isinstance(by_name[name][3], float) and math.isnan(by_name[name][3]), name
    cp.checks.clear()
    tex = _tex(cp)
    cp.grade_pins(pins, tex, set(tex))
    got = {c["name"]: c for c in cp.checks}
    assert got["sec2 fellowship entries 205"]["retired"]
    for name in centre:
        assert not got[name]["ok"] and "ledger expects nan" in got[name]["detail"], got[name]
    assert got["sec2 verified econ roster 1008"]["ok"]      # roster_people is derived under M too


# ---- R1 M (final-03 audit, 2026-10-18): Table 2's Panel 2 joint-test cells may print '$<$' anywhere ----
# Under M the economics event-clustered p is 1.4e-05, so the draft generator prints '$<$0.001' where the
# October pattern wants a bare number. The pattern now reads Table 2's Panel 2 block only and takes either
# form in every p cell (non-capturing prefix: the October groups are kept); the economics pin takes the
# generator's own rule. October gives the same two report lines.
P2J_ECON_EVENT = "p2 prose joint econ event p=0.003"
P2J_CHEM_EVENT = "p2 prose joint econ+chem event p<0.001"
P2J_OCTOBER = {P2J_ECON_EVENT: "tab_main_results.tex prints 0.003 == ledger 0.003",
               P2J_CHEM_EVENT: ("tab_main_results.tex prints threshold 0.001 (expected the literal 0.001); "
                                "ledger value 0.00049439 is below it")}
P2_EVENT_ROW = "\\REV{\\quad event clusters} & \\REV{0.003} & \\REV{$<$0.001} & \\REV{0.109}"
P1_EVENT_ROW = "\\REV{\\quad event clusters} & \\REV{$<$0.001} & \\REV{$<$0.001} & \\REV{0.008}"


def _grade_p2j(cp, led, tex):
    _configure(cp, "vault")
    pins = [p for p in cp.apply_profile(cp.claims_table(led), "vault") if p[0] in P2J_OCTOBER]
    assert len(pins) == 2
    cp.checks.clear()
    cp.grade_pins(pins, tex, set(tex))
    return {c["name"]: c for c in cp.checks}


def test_p2_joint_table_pins_keep_the_october_report_lines(cp):
    got = _grade_p2j(cp, _led(cp), _tex(cp))
    assert {n: (c["ok"], c["detail"]) for n, c in got.items()} == {n: (True, d) for n, d in P2J_OCTOBER.items()}


def test_p2_joint_table_pins_read_less_than_cells_in_panel_2_only(cp):
    led = _led(cp)
    led["p1p2"]["p2_econ"]["p_joint_effects_event"] = 1.426e-05       # M: Table 2 prints $<$0.001
    tex = _tex(cp)
    t = tex["tab_main_results.tex"]
    assert t.count(P2_EVENT_ROW) == 1 and t.count(P1_EVENT_ROW) == 1
    t = t.replace(P2_EVENT_ROW, P2_EVENT_ROW.replace("{0.003}", "{$<$0.001}"))
    # Panel 1's rows now fit the loosened cells too; its economics event cell must never be the one read
    t = t.replace(P1_EVENT_ROW, P1_EVENT_ROW.replace("event clusters} & \\REV{$<$0.001}", "event clusters} & \\REV{0.123}"))
    tex["tab_main_results.tex"] = t
    got = _grade_p2j(cp, led, tex)
    assert got[P2J_ECON_EVENT]["ok"], got[P2J_ECON_EVENT]
    assert got[P2J_ECON_EVENT]["detail"] == ("tab_main_results.tex prints threshold 0.001 (expected the literal "
                                             "0.001); ledger value 1.426e-05 is below it")
    assert got[P2J_CHEM_EVENT]["ok"], got[P2J_CHEM_EVENT]
    # a stale October cell does not pass once the ledger p is below 0.001
    tex["tab_main_results.tex"] = t.replace("event clusters} & \\REV{$<$0.001} & \\REV{$<$0.001} & \\REV{0.109}",
                                            "event clusters} & \\REV{0.003} & \\REV{$<$0.001} & \\REV{0.109}")
    assert not _grade_p2j(cp, led, tex)[P2J_ECON_EVENT]["ok"]
