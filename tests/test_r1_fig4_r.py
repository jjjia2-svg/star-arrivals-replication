# -*- coding: utf-8 -*-
"""R1 N5 (W1-FIG4): save_sample=TRUE is neutral, and the sample file agrees with the estimator.

Big host only (marker estimate, batch B4: r1kit.py test --kind test_big --markers "not live and
estimate"). Toy frames are built in tmp_path, so no data sync is needed. The R stack is the pinned
rmac layer ($SAR_RSCRIPT_RMAC / $SAR_RLIB_RMAC, set by the boot), falling back to Rscript on PATH.
"""
from __future__ import annotations

import gzip
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.estimate

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from analysis.lib import compare_json  # noqa: E402

EST = REPO / "analysis" / "estimation"
DRIVER = REPO / "analysis" / "robustness" / "figure4" / "run_save_sample.R"
FIG4_COUNTS = REPO / "pipeline" / "aws" / "r1" / "fig4_counts.py"
#: label -> (verbatim driver, toy frame file)
CELLS = {"P1_toy_econ": ("run_p1.R", "p1_toy.csv"),
         "P2_toy_econ": ("run_p2.R", "p2_toy.csv"),
         "P3cut_pos_toy_econ": ("run_p3_tp.R", "p3_toy.parquet")}


def _r():
    rs = os.environ.get("SAR_RSCRIPT_RMAC") or shutil.which("Rscript")
    if not rs:
        pytest.fail("no R stack: $SAR_RSCRIPT_RMAC unset and no Rscript on PATH (the big host must have the rmac layer)")
    env = dict(os.environ, R_PROFILE_USER="/dev/null")
    if os.environ.get("SAR_RLIB_RMAC"):
        env["R_LIBS"] = os.environ["SAR_RLIB_RMAC"]
    return rs, env


def _run(script, args, out, cwd):
    rs, env = _r()
    out.mkdir(parents=True, exist_ok=True)
    env["SAR_OUT"] = str(out)
    p = subprocess.run([rs, str(script), *map(str, args)], cwd=cwd, env=env, capture_output=True, text=True)
    assert p.returncode == 0, f"{script.name} {args}: rc {p.returncode}\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}"
    return p


# ---------------------------------------------------------------------------------------------
# toy frames: staggered arrivals, never-switchers, gaps, a few contaminated / missing rows
# ---------------------------------------------------------------------------------------------
def _toy_frames(d: pathlib.Path):
    rng = np.random.default_rng(20261015)
    arrivals = [2005, 2006, 2007, 2008, 2009, 2010]
    rows = []
    for e, a in enumerate(arrivals, 1):
        for i in range(18):
            pid = f"A{100 + (e * 7 + i) % 60}"              # persons recur across events
            dose = 0.0 if i % 3 == 0 else round(float(rng.uniform(0.1, 1.0)), 4)
            ch = ("network", "dept_only", "both")[i % 3 if i % 3 else int(rng.integers(0, 3))]
            for y in range(a - 5, a + 6):
                if rng.random() < 0.06:
                    continue
                rows.append({"event_id": f"E{e}", "incumbent_person_id": pid, "year": y,
                             "age_gap": int(rng.integers(-40, 41)) if rng.random() > 0.02 else 75,
                             "post": "True" if y >= a else "False",
                             "fwci_frac": None if rng.random() < 0.02 else round(float(rng.gamma(1.5, 1.0)), 5),
                             "dose_topic": dose, "channel": ch})
    pd.DataFrame(rows).to_csv(d / "p1_toy.csv", index=False)

    rows = []
    for e, a in enumerate(arrivals + [2030], 1):          # 2030: star after the panel ends (never-switchers)
        for i in range(16):
            for y in range(max(2000, a - 6), min(2016, a + 11)):
                if rng.random() < 0.05:
                    continue
                rows.append({"pid": f"A{(e * 5 + i) % 50}", "event_id": f"E{e}", "year": y,
                             "post": int(y >= a), "y": int(rng.random() < 0.12)})
    pd.DataFrame(rows).to_csv(d / "p2_toy.csv", index=False)

    rows, g = [], 0
    for e, a in enumerate(arrivals + [2030], 1):
        for i in range(18):
            g += 1
            for y in range(max(2000, a - 6), min(2016, a + 11)):
                if rng.random() < 0.05:
                    continue
                rows.append({"grp": g, "year": y, "y": int(rng.random() < 0.15), "D": int(y >= a), "ev": e})
    pd.DataFrame(rows).to_parquet(d / "p3_toy.parquet", index=False)


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """Every toy cell run twice: through the verbatim driver (a/) and through run_save_sample.R (b/)."""
    root = tmp_path_factory.mktemp("fig4_toy")
    _toy_frames(root)
    for label, (drv, frame) in CELLS.items():
        _run(EST / drv, [label, root / frame], root / "a", root)
        _run(DRIVER, [label, root / frame], root / "b", root)
    return root


def _ok(label, js):
    if label.startswith("P1"):
        return all(js["channels"][c]["status"] == "OK" for c in ("union", "network", "dept"))
    if label.startswith("P2"):
        return js["status"] == "OK"
    return "ate" in js["pair_cluster"] and "ate" in js["event_cluster"]


def test_save_sample_is_neutral_on_a_toy_panel(runs):
    # (a) the driver: its JSON is compare_json-EQUAL to the verbatim driver's, cell by cell
    for label in CELLS:
        a = json.loads((runs / "a" / f"{label}.json").read_text(encoding="utf-8"))
        b = json.loads((runs / "b" / f"{label}.json").read_text(encoding="utf-8"))
        assert _ok(label, a), f"{label}: the toy did not estimate, so equality would prove nothing"
        assert compare_json.compare(b, a) == [], label
        assert (runs / "b" / f"{label}_sample.csv.gz").is_file() and (runs / "b" / f"{label}_switchers.csv").is_file()
        assert not (runs / "a" / f"{label}_sample.csv.gz").exists()
    # (b) the package: with and without save_sample=TRUE, every reported result is identical
    script = runs / "neutral.R"
    script.write_text(r'''
suppressMessages({ library(polars); library(DIDmultiplegtDYN); library(jsonlite) }); set.seed(42)
a <- commandArgs(trailingOnly=TRUE)
f <- read.csv(a[1], stringsAsFactors=FALSE)
f <- f[!is.na(f$fwci_frac), ]
f$grp_id <- as.integer(factor(paste(f$incumbent_person_id, f$event_id)))
f$person_id <- as.integer(factor(f$incumbent_person_id))
f$y <- log1p(f$fwci_frac); f$D <- f$dose_topic * as.integer(tolower(f$post) == "true")
d1 <- f[, c("grp_id","year","y","D","person_id")]
p3 <- as.data.frame(pl$read_parquet(a[2]))
same <- function(x, y) identical(x$results$ATE, y$results$ATE) && identical(x$results$Effects, y$results$Effects) &&
  identical(x$results$Placebos, y$results$Placebos) && identical(x$results$p_jointeffects, y$results$p_jointeffects) &&
  identical(x$results$p_jointplacebo, y$results$p_jointplacebo)
r0 <- did_multiplegt_dyn(df=d1, outcome="y", group="grp_id", time="year", treatment="D", effects=6, placebo=4,
        cluster="person_id", graph_off=TRUE)
r1 <- did_multiplegt_dyn(df=d1, outcome="y", group="grp_id", time="year", treatment="D", effects=6, placebo=4,
        cluster="person_id", graph_off=TRUE, save_sample=TRUE)
q0 <- did_multiplegt_dyn(df=p3[, c("grp","year","y","D")], outcome="y", group="grp", time="year", treatment="D",
        effects=5, placebo=4, graph_off=TRUE)
q1 <- did_multiplegt_dyn(df=p3[, c("grp","year","y","D")], outcome="y", group="grp", time="year", treatment="D",
        effects=5, placebo=4, graph_off=TRUE, save_sample=TRUE)
e1 <- did_multiplegt_dyn(df=p3[, c("grp","year","y","D","ev")], outcome="y", group="grp", time="year", treatment="D",
        effects=5, placebo=4, cluster="ev", graph_off=TRUE, save_sample=TRUE)
tags <- function(s) { s <- s[order(s$grp, s$year), c("grp","year","did_sample","did_effect")]; rownames(s) <- NULL; s }
write(toJSON(list(p1=same(r0, r1), p3=same(q0, q1), has_sample=!is.null(r1$save_sample) && !is.null(q1$save_sample),
  cluster_same_tags=identical(tags(q1$save_sample), tags(e1$save_sample)),
  effects_cols=colnames(r1$results$Effects)), auto_unbox=TRUE), file.path(Sys.getenv("SAR_OUT"), "neutral.json"))
''', encoding="utf-8")
    _run(script, [runs / "p1_toy.csv", runs / "p3_toy.parquet"], runs / "n", runs)
    got = json.loads((runs / "n" / "neutral.json").read_text(encoding="utf-8"))
    assert got["p1"] is True and got["p3"] is True and got["has_sample"] is True, got
    # the P3 driver keeps the pair-cluster run's sample: the event-cluster run tags the same cells
    assert got["cluster_same_tags"] is True, got


def _fc():
    spec = importlib.util.spec_from_file_location("fig4_counts_r", FIG4_COUNTS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sample_file_matches_the_estimator(runs):
    fc = _fc()
    record = {}
    for label, (_drv, frame) in CELLS.items():
        with gzip.open(runs / "b" / f"{label}_sample.csv.gz", "rt", encoding="utf-8") as fh:
            s = pd.read_csv(fh)
        table = pd.read_csv(runs / "b" / f"{label}_switchers.csv")
        js = json.loads((runs / "b" / f"{label}.json").read_text(encoding="utf-8"))
        assert list(s.columns) == ["channel", "grp_id", "year", "D", "did_sample", "did_effect", "arrival", "zero_dose"]
        assert set(s["did_sample"]) <= {"Control", "Switcher-in", "Switcher-out"} and len(s) > 0
        assert not s.duplicated(["channel", "grp_id", "year"]).any()
        # 2.3.3 reports a Switchers column; the cross-check is against it (recorded below)
        record[label] = "Switchers" if table["switchers"].notna().any() else "N only"
        assert record[label] == "Switchers", (label, table)
        assert set(fc.switcher_check(s, table).values()) == {"MATCH"}, (label, fc.switcher_check(s, table))
        if label.startswith("P3"):      # the P3 JSON itself carries the Effects switchers
            want = [e["switchers"] for e in js["pair_cluster"]["effects"]]
            got = table[(table["kind"] == "effect")]["switchers"].astype(int).tolist()
            assert got == want, (label, got, want)
            frame_rows = pd.read_parquet(runs / frame)[["grp", "year"]].rename(columns={"grp": "grp_id"})
        if label.startswith("P1"):      # every sampled cell is a row of the channel's estimation frame
            assert set(s["channel"]) == {"union", "network", "dept"}
            assert s["zero_dose"].notna().all()
            for ch in ("union", "network", "dept"):
                assert (s["channel"] == ch).sum() <= js["channels"][ch]["obs"]
        if label.startswith("P2"):
            assert set(s["channel"]) == {"all"} and len(s) <= js["rows"]
        if label.startswith("P3"):
            assert set(s["channel"]) == {"all"}
            m = s.merge(frame_rows, on=["grp_id", "year"], how="left", indicator=True)
            assert (m["_merge"] == "both").all()
        # arrival = the group's first year with post / D > 0; treated rows never precede it
        treated = s[s["D"] > 0]
        assert (treated["year"] >= treated["arrival"]).all()
        # the counts run on the real sample shape, and every counted pool is drawn from sampled groups
        model, ne, npl = fc.model_of(label)
        rows = fc.count(s, n_effects=ne, n_placebos=npl)
        assert rows and {r["pool"] for r in rows} == ({"zero_dose", "pos_not_yet"} if model == "M1" else {"not_yet"})
        for ch, part in s.groupby("channel"):
            n_groups = part["grp_id"].nunique()
            assert all(r["n_relations"] <= n_groups for r in rows if r["channel"] == ch)
    (runs / "switcher_source.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    print("switcher cross-check source per cell:", record)
