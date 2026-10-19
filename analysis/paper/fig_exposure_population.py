#!/usr/bin/env python3
"""fig_exposure_population.py — two-circle exposure-population diagram (economics, sec2_data.tex).

Reproduces the composition of thesis_report/figures/fig_exposure_population.pdf: a solid ellipse
(the department roster in the year of arrival) overlapping a dashed ellipse (the star's pre-arrival
coauthorship network within two hops); the three regions are labelled with incumbent-event relation
counts (roster only / both / network only), and a caption-style line under the diagram gives the
totals. No number here is typed by hand: every count comes from output/paper/data_numbers_main.json
(`econ_relations`, `econ_persons`, `econ_events`), written by analysis/paper/ledger_main.py — run
that first if data_numbers_main.json is missing.

This is a fresh script (no surviving thesis generator for this figure), built to match what the
thesis PDF shows, not a byte-identical port: `pdftoppm -r 150` the original and this output and
compare panel-by-panel (see the M2/T5 report for the actual comparison).

Reads:   output/paper/data_numbers_main.json
Writes:  output/paper/fig_exposure_population.pdf

Written 2026-08-24 for the star_arrivals_replication repo (M2/T5).
Run:  python3 analysis/paper/fig_exposure_population.py
"""
import json, sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from analysis.lib.paths import load_paths

P = load_paths()
LEDGER_PATH = P["output"] / "paper" / "data_numbers_main.json"
OUT_FIG = P["output"] / "paper" / "fig_exposure_population.pdf"

if not LEDGER_PATH.exists():
    sys.exit(f"missing {LEDGER_PATH} — run: python3 analysis/paper/ledger_main.py")

LEDGER = json.loads(LEDGER_PATH.read_text())

# Every number this figure draws, keyed exactly as in the ledger, for a source == displayed check.
PLOTTED_VALUES = {
    "econ_relations": LEDGER["econ_relations"],
    "econ_persons": LEDGER["econ_persons"],
    "econ_events": LEDGER["econ_events"],
}


def build_figure():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Ellipse

    r = PLOTTED_VALUES["econ_relations"]
    dept_only, network_only, both, total = r["dept_only"], r["network"], r["both"], r["total"]
    persons, events = PLOTTED_VALUES["econ_persons"], PLOTTED_VALUES["econ_events"]

    fig, ax = plt.subplots(figsize=(6.6, 4.6))
    cx = 1.05  # half the centre-to-centre distance between the two ellipses
    ax.add_patch(Ellipse((-cx, 0), width=4.4, height=3.0, fill=False, lw=1.8, ls="-", color="black"))
    ax.add_patch(Ellipse((cx, 0), width=4.4, height=3.0, fill=False, lw=1.8, ls="--", color="black"))

    ax.text(-cx - 0.85, 1.85, "Department roster\nat arrival", ha="center", va="bottom", fontsize=10)
    ax.text(cx + 0.85, 1.85, "Pre-arrival coauthorship\nnetwork (two hops)", ha="center", va="bottom", fontsize=10)

    ax.text(-1.55, 0.18, f"{dept_only:,}", ha="center", va="center", fontsize=15)
    ax.text(-1.55, -0.32, "roster only", ha="center", va="center", fontsize=9)
    ax.text(0, 0.18, f"{both:,}", ha="center", va="center", fontsize=15)
    ax.text(0, -0.32, "both", ha="center", va="center", fontsize=9)
    ax.text(1.55, 0.18, f"{network_only:,}", ha="center", va="center", fontsize=15)
    ax.text(1.55, -0.32, "network only", ha="center", va="center", fontsize=9)

    ax.text(0, -2.2, f"Total: {total:,} incumbent–event relations, {persons:,} incumbents, {events} events",
            ha="center", va="center", fontsize=10.5)

    ax.set_xlim(-4.2, 4.2)
    ax.set_ylim(-2.65, 2.55)
    ax.set_aspect("equal")
    ax.axis("off")
    plt.tight_layout()
    OUT_FIG.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT_FIG)
    print("wrote", OUT_FIG, "|", PLOTTED_VALUES)


if __name__ == "__main__":
    build_figure()
