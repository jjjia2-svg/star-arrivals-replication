"""Piece B of the October caliber (pipeline/frames/cal2026-10/econ_gold/): economics through the
chemistry/mathematics gold chain. Added at review (2026-09-22) — the piece shipped without tests.

What is pinned here:
  * the three `_econ` clones differ from their sha-pinned originals by an exact whitelist of
    wiring lines (the `--field` choice list, the U2 person map, the field's own signed-star
    table) and a header comment block — nothing else, so no computation line can drift;
  * the event-id bijection (star:year <-> star:school) on the 2026-08-28 economics table and
    its refusal of a star with two events;
  * the shape adapters round-trip byte for byte on a synthetic frame, drop out-of-table and
    out-of-pool rows with per-event / per-person accounting, and refuse quoted lines;
  * the pool filter on the real inputs reproduces the verified-pool build's 162 exclusions
    (data-disk + legacy tree; skipped elsewhere);
  * the launcher refuses `--cal` (not implemented; and never without a CHAIN_PROVEN control),
    is declared in LAUNCHERS, and every file beside it is declared NOT_RUNNABLE in run_frames;
  * the frozen control report, when present, is internally consistent (a NOT_EQUAL verdict
    carries its stop, R0 passed, the pool check passed, the frames are not byte-equal).
The data-disk control itself (R cells, three stages) is run_econ_gold.py --control, not pytest.
"""
from __future__ import annotations

import csv
import difflib
import hashlib
import json
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
LAYER = REPO / "pipeline" / "frames" / "cal2026-10" / "econ_gold"
RV = REPO / "data" / "raw_verified"
VP = REPO / "data" / "robustness_2026-09-13_verified_pool"
PRODUCTS = REPO / "data" / "cal2026-10" / "econ_gold_control"
sys.path.insert(0, str(LAYER))
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))
import econ_gold_stage as eg                                            # noqa: E402

CLONE_HEADER_LINES = 10          # the `# cal2026-10 econ_gold clone …` block after the shebang

#: clone -> (pinned original, exact non-header diff: removed lines, added lines)
CLONES = {
    "10_build_union_frame_gold_econ.py": (
        "pipeline/frames/multidisc_gold_2026-08-10/code/10_build_union_frame_gold.py",
        ['ap.add_argument("--field", required=True, choices=["chemistry", "math_stats"])',
         'for f_ in ("chemistry", "math_stats"):'],
        ['ap.add_argument("--field", required=True, choices=["chemistry", "math_stats", "econ"])',
         'if FIELD == "econ":   # cal2026-10 econ_gold wiring (see header): U2 person map; econ\'s own signed-star table',
         '    PMAP = str(_sar_derived_root() / "u2_person_map_11school_2026-07-16/person_map/data.parquet")',
         '    SIGNED_FIELDS = ("econ",)',
         'else:',
         '    SIGNED_FIELDS = ("chemistry", "math_stats")',
         'for f_ in SIGNED_FIELDS:']),
    "20_rebuild_y_gold_econ.py": (
        "pipeline/frames/multidisc_gold_2026-08-10/code/20_rebuild_y_gold.py",
        ['ap.add_argument("--field", required=True, choices=["chemistry", "math_stats"])',
         'for f_ in ("chemistry", "math_stats"):'],
        ['ap.add_argument("--field", required=True, choices=["chemistry", "math_stats", "econ"])',
         'if FIELD == "econ":   # cal2026-10 econ_gold wiring (see header): U2 person map; econ\'s own signed-star table',
         '    PMAP = str(_sar_derived_root() / "u2_person_map_11school_2026-07-16/person_map/data.parquet")',
         '    SIGNED_FIELDS = ("econ",)',
         'else:',
         '    SIGNED_FIELDS = ("chemistry", "math_stats")',
         'for f_ in SIGNED_FIELDS:']),
    "30_build_panels23_gold_econ.py": (
        "pipeline/frames/multidisc_gold_2026-08-10/code/30_build_panels23_gold.py",
        ['ap.add_argument("--field", required=True, choices=["chemistry", "math_stats"])'],
        ['ap.add_argument("--field", required=True, choices=["chemistry", "math_stats", "econ"])',
         'if FIELD == "econ":   # cal2026-10 econ_gold wiring (see header): U2 person map (set after PMAP below)',
         '    _ECON_PMAP = str(_sar_derived_root() / "u2_person_map_11school_2026-07-16/person_map/data.parquet")',
         'if FIELD == "econ":',
         '    PMAP = _ECON_PMAP   # cal2026-10 econ_gold wiring']),
}


def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _manifest() -> dict[str, str]:
    out = {}
    for line in (REPO / "tests" / "pipeline_ported.sha256").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            sha, rel = line.split("  ", 1)
            out[rel] = sha
    return out


# ---------------------------------------------------------------------------------------------
# the clones
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("clone", sorted(CLONES))
def test_clone_differs_from_its_pinned_original_by_the_wiring_whitelist_only(clone):
    orig_rel, removed, added = CLONES[clone]
    orig = REPO / orig_rel
    assert _sha(orig) == _manifest()[orig_rel], f"{orig_rel} no longer matches its pin"
    o = orig.read_text(encoding="utf-8").splitlines()
    c = (LAYER / clone).read_text(encoding="utf-8").splitlines()
    assert o[0] == c[0] == "#!/usr/bin/env python3"
    header = c[1:1 + CLONE_HEADER_LINES]
    assert all(ln.startswith("# ") for ln in header) and "verbatim pin" in header[1], header
    assert _manifest()[orig_rel] in header[1], "the header must name the original's pinned sha"
    body = c[1 + CLONE_HEADER_LINES:]
    diff = [ln for ln in difflib.unified_diff(o[1:], body, n=0, lineterm="")
            if not ln.startswith(("---", "+++", "@@"))]
    got_removed = [ln[1:] for ln in diff if ln.startswith("-")]
    got_added = [ln[1:] for ln in diff if ln.startswith("+")]
    assert got_removed == removed, got_removed
    assert got_added == added, got_added


def test_diff_md_names_every_clone_and_pin():
    text = (LAYER / "DIFF.md").read_text(encoding="utf-8")
    for clone, (orig_rel, _, _) in CLONES.items():
        assert clone in text and orig_rel in text and _manifest()[orig_rel] in text, clone


# ---------------------------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------------------------

def test_event_map_is_a_bijection_on_the_0828_economics_table():
    ev = eg.EventMap(RV / "events_econ_cal2026-08-28.csv")
    assert len(ev.rows) == 116 and len(ev.gold_ids) == len(ev.econ_ids) == 116
    for e in ev.econ_ids:
        assert ev.to_econ(ev.to_gold(e)) == e
    ledger = list(csv.DictReader(ev.gold_ledger().decode("utf-8").splitlines()))
    assert list(ledger[0]) == ["field", "school", "author_id", "display_name", "arrival_corrected",
                               "evidence_grade", "evidence_url", "signature"]
    assert {r["field"] for r in ledger} == {"econ"}
    base = list(csv.DictReader(ev.gold_base().decode("utf-8").splitlines()))
    assert {r["event_id"] for r in base} == ev.gold_ids
    assert {(r["author_id"], int(r["arrival_corrected"])) for r in ledger} == \
        {(s, y) for s, (_, y) in ev.by_star.items()}
    assert len(ev.stars()) == 116


def _events(tmp: pathlib.Path, rows) -> pathlib.Path:
    p = tmp / "events.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["event_id", "star_id", "school", "arrival_year"])
        for star, school, year in rows:
            w.writerow([f"{star}:{year}", star, school, year])
    return p


def test_event_map_refuses_a_star_with_two_events(tmp_path):
    with pytest.raises(AssertionError, match="two events"):
        eg.EventMap(_events(tmp_path, [("A1", "monash", 2005), ("A1", "uq", 2010)]))


# ---------------------------------------------------------------------------------------------
# adapters
# ---------------------------------------------------------------------------------------------

def _line(pid, year, star, ev, extra="True,True,,0.5,False,3.0,1.25,2,1.0,1,0.8,0.7"):
    return f"{pid},{year},{star},{ev},{extra}"


def test_adapt_network_frame_filters_and_preserves_bytes(tmp_path):
    ev = eg.EventMap(_events(tmp_path, [("S1", "monash", 2005), ("S2", "uq", 2010)]))
    lines = [",".join(eg.FRAME_COLS),
             _line("P_A1", 2004, "P_S1", "S1:2005"),
             _line("P_A2", 2004, "P_S1", "S1:2005"),          # A2 not in pool
             _line("P_A1", 2009, "P_S2", "S2:2010"),
             _line("P_A3", 2000, "P_S9", "S9:2001"),          # event not in table
             _line("P_A1", 2005, "P_S1", "S1:2005", "True,True,0.1,0.55,True,-2.0,,0,,0,,")]
    src = tmp_path / "net.csv"
    src.write_bytes(("\n".join(lines) + "\n").encode())
    blob, st = eg.adapt_network_frame(src, ev, {"P_A1"})
    out = blob.decode().splitlines()
    assert out[0] == lines[0]
    assert out[1:] == [_line("A1", 2004, "S1", "S1:monash"), _line("A1", 2009, "S2", "S2:uq"),
                       _line("A1", 2005, "S1", "S1:monash", "True,True,0.1,0.55,True,-2.0,,0,,0,,")]
    assert st == {"rows_in": 5, "rows_kept": 3, "rows_dropped_event_not_in_table": 1,
                  "events_dropped": {"S9:2001": 1}, "rows_dropped_not_in_pool": 1,
                  "persons_dropped_not_in_pool": ["P_A2"], "persons_kept": 1}
    # no pool -> only the table filter
    _, st2 = eg.adapt_network_frame(src, ev, None)
    assert st2["rows_kept"] == 4 and st2["persons_dropped_not_in_pool"] == []


def test_adapt_network_frame_refuses_quoted_lines_and_cr(tmp_path):
    ev = eg.EventMap(_events(tmp_path, [("S1", "monash", 2005)]))
    src = tmp_path / "q.csv"
    src.write_bytes((",".join(eg.FRAME_COLS) + "\n" + _line('"P_A1"', 2004, "P_S1", "S1:2005") + "\n").encode())
    with pytest.raises(AssertionError):
        eg.adapt_network_frame(src, ev, None)
    src.write_bytes((",".join(eg.FRAME_COLS) + "\r\n").encode())
    with pytest.raises(AssertionError, match="CR"):
        eg.adapt_network_frame(src, ev, None)


def test_restore_p1_and_p2_are_the_exact_inverse(tmp_path):
    ev = eg.EventMap(_events(tmp_path, [("S1", "monash", 2005), ("S2", "uq", 2010)]))
    hdr = ",".join(eg.FRAME_COLS + ["channel"])
    gold = tmp_path / "gold.csv"
    gold.write_bytes(("\n".join([
        hdr,
        _line("A1", 2004, "S1", "S1:monash") + ",network",
        _line("A1", 2009, "S2", "S2:uq") + ",both",
        # dept-only block, written by the union builder in GOLD event order (S1:monash < S2:uq)
        _line("A7", 2004, "S1", "S1:monash") + ",dept_only",
        _line("A7", 2009, "S2", "S2:uq") + ",dept_only",
        _line("A7", 2003, "S1", "S1:monash") + ",dept_only",
    ]) + "\n").encode())
    out = eg.restore_p1(gold, ev, 2).decode().splitlines()
    assert out[0] == hdr
    assert out[1:3] == [_line("P_A1", 2004, "P_S1", "S1:2005") + ",network",
                        _line("P_A1", 2009, "P_S2", "S2:2010") + ",both"]
    # tail re-sorted by (pid, econ event id, year)
    assert out[3:] == [_line("P_A7", 2003, "P_S1", "S1:2005") + ",dept_only",
                       _line("P_A7", 2004, "P_S1", "S1:2005") + ",dept_only",
                       _line("P_A7", 2009, "P_S2", "S2:2010") + ",dept_only"]
    with pytest.raises(AssertionError, match="network block"):
        eg.restore_p1(gold, ev, 3)
    p2 = tmp_path / "becoming.csv"
    p2.write_bytes(("\n".join([",".join(eg.P2_COLS),
                               "A7,S2,S2:uq,dept_only,2009,-1,0,0",
                               "A7,S1,S1:monash,network,2004,-1,0,0",
                               "A7,S1,S1:monash,network,2003,-2,0,0"]) + "\n").encode())
    assert eg.restore_p2(p2, ev).decode().splitlines()[1:] == [
        "A7,S1,S1:2005,network,2003,-2,0,0", "A7,S1,S1:2005,network,2004,-1,0,0",
        "A7,S2,S2:2010,dept_only,2009,-1,0,0"]


def test_supplement_patch_is_reshaped_to_the_netbase_schema(tmp_path):
    a = tmp_path / "a.jsonl"
    a.write_text(json.dumps({"work_id": "W1", "publication_year": 2001, "type": "article",
                             "seed_author": "A1", "authors": ["A1", "A2"]}) + "\n\n")
    patch = tmp_path / "patch.jsonl"
    patch.write_text(json.dumps({"author_id": "A9", "work_id": "W9", "publication_year": 2010,
                                 "fwci": 1.0, "author_ids": ["A9"]}) + "\n")
    blob, st = eg.supplement_jsonl([a], patch)
    rows = [json.loads(ln) for ln in blob.decode().splitlines()]
    assert rows[0]["work_id"] == "W1"
    assert rows[1] == {"work_id": "W9", "publication_year": 2010, "type": None,
                       "seed_author": "A9", "authors": ["A9"]}
    assert st == {"a.jsonl": 1, "patch.jsonl (reshaped)": 1}


# ---------------------------------------------------------------------------------------------
# the pool filter on the real inputs (positive control of the D4 rule)
# ---------------------------------------------------------------------------------------------

def test_pool_filter_reproduces_the_verified_pool_exclusions_on_the_real_inputs():
    from pipeline.lib.paths import PathUnresolved, derived_root
    try:
        pmap = derived_root() / "u2_person_map_11school_2026-07-16/person_map/data.parquet"
        net = eg.fs.real_v2() / "econ_fnfix_2026-08-15/data/network_frame_fnfix.csv"
    except PathUnresolved as exc:
        pytest.skip(str(exc))
    if not (pmap.is_file() and net.is_file()):
        pytest.skip("data disk / legacy tree not present")
    pool, st = eg.pool_ids(RV / "roster_econ_verified.parquet", pmap)
    assert st["roster_authors"] == 920
    ev = eg.EventMap(RV / "events_econ_cal2026-08-28.csv")
    _, s = eg.adapt_network_frame(net, ev, pool)
    excluded = sorted(r["person_id"] for r in csv.DictReader(open(VP / "excluded_persons.csv")))
    assert len(excluded) == 162 and s["persons_dropped_not_in_pool"] == excluded
    assert s["events_dropped"] == {"A5044432173:2006": 704}      # the only non-table event


# ---------------------------------------------------------------------------------------------
# the launcher
# ---------------------------------------------------------------------------------------------

def _launcher():
    from pipeline.lib.paths import PathUnresolved
    try:
        import run_econ_gold as reg                                     # noqa: PLC0415
    except PathUnresolved as exc:
        pytest.skip(f"launcher needs the data root at import: {exc}")
    return reg


def test_launcher_is_declared_and_every_sibling_is_declared_not_runnable():
    from pipeline.lib.paths import LAUNCHERS
    assert "pipeline/frames/cal2026-10/econ_gold/run_econ_gold.py" in LAUNCHERS
    reg = _launcher()
    nr = reg._run_frames_module().NOT_RUNNABLE
    for py in sorted(LAYER.glob("*.py")):
        assert f"cal2026-10/econ_gold/{py.name}" in nr, py.name
    src = (LAYER / "run_econ_gold.py").read_text(encoding="utf-8")
    assert src.count("runpy.run_path(") == src.count("with staged_run(") == 1


def test_cal_is_refused_without_a_proven_control_and_is_not_implemented(tmp_path, monkeypatch):
    reg = _launcher()
    from pipeline.lib.paths import OUT_ROOT_ENV, PathUnresolved
    monkeypatch.setattr(reg, "PRODUCTS", tmp_path / "products")
    root = tmp_path / "out"
    root.mkdir()
    monkeypatch.setenv(OUT_ROOT_ENV, str(root))
    assert reg.main(["--control"]) == 2                                   # --execute missing
    assert reg.main([]) == 2
    with pytest.raises(PathUnresolved, match="refused: the control verdict is ABSENT"):
        reg.main(["--cal", "--execute"])
    (tmp_path / "products").mkdir()
    (tmp_path / "products" / "control_report.json").write_text(json.dumps({"verdict": "NOT_EQUAL"}))
    with pytest.raises(PathUnresolved, match="refused: the control verdict is NOT_EQUAL"):
        reg.main(["--cal", "--execute"])
    (tmp_path / "products" / "control_report.json").write_text(json.dumps({"verdict": "CHAIN_PROVEN"}))
    with pytest.raises(PathUnresolved, match="not enabled"):
        reg.main(["--cal", "--execute"])
    (root / "x").write_text("")
    with pytest.raises(PathUnresolved, match="empty absolute"):
        reg.main(["--control", "--execute"])


def test_no_absolute_path_outside_config():
    for f in sorted(LAYER.iterdir()):
        if f.suffix in (".py", ".md"):
            t = f.read_text(encoding="utf-8")
            assert "/Users/" not in t and "/Volumes/" not in t, f.name


# ---------------------------------------------------------------------------------------------
# the frozen control report
# ---------------------------------------------------------------------------------------------

def test_frozen_control_report_is_internally_consistent():
    rep = PRODUCTS / "control_report.json"
    if not rep.is_file():
        pytest.skip("control not run on this checkout")
    r = json.loads(rep.read_text(encoding="utf-8"))
    assert r["verdict"] in ("CHAIN_PROVEN", "NOT_EQUAL")
    assert (r["verdict"] == "NOT_EQUAL") == bool(r["stops"])
    assert r["R0_estimator_positive_control"]["P1ver_econ"] == "EQUAL"
    assert r["R0_estimator_positive_control"]["P2ver_econ"] == "EQUAL"
    assert r["pool_check"]["equal_sets"] is True
    assert r["pool_check"]["persons_dropped_by_pool_filter"] == 162
    eq = r["products"]["frame_bytes_equal_to_verified"]
    if not (eq["p1"] and eq["p2"]):
        assert r["verdict"] == "NOT_EQUAL"
    e = r["E_estimates"]
    assert (e["P1ver_econ"] == "EQUAL" and e["P2ver_econ"] == "EQUAL") == (r["verdict"] == "CHAIN_PROVEN")
    acc = json.loads((PRODUCTS / "accounting_P1.json").read_text(encoding="utf-8"))
    assert acc["rows_new"] == acc["identical"] + acc["modified"] + acc["added_rows"]
    assert acc["rows_frozen"] == acc["identical"] + acc["modified"] + acc["removed_rows"]
    assert r["accounting"]["P1"]["rows_new"] == acc["rows_new"]
