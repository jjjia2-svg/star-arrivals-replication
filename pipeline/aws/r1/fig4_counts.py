#!/usr/bin/env python3
"""R1 N5: Figure 4 comparison-relation counts from did_multiplegt_dyn(save_sample=TRUE). Instance only.

  fig4_counts.py --cells-out DIR --out DIR

DIR (--cells-out) is a run_cells.py stage output: every work/<label>/out/<label>_sample.csv.gz under it
(written by analysis/robustness/figure4/run_save_sample.R) is counted, with the sibling
<label>_switchers.csv used for the cross-check. Writes <out>/fig4_counts.csv (one row per label, channel,
cohort, effect or placebo, pool) and <out>/fig4_counts.json:
  {"<label>/<channel>": {label, field, model, channel, switcher_check,
                         cohorts: {G: {year: {kind, k, ell, zero_dose, pos_not_yet, not_yet, switchers}}}}}
(P1 has three channels, union/network/dept; P2 and P3 one, "all"; a pool a model does not have is null.)

The rule (author's 2026-10-03 figure decisions; figB.py; tests/test_r1_fig4.py checks parity):
a comparison relation in year t for cohort G (groups whose first D > 0 is in G) is a group in the
estimation sample with a row in G-1 and in t, D == 0 in G-1, and not switched by t (no D != 0 in any
sampled year <= t). Never-switchers count as well. In Model 1 (zero_dose given) the pool splits into
zero_dose (dose_topic == 0) and pos_not_yet (positive dose, star not yet arrived); in Models 2 and 3
it is one pool, not_yet. Effect k is year G-1+k; placebo k is year G-1-k and keeps effect k's pool,
only the relations that also have a row in the placebo year. n_switchers is the number of cohort-G
groups the package tagged did_effect == k (for a placebo: those that also have a row in its year).
save_sample tags groups only (Control / Switcher-in / Switcher-out, and did_effect for switchers),
not "used as control at t", so the pools follow the rule; only the switcher counts can be checked
against the estimator: per channel and effect k, the groups tagged k must equal the Effects table's
Switchers column. A mismatch fails the run (exit 1) after the outputs are written.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import sys

import numpy as np
import pandas as pd

HOSTS = ("ec2-r1-test", "ec2-r1")
#: label prefix -> (model, effects, placebos): the verbatim drivers' did_multiplegt_dyn calls
SPEC = {"P1": ("M1", 6, 4), "P2": ("M2", 5, 4), "P3": ("M3", 5, 4)}
FIELDS = ("econ", "chemistry", "math_stats")
SAMPLE = "_sample.csv.gz"
SWITCHERS = "_switchers.csv"
COLUMNS = ("label", "field", "model", "channel", "cohort", "year", "ell", "kind", "k", "pool",
           "n_relations", "n_switchers")
_TRUE = {"TRUE", "True", "true", True, 1, 1.0}
_FALSE = {"FALSE", "False", "false", False, 0, 0.0}


def model_of(label):
    """(model, n_effects, n_placebos) from the label prefix."""
    if label[:2] not in SPEC:
        raise ValueError(f"{label}: the label must start with P1, P2 or P3")
    return SPEC[label[:2]]


def field_of(label):
    return next((f for f in FIELDS if f in label), "")


def _flag(series):
    """zero_dose as True / False / None, whatever the writer's spelling (fwrite TRUE/FALSE, pandas bool)."""
    out = []
    for v in series:
        if isinstance(v, (bool, np.bool_)):
            out.append(bool(v))
        elif v is None or v is pd.NA or (isinstance(v, float) and np.isnan(v)):
            out.append(None)
        elif v in _TRUE:
            out.append(True)
        elif v in _FALSE:
            out.append(False)
        else:
            raise ValueError(f"zero_dose value {v!r}")
    return out


def _count_channel(channel, df, n_effects, n_placebos):
    df = df[pd.to_numeric(df["D"], errors="coerce").notna()]
    if df.empty:
        return []
    year = df["year"].astype(int).to_numpy()
    if pd.DataFrame({"g": df["grp_id"].to_numpy(), "y": year}).duplicated().any():
        raise ValueError(f"{channel}: duplicate (grp_id, year) rows in the sample")
    gids, gi = np.unique(df["grp_id"].astype(str).to_numpy(), return_inverse=True)
    ng, y0 = len(gids), int(year.min())
    years = np.arange(y0, int(year.max()) + 1)
    yi = year - y0
    present = np.zeros((len(years), ng), bool)
    present[yi, gi] = True
    dmat = np.zeros((len(years), ng))
    dmat[yi, gi] = pd.to_numeric(df["D"]).to_numpy(float)
    eff = np.full((len(years), ng), np.nan)
    eff[yi, gi] = pd.to_numeric(df["did_effect"], errors="coerce").to_numpy(float)
    treated = present & (dmat != 0)
    first = np.where(treated.any(0), years[treated.argmax(0)], np.inf)      # first switch, inf = never
    first_row = years[present.argmax(0)]
    cohort = np.where(np.isfinite(first) & (first > first_row), first, np.nan)
    flags = _flag(df["zero_dose"]) if "zero_dose" in df else [None] * len(df)
    split = any(f is not None for f in flags)
    zero = np.zeros(ng, bool)
    zero[gi[np.array([f is True for f in flags], dtype=bool)]] = True
    none = np.zeros(ng, bool)

    def at(mat, y, fill):
        i = y - y0
        return mat[i] if 0 <= i < len(years) else np.full(ng, fill, dtype=mat.dtype)

    pools = (("zero_dose", zero), ("pos_not_yet", ~zero)) if split else (("not_yet", ~none),)
    rows = []
    for g in sorted(int(c) for c in np.unique(cohort[~np.isnan(cohort)])):
        base = g - 1
        in_g = cohort == g
        b = at(present, base, False) & (at(dmat, base, 0.0) == 0)
        eff_pool = {}
        for k in range(1, n_effects + 1):
            t = base + k
            cand = b & at(present, t, False) & (first > t)
            tagged = in_g & (at(eff, t, np.nan) == k)
            eff_pool[k] = (cand, tagged)
            for name, mask in pools:
                rows.append({"channel": channel, "cohort": g, "year": t, "ell": t - g, "kind": "effect", "k": k,
                             "pool": name, "n_relations": int((cand & mask).sum()), "n_switchers": int(tagged.sum())})
        for k in range(1, min(n_placebos, n_effects) + 1):
            p = base - k
            cand, tagged = eff_pool[k]
            row_p = at(present, p, False)
            for name, mask in pools:
                rows.append({"channel": channel, "cohort": g, "year": p, "ell": p - g, "kind": "placebo", "k": k,
                             "pool": name, "n_relations": int((cand & row_p & mask).sum()),
                             "n_switchers": int((tagged & row_p).sum())})
    return rows


def count(sample_df, *, n_effects, n_placebos):
    """Rows {channel, cohort, year, ell, kind, k, pool, n_relations, n_switchers} for every channel and
    cohort of a save_sample file (columns channel, grp_id, year, D, did_effect, zero_dose)."""
    rows = []
    for channel, part in sample_df.groupby("channel", sort=True):
        rows += _count_channel(str(channel), part, n_effects, n_placebos)
    return rows


def switcher_check(sample_df, table):
    """{channel: 'MATCH' | 'NOT_REPORTED' | 'MISMATCH ...'}: per effect k, groups tagged did_effect == k
    against the Effects table's Switchers column (table: channel, kind, k, n, switchers)."""
    out = {}
    for channel, part in sample_df.groupby("channel", sort=True):
        channel = str(channel)
        t = None if table is None else table[(table["channel"].astype(str) == channel) & (table["kind"] == "effect")]
        sw = None if t is None else pd.to_numeric(t["switchers"], errors="coerce")
        if t is None or t.empty or sw.isna().all():
            out[channel] = "NOT_REPORTED"
            continue
        e = pd.to_numeric(part["did_effect"], errors="coerce")
        tagged = part[e.notna()].groupby(e[e.notna()].astype(int))["grp_id"].nunique()
        bad = [f"k={int(k)}: sample {int(tagged.get(int(k), 0))} vs table {int(round(s))}"
               for k, s in zip(t["k"], sw) if not pd.isna(s) and int(tagged.get(int(k), 0)) != int(round(s))]
        out[channel] = "MATCH" if not bad else "MISMATCH " + "; ".join(bad)
    return out


def _json(rows, checks):
    out = {}
    for r in rows:
        key = f"{r['label']}/{r['channel']}"
        e = out.setdefault(key, {"label": r["label"], "field": r["field"], "model": r["model"],
                                 "channel": r["channel"], "switcher_check": checks.get(key), "cohorts": {}})
        cell = e["cohorts"].setdefault(str(r["cohort"]), {}).setdefault(str(r["year"]), {
            "kind": r["kind"], "k": r["k"], "ell": r["ell"], "zero_dose": None, "pos_not_yet": None,
            "not_yet": None, "switchers": r["n_switchers"]})
        cell[r["pool"]] = r["n_relations"]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Figure 4 comparison-relation counts from save_sample files")
    ap.add_argument("--cells-out", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if os.environ.get("SAR_HOST", "").strip() not in HOSTS:
        raise SystemExit("R1 rule: fig4_counts.py runs only on an R1 instance ($SAR_HOST)")
    files = sorted(pathlib.Path(a.cells_out).rglob("*" + SAMPLE))
    if not files:
        raise SystemExit(f"no *{SAMPLE} under {a.cells_out}")
    labels = [f.name[:-len(SAMPLE)] for f in files]
    if len(set(labels)) != len(labels):
        raise SystemExit(f"a label has two sample files under {a.cells_out}")
    rows, checks, empty = [], {}, []
    for f, label in zip(files, labels):
        model, n_eff, n_pla = model_of(label)
        sample = pd.read_csv(f, dtype={"channel": str, "did_sample": str})
        if sample.empty:
            empty.append(label)
            continue
        swf = f.with_name(label + SWITCHERS)
        table = pd.read_csv(swf, dtype={"channel": str, "kind": str}) if swf.is_file() else None
        for ch, res in switcher_check(sample, table).items():
            checks[f"{label}/{ch}"] = res
        for r in count(sample, n_effects=n_eff, n_placebos=n_pla):
            rows.append({"label": label, "field": field_of(label), "model": model, **r})
    rows.sort(key=lambda r: (r["label"], r["channel"], r["cohort"], r["kind"], r["k"], r["pool"]))
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "fig4_counts.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    (out / "fig4_counts.json").write_text(json.dumps(_json(rows, checks), indent=1, sort_keys=True) + "\n",
                                          encoding="utf-8")
    for key, res in sorted(checks.items()):
        print(f"{key:<36} switchers {res}")
    for label in empty:
        print(f"{label:<36} EMPTY sample (every channel failed?)")
    bad = empty or any(v.startswith("MISMATCH") for v in checks.values())
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
