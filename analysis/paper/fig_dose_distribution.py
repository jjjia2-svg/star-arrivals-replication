#!/usr/bin/env python3
"""fig_dose_distribution.py — grouped bar chart, similarity-dose distribution by discipline
(sec2_data.tex, thesis_report/figures/fig_dose_distribution.pdf).

Reproduces the composition of the thesis figure: for each discipline (economics, chemistry,
mathematics & statistics), the share of incumbent-event relations falling in each of the ten
similarity-dose bins (width 0.1, [0.0,0.1) .. [0.9,1.0]), as three side-by-side bar series with
one hatch pattern per discipline. A footnote line under the chart carries the caption's exclusion
note (relations with no pre-arrival portfolio, hence no dose, are dropped from the denominator).
No number here is typed by hand: every count comes from output/paper/data_numbers_main.json
(`{d}_dose_bins_pct`, `{d}_relations`, `{d}_dose_na_relations`), written by
analysis/paper/ledger_main.py — run that first if data_numbers_main.json is missing.

This is a fresh script (no surviving thesis generator for this figure), built to match what the
thesis PDF shows, not a byte-identical port: `pdftoppm -r 150` the original and this output and
compare panel-by-panel (see the M2/T5 report for the actual comparison).

Reads:   output/paper/data_numbers_main.json
Writes:  output/paper/fig_dose_distribution.pdf

Written 2026-08-24 for the star_arrivals_replication repo (M2/T5).
Run:  python3 analysis/paper/fig_dose_distribution.py
"""
import json, sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from analysis.lib.paths import load_paths

P = load_paths()
LEDGER_PATH = P["output"] / "paper" / "data_numbers_main.json"
OUT_FIG = P["output"] / "paper" / "fig_dose_distribution.pdf"

if not LEDGER_PATH.exists():
    sys.exit(f"missing {LEDGER_PATH} — run: python3 analysis/paper/ledger_main.py")

LEDGER = json.loads(LEDGER_PATH.read_text())

DISCIPLINES = [
    ("econ", "Economics", "white", "///"),
    ("chem", "Chemistry", "0.65", ""),
    ("math", "Mathematics & Statistics", "white", "..."),
]

# Every number this figure draws or annotates, keyed exactly as in the ledger.
PLOTTED_VALUES = {}
for _d, *_ in DISCIPLINES:
    PLOTTED_VALUES[f"{_d}_dose_bins_pct"] = LEDGER[f"{_d}_dose_bins_pct"]
    PLOTTED_VALUES[f"{_d}_relations"] = LEDGER[f"{_d}_relations"]
    PLOTTED_VALUES[f"{_d}_dose_na_relations"] = LEDGER[f"{_d}_dose_na_relations"]


def build_figure():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    bins = [f"{i/10:.1f}-{(i+1)/10:.1f}" for i in range(10)]
    x = np.arange(10)
    width = 0.26

    fig, ax = plt.subplots(figsize=(7.4, 4.4))
    for i, (d, label, color, hatch) in enumerate(DISCIPLINES):
        pct = PLOTTED_VALUES[f"{d}_dose_bins_pct"]
        vals = [pct.get(str(b), 0.0) for b in range(10)]
        ax.bar(x + (i - 1) * width, vals, width=width, label=label, color=color,
               edgecolor="black", hatch=hatch, linewidth=0.8)

    ax.set_xticks(x)
    ax.set_xticklabels(bins, rotation=45, ha="right")
    ax.set_xlabel("Similarity dose bin")
    ax.set_ylabel("Share of incumbent-event relations (%)")
    ax.legend(frameon=True, fontsize=9, loc="upper right")

    obs = {d: PLOTTED_VALUES[f"{d}_relations"]["total"] - PLOTTED_VALUES[f"{d}_dose_na_relations"]
           for d, *_ in DISCIPLINES}
    note = (f"Observed dose: {obs['econ']:,} economics, {obs['chem']:,} chemistry, {obs['math']:,} mathematics relations.\n"
            f"{PLOTTED_VALUES['chem_dose_na_relations']} chemistry and {PLOTTED_VALUES['math_dose_na_relations']} "
            "mathematics relations excluded (no pre-arrival portfolio).")
    fig.text(0.5, 0.01, note, ha="center", va="bottom", fontsize=7.5)

    plt.tight_layout(rect=(0, 0.11, 1, 1))
    OUT_FIG.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT_FIG)
    print("wrote", OUT_FIG, "|", obs)


if __name__ == "__main__":
    build_figure()
