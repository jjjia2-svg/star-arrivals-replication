#!/usr/bin/env python3
"""fig_hops.py — schematic of who is exposed to an arrival: the star, one hop, two hops, and the
department roster drawn as a box that lies mostly OUTSIDE the network.

Why this figure exists. The supervisor's comment on the 2026-09-01 draft (sec2_data.tex, the exposure
paragraph): "I still think a reader will find it very difficult to understand one-hop and two-hop
... Would a diagram help?" — the third time the two-hop idea was queried. The 27 August comments
also read the two-hop incumbents as people inside the hiring department; for Yves Zénou's 2016
arrival at Monash, 94 of the 118 network members are NOT on the roster, which is why the roster
box here extends well outside the network circle. The existing Figure (fig_exposure_population.pdf)
is a two-circle count diagram and does not show hops.

The dots are illustrative (their number and placement carry no information). The only numbers
drawn are the four counts for the Zénou event, and they are read from the ledger written by
analysis/paper/gaps_zenou.py — nothing is typed by hand.

Reads:   output/paper/gaps_zenou.json   (keys roster, network, network_only, union, outside_network)
Writes:  output/paper/fig_hops.pdf      (+ fig_hops.png preview when --png is given)
Run:     python3 analysis/paper/fig_hops.py [--png]
Written 2026-09-10.
"""
import json, math, sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from analysis.lib.paths import load_paths

P = load_paths()
LEDGER = P["output"] / "paper" / "gaps_zenou.json"
OUT_PDF = P["output"] / "paper" / "fig_hops.pdf"
OUT_PNG = P["output"] / "paper" / "fig_hops.png"


def main(png: bool = False) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, Rectangle, FancyArrowPatch

    z = json.loads(LEDGER.read_text(encoding="utf-8"))
    roster, network, net_only = z["roster"], z["network"], z["network_only"]
    union, outside = z["union"], z["outside_network"]

    plt.rcParams.update({"font.family": "serif", "font.size": 9, "pdf.fonttype": 42})
    fig, ax = plt.subplots(figsize=(6.6, 4.5))
    fig.subplots_adjust(left=0.005, right=0.995, bottom=0.005, top=0.995)
    ax.set_aspect("equal"); ax.axis("off")
    ax.set_xlim(-4.65, 5.5); ax.set_ylim(-3.65, 3.1)

    grey, dark = "0.55", "0.15"
    # --- the star and its network -------------------------------------------------------------
    r1, r2, rnet = 1.0, 2.0, 2.45
    hop1 = [(r1 * math.cos(a), r1 * math.sin(a)) for a in
            [math.radians(d) for d in (20, 80, 140, 200, 260, 320)]]
    hop2 = []
    for i, (x1, y1) in enumerate(hop1):
        base = math.atan2(y1, x1)
        for da in (-0.28, 0.28):
            a = base + da
            hop2.append(((r2 * math.cos(a), r2 * math.sin(a)), (x1, y1)))
    ax.add_patch(Circle((0, 0), rnet, fill=False, ls="--", lw=1.0, ec=dark, zorder=1))
    for (x2, y2), (x1, y1) in hop2:
        ax.plot([x1, x2], [y1, y2], color=grey, lw=0.8, zorder=2)
    for x1, y1 in hop1:
        ax.plot([0, x1], [0, y1], color=grey, lw=0.8, zorder=2)
    ax.scatter([p[0][0] for p in hop2], [p[0][1] for p in hop2], s=22, facecolor="white",
               edgecolor=dark, lw=0.9, zorder=4)
    ax.scatter([p[0] for p in hop1], [p[1] for p in hop1], s=30, facecolor=grey,
               edgecolor=dark, lw=0.9, zorder=4)
    ax.scatter([0], [0], s=150, marker="*", facecolor="black", edgecolor="black", zorder=5)
    ax.annotate("star", (0, 0), xytext=(-0.02, -0.36), ha="center", va="top", fontsize=9)

    # --- people beyond two hops (link too weak to count: not in the network) -------------------
    beyond = [(-3.05, 1.35), (-3.2, -0.6), (-2.75, -1.95), (-1.3, -2.55), (0.9, -2.6)]
    ax.scatter([p[0] for p in beyond], [p[1] for p in beyond], s=18, facecolor="white",
               edgecolor=grey, lw=0.8, zorder=3)
    ax.text(-4.6, 2.75, "beyond two hops: link too weak,\nso not in the network",
            ha="left", va="top", fontsize=8, color=dark)

    # --- the department roster: a box lying mostly outside the network -------------------------
    bx0, bx1, by0, by1 = 1.05, 5.15, -1.55, 1.55
    ax.add_patch(Rectangle((bx0, by0), bx1 - bx0, by1 - by0, fill=False, lw=1.3, ec="black",
                           zorder=1))
    # roster members outside the network (right part of the box)
    ro = [(3.05, 1.05), (3.6, 0.35), (3.15, -0.5), (3.85, -1.05), (4.45, 0.95), (4.6, -0.25),
          (4.1, 0.15), (4.75, -1.15), (3.5, 1.3)]
    ax.scatter([p[0] for p in ro], [p[1] for p in ro], s=22, facecolor="white", edgecolor=dark,
               lw=0.9, zorder=4)
    ax.text((bx0 + bx1) / 2 + 0.55, by1 + 0.12, "department roster, arrival year",
            ha="center", va="bottom", fontsize=9)

    # --- the one-introduction arrow -----------------------------------------------------------
    (tx, ty), _ = hop2[2]          # the two-hop dot at about 64 degrees, top right of the star
    ax.add_patch(FancyArrowPatch((0.12, 0.12), (tx - 0.08, ty - 0.08), arrowstyle="-|>",
                                 mutation_scale=9, lw=0.8, ls=":", color=dark, zorder=3))
    ax.text(0.95, 2.6, "dotted arrow: a coauthor's coauthor\nis one introduction away",
            ha="left", va="bottom", fontsize=8, color=dark)

    # --- ring labels ---------------------------------------------------------------------------
    lead = dict(arrowstyle="-", color=grey, lw=0.7, shrinkA=2, shrinkB=4)
    ax.annotate("one hop: the star's coauthors", xy=hop1[2], xytext=(-4.6, 1.35),
                ha="left", va="center", fontsize=8, color=dark, arrowprops=lead)
    ax.annotate("two hops: their coauthors", xy=hop2[7][0], xytext=(-4.6, -1.45),
                ha="left", va="center", fontsize=8, color=dark, arrowprops=lead)
    ax.text(-1.55, -2.62, "dashed circle: the star's network,\neveryone within two hops",
            ha="center", va="top", fontsize=8, color=dark)

    # --- the counts for the Zénou event, from the ledger --------------------------------------
    box = (f"Yves Zénou, Monash, 2016\n"
           f"roster: {roster}\n"
           f"two-hop network: {network} ({net_only} not on the roster)\n"
           f"exposure population, either: {union}\n"
           f"roster members outside the network: {outside}")
    ax.text(5.45, -3.6, box, ha="right", va="bottom", fontsize=8,
            bbox=dict(boxstyle="round,pad=0.35", fc="white", ec=grey, lw=0.8))

    OUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PDF)
    if png:
        fig.savefig(OUT_PNG, dpi=160)
    print(f"wrote {OUT_PDF}" + (f" and {OUT_PNG}" if png else ""))


if __name__ == "__main__":
    main(png="--png" in sys.argv[1:])
