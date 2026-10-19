"""merge_null.py — fold run_null.R slice CSVs into the JSON the paper ledger reads.

REPO-AUTHORED, 2026-08-30. The slices of one label partition the simulation indices 1..nsim with
no gaps and no overlaps; this asserts that before averaging, so a lost or duplicated slice is an
error rather than a quietly different mean. Output shape matches the 2026-08-17 script's JSON
(`nsim`, `null_mean`), which is what analysis/paper/ledger_p3afar.py consumes.

Usage:  python merge_null.py <slice_dir> <label> <expected_nsim> <out.json>
"""
import csv, json, pathlib, statistics, sys

KEYS = ("ratio_yearFE", "ratio_evyearFE", "dcdh_ate_pp")


def merge(slice_dir: pathlib.Path, label: str, nsim: int) -> dict:
    rows = []
    for f in sorted(slice_dir.glob(f"{label}_null_*.csv")):
        rows += list(csv.DictReader(open(f)))
    if not rows:
        raise SystemExit(f"no slice CSVs for {label} in {slice_dir}")
    sims = sorted(int(r["sim"]) for r in rows)
    if sims != list(range(1, nsim + 1)):
        missing = sorted(set(range(1, nsim + 1)) - set(sims))
        dupes = sorted({s for s in sims if sims.count(s) > 1})
        raise SystemExit(f"{label}: slices do not partition 1..{nsim} "
                         f"(missing {missing[:20]}, duplicated {dupes[:20]})")

    def vals(k):
        return [float(r[k]) for r in rows if r[k] not in ("", "NA")]

    out = {"label": label, "nsim": nsim, "n_slices": len(list(slice_dir.glob(f"{label}_null_*.csv"))),
           "null_mean": {k: (statistics.fmean(vals(k)) if vals(k) else None) for k in KEYS},
           "null_sd": {k: (statistics.stdev(vals(k)) if len(vals(k)) > 1 else None) for k in KEYS},
           "n_used": {k: len(vals(k)) for k in KEYS},
           "sims": [{"sim": int(r["sim"]), "seed": int(r["seed"]),
                     **{k: (float(r[k]) if r[k] not in ("", "NA") else None) for k in KEYS},
                     "ties": int(r["ties"]), "rows": int(r["rows"])} for r in rows]}
    return out


if __name__ == "__main__":
    sd, lab, n, dst = pathlib.Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]), pathlib.Path(sys.argv[4])
    d = merge(sd, lab, n)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(d, indent=1))
    m = d["null_mean"]
    print(f"{lab}: nsim={d['nsim']} slices={d['n_slices']} "
          f"dCDH_null={m['dcdh_ate_pp']:+.4f} pp  (used {d['n_used']['dcdh_ate_pp']}) -> {dst}")
