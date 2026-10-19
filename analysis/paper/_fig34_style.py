"""_fig34_style.py — what Figures 3 and 4 share (R1 N9, unit W1-FIG34).

Figure 3 = analysis/paper/fig_compare_years.py (original figA.py), Figure 4 =
analysis/paper/fig_comparison_pools.py (original figB.py); the verbatim originals are in
analysis/paper/_vault_2026-10-03/ (not shipped). This module holds:

1. the design constants (cohort 2016 = Zénou's arrival at Monash, base year 2015, the Model 1
   window +-5 and the Models 2-3 window -6/+10, effects 0..5 and placebos -2..-5), unchanged;
2. the one comparison-pool rule both figures use, fed by the arrivals the carried ledger records
   (events_by_school_econ summed by year) instead of the vault's hand-typed ARRIVALS dict;
3. the shared grid geometry and greys (the vault's figA.py read these from figB.py's source text
   by regex; both now import them from here, so every year sits at the same x in both figures);
4. the font: TeX Gyre Pagella from the pinned TeX layer (P3b ruling R7: no system fonts; the
   vault split macOS Palatino.ttc). Absent -> FontStop. Only the explicit test fallback draws in
   DejaVu Serif, and the figure JSON records which font was used.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

# =====================================================================================
# 1. Design constants (vault figA.py / figB.py section 1)
# =====================================================================================
G = 2016                                   # cohort (arrival year): Zénou's, guarded by N11
BASE = G - 1                               # 2015, ell = -1
N_EFFECTS, N_PLACEBOS = 6, 4               # EST/run_p1.R:53 effects=6, placebo=4
EFFECT_YEARS = [BASE + k for k in range(1, N_EFFECTS + 1)]          # 2016..2021, ell 0..5
PLACEBO_YEARS = sorted(BASE - k for k in range(1, N_PLACEBOS + 1))  # 2011..2014, ell -5..-2
YEARS = PLACEBO_YEARS + EFFECT_YEARS       # the ten coefficient columns, 2015 excluded
M1_LO, M1_HI = 5, 5                        # Model 1 window +-5 around own arrival
M23_LO, M23_HI = 6, 10                     # Models 2-3 window -6/+10
ZERO_DOSE_TERM = "zero-dose relations"     # one term for the zero-dose group in both figures

assert EFFECT_YEARS == list(range(2016, 2022)) and PLACEBO_YEARS == [2011, 2012, 2013, 2014]


def ell(year: int) -> int:
    """Thesis convention: ell = 0 in the arrival year, ell = -1 in the base year."""
    return year - G


def paired_effect(p: int) -> int:
    """Placebo k mirrors effect k around the base year (2014<->2016 ... 2011<->2019)."""
    return BASE + (BASE - p)


def mn(x) -> str:
    return str(x).replace("-", "−")        # typographic minus


# =====================================================================================
# 2. Arrivals from the ledger, and the comparison-pool rule
# =====================================================================================
LEDGER_KEY = "events_by_school_econ"


def arrivals_by_year(events_by_school: dict) -> dict[int, int]:
    """{school: [arrival years]} (the carried ledger's shape) -> {year: number of events}."""
    c = Counter(int(y) for years in events_by_school.values() for y in years)
    return dict(sorted(c.items()))


def load_arrivals(ledger) -> dict[int, int]:
    """Economics arrivals per year from a carried ledger (output/paper/data_numbers_carried.json).
    A missing ledger or key is fatal: there is no default to fall back to."""
    ledger = Path(ledger)
    if not ledger.is_file():
        raise SystemExit(f"STOP fig34: ledger {ledger} not found (run ledger_carried.py first)")
    data = json.loads(ledger.read_text(encoding="utf-8"))
    if LEDGER_KEY not in data:
        raise SystemExit(f"STOP fig34: {ledger} has no {LEDGER_KEY!r}")
    return arrivals_by_year(data[LEDGER_KEY])


def has_row(a: int, year: int, lo: int, hi: int) -> bool:
    """A relation of a star arriving in year a has rows a-lo .. a+hi."""
    return a - lo <= year <= a + hi


def not_yet_pool(arrivals: dict, t: int, lo: int, hi: int, also_year: int | None = None) -> list[int]:
    """Arrival years of the later events usable as not-yet comparisons at effect year t: star not
    yet arrived in t, a row in the base year and in t (and, for a placebo, also a row in the
    placebo's earlier year -- the package keeps only those). Years without events are skipped."""
    return sorted(a for a, n in arrivals.items()
                  if n > 0 and a > t and has_row(a, BASE, lo, hi) and has_row(a, t, lo, hi)
                  and (also_year is None or has_row(a, also_year, lo, hi)))


def n_events(arrivals: dict, years) -> int:
    return sum(arrivals.get(a, 0) for a in years)


# structural facts that do not depend on the data (vault asserts kept as asserts)
assert {p: paired_effect(p) for p in PLACEBO_YEARS} == {2014: 2016, 2013: 2017, 2012: 2018, 2011: 2019}
# Models 2-3, 2021: a relation needs a row in 2015 (a <= 2021) and its star not yet arrived in 2021
# (a > 2021): impossible, so no comparison at all -> no coefficient, whatever the ledger says.
assert not [a for a in range(1990, 2050) if has_row(a, BASE, M23_LO, M23_HI) and a > EFFECT_YEARS[-1]]

# =====================================================================================
# 3. Geometry and greys (vault figB.py section 4; figA.py section 3 read these by regex)
# =====================================================================================
W = 6.3                                    # both figures: 6.3 in wide
X0, X1 = 1.97, W - 0.03                    # grid
GAP = 0.390909                             # the empty 2015 column: same width as every year
PAD = 0.028                                # surface gap between cells (about 2 px)
CW = (X1 - X0 - GAP) / 10                  # column width
assert abs(GAP - CW) < 1e-5, (GAP, CW)
GAP_X0 = X0 + 4 * CW
GAP_X1 = GAP_X0 + GAP
RX = GAP_X1 - PAD / 2                      # the arrival rule between 2015 and 2016 (figA: DIV_X)


def col_x(y: int) -> float:
    """Left edge of a coefficient year's column."""
    i = YEARS.index(y)
    return X0 + i * CW + (GAP if y > BASE else 0)


def centre(y: int) -> float:
    """Year centre in inches (2015 = the centre of the empty column)."""
    return X0 + 4 * CW + GAP / 2 if y == BASE else col_x(y) + CW / 2


assert abs(col_x(2016) - GAP_X1) < 1e-9 and abs(col_x(2014) + CW - GAP_X0) < 1e-9
assert all(abs((b - a) - CW) < 1e-5 for a, b in zip([centre(y) for y in range(2011, 2022)],
                                                     [centre(y) for y in range(2012, 2022)]))

# neutral greys shared by both figures (R = G = B, no colour cast in print)
INK, INK2, GREY, MUTED, RULE = "#1a1a1a", "#4a4a4a", "#6b6b6b", "#8a8a8a", "#9a9a9a"
FILL = "#dbdbdb"                           # Figure 4 'used' cells: 14% grey
RULE_LW = 0.8                              # every rule (arrival divider, group rules, bracket)
for _c in (INK, INK2, GREY, MUTED, RULE, FILL):
    assert _c[1:3] == _c[3:5] == _c[5:7], _c
FONT_SIZE = 8.5
#: savefig keywords: same dpi as the vault, no creation date (repeatable bytes for one font)
SAVE_KW = {"dpi": 220, "metadata": {"CreationDate": None}}

# =====================================================================================
# 4. Font: TeX Gyre Pagella from the pinned TeX layer
# =====================================================================================
#: the TeX layer's install root: pipeline/aws/r1/build_env.sh build_tex() "TEXDIR /opt/texlive/2025";
#: its collection-fontsrecommended carries tex-gyre (a test checks both against build_env.sh)
TEXDIR = "/opt/texlive/2025"
PAGELLA_DIR = "texmf-dist/fonts/opentype/public/tex-gyre"
PAGELLA_FILES = {"Regular": "texgyrepagella-regular.otf", "Italic": "texgyrepagella-italic.otf",
                 "Bold": "texgyrepagella-bold.otf", "BoldItalic": "texgyrepagella-bolditalic.otf"}
FAMILY = "TeX Gyre Pagella"
FALLBACK_FAMILY = "DejaVu Serif"           # bundled with matplotlib; explicit test flag only


def _font_cache() -> Path:
    """TrueType copies of the Pagella faces live under output/ (git-ignored), outside output/paper/
    so the paper folder holds only figures and ledgers."""
    from analysis.lib.paths import load_paths
    return load_paths()["output"] / "_fig34_fonts"


FONT_CACHE = _font_cache()


class FontStop(RuntimeError):
    """The thesis font is not available; the final job must not draw in another face."""


def find_pagella(search_dirs=None) -> dict[str, Path] | None:
    """The four Pagella faces, or None. With search_dirs, only those directories are looked in;
    otherwise only the pinned TeX layer's <TEXDIR>/<PAGELLA_DIR> (never a kpsewhich on PATH, which
    could be another TeX installation)."""
    dirs = [Path(d) for d in search_dirs] if search_dirs is not None else [Path(TEXDIR) / PAGELLA_DIR]
    for d in dirs:
        faces = {k: d / f for k, f in PAGELLA_FILES.items()}
        if all(p.is_file() for p in faces.values()):
            return faces
    return None


def _otf_to_ttf(src: Path, dst: Path) -> None:
    """CFF-flavoured OpenType -> TrueType outlines (fontTools' otf2ttf recipe). matplotlib's PDF
    backend embeds fonttype 42 as CIDFontType2 (TrueType); a CFF font there would be malformed."""
    from fontTools.pens.cu2quPen import Cu2QuPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import TTFont, newTable

    font = TTFont(str(src))
    assert font.sfntVersion == "OTTO" and "CFF " in font, f"{src} is not a CFF OpenType font"
    order = font.getGlyphOrder()
    gs = font.getGlyphSet()
    quad = {}
    for name in order:
        tt = TTGlyphPen(gs)
        gs[name].draw(Cu2QuPen(tt, 1.0, reverse_direction=True))
        quad[name] = tt.glyph()
    font["loca"] = newTable("loca")
    font["glyf"] = glyf = newTable("glyf")
    glyf.glyphOrder = order
    glyf.glyphs = quad
    del font["CFF "]
    if "VORG" in font:
        del font["VORG"]
    glyf.compile(font)
    hmtx = font["hmtx"]
    for name, g in glyf.glyphs.items():
        if hasattr(g, "xMin"):
            hmtx[name] = (hmtx[name][0], g.xMin)
    font["maxp"] = maxp = newTable("maxp")
    maxp.tableVersion = 0x00010000
    maxp.maxZones = 1
    for attr in ("maxTwilightPoints", "maxStorage", "maxFunctionDefs", "maxInstructionDefs",
                 "maxStackElements", "maxSizeOfInstructions"):
        setattr(maxp, attr, 0)
    maxp.maxComponentElements = max((len(getattr(g, "components", []) or []) for g in glyf.glyphs.values()),
                                    default=0)
    maxp.compile(font)
    post = font["post"]
    post.formatType = 2.0
    post.extraNames = []
    post.mapping = {}
    post.glyphOrder = order
    font.sfntVersion = "\000\001\000\000"
    tmp = dst.with_suffix(".tmp")
    font.save(str(tmp))
    tmp.replace(dst)


def _ttf_faces(faces: dict[str, Path], cache: Path) -> dict[str, Path]:
    """TrueType copies of the Pagella faces, cached by the source file's sha256."""
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    out = {}
    for k, src in faces.items():
        sha = hashlib.sha256(src.read_bytes()).hexdigest()[:12]
        dst = cache / f"{src.stem}-{sha}.ttf"
        if not dst.is_file():
            _otf_to_ttf(src, dst)
        out[k] = dst
    return out


def use_font(*, font_fallback: bool = False, search_dirs=None, cache=None) -> dict:
    """Set matplotlib's rcParams for the figures and return a JSON-ready record of the font.
    Pagella absent: FontStop, unless font_fallback (an explicit test flag) is set. Text is drawn
    with props(), which names the Pagella file itself, so no other installed face can be picked."""
    import matplotlib

    faces = find_pagella(search_dirs)
    rc = {"font.family": "serif", "font.size": FONT_SIZE, "pdf.fonttype": 42, "svg.fonttype": "none"}
    if faces is None:
        if not font_fallback:
            where = [str(d) for d in search_dirs] if search_dirs is not None else \
                [str(Path(TEXDIR) / PAGELLA_DIR)]
            raise FontStop(f"STOP fig34: {FAMILY} not found ({', '.join(where)}); restore the pinned "
                           f"TeX layer. No silent fallback to {FALLBACK_FAMILY}.")
        matplotlib.rcParams.update({**rc, "font.serif": [FALLBACK_FAMILY]})
        return {"family": FALLBACK_FAMILY, "fallback": True, "files": {}}
    if cache is None:
        raise FontStop("STOP fig34: no font cache directory given")
    ttf = _ttf_faces(faces, cache)
    matplotlib.rcParams.update({**rc, "font.serif": [FAMILY]})
    return {"family": FAMILY, "fallback": False,
            "files": {k: {"otf": faces[k].name, "sha256": hashlib.sha256(faces[k].read_bytes()).hexdigest()}
                      for k in sorted(faces)},
            "_ttf": {k: str(v) for k, v in ttf.items()}}


def face_key(style: str = "normal", weight: str = "normal") -> str:
    return ("Bold" if weight == "bold" else "") + ("Italic" if style == "italic" else "") or "Regular"


def props(font: dict, *, style: str = "normal", weight: str = "normal", size: float = FONT_SIZE):
    """FontProperties for one text: the Pagella file of that face, or the test fallback family."""
    from matplotlib.font_manager import FontProperties
    if font.get("fallback"):
        return FontProperties(family="serif", style=style, weight=weight, size=size)
    return FontProperties(fname=font["_ttf"][face_key(style, weight)], size=size)


def check_coverage(font: dict, drawn: list[tuple[str, str, str]]) -> None:
    """Every character drawn (string, style, weight) has a glyph in the Pagella face that draws it;
    a missing glyph would be a silent box or a per-glyph fallback. No-op for the test fallback."""
    if font.get("fallback"):
        return
    from fontTools.ttLib import TTFont
    cmaps = {}
    for s, style, weight in drawn:
        key = face_key(style, weight)
        if key not in cmaps:
            cmaps[key] = TTFont(font["_ttf"][key]).getBestCmap()
        missing = sorted({ch for ch in s if not ch.isspace() and ord(ch) not in cmaps[key]})
        if missing:
            raise FontStop(f"STOP fig34: {FAMILY} {key} has no glyph for {missing} in {s!r}")


def public_font(font: dict) -> dict:
    """The font record as written into the figure JSON (no local cache paths)."""
    return {k: v for k, v in font.items() if not k.startswith("_")}
