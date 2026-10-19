#!/usr/bin/env python3
"""fig_p1.py — Panel 1 event-time coefficient plot, three disciplines side by side (union channel).

One row of three panels, matching fig_p3_afar.pdf's visual style (same figure grammar as the
figure block of ledger_p3afar.py: black point-and-CI errorbars, dashed arrival line, per-panel
sample-size title). Unlike Panel 3, this panel's pre-arrival placebo coefficients are REAL and
are shown, as open circles, at ell = -5..-2; ell = -1 is the reference at zero; filled circles
at ell = 0..5 are the post-arrival coefficients (the average change in log output among
switching relations at their own dose). Bars are 95 percent confidence intervals with standard
errors clustered by incumbent.

No number here is typed by hand: everything comes from output/paper/data_numbers_p1p2.json
(analysis/paper/ledger_p1p2.py — run it first).

Reads:   output/paper/data_numbers_p1p2.json
Writes:  output/paper/fig_p1.pdf

Written 2026-08-30 for the Panel 1 + Panel 2 exhibits.
R1 FIG567 (2026-10-16): --tree {thesis_report (default), base_2026_10_11}. The default draws exactly the
figure above (the legacy thesis_report tree prints it). base_2026_10_11 draws Figure 5 of the author's
base tree, the 2026-10-03 redraw (original sec4/fig_p1.py; verbatim copy in _vault_2026-10-03/sec4/, not shipped):
y label "Change in log output (at the doses incumbents hold)", a third title line "joint placebo p = ..."
(the ledger's p_joint_placebo_person, 3 dp), grey bands over the zero-dose-only horizons (-5, -4 and 4, 5)
with the key "zero-dose relations only", one shared x label "Years since arrival (-1 = year before
arrival)", labels on -5, -3, -1, 0..5, 6.6 x 2.7 in, TeX Gyre Pagella (analysis/paper/_fig567_style.py).
Run:  python3 analysis/paper/fig_p1.py [--tree {thesis_report,base_2026_10_11}] [--ledger F] [--out-dir D]
"""
import argparse
import json, sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from analysis.lib.paths import load_paths

P = load_paths()
LEDGER_PATH = P["output"] / "paper" / "data_numbers_p1p2.json"
OUT_FIG = P["output"] / "paper" / "fig_p1.pdf"
NAME = "fig_p1"
TREES = ("thesis_report", "base_2026_10_11")

FIELDS = [("p1_econ", "Economics"), ("p1_chemistry", "Chemistry"),
          ("p1_math_stats", "Mathematics & Statistics")]


def plotted_values(ledger):
    """Every number this figure draws, keyed exactly as in the ledger (nested per cell);
    p_joint_placebo_person is drawn by the base tree's Figure 5 only."""
    return {cell: {"horizons": ledger[cell]["horizons"],
                   "placebos": ledger[cell]["placebos"],
                   "relations": ledger[cell]["relations"],
                   "events": ledger[cell]["events"],
                   "p_joint_placebo_person": ledger[cell]["p_joint_placebo_person"]}
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

    fig, axes = plt.subplots(1, 3, figsize=(6.6, 2.6))
    for col, (cell, title) in enumerate(FIELDS):
        d = values[cell]
        pl = sorted(d["placebos"], key=lambda h: h["ell"])
        ax = axes[col]
        ax.axhline(0, color="0.5", lw=0.8)
        ax.axvline(-0.5, color="0.7", lw=0.8, ls="--")
        # real pre-arrival placebos (open circles), ell = -5..-2
        ax.errorbar([h["ell"] for h in pl], [h["est"] for h in pl],
                    yerr=[1.96 * h["se_person"] for h in pl],
                    fmt="o", color="black", mfc="white", ms=3.5, capsize=2.5, lw=0.9)
        # reference year and post-arrival coefficients (filled circles)
        xs = [-1] + [h["ell"] for h in d["horizons"]]
        ys = [0.0] + [h["est"] for h in d["horizons"]]
        ses = [0.0] + [h["se_person"] for h in d["horizons"]]
        ax.errorbar(xs, ys, yerr=[1.96 * v for v in ses],
                    fmt="o", color="black", ms=3.5, capsize=2.5, lw=0.9)
        ax.set_title(f"{title}\n{d['relations']:,} relations, {d['events']} events", fontsize=8)
        ax.set_xticks([h["ell"] for h in pl] + xs)
        ax.tick_params(labelsize=7)
        ax.set_xlabel("Years since arrival", fontsize=8)
    axes[0].set_ylabel("Change in log output\n(at switchers' dose)", fontsize=8)
    plt.tight_layout()
    out_fig.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_fig)
    print("wrote", out_fig)


def generate(tree="thesis_report", ledger=None, out_dir=None, *, font_fallback=False,
             font_search_dirs=None, font_cache=None) -> dict:
    """Draw <out_dir>/fig_p1.pdf for one tree from a p1p2 ledger. Returns what was drawn (base tree:
    the drawn strings, the p-values as printed, the band ells, the size, the font)."""
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
    rec = F.draw_p1(values, FIELDS, out_fig, font, rc)
    print(f"wrote {out_fig} (base tree Figure 5); font {font['family']}"
          f"{' (TEST FALLBACK)' if font['fallback'] else ''}")
    return {"tree": tree, "pdf": str(out_fig), "font": S.public_font(font), **rec}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tree", choices=TREES, default="thesis_report",
                    help="thesis_report (default; the pre-FIG567 figure) or base_2026_10_11 (Figure 5)")
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
