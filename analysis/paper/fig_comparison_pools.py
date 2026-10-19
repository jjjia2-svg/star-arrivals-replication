#!/usr/bin/env python3
"""fig_comparison_pools.py — Figure 4: who is the comparison in each year (R1 N9, unit W1-FIG34).

Data-driven port of the original drawing script figB.py (third version, design B1, round 2; verbatim
copy and md5 in analysis/paper/_vault_2026-10-03/, not shipped). Running example: the 2016 arrivals in economics (Zénou's cohort,
Monash), base year 2015. One 3-row grid (Model 1 zero-dose relations / Model 1 positive dose, star
not yet arrived / Models 2-3 star not yet arrived), columns 2011-2021 with 2015 an empty column.

What changed against figB.py:
  - the arrivals per year come from the carried ledger (events_by_school_econ, summed by year), not
    the hand-typed ARRIVALS dict; the not-yet pools and the grey/white cell states are computed
    from them, so a different event set redraws the cells;
  - the asserts that encoded October counts (EXPECTED_M1, EXPECTED_M23, the 'none' year lists, the
    number of grey cells) are recomputations; the October values are pinned in
    tests/fixtures/r1_paper/fig34_october.json (not shipped);
  - geometry, greys and font come from analysis/paper/_fig34_style.py (TeX Gyre Pagella from the
    pinned TeX layer; STOP when absent);
  - no caption file (the caption lives in sec3_strategy.tex).
Kept: PINNED stays None, so no count is drawn (author rule 2026-10-03: "no number may be printed
before it is pinned"); the pool counts are written to the figure JSON only, as undrawn records.

Reads:   output/paper/data_numbers_carried.json  (key events_by_school_econ; run ledger_carried.py first)
Writes:  output/paper/fig_comparison_pools.pdf, output/paper/fig_comparison_pools.json
Run:     python3 analysis/paper/fig_comparison_pools.py [--ledger F] [--out-dir D]
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

NAME = "fig_comparison_pools"
P = load_paths()
LEDGER = P["output"] / "paper" / "data_numbers_carried.json"
OUT_DIR = P["output"] / "paper"

USED, NONE, NOT_REP, NO_EST = "used", "none", "not_reported", "no_estimate"
ROWS = ("M1_zero", "M1_pos", "M23")
ROW_LABELS = [S.ZERO_DOSE_TERM, "positive dose, star\nnot yet arrived", "star not yet arrived"]
PINNED = None   # pinned comparison-relation counts (save_sample); None = no number is drawn
assert PINNED is None, "pinned counts: add a drawing rule and a ledger check before use"


# =====================================================================================
# 1. Facts: pools and cell states from the ledger's arrivals
# =====================================================================================
def zero_dose_range(y: int) -> tuple[int, int]:
    """Model 1 zero-dose relations used in year y (window rule; ranges not drawn, the rotation is not
    stated until checked on AWS)."""
    if y in S.EFFECT_YEARS:
        e = S.ell(y)
        return (S.G + e - 5, S.G + 4)
    e = S.ell(S.paired_effect(y))          # placebo paired with effect e
    return (S.G + e - 5, S.G + 3 - e)


# window arithmetic only (no data): every year has a non-empty zero-dose range -> 'used' every year
ZD_EXPECTED = {2011: (2014, 2016), 2012: (2013, 2017), 2013: (2012, 2018), 2014: (2011, 2019),
               2016: (2011, 2020), 2017: (2012, 2020), 2018: (2013, 2020), 2019: (2014, 2020),
               2020: (2015, 2020), 2021: (2016, 2020)}
for _y, _rng in ZD_EXPECTED.items():
    assert zero_dose_range(_y) == _rng and _rng[0] <= _rng[1], (_y, zero_dose_range(_y), _rng)


def runs(cells: dict, row: int) -> list[dict]:
    """Merge adjacent cells with the same empty state (none / not reported) into one span.
    Used cells stay one per year: each year's pool is a different set of relations."""
    out, cur = [], None
    for y in S.YEARS:
        s = cells[(row, y)]
        if cur and s in (NONE, NOT_REP) and cur["state"] == s and cur["years"][-1] + 1 == y:
            cur["years"].append(y)
            continue
        cur = {"state": s, "years": [y]}
        out.append(cur)
    return out


def build(arrivals: dict) -> dict:
    """Pools, cell states and runs for the 2016 cohort, from arrivals {year: n_events}."""
    m1_eff = {t: S.not_yet_pool(arrivals, t, S.M1_LO, S.M1_HI) for t in S.EFFECT_YEARS}
    # a placebo column uses the pool of its PAIRED effect year, keeping only relations with a row
    # in the placebo year too (not "not yet arrived by the placebo year")
    m1_pla = {p: S.not_yet_pool(arrivals, S.paired_effect(p), S.M1_LO, S.M1_HI, also_year=p)
              for p in S.PLACEBO_YEARS}
    m23_eff = {t: S.not_yet_pool(arrivals, t, S.M23_LO, S.M23_HI) for t in S.EFFECT_YEARS}

    # structural checks (hold for any ledger)
    assert all(a > S.BASE for pool in m1_pla.values() for a in pool)          # 2015 arrivals never
    assert all(set(m1_pla[p]) <= set(m1_eff[S.paired_effect(p)]) for p in S.PLACEBO_YEARS)
    for a_, b_ in zip(S.EFFECT_YEARS, S.EFFECT_YEARS[1:]):                    # pools only shrink
        assert set(m1_eff[b_]) <= set(m1_eff[a_]) and set(m23_eff[b_]) <= set(m23_eff[a_])
    assert m23_eff[S.EFFECT_YEARS[-1]] == []                                  # 2021: no comparison

    cells = {}
    for y in S.YEARS:
        cells[(0, y)] = USED                                                  # zero-dose: every year
        pool = m1_pla[y] if y in m1_pla else m1_eff[y]
        cells[(1, y)] = USED if pool else NONE
        if y in S.PLACEBO_YEARS:
            # Models 2-3 placebos: ell -2, -3 zero by construction (SE 0); ell -4, -5 no comparison
            # (N = 0); Model 3's driver does not store placebos -> "not reported" (text gives reasons)
            cells[(2, y)] = NOT_REP
        else:
            cells[(2, y)] = USED if m23_eff[y] else NO_EST
    assert all(cells[(0, y)] == USED for y in S.YEARS)
    assert [y for y in S.YEARS if cells[(2, y)] == NOT_REP] == S.PLACEBO_YEARS
    assert cells[(2, S.EFFECT_YEARS[-1])] == NO_EST

    def pool_rec(y, pool, placebo):
        rec = {"paired_effect": S.paired_effect(y)} if placebo else {}
        rec.update({"arrival_years": pool, "n_events": S.n_events(arrivals, pool)})
        return rec

    return {
        "cohort": S.G, "base": S.BASE,
        "arrivals_by_year": {str(y): n for y, n in arrivals.items()},
        "cells": {ROWS[r]: {str(y): cells[(r, y)] for y in S.YEARS} for r in range(3)},
        "runs": {ROWS[r]: [dict(x) for x in runs(cells, r)] for r in range(3)},
        "pools": {
            "M1_pos": {str(y): pool_rec(y, m1_pla[y] if y in m1_pla else m1_eff[y], y in m1_pla)
                       for y in S.YEARS},
            "M23": {str(t): pool_rec(t, m23_eff[t], False) for t in S.EFFECT_YEARS},
        },
        "zero_dose_ranges": {str(y): list(zero_dose_range(y)) for y in S.YEARS},
        "pinned": PINNED,
        "_cells": cells,
    }


# =====================================================================================
# 2. Drawing (vault figB.py sections 3-5; geometry from _fig34_style)
# =====================================================================================
def render(fig_data: dict, font: dict, out_pdf: Path) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import to_rgb
    from matplotlib.patches import Rectangle

    cells = fig_data["_cells"]
    EDGE = S.MUTED                         # hairline frame of the white 'none' / '—' cells
    CELL_LW = 0.6
    assert 0.12 <= 1 - to_rgb(S.FILL)[0] <= 0.15              # fill 12-15% grey

    H = 1.6
    fig = plt.figure(figsize=(S.W, H))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, S.W); ax.set_ylim(0, H); ax.axis("off")
    TEXTS, DRAWN_TEXT = [], []

    def text(x, y, s, *, size=S.FONT_SIZE, style="normal", weight="normal", **kw):
        TEXTS.append(s)
        DRAWN_TEXT.append((s, style, weight))
        return ax.text(x, y, s, fontproperties=S.props(font, style=style, weight=weight, size=size), **kw)

    col_x, centre, CW, PAD = S.col_x, S.centre, S.CW, S.PAD
    Y_GROUP = H - 0.04                  # "placebos" / "effects" (top of text)
    Y_SPAN = H - 0.20                   # group rules
    Y_LAB = H - 0.25                    # "year before arrival" / "arrival" (top of text)
    Y_YEAR = Y_LAB - 0.32               # year numbers (va=bottom)
    ROW_H = 0.285
    TOP = Y_YEAR - 0.07
    ROW_TOP = [TOP, TOP - ROW_H, TOP - 2 * ROW_H - 0.08]  # extra space before Models 2-3
    assert ROW_TOP[2] - ROW_H > 0.02

    # --- column groups: "placebos" over 2011-2014, "effects" over 2016-2021 --------------------
    GROUPS = {"placebos": S.PLACEBO_YEARS, "effects": S.EFFECT_YEARS}
    span_drawn = {}
    for lab, ys in GROUPS.items():
        xa, xb = col_x(min(ys)) + PAD / 2, col_x(max(ys)) + CW - PAD / 2
        ax.plot([xa, xb], [Y_SPAN, Y_SPAN], color=S.RULE, lw=S.RULE_LW, solid_capstyle="butt")
        text((xa + xb) / 2, Y_GROUP, lab, ha="center", va="top", color=S.INK)
        span_drawn[lab] = (xa, xb)

    # --- year before arrival / arrival and years ------------------------------------------------
    text(S.RX - 0.05, Y_LAB, "year before arrival", ha="right", va="top", color=S.INK2)
    text(centre(S.G), Y_LAB, "arrival", ha="center", va="top", color=S.INK2)
    for y in range(2011, 2022):
        text(centre(y), Y_YEAR, str(y), ha="center", va="bottom", color=S.MUTED if y == S.BASE else S.INK2)
    bottom = ROW_TOP[2] - ROW_H
    ax.plot([S.RX, S.RX], [bottom - 0.01, H - 0.02], color=S.RULE, lw=S.RULE_LW, zorder=1,
            solid_capstyle="butt")

    # --- row labels: model group + full-word row label -----------------------------------------
    LX_GROUP, LX_ROW = 0.05, 0.80
    for r, lab in enumerate(ROW_LABELS):
        text(LX_ROW, ROW_TOP[r] - ROW_H / 2, lab, ha="left", va="center", color=S.INK, linespacing=1.1)
    m1_mid = (ROW_TOP[0] + ROW_TOP[1] - ROW_H) / 2
    text(LX_GROUP, m1_mid, "Model 1", size=9, weight="bold", ha="left", va="center", color=S.INK)
    text(LX_GROUP, ROW_TOP[2] - ROW_H / 2, "Models 2–3", size=9, weight="bold", ha="left", va="center",
         color=S.INK)
    BX = LX_ROW - 0.09
    ax.plot([BX + 0.04, BX, BX, BX + 0.04],
            [ROW_TOP[0] - 0.04, ROW_TOP[0] - 0.04, ROW_TOP[1] - ROW_H + 0.04,
             ROW_TOP[1] - ROW_H + 0.04], color=S.RULE, lw=S.RULE_LW)

    # --- cells -----------------------------------------------------------------------------------
    CELL_FS = 8                 # one size for every in-cell word
    drawn, patches, cell_fs = {}, {}, set()
    for r in range(3):
        for run in runs(cells, r):
            ys = run["years"]
            x0 = col_x(ys[0]) + PAD / 2
            x1 = col_x(ys[-1]) + CW - PAD / 2
            y1 = ROW_TOP[r] - PAD / 2
            y0 = ROW_TOP[r] - ROW_H + PAD / 2
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            s = run["state"]
            if s == USED:
                ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fc=S.FILL, ec="none", lw=0))
                patches.setdefault(s, []).append((S.FILL, None))
            elif s == NOT_REP:      # no fill, no frame: italic words only
                text(cx, cy, "not reported", size=CELL_FS, style="italic", ha="center", va="center",
                     color=S.GREY)
                cell_fs.add(CELL_FS)
                patches.setdefault(s, []).append((None, None))
            else:                   # NONE or NO_EST: white with a hairline frame
                ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fc="white", ec=EDGE, lw=CELL_LW))
                text(cx, cy, "none" if s == NONE else "—", size=CELL_FS,
                     style="italic" if s == NONE else "normal", ha="center", va="center", color=S.INK2)
                cell_fs.add(CELL_FS)
                patches.setdefault(s, []).append(("white", EDGE))
            for y_ in ys:
                drawn[(r, y_)] = s

    # --- checks on what was drawn (recomputations; October values are in the test fixture) ------
    assert drawn == cells, "drawn cells differ from the fact-derived cell states"
    assert S.BASE not in [y_ for (_, y_) in drawn], "2015 is an empty column, not a cell"
    assert span_drawn["placebos"][1] < S.GAP_X0 and span_drawn["effects"][0] > S.GAP_X1 - PAD
    assert abs(span_drawn["placebos"][0] - (col_x(2011) + PAD / 2)) < 1e-12
    assert abs(span_drawn["effects"][1] - (col_x(2021) + CW - PAD / 2)) < 1e-12
    assert all(S.paired_effect(p) in GROUPS["effects"] for p in GROUPS["placebos"])
    assert all(p == ("white", EDGE) for p in patches.get(NONE, []) + patches.get(NO_EST, []))
    assert patches[NOT_REP] == [(None, None)]
    assert all(p == (S.FILL, None) for p in patches[USED])
    assert len(patches[USED]) == sum(1 for v in cells.values() if v == USED)   # one grey cell per used year
    assert cell_fs == {CELL_FS}, cell_fs
    # no number other than calendar years and model names is printed (nothing unpinned)
    year_re = re.compile(r"^20(1[1-9]|2[01])$")
    for s in TEXTS:
        for t in s.split():
            if any(ch.isdigit() for ch in t):
                assert year_re.match(t) or t in {"1", "2–3"}, (s, t)
    assert not any("draft" in s.lower() for s in TEXTS), "process labels may not be printed"
    assert all(s.count("not yet arrived") <= 1 for s in TEXTS)
    words = sum(len([w for w in s.split() if not year_re.match(w)]) for s in TEXTS)
    assert words <= 35, (words, TEXTS)          # brief: about 35; hard limit 45
    S.check_coverage(font, DRAWN_TEXT)

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_pdf, **S.SAVE_KW)
    plt.close(fig)
    return TEXTS


def generate(ledger=None, out_dir=None, *, font_fallback=False, font_search_dirs=None, font_cache=None) -> dict:
    """Draw Figure 4 from a carried ledger; write <out_dir>/fig_comparison_pools.{pdf,json}."""
    ledger = Path(ledger) if ledger is not None else LEDGER
    out_dir = Path(out_dir) if out_dir is not None else OUT_DIR
    arrivals = S.load_arrivals(ledger)
    fig_data = build(arrivals)
    font = S.use_font(font_fallback=font_fallback, search_dirs=font_search_dirs,
                      cache=font_cache if font_cache is not None else S.FONT_CACHE)
    texts = render(fig_data, font, out_dir / f"{NAME}.pdf")
    out = {k: v for k, v in fig_data.items() if not k.startswith("_")}
    out.update({"texts": texts, "font": S.public_font(font), "ledger": ledger.name,
                "_rule": "Model 1 not-yet pool at effect year t: later arrival years a > t with a row in "
                         "2015 and in t (window -5/+5); a placebo uses its paired effect's pool and also "
                         "needs a row in the placebo year. Models 2-3: window -6/+10. n_events counts star "
                         "events, not relations, and is NOT drawn (PINNED is None)."})
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
