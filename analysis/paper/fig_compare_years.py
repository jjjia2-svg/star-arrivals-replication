#!/usr/bin/env python3
"""fig_compare_years.py — Figure 3: which two years each Model 1 coefficient compares (R1 N9, W1-FIG34).

Data-driven port of the original drawing script figA.py (third version, round 2, the "mirror
staircase"; verbatim copy and md5 in analysis/paper/_vault_2026-10-03/, not shipped). Running example: Yves Zénou, Monash economics,
arrival 2016, base year 2015. One row per horizon k (horizon 1 on top): a solid effect arrow from
2015 to 2015+k and, for k <= 4, a dashed placebo arrow from 2015 to 2015-k. An arrow gets an open
head when that coefficient has zero-dose relations only as comparisons (no not-yet relation left).

What changed against figA.py:
  - which coefficients are zero-dose-only is computed from the arrivals in the carried ledger
    (events_by_school_econ, summed by year) with the same pool rule as Figure 4, instead of the
    window rule alone plus the hand-typed ECON_ARRIVALS; asserts that encoded the October answer
    (open heads 2011/2012/2020/2021, the 21/11/3 pool sizes) are recomputations, and the October
    values are pinned in tests/fixtures/r1_paper/fig34_october.json (not shipped);
  - the shared grid comes from analysis/paper/_fig34_style.py (figA.py read figB.py's source text
    by regex); font TeX Gyre Pagella from the pinned TeX layer (STOP when absent);
  - no caption file (the caption lives in sec3_strategy.tex).
No count is drawn (author decision 2026-10-03: no counts and no zero-dose rotation in this figure).

Reads:   output/paper/data_numbers_carried.json  (key events_by_school_econ; run ledger_carried.py first)
Writes:  output/paper/fig_compare_years.pdf, output/paper/fig_compare_years.json
Run:     python3 analysis/paper/fig_compare_years.py [--ledger F] [--out-dir D]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from analysis.lib.paths import load_paths  # noqa: E402
from analysis.paper import _fig34_style as S  # noqa: E402

NAME = "fig_compare_years"
P = load_paths()
LEDGER = P["output"] / "paper" / "data_numbers_carried.json"
OUT_DIR = P["output"] / "paper"
KEY_TEXT = S.ZERO_DOSE_TERM + " only"     # same words as Figure 4's row "zero-dose relations"

PAIR = {S.BASE - k: S.BASE + k for k in range(1, S.N_PLACEBOS + 1)}     # placebo -> effect
assert PAIR == {2014: 2016, 2013: 2017, 2012: 2018, 2011: 2019}
assert all(S.BASE - p == e - S.BASE for p, e in PAIR.items())           # symmetric
assert set(S.EFFECT_YEARS) - set(PAIR.values()) == {2020, 2021}        # no partner
assert [S.ell(p) for p in sorted(PAIR, reverse=True)] == [-2, -3, -4, -5]


# =====================================================================================
# 1. Facts: rows, and which coefficients compare with zero-dose relations only
# =====================================================================================
def build(arrivals: dict) -> dict:
    zero_dose_only = sorted(
        [e for e in S.EFFECT_YEARS if not S.not_yet_pool(arrivals, e, S.M1_LO, S.M1_HI)]
        + [p for p in PAIR if not S.not_yet_pool(arrivals, PAIR[p], S.M1_LO, S.M1_HI, also_year=p)])
    # window rule, whatever the ledger: effects 4 and 5 (2020, 2021) need a later star with a row in
    # 2015, i.e. arriving by 2020 and after 2020/2021 -> impossible; placebos -4 and -5 (2012, 2011)
    # need a star arriving after 2018/2019 with a row in 2012/2011 (by 2017/2016) -> impossible
    assert {2011, 2012, 2020, 2021} <= set(zero_dose_only), zero_dose_only
    rows = [{"k": k, "effect": S.BASE + k, "placebo": S.BASE - k if k <= S.N_PLACEBOS else None}
            for k in range(1, S.N_EFFECTS + 1)]
    assert [r["k"] for r in rows] == [1, 2, 3, 4, 5, 6] and [r["placebo"] for r in rows[4:]] == [None, None]
    arrows = []
    for r in rows:
        for kind in ("effect", "placebo"):
            year = r[kind]
            if year is None:
                continue
            arrows.append({"row": r["k"], "kind": kind, "from": S.BASE, "to": year,
                           "open_head": year in zero_dose_only})
    ell_labels = {str(y): S.mn(S.ell(y)) for y in range(2011, 2022)}
    assert list(ell_labels.values()) == ["−5", "−4", "−3", "−2", "−1", "0", "1", "2", "3", "4", "5"]
    return {"cohort": S.G, "base": S.BASE,
            "arrivals_by_year": {str(y): n for y, n in arrivals.items()},
            "rows": rows, "arrows": arrows, "open_heads": zero_dose_only, "ell_labels": ell_labels}


# =====================================================================================
# 2. Drawing (vault figA.py sections 4-6; geometry from _fig34_style)
# =====================================================================================
def render(fig_data: dict, font: dict, out_pdf: Path) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon

    zero_dose_only = fig_data["open_heads"]
    xpos = S.centre
    DIV_X = S.RX                            # Figure 4's arrival rule
    assert xpos(2014) < DIV_X - S.GAP / 2 < xpos(2016) and xpos(2014) < xpos(S.BASE) < DIV_X

    H = 2.15
    fig = plt.figure(figsize=(S.W, H))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, S.W); ax.set_ylim(0, H); ax.axis("off")

    Y_LAB = H - 0.06                 # "year before arrival" / "arrival" (top of text)
    Y_YEAR = H - 0.38                # year numbers (va=bottom)
    Y_ELL = Y_YEAR - 0.05            # ell row (top of text)
    ROW0 = Y_ELL - 0.30              # first arrow row
    ROW_DY = 0.235
    ROW_Y = {r["k"]: ROW0 - (r["k"] - 1) * ROW_DY for r in fig_data["rows"]}
    assert min(ROW_Y.values()) > 0.08
    HEAD_L, HEAD_W = 0.075, 0.034    # arrowhead length / half-width (inches)
    SQ_GAP = 0.052                   # shaft starts just outside the 2015 square
    SHAFT_LW = 1.15

    DRAWN = {"effect": [], "placebo": [], "base_marks": [], "open": [], "lines": []}
    TEXTS, DRAWN_TEXT = [], []

    def text(x, y, s, *, size=S.FONT_SIZE, style="normal", weight="normal", **kw):
        TEXTS.append(s)
        DRAWN_TEXT.append((s, style, weight))
        return ax.text(x, y, s, fontproperties=S.props(font, style=style, weight=weight, size=size), **kw)

    def arrow(y, x0, x_tip, color, dashed, open_head):
        d = 1 if x_tip > x0 else -1
        x_neck = x_tip - d * HEAD_L
        ls = (0, (3.2, 2.0)) if dashed else "-"
        ax.plot([x0, x_neck], [y, y], color=color, lw=SHAFT_LW, ls=ls,
                solid_capstyle="butt", dash_capstyle="butt", zorder=3)
        tri = [(x_tip, y), (x_neck, y + HEAD_W), (x_neck, y - HEAD_W)]
        if open_head:
            ax.add_patch(Polygon(tri, closed=True, fc="white", ec=color, lw=0.9, joinstyle="miter", zorder=4))
        else:
            ax.add_patch(Polygon(tri, closed=True, fc=color, ec="none", zorder=4))

    # --- header: years, ell row, year before arrival / arrival ----------------------------------
    for yr_ in range(2011, 2022):
        text(xpos(yr_), Y_YEAR, str(yr_), ha="center", va="bottom",
             color=S.MUTED if yr_ == S.BASE else S.INK2)
        text(xpos(yr_), Y_ELL, fig_data["ell_labels"][str(yr_)], size=7, ha="center", va="top", color=S.MUTED)
    text(S.X0 - 0.10, Y_ELL, "ℓ", size=7.5, style="italic", ha="right", va="top", color=S.MUTED)
    text(DIV_X - 0.05, Y_LAB, "year before arrival", ha="right", va="top", color=S.INK2)
    text(xpos(S.G), Y_LAB, "arrival", ha="center", va="top", color=S.INK2)
    LABEL_X = {"base": DIV_X - 0.05, "arrival": xpos(S.G)}

    # arrival divider between 2015 and 2016, from the last row up past the year header
    last_k = fig_data["rows"][-1]["k"]
    ax.plot([DIV_X, DIV_X], [ROW_Y[last_k] - 0.12, Y_LAB], color=S.RULE, lw=S.RULE_LW, zorder=1,
            solid_capstyle="butt")
    DRAWN["lines"].append(("divider", DIV_X))

    # --- arrows and base squares (one row per horizon) ------------------------------------------
    by_row = {}
    for a in fig_data["arrows"]:
        by_row.setdefault(a["row"], []).append(a)
    for r in fig_data["rows"]:
        y = ROW_Y[r["k"]]
        for a in by_row[r["k"]]:
            d = 1 if a["to"] > S.BASE else -1
            arrow(y, xpos(S.BASE) + d * SQ_GAP, xpos(a["to"]), S.INK if a["kind"] == "effect" else S.GREY,
                  a["kind"] == "placebo", a["open_head"])
            DRAWN[a["kind"]].append((a["from"], a["to"], y))
            if a["open_head"]:
                DRAWN["open"].append(a["to"])
        ax.plot(xpos(S.BASE), y, marker="s", ms=5.0, mfc="white", mec=S.INK, mew=1.0, zorder=5)
        DRAWN["base_marks"].append((S.BASE, y))

    # direct labels on the top row (horizon 1)
    top = fig_data["rows"][0]
    text(xpos(top["effect"]) + 0.07, ROW_Y[1], "effect", ha="left", va="center", color=S.INK)
    text(xpos(top["placebo"]) - 0.07, ROW_Y[1], "placebo", ha="right", va="center", color=S.GREY)

    # --- key in the left margin: one sample open head, next to the 2012 / 2011 arrows -----------
    KEY_Y = (ROW_Y[3] + ROW_Y[4]) / 2
    KX0, KX1 = 0.06, 0.36
    arrow(KEY_Y, KX0, KX1, S.INK, False, True)
    text(KX1 + 0.07, KEY_Y, KEY_TEXT, size=8, ha="left", va="center", color=S.INK2)

    # --- drawn-element checks against the facts (recomputations) ---------------------------------
    eff = sorted(DRAWN["effect"], key=lambda r: -r[2])      # top to bottom
    plc = sorted(DRAWN["placebo"], key=lambda r: -r[2])
    assert all(s == S.BASE for s, _, _ in eff + plc), "every arrow starts at the base year"
    assert [t for _, t, _ in eff] == S.EFFECT_YEARS, "one effect arrow per effect year, 2016 on top"
    assert [t for _, t, _ in plc] == sorted(PAIR, reverse=True), "one placebo arrow per placebo year"
    for _, tp, yp in plc:                      # a placebo shares its row with its paired effect
        assert [te for _, te, ye in eff if ye == yp] == [PAIR[tp]], tp
    assert [te for _, te, ye in eff if ye not in {y for _, _, y in plc}] == [2020, 2021]
    assert len(DRAWN["base_marks"]) == len(fig_data["rows"])
    assert sorted(DRAWN["open"]) == zero_dose_only        # exactly the zero-dose-only coefficients
    assert LABEL_X["base"] == DIV_X - 0.05 and LABEL_X["arrival"] == xpos(2016)
    assert DRAWN["lines"] == [("divider", DIV_X)]           # no guide lines, no brackets
    assert all("comparisons" not in s for s in TEXTS)
    assert S.ZERO_DOSE_TERM in KEY_TEXT
    year_re = re.compile(r"20(1[1-9]|2[01])")
    words = sum(len([w for w in s.split() if not year_re.fullmatch(w)]) for s in TEXTS)
    assert words <= 25, words                              # <= 25 words, years excluded
    S.check_coverage(font, DRAWN_TEXT)

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_pdf, **S.SAVE_KW)
    plt.close(fig)
    return TEXTS


def generate(ledger=None, out_dir=None, *, font_fallback=False, font_search_dirs=None, font_cache=None) -> dict:
    """Draw Figure 3 from a carried ledger; write <out_dir>/fig_compare_years.{pdf,json}."""
    ledger = Path(ledger) if ledger is not None else LEDGER
    out_dir = Path(out_dir) if out_dir is not None else OUT_DIR
    fig_data = build(S.load_arrivals(ledger))
    font = S.use_font(font_fallback=font_fallback, search_dirs=font_search_dirs,
                      cache=font_cache if font_cache is not None else S.FONT_CACHE)
    texts = render(fig_data, font, out_dir / f"{NAME}.pdf")
    out = dict(fig_data)
    out.update({"texts": texts, "font": S.public_font(font), "ledger": ledger.name,
                "_rule": "open head = the coefficient's Model 1 not-yet pool is empty (same rule as "
                         "fig_comparison_pools.json pools.M1_pos), so only zero-dose relations compare."})
    (out_dir / f"{NAME}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ledger", type=Path, default=LEDGER)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--font-dir", type=Path, action="append",
                    help="look for TeX Gyre Pagella only here (default: the pinned TeX layer, _fig34_style.TEXDIR)")
    ap.add_argument("--test-font-fallback", action="store_true",
                    help="TESTS ONLY: draw in DejaVu Serif when Pagella is absent (recorded in the JSON)")
    a = ap.parse_args(argv)
    try:
        out = generate(a.ledger, a.out_dir, font_fallback=a.test_font_fallback, font_search_dirs=a.font_dir)
    except S.FontStop as e:
        print(e, file=sys.stderr)
        raise SystemExit(2)
    print(f"wrote {a.out_dir / (NAME + '.pdf')} and .json; font {out['font']['family']}"
          f"{' (TEST FALLBACK)' if out['font']['fallback'] else ''}")


if __name__ == "__main__":
    main()
