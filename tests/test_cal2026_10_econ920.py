"""econ920 (pipeline/frames/cal2026-10/econ920/): economics through the CANONICAL econ chain under
the October caliber. What is pinned here:
  * the union-rung clone is the pinned legacy script plus path wiring only: regenerating it from
    the sha-pinned original reproduces the tracked file (legacy tree present) and every removed
    line of DIFF.md carries an absolute machine path or a `dirname(BASE)` output path;
  * the launcher is declared in LAUNCHERS and every sibling .py is declared NOT_RUNNABLE;
  * the row-level machinery on synthetic inputs: event filter + splice, verified-roster filter,
    ledger id correction / event removal, provenance table, the output-side post-filter (drops
    network rows only, reports events left empty), the G-DOSE draw predictor (replicates the
    clone's pandas draw), the frame characterisation verdicts, and the override's evidence gate;
  * the frozen products, when present: MANIFEST, verdicts, the override record, the proof, the
    blocked p1 stage, and the row / relation totals against the files themselves.
The data-disk controls (c1a, gdose, c1b, c2, c3) and the October run are run_econ920.py, not pytest.
"""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
LAYER = REPO / "pipeline" / "frames" / "cal2026-10" / "econ920"
PRODUCTS = REPO / "data" / "cal2026-10" / "frames_econ"
CONTROLS = REPO / "data" / "cal2026-10" / "controls_report_econ920_2026-09-23.json"
sys.path.insert(0, str(LAYER))
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))
import econ920_lib as L                                                  # noqa: E402
import make_clone as mc                                                  # noqa: E402

COLS = L.FRAME_COLS


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _row(pid, ev, year, arrival, dose="0.5", ff="1.0", pc="2"):
    return [pid, str(year), "P_" + ev.split(":")[0], ev, "true", "true" if year >= arrival else "false",
            "", dose, "false", "3.0", ff, pc, ff, pc, "", ""]


def _frame(p: pathlib.Path, rels: list[tuple[str, str, int]], channel: bool = False, crlf=False) -> pathlib.Path:
    eol = "\r\n" if crlf else "\n"
    with open(p, "w", newline="", encoding="utf-8") as f:
        f.write(",".join(COLS + (["channel"] if channel else [])) + eol)
        for pid, ev, arr in rels:
            for y in range(arr - 5, arr + 6):
                cells = _row(pid, ev, y, arr)
                if channel:
                    cells.append("network")
                f.write(",".join(cells) + eol)
    return p


def _parquet(p: pathlib.Path, rows: list[dict]) -> pathlib.Path:
    import pyarrow as pa                                                  # noqa: PLC0415
    import pyarrow.parquet as pq                                          # noqa: PLC0415
    pq.write_table(pa.Table.from_pylist(rows), p)
    return p


# ---------------------------------------------------------------------------------------------
# the clone
# ---------------------------------------------------------------------------------------------

def test_clone_is_the_pinned_original_plus_path_wiring_only():
    src = mc.original_path()
    if not src.is_file():
        pytest.skip("legacy tree not on this machine")
    raw = src.read_bytes()
    assert mc.sha(raw) == mc.ORIGINAL_SHA, "the pinned original changed"
    clone = mc.HEADER.format(sha=mc.ORIGINAL_SHA) + mc.render(raw.decode("utf-8"))
    assert clone == mc.CLONE.read_text(encoding="utf-8"), "tracked clone is stale: run make_clone.py"
    assert mc.diff_md(raw.decode("utf-8"), clone, mc.ORIGINAL_SHA) == mc.DIFF.read_text(encoding="utf-8")


def test_diff_md_removed_lines_are_all_path_hunks():
    text = (LAYER / "DIFF.md").read_text(encoding="utf-8")
    body = text.split("```diff\n", 1)[1]
    removed = [ln[1:] for ln in body.splitlines() if ln.startswith("-") and not ln.startswith("---")]
    added = {ln[1:] for ln in body.splitlines() if ln.startswith("+") and not ln.startswith("+++")}
    # public copy: the comment lines whose process wording make_clone.WORDING_RX rewords show as a -/+
    # pair with equal text (difflib re-emits a neighbouring blank line the same way)
    path_hunks = [ln for ln in removed if ln not in added]
    assert len(path_hunks) == 14 and len(removed) == 17
    for ln in path_hunks:
        # 2026-09-23: DIFF.md renders the original's machine paths as placeholders (make_clone.diff_md)
        assert ("/Users/" in ln or "/Volumes/" in ln or "<legacy_thesis>" in ln or "<ssd_root>/" in ln
                or "os.path.dirname(BASE)" in ln or '{ROOT}/v2_output/' in ln or ln.startswith("ROOT = ") or ln.startswith("BASE = ")
                or ln.strip() in ("", "#!/usr/bin/env python3")), ln
    assert "/Users/" not in mc.CLONE.read_text(encoding="utf-8")
    assert "/Volumes/" not in mc.CLONE.read_text(encoding="utf-8")


def test_launcher_is_declared_and_every_sibling_is_declared_not_runnable():
    from pipeline.lib.paths import LAUNCHERS                              # noqa: PLC0415
    assert "pipeline/frames/cal2026-10/econ920/run_econ920.py" in LAUNCHERS
    import importlib.util                                                 # noqa: PLC0415
    spec = importlib.util.spec_from_file_location("_rf", REPO / "pipeline/frames/run_frames.py")
    rf = importlib.util.module_from_spec(spec)
    sys.modules["_rf"] = rf                       # dataclasses under `from __future__ import annotations`
    spec.loader.exec_module(rf)                                           # type: ignore[union-attr]
    for f in sorted(LAYER.glob("*.py")):
        assert f"cal2026-10/econ920/{f.name}" in rf.NOT_RUNNABLE, f.name


# ---------------------------------------------------------------------------------------------
# the row-level machinery on synthetic inputs
# ---------------------------------------------------------------------------------------------

def test_filter_events_drops_events_regenerates_one_and_preserves_bytes(tmp_path):
    src = _frame(tmp_path / "net.csv", [("P_A1", "S1:2010", 2010), ("P_A2", "S2:2011", 2011),
                                        ("P_A3", "OLD:2009", 2009)], crlf=True)
    block = [",".join(_row("P_A9", "NEW:2009", y, 2009)).encode() for y in range(2004, 2015)]
    rep = L.filter_events(src, keep_events={"S1:2010", "NEW:2009"}, regenerate={"OLD:2009": "NEW:2009"},
                          spliced={"NEW:2009": block}, out=tmp_path / "out.csv")
    assert rep["rows_dropped_event_not_in_set"] == {"S2:2011": {"rows": 11, "persons": 1}}
    assert rep["rows_dropped_regenerated_old_id"] == {"OLD:2009": {"rows": 11, "persons": 1, "new_id": "NEW:2009"}}
    assert rep["rows_spliced"] == {"NEW:2009": 11} and rep["output"]["rows"] == 22
    raw = src.read_bytes().split(b"\n")
    kept = [ln for ln in raw[1:] if ln and ln.split(b",")[3] == b"S1:2010"]
    assert (tmp_path / "out.csv").read_bytes() == b"\n".join([raw[0]] + kept + block) + b"\n"


def test_filter_verified_uses_both_id_forms_and_preserves_bytes(tmp_path):
    roster = _parquet(tmp_path / "roster.parquet", [{"author_id": "A1", "year_start": 2000, "year_end": 2020},
                                                     {"author_id": "A7", "year_start": 2000, "year_end": 2020}])
    pm = _parquet(tmp_path / "pm.parquet", [{"author_id": "A1", "person_id": "P_A1"},
                                            {"author_id": "A7", "person_id": "P_A5"},     # A7 folds to person P_A5
                                            {"author_id": "A5", "person_id": "P_A5"}])
    forms, src = L.verified_forms(roster, pm)
    assert forms == {"P_A1", "P_A7", "P_A5"} and src["roster_authors"] == 2
    frame = _frame(tmp_path / "net.csv", [("P_A1", "S:2010", 2010), ("P_A5", "S:2010", 2010), ("P_A9", "S:2010", 2010)])
    rep = L.filter_verified(frame, forms, tmp_path / "v.csv")
    assert rep["persons_dropped_ids"] == ["P_A9"] and rep["rows_dropped"] == 11 and rep["output"]["rows"] == 22
    raw = frame.read_bytes().split(b"\n")
    assert (tmp_path / "v.csv").read_bytes() == b"\n".join([raw[0]] + [ln for ln in raw[1:] if ln and not ln.startswith(b"P_A9,")]) + b"\n"


def test_ledger_id_correction_and_event_removal_are_line_exact(tmp_path):
    p = tmp_path / "ledger.csv"
    p.write_text("event_id,star_id,school,arrival_year,x\nOLD:2009,OLD,uwa,2009,q\nS1:2010,S1,anu,2010,\"a,b\"\nS2:2011,S2,uq,2011,\n",
                 encoding="utf-8")
    corr = {"events": {"OLD:2009": "NEW:2009"}, "stars": {"OLD": "NEW"}}
    blob, rec = L.correct_id_lines(p, corr)
    assert rec == {"corrected_lines": {"OLD:2009": 1}}
    assert blob.split(b"\n")[1] == b"NEW:2009,NEW,uwa,2009,q" and blob.split(b"\n")[2] == b'S1:2010,S1,anu,2010,"a,b"'
    rec2 = L.drop_events_from_csv(p, {"S2:2011"}, 0, tmp_path / "out.csv")
    assert rec2["removed_lines"] == {"S2:2011": 1} and rec2["lines"] == 3
    assert (tmp_path / "out.csv").read_bytes() == p.read_bytes().replace(b"S2:2011,S2,uq,2011,\n", b"")


def test_provenance_table_appends_one_row_per_regenerated_event():
    age = b"author_id,name,school,arrival,dept_id,evidence_url,verdict_source\nS1,One,anu,2010,I1,u,v\n"
    out = L.provenance_table(age, {"NEW:2009": {"name": "A5091326353", "school": "uwa", "source": "regen"}})
    rows = list(csv.DictReader(out.decode().splitlines()))
    assert [r["author_id"] for r in rows] == ["S1", "NEW"] and rows[1]["arrival"] == "2009"
    assert {f"{r['author_id']}:{int(r['arrival'])}" for r in rows} == {"S1:2010", "NEW:2009"}


def test_postfilter_union_drops_network_rows_only_and_reports_empty_events(tmp_path):
    roster = _parquet(tmp_path / "roster.parquet", [{"author_id": "A1", "year_start": 2008, "year_end": 2012},
                                                     {"author_id": "A2", "year_start": 2015, "year_end": 2020}])
    pm = _parquet(tmp_path / "pm.parquet", [{"author_id": "A1", "person_id": "P_A1"}, {"author_id": "A2", "person_id": "P_A2"}])
    # A1 in post at 2010 (kept); A2 on the roster but not in post in 2010 (b); A9 not on the roster (a);
    # event T:2010 has only A9 -> left with zero relations
    pre = _frame(tmp_path / "pre.csv", [("P_A1", "S:2010", 2010), ("P_A2", "S:2010", 2010),
                                        ("P_A9", "S:2010", 2010), ("P_A9", "T:2010", 2010)], channel=True)
    rel = tmp_path / "rel.csv"
    rel.write_text("pid,event_id,channel\nA1,S:2010,network\nA2,S:2010,network\nA9,S:2010,network\nA9,T:2010,network\n",
                   encoding="utf-8")
    rep = L.postfilter_union(pre, rel, roster, pm, tmp_path / "pf", in_post=True)
    assert rep["a_verified_roster"]["persons_dropped_ids"] == ["P_A9"]
    assert rep["b_in_post"]["relations_by_class"] == {"kept": 1, "dropped_no_spell": 0, "dropped_not_in_post": 1}
    assert rep["dropped_relations"] == 3 and rep["dropped_rows_by_channel"] == {"network": 33}
    assert rep["events_left_with_zero_relations"] == ["T:2010"]
    assert rep["output"]["rows"] == 11 and rep["output"]["relationships_lines"] == 1
    raw = pre.read_bytes().split(b"\n")
    assert pathlib.Path(rep["output"]["pre_y"]).read_bytes() == b"\n".join([raw[0]] + [ln for ln in raw[1:] if ln.startswith(b"P_A1,")]) + b"\n"
    assert pathlib.Path(rep["output"]["relationships"]).read_text() == "pid,event_id,channel\nA1,S:2010,network\n"


def test_postfilter_union_refuses_to_drop_a_roster_channel_row(tmp_path):
    roster = _parquet(tmp_path / "roster.parquet", [{"author_id": "A1", "year_start": 2008, "year_end": 2012}])
    pm = _parquet(tmp_path / "pm.parquet", [{"author_id": "A1", "person_id": "P_A1"}])
    pre = _frame(tmp_path / "pre.csv", [("P_A9", "S:2010", 2010)], channel=True)
    text = pre.read_text().replace(",network", ",dept_only")
    pre.write_text(text)
    rel = tmp_path / "rel.csv"
    rel.write_text("pid,event_id,channel\nA9,S:2010,dept_only\n")
    with pytest.raises(AssertionError):
        L.postfilter_union(pre, rel, roster, pm, tmp_path / "pf", in_post=False)


def test_predict_gdose_draw_replicates_the_clones_pandas_draw(tmp_path):
    import pandas as pd                                                   # noqa: PLC0415
    rels = [(f"P_A{i}", f"S{i % 7}:2010", 2010) for i in range(300)]
    frame = _frame(tmp_path / "net.csv", rels)
    old = pd.read_csv(frame)
    old["pid"] = old.incumbent_person_id.map(lambda x: x.replace("P_", "", 1))
    g = old[["pid", "event_id", "dose_topic"]].drop_duplicates(["pid", "event_id"])
    g = g[~g.event_id.isin({"S0:2010"})].sample(n=200, random_state=42)
    drawn = {(r.pid, r.event_id) for r in g.itertuples()}
    resid = {k: 0.05 for k in list(drawn)[:3]}
    resid[("A_not_drawn", "Z:2000")] = 0.9
    pr = L.predict_gdose_draw(frame, {"S0:2010"}, resid)
    assert pr["drawn"] == 200 and pr["predicted_max_abs_diff"] == 0.05 and pr["predicted_gate"] == "FAIL"
    assert {(a, b) for a, b, _ in pr["drawn_relations_gt_0.01"]} == set(list(drawn)[:3])
    assert L.predict_gdose_draw(frame, {"S0:2010"}, {})["predicted_gate"] == "PASS"


def test_characterise_frame_verdicts(tmp_path):
    a = _frame(tmp_path / "a.csv", [("P_A1", "S:2010", 2010), ("P_A2", "S:2010", 2010)], channel=True)
    assert L.characterise_frame(a, a)["verdict"] == "BYTE_EQUAL"
    b = tmp_path / "b.csv"
    b.write_text(a.read_text().replace("2010,P_S,S:2010,true,true,,0.5,false,3.0,1.0,2,1.0,2,,,network",
                                       "2010,P_S,S:2010,true,true,,0.5,false,3.0,1.0000000000000002,2,1.0,2,,,network", 1))
    r = L.characterise_frame(a, b)
    assert r["verdict"] == "EQUAL_MODULO_Y_SWAPPED_BY_04" and r["rows_modified"] == 1 and r["worst_ulp_by_column"] == {"fwci_frac": 1}
    c = tmp_path / "c.csv"
    c.write_text(a.read_text().replace(",0.5,false,3.0,", ",0.6,false,3.0,", 1))
    assert L.characterise_frame(a, c)["verdict"] == "NOT_EQUAL"
    d = tmp_path / "d.csv"
    d.write_text("\n".join(a.read_text().splitlines()[:-1]) + "\n")
    assert L.characterise_frame(a, d)["verdict"] == "NOT_EQUAL"


def test_override_evidence_gate_requires_every_condition(monkeypatch):
    import importlib.util                                                 # noqa: PLC0415
    spec = importlib.util.spec_from_file_location("_run_econ920", LAYER / "run_econ920.py")
    ru = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ru)                                           # type: ignore[union-attr]
    ru.REPORT.clear()
    ru.REPORT["measurements"] = {"gdose_population": {"n": 10, "share_exact_1e-9": 0.8, "max_abs_diff": 0.1,
                                                      "n_gt_0.01": 2, "n_gt_0.05": 1, "frozen_0813_draw": {}}}
    ru.REPORT["_gdose_residuals"] = {"A1|S:2010": 0.07, "A2|T:2011": 0.02}
    pred = {"predicted_gate": "FAIL", "predicted_max_abs_diff": 0.07, "predicted_share_exact_1e-9": 0.88}
    res = {"gate_overridden": True,
           "report": {"G_DOSE": {"n": 200, "missing_side": 0, "max_abs_diff": 0.07, "share_exact_1e-9": 0.88},
                      "G_ROW": {"mismatches": 0}, "G_SUM": {"ok": True}},
           "drawn_residuals_gt_1e-9": [{"pid": "A1", "event_id": "S:2010", "frozen_dose": 0.5, "recomputed": 0.57, "abs_diff": 0.07}]}
    ok, rec = ru.override_is_justified(pred, res)
    assert ok and all(rec["conditions"].values())
    bad = json.loads(json.dumps(res))
    bad["drawn_residuals_gt_1e-9"][0]["abs_diff"] = 0.071          # not a frozen-population residual
    assert ru.override_is_justified(pred, bad)[0] is False
    bad = json.loads(json.dumps(res)); bad["report"]["G_ROW"]["mismatches"] = 1
    assert ru.override_is_justified(pred, bad)[0] is False
    bad = json.loads(json.dumps(res)); bad["gate_overridden"] = False
    assert ru.override_is_justified(pred, bad)[0] is False
    assert ru.override_is_justified({"predicted_gate": "PASS"}, res)[0] is False


# ---------------------------------------------------------------------------------------------
# the frozen products
# ---------------------------------------------------------------------------------------------

@pytest.mark.skipif(not (PRODUCTS / "MANIFEST.sha256").is_file(), reason="October econ products not frozen here")
def test_frozen_products_match_their_manifest_and_their_build_report():
    man = {ln.split("  ", 1)[1].strip(): ln.split("  ", 1)[0]
           for ln in (PRODUCTS / "MANIFEST.sha256").read_text().splitlines() if ln.strip()}
    files = {f"data/cal2026-10/frames_econ/{p.relative_to(PRODUCTS).as_posix()}"
             for p in PRODUCTS.rglob("*") if p.is_file() and p.name != "MANIFEST.sha256"}
    assert set(man) == files
    for rel, want in man.items():
        assert sha(REPO / rel) == want, rel
    r = json.loads((PRODUCTS / "build_report_econ920_2026-10.json").read_text("utf-8"))
    assert {k: v["verdict"] for k, v in r["controls"].items()} == {c: "CLEAR" for c in ("c1a", "c1b", "c2", "c3")}
    assert r["stops"] == []
    o = r["october"]
    # (review 2026-09-23: the earlier `A and B if C else True` was vacuous when the key was absent)
    assert o["g_row_proof"]["closed"]
    assert o["g_row_proof"]["counts"].get("OTHER_DIFFERENCE", 0) == 0
    assert o["g_row_proof"]["counts"].get("network_row_without_frozen_source", 0) == 0
    assert o["g_row_proof"]["counts"].get("dept_only_rebuilt_changed_BEYOND_Y_SWAPPED", 0) == 0
    for ch in o["g_row_proof"]["dept_only_rebuilt_changed"]:
        assert set(ch["cols"]) <= set(L.Y_SWAPPED_BY_04) and all(v <= 8 for v in ch["ulps"].values())
    # the override: recorded, justified, and marked in the directory
    ov = o["gdose_gate_override"]
    assert all(ov["conditions"].values()) and (PRODUCTS / "DEVIATION_gdose_gate_override_2026-09-23.md").is_file()
    assert {d["where"] for d in r["deviations"]} >= {"october union rung"}
    # since 729788a the p1 stage passes (the 2 roster additions got the API patch supplement):
    # the three p1 frames are frozen, 04's anchor report kept, nothing left un-frozen
    assert o["chain"]["p1_econ"]["status"] == "OK" and o["not_frozen"] == []
    assert o["chain"]["p1_econ"]["g_econ_rebuild"]["PASS"] is True
    for name in ("p1_frame_econ.csv", "p1_frame_econ_old79.csv", "p1_frame_econ_new37.csv", "g_econ_rebuild_econ.json"):
        assert (PRODUCTS / name).is_file(), name
    assert not (PRODUCTS / "_blocked_p1").exists() and not (PRODUCTS / "p1_pre_y_frame_econ.csv").exists()
    assert o["shadow"]["patch_supplement"]["extra_lines"] == 190 and o["shadow"]["patch_supplement"]["frozen_lines"] == 17191
    # the union clone reads the SHADOW's patch (frozen ⧺ supplement), never the legacy path (review
    # fix 2026-09-23). The products frozen by 729788a predate the fix (their clone read the legacy
    # path, which the shadow build had overwritten through a hard link — same bytes, wrong route);
    # a re-freeze after the legacy restoration records the route here.
    if "union_patch_a" in o:
        assert o["union_patch_a"]["lines"] == 17191 + 190 and "shadow" in o["union_patch_a"]["path"]
    # totals against the files themselves
    rel_rows = list(csv.DictReader(open(PRODUCTS / "relationships_econ.csv", encoding="utf-8")))
    assert len(rel_rows) == o["accounting"]["relationships"]["after_post_filter_total"]
    assert sum(v["relations"] for v in o["accounting"]["per_event"].values()) == len(rel_rows)
    p1_rows = (PRODUCTS / "p1_frame_econ.csv").read_bytes().count(b"\n") - 1
    assert p1_rows == o["accounting"]["rows"]["pre_y_frame_rows"] == 11 * len(rel_rows)
    o79 = (PRODUCTS / "p1_frame_econ_old79.csv").read_bytes().count(b"\n") - 1
    n37 = (PRODUCTS / "p1_frame_econ_new37.csv").read_bytes().count(b"\n") - 1
    assert o79 + n37 == p1_rows
    assert (PRODUCTS / "p2_becoming_econ.csv").read_bytes().count(b"\n") - 1 == o["accounting"]["p2_rows"]
    led = list(csv.DictReader(open(PRODUCTS / "p1_events_ledger_econ.csv", encoding="utf-8")))
    ids = {x["event_id"] for x in led}
    assert len(led) == 113 and "A5091326353:2009" in ids and "A5090515599:2009" not in ids
    assert not ({"A5110738002:2009", "A5102739182:2010", "A5041849660:2003", "A5044432173:2006"} & ids)
    assert o["accounting"]["events_with_zero_relations"] == [] and o["postfilter_a_b"]["events_left_with_zero_relations"] == []


@pytest.mark.skipif(not CONTROLS.is_file(), reason="controls report not frozen here")
def test_controls_report_is_internally_consistent():
    c = json.loads(CONTROLS.read_text("utf-8"))
    assert {k: v["verdict"] for k, v in c["controls"].items()} == {k: "CLEAR" for k in ("c1a", "c1b", "c2", "c3")}
    c1a = c["controls"]["c1a"]
    assert c1a["runs"][0]["relationships_byte_equal"] and c1a["frame"]["verdict"] == "EQUAL_MODULO_Y_SWAPPED_BY_04"
    assert c1a["determinism"]["two_runs_byte_equal"] is False           # the original's own non-determinism, proven
    c2 = c["controls"]["c2"]
    assert all(v["verdict"] == "BYTE_EQUAL" for k, v in c2["frames"].items() if k.endswith(".csv"))
    assert c2["frames"]["p3_slim_econ.parquet"]["equal"] and c2["frames"]["p3_slim_ev_econ.parquet"]["equal"]
    assert all(v["verdict"] == "EQUAL" for v in c2["cells"].values()) and set(c2["cells"]) == {
        "P1_econ_fnfix", "P1_econ_fnfix_old79", "P1_econ_fnfix_new37", "P2_econ_fnfix"}
    c3 = c["controls"]["c3"]
    assert c3["exclusion_control_on_frozen_frames"]["equal"] and c3["postfilter_a"]["dropped_persons_equal_the_162"]
    assert all(v["verdict"] == "BYTE_EQUAL" for v in c3["frames"].values())
    assert {k: v["verdict"] for k, v in c3["cells"].items()} == {"P1ver_econ": "EQUAL", "P2ver_econ": "EQUAL"}
    pop = c["measurements"]["gdose_population"]
    assert pop["share_exact_1e-9"] < 0.90 and pop["n_gt_0.01"] > 0     # the gate cannot pass on the whole population


# ---------------------------------------------------------------------------------------------
# c1b on EC2: the ledger stage opens the shadow supplement for append (01_merge_inputs.py:100)
# ---------------------------------------------------------------------------------------------

def test_c1b_shadow_supplement_is_an_own_copy_never_the_read_only_source(tmp_path, monkeypatch):
    """With no extra supplement the shadow must still hold its OWN copy of the frozen supplement:
    the ledger script opens it with mode 'a', which fails on a read-only legacy inode (EC2) and
    would write through a hard link into the legacy file (Mac)."""
    v2 = tmp_path / "v2"
    sup_rel = f"{L.ECON}/data/edges_supplement_fnfix.jsonl"
    for rel, data in {sup_rel: b'{"w": 1}\n{"w": 2}\n',
                      f"{L.ECON}/data/new_events_econ.csv": b"author_id,arrival\nA1,2010\n",
                      L.fs08.ECON_RUN_FRAME: b"h\n1\n",
                      f"{L.ECON}/runs/econ_fnfix/build_report.json": b'{"export": {}}'}.items():
        (v2 / rel).parent.mkdir(parents=True, exist_ok=True)
        (v2 / rel).write_bytes(data)
    src = v2 / sup_rel
    src.chmod(0o444)
    monkeypatch.setattr(L.fs08, "FROZEN_LINKS", (sup_rel,))
    monkeypatch.setattr(L, "CHEMMATH_AFAR_INPUTS", {})
    sh, _ = L.build_econ_shadow(tmp_path / "shadow", v2, removed_new_stars=set(), supplement_extra=None)
    dest = sh.path(sup_rel)
    assert dest.read_bytes() == src.read_bytes()
    assert dest.stat().st_ino != src.stat().st_ino and src.stat().st_nlink == 1
    with open(dest, "a"):
        pass
    assert sh.entries[-1]["rel"] == sup_rel and sh.entries[-1]["sha256"] == sha(src)
