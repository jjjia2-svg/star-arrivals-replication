"""tests/test_nocentre_cal2026_10.py — the ± research-centre check (T6-1) on the October canon (2026-09-23).

Read-only pins on what analysis/robustness/sensitivity/run_nocentre_cal2026_10.py froze under
data/cal2026-10/robustness/nocentre/ and its nocentre_report.json: the inputs are the promoted canon
(sha256 recomputed; the two driver files R1 changed afterwards are checked against git at the R1 base),
every control the report calls EQUAL is compare_json-EQUAL to its gold on disk
(recomputed, not trusted), the two driver runs stopped nowhere and their controls are clean, the
population change is the roster substitution and nothing else (the accounting closed with named
causes; -134 chemistry / -28 math_stats people = the research-centre staff of the 2026-08-10
ruling), every cell's JSON carries the label / headline the report records, NOT_RUN.md is gone,
the MANIFEST pins every product, and the driver's default behaviour is unchanged (--roster-variant
defaults to fnfix). Needs neither R nor the data disk.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
NC = REPO / "data/cal2026-10/robustness/nocentre"
REPORT = NC / "nocentre_report.json"
FIELDS = ("chemistry", "math_stats")
DRIVER = REPO / "pipeline/frames/cal2026-10/run_cal_frames_chemmath.py"
LAUNCHER = REPO / "analysis/robustness/sensitivity/run_nocentre_cal2026_10.py"

pytestmark = pytest.mark.skipif(not REPORT.is_file(), reason="nocentre_report.json not frozen")

#: inputs of the 2026-09-23 run that R1 changed on purpose afterwards: W1-OCT-A (00a62f6) gave the chem/maths
#: driver and stage.py explicit event tables and run-config stage sections, with October's values as the
#: defaults. The run used their last pre-R1 versions, which git holds at the R1 base PRE_R1 (the commit every
#: R1 wave-1 branch was cut from). Any other moved input - and a listed one that has stopped moving - fails.
PRE_R1 = "7abc0cf8eff440b3fc422f1d30cc8d3ada221616"
R1_CHANGED = ("pipeline/frames/cal2026-10/run_cal_frames_chemmath.py", "pipeline/frames/cal2026-10/stage.py")

#: the population change the roster substitution produces (byte-stable products: relationships,
#: becoming; the p1 row counts follow the relations), measured 2026-09-23
PIN = {
    "chemistry": {"roster_persons": (518, 384), "relations": (2785, 2361), "persons": (470, 330),
                  "p1_rows": (30635, 25971), "p2_rows": (46168, 39010), "pairs": (109984, 77167),
                  "removed_by_cause": {"person_not_in_variant_roster": 349, "no_variant_spell_at_arrival": 75},
                  "channel_changed": {"both->network": 5}, "events": 38},
    "math_stats": {"roster_persons": (573, 545), "relations": (1810, 1769), "persons": (481, 454),
                   "p1_rows": (19910, 19459), "p2_rows": (30314, 29645), "pairs": (55237, 52369),
                   "removed_by_cause": {"person_not_in_variant_roster": 38, "no_variant_spell_at_arrival": 3},
                   "channel_changed": {}, "events": 33},
}
CELLS = ("P1nc_chemistry", "P1nc_math_stats", "P2nc_chemistry", "P2nc_math_stats", "P3nc_math_stats_full",
         "P3nc_pos_chemistry_A_far", "P3nc_pos_math_stats_A_far")
CONTROLS = {"P1_fnfix_chemistry": "P1_fnfix_chemistry", "P1_fnfix_math_stats": "P1_fnfix_math_stats",
            "P2_fnfix_chemistry": "P2_fnfix_chemistry", "P2_fnfix_math_stats": "P2_fnfix_math_stats",
            "P3_fnfix_math_stats": "P3_fnfix_math_stats",
            "P3cut_pos_chemistry": "P3pos_chemistry_A_far", "P3cut_pos_math_stats": "P3pos_math_stats_A_far"}


def _rep() -> dict:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _sha_at(commit: str, relp: str) -> str:
    """sha256 of `relp` as git holds it at `commit`; a commit missing from the clone fails, it never skips."""
    blob = subprocess.run(["git", "show", f"{commit}:{relp}"], cwd=REPO, capture_output=True, check=True).stdout
    return hashlib.sha256(blob).hexdigest()


def _compare(new: pathlib.Path, gold: pathlib.Path) -> bool:
    proc = subprocess.run([sys.executable, "-m", "analysis.lib.compare_json", str(new), str(gold)],
                          cwd=REPO, capture_output=True, text=True)
    return proc.returncode == 0 and proc.stdout.strip().startswith("EQUAL")


def test_report_is_done_and_its_inputs_are_the_promoted_canon():
    r = _rep()
    assert r["group"] == "nocentre" and r["caliber"] == "cal2026-10" and r["status"] == "DONE" and r["stops"] == []
    moved = sorted(relp for relp, h in r["inputs"]["sha256"].items() if _sha(REPO / relp) != h)
    assert moved == sorted(R1_CHANGED), f"inputs moved since the run: {moved} (R1-declared: {list(R1_CHANGED)})"
    assert all(r["inputs"]["frozen_october_frames_match_their_MANIFEST"].values())
    assert all(r["inputs"]["data_frames_equal_frozen_october"].values())
    assert all(r["inputs"]["incfel_roster_equals_legacy_2026-08-10_copy"].values())
    for f in FIELDS:
        rp = r["inputs"]["roster_persons"][f]
        assert (rp["canon"], rp["incfel"]) == PIN[f]["roster_persons"]
        assert rp["only_canon (research-centre staff)"] == rp["canon"] - rp["incfel"] and rp["only_incfel"] == 0


def test_report_historical_inputs_match_pre_r1():
    # The public repository starts with public bytes; private Git history is not shipped.
    for relp in R1_CHANGED:
        present = subprocess.run(["git", "cat-file", "-e", f"{PRE_R1}:{relp}"],
                                 cwd=REPO, capture_output=True)
        if present.returncode:
            pytest.skip("pre-R1 Git input objects are not shipped with the public repository")
    r = _rep()
    for relp in R1_CHANGED:
        assert _sha_at(PRE_R1, relp) == r["inputs"]["sha256"][relp], relp


def test_both_driver_runs_stopped_nowhere_and_their_controls_are_clean():
    r = _rep()
    for tag in ("control", "variant"):
        d = r["driver_runs"][tag]
        assert d["rc"] == 0 and d["driver_stops"] == [], tag
        rep = REPO / d["report"]
        assert rep.is_file() and _sha(rep) == d["report_sha256"]
        j = json.loads(rep.read_text(encoding="utf-8"))
        assert j["stops"] == [] and j["roster_variant"] == ("fnfix" if tag == "control" else "incfel")
        for f in FIELDS:
            c = d["fields"][f]
            assert c["control_ok"] is True, (tag, f)
            assert c["prodlib_control_vs_08_28"] == "BYTE_EQUAL" and c["relationships_vs_08_28"] == "BYTE_EQUAL"
            assert c["p2_becoming_vs_08_28"] == "BYTE_EQUAL" and c["p1_frame_vs_08_28_H1"]["ok"] is True
            assert c["p1_frame_vs_08_28_H1"]["worst_ulp"] <= 8
            assert set(c["parquets_vs_08_28"].values()) == {"EQUAL"}
            assert c["r_cells_vs_08_28_golds"] == {f"P1_fnfix_{f}": "EQUAL", f"P2_fnfix_{f}": "EQUAL"}
            assert c["union_build_report_vs_08_28"] in ("EQUAL_MODULO_PATHS", "EQUAL_MODULO_PATHS_AND_H1_ADVISORY")
            assert c["union_build_report_h1_ulp_in_advisory"]["worst_ulp"] <= 8
        if tag == "control":
            for f in FIELDS:
                v = d["fields"][f]["october_vs_frozen_cal2026_10"]
                assert v["all_equal"] is True and v["relationships"] == "BYTE_EQUAL" and v["p2_becoming"] == "BYTE_EQUAL"
                assert v["p1_frame_H1"]["ok"] is True and set(v["parquets"].values()) == {"EQUAL"}
                assert j["fields"][f]["october"]["prodlib"]["prodlib_frame_vs_08_28_staged"] == "BYTE_EQUAL"
        else:
            assert d["products_dir"] and not pathlib.Path(d["products_dir"]).is_relative_to(REPO / "data")
            for f in FIELDS:
                L = j["roster_variant_links"][f]
                assert L["source"] == f"data/raw_verified/incfel/roster_gold_{f}.parquet"
                assert L["variant_sha256"] == _sha(REPO / L["source"])
                assert L["canon_sha256"] == _sha(REPO / f"data/raw_verified/roster_gold_{f}.parquet")
                sp = j["fields"][f]["october"]["inpost"]["spells"]
                assert sp["roster_sha256"] == L["variant_sha256"], "the in-post spells must come from the variant roster"
                assert j["fields"][f]["october"]["prodlib"]["prodlib_frame_vs_08_28_staged"].startswith("NOT_EQUAL (VARIANT")


@pytest.mark.parametrize("field", FIELDS)
def test_population_change_is_the_roster_substitution_and_nothing_else(field):
    r = _rep()
    P = r["population"][field]
    pin = PIN[field]
    assert P["closed"] is True
    R = P["relationships"]
    assert R["closed"] and (R["relations_canon"], R["relations_variant"]) == pin["relations"]
    assert (R["persons_canon"], R["persons_variant"]) == pin["persons"]
    assert R["removed_by_cause"] == pin["removed_by_cause"] and R["removed"] == sum(pin["removed_by_cause"].values())
    assert R["channel_changed_as_predicted"] == pin["channel_changed"]
    assert R["added"] == 0 and R["persons_added"] == 0
    assert R["events_canon"] == R["events_variant"] == pin["events"]
    assert (P["roster"]["canon"]["persons"], P["roster"]["variant"]["persons"]) == pin["roster_persons"]
    assert P["roster"]["persons_only_in_variant"] == 0
    for key, name in (("p1_rows", "p1_frame"), ("p2_rows", "p2_becoming")):
        X = P[name]
        assert (X["rows_frozen"], X["rows_new"]) == pin[key] and X["closed"] is True
        assert X["removed"]["n_unaccounted"] == 0 and X["added"]["n_unaccounted"] == 0 and X["modified"]["n_unaccounted"] == 0
        assert X["modified"]["worst_ulp"] <= 8
        assert set(X["removed"]) - {"n_unaccounted", "unaccounted_sample"} <= {"person_not_in_variant_roster", "no_variant_spell_at_arrival"}
    assert (P["pairs"]["pairs_frozen"], P["pairs"]["pairs_new"]) == pin["pairs"]
    assert P["pairs"]["closed"] and P["pairs"]["pairs_removed"] == P["pairs"]["pairs_removed_endpoint_dropped"]
    assert P["pairs"]["pairs_added"] == 0 and P["pairs"]["surviving_pair_rows_changed"] == 0
    assert P["slim"]["consistent"] is True


def test_estimation_controls_recompute_equal_to_the_october_golds():
    r = _rep()
    E = r["controls"]["estimation"]
    assert E["all_equal"] is True and set(E["cells"]) == set(CONTROLS)
    for label, gold in CONTROLS.items():
        c = E["cells"][label]
        assert c["status"] == "OK" and c["compare"]["verdict"] == "EQUAL"
        js = REPO / c["json"]
        assert js.is_file() and _sha(js) == c["json_sha256"]
        assert _compare(js, REPO / f"analysis/expected/{gold}.json"), label
    for f in FIELDS:
        assert E["frames"][f"pos_cut_{f}"]["vs_frozen_pos_frame"]["content"] == "EQUAL"
    assert E["frames"]["make_slim_math_stats"]["slim_vs_data_frames"]["content"] == "EQUAL"


def test_every_variant_cell_exists_with_its_label_and_headline():
    r = _rep()
    assert set(r["cells"]) == set(CELLS)
    for label, c in r["cells"].items():
        assert c["status"] == "OK", label
        js = REPO / c["json"]
        assert js.is_file() and _sha(js) == c["json_sha256"]
        j = json.loads(js.read_text(encoding="utf-8"))
        assert j["label"] == label
        h = c["headline"]
        if "channels" in h:                                   # P1: three channels, all OK
            assert set(h["channels"]) == {"union", "network", "dept"}
            for ch, v in h["channels"].items():
                assert v["status"] == "OK" and v["ate"] == j["channels"][ch]["ate"], (label, ch)
        elif "pair_cluster" in h:                             # P3 pos: both clusterings carry an ATE
            assert h["pair_cluster"]["ate"] == j["pair_cluster"]["ate"] and h["event_cluster"]["ate"] == j["event_cluster"]["ate"]
        else:
            assert h["ate"] == j["ate"] and h["se"] == j["se"]
        assert c["frame_sha256"] in json.dumps(r["variant_frames_sha256"]) or "afar" in c["frame"], label
    # the variant frames the cells were estimated on are the products the variant driver run froze
    for f in FIELDS:
        vf = r["variant_frames_sha256"][f]
        for name in (f"p1_frame_{f}.csv", f"p2_becoming_{f}.csv", f"pairs_none_{f}.parquet", f"p3_slim_{f}.parquet"):
            assert name in vf
        man = (NC / f"variant_frames_{f}" / "products_MANIFEST.sha256").read_text(encoding="utf-8")
        for name, h in vf.items():
            if name != "MANIFEST.sha256":
                assert f"{h}  {name}" in man, name


def test_not_run_record_replaced_and_manifest_pins_every_product():
    assert not (NC / "NOT_RUN.md").exists()
    assert _rep().get("replaced", "").startswith("NOT_RUN.md")
    lines = (NC / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines()
    man = {ln.split("  ", 1)[1]: ln.split("  ", 1)[0] for ln in lines if "  " in ln}
    files = {p.relative_to(REPO).as_posix() for p in NC.rglob("*")
             if p.is_file() and p.name not in ("MANIFEST.sha256", ".DS_Store")}
    assert set(man) == files, sorted(set(man) ^ files)[:10]
    for relp, h in man.items():
        assert _sha(REPO / relp) == h, relp


def test_driver_default_behaviour_and_launcher_are_unchanged_in_shape():
    src = DRIVER.read_text(encoding="utf-8")
    assert 'ap.add_argument("--roster-variant", default="fnfix"' in src
    assert 'ROSTER_VARIANTS = ("fnfix", "incfel")' in src
    assert "runpy" not in src
    # the variant re-points the OCTOBER shadow only, after build_shadow's own sha assertion on the canon link
    assert "sh_oct.link_frozen(rel_r, src)" in src and "sh_ctl.link_frozen(rel_r" not in src
    # the control chain's references follow the 08-28 canon after the promotion
    assert 'EXPECTED08 = CAL08 / "estimates"' in src
    lsrc = LAUNCHER.read_text(encoding="utf-8")
    assert '"--roster-variant", "incfel", "--products-dir"' in lsrc and 'os.environ.setdefault("SAR_R_CAP", "3")' in lsrc
