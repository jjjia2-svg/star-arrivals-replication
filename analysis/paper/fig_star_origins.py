#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fig_star_origins.py — Figure 1: where the arriving stars came from (written 2026-09-23; revised the
same day; drawing replaced 2026-10-01 by
the colour unit-dot map).

One dot per arrival event (184 dots), placed in a block on the country of the star's last institution
abroad before arrival; the disciplines differ by colour (economics dark blue, chemistry orange,
mathematics & statistics pale yellow with a dark rim). World map plus an enlarged Europe panel; the
Australian universities that hired the stars are dark triangles. The only words in the figure are the
three discipline names of the legend and seven two-letter country codes (CA, NL, BE, CH, AT, HK, SG)
where position alone is ambiguous (the course word count includes figure text): no title, no axis
labels, no notes, no years (arrival years are in the ledger). No personal names are drawn or written
anywhere. Until 2026-10-01 the figure drew one arc per event (black-and-white line styles); see
DRAWING.

ORIGIN: HUMAN-VERIFIED WHERE IT EXISTS, OTHERWISE THE OPENALEX RULE
  H. data/paper_inputs/star_origins_2026-10/human_origin_overrides.csv (pinned; README in that folder)
     holds one row per event for which a person checked where the star came from (CV, ORCID, official
     pages): 89 events — 16 economics events (checked 2026-07-20), the poach-gate verdicts 2026-08-15
     (62; one chemistry star is filed there under another OpenAlex id, found by name, field and
     arrival year), the U4-flagged recheck 2026-08-16 (5 economics), the 2026-09-22 recheck identity
     anchors (14 economics; 7 of them covered by no other record). The origin there is the post held just
     before arrival; a visiting post is not a post (the poach gate's rule). Placement column:
       human_institution  the record names the institution; its snapshot institution record gives the
                          name, country and place. `coords_from`, when set, names the snapshot record
                          whose coordinates place the marker, because the named institution has no
                          record of its own and the record OpenAlex files it under sits in another
                          city (1 event).
       machine_institution_same_country  the record gives only the country and the OpenAlex rule's
                          institution (M below) is in that country: that institution is kept.
       country_main_city  the record gives only the country and the OpenAlex rule's institution is in
                          another country: no institution is named; the marker goes to the country's
                          main research city = the city with the most distinct institutions of that
                          country in institutions.csv (ties: alphabetical), placed at the median
                          latitude and the median longitude of those institutions.
     A row must match its event (star id, school, arrival year) and every row must be used, or the
     script stops. Rows are keyed by (discipline, star_id, arrival_year), not by event_row (R1 F21), so
     a row follows its event when rows are inserted or removed above it. In an M canon the table is the
     merged one tools/star_origins_extract_2026-10.py writes: October's rows re-keyed through
     alias_event() (id corrections, confirmed re-dates), rows of events not in the run dropped, the r1 rows
     of data/cal2026-10r1/inputs/star_origins/ (not shipped) appended (columns carried_from, recheck added; a re-dated
     October row needs an r1 confirmation row, since the origin is the last post before arrival).
  M. Every other event: the OpenAlex rule below (event = star s arriving at school in year T, from
     data/cal2026-10/events_{econ,chemistry,math_stats}_cal2026-10.csv — 113 / 38 / 33 events). It
     runs for all 184 events; the per-event CSV keeps its answer in the machine_* columns next to the
     final origin, and the ledger reports both.
  0. Affiliation-years A = the (institution, year) pairs in the OpenAlex snapshot's author record
     `affiliations` for the star's own OpenAlex author id (the id in the event table), keeping years
     <= T-1 and institutions outside Australia. An institution's country is its snapshot institution
     record's country_code, else the code printed inside the affiliation. A pair with neither is not
     used: at cal2026-10 these are institutions whose snapshot records carry an empty country_code
     (they name a country only in their `geo` block, which the extraction does not keep); the ledger
     counts them and re-runs the rule with them kept as foreign candidates
     (pooled_origins_changed_if_no_country_kept).
  1. T-1 (rule "T-1", gap 0): if A has pairs in year T-1, the origin is the one of those institutions
     with the MOST WORKS in T-1 — works = distinct OpenAlex works in the U1 extraction tables
     (works_affil x authorship_edges, both 2026-07 U1 extractions pooled) that list the star with that
     institution and were published in T-1.
  2. Otherwise (rule "latest_pre"): the latest year y < T-1 in which A has any pair; the origin is
     chosen among that year's institutions the same way; the year gap (T-1) - y is recorded.
  Ties in 1-2 go to the institution with more distinct pre-arrival years in A, then to the smaller
  institution id compared as a NUMBER (I27837315 < I166437374) — recorded per event as tie_break
  single / works / years / id.
  3. Identity fallback (economics only; id_source "u2_fragments"): if the star's own id leaves A empty,
     steps 0-2 run on the union of the OpenAlex author ids that the U2 person map folds into the star's
     person (the identity the economics frames use), minus the ids that
     data/cal2026-10/star_id_corrections_2026-10.csv lists as wrong; works are summed across ids.
  4. Otherwise the origin is unknown (reported; zero events at cal2026-10).
  Known limits of M, stated rather than fixed: OpenAlex affiliations follow publication bylines, which
  lag job moves (a new postdoc's first papers often still carry the PhD institution) and can carry
  secondary labels (research networks, hospitals, institutes in the same city); ids merged with a
  namesake can add a wrong institution; about one affiliation-year in nine has no U1 work behind it,
  which weakens the works tie-break. tools/star_origins_crosscheck_2026-10.py measures M against the
  human records and checks the override table against them.
Destination: the event school's university (the SCHOOL_INST map the event pipeline pins), placed at its
snapshot institution coordinates.

DRAWING (2026-10-01: colour unit-dot map; the code is analysis/paper/fig_star_origins_dots.py, whose
docstring has the full rules and every check)
  Size: 15 x 12 cm (15 cm = the thesis text width, so the legend prints at 9 pt and the country codes
  at 8 pt when the figure is included at \\textwidth).
  Panels: a world map (Robinson projection from the standard 5-degree table, centred on 150E; cropped from 47S to just
  above the Europe box, and from the Europe box's west edge to just east of Rio de Janeiro) and below
  it, at left, Europe enlarged about 5.8 times (Robinson centred on the panel, 14W-23E, 39.4N-59.7N);
  the Europe panel's area is outlined on the world map. Legend at right of the Europe panel.
  Dots: one 1.5-mm dot per event. The dots of one origin country form one block, 10 per row, filled
  left to right from the bottom row, economics first, then chemistry, then mathematics & statistics,
  so each discipline is one connected run and counts read in tens. A block sits on its country: on
  the origin point nearest the mean of the country's origin points, or on a fixed target point for
  the US, Canada, Vietnam, Malaysia, the Philippines and the European countries, and just east of
  North Island for New Zealand; overlapping blocks are pushed apart. Europe's countries (origins
  inside the panel's crop) are drawn in the Europe panel only.
  Land: Natural Earth 1:50m land polygons (data/paper_inputs/basemap/ne_50m_land.geojson, public
  domain, pinned), Australia shaded darker. The ETOPO5 mask is no longer drawn; compute() still uses
  it for the ledger's sea-side marker counts (below), which are unchanged.
  Destinations: one dark triangle per destination place (universities in one city share a place).
  The Sydney (four universities) and Canberra triangles touch at their true places; they are nudged
  apart by the least move along the axis that separates them, leaving 0.1 mm of clear land between
  their white rims (Canberra moves only as far as it can without coming that close to the Melbourne
  triangles; Sydney takes the rest): at cal2026-10 Sydney 0.68 mm east-north-east, Canberra 0.15 mm
  west-south-west. The nudge is recorded in the ledger (figure_destination_nudge_mm, mm on the
  figure, east and north).
  Words: the three legend labels and the codes CA, NL, BE, CH, AT, HK, SG; asserted on the figure's
  text objects and, where poppler's pdftotext is on PATH, on the PDF text layer.
  Ledger keys about the drawing (added 2026-10-01; main() adds them after the figure is drawn, so
  compute() alone does not return them): _figure_rule, figure_text, figure_size_cm,
  figure_destination_nudge_mm; and, when a block uses rows of 20 or a serpentine fill,
  figure_block_exceptions records the departure from the original layout for the caption check.
  Kept from the arc design (2026-09-23), unchanged: compute() still builds each event's arc (a
  quadratic Bezier in Robinson coordinates centred on 150E, control point ARC_BOW x chord length off
  the chord's midpoint on the northern side; frame 58S-72N) and counts arcs that leave that frame
  (*_arcs_leaving_frame, _arc_rule; all 0); and it tests every origin and destination marker against
  the 1-degree ETOPO5 land mask (data/paper_inputs/basemap; cells centred on half degrees, as the
  grid's own georeference in topo.mat says — see MASK_LAT0), split into half-degree cells, expanded by
  one half-degree cell (3x3 maximum) and smoothed (3x3 mean), land at the 0.5 contour
  (*_origin_markers_at_sea*, pooled_destination_markers_at_sea*, _land_rule). The figure draws
  neither the arcs nor the mask.

Reads ONLY pinned inputs (sha256 in PINS; a changed input stops the script):
  data/cal2026-10/events_{econ,chemistry,math_stats}_cal2026-10.csv
  data/paper_inputs/star_origins_2026-10/{star_author_ids,affiliation_years,institutions,destinations}.csv
      (frozen from the offline snapshot by tools/star_origins_extract_2026-10.py)
  data/paper_inputs/star_origins_2026-10/human_origin_overrides.csv   (hand-curated; README there)
  data/paper_inputs/basemap/land_mask_etopo5_1deg.txt   (tools/basemap_etopo5_mask_2026-10.py; README there)
  data/paper_inputs/basemap/ne_50m_land.geojson   (Natural Earth, downloaded 2026-10-01; README there)
Writes (output/paper/):
  fig_star_origins.pdf (+ fig_star_origins.png preview, 200 dpi)
  data_numbers_star_origins.json   the ledger (flat keys econ_/chem_/math_/pooled_ plus figure_*, sorted)
  star_origins_2026-10.csv         one row per event: institution names and places only
Deterministic: two runs give byte-identical outputs (PDF CreationDate fixed below).
Run:  setup/.venv/bin/python analysis/paper/fig_star_origins.py
"""
from __future__ import annotations

import collections
import csv
import datetime
import hashlib
import io
import json
import math
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from analysis.lib.paths import load_paths  # noqa: E402
from analysis.lib import canon  # noqa: E402

#: the October inputs and their sha256, by (paths key, path under that root). R1 F7: the roots come
#: from config; October keeps these pins (PINS spells them with the October repo-relative keys, as
#: before), an M canon takes them from its MANIFESTs ('<prefix>/<rel>' keys, tools/r1_canon.py).
_OCTOBER_PINS = {
    ("cal", "events_econ_cal2026-10.csv"):
        "509e4955cdce5ea289829689bdbc193c0ca49a732420a3437301d7191267cc64",
    ("cal", "events_chemistry_cal2026-10.csv"):
        "7f8d75e50ad0c2dfd75ae069466d7962f672b53a4562fb76e03f8e4458f8edaa",
    ("cal", "events_math_stats_cal2026-10.csv"):
        "c25da2173ed7b03ea3ae8f44aa91e0fdbeb5a1666599d9ccc9325fd37cc397e7",
    ("paper_inputs", "star_origins_2026-10/star_author_ids.csv"):
        "4d09a6cb5dbe93c6cbf0b96d21274091ea6e90b47954baa1eb08c0e0691c6a78",
    ("paper_inputs", "star_origins_2026-10/affiliation_years.csv"):
        "a10964b6f489236347cae8902d3ca7f355d8886992329c6e84d99f8eb48b2f12",
    ("paper_inputs", "star_origins_2026-10/institutions.csv"):
        "75b480f2bc74bd075c6c432b8ebb160646d945b224f98ee0d6e3d852b5bf96e6",
    ("paper_inputs", "star_origins_2026-10/destinations.csv"):
        "d24edf2970ab17ca314b13434941619fe7a459b1d52f753b94efcaeeac64d89e",
    ("paper_inputs", "star_origins_2026-10/human_origin_overrides.csv"):
        "f65f9e21f8cb807082ce3e99ab1b323939987bca5a514ec0e9ac45368790e0f0",
    ("paper_inputs", "basemap/land_mask_etopo5_1deg.txt"):
        "d7a628133623a669761347fddfda8222b5a48b61f531ee05247a130a31e2dfbc",
    ("paper_inputs", "basemap/ne_50m_land.geojson"):
        "e874b27a51d146452be360cafb3cc50c86001074a67d534113e6534682f9826b",
}


def src(key_name: str, rel: str) -> str:
    """The key an input is pinned and named by: data/cal2026-10/... (October), cal/... (an M canon)."""
    return canon.key(load_paths()[key_name] / rel)


def _pins() -> dict:
    if canon.mode() == "october":
        return {src(k, rel): h for (k, rel), h in _OCTOBER_PINS.items()}
    out = {}
    for k, rel in _OCTOBER_PINS:
        key = src(k, rel)
        man = canon.read_manifest(canon.manifest(k))
        if key not in man:
            raise SystemExit(f"PIN MISSING {key}: not in {canon.manifest(k)}")
        out[key] = man[key]
    return out


PINS = _pins()
#: (event-table key, ledger prefix, legend label)
FIELDS = (("econ", "econ", "Economics"), ("chemistry", "chem", "Chemistry"),
          ("math_stats", "math", "Mathematics & Statistics"))
PLACEMENTS = ("human_institution", "machine_institution_same_country", "country_main_city")
PERIODS = ((1999, 2004), (2005, 2009), (2010, 2014), (2015, 2019), (2020, 2024))   # ledger only
CENTRAL_LON = 150.0                  # Pacific-centred: Europe left, the Americas right
#: ledger key of the blocks that leave the 2026-10-01 fill (R1 M2 round 3); final_stage.py gate 2 reads it
FIGURE_EXCEPTIONS_KEY = "figure_block_exceptions"
LAT_MIN, LAT_MAX = -58.0, 72.0       # frame of the arc check in compute() (the figure's crop: fig_star_origins_dots)
ARC_BOW = 0.20                       # control-point offset / chord length (the curve bows by half that)
FIG_WIDTH_CM = 15.0                  # thesis text width
FONT_PT = 9.0                        # legend text (the country codes are 8 pt)
PDF_DATE = datetime.datetime(2026, 9, 23, tzinfo=datetime.timezone.utc)

#: CO, NG, PK, SA, SI and UA are R1 origins only (October has none)
COUNTRY_NAMES = {
    "AR": "Argentina", "AT": "Austria", "BE": "Belgium", "BR": "Brazil", "CA": "Canada",
    "CH": "Switzerland", "CL": "Chile", "CN": "China", "CO": "Colombia", "CZ": "Czechia", "DE": "Germany",
    "DK": "Denmark", "ES": "Spain", "ET": "Ethiopia", "FI": "Finland", "FR": "France", "GB": "United Kingdom",
    "GR": "Greece", "HK": "Hong Kong", "ID": "Indonesia", "IE": "Ireland", "IL": "Israel", "IN": "India", "IT": "Italy",
    "JP": "Japan", "KR": "South Korea", "MX": "Mexico", "MY": "Malaysia", "NG": "Nigeria", "NL": "Netherlands",
    "NO": "Norway", "NZ": "New Zealand", "PH": "Philippines", "PK": "Pakistan", "PL": "Poland", "PT": "Portugal",
    "RS": "Serbia", "RU": "Russia", "SA": "Saudi Arabia", "SE": "Sweden", "SG": "Singapore", "SI": "Slovenia",
    "TW": "Taiwan", "UA": "Ukraine", "US": "United States", "VN": "Vietnam", "ZA": "South Africa",
}
#: Europe includes the United Kingdom, Switzerland, Norway, Serbia, Russia and Ukraine
EUROPE = {"AT", "BE", "CH", "CZ", "DE", "DK", "ES", "FI", "FR", "GB", "GR", "IE", "IT", "NL", "NO",
          "PL", "PT", "RS", "RU", "SE", "SI", "UA"}
ASIA = {"CN", "HK", "ID", "IL", "IN", "JP", "KR", "MY", "PH", "PK", "SA", "SG", "TW", "VN"}   # incl. Israel and Saudi Arabia
REGIONS = (("north_america", {"US", "CA"}), ("europe", EUROPE), ("asia", ASIA),
           ("new_zealand", {"NZ"}), ("latin_america", {"AR", "BR", "CL", "CO", "MX"}),
           ("africa", {"ET", "NG", "ZA"}))


# ---------------------------------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------------------------------
def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def read_pinned(rel: str) -> str:
    b = canon.resolve(rel).read_bytes()
    got = sha256_bytes(b)
    if got != PINS[rel]:
        raise SystemExit(f"PIN MISMATCH {rel}: {got} != {PINS[rel]}")
    return b.decode("utf-8")


def rows(rel: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(read_pinned(rel))))


def alias_event(star_id: str, year: int, *, corrections: dict, redates: dict) -> tuple[str, int]:
    """(star_id, arrival_year) of an October event in a run's event set (R1 F21): the id through
    `corrections` ({old_id: new_id}, chains followed, a cycle stops), then the year through `redates`
    ({(star_id, old_year): new_year}, keyed by the id the run uses). No entry: the event is unchanged."""
    seen = set()
    while star_id in corrections:
        if star_id in seen:
            raise SystemExit(f"alias_event: id correction cycle at {star_id}")
        seen.add(star_id)
        star_id = corrections[star_id]
    year = int(year)
    return star_id, int(redates.get((star_id, year), year))


def override_key(r: dict) -> tuple[str, str, int]:
    """The key an override row is matched to its event by: (discipline, star_id, arrival_year)."""
    return (r["discipline"], r["star_id"], int(r["arrival_year"]))


def load_inputs() -> dict:
    events = []
    for key, pre, _label in FIELDS:
        for k, r in enumerate(rows(src("cal", f"events_{key}_cal2026-10.csv")), 1):
            events.append({
                "field": key, "prefix": pre, "event_row": k, "school": r["school"],
                "star": r["star_id"] if key == "econ" else r["author_id"],
                "arrival": int(r["arrival_year"] if key == "econ" else r["arrival_corrected"])})
    base = src("paper_inputs", "star_origins_2026-10") + "/"
    ids = collections.defaultdict(lambda: {"star": [], "u2_fragment": []})
    for r in rows(base + "star_author_ids.csv"):
        ids[r["star_id"]][r["role"]].append(r["author_id"])
    aff = collections.defaultdict(list)
    for r in rows(base + "affiliation_years.csv"):
        aff[r["author_id"]].append((r["institution_id"], int(r["year"]), r["country_code_aff"],
                                    int(r["n_works"])))
    inst = {r["institution_id"]: r for r in rows(base + "institutions.csv")}
    dest = {r["school"]: r["institution_id"] for r in rows(base + "destinations.csv")}
    overrides: dict[tuple[str, str, int], dict] = {}
    for r in rows(base + "human_origin_overrides.csv"):
        k = override_key(r)
        if k in overrides:
            raise SystemExit(f"override table: duplicate row for {k}")
        overrides[k] = r
    mask_lines = [ln for ln in read_pinned(src("paper_inputs", "basemap/land_mask_etopo5_1deg.txt"))
                  .splitlines() if ln and not ln.startswith("#")]
    return {"events": events, "ids": ids, "aff": aff, "inst": inst, "dest": dest,
            "overrides": overrides, "mask": mask_lines}


# ---------------------------------------------------------------------------------------------------
# the OpenAlex rule (M)
# ---------------------------------------------------------------------------------------------------
def country(inst: dict, iid: str, printed: str = "") -> str:
    return (inst.get(iid) or {}).get("country_code") or printed or ""


def iid_number(iid: str) -> int:
    """An OpenAlex institution id as a number: 'I27837315' -> 27837315."""
    return int(iid.lstrip("I"))


def origin_of(author_ids: list[str], T: int, aff: dict, inst: dict,
              keep_no_country: bool = False) -> dict | None:
    """Steps 0-2 of the rule on the pooled affiliation-years of `author_ids`; None if A is empty.
    keep_no_country=True is the sensitivity run: institutions without any country count as foreign."""
    works: dict[tuple[str, int], int] = collections.Counter()
    years_at: dict[str, set[int]] = collections.defaultdict(set)
    for a in author_ids:
        for iid, y, printed, n in aff.get(a, ()):
            c = country(inst, iid, printed)
            if y > T - 1 or c == "AU" or (not c and not keep_no_country):
                continue
            works[(iid, y)] += n
            years_at[iid].add(y)
    if not works:
        return None
    y = max(yy for (_i, yy) in works)
    cand = sorted({i for (i, yy) in works if yy == y},
                  key=lambda i: (-works[(i, y)], -len(years_at[i]), iid_number(i)))
    if len(cand) == 1:
        tie = "single"
    elif works[(cand[0], y)] != works[(cand[1], y)]:
        tie = "works"
    elif len(years_at[cand[0]]) != len(years_at[cand[1]]):
        tie = "years"
    else:
        tie = "id"
    return {"institution_id": cand[0], "aff_year": y, "gap": (T - 1) - y,
            "rule": "T-1" if y == T - 1 else "latest_pre", "tie_break": tie,
            "n_works_in_year": works[(cand[0], y)], "n_candidates": len(cand)}


def no_country_cells(author_ids: list[str], T: int, aff: dict, inst: dict) -> set[tuple[str, int]]:
    """(institution, year) pairs at or before T-1 that step 0 drops for want of any country."""
    return {(iid, y) for a in author_ids for iid, y, printed, _n in aff.get(a, ())
            if y <= T - 1 and not country(inst, iid, printed)}


def machine_origin(e: dict, inp: dict, keep_no_country: bool = False) -> tuple[dict | None, str, list[str]]:
    """Steps 0-3 for one event: (origin or None, id source, the author ids the rule used)."""
    own = inp["ids"][e["star"]]["star"] or [e["star"]]
    o = origin_of(own, e["arrival"], inp["aff"], inp["inst"], keep_no_country)
    if o is None and e["field"] == "econ" and inp["ids"][e["star"]]["u2_fragment"]:
        pooled = own + inp["ids"][e["star"]]["u2_fragment"]
        return origin_of(pooled, e["arrival"], inp["aff"], inp["inst"], keep_no_country), "u2_fragments", pooled
    return o, "star_id", own


def main_city(cc: str, inst: dict) -> tuple[str, float, float, int]:
    """The country's main research city: most distinct institutions of that country in
    institutions.csv (ties: alphabetical); point = median latitude and median longitude of them."""
    pts: dict[str, list[tuple[float, float]]] = collections.defaultdict(list)
    for r in inst.values():
        if r["country_code"] == cc and r["city"] and r["latitude"] and r["longitude"] and r["in_snapshot"] == "1":
            pts[r["city"]].append((float(r["latitude"]), float(r["longitude"])))
    if not pts:
        raise SystemExit(f"no snapshot institution with a place in country {cc}")
    city = min(pts, key=lambda c: (-len(pts[c]), c))
    return (city, statistics.median(p[0] for p in pts[city]), statistics.median(p[1] for p in pts[city]),
            len(pts[city]))


def region_of(cc: str) -> str:
    for name, codes in REGIONS:
        if cc in codes:
            return name
    raise SystemExit(f"country {cc} has no region in fig_star_origins.REGIONS — add it")


def period_of(year: int) -> int:
    for k, (a, b) in enumerate(PERIODS):
        if a <= year <= b:
            return k
    raise SystemExit(f"arrival year {year} outside {PERIODS}")


def _human_origin(key, ov: dict, e: dict, mach: dict | None, inst: dict) -> dict:
    """The final origin of an event with a human record (placement rules H in the docstring)."""
    if (ov["star_id"], ov["school"], int(ov["arrival_year"])) != (e["star"], e["school"], e["arrival"]):
        raise SystemExit(f"override {key} does not match its event")
    pl, cc = ov["placement"], ov["country_code"]
    if pl == "human_institution":
        r = inst.get(ov["institution_id"])
        if r is None or country(inst, ov["institution_id"]) != cc:
            raise SystemExit(f"override {key}: institution {ov['institution_id']} missing or not in {cc}")
        c = inst[ov["coords_from"]] if ov["coords_from"] else r
        return {"iid": ov["institution_id"], "name": r["display_name"], "cc": cc, "type": r["type"],
                "city": c["city"], "lat": float(c["latitude"]), "lon": float(c["longitude"])}
    if pl == "machine_institution_same_country":
        if mach is None or mach["cc"] != cc or ov["institution_id"] or ov["coords_from"]:
            raise SystemExit(f"override {key}: the machine institution is not in {cc}")
        return dict(mach)
    if pl == "country_main_city":
        if (mach is not None and mach["cc"] == cc) or ov["institution_id"] or ov["coords_from"]:
            raise SystemExit(f"override {key}: the machine institution is in {cc}; use machine_institution_same_country")
        city, lat, lon, _n = main_city(cc, inst)
        return {"iid": "", "name": "", "cc": cc, "type": "", "city": city, "lat": lat, "lon": lon}
    raise SystemExit(f"override {key}: unknown placement {pl}")


def compute(inp: dict | None = None) -> tuple[list[dict], dict]:
    inp = inp or load_inputs()
    inst, dest, ovr = inp["inst"], inp["dest"], inp["overrides"]
    S = land_fields(inp["mask"])
    M = raw_mask(inp["mask"])
    used: set[tuple[str, str, int]] = set()
    dropped: set[tuple[str, int]] = set()
    n_changed_if_kept = 0
    out = []
    for e in inp["events"]:
        o, src, used_ids = machine_origin(e, inp)
        dropped |= no_country_cells(used_ids, e["arrival"], inp["aff"], inst)
        o2, _s2, _u2 = machine_origin(e, inp, keep_no_country=True)
        n_changed_if_kept += int((o or {}).get("institution_id") != (o2 or {}).get("institution_id"))
        d = inst[dest[e["school"]]]
        row = {"discipline": e["field"], "event_row": e["event_row"], "school": e["school"],
               "arrival_year": e["arrival"], "arrival_period": "%d-%d" % PERIODS[period_of(e["arrival"])],
               "destination_institution": d["display_name"], "destination_lat": float(d["latitude"]),
               "destination_lon": float(d["longitude"])}
        mach = None
        if o is not None:
            m = inst[o["institution_id"]]
            if not m.get("latitude") or not m.get("longitude"):
                raise SystemExit(f"origin {o['institution_id']} has no coordinates")
            mach = {"iid": o["institution_id"], "name": m["display_name"], "cc": country(inst, o["institution_id"]),
                    "type": m["type"], "city": m["city"], "lat": float(m["latitude"]), "lon": float(m["longitude"])}
            row.update({"machine_institution": mach["name"], "machine_institution_id": mach["iid"],
                        "machine_country": mach["cc"], "machine_affiliation_year": o["aff_year"],
                        "machine_year_gap": o["gap"], "machine_rule": o["rule"], "machine_id_source": src,
                        "machine_tie_break": o["tie_break"], "machine_n_works_in_year": o["n_works_in_year"],
                        "machine_n_candidates": o["n_candidates"]})
        key = (e["field"], e["star"], e["arrival"])
        if key in ovr:
            used.add(key)
            final, source, placement = _human_origin(key, ovr[key], e, mach, inst), "human", ovr[key]["placement"]
        else:
            final, source, placement = mach, "machine", "machine_rule"
        if final is None:
            row["origin_status"] = "unknown"
            out.append(row)
            continue
        cc = final["cc"]
        row.update({"origin_status": "found", "origin_source": source, "origin_placement": placement,
                    "origin_institution": final["name"], "origin_institution_id": final["iid"],
                    "origin_institution_type": final["type"], "origin_city": final["city"],
                    "origin_country": cc, "origin_country_name": COUNTRY_NAMES[cc],
                    "origin_region": region_of(cc), "origin_lat": final["lat"], "origin_lon": final["lon"]})
        row["origin_at_sea"] = int(land_at(S, final["lat"], final["lon"]) < 0.5)
        row["origin_at_sea_raw_mask"] = int(raw_land_at(M, final["lat"], final["lon"]) < 0.5)
        x, y = arc_xy(final["lat"], final["lon"], row["destination_lat"], row["destination_lon"])
        row["arc_leaves_frame"] = int(not bool(inside_frame(x, y).all()))
        out.append(row)
    unused = sorted(set(ovr) - used)
    if unused:
        raise SystemExit(f"override rows without an event: {unused}")
    dests = sorted({(r["destination_lat"], r["destination_lon"]) for r in out})
    extras = {"dropped_cells": len(dropped), "dropped_institutions": len({i for i, _y in dropped}),
              "changed_if_kept": n_changed_if_kept, "dest_places": len(dests),
              "dest_at_sea": sum(land_at(S, la, lo) < 0.5 for la, lo in dests),
              "dest_at_sea_raw": sum(raw_land_at(M, la, lo) < 0.5 for la, lo in dests)}
    return out, ledger_from(out, extras)


def pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 1) if d else 0.0


def _top(cc: collections.Counter, n_found: int) -> list:
    top = sorted(cc.items(), key=lambda kv: (-kv[1], kv[0]))
    return [[c, COUNTRY_NAMES[c], n, pct(n, n_found)] for c, n in top[:10]]


def ledger_from(ev: list[dict], extras: dict | None = None) -> dict:
    L: dict = {}
    groups = [(pre, [r for r in ev if r["discipline"] == key]) for key, pre, _t in FIELDS]
    groups.append(("pooled", ev))
    for pre, g in groups:
        found = [r for r in g if r["origin_status"] == "found"]
        mach = [r for r in g if r.get("machine_institution_id")]
        human = [r for r in found if r["origin_source"] == "human"]
        cc = collections.Counter(r["origin_country"] for r in found)
        mcc = collections.Counter(r["machine_country"] for r in mach)
        L[f"{pre}_events"] = len(g)
        L[f"{pre}_with_origin"] = len(found)
        L[f"{pre}_origin_unknown"] = len(g) - len(found)
        L[f"{pre}_coverage_pct"] = pct(len(found), len(g))
        # where the final (drawn) origin comes from
        L[f"{pre}_origin_source_human"] = len(human)
        L[f"{pre}_origin_source_machine"] = sum(r["origin_source"] == "machine" for r in found)
        L[f"{pre}_placement_counts"] = {p: sum(r["origin_placement"] == p for r in found)
                                        for p in PLACEMENTS + ("machine_rule",)}
        L[f"{pre}_human_same_institution_as_machine"] = sum(
            r["origin_institution_id"] == r.get("machine_institution_id") for r in human)
        L[f"{pre}_human_changed_institution"] = sum(
            r["origin_institution_id"] != r.get("machine_institution_id") for r in human)
        L[f"{pre}_human_changed_country"] = sum(r["origin_country"] != r.get("machine_country") for r in human)
        # the OpenAlex rule (M), run on every event
        L[f"{pre}_machine_with_origin"] = len(mach)
        L[f"{pre}_rule_t_minus_1"] = sum(r["machine_rule"] == "T-1" for r in mach)
        L[f"{pre}_rule_latest_pre"] = sum(r["machine_rule"] == "latest_pre" for r in mach)
        L[f"{pre}_via_u2_fragments"] = sum(r["machine_id_source"] == "u2_fragments" for r in mach)
        L[f"{pre}_via_api"] = 0
        L[f"{pre}_year_gap_counts"] = {str(k): v for k, v in
                                       sorted(collections.Counter(r["machine_year_gap"] for r in mach).items())}
        L[f"{pre}_max_year_gap"] = max((r["machine_year_gap"] for r in mach), default=0)
        L[f"{pre}_tie_break_counts"] = dict(sorted(collections.Counter(r["machine_tie_break"] for r in mach).items()))
        L[f"{pre}_machine_origin_countries"] = len(mcc)
        L[f"{pre}_machine_country_counts"] = dict(sorted(mcc.items()))
        L[f"{pre}_machine_top_countries"] = _top(mcc, len(mach))
        # the final origins, as drawn
        L[f"{pre}_arcs_leaving_frame"] = sum(r["arc_leaves_frame"] for r in found)
        L[f"{pre}_origin_markers_at_sea"] = sum(r["origin_at_sea"] for r in found)
        L[f"{pre}_origin_markers_at_sea_raw_mask"] = sum(r["origin_at_sea_raw_mask"] for r in found)
        L[f"{pre}_origin_countries"] = len(cc)
        L[f"{pre}_origin_institutions"] = len({r["origin_institution_id"] for r in found if r["origin_institution_id"]})
        L[f"{pre}_origin_type_counts"] = dict(sorted(collections.Counter(
            r["origin_institution_type"] or "country_only" for r in found).items()))
        L[f"{pre}_country_counts"] = dict(sorted(cc.items()))
        L[f"{pre}_top_countries"] = _top(cc, len(found))
        L[f"{pre}_n_us"] = cc.get("US", 0)
        L[f"{pre}_share_us_pct"] = pct(cc.get("US", 0), len(found))
        L[f"{pre}_n_gb"] = cc.get("GB", 0)
        L[f"{pre}_share_gb_pct"] = pct(cc.get("GB", 0), len(found))
        L[f"{pre}_n_us_gb"] = cc.get("US", 0) + cc.get("GB", 0)
        L[f"{pre}_share_us_gb_pct"] = pct(cc.get("US", 0) + cc.get("GB", 0), len(found))
        reg = collections.Counter(r["origin_region"] for r in found)
        for name, _codes in REGIONS:
            L[f"{pre}_n_{name}"] = reg.get(name, 0)
            L[f"{pre}_share_{name}_pct"] = pct(reg.get(name, 0), len(found))
        eu_ex_gb = sum(n for c, n in cc.items() if c in EUROPE and c != "GB")
        L[f"{pre}_n_europe_ex_gb"] = eu_ex_gb
        L[f"{pre}_share_europe_ex_gb_pct"] = pct(eu_ex_gb, len(found))
        L[f"{pre}_arrival_period_counts"] = {"%d-%d" % p: sum(r["arrival_period"] == "%d-%d" % p for r in g)
                                             for p in PERIODS}
        L[f"{pre}_arrival_year_min"] = min(r["arrival_year"] for r in g)
        L[f"{pre}_arrival_year_max"] = max(r["arrival_year"] for r in g)
        L[f"{pre}_destination_universities"] = len({r["school"] for r in g})
    if extras is not None:
        L["pooled_affiliation_cells_dropped_no_country"] = extras["dropped_cells"]
        L["pooled_institutions_dropped_no_country"] = extras["dropped_institutions"]
        L["pooled_origins_changed_if_no_country_kept"] = extras["changed_if_kept"]
        L["pooled_destination_places"] = extras["dest_places"]
        L["pooled_destination_markers_at_sea"] = extras["dest_at_sea"]
        L["pooled_destination_markers_at_sea_raw_mask"] = extras["dest_at_sea_raw"]
    L["_about"] = ("analysis/paper/fig_star_origins.py — last institution abroad before arrival of every "
                   "cal2026-10 arrival event: human-verified where a record exists "
                   "(data/paper_inputs/star_origins_2026-10/human_origin_overrides.csv), else the OpenAlex "
                   "T-1 rule (generator docstring). The machine_* keys and the rule_* / tie_break / year_gap "
                   "/ via_u2 keys describe the OpenAlex rule run on all events; every other key describes "
                   "the final (drawn) origins. Shares are of events with an origin; Europe includes the "
                   "United Kingdom; asia includes Israel")
    L["_main_city_rule"] = ("country_main_city: the city with the most distinct institutions of that "
                            "country in institutions.csv (ties alphabetical); point = median lat and median lon")
    L["_arc_rule"] = (f"quadratic Bezier in Robinson coordinates centred on {CENTRAL_LON:g}E; control point "
                      f"{ARC_BOW:g} x chord length off the chord midpoint on the northern side; frame "
                      f"{LAT_MIN:g} to {LAT_MAX:g} degrees latitude")
    L["_land_rule"] = ("ETOPO5 1-degree mask (cells centred on half degrees, topolegend [1 90 0]) split "
                       "into 0.5-degree cells, 3x3 max (coast out by half a 1-degree cell), 3x3 mean, "
                       "filled at 0.5; a marker is at sea when the bilinear value < 0.5")
    L["_inputs_sha256"] = dict(sorted(PINS.items()))
    L["_network_requests"] = 0
    return L


# ---------------------------------------------------------------------------------------------------
# land
# ---------------------------------------------------------------------------------------------------
#: cell geometry of the mask, from the grid's own georeference in topo.mat (topolegend = [1 90 0],
#: topolatlim = [-90 90], topolonlim = [0 360]): 1-degree cells with edges on whole degrees, so cell
#: (k, j) is centred on latitude -89.5 + k and longitude 0.5 + j. (MATLAB's contour demo labels the
#: cells -89..90 / 0..359, half a degree north-west of their centres; the map used that labelling
#: until the 2026-09-23 revision.)
MASK_LAT0, MASK_LON0 = -89.5, 0.5


def raw_mask(mask: list[str]):
    """The 1-degree mask as an array: row k centred on latitude -89.5+k, column j on longitude 0.5+j."""
    import numpy as np
    return np.array([[1.0 if ch == "1" else 0.0 for ch in ln] for ln in mask])


def _neighbours(A):
    """The 9 shifted copies of A for a 3x3 window; longitude (columns) wraps, latitude edges repeat."""
    import numpy as np
    P = np.pad(A, ((1, 1), (0, 0)), mode="edge")
    P = np.concatenate([P[:, -1:], P, P[:, :1]], axis=1)
    h, w = A.shape
    return [P[1 + di:1 + di + h, 1 + dj:1 + dj + w] for di in (-1, 0, 1) for dj in (-1, 0, 1)]


def land_fields(mask: list[str]):
    """Half-degree land field: the 1-degree mask split into 0.5-degree cells (centres lat
    -89.75 + 0.5 i, lon 0.25 + 0.5 j), expanded by one cell (3x3 max) and smoothed (3x3 mean).
    Land where the field >= 0.5."""
    import numpy as np
    F = np.repeat(np.repeat(raw_mask(mask), 2, axis=0), 2, axis=1)
    D = np.max(np.stack(_neighbours(F)), axis=0)
    return np.mean(np.stack(_neighbours(D)), axis=0)


def _bilinear(G, lat: float, lon: float, lat0: float, lon0: float, step: float) -> float:
    fi = (lat - lat0) / step
    fj = ((lon - lon0) % 360.0) / step
    i0 = min(max(int(math.floor(fi)), 0), G.shape[0] - 2)
    ti = min(max(fi - i0, 0.0), 1.0)
    j0 = int(math.floor(fj)) % G.shape[1]
    j1 = (j0 + 1) % G.shape[1]
    tj = fj - math.floor(fj)
    return float((1 - ti) * (1 - tj) * G[i0, j0] + (1 - ti) * tj * G[i0, j1]
                 + ti * (1 - tj) * G[i0 + 1, j0] + ti * tj * G[i0 + 1, j1])


def land_at(S, lat: float, lon: float) -> float:
    """Bilinear value of the expanded half-degree land field at a place."""
    return _bilinear(S, lat, lon, MASK_LAT0 - 0.25, MASK_LON0 - 0.25, 0.5)


def raw_land_at(M, lat: float, lon: float) -> float:
    """Bilinear value of the raw 1-degree mask at a place (what the unexpanded 0.5 contour draws)."""
    return _bilinear(M, lat, lon, MASK_LAT0, MASK_LON0, 1.0)


# ---------------------------------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------------------------------
_ROB_X = (1.0000, 0.9986, 0.9954, 0.9900, 0.9822, 0.9730, 0.9600, 0.9427, 0.9216, 0.8962, 0.8679,
          0.8350, 0.7986, 0.7597, 0.7186, 0.6732, 0.6213, 0.5722, 0.5322)
_ROB_Y = (0.0000, 0.0620, 0.1240, 0.1860, 0.2480, 0.3100, 0.3720, 0.4340, 0.4958, 0.5571, 0.6176,
          0.6769, 0.7346, 0.7903, 0.8435, 0.8936, 0.9394, 0.9761, 1.0000)


def rel_lon(lon):
    """Longitude relative to the central meridian, in [-180, 180)."""
    import numpy as np
    return (np.asarray(lon, dtype=float) - CENTRAL_LON + 180.0) % 360.0 - 180.0


def robinson(rlon, lat):
    """Robinson projection (Snyder's 5-degree table, linear interpolation) of relative lon/lat."""
    import numpy as np
    rlon, lat = np.asarray(rlon, dtype=float), np.asarray(lat, dtype=float)
    a = np.abs(lat)
    grid = np.arange(0.0, 91.0, 5.0)
    x = 0.8487 * np.interp(a, grid, _ROB_X) * np.radians(rlon)
    y = 1.3523 * np.interp(a, grid, _ROB_Y) * np.sign(lat)
    return x, y


def inside_frame(x, y, tol: float = 1e-9):
    """True where projected points lie inside the map frame (the Robinson outline, LAT_MIN..LAT_MAX)."""
    import numpy as np
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    grid = np.arange(0.0, 91.0, 5.0)
    lat = np.sign(y) * np.interp(np.abs(y) / 1.3523, _ROB_Y, grid)
    x_edge = 0.8487 * np.interp(np.abs(lat), grid, _ROB_X) * np.pi
    _xl, y_lo = robinson(0.0, LAT_MIN)
    _xh, y_hi = robinson(0.0, LAT_MAX)
    return (np.abs(x) <= x_edge + tol) & (y >= y_lo - tol) & (y <= y_hi + tol)


def arc_xy(lat0: float, lon0: float, lat1: float, lon1: float, n: int = 121):
    """Projected points of the drawn arc: a quadratic Bezier from origin to destination whose control
    point sits ARC_BOW x chord length off the chord's midpoint, on the northern (upper) side."""
    import numpy as np
    x0, y0 = robinson(rel_lon(lon0), lat0)
    x1, y1 = robinson(rel_lon(lon1), lat1)
    x0, y0, x1, y1 = float(x0), float(y0), float(x1), float(y1)
    dx, dy = x1 - x0, y1 - y0
    chord = math.hypot(dx, dy)
    if chord == 0.0:
        return np.array([x0, x1]), np.array([y0, y1])
    nx, ny = -dy / chord, dx / chord
    if ny < 0 or (ny == 0 and nx < 0):
        nx, ny = -nx, -ny
    cx, cy = (x0 + x1) / 2 + ARC_BOW * chord * nx, (y0 + y1) / 2 + ARC_BOW * chord * ny
    t = np.linspace(0.0, 1.0, n)
    return ((1 - t) ** 2 * x0 + 2 * t * (1 - t) * cx + t ** 2 * x1,
            (1 - t) ** 2 * y0 + 2 * t * (1 - t) * cy + t ** 2 * y1)


# ---------------------------------------------------------------------------------------------------
# drawing (2026-10-01: colour unit-dot map; the code is in fig_star_origins_dots.py)
# ---------------------------------------------------------------------------------------------------
def draw(ev: list[dict], L: dict, pdf: Path, png: Path) -> dict:
    """Draw Figure 1 (fig_star_origins_dots.draw) into pdf and png; return its report: the figure's
    words (report["texts"]: the three legend labels and seven country codes, nothing else), its size,
    the destination nudge and the layout diagnostics."""
    from analysis.paper import fig_star_origins_dots as D
    return D.draw(ev, L, pdf, png)


def _block_rule_note(rules: dict | None) -> str:
    """The R1 exceptions to the fill rule at this run's counts ('' when none, as in October)."""
    from analysis.paper import fig_star_origins_dots as D
    notes = []
    if rules and rules.get("wide"):
        notes.append(f"Europe-panel blocks that rows of ten would make taller than {D.EU_MAX_ROWS} rows take whole "
                     "tens per row and grow west: "
                     + ", ".join(f"{cc} {r} per row" for cc, r in sorted(rules["wide"].items())))
    if rules and rules.get("serpentine"):
        notes.append("blocks whose left-to-right fill would split a discipline's run are filled serpentine "
                     "(odd rows right to left): " + ", ".join(rules["serpentine"]))
    return ". At this run's counts: " + "; ".join(notes) if notes else ""


def figure_ledger(rep: dict) -> dict:
    """The ledger keys about the drawing (added 2026-10-01; values from draw()'s report)."""
    from analysis.paper import fig_star_origins_dots as D
    out = {
        "_figure_rule": (
            f"analysis/paper/fig_star_origins_dots.py: one {D.DOT_MM:g}-mm dot per event; the dots of one "
            f"origin country form one block on that country ({D.ROW} per row, bottom row first, economics, "
            "chemistry, mathematics & statistics in that order); world map (Robinson centred on "
            f"{CENTRAL_LON:g}E) plus an enlarged Europe panel; land = Natural Earth 1:50m "
            "(data/paper_inputs/basemap/ne_50m_land.geojson); one triangle per destination place, those that "
            f"touch nudged apart by the least move leaving {D.DEST_CLEAR_MM:g} mm of clear land between their "
            "white rims (figure_destination_nudge_mm: mm on the figure, east and north). The figure draws "
            "no arcs and not the ETOPO5 mask: _arc_rule / *_arcs_leaving_frame and _land_rule / *_at_sea* "
            "are compute()'s checks, unchanged since 2026-09-23") + _block_rule_note(rep.get("block_rules")),
        "figure_text": list(rep["texts"]),
        "figure_size_cm": list(rep["size_cm"]),
        "figure_destination_nudge_mm": rep["nudge_mm"],
    }
    rules = rep.get("block_rules") or {}
    if rules.get("serpentine") or rules.get("wide"):
        # Codex STOP 2: the caption says 'grouped in rows of ten'; the exceptions as data, for gate 2 to send to the
        # author (no key when there are none: October's ledger is unchanged)
        out[FIGURE_EXCEPTIONS_KEY] = {"rows_of": D.ROW, "serpentine": sorted(rules.get("serpentine") or []),
                                      "wide": dict(sorted((rules.get("wide") or {}).items()))}
    return out


#: the per-event CSV: institution names and places only — no person, no author id
CSV_COLUMNS = ("discipline", "event_row", "school", "destination_institution", "arrival_year",
               "arrival_period", "origin_status", "origin_source", "origin_placement", "origin_institution",
               "origin_institution_id", "origin_institution_type", "origin_city", "origin_country",
               "origin_country_name", "origin_region", "origin_lat", "origin_lon", "machine_institution",
               "machine_institution_id", "machine_country", "machine_affiliation_year", "machine_year_gap",
               "machine_rule", "machine_id_source", "machine_tie_break", "machine_n_works_in_year",
               "machine_n_candidates", "origin_at_sea", "origin_at_sea_raw_mask", "arc_leaves_frame")


def write_outputs(ev: list[dict], L: dict, outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "data_numbers_star_origins.json").write_text(
        json.dumps(L, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_COLUMNS)
    order = {k: i for i, (k, _p, _t) in enumerate(FIELDS)}
    for r in sorted(ev, key=lambda r: (order[r["discipline"]], r["event_row"])):
        w.writerow(["" if r.get(c) is None else r.get(c) for c in CSV_COLUMNS])
    (outdir / "star_origins_2026-10.csv").write_text(buf.getvalue(), encoding="utf-8")


def shown(p: Path) -> str:
    """A path for printing: relative to the repo when it lies inside it, else absolute (the output
    directory can sit outside the repo under $SAR_PATHS_CONFIG)."""
    try:
        return str(p.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def main() -> None:
    P = load_paths()
    outdir = P["output"] / "paper"
    inp = load_inputs()
    ev, L = compute(inp)
    outdir.mkdir(parents=True, exist_ok=True)
    rep = draw(ev, L, outdir / "fig_star_origins.pdf", outdir / "fig_star_origins.png")
    L.update(figure_ledger(rep))          # the drawing keys; every compute() key is left as it is
    write_outputs(ev, L, outdir)
    print(f"events {L['pooled_events']}, with origin {L['pooled_with_origin']} "
          f"(human {L['pooled_origin_source_human']}, machine {L['pooled_origin_source_machine']}), "
          f"countries {L['pooled_origin_countries']}; figure {rep['pdf_cm'][0]:g} x {rep['pdf_cm'][1]:g} cm, "
          f"{rep['pdf_kb']} kB, text {rep['texts']}, PDF text layer "
          f"{rep['pdf_tokens'] if rep['pdf_tokens'] is not None else 'not checked (no pdftotext on PATH)'}; "
          f"destination nudge mm {rep['nudge_mm']} -> {shown(outdir / 'fig_star_origins.pdf')}")
    print(f"labels (code, own-row mm, next-block mm, frame mm) {rep['labels']}; destinations: least "
          f"clearance {rep['dest_min_clear_mm']} mm, drawn as one {rep['dest_coincident']}, centre on "
          f"Australian land {rep['dest_centre_on_land']}; land {rep['land']}; panels {rep['panels_cm']}")


if __name__ == "__main__":
    main()
