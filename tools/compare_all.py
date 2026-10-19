# tools/compare_all.py
"""Compare every recorded estimate with this run's result: each <expected>/<name>.json against
<output>/estimates/<name>.json, exactly (analysis/lib/compare_json.py). Writes <output>/compare_report.md and
exits 1 if a result differs or is missing.

The large Panel 3 cells are the rcloud rows of the canon's cell lists (config/r1/cells: oct29.tsv for the
October 2026 version; M.tsv and M_evcl.tsv for a canon tree). A run that did not re-run them has no result
for them, and they count as VERIFIED_NOT_RERUN when tools/verify_cloud_custody.py accepts their custody
record (its output goes to <output>/logs/custody.log):

    October 2026 version   verify_cloud_custody.py --custody <cal>/cloud
    a canon tree           verify_cloud_custody.py --custody <canon>/custody --spec <canon>/custody/custody_r1.json

The custody folder is passed relative to the repository when it lies inside it. --custody-spec FILE
replaces the --spec. Every root comes from the paths config in force. A canon tree is recognised as
analysis/lib/canon.py recognises it (the cal root's parent holds CANON.json); this script does not import
canon.py, and analysis/run_all.sh has checked the canon before it runs this."""
import argparse, csv, json, os, pathlib, sys, subprocess
ROOT = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from analysis.lib.compare_json import compare
from analysis.lib.paths import load_paths
#: the cell lists each canon runs: the same table as analysis/lib/run_all_stages.py CELL_LISTS (a test keeps them equal)
CELLS_DIR = ROOT / "config" / "r1" / "cells"
CELL_LISTS = {"october": ("oct29.tsv",), "M": ("M.tsv", "M_evcl.tsv")}
CANON_JSON, CUSTODY_DIR, CUSTODY_SPEC = "CANON.json", "custody", "custody_r1.json"


def canon_root(P) -> pathlib.Path:
    """The directory holding the cal root (a canon tree's root)."""
    return pathlib.Path(P["cal"]).resolve().parent


def mode(P) -> str:
    """'M' when the cal root sits in a canon tree, else 'october'."""
    return "M" if (canon_root(P) / CANON_JSON).is_file() else "october"


def cloud_only(P) -> set:
    """The out_names of the canon's rcloud rows: the large cells that are custody-checked, not re-run."""
    names = set()
    for name in CELL_LISTS[mode(P)]:
        with open(CELLS_DIR / name, encoding="utf-8", newline="") as fh:
            names |= {r["out_name"] for r in csv.DictReader(fh, delimiter="\t") if r["stack"] == "rcloud"}
    return names


def shown(p) -> str:
    """A path relative to the repository when it lies inside it, else absolute."""
    p = pathlib.Path(p).resolve()
    root = ROOT.resolve()
    return os.path.relpath(p, root) if root in p.parents else str(p)


def custody_args(P, spec=None) -> list:
    """The verify_cloud_custody.py arguments for the canon in force (see the module docstring)."""
    if mode(P) == "M":
        d = canon_root(P) / CUSTODY_DIR
        return ["--custody", shown(d), "--spec", spec or str(d / CUSTODY_SPEC)]
    return ["--custody", shown(pathlib.Path(P["cal"]) / "cloud")] + (["--spec", spec] if spec else [])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--custody-spec", default=None, help="a custody JSON passed to verify_cloud_custody.py as --spec")
    a = ap.parse_args(argv)
    P = load_paths()
    EXP = P["expected"]; OUT = P["output"] / "estimates"; REP = P["output"] / "compare_report.md"
    cloud = cloud_only(P)
    cmd = [sys.executable, str(ROOT / "tools/verify_cloud_custody.py"), *custody_args(P, a.custody_spec)]
    custody = subprocess.run(cmd, capture_output=True, text=True)
    (P["output"] / "logs").mkdir(parents=True, exist_ok=True); (P["output"] / "logs" / "custody.log").write_text(custody.stdout + custody.stderr)
    rows, bad = [], 0
    for g in sorted(EXP.glob("*.json")):
        local = OUT / g.name
        if not local.exists():
            status = "VERIFIED_NOT_RERUN" if (g.name in cloud and custody.returncode == 0) else "MISSING"
            if status == "MISSING": bad += 1
            rows.append((g.name, status, "")); continue
        d = compare(json.load(open(local)), json.load(open(g)))
        if d: bad += 1
        rows.append((g.name, "EQUAL" if not d else "DIFF", d[0].replace("|", "\\|") if d else ""))
    REP.write_text(f"# Compare report — {shown(OUT)} vs {shown(EXP)}\n\n| file | status | first difference |\n|---|---|---|\n" +
                   "\n".join(f"| {n} | {s} | {f} |" for n, s, f in rows) + f"\n\nCloud custody: {'OK' if custody.returncode == 0 else 'FAIL'} "
                   f"({shown(P['output'] / 'logs' / 'custody.log')})\n")
    print("\n".join(f"{s:20s} {n}" for n, s, _ in rows)); print("ALL_EQUAL" if not bad else f"PROBLEMS {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
