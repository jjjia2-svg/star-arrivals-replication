#!/usr/bin/env python3
"""summarize_perm.py — permutation p-values for the T5 randomization-inference batch.

Reads the per-chunk CSVs written by run_perm.R under <outdir>/raw/ and the identity controls
under <outdir>/control/, and writes <outdir>/perm_summary.csv + perm_summary.json.

The permutation p-value follows the standard randomization-inference convention that includes
the observed assignment in the reference set:
    p_perm(|ATE|) = (1 + #{ b : |ATE_b| >= |ATE_obs| }) / (B_ok + 1)
    p_perm(|t|)   = (1 + #{ b : |t_b|   >= |t_obs|   }) / (B_ok + 1)
where B_ok counts the permutations whose estimation succeeded (FAILED draws are reported,
not silently dropped from B — they are excluded from both numerator and denominator, and
their count is a column of the summary). The conventional (asymptotic) two-sided p beside it
is 2*(1 - Phi(|t_obs|)) from the frozen gold's cluster-robust SE.
"""
import csv
import json
import math
import pathlib
import sys


def norm_sf(x: float) -> float:
    return 0.5 * math.erfc(x / math.sqrt(2.0))


def main(outdir: str) -> None:
    root = pathlib.Path(outdir)
    rows = []
    for f in sorted((root / "raw").glob("*_perm_*.csv")):
        with open(f, newline="", encoding="utf-8") as fh:
            rows += list(csv.DictReader(fh))
    ctl = []
    for f in sorted((root / "control").glob("*_perm_0_0.csv")):
        with open(f, newline="", encoding="utf-8") as fh:
            ctl += [r for r in csv.DictReader(fh) if r["perm"] == "0"]
    assert ctl, "no identity controls found"
    by_lab: dict[str, list[dict]] = {}
    for r in rows:
        by_lab.setdefault(r["label"], []).append(r)
    out = []
    for c in sorted(ctl, key=lambda r: r["label"]):
        lab = c["label"]
        perms = by_lab.get(lab, [])
        ok = [r for r in perms if r["status"] == "OK"]
        failed = [r for r in perms if r["status"] != "OK"]
        seen = {int(r["perm"]) for r in perms}
        assert seen == set(range(1, len(perms) + 1)), (
            f"{lab}: permutation indices are not 1..{len(perms)}: missing "
            f"{sorted(set(range(1, len(perms) + 1)) - seen)[:5]} / dupes possible")
        ate0, se0 = float(c["ate"]), float(c["se"])
        t0 = ate0 / se0
        n_ge_ate = sum(1 for r in ok if abs(float(r["ate"])) >= abs(ate0))
        n_ge_t = sum(1 for r in ok if abs(float(r["t"])) >= abs(t0))
        B = len(ok)
        entry = {
            "label": lab, "mode": c["mode"], "n_events": int(c["n_events"]),
            "B_requested": len(perms), "B_ok": B, "B_failed": len(failed),
            "ate_obs": ate0, "se_obs": se0, "t_obs": round(t0, 4),
            "p_conv_normal": round(2 * norm_sf(abs(t0)), 6),
            "p_perm_abs_ate": round((1 + n_ge_ate) / (B + 1), 6),
            "p_perm_abs_t": round((1 + n_ge_t) / (B + 1), 6),
            # descriptive only (the p-values use ate and t); null when a draw's count is NA (R1: every
            # permuted P1 econ draw - an event left with only NA doses has any() = NA)
            "mean_treated_events": round(
                sum(int(r["n_treated_events"]) for r in ok) / max(B, 1), 1)
            if all(r["n_treated_events"].lstrip("-").isdigit() for r in ok) else None,
        }
        out.append(entry)
    with open(root / "perm_summary.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    (root / "perm_summary.json").write_text(
        json.dumps({"seed_key": "config/seeds.yaml permutation_seed", "cells": out},
                   indent=1) + "\n", encoding="utf-8")
    for e in out:
        print(f"{e['label']:24s} B_ok={e['B_ok']:3d} fail={e['B_failed']:2d} "
              f"ate={e['ate_obs']:+.6g} t={e['t_obs']:+.3f} "
              f"p_conv={e['p_conv_normal']:.4f} p_perm|ATE|={e['p_perm_abs_ate']:.4f} "
              f"p_perm|t|={e['p_perm_abs_t']:.4f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/robustness_2026-08-29_b/perm")
