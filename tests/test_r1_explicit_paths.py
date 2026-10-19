"""R1 F3 + F14 (unit W1-OCT-A): the October frames code names every input through the run config
(pipeline.lib.r1_config, section `stage`) or a required flag — no 'auto' event tables, no
choose-by-existence restake / names / roster-added tables, no October product read from the repo
when the chemistry / mathematics driver is given --october-ref — and stage.build_shadow takes the
M stars_excluded list and rosters as keyword-only switches whose None defaults are October.

Everything here runs on toy inputs in tmp_path, except the B0 test, which reads small tracked
files (config/r1/B0.json and October's recorded build reports). With the B0 values every output
is October's; J0 gate 1 is the full proof."""
from __future__ import annotations

import csv
import hashlib
import inspect
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
LAYER = REPO / "pipeline" / "frames" / "cal2026-10"
CAL10 = REPO / "data" / "cal2026-10"
CAL08 = REPO / "data" / "cal2026-08-28"
for p in (str(LAYER / "econ920"), str(LAYER)):
    if p not in sys.path:
        sys.path.insert(0, p)
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))

import stage                                                            # noqa: E402
import econ920_lib as L                                                 # noqa: E402
import run_cal_frames_chemmath as rc                                    # noqa: E402
import run_controls as rctl                                             # noqa: E402

RL = "multidisc_2026-07-24/code/roster_lib.py"


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _csv(p: pathlib.Path, header: list[str], rows: list[list]) -> pathlib.Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return p


def _parquet(p: pathlib.Path, cols: dict, schema=None) -> pathlib.Path:
    import pyarrow as pa                                                # noqa: PLC0415
    import pyarrow.parquet as pq                                        # noqa: PLC0415
    p.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(cols, schema=schema), p)
    return p


def _rows(p: pathlib.Path) -> list[dict]:
    return list(csv.DictReader(open(p, newline="", encoding="utf-8")))


# ---------------------------------------------------------------------------------------------
# stage.py: event tables, restake rows, names
# ---------------------------------------------------------------------------------------------

def _event_tables_at(d: pathlib.Path, chem_stars=("C1",), math_stars=("M1",)) -> pathlib.Path:
    _csv(d / "events_econ_cal2026-10.csv", ["star_id", "school", "arrival_year", "event_id"],
         [["E1", "anu", 2010, "E1:2010"]])
    _csv(d / "events_chemistry_cal2026-10.csv", ["author_id", "field", "school", "arrival_corrected"],
         [[a, "chemistry", "anu", 2005] for a in chem_stars])
    _csv(d / "events_math_stats_cal2026-10.csv", ["author_id", "field", "school", "arrival_corrected"],
         [[a, "math_stats", "uq", 2001] for a in math_stars])
    return d


def test_event_tables_has_no_auto_mode(tmp_path):
    ev = _event_tables_at(tmp_path / "ev")
    with pytest.raises(ValueError):
        stage.event_tables("auto", root=ev)                     # never chosen by which files exist
    with pytest.raises(TypeError):
        stage.event_tables("cal2026-10")                        # the root is named, not implied
    tables, tag = stage.event_tables("cal2026-10", root=ev)
    assert tag == "cal2026-10"
    assert tables == {f: ev / f"events_{f}_cal2026-10.csv" for f in stage.FIELDS}
    (ev / "events_math_stats_cal2026-10.csv").unlink()
    with pytest.raises(FileNotFoundError):                      # no silent fall back to 08-28
        stage.event_tables("cal2026-10", root=ev)
    # explicit tables (the M driver's form): all three fields, tag 'explicit'
    named = {f: _csv(tmp_path / "m" / f"events_{f}_r1.csv", ["author_id"], [["X"]]) for f in stage.FIELDS}
    assert stage.event_tables(named, root=ev) == (named, "explicit")
    with pytest.raises(ValueError):
        stage.event_tables({"econ": named["econ"]}, root=ev)


def test_restake_rows_and_names_read_only_the_paths_given(tmp_path, monkeypatch):
    # October's choose-by-existence candidates sit where the old code looked; they must be ignored
    cal10, cal08 = tmp_path / "cal10", tmp_path / "cal08"
    _csv(cal10 / "restake_2026-10.csv", ["author_id", "aage"], [["E1", 99]])
    _csv(cal10 / "verdicts_2026-10.csv", ["author_id", "name"], [["E1", "Wrong Name"], ["E2", "Extra"]])
    _csv(cal08 / "restake_2026-08-28.csv", ["author_id", "aage"], [["E1", 77]])
    _csv(cal08 / "verdicts_2026-08-28.csv", ["author_id", "name"], [["E1", "Old Name"]])
    monkeypatch.setattr(stage, "CAL10", cal10)
    monkeypatch.setattr(stage, "CAL08", cal08)
    given = _csv(tmp_path / "given" / "restake.csv", ["author_id", "aage"], [["E1", 12], ["E3", 5]])
    rows, label = stage._restake_rows(given, "L")
    assert label == "L" and set(rows) == {"E1", "E3"} and rows["E1"]["aage"] == "12"
    a = _csv(tmp_path / "given" / "names.csv", ["author_id", "name"], [["E1", "Name One"]])
    assert stage._names([a]) == {"E1": "Name One"}
    b = _csv(tmp_path / "given" / "names2.csv", ["author_id", "name"], [["E1", "Name Two"]])
    assert stage._names([a, b]) == {"E1": "Name Two"}            # later files win, in the given order
    with pytest.raises(FileNotFoundError):                       # a named file that is absent is a STOP
        stage._names([tmp_path / "given" / "absent.csv"])
    with pytest.raises(FileNotFoundError):
        stage._restake_rows(tmp_path / "given" / "absent.csv", "L")
    with pytest.raises(TypeError):                               # a bare path is not a list of paths
        stage._names(a)


def _u4_aug_v2(v2: pathlib.Path) -> None:
    import pyarrow as pa                                                # noqa: PLC0415
    s, i, b, d = pa.string(), pa.int64(), pa.bool_(), pa.float64()
    ev_schema = pa.schema([("event_id", s), ("dept_id", s), ("star_person_id", s), ("arrival_year", i),
                           ("t_minus_1", i), ("arrival_source", s), ("arrival_evidence_strength", s),
                           ("modal_inst_year", i), ("prior_main_exited", b), ("min_tenure_ok", b),
                           ("departed_year", i)])
    _parquet(v2 / stage.ECON_FNFIX / "u4_aug" / "events" / "data.parquet",
             {n: [] for n in ev_schema.names}, schema=ev_schema)
    ss_schema = pa.schema([("author_id", s), ("name", s), ("dept", s), ("arrival", i), ("subfield", s),
                           ("age_bin", s), ("academic_age", i), ("stock", i), ("percentile", d),
                           ("cell_n", i), ("is_star_1pct", b), ("is_star_5pct", b), ("age_eligible", b),
                           ("is_foreign_poach", b)])
    _parquet(v2 / stage.ECON_FNFIX / "u4_aug" / "star_set" / "star_set.parquet",
             {"author_id": ["Z"], "name": [None], "dept": ["anu_econ"], "arrival": [2000],
              "subfield": ["2002"], "age_bin": [None], "academic_age": [None], "stock": [None],
              "percentile": [None], "cell_n": [None], "is_star_1pct": [True], "is_star_5pct": [True],
              "age_eligible": [True], "is_foreign_poach": [True]}, schema=ss_schema)


def test_build_u4_aug_takes_restake_and_names_from_the_arguments(tmp_path, monkeypatch):
    import pyarrow.parquet as pq                                        # noqa: PLC0415
    cal10, cal08 = tmp_path / "cal10", tmp_path / "cal08"
    _csv(cal10 / "restake_2026-10.csv", ["author_id", "after_cell", "aage", "after_stock", "after_pct",
                                         "after_cell_n"], [["E1", "a|old|b", 99, 1, 0.1, 2]])
    _csv(cal10 / "verdicts_2026-10.csv", ["author_id", "name"], [["E1", "Wrong Name"]])
    _csv(cal08 / "restake_2026-08-28.csv", ["author_id", "after_cell", "aage", "after_stock", "after_pct",
                                            "after_cell_n"], [["E1", "a|older|b", 77, 1, 0.1, 2]])
    _csv(cal08 / "verdicts_2026-08-28.csv", ["author_id", "name"], [["E1", "Old Name"]])
    monkeypatch.setattr(stage, "CAL10", cal10)
    monkeypatch.setattr(stage, "CAL08", cal08)
    v2 = tmp_path / "v2"
    _u4_aug_v2(v2)
    econ = _csv(tmp_path / "events_econ.csv", ["star_id", "school", "arrival_year", "event_id",
                                               "arrival_source", "arrival_evidence"],
                [["E1", "anu", 2010, "E1:2010", "roster", "strong"], ["E2", "anu", 2012, "E2:2012", "", ""]])
    restake = _csv(tmp_path / "cfg" / "restake.csv", ["author_id", "after_cell", "aage", "after_stock",
                                                      "after_pct", "after_cell_n"],
                   [["E1", "x|mid|y", 12, "30.0", "0.97", "40.0"]])
    names = _csv(tmp_path / "cfg" / "names.csv", ["author_id", "name"], [["E1", "Name One"]])
    with pytest.raises(TypeError):                               # the three inputs are keyword-only, required
        stage.build_u4_aug(v2, econ, {"anu": "D_ANU"}, tmp_path / "out0")
    rep = stage.build_u4_aug(v2, econ, {"anu": "D_ANU"}, tmp_path / "out", restake_csv=restake,
                             restake_label="LABEL", names_csvs=[names])
    assert rep["restake_source"] == "LABEL" and rep["n_events"] == 2 and rep["n_with_restake_row"] == 1
    ss = pq.read_table(tmp_path / "out" / "star_set" / "star_set.parquet").to_pylist()
    assert [(r["author_id"], r["name"], r["academic_age"], r["age_bin"], r["stock"], r["cell_n"])
            for r in ss] == [("E1", "Name One", 12, "mid", 30, 40), ("E2", None, None, None, None, None)]
    ev = pq.read_table(tmp_path / "out" / "events" / "data.parquet").to_pylist()
    assert [(r["event_id"], r["dept_id"], r["t_minus_1"]) for r in ev] == [("E1:2010", "D_ANU", 2009),
                                                                          ("E2:2012", "D_ANU", 2011)]


def test_b0_stage_section_reproduces_octobers_restake_source():
    from pipeline.lib import r1_config                                  # noqa: PLC0415
    cfg = r1_config.load(REPO / "config" / "r1" / "B0.json").resolved("stage")
    recorded = json.loads((CAL10 / "frames_econ" / "build_report_econ920_2026-10.json")
                          .read_text("utf-8"))["october"]["regeneration"]["u4_aug"]["restake_source"]
    assert cfg["restake_label"] == recorded == \
        "data/cal2026-08-28/restake_2026-08-28.csv (08-28 candidates only; October table absent)"
    for name in ("controls_report_piece_a_2026-09-22.json", "controls_report_piece_a_review_2026-09-22.json"):
        c2 = json.loads((CAL10 / name).read_text("utf-8"))["c2"]["derivation"]["u4_aug"]
        assert c2["restake_source"] == cfg["restake_label"], name
    res = lambda v: pathlib.Path(v).resolve()                           # noqa: E731
    assert res(cfg["restake_csv"]) == (CAL08 / "restake_2026-08-28.csv").resolve()
    assert [res(p) for p in cfg["names_csvs"]] == [(CAL08 / "verdicts_2026-08-28.csv").resolve()]
    assert res(cfg["events_root"]) == CAL10.resolve()
    assert res(cfg["restake_econ_aug"]) == (CAL10 / "restake_econ11_aug_2026-10.csv").resolve() \
        == L.RESTAKE_OCT.resolve()
    assert res(cfg["roster_added"]) == (CAL10 / "roster_added_2026-10.csv").resolve()
    # October's own fallback was taken because the October table never existed in place
    assert not (CAL10 / "restake_2026-10.csv").exists() and not (CAL10 / "verdicts_2026-10.csv").exists()
    rows, label = stage._restake_rows(pathlib.Path(cfg["restake_csv"]), cfg["restake_label"])
    assert label == recorded
    assert rows == {r["author_id"]: r for r in _rows(CAL08 / "restake_2026-08-28.csv")}
    assert stage.u4_aug_inputs(cfg)["restake_label"] == recorded
    # the event tables the stage section names are the October tables
    tables, tag = stage.event_tables("cal2026-10", root=pathlib.Path(cfg["events_root"]))
    assert tag == "cal2026-10" and all(p.is_file() for p in tables.values())


def test_october_callers_stop_without_a_run_config(monkeypatch):
    from pipeline.lib.r1_config import ConfigStop                       # noqa: PLC0415
    monkeypatch.delenv("SAR_R1_CONFIG", raising=False)
    with pytest.raises(ConfigStop):
        stage.stage_config()
    with pytest.raises(ConfigStop):                              # econ920's two cross-checks read it too
        L.restake_aug_rows()
    with pytest.raises(ConfigStop):
        L.roster_added_persons()


def test_stage_value_refuses_an_unnamed_key():
    with pytest.raises(KeyError):
        stage.stage_value({}, "restake_csv")
    with pytest.raises(KeyError):
        stage.stage_value({"names_csvs": []}, "names_csvs")
    with pytest.raises(KeyError):
        stage.u4_aug_inputs({"restake_csv": "x", "restake_label": "L"})       # names_csvs missing
    got = stage.u4_aug_inputs({"restake_csv": "a/r.csv", "restake_label": "L", "names_csvs": ["a/n.csv"]})
    assert got == {"restake_csv": pathlib.Path("a/r.csv"), "restake_label": "L",
                   "names_csvs": [pathlib.Path("a/n.csv")]}


# ---------------------------------------------------------------------------------------------
# econ920_lib: the two silent-fallback sites
# ---------------------------------------------------------------------------------------------

def _star_set_v2(v2: pathlib.Path) -> None:
    _parquet(v2 / L.ECON / "u4_aug" / "star_set" / "star_set.parquet",
             {"author_id": ["OLD", "X"], "arrival": [2009, 2001], "academic_age": [4, 10]})


def test_econ920_restake_crosscheck_has_no_silent_fallback(tmp_path, monkeypatch):
    import pyarrow.parquet as pq                                        # noqa: PLC0415
    v2 = tmp_path / "v2"
    _star_set_v2(v2)
    corr = {"stars": {"OLD": "NEW"}, "events": {}}
    # the module constant October read by existence: a conflicting age there must not be consulted
    monkeypatch.setattr(L, "RESTAKE_OCT", _csv(tmp_path / "oct" / "restake.csv",
                                               ["author_id", "aage", "arrival_true"], [["NEW", 99, 2009]]))
    good = _csv(tmp_path / "cfg" / "restake.csv", ["author_id", "aage", "arrival_true"], [["NEW", 4, 2009]])
    rec = L.rekeyed_star_set(v2, corr, tmp_path / "out" / "ss.parquet", stage_cfg={"restake_econ_aug": good})
    assert rec["rekeyed"] == [{"old": "OLD", "new": "NEW", "arrival": 2009, "academic_age": 4,
                               "restake_aage": 4, "restake_arrival_true": "2009"}]
    assert pq.read_table(tmp_path / "out" / "ss.parquet").column("author_id").to_pylist() == ["NEW", "X"]
    bad = _csv(tmp_path / "cfg" / "restake_bad.csv", ["author_id", "aage", "arrival_true"], [["NEW", 5, 2009]])
    with pytest.raises(AssertionError):                          # the configured table IS the cross-check
        L.rekeyed_star_set(v2, corr, tmp_path / "out" / "ss2.parquet", stage_cfg={"restake_econ_aug": bad})
    with pytest.raises(FileNotFoundError):                       # configured but absent: no skip
        L.rekeyed_star_set(v2, corr, tmp_path / "out" / "ss3.parquet",
                           stage_cfg={"restake_econ_aug": tmp_path / "cfg" / "absent.csv"})
    with pytest.raises(KeyError):                                # not configured: no skip either
        L.rekeyed_star_set(v2, corr, tmp_path / "out" / "ss4.parquet", stage_cfg={})
    assert L.restake_aug_rows({"restake_econ_aug": good}) == {"NEW": {"author_id": "NEW", "aage": "4",
                                                                      "arrival_true": "2009"}}
    sig = inspect.signature(L.rekeyed_star_set).parameters["stage_cfg"]
    assert sig.kind is inspect.Parameter.KEYWORD_ONLY and sig.default is None


def _agg_inputs(tmp: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    v2 = tmp / "v2"
    _parquet(v2 / "fwci_fullsnapshot_rebuild_2026-08-09" / "data" / "econ_units_2026-08-09.parquet",
             {"incumbent_person_id": ["P_U1"]})
    patch = v2 / "econ_final_2026-08-13" / "patch" / "works_by_author.jsonl"
    patch.parent.mkdir(parents=True)
    patch.write_text(json.dumps({"author_id": "A2"}) + "\n", encoding="utf-8")
    pre_y = _csv(tmp / "pre_y.csv", ["incumbent_person_id", "year", "event_id", "channel", "pub_count"],
                 [["P_X1", 2010, "E:2010", "network", 2], ["P_U1", 2010, "E:2010", "network", 1],
                  ["P_A2", 2010, "E:2010", "both", 3], ["P_X1", 2011, "E:2010", "network", 0],
                  ["P_X2", 2011, "F:2011", "dept_only", 1]])
    return v2, pre_y


def test_roster_added_is_required(tmp_path, monkeypatch):
    v2, pre_y = _agg_inputs(tmp_path)
    # the October location the old code read by existence holds the OTHER person
    cal10 = tmp_path / "cal10"
    _csv(cal10 / "roster_added_2026-10.csv", ["author_id", "dept_key"], [["X2", "anu_econ"]])
    monkeypatch.setattr(L, "CAL10", cal10)
    added = _csv(tmp_path / "cfg" / "roster_added.csv", ["author_id", "dept_key"], [["X1", "anu_econ"]])
    out = L.agg_missing_persons(pre_y, v2, {"F:2011"}, stage_cfg={"roster_added": added})
    blk, na = out["old_event_rows_blocking"], out["prodlib_event_rows_written_NA"]
    assert blk["persons"] == ["P_X1"] and blk["rows"] == 1 and blk["persons_in_roster_added_2026-10"] == 1
    assert na["persons"] == ["P_X2"] and na["persons_in_roster_added_2026-10"] == 0
    assert blk["by_channel"] == {"network": 1, "dept_only": 0, "both": 0}
    with pytest.raises(FileNotFoundError):
        L.agg_missing_persons(pre_y, v2, {"F:2011"}, stage_cfg={"roster_added": tmp_path / "absent.csv"})
    with pytest.raises(KeyError):
        L.agg_missing_persons(pre_y, v2, {"F:2011"}, stage_cfg={})
    assert L.roster_added_persons({"roster_added": added}) == {"P_X1"}


def test_regenerate_with_prodlib_reads_the_stage_section():
    p = inspect.signature(L.regenerate_with_prodlib).parameters["stage_cfg"]
    assert p.kind is inspect.Parameter.KEYWORD_ONLY and p.default is None   # None = load_env (October callers)
    src = (LAYER / "econ920" / "econ920_lib.py").read_text("utf-8")
    assert "RESTAKE_OCT.is_file()" not in src and 'roster_added_2026-10.csv").is_file()' not in src
    body = inspect.getsource(L.regenerate_with_prodlib)
    assert "u4_aug_inputs(" in body and "stage_config()" in body


# ---------------------------------------------------------------------------------------------
# stage.build_shadow: explicit tables, and the F14 keyword-only switches
# ---------------------------------------------------------------------------------------------

class _EconCalled(Exception):
    pass


def _toy_shadow(tmp: pathlib.Path, monkeypatch, *, raw_equal: bool = True, chem_stars=("C1",)) -> dict:
    """A toy legacy tree + 08-28 dir + raw_verified dir + October event tables; the econ subtree is
    replaced by a recorder (its parts have their own toy tests in test_cal2026_10_piece_a.py)."""
    v2 = tmp / "v2"
    (v2 / RL).parent.mkdir(parents=True)
    (v2 / RL).write_text("SCHOOL_INST = {}\n", encoding="utf-8")
    gold = v2 / stage.GOLD / "data"
    links = [RL]
    raw = tmp / "raw"
    for f in stage.FIELDS_GOLD:
        rel = f"{stage.GOLD}/data/fnfix/roster_gold_{f}.parquet"
        _parquet(v2 / rel, {"author_id": [f"L_{f}"], "year_start": [2000], "year_end": [2010]})
        links.append(rel)
        raw.mkdir(exist_ok=True)
        if raw_equal:
            (raw / f"roster_gold_{f}.parquet").write_bytes((v2 / rel).read_bytes())
        else:
            _parquet(raw / f"roster_gold_{f}.parquet", {"author_id": [f"OTHER_{f}"], "year_start": [1990],
                                                        "year_end": [1999]})
    _csv(gold / "shortlist_fnfix.csv", ["author_id", "field", "school", "arrival_year"],
         [["C1", "chemistry", "anu", 2005]])
    _csv(gold / "events_chemistry_fnfixbase_2026-08-10.csv", ["event_id", "arrival_year"], [["C1:anu", 2005]])
    _csv(gold / "events_math_stats_fnfixbase_2026-08-10.csv", ["event_id", "arrival_year"], [["M1:uq", 2001]])
    cal08 = tmp / "cal08"
    excl08 = _parquet(cal08 / "stars_excluded_cal2026-08-28.parquet", {"author_id": ["C1", "M1", "Z9"]})
    (cal08 / "edges_supplement_cal2026-08-28.jsonl").write_text('{"w": 1}\n', encoding="utf-8")
    ev = _event_tables_at(tmp / "ev", chem_stars=chem_stars)
    monkeypatch.setattr(stage, "legacy_v2", lambda: v2)
    monkeypatch.setattr(stage, "CAL08", cal08)
    monkeypatch.setattr(stage, "RAW", raw)
    monkeypatch.setattr(stage.fs08, "FROZEN_LINKS", tuple(links))
    monkeypatch.setitem(stage.fs08.PINNED_LEGACY_CODE, RL, sha(v2 / RL))
    calls: list = []

    def econ(*a, **k):
        calls.append(k)
    monkeypatch.setattr(stage, "_econ_subtree", econ)
    cfg = {"events_root": ev, "restake_csv": tmp / "unused_restake.csv", "restake_label": "L",
           "names_csvs": [tmp / "unused_names.csv"]}
    return {"v2": v2, "cal08": cal08, "excl08": excl08, "ev": ev, "cfg": cfg, "econ_calls": calls}


def _entry(sh, rel: str) -> dict:
    return [e for e in sh.entries if e["rel"] == rel][-1]


def test_build_shadow_defaults_are_october(tmp_path, monkeypatch):
    params = inspect.signature(stage.build_shadow).parameters
    assert params["events"].default is inspect.Parameter.empty            # no 'auto' default
    assert params["stage_cfg"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["stage_cfg"].default is inspect.Parameter.empty
    for name in ("stars_excluded", "rosters"):
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY and params[name].default is None
    src = inspect.getsource(stage.build_shadow)
    assert 'CAL08 / "stars_excluded_cal2026-08-28.parquet"' in src            # the None branches
    assert 'RAW / f"roster_gold_{field}.parquet"' in src
    t = _toy_shadow(tmp_path, monkeypatch)
    sh, rec = stage.build_shadow(tmp_path / "shadow", "cal2026-10", stage_cfg=t["cfg"])
    gold = f"{stage.GOLD}/data"
    assert sh.path(f"{gold}/stars_excluded_fnfix.parquet").read_bytes() == t["excl08"].read_bytes()
    assert _entry(sh, f"{gold}/stars_excluded_fnfix.parquet")["origin"] == \
        "cal:stars_excluded_cal2026-08-28.parquet (unchanged for chemistry/math_stats)"
    for f in stage.FIELDS_GOLD:
        rel = f"{gold}/fnfix/roster_gold_{f}.parquet"
        assert sha(sh.path(rel)) == sha(t["v2"] / rel)
        assert _entry(sh, rel)["origin"] == f"frozen:{t['v2'] / rel}"
    assert "rosters" not in rec and "stars_excluded_chemmath" not in rec
    assert rec["events"] == "cal2026-10"
    assert rec["tables"]["chemistry"]["path"] == str(t["ev"] / "events_chemistry_cal2026-10.csv")
    assert _entry(sh, f"{gold}/events_chemistry_fnfix_2026-08-10.csv")["origin"] == \
        f"cal:{t['ev'] / 'events_chemistry_cal2026-10.csv'} (cal2026-10)"
    assert len(t["econ_calls"]) == 1 and t["econ_calls"][0]["stage_cfg"] is t["cfg"]


def test_build_shadow_defaults_keep_the_october_asserts(tmp_path, monkeypatch):
    t = _toy_shadow(tmp_path / "a", monkeypatch, raw_equal=False)
    with pytest.raises(AssertionError, match="raw_verified"):
        stage.build_shadow(tmp_path / "a" / "shadow", "cal2026-10", stage_cfg=t["cfg"])
    t = _toy_shadow(tmp_path / "b", monkeypatch, chem_stars=("C1", "C2"))
    with pytest.raises(AssertionError, match="C2"):              # C2 is outside the 08-28 list: STOP
        stage.build_shadow(tmp_path / "b" / "shadow", "cal2026-10", stage_cfg=t["cfg"])
    with pytest.raises(KeyError):                                # the tables' root is named by config
        stage.build_shadow(tmp_path / "b" / "shadow2", "cal2026-10",
                           stage_cfg={k: v for k, v in t["cfg"].items() if k != "events_root"})


def test_build_shadow_links_given_rosters_and_exclusions(tmp_path, monkeypatch):
    t = _toy_shadow(tmp_path, monkeypatch, raw_equal=False, chem_stars=("C1", "C2"))
    r1 = tmp_path / "r1"
    rosters = {f: _parquet(r1 / f"roster_gold_{f}_r1.parquet", {"author_id": [f"N_{f}", "C2"],
                                                                "year_start": [2001, 2002],
                                                                "year_end": [2011, 2012]})
               for f in stage.FIELDS_GOLD}
    mlist = _parquet(r1 / "stars_excluded_r1.parquet", {"author_id": ["C1", "C2", "M1"]})
    sh, rec = stage.build_shadow(tmp_path / "shadow", "cal2026-10", stage_cfg=t["cfg"],
                                 stars_excluded=mlist, rosters=rosters)
    gold = f"{stage.GOLD}/data"
    for f, src in rosters.items():
        rel = f"{gold}/fnfix/roster_gold_{f}.parquet"
        assert sh.path(rel).read_bytes() == src.read_bytes()                 # re-pointed link
        e = _entry(sh, rel)
        assert e["origin"].startswith("r1:") and str(src) in e["origin"] and e["sha256"] == sha(src)
        assert rec["rosters"][f] == {"source": str(src), "sha256": sha(src)}
    assert sh.path(f"{gold}/stars_excluded_fnfix.parquet").read_bytes() == mlist.read_bytes()
    e = _entry(sh, f"{gold}/stars_excluded_fnfix.parquet")
    assert e["origin"].startswith("r1:") and str(mlist) in e["origin"]
    assert rec["stars_excluded_chemmath"] == {"source": str(mlist), "sha256": sha(mlist), "n": 3}
    assert len(t["econ_calls"]) == 1
    # the given list replaces the 08-28 membership check: a star outside IT is the STOP
    short = _parquet(r1 / "stars_excluded_short.parquet", {"author_id": ["C1", "M1"]})
    with pytest.raises(AssertionError, match="C2"):
        stage.build_shadow(tmp_path / "shadow2", "cal2026-10", stage_cfg=t["cfg"], stars_excluded=short,
                           rosters=rosters)
    with pytest.raises(ValueError):
        stage.build_shadow(tmp_path / "shadow3", "cal2026-10", stage_cfg=t["cfg"],
                           rosters={"econ": rosters["chemistry"]})


# ---------------------------------------------------------------------------------------------
# the two October drivers pass stage_cfg; the chemistry / mathematics driver reads October from --october-ref
# ---------------------------------------------------------------------------------------------

class _Sentinel(Exception):
    pass


def test_drivers_pass_the_stage_section_to_build_shadow(tmp_path, monkeypatch):
    seen: list = []

    def fake(root, events, **kw):
        seen.append((events, kw))
        raise _Sentinel()
    monkeypatch.setattr(stage, "build_shadow", fake)
    monkeypatch.setattr(stage, "legacy_v2", lambda: tmp_path / "v2")
    cfg = {"events_root": tmp_path, "restake_csv": "r", "restake_label": "L", "names_csvs": ["n"]}
    with pytest.raises(_Sentinel):
        rc.build_shadow(tmp_path, "control", cfg)
    with pytest.raises(_Sentinel):
        rctl.control_c2(tmp_path, cfg)
    assert seen == [("cal2026-10", {"stage_cfg": cfg}), ("cal2026-08-28", {"stage_cfg": cfg})]


def test_drivers_stop_without_a_run_config_before_any_work(tmp_path, monkeypatch):
    from pipeline.lib.paths import OUT_ROOT_ENV                         # noqa: PLC0415
    from pipeline.lib.r1_config import ConfigStop                       # noqa: PLC0415
    monkeypatch.delenv("SAR_R1_CONFIG", raising=False)

    def ran(*a, **k):
        raise AssertionError("work started without a run config")
    for mod, fn in ((rctl, "control_c1"), (rc, "preconditions")):
        monkeypatch.setattr(mod, fn, ran)
    (tmp_path / "o1").mkdir()
    monkeypatch.setenv(OUT_ROOT_ENV, str(tmp_path / "o1"))
    with pytest.raises(ConfigStop):
        rctl.main(["--execute"])
    (tmp_path / "o2").mkdir()
    monkeypatch.setenv(OUT_ROOT_ENV, str(tmp_path / "o2"))
    with pytest.raises(ConfigStop):
        rc.main(["--execute", "--october-ref", str(tmp_path)])


def test_chemmath_october_ref_is_a_required_flag(tmp_path, monkeypatch):
    from pipeline.lib.paths import OUT_ROOT_ENV                         # noqa: PLC0415
    monkeypatch.delenv(OUT_ROOT_ENV, raising=False)              # the old code must stop before any work
    monkeypatch.delenv("SAR_R1_CONFIG", raising=False)
    with pytest.raises(SystemExit) as e:
        rc.main(["--execute"])
    assert e.value.code == 2
    src = (LAYER / "run_cal_frames_chemmath.py").read_text("utf-8")
    assert "--october-ref" in src.split('"""', 2)[1]             # the usage line in the docstring shows it


def _chemmath_toy(tmp: pathlib.Path, monkeypatch) -> pathlib.Path:
    """repo/ with the 08-28 frames + golds + both MANIFESTs, ref/ with October's data/frames and
    data/cal2026-10/frames_<field>/; the repo's own data/frames copies are STALE (a read of them
    would fail its anchor) and the repo has no data/cal2026-10/frames_<field>/ (purged)."""
    repo = tmp / "repo"
    cal10, cal08, raw = repo / "data/cal2026-10", repo / "data/cal2026-08-28", repo / "data/raw_verified"
    frames08, exp08, ref = cal08 / "frames", cal08 / "estimates", tmp / "ref"
    man08, man_top = [], []
    for f in rc.FIELDS:
        for d in (cal10 / f"events_{f}_cal2026-10.csv", cal08 / f"events_{f}_cal.csv"):
            _csv(d, ["author_id"], [[f"S_{f}"]])
        for d in (raw / f"roster_gold_{f}.parquet", raw / "incfel" / f"roster_gold_{f}.parquet"):
            d.parent.mkdir(parents=True, exist_ok=True)
            d.write_bytes(f"roster {d}".encode())
        names08 = [f"p1_frame_{f}.csv", f"p2_becoming_{f}.csv", f"p3_slim_{f}.parquet",
                   f"p3_slim_ev_{f}.parquet", f"relationships_{f}.csv", f"union_build_report_{f}.json",
                   f"pairs_none_{f}.parquet", "staging_manifest_2026-08-28.json"]
        for n in names08:
            p = frames08 / n
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(f"08-28 {n}".encode())
            man08.append(f"{sha(p)}  data/cal2026-08-28/frames/{n}")
        for n in (f"P1_fnfix_{f}.json", f"P2_fnfix_{f}.json"):
            p = exp08 / n
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(f"gold {n}".encode())
            man08.append(f"{sha(p)}  data/cal2026-08-28/estimates/{n}")
        for n in (f"p1_frame_{f}.csv", f"p2_becoming_{f}.csv", f"p3_slim_{f}.parquet", f"p3_slim_ev_{f}.parquet"):
            r = ref / "data/frames" / n
            r.parent.mkdir(parents=True, exist_ok=True)
            r.write_bytes(f"october {n}".encode())
            man_top.append(f"{sha(r)}  data/frames/{n}")
            stale = repo / "data/frames" / n
            stale.parent.mkdir(parents=True, exist_ok=True)
            stale.write_bytes(f"STALE {n}".encode())
        fr = ref / f"data/cal2026-10/frames_{f}"
        fr.mkdir(parents=True)
        lines = []
        for name in rc.PRODUCTS:
            n = name.format(f=f)
            (fr / n).write_bytes(f"october {n}".encode())
            lines.append(f"{sha(fr / n)}  data/cal2026-10/frames_{f}/{n}\n")
        (fr / "MANIFEST.sha256").write_text("".join(lines), encoding="utf-8")
    (cal08 / "MANIFEST.sha256").write_text("\n".join(man08) + "\n", encoding="utf-8")
    (repo / "data/MANIFEST.sha256").write_text("\n".join(man_top) + "\n", encoding="utf-8")
    for k, v in (("REPO", repo), ("CAL10", cal10), ("CAL08", cal08), ("RAW", raw), ("INCFEL", raw / "incfel"),
                 ("FRAMES08", frames08), ("EXPECTED08", exp08)):
        monkeypatch.setattr(rc, k, v)
    monkeypatch.setattr(rc, "FRAMES", repo / "data/frames", raising=False)
    monkeypatch.setattr(rc, "STOPS", [])
    return ref


def test_chemmath_preconditions_read_october_anchors_from_the_ref_flag(tmp_path, monkeypatch):
    ref = _chemmath_toy(tmp_path, monkeypatch)
    P = rc.preconditions(ref)
    assert rc.STOPS == []
    for f in rc.FIELDS:
        assert P[f"events_{f}_byte_identical_to_08_28"] is True
        assert P[f"frozen_october_{f}"] == "anchored in its MANIFEST.sha256"
        assert P[f"data_frames_copy_{f}"] == "october"           # ref data/frames == ref frames_<f>
    # a missing October product in the ref copy is a STOP, not a skip
    (ref / "data/cal2026-10/frames_chemistry/p2_becoming_chemistry.csv").unlink()
    monkeypatch.setattr(rc, "STOPS", [])
    rc.preconditions(ref)
    assert len(rc.STOPS) == 1 and "data/cal2026-10/frames_chemistry/p2_becoming_chemistry.csv" in rc.STOPS[0]
    (ref / "data/frames/p3_slim_math_stats.parquet").unlink()
    monkeypatch.setattr(rc, "STOPS", [])
    rc.preconditions(ref)
    assert any("data/frames/p3_slim_math_stats.parquet" in s for s in rc.STOPS)


def test_chemmath_preconditions_anchor_the_ref_copy_against_the_repo_manifest(tmp_path, monkeypatch):
    ref = _chemmath_toy(tmp_path, monkeypatch)
    (ref / "data/frames/p1_frame_chemistry.csv").write_bytes(b"tampered")
    with pytest.raises(AssertionError, match="data/frames/p1_frame_chemistry.csv"):
        rc.preconditions(ref)
