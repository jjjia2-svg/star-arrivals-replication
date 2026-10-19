"""The October caliber's chemistry / math_stats frames (pipeline/frames/cal2026-10/
run_cal_frames_chemmath.py, run 2026-09-23): the frozen products under data/cal2026-10/frames_<field>/
are what their build reports say they are, and the D2 class of every relation is recomputed here by
an INDEPENDENT route — SQL over the frozen 08-28 relationships, the roster parquet and the October
event table (arrival from the table, not from the frame's `post` column the stage reads) — and must
equal the frozen October relationship set exactly. No data disk, no launcher run (< 3 s)."""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import sys

import duckdb
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
CAL10 = REPO / "data" / "cal2026-10"
CAL08 = REPO / "data" / "cal2026-08-28"
FRAMES08 = CAL08 / "frames"
LAUNCHER = "pipeline/frames/cal2026-10/run_cal_frames_chemmath.py"
FIELDS = ("chemistry", "math_stats")
PRODUCTS = ("p1_frame_{f}.csv", "p2_becoming_{f}.csv", "pairs_none_{f}.parquet",
            "relationships_{f}.csv", "union_build_report_{f}.json",
            "p3_slim_{f}.parquet", "p3_slim_ev_{f}.parquet")
sys.path.insert(0, str(REPO / "pipeline" / "stars" / "caliber_2026-08-28"))
import frames_stage as fs08                                              # noqa: E402


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def report(field: str) -> dict:
    return json.loads((CAL10 / f"frames_{field}" / f"build_report_{field}.json").read_text("utf-8"))


def test_launcher_is_declared_and_runs_nothing_unstaged():
    from pipeline.lib.paths import LAUNCHERS
    assert LAUNCHER in LAUNCHERS
    src = (REPO / LAUNCHER).read_text(encoding="utf-8")
    assert "runpy" not in src                       # prodlib runs through stage.run_prodlib's mark
    assert "with staged_run(" in (REPO / "pipeline/frames/cal2026-10/stage.py").read_text("utf-8")
    assert "50_leftbehind_build" not in src and "afar" not in src.split("What the October", 1)[1].split("Phases")[0]


@pytest.mark.parametrize("field", FIELDS)
def test_frozen_directory_matches_its_manifest_and_its_build_report(field):
    d = CAL10 / f"frames_{field}"
    lines = (d / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines()
    man = {ln.split("  ")[1]: ln.split("  ")[0] for ln in lines}
    on_disk = {f"data/cal2026-10/frames_{field}/{p.name}" for p in d.iterdir()
               if p.is_file() and p.name != "MANIFEST.sha256"}
    assert set(man) == on_disk
    for rel, s in man.items():
        assert sha(REPO / rel) == s, rel
    rep = report(field)          # written before the manifest, so it carries no `frozen` block
    assert rep["stops"] == [] if "stops" in rep else True
    # the seven products are the October chain's outputs, byte for byte
    for name in PRODUCTS:
        n = name.format(f=field)
        assert sha(d / n) == rep["october"]["products_sha256"][n], n


@pytest.mark.parametrize("field", FIELDS)
def test_controls_reproduced_the_08_28_freeze_and_the_accounting_closed(field):
    rep = report(field)
    c = rep["control"]
    sm = json.loads((FRAMES08 / "staging_manifest_2026-08-28.json").read_text("utf-8"))
    staged = {e["origin"].split()[-1]: e["sha256"] for e in sm["entries"]
              if e["origin"].startswith("cal-stage:prodlib ")}
    for tag in ("control", "october"):
        p = rep[tag]["prodlib"]
        assert p["config_equal_to_08_28_prodlib_config"] is True
        assert p["prodlib_frame_vs_08_28_staged"] == "BYTE_EQUAL"
        assert p["prodlib_frame_sha256"] == staged[field]
    cmp = c["compare"]
    assert cmp["relationships"] == "BYTE_EQUAL" and cmp["p2_becoming"] == "BYTE_EQUAL"
    assert cmp["union_build_report"]["equal_modulo_paths"] is True
    assert cmp["p1_frame"]["ok"] and cmp["p1_frame"]["worst_ulp"] <= 8 \
        and cmp["p1_frame"]["unexpected_columns"] == []
    for n in ("pairs_none", "p3_slim", "p3_slim_ev"):
        assert cmp[f"{n}_{field}.parquet"]["content"] == "EQUAL"
    assert {(r["cell"], r["status"], r["vs_expected"]) for r in c["r_cells"]} == \
        {(f"P1_fnfix_{field}", "OK", "EQUAL"), (f"P2_fnfix_{field}", "OK", "EQUAL")}
    X = rep["accounting"]
    assert X["prodlib_frame"]["closed"] and X["union_frame_vs_control"]["closed"]
    assert X["relationships"]["closed"] and X["p1_frame"]["closed"] and X["p2_becoming"]["closed"]
    assert X["pairs"]["closed"] and X["slim"]["consistent"]
    for k in ("union_frame_vs_control", "p1_frame", "p2_becoming"):
        assert X[k]["removed"]["dropped_no_spell"] == 0          # D4: the pool IS the roster
        assert X[k]["modified"]["worst_ulp"] <= 8
    assert X["filter"]["relations_by_class"]["dropped_no_spell"] == 0


def _sql_classes(field: str) -> dict[tuple[str, str], str]:
    """Every frozen 08-28 relation's D2 class from the roster + the October event table (channel
    'network' only; roster-channel relations are the union builder's own school-matched join)."""
    con = duckdb.connect()
    ev = CAL10 / f"events_{field}_cal2026-10.csv"
    rows = con.execute(f"""
        WITH rel AS (SELECT pid, event_id, channel FROM read_csv_auto('{FRAMES08 / f"relationships_{field}.csv"}', all_varchar=true)),
             ev AS (SELECT author_id || ':' || school AS event_id, CAST(arrival_corrected AS INT) AS arrival
                    FROM read_csv_auto('{ev}', all_varchar=true)),
             ro AS (SELECT author_id, year_start, year_end
                    FROM read_parquet('{REPO / "data/raw_verified" / f"roster_gold_{field}.parquet"}'))
        SELECT r.pid, r.event_id, r.channel,
               EXISTS (SELECT 1 FROM ro WHERE ro.author_id = r.pid
                       AND ro.year_start <= e.arrival AND e.arrival <= ro.year_end),
               EXISTS (SELECT 1 FROM ro WHERE ro.author_id = r.pid)
        FROM rel r JOIN ev e USING (event_id)""").fetchall()
    n_rel = con.execute(f"SELECT count(*) FROM read_csv_auto('{FRAMES08 / f'relationships_{field}.csv'}')").fetchone()[0]
    assert len(rows) == n_rel, "every frozen relation joins an October event"
    out = {}
    for pid, e, ch, inpost, has in rows:
        if ch != "network":
            assert inpost, (pid, e, ch)         # a roster-channel person is in post at a department
            continue
        out[(pid, e)] = "kept" if inpost else ("dropped_not_in_post" if has else "dropped_no_spell")
    return out


@pytest.mark.parametrize("field", FIELDS)
def test_d2_classes_recomputed_by_sql_equal_the_frozen_october_relationships(field):
    cls = _sql_classes(field)
    with open(CAL10 / f"frames_{field}" / f"inpost_relations_{field}.csv", newline="") as f:
        stage_cls = {(r["pid"], r["event_id"]): r["class"] for r in csv.DictReader(f)}
    # the stage's own class file lists every prodlib relation (network + both); relation by relation
    assert {k: v for k, v in stage_cls.items() if k in cls} == cls
    with open(FRAMES08 / f"relationships_{field}.csv", newline="") as f:
        both = {(r["pid"], r["event_id"]) for r in csv.DictReader(f) if r["channel"] == "both"}
    assert set(stage_cls) == set(cls) | both
    assert all(stage_cls[k] == "kept" for k in both)          # a `both` relation can never drop
    with open(FRAMES08 / f"relationships_{field}.csv", newline="") as f:
        frozen = {(r["pid"], r["event_id"]): r["channel"] for r in csv.DictReader(f)}
    with open(CAL10 / f"frames_{field}" / f"relationships_{field}.csv", newline="") as f:
        octo = {(r["pid"], r["event_id"]): r["channel"] for r in csv.DictReader(f)}
    expect = {k: ch for k, ch in frozen.items() if ch != "network" or cls[k] == "kept"}
    assert octo == expect
    rep = report(field)["accounting"]["relationships"]
    assert rep["removed_by_channel"] == {"network": sum(1 for v in cls.values() if v != "kept")}
    assert rep["by_channel_new"]["both"] == rep["by_channel_frozen"]["both"]
    assert rep["by_channel_new"]["dept_only"] == rep["by_channel_frozen"]["dept_only"]


@pytest.mark.parametrize("field", FIELDS)
def test_october_p1_frame_is_exactly_the_surviving_relations_times_eleven(field):
    d = CAL10 / f"frames_{field}"
    assert (CAL10 / f"events_{field}_cal2026-10.csv").read_bytes() == \
        (CAL08 / f"events_{field}_cal.csv").read_bytes()
    hdr, rows = fs08.read_frame_rows(d / f"p1_frame_{field}.csv")
    ip, ie, ic = hdr.index("incumbent_person_id"), hdr.index("event_id"), hdr.index("channel")
    with open(d / f"relationships_{field}.csv", newline="") as f:
        rel = {(r["pid"], r["event_id"]): r["channel"] for r in csv.DictReader(f)}
    keys = {(r[ip], r[ie]) for r in rows}
    assert keys == set(rel) and len(rows) == 11 * len(rel)
    assert {(r[ip], r[ie], r[ic]) for r in rows} == {(p, e, ch) for (p, e), ch in rel.items()}
    n_events = {"chemistry": 38, "math_stats": 33}[field]
    assert len({e for _, e in rel}) == n_events
    hdr2, rows2 = fs08.read_frame_rows(d / f"p2_becoming_{field}.csv")
    ip2, ie2 = hdr2.index("pid"), hdr2.index("event_id")
    assert {(r[ip2], r[ie2]) for r in rows2} <= set(rel)        # no becoming row for a dropped relation
    assert len({r[ie2] for r in rows2}) == n_events


# ---------------------------------------------------------------------------------------------
# EC2: the recorded 08-28 prodlib configs carry the Mac roots of config/paths.yaml
# ---------------------------------------------------------------------------------------------

def _driver():
    import importlib.util                                                # noqa: PLC0415
    spec = importlib.util.spec_from_file_location("run_cal_frames_chemmath", REPO / LAUNCHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_recorded_mac_roots_are_rebased_onto_the_configured_roots(monkeypatch):
    d = _driver()
    mac = {"ssd_root": pathlib.Path("/mnt/macdisk/openalex_pipeline"),
           "legacy_v2_output": pathlib.Path("/home/x/thesis/v2_output"),
           "legacy_thesis": pathlib.Path("/home/x/thesis")}
    aws = {"ssd_root": pathlib.Path("/data/openalex_pipeline"),
           "legacy_v2_output": pathlib.Path("/data/legacy/thesis/v2_output"),
           "legacy_thesis": pathlib.Path("/data/legacy/thesis")}
    monkeypatch.setattr(d, "load_paths", lambda p=None: mac if p is not None else aws)
    ref = {"snapshot": {"edges_glob": "/mnt/macdisk/openalex_pipeline/derived/e/*.parquet",
                        "fwci_baseline_pop_glob": "/home/x/thesis/v2_output/fwci/*.parquet",
                        "other": "/mnt/macdisk/openalex_pipeline_old/x", "n": 3},
           "events": {"signed_csv": "/work/shadow/a.csv"}, "list": ["/home/x/thesis/z", 1]}
    got, moved = d.rebase_recorded_roots(ref)
    assert got["snapshot"]["edges_glob"] == "/data/openalex_pipeline/derived/e/*.parquet"
    assert got["snapshot"]["fwci_baseline_pop_glob"] == "/data/legacy/thesis/v2_output/fwci/*.parquet"
    assert got["snapshot"]["other"] == ref["snapshot"]["other"]           # not on a path boundary
    assert got["snapshot"]["n"] == 3 and got["events"] == ref["events"]
    assert got["list"] == ["/data/legacy/thesis/z", 1]
    assert sorted(moved) == ["list[0]", "snapshot.edges_glob", "snapshot.fwci_baseline_pop_glob"]
    assert ref["snapshot"]["edges_glob"].startswith("/mnt/macdisk/")         # input left as it was


def test_rebase_is_a_no_op_when_the_configured_roots_are_the_recorded_ones(monkeypatch):
    d = _driver()
    mac = {"ssd_root": pathlib.Path("/mnt/macdisk/openalex_pipeline"),
           "legacy_v2_output": pathlib.Path("/home/x/thesis/v2_output"),
           "legacy_thesis": pathlib.Path("/home/x/thesis")}
    monkeypatch.setattr(d, "load_paths", lambda p=None: mac)
    ref = {"snapshot": {"edges_glob": "/mnt/macdisk/openalex_pipeline/derived/e/*.parquet"}}
    assert d.rebase_recorded_roots(ref) == (ref, [])


# ---------------------------------------------------------------------------------------------
# EC2: the union report's G-VAL fill examples print the OLD frame value as pandas parsed it
# ---------------------------------------------------------------------------------------------

def _report(tmp, fill_old: str, ex_fresh: str, fill_fresh: str = "None") -> pathlib.Path:
    p = tmp / f"r_{len(list(tmp.iterdir()))}.json"
    p.write_text(json.dumps({"run_dir": "/some/run", "G_VAL_advisory": {
        "fill_examples": [["A1", "A2:x", "2014", "fwci_mean_ex_star", "old_val", fill_old, fill_fresh]],
        "examples": [["A1", "A2:x", "2014", "fwci_frac", "1.2843267917633057", ex_fresh]]}}), "utf-8")
    return p


def test_union_report_accepts_a_few_ulp_on_a_fill_example_old_value_and_records_it(tmp_path):
    d = _driver()
    a = _report(tmp_path, "1.929583549499512", "1.0098933333333333")      # EC2 parse of the old frame
    b = _report(tmp_path, "1.9295835494995115", "1.0098933333333333")     # the frozen report (2 ULP)
    r = d.json_equal_modulo_paths(a, b)
    assert r["equal_modulo_paths"] is False and r["equal_modulo_paths_and_h1_advisory"] is True
    assert r["h1_ulp_in_advisory"]["n"] == 1 and r["h1_ulp_in_advisory"]["worst_ulp"] == 2


def test_union_report_still_stops_on_a_large_fill_gap_or_another_field(tmp_path):
    d = _driver()
    base = _report(tmp_path, "1.9295835494995115", "1.0098933333333333")
    far = _report(tmp_path, "1.9295835494996115", "1.0098933333333333")    # far beyond 8 ULP
    assert d.json_equal_modulo_paths(far, base)["equal_modulo_paths_and_h1_advisory"] is False
    fresh = _report(tmp_path, "1.9295835494995115", "1.0098933333333333", fill_fresh="2.0")
    assert d.json_equal_modulo_paths(fresh, base)["equal_modulo_paths_and_h1_advisory"] is False


def test_union_report_accepts_a_few_ulp_on_an_example_old_value_too(tmp_path):
    """j0-04, math_stats control: G_VAL_advisory.examples[i][4] (the OLD frame value, parsed by pandas)
    moved by 2 ULP on EC2; the rule covers both parsed OLD values and FRESH H1 sums, nothing else."""
    d = _driver()
    def rep(old):
        p = tmp_path / f"e_{len(list(tmp_path.iterdir()))}.json"
        p.write_text(json.dumps({"G_VAL_advisory": {"fill_examples": [], "examples": [
            ["A1", "A2:x", "2014", "fwci_mean", old, "1.0098933333333333"]]}}), "utf-8")
        return p
    r = d.json_equal_modulo_paths(rep("1.8465572595596316"), rep("1.8465572595596311"))
    assert r["equal_modulo_paths_and_h1_advisory"] is True and r["h1_ulp_in_advisory"]["worst_ulp"] == 2
    assert d.json_equal_modulo_paths(rep("1.8465572595596316"), rep("1.8465572595590000"))[
        "equal_modulo_paths_and_h1_advisory"] is False
