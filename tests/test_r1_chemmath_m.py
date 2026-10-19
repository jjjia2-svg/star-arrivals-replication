"""R1 F14 + J0-MEAS.3h (unit W2-CHEMM): the M chemistry / mathematics frames driver
pipeline/aws/r1/chemmath_m.py, on toy inputs in tmp_path (no builder, no real data).

The builder subprocesses (run_cal_frames_chemmath.run_stage / run_make_slim) are replaced by recorders
that write tiny placeholder outputs; prodlib and the shadow builder are replaced where a test does not
need them. The only real files read are small tracked ones (config/r1/B0.json and the files it pins, the
October event tables)."""
from __future__ import annotations

import csv
import hashlib
import inspect
import json
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import chemmath_m as cm                                                  # noqa: E402

stage, rcf = cm.stage, cm.rcf
from pipeline.lib import r1_config as r1c                                # noqa: E402

GOLD = stage.GOLD
#: the paths config the tests run under by default (sar_f0_plugin.py); not an edge-table shadow
OCTOBER_PATHS = str(REPO / "config" / "paths_october.yaml")
FRAME_COLS = ["incumbent_person_id", "year", "star_person_id", "event_id", "treated", "post",
              "dose_coupling_baseline", "dose_topic", "dose_low_confidence", "age_gap", "fwci_frac",
              "pub_count", "fwci_frac_ex_star", "pub_count_ex_star", "fwci_mean", "fwci_mean_ex_star"]


def sha(p) -> str:
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def _parquet(p: pathlib.Path, cols: dict) -> pathlib.Path:
    import pyarrow as pa                                                 # noqa: PLC0415
    import pyarrow.parquet as pq                                         # noqa: PLC0415
    p.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(cols), p)
    return p


def _csv(p: pathlib.Path, header: list, rows: list) -> pathlib.Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return p


class FakeCfg:
    def __init__(self, switches=None, pins=None, name="M"):
        self.sw = dict(switches or {})
        self.raw = {"pins": dict(pins or {})}
        self.name = name

    def switch(self, n):
        return self.sw.get(n, r1c.SWITCHES[n]["off"])

    def is_on(self, n):
        return self.switch(n) != r1c.SWITCHES[n]["off"]


# ---------------------------------------------------------------------------------------------
# the chain
# ---------------------------------------------------------------------------------------------

def _recorders(monkeypatch, calls):
    def fake_stage(name, scratch, args, shadow):
        calls.append(("stage", name, str(scratch), tuple(args), str(shadow)))
        return {"run_dir": scratch / "rd", "stage": name}

    def fake_slim(field, src, out_dir):
        calls.append(("slim", field, str(src), str(out_dir)))
        return {"ev": out_dir / "ev.parquet", "noev": out_dir / "noev.parquet"}

    def fake_install(self, rel, produced, origin):
        calls.append(("install", rel, str(produced), origin))
    monkeypatch.setattr(rcf, "run_stage", fake_stage)
    monkeypatch.setattr(rcf, "run_make_slim", fake_slim)
    monkeypatch.setattr(stage.fs08.Shadow, "install", fake_install)


def test_run_chain_m_without_hook_issues_the_october_sequence(tmp_path, monkeypatch):
    calls: list = []
    _recorders(monkeypatch, calls)
    sh = stage.fs08.Shadow(tmp_path / "shadow" / "v2_output")
    frame = tmp_path / "frame.csv"
    rcf.run_chain("chemistry", tmp_path, sh, "m", frame, "origin X")
    october = list(calls)
    assert [c[1] for c in october if c[0] == "stage"] == ["union-gold", "p1-gold", "p2-gold"]
    calls.clear()
    cm.run_chain_m("chemistry", tmp_path, sh, "m", frame, "origin X")
    assert calls == october
    # the hook: called once, after the union outputs are installed and before p1-gold
    calls.clear()

    def hook(f, sh_, st):
        calls.append(("hook", f, st["stage"]))
        return {"x": 1}
    stages = cm.run_chain_m("chemistry", tmp_path, sh, "m", frame, "origin X", post_union=hook)
    i = calls.index(("hook", "chemistry", "union-gold"))
    assert calls[:i] == october[:i] and calls[i + 1:] == october[i:]
    assert calls[i - 1][0] == "install" and calls[i - 1][1].endswith("union_frame_chemistry/funnel.json")
    assert calls[i + 1][:2] == ("stage", "p1-gold")
    assert stages["post_union"] == {"x": 1}


# ---------------------------------------------------------------------------------------------
# preconditions
# ---------------------------------------------------------------------------------------------

def test_preconditions_stop_on_unpinned_input_missing_exclusion_or_unsigned_switch(tmp_path):
    # (a) an unsigned config row: the run config loader's STOP surfaces as CONFIG_UNSIGNED
    raw = json.loads((REPO / "config" / "r1" / "B0.json").read_text(encoding="utf-8"))
    raw["switches"][0]["decided"] = ""
    bad = tmp_path / "B0_unsigned.json"
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(cm.Stop) as e:
        cm.load_config(bad)
    assert e.value.code == "CONFIG_UNSIGNED"
    assert cm.load_config(REPO / "config" / "r1" / "B0.json").name == "B0"
    with pytest.raises(cm.Stop) as e:
        cm.check_mode(cm.load_config(REPO / "config" / "r1" / "B0.json"), "m")
    assert e.value.code == "CONFIG_MODE"
    # (b) an input inside the repository must be pinned, with the right sha256
    repo = tmp_path / "repo"
    f = repo / "data" / "x" / "roster.parquet"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"roster")
    outside = tmp_path / "work" / "events.csv"
    outside.parent.mkdir()
    outside.write_bytes(b"events")
    with pytest.raises(cm.Stop) as e:
        cm.pin_check(FakeCfg(pins={}), repo, {"roster": f})
    assert e.value.code == "UNPINNED_INPUT"
    with pytest.raises(cm.Stop) as e:
        cm.pin_check(FakeCfg(pins={"data/x/roster.parquet": "0" * 64}), repo, {"roster": f})
    assert e.value.code == "PIN_MISMATCH"
    rec = cm.pin_check(FakeCfg(pins={"data/x/roster.parquet": sha(f)}), repo, {"roster": f, "events": outside})
    assert rec["roster"]["pinned_by"] == "config" and rec["events"]["outside_repo"] == str(outside.resolve())
    # a frozen data MANIFEST line pins too (the 08-28 stars_excluded list is anchored there)
    rel = "data/cal2026-08-28/stars_excluded_cal2026-08-28.parquet"
    rec = cm.pin_check(FakeCfg(pins={}), REPO, {"base": REPO / rel})
    assert rec["base"]["pinned_by"] == "manifest"
    # (c) an event star missing from the stars_excluded list
    tables = _tables(tmp_path / "ev")
    short = _parquet(tmp_path / "excl.parquet", {"author_id": ["A1000001", "A2000001"]})
    with pytest.raises(cm.Stop) as e:
        cm.check_stars_excluded(short, tables)
    assert e.value.code == "STAR_NOT_EXCLUDED" and e.value.ids == ["A3000001"]
    full = _parquet(tmp_path / "excl2.parquet", {"author_id": ["A1000001", "A2000001", "A3000001"]})
    assert cm.check_stars_excluded(full, tables) == 3


def _tables(d: pathlib.Path, econ=("E1000001",), chem=("A1000001", "A2000001"), math=("A3000001",)) -> dict:
    """Toy event tables with the 08-28 headers (the real header lines, toy rows)."""
    hdr = {f: next(csv.reader([(stage.CAL08 / f"events_{f}_cal.csv").read_text("utf-8").split("\n", 1)[0]]))
           for f in stage.FIELDS}
    out = {}
    for f, stars in (("econ", econ), ("chemistry", chem), ("math_stats", math)):
        rows = []
        for i, a in enumerate(stars):
            r = {c: "" for c in hdr[f]}
            if f == "econ":
                r.update(event_id=f"{a}:2010", star_id=a, school="anu", arrival_year="2010")
            else:
                r.update(field=f, school=f"s{i}", author_id=a, arrival_corrected="2010")
            rows.append([r[c] for c in hdr[f]])
        out[f] = _csv(d / f"events_{f}_cal2026-10.csv", hdr[f], rows)
    return out


def test_check_tables_reads_the_08_28_shape(tmp_path):
    tables = _tables(tmp_path / "ev")
    rec = cm.check_tables(tables)
    assert rec["chemistry"]["n_events"] == 2 and rec["econ"]["n_events"] == 1
    bad = dict(tables)
    bad["math_stats"] = _csv(tmp_path / "bad" / "events_math_stats_cal2026-10.csv",
                             ["field", "school", "author_id", "arrival_corrected"], [["math_stats", "s", "A3", "2010"]])
    with pytest.raises(cm.Stop) as e:
        cm.check_tables(bad)
    assert e.value.code == "EVENT_HEADER"
    assert cm.t1_of(tables["chemistry"]) == {"A1000001:s0": 2009, "A2000001:s1": 2009}


# ---------------------------------------------------------------------------------------------
# the shadow: October defaults in b0, the M list and rosters in m
# ---------------------------------------------------------------------------------------------

def test_build_shadow_defaults_are_october(tmp_path, monkeypatch):
    params = inspect.signature(stage.build_shadow).parameters
    for name in ("stars_excluded", "rosters"):
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY and params[name].default is None
    src = inspect.getsource(stage.build_shadow)
    assert 'CAL08 / "stars_excluded_cal2026-08-28.parquet"' in src
    assert 'RAW / f"roster_gold_{field}.parquet"' in src
    seen: list = []
    orig_econ = stage._econ_subtree

    def fake(root, events, **kw):
        seen.append((root.name, events, kw, stage._econ_subtree is orig_econ))
        rec: dict = {}
        if stage._econ_subtree is not orig_econ:
            stage._econ_subtree(root, None, None, None, None, rec, stage_cfg=kw["stage_cfg"])
        return stage.fs08.Shadow(root / "v2_output"), rec
    monkeypatch.setattr(stage, "build_shadow", fake)
    cfg = {"events_root": tmp_path, "restake_csv": "r", "restake_label": "L", "names_csvs": ["n"]}
    cm.make_shadow_b0(tmp_path, cfg)
    assert seen[0] == ("shadow_b0", "cal2026-10", {"stage_cfg": cfg}, True)     # October: no M switch
    tables = _tables(tmp_path / "ev")
    mlist = _parquet(tmp_path / "m.parquet", {"author_id": ["A1000001"]})
    rosters = {"chemistry": tmp_path / "rc.parquet", "math_stats": tmp_path / "rm.parquet"}
    _sh, rec = cm.make_shadow_m(tmp_path, tables, tmp_path / "ev", mlist, rosters)
    name, events, kw, econ_is_orig = seen[1]
    assert name == "shadow_m" and events == {f: pathlib.Path(tables[f]) for f in stage.FIELDS}
    assert kw["stars_excluded"] == mlist and kw["rosters"] == rosters
    assert econ_is_orig is False and rec["econ_subtree_skipped"] is True
    assert stage._econ_subtree is orig_econ                                     # restored after the call


def test_m_stars_excluded_rule(tmp_path):
    # base: A1 (kept), A2 (a DROP star, not an M event star -> back to the colleagues),
    # A3 (a DROP verdict but still an M event star -> stays), A4 (kept)
    base = _parquet(tmp_path / "base.parquet", {"author_id": ["A1000001", "A2000001", "A3000001", "A4000001"]})
    tables = _tables(tmp_path / "ev", econ=("E1000001",), chem=("A3000001", "C1000001"), math=("M1000001",))
    out = tmp_path / "m.parquet"
    rec = cm.m_stars_excluded(base, tables, {"A2000001", "A3000001"}, {"C1000001": ["C1000002"], "X9": ["X8"]}, out)
    import pyarrow.parquet as pq                                         # noqa: PLC0415
    got = pq.read_table(out).column("author_id").to_pylist()
    assert got == sorted({"A1000001", "A3000001", "A4000001", "E1000001", "C1000001", "C1000002", "M1000001"})
    assert rec["removed"] == ["A2000001"]
    assert rec["added"] == ["C1000001", "C1000002", "E1000001", "M1000001"]
    assert rec["alias_ids"] == ["C1000002"]
    assert rec["drop_stars_that_are_m_event_stars"] == ["A3000001"]
    assert cm.check_stars_excluded(out, tables) == len(got)


# ---------------------------------------------------------------------------------------------
# rosters: the variant's files, ONE file for prodlib, the dept channel and the D2 spells
# ---------------------------------------------------------------------------------------------

def _roster(p, rows) -> pathlib.Path:
    return _parquet(p, {"dept_key": [r[0] for r in rows], "school": [r[1] for r in rows],
                        "author_id": [r[2] for r in rows], "year_start": [r[3] for r in rows],
                        "year_end": [r[4] for r in rows]})


def test_incfel_variant_reads_the_incfel_roster(tmp_path):
    rows = [("anu_chem", "anu", "A1000001", 2008, 2012), ("anu_chem", "anu", "A2000001", 2000, 2005)]
    inc = {f: _roster(tmp_path / "r" / f"roster_gold_{f}_r1_incfel.parquet", rows) for f in cm.FIELDS}
    fn = {f: _roster(tmp_path / "r" / f"roster_gold_{f}_r1.parquet", rows) for f in cm.FIELDS}
    assert set(cm.check_rosters(inc, "incfel")) == set(cm.FIELDS)
    assert set(cm.check_rosters(fn, "fnfix")) == set(cm.FIELDS)
    for files, variant in ((fn, "incfel"), (inc, "fnfix")):
        with pytest.raises(cm.Stop) as e:
            cm.check_rosters(files, variant)
        assert e.value.code == "ROSTER_VARIANT"
    wrong = dict(inc)
    wrong["chemistry"] = _parquet(tmp_path / "w" / "roster_gold_chemistry_r1_incfel.parquet",
                                  {"author_id": ["A1"], "year_start": [2000], "year_end": [2001]})
    with pytest.raises(cm.Stop) as e:
        cm.check_rosters(wrong, "incfel")
    assert e.value.code == "ROSTER_SHAPE"
    # the D2 spells read the very file the shadow links for prodlib / the union builder
    frame = tmp_path / "prodlib_frame.csv"
    lines = [",".join(FRAME_COLS)]
    for pid in ("A1000001", "A2000001"):
        for y in range(2005, 2016):
            lines.append(f"{pid},{y},S1,S1:anu,True,{'True' if y >= 2010 else 'False'},,0.5,False,3.0,0.0,0.0,0.0,0.0,,")
    frame.write_bytes(("\r\n".join(lines) + "\r\n").encode())
    sh = stage.fs08.Shadow(tmp_path / "sh" / "v2_output")
    sh.link_frozen(f"{GOLD}/data/fnfix/roster_gold_chemistry.parquet", inc["chemistry"])
    filt = cm.d2_step("chemistry", frame, inc["chemistry"], sh, tmp_path, "m")
    assert filt["report"]["spells"]["roster_sha256"] == sha(inc["chemistry"])
    assert filt["report"]["relations_by_class"] == {"kept": 1, "dropped_no_spell": 0, "dropped_not_in_post": 1}
    assert filt["walk"]["closed"] and filt["walk"]["rows_removed"] == 11
    other = _roster(tmp_path / "o" / "roster_gold_chemistry_r1_incfel.parquet", rows[:1])
    with pytest.raises(cm.Stop) as e:
        cm.d2_step("chemistry", frame, other, sh, tmp_path, "m2")
    assert e.value.code == "ROSTER_NOT_ONE_FILE"


# ---------------------------------------------------------------------------------------------
# N2 env and the b0 switch-off run
# ---------------------------------------------------------------------------------------------

def test_edge_env_follows_the_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("SAR_PATHS_CONFIG", OCTOBER_PATHS)
    monkeypatch.delenv("SAR_SSD_ROOT", raising=False)
    off = FakeCfg()
    assert cm.edge_env(off)["edge_shadow"] is False
    on = FakeCfg({"chemmath_edges": r1c.SWITCHES["chemmath_edges"]["on"]})
    with pytest.raises(cm.Stop) as e:
        cm.edge_env(on)                                    # on, but the stage did not export the shadow
    assert e.value.code == "EDGE_ENV"
    d = tmp_path / "edge_table"
    d.mkdir()
    (d / cm.et.MANIFEST_NAME).write_text("{}", encoding="utf-8")
    pf = d / cm.et.PATHS_NAME
    pf.write_text((REPO / "config" / "paths_october.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("SAR_PATHS_CONFIG", str(pf))
    with pytest.raises(cm.Stop) as e:
        cm.edge_env(off)                                   # off, but the edge shadow is in the env
    assert e.value.code == "EDGE_ENV"


def test_mode_b0_sets_no_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")
    monkeypatch.setenv("SAR_PATHS_CONFIG", OCTOBER_PATHS)
    for k in ("SAR_SSD_ROOT", "SAR_OUT_ROOT"):
        monkeypatch.delenv(k, raising=False)
    shadow_calls: list = []

    def fake_build_shadow(root, events, **kw):
        shadow_calls.append((events, sorted(kw)))
        return stage.fs08.Shadow(root / "v2_output"), {"events": events, "tables": {}}
    monkeypatch.setattr(stage, "build_shadow", fake_build_shadow)
    frame = tmp_path / "frame.csv"
    frame.write_text(",".join(FRAME_COLS) + "\n", encoding="utf-8")

    def fake_prodlib(field, root, shadow_root, tag, rec, *, real_derived, n_events):
        rec["events_in_prodlib"] = n_events
        return frame, {"snapshot": {"edges_glob": "E", "works_glob": "W"}}
    monkeypatch.setattr(cm, "run_prodlib_m", fake_prodlib)
    rosters_seen = []

    def fake_d2(field, fr, roster, sh, root, tag):
        rosters_seen.append(pathlib.Path(roster))
        rep = {"relations_by_class": {}, "rows_by_class": {}, "persons_by_class": {},
               "events_left_with_zero_rows": [], "input": {}, "output": {}}
        return {"input": fr, "output": fr, "report": rep, "cls": {}, "walk": {"closed": True}}
    monkeypatch.setattr(cm, "d2_step", fake_d2)
    envs: list = []

    def fake_stage(name, scratch, args, shadow):
        envs.append(os.environ.get("SAR_PATHS_CONFIG"))
        f = args[1]
        base = scratch / "rd" / "data" / "fnfix"
        if name == "union-gold":
            d = base / f"union_frame_{f}"
            d.mkdir(parents=True)
            for n in (f"analysis_frame_{f}_2026-08-10.csv", "relationships.csv", "funnel.json"):
                (d / n).write_text("x\n", encoding="utf-8")
            (d / "build_report.json").write_text(json.dumps(
                {"G_DOSE_advisory": {"n": 200, "missing_side": 0, "max_abs_diff": 0.2, "share_exact_1e-9": 0.9,
                                     "share_le_0.01": 0.95}, "frame": {}, "GATE": "PASS"}), encoding="utf-8")
        elif name == "p1-gold":
            base.mkdir(parents=True)
            (base / f"analysis_frame_{f}_new_gold_2026-08-10.csv").write_text("h\nx\n", encoding="utf-8")
        else:
            d = base / f"panels23_{f}_gold"
            d.mkdir(parents=True)
            for n in ("becoming_none.csv", "pairs_none.parquet", "pairs_slim_none.parquet"):
                (d / n).write_text("x\n", encoding="utf-8")
        return {"run_dir": scratch / "rd", "stage": name}

    def fake_slim(field, src, out_dir):
        out_dir.mkdir(parents=True)
        for n in ("ev", "noev"):
            (out_dir / f"{n}.parquet").write_text("x\n", encoding="utf-8")
        return {"ev": out_dir / "ev.parquet", "noev": out_dir / "noev.parquet", "stats": {}}
    monkeypatch.setattr(rcf, "run_stage", fake_stage)
    monkeypatch.setattr(rcf, "run_make_slim", fake_slim)

    def never(*a, **k):
        raise AssertionError("mode b0 must not run V3-NET or the dose post-step")
    monkeypatch.setattr(cm.nf, "apply", never)
    monkeypatch.setattr(cm.dc, "apply", never)
    cov: list = []
    monkeypatch.setattr(cm, "coverage_step", lambda ctx, fields, out, R: cov.append(ctx["cfg"].switch("agg_missing")))
    monkeypatch.setattr(cm, "compare_products", lambda f, prod, ref: {"all_equal": True, "differ": []})
    out = tmp_path / "out"
    rc = cm.main(["--mode", "b0", "--config", str(REPO / "config" / "r1" / "B0.json"),
                  "--october-ref", str(tmp_path / "ref"), "--out", str(out), "--scratch", str(tmp_path / "scratch")])
    assert rc == 0, (out / "chemmath_m_run_report.json").read_text(encoding="utf-8")
    assert envs and all(v == OCTOBER_PATHS for v in envs) and len(envs) == 6   # no edge-table shadow in any builder env
    assert os.environ["SAR_PATHS_CONFIG"] == OCTOBER_PATHS
    assert shadow_calls == [("cal2026-10", ["stage_cfg"])]                 # October tables, no M list / rosters
    assert rosters_seen == [stage.RAW / f"roster_gold_{f}.parquet" for f in cm.FIELDS]
    assert cov == ["report"]
    assert (out / "RESULT.txt").read_text(encoding="utf-8") == "OK\n"
    for f in cm.FIELDS:
        assert (out / f"frames_{f}" / "MANIFEST.sha256").is_file()
    g = json.loads((out / "report_gdose_chemmath.json").read_text(encoding="utf-8"))
    assert g["fields"]["chemistry"]["max_abs_diff"] == 0.2                  # copied, never gated
    # b0 takes no M input
    with pytest.raises(SystemExit):
        cm.parse(["--mode", "b0", "--config", "c", "--october-ref", "r", "--out", "o", "--calls", "x"])
    with pytest.raises(SystemExit):
        cm.parse(["--mode", "m", "--config", "c", "--out", "o"])


# ---- b0 --edge-proof: the S10 reverse proof's driver mode (J0-MEAS.3j, reverse_proof_s10.py) -------------------

def _edge_shadow(tmp_path, monkeypatch, target_name, *, swapped=None):
    """A toy edge-table shadow env (manifest + paths file, as edge_table.ensure_shadow writes them) whose 07-05
    name points at <tmp>/<target_name>; stage.derived_root() is the shadow's derived dir, as it is in a process
    started with SAR_PATHS_CONFIG = that paths file. Nothing is read through it."""
    d = tmp_path / "edge_table"
    d.mkdir(exist_ok=True)
    shadow, real = d / "openalex_pipeline", tmp_path / "real" / "openalex_pipeline"
    (d / cm.et.MANIFEST_NAME).write_text(json.dumps({
        "swapped_name": swapped or cm.et.TABLE_0705, "target": str(tmp_path / "tables" / target_name),
        "shadow_ssd_root": str(shadow), "real_ssd_root": str(real)}), encoding="utf-8")
    pf = d / cm.et.PATHS_NAME
    pf.write_text("ssd_root: x\n", encoding="utf-8")
    monkeypatch.setenv("SAR_PATHS_CONFIG", str(pf))
    monkeypatch.delenv("SAR_SSD_ROOT", raising=False)
    monkeypatch.setattr(stage, "derived_root", lambda: shadow / "derived")
    return shadow, real


def test_edge_proof_env_needs_the_shadow_and_records_any_target(tmp_path, monkeypatch):
    """The reverse proof runs the b0 driver through the edge-table shadow onto three tables: the cut, the full
    11-school table and the re-materialised 07-05 copy. Plain b0 refuses a shadow env (EDGE_ENV, chemmath_m.py
    edge_env); --edge-proof requires one, accepts any target behind the 07-05 name and records it, and the real
    derived root (the B0 render's prefix) comes from the shadow manifest."""
    b0 = FakeCfg(name="B0")
    for name in ("u1_cut", cm.et.TABLE_11, "u1_0705_copy"):
        shadow, real = _edge_shadow(tmp_path, monkeypatch, name)
        rec = cm.edge_env(b0, proof=True)
        assert rec["edge_proof"] is True and rec["edge_shadow"] is True
        assert pathlib.Path(rec["target"]).name == name
        assert rec["real_derived"] == str(real / "derived") and rec["shadow_derived"] == str(shadow / "derived")
        with pytest.raises(cm.Stop) as e:                  # plain b0 keeps its guard (J0 / F14 b0 unchanged)
            cm.edge_env(b0)
        assert e.value.code == "EDGE_ENV"
    on = FakeCfg({"chemmath_edges": r1c.SWITCHES["chemmath_edges"]["on"]})
    _edge_shadow(tmp_path, monkeypatch, "u1_cut")
    with pytest.raises(cm.Stop) as e:                      # the M on-path still wants the 11-school table
        cm.edge_env(on)
    assert e.value.code == "EDGE_ENV"
    with pytest.raises(cm.Stop) as e:                      # --edge-proof is a switch-off (B0) mode
        cm.edge_env(on, proof=True)
    assert e.value.code == "EDGE_ENV"
    _edge_shadow(tmp_path, monkeypatch, "u1_cut", swapped="u1_other")
    with pytest.raises(cm.Stop) as e:                      # only the 07-05 name may be swapped
        cm.edge_env(b0, proof=True)
    assert e.value.code == "EDGE_ENV"
    _edge_shadow(tmp_path, monkeypatch, "u1_cut")
    monkeypatch.setenv("SAR_SSD_ROOT", str(tmp_path))
    with pytest.raises(cm.Stop) as e:                      # $SAR_SSD_ROOT would override the shadow
        cm.edge_env(b0, proof=True)
    assert e.value.code == "EDGE_ENV"
    monkeypatch.delenv("SAR_SSD_ROOT")
    monkeypatch.setattr(stage, "derived_root", lambda: tmp_path / "elsewhere" / "derived")
    with pytest.raises(cm.Stop) as e:                      # the process did not start under the shadow
        cm.edge_env(b0, proof=True)
    assert e.value.code == "EDGE_ENV"
    monkeypatch.setenv("SAR_PATHS_CONFIG", OCTOBER_PATHS)
    with pytest.raises(cm.Stop) as e:                      # no shadow at all
        cm.edge_env(b0, proof=True)
    assert e.value.code == "EDGE_ENV"


def _toy_b0_chain(monkeypatch, tmp_path, *, all_equal):
    """The b0 run with every builder replaced (as in test_mode_b0_sets_no_switch); compare_products says
    `all_equal` for both fields (differ = relationships otherwise)."""
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")
    monkeypatch.delenv("SAR_OUT_ROOT", raising=False)
    monkeypatch.setattr(stage, "build_shadow",
                        lambda root, events, **kw: (stage.fs08.Shadow(root / "v2_output"), {"events": events}))
    frame = tmp_path / "frame.csv"
    frame.write_text(",".join(FRAME_COLS) + "\n", encoding="utf-8")

    def fake_prodlib(field, root, shadow_root, tag, rec, *, real_derived, n_events):
        rec["events_in_prodlib"], rec["real_derived_seen"] = n_events, str(real_derived)
        return frame, {"snapshot": {"edges_glob": "E", "works_glob": "W"}}
    monkeypatch.setattr(cm, "run_prodlib_m", fake_prodlib)
    rep = {"relations_by_class": {}, "rows_by_class": {}, "persons_by_class": {}, "events_left_with_zero_rows": [],
           "input": {}, "output": {}}
    monkeypatch.setattr(cm, "d2_step", lambda field, fr, roster, sh, root, tag: {
        "input": fr, "output": fr, "report": rep, "cls": {}, "walk": {"closed": True}})

    def fake_stage(name, scratch, args, shadow):
        f = args[1]
        base = scratch / "rd" / "data" / "fnfix"
        if name == "union-gold":
            d = base / f"union_frame_{f}"
            d.mkdir(parents=True)
            for n in (f"analysis_frame_{f}_2026-08-10.csv", "relationships.csv", "funnel.json"):
                (d / n).write_text("x\n", encoding="utf-8")
            (d / "build_report.json").write_text(json.dumps({"G_DOSE_advisory": {}, "frame": {}}), encoding="utf-8")
        elif name == "p1-gold":
            base.mkdir(parents=True)
            (base / f"analysis_frame_{f}_new_gold_2026-08-10.csv").write_text("h\nx\n", encoding="utf-8")
        else:
            d = base / f"panels23_{f}_gold"
            d.mkdir(parents=True)
            for n in ("becoming_none.csv", "pairs_none.parquet", "pairs_slim_none.parquet"):
                (d / n).write_text("x\n", encoding="utf-8")
        return {"run_dir": scratch / "rd", "stage": name}

    def fake_slim(field, src, out_dir):
        out_dir.mkdir(parents=True)
        for n in ("ev", "noev"):
            (out_dir / f"{n}.parquet").write_text("x\n", encoding="utf-8")
        return {"ev": out_dir / "ev.parquet", "noev": out_dir / "noev.parquet", "stats": {}}
    monkeypatch.setattr(rcf, "run_stage", fake_stage)
    monkeypatch.setattr(rcf, "run_make_slim", fake_slim)
    monkeypatch.setattr(cm, "coverage_step", lambda ctx, fields, out, R: None)
    monkeypatch.setattr(cm, "compare_products", lambda f, prod, ref: {
        "all_equal": all_equal, "differ": [] if all_equal else ["relationships"]})


def test_edge_proof_reports_the_october_comparison_and_freezes_the_products(tmp_path, monkeypatch):
    """S10 step 4 runs the b0 driver on the FULL 11-school table, whose products differ from October by design:
    plain b0 would STOP B0_NOT_OCTOBER before freezing anything, so the proof could never compare them.
    --edge-proof reports the comparison (report_chemmath_m.json edge_proof, the run report's vs_october) and
    freezes every product; without the flag the STOP and its no-products behaviour are unchanged."""
    _toy_b0_chain(monkeypatch, tmp_path, all_equal=False)
    _shadow, real = _edge_shadow(tmp_path, monkeypatch, cm.et.TABLE_11)
    out = tmp_path / "out"
    argv = ["--mode", "b0", "--edge-proof", "--config", str(REPO / "config" / "r1" / "B0.json"),
            "--october-ref", str(tmp_path / "ref"), "--fields", "chemistry,math_stats"]
    rc = cm.main(argv + ["--out", str(out), "--scratch", str(tmp_path / "scratch")])
    report = json.loads((out / "chemmath_m_run_report.json").read_text(encoding="utf-8"))
    assert rc == 0, report.get("stop")
    assert (out / "RESULT.txt").read_text(encoding="utf-8") == "OK\n"
    for f in cm.FIELDS:
        assert (out / f"frames_{f}" / "MANIFEST.sha256").is_file(), f
        assert (out / f"frames_{f}" / f"relationships_{f}.csv").is_file(), f
        assert report["vs_october"][f]["all_equal"] is False
        assert report["fields"][f]["prodlib"]["real_derived_seen"] == str(real / "derived")
    s = json.loads((out / "report_chemmath_m.json").read_text(encoding="utf-8"))
    assert s["edge_proof"]["target"] == cm.et.TABLE_11
    assert s["edge_proof"]["b0_vs_october"] == {f: {"all_equal": False, "differ": ["relationships"]}
                                                for f in cm.FIELDS}
    assert report["edges"]["edge_proof"] is True
    # control: plain b0 on the same (unequal) products, no shadow env -> STOP B0_NOT_OCTOBER, nothing frozen
    monkeypatch.setenv("SAR_PATHS_CONFIG", OCTOBER_PATHS)
    out2 = tmp_path / "out2"
    rc = cm.main([a for a in argv if a != "--edge-proof"] + ["--out", str(out2), "--scratch", str(tmp_path / "s2")])
    assert rc == cm.EXIT_STOP
    assert (out2 / "RESULT.txt").read_text(encoding="utf-8") == "STOP B0_NOT_OCTOBER\n"
    assert not any((out2 / f"frames_{f}").exists() for f in cm.FIELDS)
    # --edge-proof is a b0 flag
    m_args = ["--mode", "m", "--config", "c", "--out", "o", "--events-dir", "e", "--roster-chemistry", "r",
              "--roster-math-stats", "r", "--roster-variant", "fnfix", "--stars-excluded-base", "s",
              "--event-tables-all", "e", "--calls", "c"]
    assert cm.parse(m_args).edge_proof is False
    with pytest.raises(SystemExit):
        cm.parse(m_args + ["--edge-proof"])


def test_an_in_process_prodlib_exit_is_a_stop_with_its_code(tmp_path, monkeypatch):
    """t-big-04: the S10 cut run ended rc=3 with nothing in STAGE_OUT to say why. build_frame.py runs in process
    (stage.run_prodlib, runpy), so its own STOP - a sys.exit - ended the driver directly, with no RESULT.txt and
    no stop report. It is now STOP PRODLIB_EXIT with the field and the exit code, written like every other STOP."""
    real_prodlib_m = cm.run_prodlib_m
    _toy_b0_chain(monkeypatch, tmp_path, all_equal=True)
    monkeypatch.setattr(cm, "run_prodlib_m", real_prodlib_m)
    monkeypatch.setattr(stage, "derived_root", lambda: tmp_path / "derived")
    monkeypatch.setenv("SAR_PATHS_CONFIG", OCTOBER_PATHS)
    monkeypatch.delenv("SAR_SSD_ROOT", raising=False)
    calls = []

    def exits(field, mirror, cfg, rec):
        calls.append(field)
        raise SystemExit(3)
    monkeypatch.setattr(stage, "run_prodlib", exits)
    out = tmp_path / "out"
    rc = cm.main(["--mode", "b0", "--config", str(REPO / "config" / "r1" / "B0.json"), "--october-ref",
                  str(tmp_path / "ref"), "--out", str(out), "--scratch", str(tmp_path / "scratch")])
    assert rc == cm.EXIT_STOP and calls == ["chemistry"]
    assert (out / "RESULT.txt").read_text(encoding="utf-8") == "STOP PRODLIB_EXIT\n"
    stop = json.loads((out / "stop_report_chemmath_m.json").read_text(encoding="utf-8"))
    assert stop["code"] == "PRODLIB_EXIT" and stop["ids"] == ["chemistry"]
    report = json.loads((out / "chemmath_m_run_report.json").read_text(encoding="utf-8"))
    assert report["stop"]["detail"] == "build_frame.py exited with 3 (an in-process prodlib STOP)"
    assert report["fields"]["chemistry"]["prodlib"]["config_diff_vs_b0"]["keys"] == []   # it got past the config check


def test_gdose_advisory_is_copied_and_never_gated(tmp_path):
    rep = tmp_path / "build_report.json"
    rep.write_text(json.dumps({"G_DOSE_advisory": {"n": 200, "missing_side": 3, "max_abs_diff": 0.2,
                                                   "share_exact_1e-9": 0.5, "share_le_0.01": 0.6,
                                                   "worst": [["A1", "E", "0.1", "0.3"]]}}), encoding="utf-8")
    assert cm.gdose_advisory(rep) == {"n": 200, "missing_side": 3, "max_abs_diff": 0.2, "share_exact_1e-9": 0.5,
                                      "share_le_0.01": 0.6}


def test_driver_refuses_off_host(monkeypatch):
    monkeypatch.delenv("SAR_HOST", raising=False)
    with pytest.raises(SystemExit, match="R1 rule"):
        cm.main(["--mode", "b0", "--config", "c", "--october-ref", "r", "--out", "o"])


# ---- W2-2 (2026-10-16): chem/maths agg_missing in M ---------------------------------------
# October's own chemistry agg_missing persons (the 11 rows October accepted) are allowlisted by id in config M;
# any other person with papers and no aggregate STOPs. The ids come from October's own frame (chemmath_m.py
# --mode b0 coverage report, cross-checked EQUAL to the October y-step count), never typed by hand.
M_JSON = REPO / "config" / "r1" / "M.json"
OCT_Y = REPO / "data" / "cal2026-10" / "yrebuild_chemmath"


def _cov(persons_by_field, status="EQUAL"):
    return {"fields": {f: {"missing": {"rows": len(ps), "persons": list(ps), "person_years": len(ps), "events": [],
                                       "by_channel": {}},
                           "cross_check": {"status": status, "y_step_agg_missing": len(ps), "rows": len(ps)}}
                       for f, ps in persons_by_field.items()}}


def test_agg_missing_allowlist_admits_only_octobers_persons():
    import missing_persons as mp                                         # noqa: PLC0415
    allow = {"chemistry": {"persons": ["P_A1", "P_A2"]}, "math_stats": {"persons": []}}
    res = cm.apply_agg_allowlist(_cov({"chemistry": ["P_A1", "P_A2", "P_A3"], "math_stats": []}), allow)
    assert res["fields"]["chemistry"]["missing"]["persons"] == ["P_A3"]
    assert res["fields"]["chemistry"]["missing"]["allowlisted_persons"] == ["P_A1", "P_A2"]
    assert mp.coverage_gate(res, "stop", 1) == ("AGG_MISSING", ["P_A3"])                 # an outsider stops
    res = cm.apply_agg_allowlist(_cov({"chemistry": ["P_A1"], "math_stats": []}), allow)
    assert mp.coverage_gate(res, "stop", 1) == ("OK", [])                                # October's own pass
    assert res["fields"]["chemistry"]["allowlisted_not_missing"] == ["P_A2"]             # reported, not a stop
    res = cm.apply_agg_allowlist(_cov({"chemistry": [], "math_stats": ["P_A1"]}), allow)
    assert mp.coverage_gate(res, "stop", 1) == ("AGG_MISSING", ["P_A1"])                 # the list is per field
    res = cm.apply_agg_allowlist(_cov({"chemistry": ["P_A1"]}, status="MISMATCH"), allow)
    assert mp.coverage_gate(res, "stop", 1)[0] == "CROSSCHECK_FAIL"                      # the cross-check still rules
    with pytest.raises(ValueError):
        cm.apply_agg_allowlist(_cov({"chemistry": []}), {"chemistry": {"persons": ["Smith"]}})   # ids only


def test_m_config_allowlists_octobers_chemistry_agg_missing():
    import missing_persons as mp                                         # noqa: PLC0415
    allow = json.loads(M_JSON.read_text(encoding="utf-8"))["agg_missing_allow"]
    assert len(allow["rule"]) > 30 and "W2-2" in allow["rule"]
    for f in ("chemistry", "math_stats"):
        october = mp.y_step_agg_missing(json.loads((OCT_Y / f"g_yrebuild_{f}.json").read_text(encoding="utf-8")))
        row = allow[f]
        assert row["october_rows"] == october, f                                        # 11 chemistry, 0 maths
        assert all(mp.norm_id(p) == p for p in row["persons"]) and len(row["persons"]) <= october, f
        assert len(row["source"]) > 30, f
        if october and not row["persons"]:                                                # until W3-MPIN fills it
            assert len(row.get("pending", "")) > 30, f
    assert allow["math_stats"]["persons"] == []


def test_coverage_step_applies_the_config_allowlist(tmp_path, monkeypatch):
    class Cfg:
        raw = {"agg_missing_allow": {"chemistry": {"persons": ["P_A1"]}, "math_stats": {"persons": []}}}

        def switch(self, name):
            return "stop"

    class Sh:
        def path(self, rel):
            return tmp_path / "pm.parquet"

    found = {"chemistry": ["P_A1"], "math_stats": []}
    monkeypatch.setattr(cm.mp, "chemmath_dirs",
                        lambda dirs, pm, e, w: _cov({dirs[0].name: found[dirs[0].name]}))
    ctx = {"cfg": Cfg(), "sh": Sh(), "p1_dirs": {f: tmp_path / f for f in ("chemistry", "math_stats")},
           "globs": {f: ("e", "w") for f in ("chemistry", "math_stats")}}
    R = {}
    cm.coverage_step(ctx, ["chemistry", "math_stats"], tmp_path / "out", R)              # October's own: no stop
    assert R["coverage"]["code"] == "OK" and R["coverage"]["allowlisted"] == {"chemistry": ["P_A1"], "math_stats": []}
    assert (tmp_path / "out" / "report_coverage_chemmath.json").is_file()
    found["chemistry"] = ["P_A1", "P_A9"]
    with pytest.raises(cm.Stop) as e:
        cm.coverage_step(ctx, ["chemistry", "math_stats"], tmp_path / "out2", {})
    assert e.value.code == "AGG_MISSING" and e.value.ids == ["P_A9"]


def test_render_diff_allows_the_derived_root_inside_a_note_too():
    """S10 t-big-05: with chemmath_edges on, the M render and the B0 render also differ in the template's
    documentation note, which names ${DERIVED}; only that same root swap is allowed, in any key."""
    md, rd = "/work/shadow/openalex_pipeline/derived", "/data/openalex_pipeline/derived"
    note = "rendered: {d} = <ssd_root>/derived"
    m = {"snapshot": {"edges_glob": md + "/e/*.parquet"}, "_cal2026_10_note": note.format(d=md), "fp_gap": 10}
    b = {"snapshot": {"edges_glob": rd + "/e/*.parquet"}, "_cal2026_10_note": note.format(d=rd), "fp_gap": 10}
    d = cm.render_diff(m, b, md, rd)
    assert d["only_snapshot_prefix"] is True and d["keys"] == ["_cal2026_10_note", "snapshot"]
    assert cm.render_diff({**m, "_cal2026_10_note": "other text"}, b, md, rd)["only_snapshot_prefix"] is False
    assert cm.render_diff({**m, "fp_gap": 11}, b, md, rd)["only_snapshot_prefix"] is False


def test_describe_csv_gives_counts_and_the_header_only(tmp_path):
    """j1a-17: prodlib's CSV sniffer failed on a shadow events file that reads fine on the Mac; on an error the
    driver now logs each CSV the rendered config names: bytes, lines, line ends, field counts, the header."""
    p = tmp_path / "e.csv"
    p.write_bytes(b"field,school,author_id\r\nchemistry,unsw,A1\nchemistry,uq,A2,extra\n")
    d = cm.describe_csv(p)
    assert d == {"name": "e.csv", "bytes": p.stat().st_size, "lines": 3, "crlf": 1, "lf_only": 2,
                 "field_counts": [3, 4], "header": "field,school,author_id"}
    assert cm.describe_csv(tmp_path / "absent.csv") == {"name": "absent.csv", "missing": True}
