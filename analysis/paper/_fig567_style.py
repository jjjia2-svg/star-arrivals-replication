"""_fig567_style.py — the base tree's Figures 5, 6 and 7 (R1, unit FIG567).

The author's base tree (the manuscript of 2026-10-11) prints the three Section 4 event-study figures as
they were redrawn on 2026-10-03 by the author's original plotting scripts outside this repository (kept
privately with their md5; not shipped):

  Figure 5  fig_p1.pdf       analysis/paper/fig_p1.py --tree base_2026_10_11     (original sec4/fig_p1.py)
  Figure 6  fig_p2.pdf       analysis/paper/fig_p2.py --tree base_2026_10_11     (original sec4/fig_p2.py)
  Figure 7  fig_p3_afar.pdf  analysis/paper/ledger_p3afar.py --tree base_2026_10_11, which draws through
                             analysis/paper/fig_p3_afar.py                          (original sec4/fig_p3_afar.py)

Without --tree (thesis_report) each generator still draws the pre-2026-10-03 figure byte for byte (the
legacy thesis_report tree prints those). This module is the port of the original two helpers,
_sec4_style.py (greys, ticks, the shared words) and _two_row.py (the layout of Figures 6 and 7), with
three changes:
  - font: TeX Gyre Pagella from the pinned TeX layer through _fig34_style (the originals used the macOS
    system Palatino; the package uses no system fonts). Absent -> FontStop; only an explicit test flag draws
    in DejaVu Serif. So the bytes differ from the printed PDFs; the words and page size do not;
  - the October answers the original scripts asserted (the three joint placebo p-values, which interval of
    Figure 7 leaves its panel) are not asserted here: a manuscript test fixture
    (tests/fixtures/r1_paper/, not shipped) pins them. Structural asserts (horizons, the window rule, the shared x-axis) stay;
  - no PNG preview and no word count print (PyMuPDF is not in the generators' layer); the PDF is saved
    without a CreationDate (_fig34_style.SAVE_KW).
Every number drawn comes from the ledger the generator reads.
"""
from __future__ import annotations

import contextlib
from pathlib import Path

from analysis.paper import _fig34_style as S

BASE = "base_2026_10_11"
THESIS = "thesis_report"
TREES = (THESIS, BASE)

# neutral greys (R = G = B): the four Figures 3-4 share, plus three the original _sec4_style.py added
INK, INK2, MUTED, RULE = S.INK, S.INK2, S.MUTED, S.RULE
ZERO = "#7a7a7a"          # zero line
BAND = "#e3e3e3"          # zero-dose-only horizons (Figure 5)
BAND_NE = "#efefef"       # not-estimated year (Figures 6, 7)
for _c in (INK, INK2, MUTED, RULE, ZERO, BAND, BAND_NE):
    assert _c[1:3] == _c[3:5] == _c[5:7], _c
assert (INK, INK2, MUTED, RULE) == ("#1a1a1a", "#4a4a4a", "#8a8a8a", "#9a9a9a")   # the original values

NOT_EST_LABEL = "not estimated"
# the one wording shared with Figure 3's key (original: "outline: identical words")
ZERO_DOSE_LABEL = S.ZERO_DOSE_TERM + " only"
X_LABEL = "Years since arrival (−1 = year before arrival)"
assert ZERO_DOSE_LABEL == "zero-dose relations only"

#: the original apply_style() rcParams, without the font family (set by font_rc from the font found)
RC = {"font.size": 8.5, "axes.titlesize": 8.5, "axes.labelsize": 8.5,
      "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
      "axes.linewidth": 0.6, "xtick.major.width": 0.6, "ytick.major.width": 0.6,
      "xtick.major.size": 2.5, "ytick.major.size": 2.5,
      "axes.unicode_minus": True, "pdf.fonttype": 42}
#: savefig keywords: no creation date (the base tree's PDFs carry 2026-10-03; ours carry none)
SAVE_KW = {"metadata": {"CreationDate": None}}


def zero_dose_only_ells() -> list[int]:
    """Model 1 coefficients (thesis ell) whose only comparisons are zero-dose relations for EVERY cohort:
    the not-yet pool is empty even with a star arriving in every year. Same pool rule as Figures 3-4
    (_fig34_style.not_yet_pool, Model 1 window +-5); the original typed [-5, -4, 4, 5]."""
    every = {a: 1 for a in range(S.G - 40, S.G + 41)}
    eff = [S.ell(t) for t in S.EFFECT_YEARS if not S.not_yet_pool(every, t, S.M1_LO, S.M1_HI)]
    plc = [S.ell(p) for p in S.PLACEBO_YEARS
           if not S.not_yet_pool(every, S.paired_effect(p), S.M1_LO, S.M1_HI, also_year=p)]
    return sorted(eff + plc)


ZERO_DOSE_ONLY_ELL = zero_dose_only_ells()
assert ZERO_DOSE_ONLY_ELL == [-5, -4, 4, 5], ZERO_DOSE_ONLY_ELL     # window rule, not data


def fmt_p(p: float) -> str:
    """The original joint placebo p format (3 dp, the text's precision; <0.001 below 0.0005)."""
    return "<0.001" if p < 0.0005 else f"{p:.3f}"


def font_rc(*, font_fallback: bool = False, search_dirs=None, cache=None) -> tuple[dict, dict]:
    """(rcParams for style(), the font record). TeX Gyre Pagella from the pinned TeX layer
    (_fig34_style.use_font: FontStop when absent unless font_fallback, the explicit test flag). Its
    TrueType copies are registered with matplotlib's font manager so the axes' own text (ticks, titles,
    labels, the key) is drawn in it; draw-time checks confirm the face actually used."""
    import matplotlib
    from matplotlib import font_manager as fm

    with matplotlib.rc_context():                       # use_font sets rcParams; keep them local
        font = S.use_font(font_fallback=font_fallback, search_dirs=search_dirs,
                          cache=cache if cache is not None else S.FONT_CACHE)
    family = S.FALLBACK_FAMILY if font["fallback"] else S.FAMILY
    if not font["fallback"]:
        for path in font["_ttf"].values():
            fm.fontManager.addfont(path)
    rc = {**RC, "font.family": "serif", "font.serif": [family], "svg.fonttype": "none"}
    return rc, font


@contextlib.contextmanager
def style(rc: dict):
    """matplotlib's defaults plus rc for the duration of one drawing, whatever the caller's rcParams
    (the original scripts ran in a fresh interpreter); the caller's rcParams come back afterwards."""
    import matplotlib
    with matplotlib.rc_context():
        matplotlib.rcdefaults()
        matplotlib.rcParams.update(rc)
        yield


def check_font(font: dict) -> None:
    """Inside style(rc): the regular face matplotlib resolves for the figure text is the
    Pagella copy (or, under the test flag, the fallback family). Any other face is a FontStop."""
    from matplotlib import font_manager as fm
    if font["fallback"]:
        return
    want = Path(font["_ttf"]["Regular"]).resolve()
    try:
        got = Path(fm.findfont(fm.FontProperties(family="serif"), fallback_to_default=False)).resolve()
    except ValueError as e:
        raise S.FontStop(f"STOP fig567: {S.FAMILY} is not resolvable by matplotlib ({e})") from None
    if got != want:
        raise S.FontStop(f"STOP fig567: matplotlib resolves {got.name}, not the {S.FAMILY} copy {want.name}")


def tidy(ax):
    """Open frame (no top/right spines), as in the rest of the essay's figures."""
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color(INK2)
    ax.spines["bottom"].set_color(INK2)
    ax.tick_params(colors=INK2)


def tick_label(t: int) -> str:
    """Readable ticks (change #5): every integer gets a tick; labels on -1 and every year from 0 on, and
    on odd years before -1 (adjacent negative labels collide at this panel width)."""
    if t >= -1 or t % 2 == 1:
        return str(t).replace("-", "−")
    return ""


def set_event_ticks(ax, lo: int, hi: int) -> list[int]:
    ticks = list(range(lo, hi + 1))
    ax.set_xticks(ticks, [tick_label(t) for t in ticks])
    return ticks


def drawn_texts(fig) -> list[str]:
    """Every string a draw of the figure actually renders (titles, axis labels, the tick labels of the
    ticks in view, the key, the shared x label), in draw order: Text.draw is observed for one canvas
    draw, after its own visible / empty-string checks."""
    import matplotlib.text as mtext
    drawn = []
    orig = mtext.Text.draw

    def observed(self, renderer):
        if self.get_visible() and self.get_text() != "":
            drawn.append(self.get_text())
        return orig(self, renderer)

    mtext.Text.draw = observed
    try:
        fig.canvas.draw()
    finally:
        mtext.Text.draw = orig
    return [s for s in drawn if s.strip()]


def save(fig, out_pdf: Path, font: dict) -> list[str]:
    """Glyph coverage of every drawn string in the face that draws it, then the PDF; returns the
    strings (for the caller's record)."""
    texts = drawn_texts(fig)
    S.check_coverage(font, [(s, "normal", "normal") for s in texts])
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_pdf, **SAVE_KW)
    return texts


# =====================================================================================================
# Figure 5 (original sec4/fig_p1.py build_figure)
# =====================================================================================================
def draw_p1(values: dict, fields, out_pdf: Path, font: dict, rc: dict) -> dict:
    """values: {cell: {horizons, placebos, relations, events, p_joint_placebo_person}} (the ledger's
    shape); fields: [(cell, title)] in column order."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    with style(rc):
        check_font(font)
        fig, axes = plt.subplots(1, 3, figsize=(6.6, 2.7), sharex=True)
        p_txt = {}
        for col, (cell, title) in enumerate(fields):
            d = values[cell]
            pl = sorted(d["placebos"], key=lambda h: h["ell"])
            hz = sorted(d["horizons"], key=lambda h: h["ell"])
            assert [h["ell"] for h in pl] == [-5, -4, -3, -2], cell
            assert [h["ell"] for h in hz] == [0, 1, 2, 3, 4, 5], cell
            ax = axes[col]
            tidy(ax)
            # change #3: zero-dose-only horizons, both sides (one band per run of adjacent ells)
            for lo, hi in _runs(ZERO_DOSE_ONLY_ELL):
                ax.axvspan(lo - 0.5, hi + 0.5, color=BAND, lw=0, zorder=0)
            ax.axhline(0, color=ZERO, lw=0.7, zorder=1)
            ax.axvline(-0.5, color=RULE, lw=0.8, ls=(0, (3, 2)), zorder=1)
            # placebo coefficients (open circles), ell = -5..-2
            ax.errorbar([h["ell"] for h in pl], [h["est"] for h in pl],
                        yerr=[1.96 * h["se_person"] for h in pl],
                        fmt="o", color=INK, mfc="white", mew=0.9, ms=3.4, capsize=2.2, lw=0.9,
                        zorder=3)
            # year before arrival at zero (no interval) and effects (filled circles)
            xs = [-1] + [h["ell"] for h in hz]
            ys = [0.0] + [h["est"] for h in hz]
            ses = [0.0] + [h["se_person"] for h in hz]
            ax.errorbar(xs, ys, yerr=[1.96 * v for v in ses],
                        fmt="o", color=INK, ms=3.4, capsize=2.2, lw=0.9, zorder=3)
            # change #2: the joint placebo p-value, one line under the panel title (from the ledger)
            p_txt[cell] = fmt_p(d["p_joint_placebo_person"])
            ax.set_title(f"{title}\n{d['relations']:,} relations, {d['events']} events\n"
                         f"joint placebo p = {p_txt[cell]}", linespacing=1.25)
            ax.set_xlim(-5.6, 5.6)
            set_event_ticks(ax, -5, 5)
        axes[0].set_ylabel("Change in log output\n(at the doses incumbents hold)")
        # change #3 key, once, same words as Figure 3
        fig.legend(handles=[Patch(facecolor=BAND, edgecolor="none", label=ZERO_DOSE_LABEL)],
                   loc="lower right", bbox_to_anchor=(0.995, -0.01), frameon=False, fontsize=8,
                   handlelength=1.4, handleheight=0.9)
        fig.tight_layout(rect=(0, 0.045, 1, 1), w_pad=1.2)
        fig.supxlabel(X_LABEL, fontsize=8.5, y=0.012)
        texts = save(fig, out_pdf, font)
        plt.close(fig)
    return {"texts": texts, "p_joint_placebo": p_txt, "zero_dose_only_ell": list(ZERO_DOSE_ONLY_ELL),
            "size_in": [6.6, 2.7]}


def _runs(ells: list[int]) -> list[tuple[int, int]]:
    """[-5, -4, 4, 5] -> [(-5, -4), (4, 5)]: maximal runs of consecutive integers."""
    out = []
    for e in sorted(ells):
        if out and e == out[-1][1] + 1:
            out[-1] = (out[-1][0], e)
        else:
            out.append((e, e))
    return out


assert _runs(ZERO_DOSE_ONLY_ELL) == [(-5, -4), (4, 5)]   # the original two bands (-5.5..-3.5, 3.5..5.5)

# =====================================================================================================
# Figures 6 and 7 (original sec4/_two_row.py draw)
# =====================================================================================================
X_TICKS = list(range(-6, 6))
X_LIM = (-6.6, 5.6)
NOT_EST_ELL = 5
TWO_ROW_SIZE_IN = (6.6, 4.7)


def draw_two_row(panels, unit_word, top_ylabel, out_pdf: Path, font: dict, rc: dict, clip=None) -> dict:
    """panels: list of dicts with keys title, n_units, events, coefs [(ell, est, se)], raw {tau: rate}.
    Upper row: event-time coefficients, ell = 0..4, with ell = -1 at zero. Lower row: the raw first-tie
    rate by years since arrival (observable years), ell = -6..5. clip: {column: (ylo, yhi)} clips one
    upper panel's y-range and marks every interval end that leaves it with an arrowhead at the edge
    (change #7). Returns the drawn strings and the clipped interval ends [(col, ell, end, value)]."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    clip = clip or {}
    with style(rc):
        check_font(font)
        fig, axes = plt.subplots(2, 3, figsize=TWO_ROW_SIZE_IN, sharex=True,
                                 gridspec_kw={"height_ratios": [1.05, 1]})
        clipped = []
        for col, d in enumerate(panels):
            ax, ax2 = axes[0, col], axes[1, col]
            for a in (ax, ax2):
                tidy(a)
                a.axvspan(NOT_EST_ELL - 0.5, NOT_EST_ELL + 0.5, color=BAND_NE, lw=0, zorder=0)
                a.axvline(-0.5, color=RULE, lw=0.8, ls=(0, (3, 2)), zorder=1)
            # upper row: coefficients (pre-arrival ones are zero by construction, omitted)
            assert [e for e, _, _ in d["coefs"]] == [0, 1, 2, 3, 4], d["title"]
            xs = [-1] + [e for e, _, _ in d["coefs"]]
            ys = [0.0] + [b for _, b, _ in d["coefs"]]
            ses = [0.0] + [s for _, _, s in d["coefs"]]
            ax.axhline(0, color=ZERO, lw=0.7, zorder=1)
            ax.errorbar(xs, ys, yerr=[1.96 * v for v in ses], fmt="o", color=INK, ms=3.4,
                        capsize=2.2, lw=0.9, zorder=3)
            ax.set_title(f"{d['title']}\n{d['n_units']:,} {unit_word}, {d['events']} events",
                         linespacing=1.25)
            if col in clip:
                ylo, yhi = clip[col]
                ax.set_ylim(ylo, yhi)
                for x, y, s in zip(xs, ys, ses):
                    if not ylo < y < yhi:
                        raise SystemExit(f"STOP fig567: {d['title']} ell={x} estimate {y} lies outside the "
                                         f"panel's fixed y-range {clip[col]} (a design constant of the "
                                         f"2026-10-03 figure); the author sets a new range")
                    for end, v in (("lower", y - 1.96 * s), ("upper", y + 1.96 * s)):
                        if (end == "lower" and v < ylo) or (end == "upper" and v > yhi):
                            edge = ylo if end == "lower" else yhi
                            ax.plot([x], [edge], marker="v" if end == "lower" else "^", ms=4.5,
                                    color=INK, clip_on=False, zorder=5)
                            clipped.append((col, x, end, v))
            # lower row: raw first-tie rate by years since arrival (observable years)
            taus = sorted(d["raw"])
            ax2.plot(taus, [d["raw"][t] for t in taus], "o-", color=INK, ms=3, lw=0.9, zorder=3)
            ax2.set_ylim(bottom=0)
            ax2.set_xlim(*X_LIM)
            set_event_ticks(ax2, X_TICKS[0], X_TICKS[-1])
        axes[0, 0].set_ylabel(top_ylabel)
        axes[1, 0].set_ylabel("Raw first-tie rate\n(percent per year)")
        fig.legend(handles=[Patch(facecolor=BAND_NE, edgecolor="none", label=NOT_EST_LABEL)],
                   loc="lower right", bbox_to_anchor=(0.995, -0.005), frameon=False, fontsize=8,
                   handlelength=1.4, handleheight=0.9)
        fig.tight_layout(rect=(0, 0.03, 1, 1), w_pad=1.2, h_pad=0.6)
        fig.supxlabel(X_LABEL, fontsize=8.5, y=0.008)
        texts = save(fig, out_pdf, font)
        # checks on what was drawn
        for col in range(3):
            assert list(axes[1, col].get_xticks()) == X_TICKS
            assert axes[0, col].get_xlim() == axes[1, col].get_xlim() == X_LIM
        plt.close(fig)
    return {"texts": texts, "clipped": [list(c) for c in clipped], "size_in": list(TWO_ROW_SIZE_IN)}


def raw_by_tau(raw: dict) -> dict[int, float]:
    """The ledger's raw rates keyed by int tau (JSON keys are strings), checked to cover -6..5."""
    out = {int(t): v for t, v in raw.items()}
    assert sorted(out) == list(range(-6, 6)), sorted(out)
    return out
