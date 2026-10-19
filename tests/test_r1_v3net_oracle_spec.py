# -*- coding: utf-8 -*-
"""pipeline/aws/r1/v3net_oracle_spec.py - the B4 builder of the V3-NET oracle spec, on fakes only.

The two parts call the M drivers' own functions (chemmath_m b0 setup + run_prodlib_m + d2_step; econ920_m's
October plan through shadow -> events_filter). Here those drivers are SimpleNamespace fakes that record the calls
and write toy files under tmp_path, so nothing reads a data disk; the real run is batch B4 (test_big job step,
then tests/test_r1_network_freeze_real.py reads the spec)."""
from __future__ import annotations

import json
import pathlib
import sys
import types

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import v3net_oracle_spec as vs     # noqa: E402

#: what network_freeze.oracle() reads from a spec item (its _observe / _frame_item / Graph)
OBSERVE_KEYS = {"label", "field", "config", "event_table"}
FRAME_KEYS = {"label", "frame", "config", "graph", "event_table", "u5_dose"}
GRAPH_KEYS = {"edges_glob", "works_glob", "supplement_jsonl", "person_map"}


def test_the_spec_schema_is_the_one_the_oracle_accepts():
    src = (REPO / "pipeline" / "aws" / "r1" / "network_freeze.py").read_text(encoding="utf-8")
    assert f'"{vs.SCHEMA}"' in src
    assert vs.ECON_STEPS == ("shadow", "ledger", "star_set", "regenerate", "events_filter")   # REGEN-AGE order


def _cm(tmp_path, calls):
    """A fake chemmath_m: the b0 setup, the prodlib rung and the D2 rung, each recording its call."""
    sh = types.SimpleNamespace(root=tmp_path / "shadow" / "root")

    def setup_b0(cfg, a, scratch, R):
        calls.append(("setup_b0", cfg, R["edges"]["switch"]))
        return {"tag": "b0", "sh": sh, "real_derived": tmp_path / "real",
                "tables": {f: tmp_path / f"events_{f}.csv" for f in vs.CHEMMATH_FIELDS},
                "rosters": {f: tmp_path / f"roster_{f}.parquet" for f in vs.CHEMMATH_FIELDS}}

    def run_prodlib_m(field, root, shadow_root, tag, rec, *, real_derived, n_events):
        calls.append(("prodlib", field, tag, n_events))
        cfgp = root / f"{tag}_prodlib_{field}" / f"config_{field}.json"
        cfgp.parent.mkdir(parents=True)
        cfgp.write_text("{}")
        rec["prodlib"] = {field: {"config": str(cfgp)}}
        rec["frame_rows"] = 7
        return root / f"frame_{field}.csv", {}

    def d2_step(field, frame, roster, sh_, root, tag):
        calls.append(("d2", field, pathlib.Path(frame).name, pathlib.Path(roster).name))
        out = root / f"{tag}_inpost_{field}" / "frame_inpost.csv"
        out.parent.mkdir(parents=True)
        out.write_text("h\na\nb\n")
        return {"output": out, "walk": {"closed": True}}

    return types.SimpleNamespace(
        load_config=lambda p: types.SimpleNamespace(name="B0", path=p),
        check_mode=lambda cfg, mode: calls.append(("mode", mode)),
        edge_env=lambda cfg: {"switch": "u1_edges_full_2026-07-05", "real_derived": str(tmp_path / "real")},
        setup_b0=setup_b0, run_prodlib_m=run_prodlib_m, d2_step=d2_step,
        read_csv=lambda p: [{}, {}, {}], _lines=lambda p: pathlib.Path(p).read_text().count("\n") - 1)


def test_chemmath_part_uses_the_b0_rungs_and_emits_one_observe_and_one_frame_item_per_field(tmp_path):
    calls = []
    frag = vs.part_chemmath(tmp_path / "work", tmp_path / "B0.json", cm=_cm(tmp_path, calls))
    assert [c[0] for c in calls] == ["mode", "setup_b0", "prodlib", "d2", "prodlib", "d2"]
    assert calls[0] == ("mode", "b0") and calls[2] == ("prodlib", "chemistry", "b0", 3)
    assert calls[3] == ("d2", "chemistry", "frame_chemistry.csv", "roster_chemistry.parquet")
    assert [x["label"] for x in frag["observe"]] == list(vs.CHEMMATH_FIELDS) == [x["label"] for x in frag["frames"]]
    for ob, fr in zip(frag["observe"], frag["frames"]):
        assert set(ob) == OBSERVE_KEYS and set(fr) <= FRAME_KEYS and "graph" not in fr
        assert ob["config"] == fr["config"] and pathlib.Path(ob["config"]).name == f"config_{ob['field']}.json"
        assert ob["event_table"] == fr["event_table"] == str(tmp_path / f"events_{ob['field']}.csv")
        assert fr["frame"].endswith(f"b0_inpost_{ob['field']}/frame_inpost.csv")
    assert frag["counts"]["math_stats"] == {"rows_prodlib": 7, "rows_after_d2": 2}
    with pytest.raises(FileExistsError):                                  # a part never reuses a work dir
        vs.part_chemmath(tmp_path / "work", tmp_path / "B0.json", cm=_cm(tmp_path, []))


def _graph(tag):
    """An econ920_m.freeze_graphs value (network_freeze.Graph's four fields)."""
    return types.SimpleNamespace(edges_glob=f"{tag}/E/**/*.parquet", works_glob=f"{tag}/W/**/*.parquet",
                                 supplement_jsonl=f"{tag}/sup.jsonl", person_map_parquet=f"{tag}/pm.parquet")


def _em(tmp_path, n_regen, *, n_fnfix=0, order=None, name="B0", u5=False):
    calls = []
    derived = tmp_path / "derived"
    if u5:
        (derived / vs.U5_DOSE_REL).parent.mkdir(parents=True)
        (derived / vs.U5_DOSE_REL).write_bytes(b"PAR1")
    cal = tmp_path / "cal"

    class Steps:
        def __getattr__(self, step):
            def run(ctx):
                calls.append(step)
                if step == "shadow":
                    ctx.sh = types.SimpleNamespace(path=lambda rel: tmp_path / "shadow" / rel)
                if step == "regenerate":
                    ctx.prod_cfg = {"snapshot": {"edges_glob": "E/**/*.parquet", "works_glob": "W/**/*.parquet"}}
                    ctx.report["regeneration"] = {"prodlib": {"config": str(tmp_path / "regen" / "config_econ.json")}}
                if step == "events_filter":
                    ctx.net1 = tmp_path / "net_1_events.csv"
            return run

    def make_ctx(**kw):
        calls.append(("make_ctx", kw["events_dir"], kw["patch_r1"], kw["exclusion_base_path"]))
        return types.SimpleNamespace(report=kw["report"]["m"], plan=kw["plan"], v2=kw["v2"])

    def fnfix_events(v2):
        calls.append(("fnfix_events", v2))
        return {"A3:2012"}

    def split_net1(frame, *, regen, fnfix, out_dir):
        calls.append(("split", pathlib.Path(frame).name, sorted(regen), sorted(fnfix)))
        n = {"july": 10, "fnfix": n_fnfix, "regenerated": n_regen}
        return {k: (out_dir / f"net1_{k}_rows.csv", n[k]) for k in ("july", "fnfix", "regenerated")}

    def freeze_graphs(ctx, *, need_fnfix):
        calls.append(("graphs", need_fnfix))
        return ({"july": _graph("july"), "fnfix": _graph("fnfix") if need_fnfix else None, "regenerated": None},
                {"july": {}, "fnfix": {"config_sha256": "f" * 64} if need_fnfix else None})

    L = types.SimpleNamespace(CAL10=cal, ROSTER_1008=tmp_path / "roster.parquet", real_v2=lambda: tmp_path / "v2",
                              person_map_path=lambda: tmp_path / "pm.parquet")
    pa = types.SimpleNamespace(_names=lambda x: ["n"], stage_value=lambda c, k: "names.csv", derived_root=lambda: derived)
    em = types.SimpleNamespace(
        ORDER=order or ("shadow", "ledger", "star_set", "regenerate", "events_filter", "network_freeze"),
        L=L, pa_stage=pa, SUP_FNFIX_REL="econ/data/edges_supplement_fnfix.jsonl", Steps=Steps,
        r1_config=types.SimpleNamespace(load=lambda p: types.SimpleNamespace(name=name, resolved=lambda s: {})),
        plan_october=lambda v2, names: types.SimpleNamespace(regen={"A5091326353:2009": "corrected"}),
        make_ctx=make_ctx, FREEZE_PARTS=("july", "fnfix", "regenerated"), fnfix_events=fnfix_events,
        split_net1=split_net1, freeze_graphs=freeze_graphs)
    return em, calls


def test_econ_part_runs_octobers_first_four_steps_and_splits_net1_like_the_m_step(tmp_path):
    """t-big-04: the 2026-08-15 prodlib rows of the fn-fix events were classified on the July graph and two
    relations came out UNEXPLAINED (incumbents that exist only in that run's person map). The spec now takes
    econ920_m's own three-way split and its per-part graphs: 'econ' (July rows, July graph, U5 flags),
    'econ_fnfix' (the 08-15 run's graph) and 'econ_regenerated' (the regeneration config)."""
    em, calls = _em(tmp_path, n_regen=4, n_fnfix=7, u5=True)
    frag = vs.part_econ(tmp_path / "work", tmp_path / "B0.json", em=em)
    assert calls[0] == ("make_ctx", tmp_path / "cal", None, None)
    n = len(vs.ECON_STEPS)
    assert calls[1:1 + n] == list(vs.ECON_STEPS)
    assert calls[1 + n:] == [("fnfix_events", tmp_path / "v2"),
                         ("split", "net_1_events.csv", ["A5091326353:2009"], ["A3:2012"]), ("graphs", True)]
    (ob,) = frag["observe"]
    assert set(ob) == OBSERVE_KEYS and ob["label"] == ob["field"] == "econ"
    assert ob["config"] == str(tmp_path / "regen" / "config_econ.json")
    assert ob["event_table"] == str(tmp_path / "cal" / vs.ECON_TABLE)
    july, fnfix, regen = frag["frames"]
    for item, tag in ((july, "july"), (fnfix, "fnfix")):
        assert set(item) <= FRAME_KEYS and set(item["graph"]) == GRAPH_KEYS and "config" not in item
        assert item["graph"] == {"edges_glob": f"{tag}/E/**/*.parquet", "works_glob": f"{tag}/W/**/*.parquet",
                                 "supplement_jsonl": f"{tag}/sup.jsonl", "person_map": f"{tag}/pm.parquet"}
        assert item["frame"].endswith(f"net1_{tag}_rows.csv") and item["event_table"] == ob["event_table"]
    assert july["label"] == "econ" and july["u5_dose"].endswith("dose.parquet")
    assert fnfix["label"] == "econ_fnfix" and "u5_dose" not in fnfix       # U5 flags describe the July rows only
    assert regen == {"label": "econ_regenerated", "frame": regen["frame"], "config": ob["config"],
                     "event_table": ob["event_table"]} and regen["frame"].endswith("net1_regenerated_rows.csv")
    c = frag["counts"]["econ"]
    assert (c["net1_rows_july"], c["net1_rows_fnfix"], c["net1_rows_regenerated"]) == (10, 7, 4)
    assert c["u5_dose"] == "present" and c["fnfix_config_sha256"] == "f" * 64


def test_econ_part_without_regenerated_rows_or_u5_and_its_guards(tmp_path):
    em, calls = _em(tmp_path, n_regen=0)
    frag = vs.part_econ(tmp_path / "w1", tmp_path / "B0.json", em=em)
    assert [x["label"] for x in frag["frames"]] == ["econ"] and "u5_dose" not in frag["frames"][0]
    assert calls[-1] == ("graphs", False)                  # no fn-fix row: the 08-15 config is not even read
    em, _ = _em(tmp_path, n_regen=0, order=("ledger", "shadow", "regenerate", "events_filter"))
    with pytest.raises(RuntimeError, match="ORDER"):
        vs.part_econ(tmp_path / "w2", tmp_path / "B0.json", em=em)
    em, _ = _em(tmp_path, n_regen=0, name="M")
    with pytest.raises(RuntimeError, match="not B0"):
        vs.part_econ(tmp_path / "w3", tmp_path / "M.json", em=em)


def _frag(*labels):
    return {"observe": [{"label": x} for x in labels], "frames": [{"label": x} for x in labels], "counts": {}}


def test_build_writes_the_parts_that_succeeded_and_says_which_failed(tmp_path):
    def run_part(part, work, config):
        return (0, _frag("chemistry", "math_stats")) if part == "chemmath" else (1, None)

    spec, rep = tmp_path / "spec.json", tmp_path / "out" / "report.json"
    assert vs.build(tmp_path / "work", spec, rep, tmp_path / "B0.json", run_part=run_part) == 1
    body = json.loads(spec.read_text())
    assert body["schema"] == vs.SCHEMA and [x["label"] for x in body["observe"]] == ["chemistry", "math_stats"]
    r = json.loads(rep.read_text())
    assert r["result"] == "INCOMPLETE" and r["parts"]["econ"]["result"] == "FAIL" and r["parts"]["econ"]["rc"] == 1
    assert r["parts"]["chemmath"]["labels"] == ["chemistry", "math_stats"]

    ok = {"chemmath": _frag("chemistry", "math_stats"), "econ": _frag("econ")}
    assert vs.build(tmp_path / "work2", tmp_path / "s2.json", tmp_path / "r2.json", tmp_path / "B0.json",
                    run_part=lambda p, w, c: (0, ok[p])) == 0
    assert [x["label"] for x in json.loads((tmp_path / "s2.json").read_text())["frames"]] == \
        ["chemistry", "math_stats", "econ"]
    with pytest.raises(ValueError, match="duplicate"):
        vs.assemble({"chemmath": _frag("econ"), "econ": _frag("econ")})
    (tmp_path / "busy").mkdir()
    (tmp_path / "busy" / "x").write_text("x")
    with pytest.raises(SystemExit, match="empty"):
        vs.build(tmp_path / "busy", spec, rep, tmp_path / "B0.json", run_part=run_part)


def test_cli_runs_only_on_an_r1_host(tmp_path, monkeypatch):
    monkeypatch.delenv("SAR_HOST", raising=False)
    with pytest.raises(SystemExit, match="R1 instance"):
        vs.main(["build", "--work", str(tmp_path / "w"), "--spec", str(tmp_path / "s"), "--report", str(tmp_path / "r")])
