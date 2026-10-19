#!/usr/bin/env python3
"""fig_p3_afar.py — the Panel 3 (A_far) figure, fig_p3_afar.pdf, drawn from a Panel 3 ledger.

analysis/paper/ledger_p3afar.py builds data_numbers_p3afar.json and calls draw() with the ledger it has
just built; until R1 FIG567 (2026-10-16) the same drawing lines sat inline in it. Two trees:
  thesis_report (default)  the figure ledger_p3afar.py has always drawn (the legacy thesis_report tree
                           prints it): top row event-time coefficients, bottom row raw first-tie rates by
                           years since arrival, 6.6 x 4.9 in. The lines are moved here unchanged.
  base_2026_10_11          Figure 7 of the author's base tree, the 2026-10-03 redraw (original
                           sec4/fig_p3_afar.py + _two_row.py; verbatim copies in _vault_2026-10-03/sec4/, not shipped):
                           upper y label "Change in first-tie rate (pp)", both rows on one x-axis -6..5
                           with a light band and the key "not estimated" over ell = 5, one shared x label
                           "Years since arrival (-1 = year before arrival)", 6.6 x 4.7 in, TeX Gyre Pagella
                           (_fig567_style.py), and chemistry's upper panel clipped to CHEM_CLIP with an
                           arrowhead at every interval end that leaves it (change #7). Which ends leave is
                           data: the October answer (only chemistry's year-4 lower end) is pinned in a
                           manuscript test fixture (not shipped), and the base tree's caption says
                           so ("An arrow marks chemistry's year-four interval"); a point estimate outside
                           CHEM_CLIP is a STOP.
Every number drawn comes from the ledger: pairs, events_with_pairs, horizons_pp (est, se_pair) and
raw_rate_by_event_time_pp.

Standalone (redraw from a written ledger): python3 analysis/paper/fig_p3_afar.py
    [--tree {thesis_report,base_2026_10_11}] [--ledger F] [--out-dir D] [--font-dir D] [--test-font-fallback]
"""
import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from analysis.lib import canon
from analysis.lib.paths import load_paths
from analysis.paper._fig34_style import FontStop  # noqa: F401  (ledger_p3afar.py catches it)

P = load_paths()
LEDGER_PATH = P["output"] / "paper" / "data_numbers_p3afar.json"
OUT_FIG = P["output"] / "paper" / "fig_p3_afar.pdf"
NAME = "fig_p3_afar"
TREES = ("thesis_report", "base_2026_10_11")
FIELDS = [("econ", "Economics"), ("chemistry", "Chemistry"), ("math_stats", "Mathematics & Statistics")]
#: the y-range of the chemistry upper panel in the base tree's Figure 7 (original sec4/fig_p3_afar.py
#: CHEM_CLIP, a design constant of the 2026-10-03 figure)
CHEM_CLIP = (-2.6, 1.4)


def plotted_values(led):
    """Every number the figure draws, per field, keyed as in the ledger."""
    return {f: {"pairs": led[f]["pairs"], "events_with_pairs": led[f]["events_with_pairs"],
                "horizons_pp": led[f]["horizons_pp"],
                "raw_rate_by_event_time_pp": led[f]["raw_rate_by_event_time_pp"]}
            for f, _ in FIELDS}


def draw_thesis_report(led, out_fig):
    """The thesis_report figure: ledger_p3afar.py's figure lines, unchanged (one loop instead of the
    ledger loop; the in-memory ledger's int tau keys or a written ledger's string keys)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 3, figsize=(6.6, 4.9))
    for col, (f, title) in enumerate(FIELDS):
        d = led[f]
        # ---- figure, top: coefficients
        ax = axes[0, col]
        xs = [-1] + [h["ell"] for h in d["horizons_pp"]]
        ys = [0.0] + [h["est"] for h in d["horizons_pp"]]
        ses = [0.0] + [h["se_pair"] for h in d["horizons_pp"]]
        ax.axhline(0, color="0.5", lw=0.8); ax.axvline(-0.5, color="0.7", lw=0.8, ls="--")
        ax.errorbar(xs, ys, yerr=[1.96 * v for v in ses], fmt="o", color="black", ms=3.5, capsize=2.5, lw=0.9)
        ax.set_title(f"{title}\n{d['pairs']:,} pairs, {d['events_with_pairs']} events", fontsize=8)
        ax.set_xticks(xs); ax.tick_params(labelsize=7)
        # ---- figure, bottom: raw rates by event time (observable years)
        ax2 = axes[1, col]
        raw = {int(t): v for t, v in d["raw_rate_by_event_time_pp"].items()}
        taus = sorted(raw); vals = [raw[t] for t in taus]
        ax2.axvline(-0.5, color="0.7", lw=0.8, ls="--")
        ax2.plot(taus, vals, "o-", color="black", ms=3, lw=0.9)
        ax2.set_xticks(taus); ax2.tick_params(labelsize=7); ax2.set_ylim(bottom=0)
        ax2.set_xlabel("Years since arrival", fontsize=8)
    axes[0, 0].set_ylabel("Change in yearly first-tie\nprobability (pp)", fontsize=8)
    axes[1, 0].set_ylabel("Raw first-tie rate\n(percent per year)", fontsize=8)
    plt.tight_layout()
    os.makedirs(os.path.dirname(out_fig), exist_ok=True)
    plt.savefig(out_fig)
    plt.close(fig)


def base_panels(led):
    """The base tree's two-row panels (original sec4/fig_p3_afar.py), from the ledger."""
    from analysis.paper import _fig567_style as F
    panels = []
    for f, title in FIELDS:
        d = led[f]
        hz = sorted(d["horizons_pp"], key=lambda h: h["ell"])
        panels.append({"title": title, "n_units": d["pairs"], "events": d["events_with_pairs"],
                       "coefs": [(h["ell"], h["est"], h["se_pair"]) for h in hz],
                       "raw": F.raw_by_tau(d["raw_rate_by_event_time_pp"])})
    return panels


#: the arrows Figure 7's caption (sections/sec4_p3.tex) describes, per canon. October's numbers send chemistry's
#: year-four interval below the plot and its caption says so ("An arrow marks chemistry's year-four interval
#: (below the plot)"); under M no interval leaves CHEM_CLIP and the current tree's caption has no arrow sentence
#: (2026-10-18). The drawn arrows must be exactly these, or the caption no longer describes the figure.
CAPTION_ARROWS = {"october": [["chemistry", 4, "lower"]], "M": []}


def draw(led, tree="thesis_report", out_fig=None, *, font_fallback=False, font_search_dirs=None,
         font_cache=None, caption_check=True, mode=None) -> dict:
    """Draw fig_p3_afar.pdf for one tree from a Panel 3 ledger (the dict ledger_p3afar.py builds, or a
    written data_numbers_p3afar.json). Returns what was drawn (base tree: the drawn strings, the
    clipped interval ends [field, ell, end, value], the size, the font)."""
    if tree not in TREES:
        raise SystemExit(f"--tree: {tree!r} is not one of {TREES}")
    out_fig = OUT_FIG if out_fig is None else Path(out_fig)
    if tree == "thesis_report":
        draw_thesis_report(led, out_fig)
        return {"tree": tree, "pdf": str(out_fig)}
    from analysis.paper import _fig34_style as S
    from analysis.paper import _fig567_style as F
    col = [f for f, _ in FIELDS].index("chemistry")
    rc, font = F.font_rc(font_fallback=font_fallback, search_dirs=font_search_dirs, cache=font_cache)
    rec = F.draw_two_row(base_panels(led), "pairs", "Change in first-tie\nrate (pp)", out_fig, font, rc,
                         clip={col: CHEM_CLIP})
    rec["clipped"] = [[FIELDS[c][0], ell, end, v] for c, ell, end, v in rec["clipped"]]
    arrows, want = [c[:3] for c in rec["clipped"]], CAPTION_ARROWS[mode or canon.mode()]
    if caption_check and arrows != want:
        out_fig.unlink(missing_ok=True)
        raise SystemExit(f"STOP fig567 CAPTION_ARROWS: Figure 7 draws arrows {arrows}; the caption "
                         f"(sections/sec4_p3.tex) describes {want}: change the caption with the figure")
    return {"tree": tree, "pdf": str(out_fig), "font": S.public_font(font), **rec}


def generate(tree="thesis_report", ledger=None, out_dir=None, **font_kw) -> dict:
    """Read a written Panel 3 ledger and draw <out_dir>/fig_p3_afar.pdf."""
    ledger = LEDGER_PATH if ledger is None else Path(ledger)
    if not ledger.exists():
        sys.exit(f"missing {ledger} — run: python3 analysis/paper/ledger_p3afar.py")
    out_fig = (OUT_FIG.parent if out_dir is None else Path(out_dir)) / f"{NAME}.pdf"
    return draw(json.loads(ledger.read_text()), tree, out_fig, **font_kw)


def main(argv=None):
    from analysis.paper import _fig34_style as S
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tree", choices=TREES, default="thesis_report")
    ap.add_argument("--ledger", type=Path, default=None, help=f"default {LEDGER_PATH}")
    ap.add_argument("--out-dir", type=Path, default=None, help=f"default {OUT_FIG.parent}")
    ap.add_argument("--font-dir", type=Path, action="append",
                    help="base tree: look for TeX Gyre Pagella only here (default: the pinned TeX layer)")
    ap.add_argument("--test-font-fallback", action="store_true",
                    help="TESTS ONLY: base tree drawn in DejaVu Serif when Pagella is absent")
    a = ap.parse_args(argv)
    try:
        rec = generate(a.tree, a.ledger, a.out_dir, font_fallback=a.test_font_fallback,
                       font_search_dirs=a.font_dir)
    except S.FontStop as e:
        print(e, file=sys.stderr)
        raise SystemExit(2)
    print("wrote", rec["pdf"], "| clipped:", rec.get("clipped"))


if __name__ == "__main__":
    main()
