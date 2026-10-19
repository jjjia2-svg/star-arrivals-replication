#!/usr/bin/env python3
"""fig_p2.py — Panel 2, three disciplines side by side, matching fig_p3_afar.pdf's layout.

Top row: event-time coefficients (the change in the yearly probability of a first coauthorship
with the star, in percentage points), ell = 0..4, with the year before arrival (ell = -1) as
the reference at zero; bars are 95 percent confidence intervals, standard errors clustered by
incumbent. Pre-arrival placebo coefficients are zero by construction in this panel and are
omitted (Section 3), exactly as in the Panel 3 figure.
Bottom row: the raw first-tie-with-star rate, without any comparison group, by years since
arrival, on observable relation-years only (calendar year <= 2024) — computed by the ledger
from the frozen becoming frames.

No number here is typed by hand: everything comes from output/paper/data_numbers_p1p2.json
(analysis/paper/ledger_p1p2.py — run it first).

Reads:   output/paper/data_numbers_p1p2.json
Writes:  output/paper/fig_p2.pdf

Written 2026-08-30 for the Panel 1 + Panel 2 exhibits.
R1 FIG567 (2026-10-16): --tree {thesis_report (default), base_2026_10_11}. The default draws exactly the
figure above (the legacy thesis_report tree prints it). base_2026_10_11 draws Figure 6 of the author's
base tree, the 2026-10-03 redraw (original sec4/fig_p2.py + _two_row.py; verbatim copies in
_vault_2026-10-03/sec4/, not shipped): upper y label "Change in first-tie rate with the star (pp)", both rows on one
x-axis -6..5 with a light band and the key "not estimated" over ell = 5, labels on -5, -3, -1, 0..5 (lower
row only), one shared x label "Years since arrival (-1 = year before arrival)", 6.6 x 4.7 in, TeX Gyre
Pagella (analysis/paper/_fig567_style.py).
Run:  python3 analysis/paper/fig_p2.py [--tree {thesis_report,base_2026_10_11}] [--ledger F] [--out-dir D]
"""
import argparse
import json, sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from analysis.lib.paths import load_paths

P = load_paths()
LEDGER_PATH = P["output"] / "paper" / "data_numbers_p1p2.json"
OUT_FIG = P["output"] / "paper" / "fig_p2.pdf"
NAME = "fig_p2"
TREES = ("thesis_report", "base_2026_10_11")

FIELDS = [("p2_econ", "Economics"), ("p2_chemistry", "Chemistry"),
          ("p2_math_stats", "Mathematics & Statistics")]


def plotted_values(ledger):
    """Every number this figure draws, keyed exactly as in the ledger (nested per cell)."""
    return {cell: {"horizons_pp": ledger[cell]["horizons_pp"],
                   "raw_rate_by_event_time_pp": ledger[cell]["raw_rate_by_event_time_pp"],
                   "relations": ledger[cell]["relations"],
                   "events": ledger[cell]["events"]}
            for cell, _ in FIELDS}


LEDGER = json.loads(LEDGER_PATH.read_text()) if LEDGER_PATH.exists() else None
PLOTTED_VALUES = plotted_values(LEDGER) if LEDGER is not None else {}


def missing(ledger):
    return f"missing {ledger} — run: python3 analysis/paper/ledger_p1p2.py"


def build_figure(values=None, out_fig=None):
    """The thesis_report figure (drawing unchanged since 2026-08-30)."""
    values = PLOTTED_VALUES if values is None else values
    out_fig = OUT_FIG if out_fig is None else Path(out_fig)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 3, figsize=(6.6, 4.9))
    for col, (cell, title) in enumerate(FIELDS):
        d = values[cell]
        # ---- top: coefficients (placebos are structural zeros, omitted — as in fig_p3_afar)
        ax = axes[0, col]
        xs = [-1] + [h["ell"] for h in d["horizons_pp"]]
        ys = [0.0] + [h["est"] for h in d["horizons_pp"]]
        ses = [0.0] + [h["se_person"] for h in d["horizons_pp"]]
        ax.axhline(0, color="0.5", lw=0.8)
        ax.axvline(-0.5, color="0.7", lw=0.8, ls="--")
        ax.errorbar(xs, ys, yerr=[1.96 * v for v in ses],
                    fmt="o", color="black", ms=3.5, capsize=2.5, lw=0.9)
        ax.set_title(f"{title}\n{d['relations']:,} relations, {d['events']} events", fontsize=8)
        ax.set_xticks(xs)
        ax.tick_params(labelsize=7)
        # ---- bottom: raw first-tie-with-star rate by event time (observable years)
        ax2 = axes[1, col]
        taus = sorted(int(t) for t in d["raw_rate_by_event_time_pp"])
        vals = [d["raw_rate_by_event_time_pp"][str(t)] if str(t) in d["raw_rate_by_event_time_pp"]
                else d["raw_rate_by_event_time_pp"][t] for t in taus]
        ax2.axvline(-0.5, color="0.7", lw=0.8, ls="--")
        ax2.plot(taus, vals, "o-", color="black", ms=3, lw=0.9)
        ax2.set_xticks(taus)
        ax2.tick_params(labelsize=7)
        ax2.set_ylim(bottom=0)
        ax2.set_xlabel("Years since arrival", fontsize=8)
    axes[0, 0].set_ylabel("Change in yearly first-tie\nprobability with the star (pp)", fontsize=8)
    axes[1, 0].set_ylabel("Raw first-tie rate\n(percent per year)", fontsize=8)
    plt.tight_layout()
    out_fig.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_fig)
    print("wrote", out_fig)


def base_panels(values):
    """The base tree's two-row panels (original sec4/fig_p2.py), from the ledger values."""
    from analysis.paper import _fig567_style as F
    panels = []
    for cell, title in FIELDS:
        d = values[cell]
        hz = sorted(d["horizons_pp"], key=lambda h: h["ell"])
        panels.append({"title": title, "n_units": d["relations"], "events": d["events"],
                       "coefs": [(h["ell"], h["est"], h["se_person"]) for h in hz],
                       "raw": F.raw_by_tau(d["raw_rate_by_event_time_pp"])})
    return panels


def generate(tree="thesis_report", ledger=None, out_dir=None, *, font_fallback=False,
             font_search_dirs=None, font_cache=None) -> dict:
    """Draw <out_dir>/fig_p2.pdf for one tree from a p1p2 ledger. Returns what was drawn (base tree:
    the drawn strings, the size, the font)."""
    if tree not in TREES:
        raise SystemExit(f"--tree: {tree!r} is not one of {TREES}")
    ledger = LEDGER_PATH if ledger is None else Path(ledger)
    if not ledger.exists():
        sys.exit(missing(ledger))
    values = plotted_values(json.loads(ledger.read_text()))
    out_fig = (OUT_FIG.parent if out_dir is None else Path(out_dir)) / f"{NAME}.pdf"
    if tree == "thesis_report":
        build_figure(values, out_fig)
        return {"tree": tree, "pdf": str(out_fig)}
    from analysis.paper import _fig34_style as S
    from analysis.paper import _fig567_style as F
    rc, font = F.font_rc(font_fallback=font_fallback, search_dirs=font_search_dirs, cache=font_cache)
    rec = F.draw_two_row(base_panels(values), "relations", "Change in first-tie rate\nwith the star (pp)",
                         out_fig, font, rc)
    print(f"wrote {out_fig} (base tree Figure 6); font {font['family']}"
          f"{' (TEST FALLBACK)' if font['fallback'] else ''}")
    return {"tree": tree, "pdf": str(out_fig), "font": S.public_font(font), **rec}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tree", choices=TREES, default="thesis_report",
                    help="thesis_report (default; the pre-FIG567 figure) or base_2026_10_11 (Figure 6)")
    ap.add_argument("--ledger", type=Path, default=None, help=f"default {LEDGER_PATH}")
    ap.add_argument("--out-dir", type=Path, default=None, help=f"default {OUT_FIG.parent}")
    ap.add_argument("--font-dir", type=Path, action="append",
                    help="base tree: look for TeX Gyre Pagella only here (default: the pinned TeX layer)")
    ap.add_argument("--test-font-fallback", action="store_true",
                    help="TESTS ONLY: base tree drawn in DejaVu Serif when Pagella is absent")
    a = ap.parse_args(argv)
    if a.tree == "thesis_report" and a.ledger is None and a.out_dir is None:
        if LEDGER is None:                       # the no-flag run, exactly as before
            sys.exit(missing(LEDGER_PATH))
        build_figure()
        return
    from analysis.paper import _fig34_style as S
    try:
        generate(a.tree, a.ledger, a.out_dir, font_fallback=a.test_font_fallback, font_search_dirs=a.font_dir)
    except S.FontStop as e:
        print(e, file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
