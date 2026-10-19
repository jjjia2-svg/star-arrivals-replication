"""Copy the gold-standard result JSONs into analysis/expected/ and write its MANIFEST + SOURCES.
Run once: python3 tools/freeze_expected.py   (idempotent; refuses to overwrite a file whose hash changed)

Since the 2026-08-28 freeze (author approved the caliber rebuild; decision record not shipped) the golds are the caliber-rebuild estimates,
frozen in THIS repository under data/cal2026-08-28/estimates/ — sources starting with
``cal2026-08-28/`` resolve against <repo>/data. The pre-caliber golds (paper v2026-08-22) are
kept in the author's private repository (tag ``pre-cal-freeze``); the four cloud cells' custody chain for the new golds is
data/cal2026-08-28/cloud/ (tools/verify_cloud_custody.py)."""
import hashlib, shutil, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from analysis.lib.paths import load_paths

# (dest name in analysis/expected, source: cal2026-08-28/... = relative to <repo>/data)
EXPECTED = [
    ("P1_econ_fnfix.json",                  "cal2026-10/estimates/P1_econ_fnfix.json"),
    ("P1_fnfix_chemistry.json",             "cal2026-10/estimates/P1_fnfix_chemistry.json"),
    ("P1_fnfix_math_stats.json",            "cal2026-10/estimates/P1_fnfix_math_stats.json"),
    ("P1_econ_fnfix_old79.json",            "cal2026-10/estimates/P1_econ_fnfix_old79.json"),
    ("P1_econ_fnfix_new37.json",            "cal2026-10/estimates/P1_econ_fnfix_new37.json"),
    ("P2_econ_fnfix.json",                  "cal2026-10/estimates/P2_econ_fnfix.json"),
    ("P2_fnfix_chemistry.json",             "cal2026-10/estimates/P2_fnfix_chemistry.json"),
    ("P2_fnfix_math_stats.json",            "cal2026-10/estimates/P2_fnfix_math_stats.json"),
    ("P3_fnfix_math_stats.json",            "cal2026-10/estimates/P3_fnfix_math_stats.json"),
    ("P1evcl_econ.json",                    "cal2026-10/estimates/P1evcl_econ.json"),
    ("P1evcl_chemistry.json",               "cal2026-10/estimates/P1evcl_chemistry.json"),
    ("P1evcl_math_stats.json",              "cal2026-10/estimates/P1evcl_math_stats.json"),
    ("P2evcl_econ.json",                    "cal2026-10/estimates/P2evcl_econ.json"),
    ("P2evcl_chemistry.json",               "cal2026-10/estimates/P2evcl_chemistry.json"),
    ("P2evcl_math_stats.json",              "cal2026-10/estimates/P2evcl_math_stats.json"),
    ("P3evcl_math_stats.json",              "cal2026-10/estimates/P3evcl_math_stats.json"),
    ("P3lb_econ_A_far.json",                "cal2026-10/estimates/P3lb_econ_A_far.json"),
    ("P3lb_chemistry_A_far.json",           "cal2026-10/estimates/P3lb_chemistry_A_far.json"),
    ("P3lb_math_stats_A_far.json",          "cal2026-10/estimates/P3lb_math_stats_A_far.json"),
    ("P3pos_math_stats_A_far.json",         "cal2026-10/estimates/P3pos_math_stats_A_far.json"),
    ("P3med_math_stats_A_far.json",         "cal2026-10/estimates/P3med_math_stats_A_far.json"),
    ("P3pos_chemistry_A_far.json",          "cal2026-10/estimates/P3pos_chemistry_A_far.json"),
    ("P3med_chemistry_A_far.json",          "cal2026-10/estimates/P3med_chemistry_A_far.json"),
    ("P3pos_econ_A_far.json",               "cal2026-10/estimates/P3pos_econ_A_far.json"),
    ("P3med_econ_A_far.json",               "cal2026-10/estimates/P3med_econ_A_far.json"),
    ("P3_econ_fnfix.json",                  "cal2026-10/cloud/fetch/out/P3_econ_fnfix.json"),
    ("P3_fnfix_chemistry.json",             "cal2026-10/cloud/fetch/out/P3_fnfix_chemistry.json"),
    ("P3evcl_econ.json",                    "cal2026-10/cloud/fetch/out/P3evcl_econ.json"),
    ("P3evcl_chemistry.json",               "cal2026-10/cloud/fetch/out/P3evcl_chemistry.json"),
]

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def sources_md() -> str:
    """The text of analysis/expected/SOURCES.md: where each recorded estimate came from."""
    return (
        "# Recorded estimates of the October 2026 version \u2014 where each file came from\n\n"
        f"These {len(EXPECTED)} files are the recorded estimates of the October 2026 version of the data "
        "(184 events), which\n"
        "`config/paths_october.yaml` selects. The recorded estimates of the report as submitted are in\n"
        "`data/report/expected/`.\n\n"
        "| file | source |\n|---|---|\n"
        + "".join(f"| {d} | `data/{r}` |\n" for d, r in EXPECTED)
        + "\nP3pos_*/P3med_* (six files) are the Panel 3 cells on the dose-above-zero cut (`pos`, the report's\n"
        "Panel 3) and on the former median cut (`med`, a control equal to P3lb_* except its label). They were\n"
        "first frozen from `data/robustness_afar_cuts_2026-08-30/estimates/` and re-estimated on the October\n"
        "data with the other cells. The four large cells come from the October cloud run\n"
        "(`data/cal2026-10/cloud/`). Never edit these files; compare new runs against them.\n")

def main():
    p = load_paths(); dst = p["expected"]; dst.mkdir(parents=True, exist_ok=True)
    lines = []
    for dest, rel in EXPECTED:
        src = (p["repo_root"] / "data" / rel) if (p["repo_root"] / "data" / rel).exists() \
            else (p["legacy_v2_output"] / rel)   # any path frozen under <repo>/data resolves there first
        if not src.exists(): sys.exit(f"MISSING source: {src}")
        out = dst / dest
        if out.exists() and sha(out) != sha(src): sys.exit(f"REFUSE: {dest} exists with a different hash; gold standards are frozen")
        shutil.copy2(src, out)
        lines.append(f"{sha(out)}  {dest}")
    (dst / "MANIFEST.sha256").write_text("\n".join(lines) + "\n")
    (dst / "SOURCES.md").write_text(sources_md(), encoding="utf-8")
    print(f"froze {len(EXPECTED)} files into {dst}")

if __name__ == "__main__": main()
