#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fig_star_origins_dots.py — the drawing of Figure 1 (arriving stars' origins): a colour unit-dot map.

Called by analysis/paper/fig_star_origins.py (its draw()); not a script of its own. Moved into the repo
2026-10-01 from the approved prototype (map2/unitdots_coast.py, a working script that is not shipped; dot size 1.5 mm;
2026-10-01: colour version, Natural Earth coastline, smaller dots), with two reviewer fixes:
the codes HK and SG next to the Hong Kong and Singapore rows, and the Sydney and Canberra destination
triangles nudged apart so that they do not touch.

DESIGN. One dot per arrival event (October: 184 dots, 113 / 38 / 33; the counts come from the run's
event tables through canon.counts(), R1 F21, never from literals). The dots of one origin
country form a block drawn on (or right against) that country, filled 10 per row, left to right,
bottom row first, in a fixed discipline order (economics, chemistry, mathematics & statistics), so
counts read in tens and each discipline is one unbroken, connected run (asserted). Where that fill
would split a discipline's run (R1 counts, 2026-10-18: CA, NZ, CH, DE, FR; no October block), the
block is filled serpentine instead, odd rows right to left (block_fill). In the Europe panel a block
taller than EU_MAX_ROWS = 5 rows takes rows of 20 (30, ...) and grows west from the east edge a ten-wide
block would have (block_row; R1: the UK's 96 dots, which in rows of ten would cover York and Sheffield).
Both are author-facing changes to the 2026-10-01 rule made for R1's counts; October's figure keeps that
rule cell for cell. World map on top
(Robinson, centred on 150 E), Europe enlarged below-left (Robinson centred on the panel), legend at
right. Colours: economics dark blue, chemistry orange, mathematics & statistics pale yellow with a dark
rim (so its dots also read in a grey print; checked on a 100-dpi render). One dark triangle per
destination place in Australia (a place is a university's snapshot coordinates; universities in one
city share a place).
  Land: Natural Earth 1:50m land polygons (data/paper_inputs/basemap/ne_50m_land.geojson, public
  domain, pinned), projected with each panel's own Robinson. Rings that cross the panel's antimeridian
  (relative longitude +-180: Greenland on the world map, Chukotka on the Europe panel) are unwrapped
  and clipped at +-180 (Sutherland-Hodgman), so no ring jumps across the map. The coastline is stroked
  only along real coast: the clip edges and Natural Earth's own seams along 180 E (Fiji, Chukotka,
  Wrangel) are not stroked. Antarctica and the sub-Antarctic skerries (all south of 60 S, far below
  the crop) are dropped; rings whose projected extent is under SLIVER_MM are dropped as noise.
  Placement: a block is centred on the origin point nearest the mean of its country's origin points,
  except the TARGET / EU_TARGET countries (a target point on the country, or for New Zealand a place
  just east of North Island); overlapping blocks are pushed apart (layout()); Australia, Tasmania and
  the Europe box are obstacles. Checks (matplotlib Path.contains_points on the Natural Earth rings):
  no dot centre on Australian land; NZ block clear of New Zealand land; UK block on British land while
  the named English / Welsh cities stay uncovered and on land; US block centre on land; each European
  block's centre on land; no two blocks overlap or come closer than GAP_MM; every block in its panel.
  Words: the three legend labels and seven two-letter codes (CA, NL, BE, CH, AT, HK, SG: only where
  position alone is ambiguous), 8 pt with a thin white halo; nothing else (the course word count
  includes figure text). The text whitelist is asserted on the figure's text objects and, where
  poppler's pdftotext is on PATH, on the PDF's text layer.
  Destination nudge (reviewer, 2026-10-01): at their true places the Sydney and Canberra triangles
  overlap (1.2 mm apart, the triangles are 1.9 mm). nudge_destinations() moves the two apart along the
  axis that separates them fastest (perpendicular to the facing triangle edges) by the least amount
  that leaves DEST_CLEAR_MM of clear land between their white rims, sharing the move equally unless
  one of them would then come closer than DEST_CLEAR_MM to a third triangle (at cal2026-10 Canberra
  to Deakin's, at Burwood in Melbourne), which then moves only as far as it can and the other takes
  the rest. The nudge is recorded (ledger key figure_destination_nudge_mm, in mm on the 15-cm figure,
  east and north). At cal2026-10: Sydney 0.683 mm east-north-east (about 140 km at the map's scale;
  its triangle now straddles the coast), Canberra 0.154 mm west-south-west (about 30 km); before the
  nudge the two rim outlines overlapped by 0.74 mm. Melbourne and Burwood (Deakin) lie 0.07 mm apart
  and draw as one triangle (not separated).
  Philippines: its one dot is placed 0.27 degrees (0.14 mm) south of its origin (Los Banos), still on
  Luzon, so that the HK code (added 2026-10-01, right of its row) passes the label rule.
"""
from __future__ import annotations

import collections
import csv
import io
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patheffects as pe  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Circle, FancyBboxPatch, PathPatch, Polygon, Rectangle  # noqa: E402
from matplotlib.path import Path as MPath  # noqa: E402
from matplotlib.text import Text  # noqa: E402

import analysis.paper.fig_star_origins as F  # noqa: E402
from analysis.lib import canon  # noqa: E402

NE_REL = F.src("paper_inputs", "basemap/ne_50m_land.geojson")     # pinned in F.PINS (R1 F7: root from config)
NE_FEATURES = 1420

#: (event-table key, ledger prefix, legend label) — also the fill order inside a block
DISC = F.FIELDS


def expected_counts() -> dict:
    """Events per field in the run in force: canon.counts()['events'] (October: config/r1/counts_B0.json,
    113 / 38 / 33; an M canon: <canon>/cal/counts.json). R1 F21: these replace the 184-dot literals."""
    ev = canon.counts()["events"]
    return {k: int(ev[k]) for k, _p, _l in DISC}


ST = {"fill": {"econ": "#1f4f94", "chemistry": "#e87e34", "math_stats": "#fae99a"},
      "rim": {"econ": ("#163a6e", 0.40), "chemistry": ("#9e511e", 0.40), "math_stats": ("#24221e", 0.65)},
      "land": "#ebe9e4", "coast": ("#b9b4aa", 0.30),
      "aus": ("#d7d2c8", "#57534c", 0.50),
      "frame": ("#5f5b54", 0.50), "box_fill": ("white", 0.60),
      "label": "#2b2925", "dest": "#1c1b19", "backing": "white"}

# ---- marks: everything tied to the dot scales with it
DOT_MM = 1.5                          # dot diameter (approved 2026-10-01)
SC = DOT_MM / 2.2                     # scale against the 2.2 mm dots the layout was first tuned for
PITCH_MM = round(2.6 * SC, 2)         # centre-to-centre spacing inside a block (2.6 at 2.2 mm)
BACK_MM = round(0.30 * SC, 2)         # white margin of the block backing round the outer dots
GAP_MM = round(1.1 * SC, 2)           # minimum clear space between two blocks / a block and an obstacle
COAST_GAP_MM = round(0.5 * SC, 2)     # a block set beside its country ("east_of_land"): gap to the coast
LABEL_GAP_MM = round(0.9 * SC, 2)     # block edge -> label anchor
ROW = 10                              # dots per row
EU_MAX_ROWS = 5                       # Europe panel: most rows a block may have before it widens (block_row, R1)
DEST_MM = 1.9                         # destination triangle size (matplotlib marker '^': width = height)
DEST_EDGE_PT = 0.35                   # white rim of the destination triangles (stroke width, mitred)
DEST_CLEAR_MM = 0.10                  # clear land required between the white rims of two triangles
COINCIDENT_MM = 0.10                  # places closer than this draw as one triangle and are not separated
SLIVER_MM = 0.2                       # land rings with a smaller projected extent are dropped
CLIP_MARGIN_MM = 1.0                  # land is clipped to the panel frame grown by this much

W_CM = F.FIG_WIDTH_CM                 # 15 cm, the thesis text width
H_CM = 12.0                           # figure height (budget 12 cm)
H_MAX_CM = 12.0
M_CM = 0.03                           # outer margin: keeps the frame lines whole at the page edge
LEGEND_PT = F.FONT_PT                 # legend text (9 pt)
LABEL_PT = 8.0                        # country codes
HALO_PT = 2.2                         # white halo round the country codes (stroke width)
PNG_DPI = 200                         # output/paper/fig_star_origins.png (preview)
PRINT_DPI = 100                       # in-memory render for the maths-rim check
# ---- world map crop (Robinson, central meridian F.CENTRAL_LON)
LAT_LO = -47.0                        # keeps NZ's South Island; origins reach -45.9, Tasmania -43.6
TOP_PAD_MM, LEFT_PAD_MM = 1.6, 1.6    # room above / left of the Europe box
RIGHT_X_EXTRA_MM = 3.2                # room right of Rio de Janeiro (the easternmost origin)
# ---- Europe panel
EU_LAT = (39.4, 59.7)                 # Madrid 40.4 N .. Stockholm 59.3 N (Seville, 37.4 N, falls just south)
EU_LON = (-14.0, 23.0)                # west / east edge at the panel's mid-latitude
EU_LON_C = (EU_LON[0] + EU_LON[1]) / 2   # the panel's projection meridian (panel centred on it)
GAP_PANELS_CM = 0.30                  # world map bottom -> Europe panel top
LEG_MIN_CLEAR_MM = 4.0                # legend: at least this much room to the page edge and the panel
#: block-centre targets (lon, lat) where the country's own origin points would put the block off the
#: country or across a neighbour; every other block targets its origin point nearest the mean of its
#: origin points.
TARGET = {"US": ("centre", -97.5, 37.0), "CA": ("centre", -101.0, 55.5),
          "NZ": ("east_of_land", 165.0, 179.9, -38.9),
          "VN": ("centre", 108.4, 14.6),          # central coast: Hanoi would put the dot against the HK row
          "MY": ("centre", 116.8, 5.6),           # Sabah: Miri would put the dot against the SG row
          "PH": ("centre", 121.26, 13.9)}         # Los Banos (14.17 N) moved 0.27 deg (0.14 mm) south, still
#                                                   on Luzon, so that the HK code (2026-10-01) stays clearly
#                                                   nearer its own row than the PH dot (1.15 -> 1.29 mm)
EU_TARGET = {"GB": ("centre", 1.3, 56.2), "IE": ("centre", -8.0, 53.3), "NL": ("centre", 5.4, 52.5),
             "BE": ("centre", 4.6, 50.6), "DE": ("centre", 10.8, 51.4), "FR": ("centre", 1.5, 48.0),
             "CH": ("centre", 8.2, 46.7), "AT": ("centre", 13.0, 47.4), "IT": ("centre", 10.2, 44.9),
             "ES": ("centre", -3.7, 41.0), "SE": ("centre", 14.0, 57.4)}
#: country codes (only where position alone is ambiguous): cc -> (panel, side of the block).
#: HK and SG added 2026-10-01 (reviewer). HK sits right of its row: on the left the Vietnam dot is 0.92 mm
#: from the code, closer than the label rule allows (check_labels: own row + 1 mm).
LABELS = {"CA": ("world", "left"), "HK": ("world", "right"), "SG": ("world", "left"),
          "NL": ("europe", "left"), "BE": ("europe", "left"),
          "CH": ("europe", "left"), "AT": ("europe", "right")}
#: the only words in the figure: the legend labels and the codes above
FIGURE_TEXT = tuple(sorted([lab for _k, _p, lab in DISC] + list(LABELS)))
#: places that must stay visible under / around the UK block (lon, lat), and one it must cover
UK_VISIBLE = {"London": (-0.13, 51.5), "Sheffield": (-1.47, 53.38), "Exeter": (-3.53, 50.72),
              "Cardiff": (-3.18, 51.48), "York": (-1.08, 53.96)}
UK_COVERED = {"Aberdeen": (-2.1, 57.15)}
PROBLEMS: list = []                   # label problems: fatal at the end of draw()


# ------------------------------------------------------------------------------------------ data
def check_events(ev: list[dict], L: dict, expected: dict | None = None) -> list[dict]:
    """The events in the per-event CSV's order (discipline, event row), checked against the ledger and the
    run's event counts (expected_counts(); October 184 = 113 / 38 / 33): every origin found, per-country
    counts per discipline and pooled."""
    expected = expected_counts() if expected is None else expected
    order = {k: i for i, (k, _p, _l) in enumerate(DISC)}
    rows = sorted(ev, key=lambda r: (order[r["discipline"]], r["event_row"]))
    c = collections.Counter(r["discipline"] for r in rows)
    assert {k: c.get(k, 0) for k in expected} == expected and set(c) <= set(expected), (c, expected)
    assert len(rows) == sum(expected.values()) and all(r["origin_status"] == "found" for r in rows)
    for key, pre, _l in DISC:
        got = collections.Counter(r["origin_country"] for r in rows if r["discipline"] == key)
        assert dict(got) == L[f"{pre}_country_counts"], (key, got)
        assert sum(got.values()) == expected[key]
    pooled = collections.Counter(r["origin_country"] for r in rows)
    assert dict(pooled) == L["pooled_country_counts"], pooled
    return rows


def destinations(rows: list[dict]) -> list[dict]:
    """One mark per destination place: (lon, lat) of the event schools' universities from the pinned
    inputs, with the snapshot city and the schools at that place; sorted by (lon, lat)."""
    base = F.src("paper_inputs", "star_origins_2026-10") + "/"
    dest = {r["school"]: r["institution_id"] for r in csv.DictReader(io.StringIO(F.read_pinned(base + "destinations.csv")))}
    inst = {r["institution_id"]: r for r in csv.DictReader(io.StringIO(F.read_pinned(base + "institutions.csv")))}
    out: dict = {}
    for r in rows:
        i = inst[dest[r["school"]]]
        assert i["country_code"] == "AU", i
        k = (float(i["longitude"]), float(i["latitude"]))
        m = out.setdefault(k, {"lon": k[0], "lat": k[1], "city": i["city"], "schools": set()})
        assert m["city"] == i["city"], (k, m["city"], i["city"])
        m["schools"].add(r["school"])
    return [out[k] for k in sorted(out)]


# ------------------------------------------------------------------------------------------ land
def load_land() -> list[list[np.ndarray]]:
    """Natural Earth 1:50m land: a list of polygons, each [exterior, hole, ...] of (lon, lat) rings
    without the closing vertex. The file's sha256 is checked by F.read_pinned. Drops everything
    south of 60 S."""
    G = json.loads(F.read_pinned(NE_REL))
    assert len(G["features"]) == NE_FEATURES
    polys = []
    for f in G["features"]:
        g = f["geometry"]
        assert g["type"] in ("Polygon", "MultiPolygon"), g["type"]
        for p in ([g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]):
            rings = [np.asarray(r, float)[:-1] for r in p if len(r) >= 4]   # a 1-point "hole" is skipped
            if rings and rings[0][:, 1].max() > -60.0:
                polys.append(rings)
    return polys


def _area(P: np.ndarray) -> float:
    x, y = P[:, 0], P[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _clip(P: np.ndarray, axis: int, c: float, keep_le: bool) -> np.ndarray:
    """Sutherland-Hodgman: the part of the closed ring P with P[:, axis] <= c (keep_le) or >= c.
    New vertices land exactly on the line."""
    s = 1.0 if keep_le else -1.0
    o = 1 - axis
    out = []
    for i in range(len(P)):
        A, B = P[i - 1], P[i]
        fa, fb = s * (A[axis] - c), s * (B[axis] - c)
        if (fa > 0) != (fb > 0):
            t = (c - A[axis]) / (B[axis] - A[axis])
            q = [0.0, 0.0]
            q[axis], q[o] = c, A[o] + t * (B[o] - A[o])
            out.append(q)
        if fb <= 0:
            out.append((B[0], B[1]))
    return np.array(out, float).reshape(-1, 2)


def split_ring(ll: np.ndarray, C: float) -> list[np.ndarray]:
    """(relative lon, lat) pieces of a ring for a map centred on C: a ring that crosses the map's
    antimeridian (relative lon +-180) is unwrapped and clipped at +-180 into its pieces."""
    rel = (ll[:, 0] - C + 180.0) % 360.0 - 180.0
    d = np.diff(np.r_[rel, rel[:1]])
    if not np.any(np.abs(d) > 180.0):
        return [np.column_stack([rel, ll[:, 1]])]
    wrap = np.where(d > 180.0, -360.0, np.where(d < -180.0, 360.0, 0.0))
    assert abs(float(np.sum(wrap))) < 1e-9, "ring winds round a pole"
    pts = np.column_stack([rel + np.r_[0.0, np.cumsum(wrap[:-1])], ll[:, 1]])
    out = []
    for k in range(int(np.floor((pts[:, 0].min() + 180.0) / 360.0)), int(np.floor((pts[:, 0].max() + 180.0) / 360.0)) + 1):
        Q = _clip(pts - [360.0 * k, 0.0], 0, -180.0, keep_le=False)
        if len(Q) >= 3:
            Q = _clip(Q, 0, 180.0, keep_le=True)
        if len(Q) >= 3 and abs(_area(Q)) > 1e-9:
            out.append(Q)
    return out


def project_land(polys, C: float, xlim, ylim, u: float) -> dict:
    """Project the land for one panel (Robinson centred on C) and clip it to the panel frame grown by
    CLIP_MARGIN_MM (the clip edges lie outside the frame, so the visible land is untouched). Returns the
    polygons that reach the panel, each {"xy": [rings], "ll": [rings as lon/lat], "seam": [per-edge
    bool: not coast], "aus": bool}, and counts of what was split / dropped."""
    m = CLIP_MARGIN_MM / 10.0 * u
    rect = (xlim[0] - m, ylim[0] - m, xlim[1] + m, ylim[1] + m)
    out, n_split, n_sliver, n_vert = [], 0, 0, 0
    for rings in polys:
        lon0, lat0 = rings[0][:, 0], rings[0][:, 1]
        aus = bool((lon0.min() >= 112) & (lon0.max() <= 155) & (lat0.min() >= -45) & (lat0.max() <= -10))
        pieces = split_ring(rings[0], C)
        holes = [h for r in rings[1:] for h in split_ring(r, C)]
        if len(pieces) != 1:
            n_split += 1
            assert not holes, "a split ring with holes"
        for E in pieces:
            xy_rings, ll_rings, seams = [], [], []
            for k, Q in enumerate([E] + holes):
                x, y = F.robinson(Q[:, 0], Q[:, 1])
                xy = np.column_stack([x, y])
                if x.max() < rect[0] or x.min() > rect[2] or y.max() < rect[1] or y.min() > rect[3]:
                    if k == 0:
                        break                               # outside the panel
                    continue
                if max(np.ptp(x), np.ptp(y)) / u * 10.0 < SLIVER_MM:
                    n_sliver += 1
                    if k == 0:
                        break
                    continue
                for axis, c, le in ((0, rect[0], False), (0, rect[2], True), (1, rect[1], False), (1, rect[3], True)):
                    if (xy[:, axis].min() < c) if not le else (xy[:, axis].max() > c):
                        xy = _clip(xy, axis, c, le)
                        if len(xy) < 3:
                            break
                if len(xy) < 3 or abs(_area(xy)) < 1e-12:
                    if k == 0:
                        break
                    continue
                rel, lat = inv_robinson(xy[:, 0], xy[:, 1], 0.0)
                lon = (rel + C + 180.0) % 360.0 - 180.0
                on_clip = np.abs(np.abs(rel) - 180.0) < 1e-6              # map antimeridian (clip line)
                on_seam = np.abs(np.abs(lon) - 180.0) < 1e-6              # Natural Earth's own 180 E seam
                seam = (on_clip & np.roll(on_clip, -1)) | (on_seam & np.roll(on_seam, -1))
                for axis, c in ((0, rect[0]), (0, rect[2]), (1, rect[1]), (1, rect[3])):   # frame-clip edges
                    on = xy[:, axis] == c
                    seam |= on & np.roll(on, -1)
                # exterior anticlockwise, holes clockwise (fills right under either fill rule)
                if (_area(xy) > 0) != (k == 0):
                    xy, lon, lat, seam = xy[::-1], lon[::-1], lat[::-1], np.roll(seam[::-1], -1)
                xy_rings.append(xy)
                ll_rings.append(np.column_stack([lon, lat]))
                seams.append(seam)
                n_vert += len(xy)
            if xy_rings:
                out.append({"xy": xy_rings, "ll": ll_rings, "seam": seams, "aus": aus})
    return {"polys": out, "n_split": n_split, "n_sliver": n_sliver, "n_vert": n_vert}


def fill_path(polys) -> MPath:
    verts, codes = [], []
    for p in polys:
        for xy in p["xy"]:
            verts += list(xy) + [xy[0]]
            codes += [MPath.MOVETO] + [MPath.LINETO] * (len(xy) - 1) + [MPath.CLOSEPOLY]
    return MPath(np.array(verts), codes)


def coast_path(polys) -> MPath:
    """The coastline: every ring edge except the antimeridian clip edges and Natural Earth's seams."""
    verts, codes = [], []
    for p in polys:
        for xy, seam in zip(p["xy"], p["seam"]):
            n = len(xy)
            if not seam.any():
                verts += list(xy) + [xy[0]]
                codes += [MPath.MOVETO] + [MPath.LINETO] * (n - 1) + [MPath.CLOSEPOLY]
                continue
            s0 = int(np.flatnonzero(seam)[0])
            run = []
            for j in range(1, n + 1):                      # edges s0+1 .. s0+n (edge i: vertex i -> i+1)
                e = (s0 + j) % n
                if seam[e]:
                    if len(run) >= 2:
                        verts += run
                        codes += [MPath.MOVETO] + [MPath.LINETO] * (len(run) - 1)
                    run = []
                else:
                    if not run:
                        run = [xy[e]]
                    run.append(xy[(e + 1) % n])
            if len(run) >= 2:
                verts += run
                codes += [MPath.MOVETO] + [MPath.LINETO] * (len(run) - 1)
    return MPath(np.array(verts), codes)


def ring_paths(polys) -> list[MPath]:
    """One closed path per exterior ring (holes ignored: point-in-land tests are made away from lakes)."""
    return [MPath(np.vstack([p["xy"][0], p["xy"][0][:1]]), closed=True) for p in polys]


def on_land(paths: list[MPath], x, y) -> np.ndarray:
    P = np.column_stack([np.atleast_1d(x), np.atleast_1d(y)])
    hit = np.zeros(len(P), bool)
    for pa in paths:
        hit |= pa.contains_points(P)
    return hit


def east_edge(polys, lo0: float, lo1: float, ylo: float, yhi: float) -> float:
    """Largest projected x of land whose longitude is in [lo0, lo1], within the band ylo <= y <= yhi."""
    best = -np.inf
    for p in polys:
        for xy, ll in zip(p["xy"], p["ll"]):
            A, B = xy, np.roll(xy, -1, axis=0)
            la, lb = ll[:, 0], np.roll(ll[:, 0], -1)
            ok = (la >= lo0) & (la <= lo1) & (lb >= lo0) & (lb <= lo1)
            inb = ok & (A[:, 1] >= ylo) & (A[:, 1] <= yhi)
            if inb.any():
                best = max(best, float(A[inb, 0].max()))
            for lev in (ylo, yhi):
                cr = ok & ((A[:, 1] - lev) * (B[:, 1] - lev) < 0)
                if cr.any():
                    t = (lev - A[cr, 1]) / (B[cr, 1] - A[cr, 1])
                    best = max(best, float((A[cr, 0] + t * (B[cr, 0] - A[cr, 0])).max()))
    return best


# ------------------------------------------------------------------------------------------ geometry
_GRID = np.arange(0.0, 91.0, 5.0)


def inv_robinson(x, y, clon: float):
    """Inverse of F.robinson (exact: the forward map is piecewise linear in latitude)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    lat = np.sign(y) * np.interp(np.abs(y) / 1.3523, F._ROB_Y, _GRID)
    lon = clon + np.degrees(x / (0.8487 * np.interp(np.abs(lat), _GRID, F._ROB_X)))
    return lon, lat


def eu_rel(lon):
    return (np.asarray(lon, dtype=float) - EU_LON_C + 180.0) % 360.0 - 180.0


def eu_proj(lon, lat):
    return F.robinson(eu_rel(lon), lat)


def w_proj(lon, lat):
    return F.robinson(F.rel_lon(lon), lat)


# ------------------------------------------------------------------------------------------ destinations
RIM_MM = DEST_EDGE_PT / 2 / 72 * 25.4          # outer half of the white rim


def dest_triangle(grow_mm: float = 0.0) -> np.ndarray:
    """Vertices (mm, relative to the place) of a destination triangle as matplotlib draws marker '^' at
    size DEST_MM: apex (0, s/2), base corners (-s/2, -s/2), (s/2, -s/2). grow_mm > 0 gives the outline
    of the triangle with its white rim (outer half of the stroke, mitred corners): the triangle scaled
    about its incentre so that every edge moves out by grow_mm."""
    s = DEST_MM
    V = np.array([[0.0, s / 2], [-s / 2, -s / 2], [s / 2, -s / 2]])
    side = np.array([np.linalg.norm(V[1] - V[2]), np.linalg.norm(V[2] - V[0]), np.linalg.norm(V[0] - V[1])])
    inc = side @ V / side.sum()
    rho = 2.0 * abs(_area(V)) / side.sum()
    return inc + (V - inc) * (rho + grow_mm) / rho


def _seg_dist(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    ab = b - a
    t = min(max(float(np.dot(p - a, ab) / np.dot(ab, ab)), 0.0), 1.0)
    return float(np.hypot(*(a + t * ab - p)))


def sat_gap(P: np.ndarray, Q: np.ndarray) -> tuple[float, np.ndarray]:
    """Largest gap between convex polygons P and Q over the separating axes (their edge normals), with
    that axis as a unit vector pointing from P towards Q. Negative: they overlap, and minus the gap is
    the shortest translation that separates them (along the axis)."""
    best, axis = -math.inf, None
    for R in (P, Q):
        for i in range(len(R)):
            e = R[(i + 1) % len(R)] - R[i]
            n = np.array([e[1], -e[0]]) / math.hypot(e[0], e[1])
            for m in (n, -n):
                g = float((Q @ m).min() - (P @ m).max())
                if g > best:
                    best, axis = g, m
    return best, axis


def poly_dist(P: np.ndarray, Q: np.ndarray) -> float:
    """Euclidean distance between convex polygons (negative: overlap depth, from sat_gap)."""
    g, _m = sat_gap(P, Q)
    if g <= 0:
        return g
    return min(_seg_dist(p, R[i], R[(i + 1) % len(R)]) for S, R in ((P, Q), (Q, P)) for p in S for i in range(len(R)))


def nudge_destinations(D: list[dict], u: float) -> dict:
    """Separate destination triangles that touch (module docstring, 'Destination nudge'). Positions in
    mm on the figure; returns the nudge (mm, east and north) per mark, the separated pairs, the
    coincident pairs (one drawn triangle; not separated) and the clearances after the nudge."""
    pos = np.array([[float(v) / u * 10.0 for v in w_proj(m["lon"], m["lat"])] for m in D])
    O = dest_triangle(RIM_MM)
    n = len(D)
    nudge = np.zeros((n, 2))
    coincident = [(i, j) for i in range(n) for j in range(i + 1, n)
                  if math.hypot(*(pos[i] - pos[j])) < COINCIDENT_MM]
    together = {k for p in coincident for k in p}

    def dist(i: int, j: int) -> float:
        return poly_dist(O + pos[i] + nudge[i], O + pos[j] + nudge[j])

    def pairs() -> list[tuple[int, int]]:
        return [(i, j) for i in range(n) for j in range(i + 1, n) if (i, j) not in coincident]

    touching = [(i, j) for i, j in pairs() if dist(i, j) < DEST_CLEAR_MM]
    separated = []
    for i, j in touching:
        assert i not in together and j not in together, "a coincident place touches a third one"
        g, m = sat_gap(O + pos[i] + nudge[i], O + pos[j] + nudge[j])   # m: from i towards j
        T = DEST_CLEAR_MM - g                                              # total move along m

        def slack(k: int, d: np.ndarray, partner: int) -> float:
            """How far mark k can move along d before it comes within DEST_CLEAR_MM of a third mark."""
            def ok(t: float) -> bool:
                keep = nudge[k].copy()
                nudge[k] = keep + t * d
                good = all(dist(k, q) >= DEST_CLEAR_MM for q in range(n) if q not in (k, partner))
                nudge[k] = keep
                return good
            assert ok(0.0), (D[k]["city"], "already too close to a third triangle")
            if ok(T):
                return T
            lo, hi = 0.0, T
            for _ in range(60):
                mid = (lo + hi) / 2
                lo, hi = (mid, hi) if ok(mid) else (lo, mid)
            return lo
        si, sj = slack(i, -m, j), slack(j, m, i)
        b = min(T / 2, si)                 # mark i moves b against m, mark j moves a along m
        a = T - b
        if a > sj:
            a, b = sj, T - sj
        assert a <= sj + 1e-12 and b <= si + 1e-12, (D[i]["city"], D[j]["city"], "no nudge clears both")
        nudge[i] -= b * m
        nudge[j] += a * m
        separated.append((i, j))
    clear = {(D[i]["city"], D[j]["city"]): dist(i, j) for i, j in pairs()}
    assert min(clear.values()) >= DEST_CLEAR_MM - 1e-9, clear
    for i, j in separated:          # the least nudge along the axis: the pair ends exactly at the clearance
        assert abs(dist(i, j) - DEST_CLEAR_MM) < 1e-6, (D[i]["city"], D[j]["city"], dist(i, j))
    return {"pos_mm": pos, "nudge_mm": nudge, "separated": [(D[i]["city"], D[j]["city"]) for i, j in separated],
            "coincident": [(D[i]["city"], D[j]["city"], round(math.hypot(*(pos[i] - pos[j])), 3)) for i, j in coincident],
            "clear_mm": clear,
            "unnudged_mm": {(D[i]["city"], D[j]["city"]): poly_dist(O + pos[i], O + pos[j]) for i, j in separated}}


# ------------------------------------------------------------------------------------------ blocks
def block_row(n: int, max_rows: int | None = None) -> int:
    """Dots per row of a block of n dots: ROW, or, when a ROW-wide block would be taller than max_rows,
    the fewest whole tens that keep it within max_rows rows (None: no limit).
    R1 (2026-10-18; an author-facing change to the 2026-10-01 rule): the Europe panel sets EU_MAX_ROWS = 5,
    the height of October's tallest European block (the UK, 49 dots), so no October block changes. At R1's
    counts the UK block (96 dots) would be 10 rows (17.8 mm) tall in rows of ten, and only 8 rows fit
    between York and the panel's top, so it would cover York and Sheffield; in rows of 20 it is 5 rows tall.
    The world map sets no limit: R1's US block (101 dots) passes every world check in 11 rows of ten, and in
    rows of 20 it would sit 0.15 mm under the CA code (the label rule needs it clearly farther than CA's row)."""
    if max_rows is None:
        return ROW
    return ROW * max(1, math.ceil(n / (ROW * max_rows)))


def block_dims(n: int, row: int = ROW) -> tuple[int, int]:
    return min(n, row), math.ceil(n / row)


def fill_cells(n: int, serpentine: bool = False, row: int = ROW) -> list[tuple[int, int]]:
    """Grid cell (column, row) of the k-th dot, `row` dots per row: left to right, bottom row first;
    serpentine: odd rows right to left (block_fill says when)."""
    return [(row - 1 - k % row if serpentine and (k // row) % 2 else k % row, k // row) for k in range(n)]


def backing_spans(n: int, serpentine: bool = False, row: int = ROW) -> list[tuple[int, int, int, int]]:
    """The white backing of a block as cell spans (col0, col1, row0, row1), ends exclusive: the full
    rows, then the part-filled top row (on the right when that row runs right to left)."""
    cols = min(n, row)
    full, rem = divmod(n, row)
    c0 = cols - rem if serpentine and full % 2 else 0
    return [sp for sp in ((0, cols, 0, full), (c0, c0 + rem, full, full + 1)) if sp[1] > sp[0] and sp[3] > sp[2]]


DISC_ORDER = [(k, i) for i, (k, *_r) in enumerate(DISC)]


def split_runs(disc: list[str], serpentine: bool = False, row: int = ROW) -> list[str]:
    """The disciplines whose cells in the fill are not one 4-connected set."""
    cells = fill_cells(len(disc), serpentine, row)
    out = []
    for d in sorted(set(disc), key=[k for k, _ in DISC_ORDER].index):
        S = {cells[k] for k, dd in enumerate(disc) if dd == d}
        seen, todo = set(), [next(iter(S))]
        while todo:
            c = todo.pop()
            if c in seen:
                continue
            seen.add(c)
            todo += [(c[0] + a, c[1] + b) for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1)) if (c[0] + a, c[1] + b) in S]
        if seen != S:
            out.append(d)
    return out


def block_fill(disc: list[str], row: int = ROW) -> bool:
    """True when a block is filled serpentine. The 2026-10-01 rule fills left to right, bottom row first;
    where that splits a discipline's run (R1 2026-10-18: CA, NZ, CH, DE and FR at R1's counts; no October
    block), odd rows run right to left instead, which keeps any run of consecutive dots connected."""
    return bool(split_runs(disc, False, row))


def assert_runs_connected(cc: str, disc: list[str], serpentine: bool = False, row: int = ROW) -> None:
    """Each discipline inside a block is one run in fill order AND a 4-connected set of cells."""
    order = [d for d, _ in DISC_ORDER]
    assert disc == sorted(disc, key=order.index), (cc, "not in discipline order")
    bad = split_runs(disc, serpentine, row)
    assert not bad, (cc, bad[0] if bad else None, "discipline run is split inside the block")


def make_blocks(groups: dict[str, list[dict]], proj, u: float, targets: dict, land=None,
                max_rows: int | None = None) -> list[dict]:
    p = PITCH_MM / 10 * u
    edge = (DOT_MM / 2 + BACK_MM) / 10 * u
    order = {k: i for k, i in DISC_ORDER}
    out = []
    for cc, rs in groups.items():
        n = len(rs)
        row = block_row(n, max_rows)
        cols, nrows = block_dims(n, row)
        hw, hh = (cols - 1) * p / 2 + edge, (nrows - 1) * p / 2 + edge
        x, y = proj(np.array([float(r["origin_lon"]) for r in rs]), np.array([float(r["origin_lat"]) for r in rs]))
        x, y = np.atleast_1d(x), np.atleast_1d(y)
        mx, my = float(np.mean(x)), float(np.mean(y))
        k = int(np.argmin((x - mx) ** 2 + (y - my) ** 2))
        tx, ty = float(x[k]), float(y[k])
        if cc in targets and targets[cc][0] == "east_of_land":
            # block's vertical centre at latitude la; its left edge COAST_GAP_MM east of the easternmost
            # Natural Earth land with longitude in [lo0, lo1] inside the block's vertical span
            _mode, lo0, lo1, la = targets[cc]
            ty = float(proj(0.5 * (lo0 + lo1), la)[1])
            xe = east_edge(land, lo0, lo1, ty - hh, ty + hh)
            assert np.isfinite(xe), (cc, "no land beside the block")
            tx = xe + COAST_GAP_MM / 10 * u + hw
        elif cc in targets:
            _mode, lo, la = targets[cc]
            px, py = proj(lo, la)
            tx, ty = float(px), float(py)
        if cols > ROW:
            # a widened block keeps the east edge a ten-wide block would have and grows west (R1: the UK
            # block, over the Irish Sea rather than across the North Sea onto Denmark's block)
            assert not (cc in targets and targets[cc][0] == "east_of_land"), (cc, "widened block beside a coast")
            tx -= (cols - ROW) * p / 2
        disc = sorted((r["discipline"] for r in rs), key=lambda d: order[d])
        serp = block_fill(disc, row)
        assert_runs_connected(cc, disc, serp, row)
        out.append({"cc": cc, "n": n, "cols": cols, "rows": nrows, "row": row, "disc": disc, "serp": serp,
                    "px": x, "py": y, "ax": tx, "ay": ty, "cx": tx, "cy": ty, "hw": hw, "hh": hh})
    out.sort(key=lambda b: (-b["n"], b["cc"]))
    return out


def block_rules(B: list[dict]) -> dict:
    """The blocks that leave the 2026-10-01 fill: serpentine ones and widened ones (cc -> dots per row)."""
    return {"serpentine": sorted(b["cc"] for b in B if b["serp"]),
            "wide": {b["cc"]: b["row"] for b in sorted(B, key=lambda b: b["cc"]) if b["row"] > ROW}}


def layout(B: list[dict], u: float, bounds, obstacles=()) -> list[dict]:
    """Push overlapping blocks apart (a heavier block moves less), with a weak pull back to the target;
    fixed rectangles push blocks out; blocks stay inside `bounds`."""
    gap = GAP_MM / 10 * u
    bx0, by0, bx1, by1 = bounds
    for it in range(5000):
        pull = 0.03 if it < 4500 else 0.0
        for b in B:
            b["cx"] += pull * (b["ax"] - b["cx"])
            b["cy"] += pull * (b["ay"] - b["cy"])
        for i in range(len(B)):
            a = B[i]
            for j in range(i + 1, len(B)):
                b = B[j]
                dx, dy = b["cx"] - a["cx"], b["cy"] - a["cy"]
                ox = a["hw"] + b["hw"] + gap - abs(dx)
                oy = a["hh"] + b["hh"] + gap - abs(dy)
                if ox <= 0 or oy <= 0:
                    continue
                fa, fb = b["n"] / (a["n"] + b["n"]), a["n"] / (a["n"] + b["n"])
                tie = 1.0 if a["cc"] < b["cc"] else -1.0
                if ox < oy:
                    s = math.copysign(1.0, dx) if dx else tie
                    a["cx"] -= s * ox * fa
                    b["cx"] += s * ox * fb
                else:
                    s = math.copysign(1.0, dy) if dy else tie
                    a["cy"] -= s * oy * fa
                    b["cy"] += s * oy * fb
            for (x0, y0, x1, y1) in obstacles:
                ox = min(a["cx"] + a["hw"] + gap, x1) - max(a["cx"] - a["hw"] - gap, x0)
                oy = min(a["cy"] + a["hh"] + gap, y1) - max(a["cy"] - a["hh"] - gap, y0)
                if ox > 0 and oy > 0:
                    if ox < oy:
                        a["cx"] += ox if a["cx"] > (x0 + x1) / 2 else -ox
                    else:
                        a["cy"] += oy if a["cy"] > (y0 + y1) / 2 else -oy
            a["cx"] = min(max(a["cx"], bx0 + a["hw"]), bx1 - a["hw"])
            a["cy"] = min(max(a["cy"], by0 + a["hh"]), by1 - a["hh"])
    return B


def check_layout(B: list[dict], u: float, bounds, obstacles=(), where: str = "") -> None:
    """No two blocks overlap (and keep the minimum gap); no block overlaps an obstacle; every block
    lies inside the frame."""
    tol = 1e-9
    gap = GAP_MM / 10 * u
    for i, a in enumerate(B):
        assert bounds[0] - tol <= a["cx"] - a["hw"] and a["cx"] + a["hw"] <= bounds[2] + tol, (where, a["cc"], "x out")
        assert bounds[1] - tol <= a["cy"] - a["hh"] and a["cy"] + a["hh"] <= bounds[3] + tol, (where, a["cc"], "y out")
        for b in B[i + 1:]:
            clear = max(abs(a["cx"] - b["cx"]) - a["hw"] - b["hw"], abs(a["cy"] - b["cy"]) - a["hh"] - b["hh"])
            assert clear >= gap * 0.98, (where, a["cc"], b["cc"], "blocks overlap / closer than the gap", clear / u * 10)
        for (x0, y0, x1, y1) in obstacles:
            ox = min(a["cx"] + a["hw"], x1) - max(a["cx"] - a["hw"], x0)
            oy = min(a["cy"] + a["hh"], y1) - max(a["cy"] - a["hh"], y0)
            assert ox <= 0 or oy <= 0, (where, a["cc"], "block on an obstacle")


def block_offsets(B: list[dict], u: float) -> None:
    """Distance (mm) from each block to the nearest of its country's origin points (reported)."""
    for b in B:
        qx = np.clip(b["px"], b["cx"] - b["hw"], b["cx"] + b["hw"])
        qy = np.clip(b["py"], b["cy"] - b["hh"], b["cy"] + b["hh"])
        b["off_mm"] = float(np.min(np.hypot(b["px"] - qx, b["py"] - qy))) / u * 10


def dot_centres(b: dict, u: float) -> np.ndarray:
    p = PITCH_MM / 10 * u
    x0 = b["cx"] - (b["cols"] - 1) * p / 2
    y0 = b["cy"] - (b["rows"] - 1) * p / 2
    return np.array([(x0 + i * p, y0 + j * p) for i, j in fill_cells(b["n"], b["serp"], b["row"])])


def draw_blocks(ax, B: list[dict], u: float, counter: collections.Counter, maths: list) -> None:
    p = PITCH_MM / 10 * u
    r_dot = DOT_MM / 20 * u
    r_back = r_dot + BACK_MM / 10 * u
    for b in B:
        x0 = b["cx"] - (b["cols"] - 1) * p / 2
        y0 = b["cy"] - (b["rows"] - 1) * p / 2
        # white backing that follows the filled cells (full rows, then the part-filled top row)
        for c0, c1, r0, r1 in backing_spans(b["n"], b["serp"], b["row"]):
            ax.add_patch(FancyBboxPatch((x0 + c0 * p - r_back, y0 + r0 * p - r_back), (c1 - c0 - 1) * p + 2 * r_back,
                                        (r1 - r0 - 1) * p + 2 * r_back, boxstyle=f"round,pad=0,rounding_size={r_back}",
                                        facecolor=ST["backing"], edgecolor="none", zorder=4))
        for (i, j), d in zip(fill_cells(b["n"], b["serp"], b["row"]), b["disc"]):
            ec, ew = ST["rim"][d]
            ax.add_patch(Circle((x0 + i * p, y0 + j * p), r_dot, facecolor=ST["fill"][d], edgecolor=ec,
                                lw=ew, zorder=5))
            counter[d] += 1
            if d == "math_stats":
                maths.append((ax, x0 + i * p, y0 + j * p))


def draw_labels(ax, B: list[dict], u: float, panel: str) -> list:
    """Two-letter code beside its row, vertically centred on the row, thin white halo. The halo is a
    separate stroke-only text (it prints as outlines); the code itself stays real text in the PDF."""
    out = []
    for b in B:
        if b["cc"] not in LABELS or LABELS[b["cc"]][0] != panel:
            continue
        side = LABELS[b["cc"]][1]
        g = LABEL_GAP_MM / 10 * u
        x, ha = {"left": (b["cx"] - b["hw"] - g, "right"), "right": (b["cx"] + b["hw"] + g, "left")}[side]
        y = b["cy"] - (b["rows"] - 1) * PITCH_MM / 10 * u / 2          # the block's bottom row
        kw = dict(ha=ha, va="center_baseline", fontsize=LABEL_PT, fontweight="normal")
        ax.text(x, y, b["cc"], color=ST["backing"], zorder=6.9, gid="halo",
                path_effects=[pe.Stroke(linewidth=HALO_PT, foreground=ST["backing"], joinstyle="round")], **kw)
        t = ax.text(x, y, b["cc"], color=ST["label"], zorder=7, **kw)
        out.append((ax, b, t))
    return out


def check_labels(labels, blocks: dict, u_of: dict) -> list:
    """Each label (halo included) lies inside its panel, clear of every block, and nearer its own row
    than any other block by a clear margin. Returns (cc, own-row distance mm, next-block distance mm,
    distance to the frame mm)."""
    rep = []
    for ax, own, t in labels:
        bb = t.get_window_extent().transformed(ax.transData.inverted())
        u = u_of[ax]
        h = HALO_PT / 2 / 72 * 2.54 * u                       # halo half-width in data units
        x0, x1, y0, y1 = bb.x0 - h, bb.x1 + h, bb.y0 - h, bb.y1 + h
        ax0, ax1 = ax.get_xlim()
        ay0, ay1 = ax.get_ylim()
        assert ax0 <= x0 and x1 <= ax1 and ay0 <= y0 and y1 <= ay1, (own["cc"], "label outside the panel")
        dist = {}
        for b in blocks[ax]:
            ox = min(x1, b["cx"] + b["hw"]) - max(x0, b["cx"] - b["hw"])
            oy = min(y1, b["cy"] + b["hh"]) - max(y0, b["cy"] - b["hh"])
            assert ox <= 0 or oy <= 0, (own["cc"], "label overlaps block", b["cc"])
            dist[b["cc"]] = math.hypot(max(0.0, -ox), max(0.0, -oy)) / u * 10
        d_own = dist.pop(own["cc"])
        d_next = min(dist.values())
        ok = d_own <= 1.5 and d_next >= d_own + 1.0
        if not ok:
            PROBLEMS.append((own["cc"], "label not clearly next to its own row", round(d_own, 2), round(d_next, 2)))
        # the label is centred on its own row (bottom row) — not between two rows
        row_y = own["cy"] - own["hh"] + BACK_MM / 10 * u + DOT_MM / 20 * u
        assert y0 < row_y < y1, (own["cc"], "label not level with its row")
        # clearance to the panel edge (mm), e.g. CA under the world map's top rule
        edge_mm = min(x0 - ax0, ax1 - x1, y0 - ay0, ay1 - y1) / u * 10
        assert edge_mm >= 1.0, (own["cc"], "label too close to the frame", edge_mm)
        rep.append((own["cc"], round(d_own, 2), round(d_next, 2), round(float(edge_mm), 1)))
    # no two labels touch
    boxes = [(ax, t.get_window_extent()) for ax, _b, t in labels]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            assert boxes[i][0] is not boxes[j][0] or not boxes[i][1].overlaps(boxes[j][1]), "labels overlap"
    return rep


def pbox(P: np.ndarray, pad: float = 0.0):
    return (float(P[:, 0].min()) - pad, float(P[:, 1].min()) - pad, float(P[:, 0].max()) + pad, float(P[:, 1].max()) + pad)


def find_poly(polys, lon: float, lat: float) -> dict:
    """The land polygon (lon/lat exterior ring) containing a place."""
    hit = [p for p in polys if MPath(p["ll"][0]).contains_point((lon, lat))]
    assert len(hit) == 1, (lon, lat, len(hit))
    return hit[0]


# ------------------------------------------------------------------------------------------ layout
def solve_layout(rows: list[dict], polys) -> dict:
    """Everything that does not depend on the palette: panel geometry, land, block positions and the
    destination triangles (with their nudge)."""
    L = {}
    rio = [r for r in rows if r["origin_country"] == "BR"]
    rx_, _ry = w_proj(float(rio[0]["origin_lon"]), float(rio[0]["origin_lat"]))
    _, wy0 = w_proj(150.0, LAT_LO)
    lat_mid = (EU_LAT[0] + EU_LAT[1]) / 2
    ex0, _ = eu_proj(EU_LON[0], lat_mid)
    ex1, _ = eu_proj(EU_LON[1], lat_mid)
    _, ey0 = eu_proj(EU_LON_C, EU_LAT[0])
    _, ey1 = eu_proj(EU_LON_C, EU_LAT[1])
    e_xl, e_yl = (float(ex0), float(ex1)), (float(ey0), float(ey1))
    # the Europe box on the world map: the exact inverse image of the panel's frame
    t = np.linspace(0.0, 1.0, 80)
    fxs = np.concatenate([e_xl[0] + (e_xl[1] - e_xl[0]) * t, np.full(80, e_xl[1]),
                          e_xl[1] - (e_xl[1] - e_xl[0]) * t, np.full(80, e_xl[0])])
    fys = np.concatenate([np.full(80, e_yl[0]), e_yl[0] + (e_yl[1] - e_yl[0]) * t,
                          np.full(80, e_yl[1]), e_yl[1] - (e_yl[1] - e_yl[0]) * t])
    olon, olat = inv_robinson(fxs, fys, EU_LON_C)
    bx, by = w_proj(olon, olat)
    bx, by = np.asarray(bx), np.asarray(by)
    u_w = 0.3
    for _k in range(60):
        w_xl = (float(bx.min()) - LEFT_PAD_MM / 10 * u_w, float(rx_) + RIGHT_X_EXTRA_MM / 10 * u_w)
        u_w = (w_xl[1] - w_xl[0]) / (W_CM - 2 * M_CM)
    w_yl = (float(wy0), float(by.max()) + TOP_PAD_MM / 10 * u_w)
    Hw = (w_yl[1] - w_yl[0]) / u_w
    He = H_CM - 2 * M_CM - Hw - GAP_PANELS_CM
    u_e = (e_yl[1] - e_yl[0]) / He
    We = (e_xl[1] - e_xl[0]) / u_e
    Hf = M_CM + Hw + GAP_PANELS_CM + He + M_CM
    assert Hf <= H_MAX_CM + 1e-9
    L.update(e_xl=e_xl, e_yl=e_yl, w_xl=w_xl, w_yl=w_yl, u_w=u_w, u_e=u_e, Hw=Hw, He=He, We=We, Hf=Hf,
             bx=bx, by=by)
    # ---- land, projected per panel
    LW = project_land(polys, F.CENTRAL_LON, w_xl, w_yl, u_w)
    LE = project_land(polys, EU_LON_C, e_xl, e_yl, u_e)
    assert LW["n_split"] >= 1, "Greenland should cross the world map's antimeridian"
    for Lp, xl in ((LW, w_xl), (LE, e_xl)):
        for p in Lp["polys"]:                              # nothing jumps across a panel
            for xy in p["xy"]:
                assert np.max(np.abs(np.diff(np.r_[xy[:, 0], xy[:1, 0]]))) < 0.5 * (xl[1] - xl[0]), "stray band"
    L.update(LW=LW, LE=LE)
    wpaths = ring_paths(LW["polys"])
    epaths = ring_paths(LE["polys"])
    aus_polys = [p for p in LW["polys"] if p["aus"]]
    aus_paths = ring_paths(aus_polys)
    mainland = max(aus_polys, key=lambda p: abs(_area(p["xy"][0])))
    tas = find_poly(aus_polys, 146.6, -42.0)
    assert mainland is not tas and abs(_area(mainland["xy"][0])) > 50 * abs(_area(tas["xy"][0]))

    def in_panel(lon, lat) -> bool:
        x, y = eu_proj(lon, lat)
        return bool(e_xl[0] <= x <= e_xl[1] and e_yl[0] <= y <= e_yl[1])

    groups = collections.defaultdict(list)
    for r in rows:
        groups[r["origin_country"]].append(r)
    eu_groups, w_groups, cropped = {}, {}, []
    for cc, rs in groups.items():
        inside = [in_panel(float(r["origin_lon"]), float(r["origin_lat"])) for r in rs]
        if any(inside):
            # a European country goes to the panel; its block is drawn on its own land there. At most a
            # minority of its origin cities may lie just outside the crop (Seville, for Spain).
            assert cc in F.EUROPE and sum(inside) * 2 > len(rs), (cc, "country mostly outside the panel")
            cropped += [(cc, r["origin_city"]) for r, i in zip(rs, inside) if not i]
            eu_groups[cc] = rs
        else:
            w_groups[cc] = rs
    nz_land = [p for p in LW["polys"] if not p["aus"]]
    Bw = make_blocks(w_groups, w_proj, u_w, TARGET, nz_land)
    obst = [pbox(mainland["xy"][0]), pbox(tas["xy"][0]),                       # Australia, Tasmania
            (float(bx.min()), float(by.min()), float(bx.max()), float(by.max()))]   # Europe box
    m = 0.6 / 10 * u_w
    w_bounds = (w_xl[0] + m, w_yl[0] + m, w_xl[1] - m, w_yl[1] - m)
    layout(Bw, u_w, w_bounds, obst)
    check_layout(Bw, u_w, w_bounds, obst, "world")
    block_offsets(Bw, u_w)
    Be = make_blocks(eu_groups, eu_proj, u_e, EU_TARGET, max_rows=EU_MAX_ROWS)
    m = 0.6 / 10 * u_e
    e_bounds = (e_xl[0] + m, e_yl[0] + m, e_xl[1] - m, e_yl[1] - m)
    layout(Be, u_e, e_bounds)
    check_layout(Be, u_e, e_bounds, (), "europe")
    block_offsets(Be, u_e)
    assert sum(b["n"] for b in Bw + Be) == len(rows)       # = the run's event count (check_events)
    # ---- placement checks
    blk = {b["cc"]: b for b in Bw + Be}

    def covers(b, proj, lon, lat) -> bool:
        x, y = proj(lon, lat)
        return abs(float(x) - b["cx"]) <= b["hw"] and abs(float(y) - b["cy"]) <= b["hh"]

    def rect_hits(b, polys_) -> int:
        """Land vertices inside the block's rectangle."""
        n = 0
        for p in polys_:
            for xy in p["xy"]:
                n += int(np.sum((np.abs(xy[:, 0] - b["cx"]) <= b["hw"]) & (np.abs(xy[:, 1] - b["cy"]) <= b["hh"])))
        return n
    # US on the US
    us = blk["US"]
    ulon, ulat = inv_robinson(us["cx"], us["cy"], F.CENTRAL_LON)
    ulon = (float(ulon) + 180.0) % 360.0 - 180.0
    assert -115 < ulon < -80 and 30 < float(ulat) < 45, ("US block not on the US", ulon, ulat)
    for place, (lo, la) in (("Kansas", (-98.0, 38.5)), ("Ohio", (-83.0, 40.0)), ("Nevada", (-116.5, 39.0))):
        assert covers(us, w_proj, lo, la), ("US block does not cover", place)
    assert on_land(wpaths, us["cx"], us["cy"]).all(), "US block centre not on land"
    # UK on Britain (Scotland / North Sea), England and Wales left visible
    gb = blk["GB"]
    britain = find_poly(LE["polys"], -1.47, 53.38)
    for place, (lo, la) in UK_VISIBLE.items():
        assert not covers(gb, eu_proj, lo, la), ("UK block covers", place)
        assert on_land(ring_paths([britain]), *eu_proj(lo, la)).all(), ("not on British land", place)
    for place, (lo, la) in UK_COVERED.items():
        assert covers(gb, eu_proj, lo, la), ("UK block no longer on Scotland", place)
    assert on_land(ring_paths([britain]), *dot_centres(gb, u_e).T).sum() >= 5, "UK block not on British land"
    # NZ beside North Island: near its origins, no New Zealand land under the block
    nz = blk["NZ"]
    assert nz["off_mm"] < 4.0, ("NZ block drifted from New Zealand", nz["off_mm"])
    nz_polys = [p for p in LW["polys"] if 165 <= p["ll"][0][:, 0].min() and p["ll"][0][:, 0].max() <= 179.9
                and -48 <= p["ll"][0][:, 1].min() and p["ll"][0][:, 1].max() <= -34]
    assert len(nz_polys) >= 2 and rect_hits(nz, nz_polys) == 0, "NZ block on New Zealand land"
    # Australia: no dot on Australian land (the obstacle boxes already keep blocks off it)
    for b in Bw:
        assert not on_land(aus_paths, *dot_centres(b, u_w).T).any(), (b["cc"], "dot on Australia")
    # Europe: every block centred on land (its own country by target / origin point)
    for b in Be:
        assert on_land(epaths, b["cx"], b["cy"]).all() or b["cc"] == "GB", (b["cc"], "block centre at sea")
    # ---- destination triangles: one per place, touching ones nudged apart
    D = destinations(rows)
    N = nudge_destinations(D, u_w)
    dx_, dy_ = w_proj([d["lon"] for d in D], [d["lat"] for d in D])
    dxy = np.column_stack([dx_, dy_]) + N["nudge_mm"] / 10.0 * u_w
    N["centre_on_land"] = {d["city"]: bool(on_land(aus_paths, x, y).all()) for d, (x, y) in zip(D, dxy)}
    L.update(Bw=Bw, Be=Be, cropped=cropped, obst=obst, D=D, N=N, dxy=dxy)
    return L


# ------------------------------------------------------------------------------------------ render
def draw_land(ax, Lp: dict) -> None:
    ccol, clw = ST["coast"]
    afill, aedge, alw = ST["aus"]
    rest = [p for p in Lp["polys"] if not p["aus"]]
    aus = [p for p in Lp["polys"] if p["aus"]]
    ax.add_patch(PathPatch(fill_path(rest), facecolor=ST["land"], edgecolor="none", lw=0, zorder=0))
    ax.add_patch(PathPatch(coast_path(rest), facecolor="none", edgecolor=ccol, lw=clw, zorder=0.5,
                           joinstyle="round", capstyle="round"))
    if aus:
        ax.add_patch(PathPatch(fill_path(aus), facecolor=afill, edgecolor=aedge, lw=alw, zorder=0.6,
                               joinstyle="round"))


def render(rows: list[dict], L: dict, pdf: Path, png: Path) -> dict:
    from PIL import Image
    e_xl, e_yl, w_xl, w_yl = L["e_xl"], L["e_yl"], L["w_xl"], L["w_yl"]
    u_w, u_e, Hw, He, We, Hf, bx, by = (L[k] for k in ("u_w", "u_e", "Hw", "He", "We", "Hf", "bx", "by"))
    Bw = [dict(b) for b in L["Bw"]]
    Be = [dict(b) for b in L["Be"]]
    fcol, flw = ST["frame"]
    fig = plt.figure(figsize=(W_CM / 2.54, Hf / 2.54))
    axw = fig.add_axes([M_CM / W_CM, (M_CM + He + GAP_PANELS_CM) / Hf, (W_CM - 2 * M_CM) / W_CM, Hw / Hf])
    axe = fig.add_axes([M_CM / W_CM, M_CM / Hf, We / W_CM, He / Hf])

    # ---- world map --------------------------------------------------------------------------------
    axw.set_xlim(*w_xl)
    axw.set_ylim(*w_yl)
    axw.set_aspect("equal")
    axw.set_axis_off()
    frame_w = Rectangle((w_xl[0], w_yl[0]), w_xl[1] - w_xl[0], w_yl[1] - w_yl[0], facecolor="none",
                        edgecolor=fcol, lw=flw, zorder=8, clip_on=False)
    axw.add_patch(frame_w)
    draw_land(axw, L["LW"])
    for p in axw.patches:
        if p is not frame_w:
            p.set_clip_path(frame_w)
    # the Europe box: pale fill + the same thin rule as the frames
    bf, ba = ST["box_fill"]
    axw.add_patch(Polygon(np.column_stack([bx, by]), closed=True, facecolor=bf, alpha=ba, edgecolor="none", zorder=1.5))
    axw.plot(np.r_[bx, bx[:1]], np.r_[by, by[:1]], color=fcol, lw=flw, zorder=2, solid_joinstyle="miter")
    dxy = L["dxy"]
    axw.scatter(dxy[:, 0], dxy[:, 1], s=(DEST_MM / 25.4 * 72) ** 2, marker="^", facecolor=ST["dest"],
                edgecolor="white", lw=DEST_EDGE_PT, zorder=3)

    # ---- Europe panel ----------------------------------------------------------------------------
    axe.set_xlim(*e_xl)
    axe.set_ylim(*e_yl)
    axe.set_aspect("equal")
    axe.set_xticks([])
    axe.set_yticks([])
    for s in axe.spines.values():
        s.set_color(fcol)
        s.set_linewidth(flw)
        s.set_zorder(9)
    draw_land(axe, L["LE"])

    # ---- blocks + labels -------------------------------------------------------------------------
    counter: collections.Counter = collections.Counter()
    maths: list = []
    draw_blocks(axw, Bw, u_w, counter, maths)
    draw_blocks(axe, Be, u_e, counter, maths)
    exp = L["expected"]
    assert {k: counter.get(k, 0) for k in exp} == exp and set(counter) <= set(exp), counter
    labels = draw_labels(axw, Bw, u_w, "world") + draw_labels(axe, Be, u_e, "europe")
    assert sorted(b["cc"] for _a, b, _t in labels) == sorted(LABELS), "a whitelisted code is not drawn once"

    # ---- legend: in the column right of the Europe panel, centred in it; markers == map dots -------
    handles = [Line2D([0], [0], ls="none", marker="o", ms=DOT_MM / 25.4 * 72, mfc=ST["fill"][k],
                      mec=ST["rim"][k][0], mew=ST["rim"][k][1]) for k, _p, _l in DISC]
    leg_y = (M_CM + He / 2) / Hf
    leg = fig.legend(handles, [lab for _k, _p, lab in DISC], loc="center left", ncol=1, frameon=False,
                     fontsize=LEGEND_PT, handlelength=0.8, handletextpad=0.6, labelspacing=0.9, borderpad=0.0,
                     borderaxespad=0.0, bbox_to_anchor=(0.5, leg_y))
    fig.canvas.draw()
    bbl = leg.get_window_extent().transformed(fig.transFigure.inverted())
    col0, col1 = (M_CM + We) / W_CM, 1.0 - M_CM / W_CM
    x_left = (col0 + col1) / 2 - bbl.width / 2
    leg.set_bbox_to_anchor((x_left, leg_y), transform=fig.transFigure)
    fig.canvas.draw()
    bbl = leg.get_window_extent().transformed(fig.transFigure.inverted())
    clear_r, clear_l = (1.0 - bbl.x1) * W_CM * 10, (bbl.x0 - col0) * W_CM * 10
    assert clear_r >= LEG_MIN_CLEAR_MM and clear_l >= LEG_MIN_CLEAR_MM, ("legend margins", clear_l, clear_r)
    for txt in leg.get_texts():
        assert "\n" not in txt.get_text() and txt.get_fontsize() == LEGEND_PT
    for h in leg.legend_handles:
        assert abs(h.get_markersize() - DOT_MM / 25.4 * 72) < 1e-9, "legend marker != map dot"
    wbb = axw.get_position()
    assert bbl.y1 < wbb.y0 and bbl.y0 > M_CM / Hf, ("legend leaves its column", bbl, wbb)
    lab_rep = check_labels(labels, {axw: Bw, axe: Be}, {axw: u_w, axe: u_e})

    # ---- save (fixed metadata: two runs give byte-identical files) ---------------------------------
    fig.savefig(pdf, format="pdf", metadata={"CreationDate": F.PDF_DATE, "ModDate": F.PDF_DATE,
                                             "Creator": "analysis/paper/fig_star_origins.py",
                                             "Title": "Star origins"})
    fig.savefig(png, format="png", dpi=PNG_DPI, metadata={"Software": "analysis/paper/fig_star_origins.py"})
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=PRINT_DPI)
    texts = [t.get_text() for t in fig.findobj(Text) if t.get_visible() and t.get_text().strip() and t.get_gid() != "halo"]
    allowed = [lab for _k, _p, lab in DISC] + [b["cc"] for _a, b, _t in labels]
    assert sorted(texts) == sorted(allowed) == list(FIGURE_TEXT), texts
    size_cm = fig.get_size_inches() * 2.54
    # rim check on the 100-dpi print render: every maths dot must show a dark ring round a light fill
    buf.seek(0)
    G = np.asarray(Image.open(buf).convert("L"), dtype=float) / 255.0
    Hpx = G.shape[0]
    r_px = DOT_MM / 2 / 25.4 * PRINT_DPI
    yy, xx = np.mgrid[-6:7, -6:7]
    rr = np.hypot(xx, yy)
    ring, core = (rr >= r_px - 1.0) & (rr <= r_px + 0.6), rr <= r_px - 1.6
    rim_min, fill_mid = [], []
    for ax_, x_, y_ in maths:
        dx, dy = ax_.transData.transform((x_, y_)) * PRINT_DPI / fig.dpi
        cx, cy = int(round(dx)), int(round(Hpx - dy))
        patch = G[cy - 6:cy + 7, cx - 6:cx + 7]
        rim_min.append(float(patch[ring].min()))
        fill_mid.append(float(patch[core].mean()))
    assert len(maths) == L["expected"]["math_stats"]
    assert max(rim_min) <= 0.45 and min(fill_mid) - max(rim_min) >= 0.45, ("maths rim too faint", rim_min, fill_mid)
    plt.close(fig)
    # the PDF's own page size (MediaBox) and, where poppler is installed, its text layer
    raw = Path(pdf).read_bytes()
    box = re.search(rb"/MediaBox \[\s*0 0 ([\d.]+) ([\d.]+)\s*\]", raw)
    pw, ph = float(box.group(1)), float(box.group(2))
    assert abs(pw / 72 * 2.54 - W_CM) < 0.01 and ph / 72 * 2.54 <= H_MAX_CM + 0.01, (pw, ph)
    tokens = None
    if shutil.which("pdftotext") and shutil.which("pdfinfo"):
        info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, check=True).stdout
        pw2, ph2 = [float(v) for v in next(ln for ln in info.splitlines() if ln.startswith("Page size")).split()[2:5:2]]
        assert abs(pw2 - pw) < 0.01 and abs(ph2 - ph) < 0.01, (pw, ph, pw2, ph2)
        pdf_text = subprocess.run(["pdftotext", "-raw", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
        tokens = pdf_text.split()
        want = sorted(" ".join(allowed).split())
        assert sorted(tokens) == want, ("PDF text layer", tokens, want)
    return {"size_cm": (round(float(size_cm[0]), 3), round(float(size_cm[1]), 3)),
            "pdf_cm": (round(pw / 72 * 2.54, 3), round(ph / 72 * 2.54, 3)), "texts": sorted(texts),
            "pdf_tokens": tokens, "labels": lab_rep, "legend_clear_mm": (round(clear_l, 1), round(clear_r, 1)),
            "maths_rim_print": (round(min(rim_min), 2), round(max(rim_min), 2), round(min(fill_mid), 2)),
            "pdf_kb": round(len(raw) / 1024)}


# ------------------------------------------------------------------------------------------ entry
def draw(ev: list[dict], L_ledger: dict, pdf: Path, png: Path) -> dict:
    """Draw Figure 1 from the computed events and their ledger; write pdf and png; return a report
    (sizes, words, label distances, the destination nudge, layout diagnostics). Every check above is
    an assert; label problems are collected and fatal here."""
    del PROBLEMS[:]
    expected = expected_counts()
    rows = check_events(ev, L_ledger, expected)
    polys = load_land()
    rc = {"font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans"], "font.size": LEGEND_PT,
          "pdf.fonttype": 42, "path.simplify": False}
    with plt.rc_context(rc):
        L = solve_layout(rows, polys)
        L["expected"] = expected
        rep = render(rows, L, pdf, png)
    assert not PROBLEMS, PROBLEMS
    u_w, u_e = L["u_w"], L["u_e"]
    N, D = L["N"], L["D"]
    rep["nudge_mm"] = {d["city"]: [round(float(v), 3) for v in N["nudge_mm"][k]]
                       for k, d in enumerate(D) if np.any(N["nudge_mm"][k] != 0.0)}
    rep["dest_pos_mm"] = {d["city"]: [float(v) for v in N["pos_mm"][k]] for k, d in enumerate(D)}
    rep["nudged_pairs"] = N["separated"]
    rep["unnudged_mm"] = {f"{a}-{b}": round(v, 3) for (a, b), v in N["unnudged_mm"].items()}
    rep["dest_min_clear_mm"] = round(min(N["clear_mm"].values()), 3)
    rep["dest_coincident"] = N["coincident"]
    rep["dest_centre_on_land"] = N["centre_on_land"]
    rep["land"] = {"ne_polygons_north_of_60s": len(polys),
                   "world": (len(L["LW"]["polys"]), L["LW"]["n_split"], L["LW"]["n_sliver"], L["LW"]["n_vert"]),
                   "europe": (len(L["LE"]["polys"]), L["LE"]["n_split"], L["LE"]["n_sliver"], L["LE"]["n_vert"])}
    rep["panels_cm"] = {"world": (round(W_CM - 2 * M_CM, 2), round(L["Hw"], 2)),
                        "europe": (round(L["We"], 2), round(L["He"], 2)), "europe_scale": round(u_w / u_e, 2)}
    mv = lambda B, u: [(b["cc"], b["n"], round(math.hypot(b["cx"] - b["ax"], b["cy"] - b["ay"]) / u * 10, 1),  # noqa: E731
                        round(b["off_mm"], 1)) for b in B]
    rep["blocks_world"] = mv(L["Bw"], u_w)
    rep["blocks_europe"] = mv(L["Be"], u_e)
    rep["cropped"] = L["cropped"]
    rep["block_rules"] = block_rules(L["Bw"] + L["Be"])
    return rep
