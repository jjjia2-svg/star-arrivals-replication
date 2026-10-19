"""Tests for the star-origins map, Figure 1 (analysis/paper/fig_star_origins.py, 2026-09-23; revised the
same day: human-verified origins first; drawing replaced 2026-10-01 by the colour unit-dot map in
analysis/paper/fig_star_origins_dots.py, 15 x 12 cm, three legend labels and seven country codes).

Everything here runs on the pinned repo inputs (no data disk, no network): the ledger's shape and
totals, the override table (shape, counts, no personal names, applied exactly, guards), byte-
determinism of the ledger / CSV / figure, the figure's text (three discipline names and the codes CA,
NL, BE, CH, AT, HK, SG, nothing else), the written ledger (compute()'s keys untouched, plus the
documented figure_* keys), the destination nudge (Sydney and Canberra apart, nothing else touching),
the Natural Earth basemap pin, the arc-frame and ETOPO5 sea-side checks that compute() still makes,
the OpenAlex rule on hand-made cases (numeric id tie-break included), the pins against the manifests,
and the cross-check's parsers. Two tests need things outside the repo and skip without them: the
override check against the human records (legacy trees) and the PyMuPDF word count (a python3 with
PyMuPDF on PATH)."""
import copy
import csv
import hashlib
import importlib.util
import json
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import analysis.paper.fig_star_origins as F  # noqa: E402
import analysis.paper.fig_star_origins_dots as D  # noqa: E402

PREFIXES = ("econ", "chem", "math", "pooled")
EVENT_COUNTS = {"econ": 113, "chem": 38, "math": 33, "pooled": 184}
#: human-verified origins (2026-09-23): events per discipline and per placement
HUMAN_COUNTS = {"econ": 59, "chem": 17, "math": 13, "pooled": 89}
PLACEMENT_COUNTS = {"human_institution": 87, "machine_institution_same_country": 1, "country_main_city": 1}
LEGEND = ["Chemistry", "Economics", "Mathematics & Statistics"]
#: the country codes the figure writes (2026-10-01: HK and SG added at the reviewer's request)
CODES = ["AT", "BE", "CA", "CH", "HK", "NL", "SG"]
FIGURE_TEXT = sorted(LEGEND + CODES)
#: the ledger keys main() adds about the drawing (2026-10-01)
FIGURE_KEYS = {"_figure_rule", "figure_text", "figure_size_cm", "figure_destination_nudge_mm"}
NE_REL = "data/paper_inputs/basemap/ne_50m_land.geojson"
OVR = REPO / "data" / "paper_inputs" / "star_origins_2026-10" / "human_origin_overrides.csv"
#: tracked economics star names (author_id, name) covering every cal2026-10 economics event star
ECON_NAMES_REPO = REPO / "data" / "cal2026-10" / "restake_econ11_aug_all_2026-10.csv"


@pytest.fixture(scope="module")
def inp():
    return F.load_inputs()


@pytest.fixture(scope="module")
def computed(inp):
    return F.compute(inp)


@pytest.fixture(scope="module")
def drawn(computed, tmp_path_factory):
    """One drawing of the figure: (report, pdf bytes, png bytes)."""
    d = tmp_path_factory.mktemp("fig")
    ev, L = computed
    rep = F.draw(ev, L, d / "f.pdf", d / "f.png")
    return rep, (d / "f.pdf").read_bytes(), (d / "f.png").read_bytes()


def _xc():
    spec = importlib.util.spec_from_file_location("xc", REPO / "tools" / "star_origins_crosscheck_2026-10.py")
    xc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(xc)
    return xc


def _event_tables():
    out = {}
    for key, _p, _t in F.FIELDS:
        with open(REPO / "data" / "cal2026-10" / f"events_{key}_cal2026-10.csv", newline="", encoding="utf-8") as fh:
            out[key] = list(csv.DictReader(fh))
    return out


def _econ_star_names() -> tuple[list[str], bool]:
    """Names of the economics event stars: from the tracked restake table (in the repo) and, when on
    this machine, the legacy coverage file; ([], False) when neither source exists. The bool says
    whether the tracked source was found and covered every economics event star."""
    stars = {r["star_id"] for r in _event_tables()["econ"]}
    names, covered = [], False
    if ECON_NAMES_REPO.is_file():
        with open(ECON_NAMES_REPO, newline="", encoding="utf-8") as fh:
            got = {r["author_id"]: r["name"] for r in csv.DictReader(fh) if r["author_id"] in stars and r["name"]}
        names += list(got.values())
        covered = set(got) == stars
    cov = pathlib.Path(F.load_paths()["legacy_v2_output"]) / "star_check_coverage_2026-09-14" / "star_check_coverage.csv"
    if cov.is_file():
        with open(cov, newline="", encoding="utf-8") as fh:
            names += [r["name"] for r in csv.DictReader(fh) if r["discipline"] == "econ"]
    return sorted(set(names)), covered


# ---------------------------------------------------------------------------------------------------
# ledger
# ---------------------------------------------------------------------------------------------------
def test_event_counts_match_event_tables(computed):
    _ev, L = computed
    for key, pre, _t in F.FIELDS:
        assert L[f"{pre}_events"] == len(_event_tables()[key]) == EVENT_COUNTS[pre]
    assert L["pooled_events"] == sum(L[f"{p}_events"] for p in ("econ", "chem", "math")) == 184


def test_ledger_shape(computed):
    _ev, L = computed
    scalar = ("events", "with_origin", "origin_unknown", "coverage_pct", "origin_source_human",
              "origin_source_machine", "human_same_institution_as_machine", "human_changed_institution",
              "human_changed_country", "machine_with_origin", "rule_t_minus_1", "rule_latest_pre",
              "via_u2_fragments", "via_api", "max_year_gap", "machine_origin_countries",
              "arcs_leaving_frame", "origin_markers_at_sea", "origin_markers_at_sea_raw_mask",
              "origin_countries", "origin_institutions", "n_us", "share_us_pct", "n_gb", "share_gb_pct",
              "n_us_gb", "share_us_gb_pct", "n_europe_ex_gb", "share_europe_ex_gb_pct",
              "arrival_year_min", "arrival_year_max", "destination_universities")
    for pre in PREFIXES:
        for k in scalar:
            assert isinstance(L[f"{pre}_{k}"], (int, float)), f"{pre}_{k}"
        for name, _codes in F.REGIONS:
            assert isinstance(L[f"{pre}_n_{name}"], int)
            assert isinstance(L[f"{pre}_share_{name}_pct"], float)
        for k in ("year_gap_counts", "tie_break_counts", "country_counts", "machine_country_counts",
                  "arrival_period_counts", "placement_counts", "origin_type_counts"):
            assert isinstance(L[f"{pre}_{k}"], dict)
        for k in ("top_countries", "machine_top_countries"):
            top = L[f"{pre}_{k}"]
            assert 1 <= len(top) <= 10
            assert all(len(t) == 4 and t[1] == F.COUNTRY_NAMES[t[0]] for t in top)
            counts = [t[2] for t in top]
            assert counts == sorted(counts, reverse=True)
    for k in ("pooled_affiliation_cells_dropped_no_country", "pooled_institutions_dropped_no_country",
              "pooled_origins_changed_if_no_country_kept", "pooled_destination_places",
              "pooled_destination_markers_at_sea", "pooled_destination_markers_at_sea_raw_mask"):
        assert isinstance(L[k], int), k
    assert L["_inputs_sha256"] == F.PINS
    assert L["_network_requests"] == 0 and L["pooled_via_api"] == 0


def test_coverage_totals(computed):
    ev, L = computed
    assert len(ev) == 184
    for pre in PREFIXES:
        n, found, mach = L[f"{pre}_events"], L[f"{pre}_with_origin"], L[f"{pre}_machine_with_origin"]
        assert found + L[f"{pre}_origin_unknown"] == n
        assert L[f"{pre}_origin_source_human"] + L[f"{pre}_origin_source_machine"] == found
        assert L[f"{pre}_origin_source_human"] == HUMAN_COUNTS[pre]
        assert sum(L[f"{pre}_placement_counts"].values()) == found
        assert L[f"{pre}_placement_counts"]["machine_rule"] == L[f"{pre}_origin_source_machine"]
        assert (L[f"{pre}_human_same_institution_as_machine"] + L[f"{pre}_human_changed_institution"]
                == L[f"{pre}_origin_source_human"])
        assert L[f"{pre}_rule_t_minus_1"] + L[f"{pre}_rule_latest_pre"] == mach
        assert sum(L[f"{pre}_year_gap_counts"].values()) == mach
        assert L[f"{pre}_year_gap_counts"].get("0", 0) == L[f"{pre}_rule_t_minus_1"]
        assert sum(L[f"{pre}_tie_break_counts"].values()) == mach
        assert sum(L[f"{pre}_machine_country_counts"].values()) == mach
        assert sum(L[f"{pre}_country_counts"].values()) == found
        assert sum(L[f"{pre}_origin_type_counts"].values()) == found
        assert len(L[f"{pre}_country_counts"]) == L[f"{pre}_origin_countries"]
        assert sum(L[f"{pre}_n_{name}"] for name, _c in F.REGIONS) == found
        assert sum(L[f"{pre}_arrival_period_counts"].values()) == n
        assert "AU" not in L[f"{pre}_country_counts"] and "AU" not in L[f"{pre}_machine_country_counts"]
    assert {k: L["pooled_placement_counts"][k] for k in PLACEMENT_COUNTS} == PLACEMENT_COUNTS
    for k in ("with_origin", "origin_unknown", "origin_source_human", "origin_source_machine",
              "human_changed_institution", "human_changed_country", "rule_t_minus_1", "rule_latest_pre",
              "via_u2_fragments", "arcs_leaving_frame", "origin_markers_at_sea", "n_us", "n_gb"):
        assert L[f"pooled_{k}"] == sum(L[f"{p}_{k}"] for p in ("econ", "chem", "math")), k
    # every event is placed: an origin with coordinates abroad and a destination in Australia
    for r in ev:
        assert r["origin_status"] == "found" and r["machine_institution_id"]
        assert r["origin_country"] != "AU" and r["machine_country"] != "AU"
        assert -90 <= r["origin_lat"] <= 90 and -180 <= r["origin_lon"] <= 180
        assert -45 < r["destination_lat"] < -10 and 110 < r["destination_lon"] < 155
    # the sensitivity run: institutions without any country change no origin
    assert L["pooled_origins_changed_if_no_country_kept"] == 0


def test_ledger_deterministic(computed, tmp_path):
    ev, L = computed
    ev2, L2 = F.compute()
    assert json.dumps(L, sort_keys=True) == json.dumps(L2, sort_keys=True)
    a, b = tmp_path / "a", tmp_path / "b"
    F.write_outputs(ev, L, a)
    F.write_outputs(ev2, L2, b)
    for name in ("data_numbers_star_origins.json", "star_origins_2026-10.csv"):
        assert (a / name).read_bytes() == (b / name).read_bytes(), name


# ---------------------------------------------------------------------------------------------------
# the human override table
# ---------------------------------------------------------------------------------------------------
def test_override_table_shape_and_events(inp):
    rows = list(csv.DictReader(open(OVR, newline="", encoding="utf-8")))
    assert tuple(rows[0].keys()) == ("discipline", "event_row", "star_id", "school", "arrival_year", "placement",
                                     "institution_id", "coords_from", "country_code")
    assert len(rows) == 89 == len({(r["discipline"], r["event_row"]) for r in rows})
    by = {key: sum(r["discipline"] == key for r in rows) for key, _p, _t in F.FIELDS}
    assert by == {"econ": 59, "chemistry": 17, "math_stats": 13}
    assert {p: sum(r["placement"] == p for r in rows) for p in F.PLACEMENTS} == PLACEMENT_COUNTS
    tables = _event_tables()
    for r in rows:
        e = tables[r["discipline"]][int(r["event_row"]) - 1]
        star = e["star_id"] if r["discipline"] == "econ" else e["author_id"]
        year = e["arrival_year"] if r["discipline"] == "econ" else e["arrival_corrected"]
        assert (r["star_id"], r["school"], r["arrival_year"]) == (star, e["school"], year)
        assert r["country_code"] in F.COUNTRY_NAMES and r["country_code"] != "AU"
        assert not {"human_evidence", "source_docs", "recheck"}.intersection(r)
        if r["placement"] == "human_institution":
            assert inp["inst"][r["institution_id"]]["country_code"] == r["country_code"]
        else:
            assert r["institution_id"] == "" and r["coords_from"] == ""
        if r["coords_from"]:
            assert r["placement"] == "human_institution" and inp["inst"][r["coords_from"]]["latitude"]
    assert sum(bool(r["coords_from"]) for r in rows) == 1


def test_override_table_has_no_personal_names(inp):
    text = OVR.read_text(encoding="utf-8")
    low = text.lower()
    assert not re.search(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", text), "an ORCID id"
    assert "http" not in low and "@" not in text
    ids = _public_event_ids()
    rows = list(csv.DictReader(open(OVR, newline="", encoding="utf-8")))
    assert len(rows) == 89
    columns = {"discipline", "event_row", "star_id", "school", "arrival_year", "placement",
               "institution_id", "coords_from", "country_code"}
    for r in rows:
        # Every surviving cell has a closed domain; no free-text name carrier remains.
        assert set(r) == columns
        assert r["discipline"] in {field for field, _prefix, _label in F.FIELDS}
        assert re.fullmatch(r"[1-9][0-9]*", r["event_row"])
        assert re.fullmatch(r"[0-9]{4}", r["arrival_year"])
        assert r["star_id"] in ids
        assert r["school"] in inp["dest"]
        assert r["placement"] in F.PLACEMENTS
        assert r["country_code"] in F.COUNTRY_NAMES
        for column in ("institution_id", "coords_from"):
            assert r[column] == "" or (re.fullmatch(r"I[0-9]+", r[column]) and r[column] in inp["inst"])


def _public_event_ids():
    """Public events retain every id and row, with personal-name columns absent."""
    tables = _event_tables()
    ids = set()
    for field, prefix, _label in F.FIELDS:
        rows = tables[field]
        assert len(rows) == EVENT_COUNTS[prefix]
        field_ids = set()
        for r in rows:
            assert not {"name", "display_name"}.intersection(r)
            star = r.get("star_id") or r["author_id"]
            assert re.fullmatch(r"A[0-9]+", star)
            field_ids.add(star)
        assert len(field_ids) == EVENT_COUNTS[prefix]
        ids.update(field_ids)
    assert sum(len(rows) for rows in tables.values()) == EVENT_COUNTS["pooled"]
    return ids


def _okey(inp, field: str, row: int) -> tuple:
    """The override key of the event in row `row` of a field's event table: (discipline, star_id, arrival_year)
    (R1 F21: overrides follow their event, not its row)."""
    e = {(e["field"], e["event_row"]): e for e in inp["events"]}[(field, row)]
    return (e["field"], e["star"], e["arrival"])


def test_overrides_applied_exactly(computed, inp):
    ev, L = computed
    ovr = inp["overrides"]
    assert len(ovr) == 89 and all(len(k) == 3 and isinstance(k[2], int) for k in ovr)
    for r in ev:
        key = _okey(inp, r["discipline"], r["event_row"])
        if key not in ovr:
            assert r["origin_source"] == "machine" and r["origin_placement"] == "machine_rule"
            assert r["origin_institution_id"] == r["machine_institution_id"]
            assert r["origin_country"] == r["machine_country"]
            continue
        o = ovr[key]
        assert r["origin_source"] == "human" and r["origin_placement"] == o["placement"]
        assert r["origin_country"] == o["country_code"]
        if o["placement"] == "human_institution":
            assert r["origin_institution_id"] == o["institution_id"]
            c = inp["inst"][o["coords_from"] or o["institution_id"]]
            assert (r["origin_lat"], r["origin_lon"]) == (float(c["latitude"]), float(c["longitude"]))
        elif o["placement"] == "machine_institution_same_country":
            assert r["origin_institution_id"] == r["machine_institution_id"]
            assert r["machine_country"] == o["country_code"]
        else:
            assert r["origin_institution_id"] == "" and r["machine_country"] != o["country_code"]
            city, lat, lon, _n = F.main_city(o["country_code"], inp["inst"])
            assert (r["origin_city"], r["origin_lat"], r["origin_lon"]) == (city, lat, lon)
    # the author-facing counts: 89 human origins, of which 18 move the institution and 10 the country
    assert (L["pooled_origin_source_human"], L["pooled_origin_source_machine"]) == (89, 95)
    assert (L["pooled_human_changed_institution"], L["pooled_human_changed_country"]) == (18, 10)
    assert L["pooled_human_same_institution_as_machine"] == 71
    # chemistry event 12: the record (filed under an alias id) names the institution the rule gives
    r12 = {(r["discipline"], r["event_row"]): r for r in ev}[("chemistry", 12)]
    assert (r12["origin_source"], r12["origin_institution"], r12["origin_country"]) == (
        "human", "I172675005", "SG")
    assert r12["origin_institution_id"] == r12["machine_institution_id"]
    # the secondary labels the verifier found are gone where a record names the employer
    names = {(r["discipline"], r["event_row"]): r["origin_institution"] for r in ev}
    assert names[("chemistry", 37)] == "I47508984"
    assert names[("econ", 30)] == "I91136226"
    assert "I185658715" not in names.values() and "I2802720485" not in names.values()


def test_main_city_rule(inp):
    city, lat, lon, n = F.main_city("GB", inp["inst"])
    assert city.startswith("place_") and n >= 20 and 51 < lat < 52 and -1 < lon < 1
    toy = {"I1": {"country_code": "XX", "city": "B", "latitude": "1", "longitude": "1", "in_snapshot": "1"},
           "I2": {"country_code": "XX", "city": "A", "latitude": "3", "longitude": "5", "in_snapshot": "1"},
           "I3": {"country_code": "XX", "city": "B", "latitude": "2", "longitude": "3", "in_snapshot": "1"},
           "I4": {"country_code": "XX", "city": "A", "latitude": "4", "longitude": "7", "in_snapshot": "1"},
           "I5": {"country_code": "YY", "city": "C", "latitude": "9", "longitude": "9", "in_snapshot": "1"}}
    assert F.main_city("XX", toy) == ("A", 3.5, 6.0, 2)          # tie on 2 -> alphabetical; medians


def test_override_guards(inp):
    def run_with(mutate):
        bad = dict(inp)
        bad["overrides"] = copy.deepcopy(inp["overrides"])
        mutate(bad["overrides"])
        return F.compute(bad)
    k1, k103, k94 = _okey(inp, "econ", 1), _okey(inp, "econ", 103), _okey(inp, "econ", 94)
    with pytest.raises(SystemExit, match="does not match"):
        run_with(lambda o: o[k1].update(school="uwa"))
    with pytest.raises(SystemExit, match="does not match"):
        run_with(lambda o: o[k1].update(star_id="A1"))
    with pytest.raises(SystemExit, match="missing or not in"):
        run_with(lambda o: o[k1].update(country_code="GB"))
    with pytest.raises(SystemExit, match="machine institution is not in"):
        run_with(lambda o: o[k103].update(country_code="DE"))
    with pytest.raises(SystemExit, match="use machine_institution_same_country"):
        run_with(lambda o: o[k94].update(country_code="CA"))
    with pytest.raises(SystemExit, match="without an event"):
        run_with(lambda o: o.__setitem__(("econ", "A0000000999", 1999), dict(o[k1])))


# ---------------------------------------------------------------------------------------------------
# figure
# ---------------------------------------------------------------------------------------------------
def test_figure_deterministic_and_text(computed, drawn, tmp_path):
    ev, L = computed
    rep, pdf1, png1 = drawn
    assert rep["texts"] == FIGURE_TEXT, rep["texts"]
    assert list(D.FIGURE_TEXT) == FIGURE_TEXT and sorted(D.LABELS) == CODES
    rep2 = F.draw(ev, L, tmp_path / "f2.pdf", tmp_path / "f2.png")
    assert (tmp_path / "f2.pdf").read_bytes() == pdf1 and (tmp_path / "f2.png").read_bytes() == png1
    assert rep2["nudge_mm"] == rep["nudge_mm"]
    assert len(pdf1) > 30_000
    assert b"/CreationDate (D:20260923000000Z)" in pdf1
    box = re.search(rb"/MediaBox \[\s*0 0 ([\d.]+) ([\d.]+)\s*\]", pdf1)
    assert abs(float(box.group(1)) - 15.0 / 2.54 * 72) < 0.01          # 15 cm wide: fonts print at 9 / 8 pt
    assert abs(float(box.group(2)) - 12.0 / 2.54 * 72) < 0.01          # 12 cm high (the budget)
    assert rep["size_cm"] == (15.0, 12.0) and rep["pdf_cm"] == (15.0, 12.0)
    assert F.FONT_PT >= 8 and D.LABEL_PT >= 8
    if rep["pdf_tokens"] is not None:                                   # poppler on PATH
        assert sorted(rep["pdf_tokens"]) == sorted(" ".join(FIGURE_TEXT).split())
    # every code is right next to its own row and clearly farther from any other block
    labs = {cc: (d_own, d_next) for cc, d_own, d_next, _edge in rep["labels"]}
    assert sorted(labs) == CODES
    assert all(d_own <= 1.5 and d_next >= d_own + 1.0 for d_own, d_next in labs.values()), labs


def test_figure_words_pymupdf(drawn, tmp_path):
    """The figure's words as the course counter sees them (PyMuPDF; a word has a letter or digit)."""
    py = shutil.which("python3")
    if not py or subprocess.run([py, "-c", "import fitz"], capture_output=True).returncode != 0:
        pytest.skip("no python3 with PyMuPDF on PATH")
    pdf = tmp_path / "f.pdf"
    pdf.write_bytes(drawn[1])
    code = ("import fitz,json,sys,re; d=fitz.open(sys.argv[1]); w=[x[4] for p in d for x in p.get_text('words')];"
            "print(json.dumps([len(d), w, sum(1 for t in w if re.search('[A-Za-z0-9]', t))]))")
    pages, toks, n = json.loads(subprocess.run([py, "-c", code, str(pdf)], capture_output=True, text=True,
                                               check=True).stdout)
    assert pages == 1 and sorted(toks) == sorted(["Economics", "Chemistry", "Mathematics", "&", "Statistics"] + CODES)
    assert n == 4 + len(CODES) == 11


def test_destination_nudge(drawn):
    """Reviewer 2026-10-01: the Sydney and Canberra triangles must not touch. Only those two move,
    apart along one axis, by the least amount that leaves DEST_CLEAR_MM between their white rims;
    afterwards no two triangles touch (Melbourne and Burwood draw as one)."""
    import numpy as np
    rep = drawn[0]
    assert rep["nudged_pairs"] == [("place_000092", "place_000499")]
    assert rep["unnudged_mm"]["place_000092-place_000499"] < 0                  # they overlapped
    nud = rep["nudge_mm"]
    assert sorted(nud) == ["place_000092", "place_000499"]
    c, s = np.array(nud["place_000092"]), np.array(nud["place_000499"])
    assert c[0] < 0 and c[1] < 0 < s[0] and s[1] > 0                  # Canberra WSW, Sydney ENE
    assert abs(c[0] * s[1] - c[1] * s[0]) < 1e-3                       # one axis
    assert 0 < np.hypot(*c) < np.hypot(*s) < 1.0                       # well under a triangle (1.9 mm)
    assert rep["dest_min_clear_mm"] >= D.DEST_CLEAR_MM - 1e-6
    assert rep["dest_coincident"] == [("place_000335", "place_000088", 0.07)]
    # least move: the pair ends at the clearance, and with 99% of the move it would still be too close
    O = D.dest_triangle(D.RIM_MM)
    pc, ps = np.array(rep["dest_pos_mm"]["place_000092"]), np.array(rep["dest_pos_mm"]["place_000499"])
    assert abs(D.poly_dist(O + pc + c, O + ps + s) - D.DEST_CLEAR_MM) < 5e-3     # nudge rounded to 0.001 mm
    assert D.poly_dist(O + pc + 0.99 * c, O + ps + 0.99 * s) < D.DEST_CLEAR_MM - 1e-4
    assert D.poly_dist(O + pc, O + ps) < 0


def test_destination_triangle_geometry():
    """The rim outline is the triangle with every edge moved out by the rim's half width."""
    import numpy as np
    T, O = D.dest_triangle(), D.dest_triangle(D.RIM_MM)
    assert np.allclose(T, [[0, D.DEST_MM / 2], [-D.DEST_MM / 2, -D.DEST_MM / 2], [D.DEST_MM / 2, -D.DEST_MM / 2]])
    for k in range(3):
        a, b = T[k], T[(k + 1) % 3]
        n = np.array([b[1] - a[1], a[0] - b[0]]) / np.hypot(*(b - a))   # outward for an anticlockwise ring
        if np.dot(n, a - T.mean(axis=0)) < 0:
            n = -n
        assert abs(float(np.dot(O[k] - a, n)) - D.RIM_MM) < 1e-12
    sq = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
    assert abs(D.poly_dist(sq, sq + [3.0, 0.0]) - 2.0) < 1e-12
    assert abs(D.poly_dist(sq, sq + [0.5, 0.0]) + 0.5) < 1e-12           # overlap depth


def test_arcs_stay_in_frame(computed):
    ev, L = computed
    assert L["pooled_arcs_leaving_frame"] == 0 and all(r["arc_leaves_frame"] == 0 for r in ev)
    # the arc that great circles could not draw: Rio de Janeiro -> Melbourne, whole and over the Pacific
    x, y = F.arc_xy(-22.98, -43.23, -37.91, 145.13)
    assert F.inside_frame(x, y).all()
    assert (F.rel_lon(-43.23) > 90) and (F.rel_lon(145.13) > -10)
    assert not F.inside_frame([0.0, 0.0, 3.0], [1.5, -1.5, 0.0]).any()      # above, below, beside


def test_geometry():
    import numpy as np
    x, y = F.robinson(np.array([0.0, 180.0]), np.array([0.0, 90.0]))
    assert abs(x[0]) < 1e-12 and abs(y[1] - 1.3523) < 1e-9
    assert F.rel_lon(150.0) == 0.0 and F.rel_lon(-30.0) == -180.0
    x, y = F.arc_xy(51.5, -0.1, -37.8, 145.0)
    x0, y0 = F.robinson(F.rel_lon(-0.1), 51.5)
    x1, y1 = F.robinson(F.rel_lon(145.0), -37.8)
    assert abs(x[0] - x0) < 1e-12 and abs(y[0] - y0) < 1e-12 and abs(x[-1] - x1) < 1e-12 and abs(y[-1] - y1) < 1e-12
    mid = len(x) // 2      # bows to the north side of the chord, by ARC_BOW / 2 of its length
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    chord = float(np.hypot(x1 - x0, y1 - y0))
    assert y[mid] > cy and abs(float(np.hypot(x[mid] - cx, y[mid] - cy)) - F.ARC_BOW / 2 * chord) < 1e-9


def test_land_mask_and_coast(computed, inp):
    lines = [ln for ln in (REPO / "data/paper_inputs/basemap/land_mask_etopo5_1deg.txt").read_text().splitlines()
             if not ln.startswith("#")]
    assert len(lines) == 180 and all(len(ln) == 360 and set(ln) <= {"0", "1"} for ln in lines)
    land = sum(ln.count("1") for ln in lines) / (180 * 360)
    assert 0.30 < land < 0.38

    def at(lat, lon):          # the 1-degree cell that contains a place (cells span whole degrees)
        return lines[int(lat + 90)][int(lon % 360)]
    assert at(-24.5, 134.5) == "1"     # central Australia
    assert at(23.5, 10.5) == "1"       # Sahara
    assert at(0.5, -149.5) == "0"      # Pacific
    assert at(30.5, -39.5) == "0"      # Atlantic
    assert (F.MASK_LAT0, F.MASK_LON0) == (-89.5, 0.5)
    S, M = F.land_fields(inp["mask"]), F.raw_mask(inp["mask"])
    assert S.shape == (360, 720) and M.shape == (180, 360)
    # Sydney (four destinations): at sea on the raw 1-degree coast, on land after the half-cell expansion
    assert F.raw_land_at(M, -33.87, 151.21) < 0.5 <= F.land_at(S, -33.87, 151.21)
    assert F.land_at(S, 0.0, -150.0) < 0.5 and F.land_at(S, -25.0, 134.0) == 1.0
    ev, L = computed
    assert L["pooled_destination_markers_at_sea"] == 0 < L["pooled_destination_markers_at_sea_raw_mask"]
    assert L["pooled_origin_markers_at_sea"] <= 2 < L["pooled_origin_markers_at_sea_raw_mask"]


def test_generator_runs_with_output_outside_the_repo(monkeypatch, tmp_path, capsys, computed):
    """main() prints its output path relative to the repo when it can, else absolute (verifier LOW:
    it used to crash on relative_to when output/ sat outside the repo). The ledger it writes is
    compute()'s ledger, every key and value unchanged, plus the four documented figure keys."""
    assert F.shown(REPO / "output" / "paper" / "x.pdf") == "output/paper/x.pdf"
    assert F.shown(tmp_path / "x.pdf") == str(tmp_path / "x.pdf")
    # only the output root moves: since W1-CANON the inputs are named through load_paths() too (src('cal', ...),
    # src('paper_inputs', ...)), so the stub keeps every real key and replaces 'output' alone
    real = F.load_paths()
    monkeypatch.setattr(F, "load_paths", lambda: {**real, "output": tmp_path})
    F.main()
    for name in ("fig_star_origins.pdf", "fig_star_origins.png", "star_origins_2026-10.csv"):
        assert (tmp_path / "paper" / name).is_file(), name
    assert str(tmp_path / "paper" / "fig_star_origins.pdf") in capsys.readouterr().out
    written = json.loads((tmp_path / "paper" / "data_numbers_star_origins.json").read_text(encoding="utf-8"))
    _ev, L = computed
    L = json.loads(json.dumps(L))                       # as JSON stores it (tuples -> lists)
    assert set(written) - set(L) == FIGURE_KEYS and set(L) <= set(written)
    assert {k: written[k] for k in L} == L
    assert written["figure_text"] == FIGURE_TEXT and written["figure_size_cm"] == [15.0, 12.0]
    assert sorted(written["figure_destination_nudge_mm"]) == ["place_000092", "place_000499"]
    assert "ne_50m_land.geojson" in written["_figure_rule"]


# ---------------------------------------------------------------------------------------------------
# per-event CSV
# ---------------------------------------------------------------------------------------------------
def test_no_personal_names_in_csv(computed, tmp_path):
    F.write_outputs(*computed, tmp_path)
    text = (tmp_path / "star_origins_2026-10.csv").read_text(encoding="utf-8")
    header = text.splitlines()[0].split(",")
    assert tuple(header) == F.CSV_COLUMNS
    assert not any(re.search(r"name|author|star", h) and h != "origin_country_name" for h in header)
    assert not re.search(r"\bA\d{8,}\b", text)          # no OpenAlex author id
    ids = _public_event_ids()
    low = text.lower()
    assert not any(s in text for s in ids)
    cov = pathlib.Path(F.load_paths()["legacy_v2_output"]) / "star_check_coverage_2026-09-14" / "star_check_coverage.csv"
    if cov.is_file():
        with open(cov, newline="", encoding="utf-8") as fh:
            econ_names = [r["name"] for r in csv.DictReader(fh) if r["discipline"] == "econ"]
        assert len(econ_names) >= 113
        for nm in econ_names:
            assert nm.lower() not in low, "a personal name leaked into the CSV"
    # institution columns hold snapshot institution names only (empty for a country-only origin)
    institutions = F.rows("data/paper_inputs/star_origins_2026-10/institutions.csv")
    assert institutions
    assert all(re.fullmatch(r"I[0-9]+", r["institution_id"]) and
               r["display_name"] == r["institution_id"] for r in institutions)
    assert all(r["city"] == "" or re.fullmatch(r"place_[0-9]{6}", r["city"]) for r in institutions)
    inst = {r["institution_id"] for r in institutions}
    cities = {r["city"] for r in institutions}
    with open(tmp_path / "star_origins_2026-10.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            assert r["destination_institution"] in inst and r["machine_institution"] in inst
            assert r["machine_institution"] == r["machine_institution_id"]
            assert r["origin_institution"] == r["origin_institution_id"]
            assert r["origin_city"] in cities or r["origin_city"] == ""
            assert r["origin_institution"] in inst or (r["origin_institution"] == ""
                                                       and r["origin_placement"] == "country_main_city")


# ---------------------------------------------------------------------------------------------------
# the OpenAlex rule
# ---------------------------------------------------------------------------------------------------
def _toy(aff_rows, inst_rows):
    aff = {}
    for a, i, y, cc, n in aff_rows:
        aff.setdefault(a, []).append((i, y, cc, n))
    inst = {i: {"country_code": cc} for i, cc in inst_rows}
    return aff, inst


def test_origin_rule_cases():
    US1, US2, AU, GB, X, Y, P, Q, N, A, B, S9, S10 = ("I101", "I102", "I103", "I104", "I105", "I106", "I107",
                                                     "I108", "I109", "I110", "I111", "I9", "I10")
    aff, inst = _toy(
        [("A1", US1, 2009, "US", 3), ("A1", US2, 2009, "US", 5), ("A1", AU, 2009, "AU", 9),
         ("A1", US1, 2008, "US", 1),
         ("A2", GB, 2006, "GB", 0), ("A2", AU, 2009, "AU", 4),
         ("A3", X, 2009, "FR", 2), ("A3", Y, 2009, "DE", 2), ("A3", X, 2005, "FR", 1),
         ("A4", P, 2009, "IT", 1), ("A4", Q, 2009, "", 2), ("A4", N, 2009, "", 7),
         ("A5", AU, 2009, "AU", 3), ("A5", US1, 2010, "US", 3),
         ("A6", B, 2009, "ES", 0), ("A6", A, 2009, "ES", 0),
         ("A7", S10, 2009, "ES", 1), ("A7", S9, 2009, "ES", 1)],
        [(US1, "US"), (US2, "US"), (AU, "AU"), (GB, "GB"), (X, "FR"), (Y, "DE"), (P, "IT"), (Q, "NL"),
         (A, "ES"), (B, "ES"), (S9, "ES"), (S10, "ES")])
    o = F.origin_of(["A1"], 2010, aff, inst)          # most works in T-1 wins; Australia ignored
    assert (o["institution_id"], o["rule"], o["gap"], o["tie_break"]) == (US2, "T-1", 0, "works")
    o = F.origin_of(["A2"], 2010, aff, inst)          # none abroad in T-1 -> latest earlier year
    assert (o["institution_id"], o["rule"], o["gap"], o["tie_break"]) == (GB, "latest_pre", 3, "single")
    o = F.origin_of(["A3"], 2010, aff, inst)          # equal works -> more pre-arrival years
    assert (o["institution_id"], o["tie_break"]) == (X, "years")
    o = F.origin_of(["A4"], 2010, aff, inst)          # N (no country anywhere) dropped; Q's record country used
    assert o["institution_id"] == Q and o["n_candidates"] == 2
    o = F.origin_of(["A4"], 2010, aff, inst, keep_no_country=True)   # sensitivity run keeps N (7 works)
    assert o["institution_id"] == N and o["n_candidates"] == 3
    assert F.origin_of(["A5"], 2010, aff, inst) is None   # only Australia before arrival (2010 is not before)
    o = F.origin_of(["A6"], 2010, aff, inst)          # full tie -> smaller id
    assert (o["institution_id"], o["tie_break"]) == (A, "id")
    o = F.origin_of(["A7"], 2010, aff, inst)          # compared as numbers: I9 < I10 (as strings I10 < I9)
    assert (o["institution_id"], o["tie_break"]) == (S9, "id")
    o = F.origin_of(["A1", "A3"], 2010, aff, inst)    # pooled ids: works summed per institution
    assert o["institution_id"] == US2 and o["n_candidates"] == 4
    assert F.iid_number("I27837315") < F.iid_number("I166437374")


def test_numeric_tie_break_on_real_events(computed):
    ev, _L = computed
    by = {(r["discipline"], r["event_row"]): r for r in ev}
    # four events decided by the id tie-break moved when the comparison became numeric (verifier LOW 1)
    assert by[("econ", 74)]["machine_institution"] == "I27837315"
    assert by[("econ", 18)]["machine_institution"] == "I18014758"
    assert all(by[k]["machine_tie_break"] == "id" for k in (("econ", 74), ("econ", 18), ("math_stats", 6),
                                                              ("math_stats", 16)))


def test_u2_fallback_only_when_own_id_is_empty(computed, inp):
    ev, _L = computed
    frag = [r for r in ev if r["machine_id_source"] == "u2_fragments"]
    assert frag and all(r["discipline"] == "econ" for r in frag)
    by_row = {(e["field"], e["event_row"]): e for e in inp["events"]}
    for r in frag:
        e = by_row[(r["discipline"], r["event_row"])]
        assert F.origin_of([e["star"]], e["arrival"], inp["aff"], inp["inst"]) is None


# ---------------------------------------------------------------------------------------------------
# pins and manifests
# ---------------------------------------------------------------------------------------------------
def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_pins_match_manifests_and_manifests_verify():
    for man in ("data/paper_inputs/star_origins_2026-10/MANIFEST.sha256",
                "data/paper_inputs/basemap/MANIFEST.sha256"):
        r = subprocess.run([sys.executable, str(REPO / "tools" / "verify_manifest.py"), man],
                           capture_output=True, text=True)
        assert r.returncode == 0 and "MANIFEST_OK" in r.stdout, r.stdout
        for line in (REPO / man).read_text().splitlines():
            h, rel = line.split("  ", 1)
            if rel in F.PINS:
                assert F.PINS[rel] == h, rel
    listed = {ln.split("  ", 1)[1] for ln in
              (REPO / "data/paper_inputs/star_origins_2026-10/MANIFEST.sha256").read_text().splitlines()}
    assert {"data/paper_inputs/star_origins_2026-10/human_origin_overrides.csv",
            "data/paper_inputs/star_origins_2026-10/README.md"} <= listed
    listed = {ln.split("  ", 1)[1] for ln in
              (REPO / "data/paper_inputs/basemap/MANIFEST.sha256").read_text().splitlines()}
    assert listed == {"data/paper_inputs/basemap/README.md", "data/paper_inputs/basemap/land_mask_etopo5_1deg.txt",
                      NE_REL}
    for rel, h in F.PINS.items():
        assert _sha(REPO / rel) == h, rel
    rep = json.loads((REPO / "data/paper_inputs/star_origins_2026-10/extract_report.json").read_text())
    assert rep["network_requests"] == 0 and rep["authors_missing"] == [] and rep["n_stars"] == 184
    for rel, h in rep["inputs_sha256"].items():
        assert _sha(REPO / rel) == h, rel


def test_natural_earth_basemap_pinned_and_documented():
    """The figure's land (2026-10-01): Natural Earth 1:50m, pinned, documented, read only through the pin."""
    assert F.PINS[NE_REL] == "e874b27a51d146452be360cafb3cc50c86001074a67d534113e6534682f9826b"
    assert _sha(REPO / NE_REL) == F.PINS[NE_REL]
    readme = (REPO / "data/paper_inputs/basemap/README.md").read_text(encoding="utf-8")
    for s in ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_land.geojson",
              "2026-10-01", "public domain", "naturalearthdata.com", F.PINS[NE_REL]):
        assert s in readme, s
    polys = D.load_land()                               # checks the feature count; drops south of 60 S
    assert len(polys) > 1000 and all(r[0][:, 1].max() > -60 for r in polys)
    assert D.NE_REL == NE_REL


# ---------------------------------------------------------------------------------------------------
# the cross-check
# ---------------------------------------------------------------------------------------------------
def test_crosscheck_parsers():
    xc = _xc()
    assert xc.countries("US") == ["US"]
    assert xc.countries("US/France (Visiting Assoc Prof Kellogg 2019-22)") == ["FR", "US"]
    assert xc.countries("University of Chicago (US)（修正）") == ["US"]
    assert xc.countries("New Zealand (Univ of Auckland 2003-2010)") == ["NZ"]
    assert xc.first_clause("CH (postdoc Univ. Geneva; PhD FU Berlin 2004)") == "postdoc Univ. Geneva"
    assert xc.same_institution("Massachusetts Institute of Technology", "MIT postdoc 2014-2016")
    assert xc.same_institution("Office Of Health Economics", "Office of Health Economics, London")
    assert xc.same_institution("University College London", "UCL 2009-14, Imperial 2001-09")
    assert xc.same_institution("University of Padua", "Italy (Univ of Padova, on unpaid leave)")
    assert xc.same_institution("California Polytechnic State University", "Cal Poly San Luis Obispo 2015-2021")
    assert not xc.same_institution("Uber AI (United States)", "United States (Yale SOM 2009-2015)")
    assert not xc.same_institution("University of Zurich", "postdoc, University of Chicago 2009-11")


def test_crosscheck_runs_with_output_outside_the_repo(monkeypatch, tmp_path, computed, capsys):
    """The cross-check's main() on an output directory outside the repo (verifier LOW: it crashed on
    relative_to); needs the legacy trees."""
    xc = _xc()
    assert xc.shown(REPO / "output" / "x.json") == "output/x.json"
    assert xc.shown(tmp_path / "x.json") == str(tmp_path / "x.json")
    P = F.load_paths()
    v2, th = pathlib.Path(P["legacy_v2_output"]), pathlib.Path(P["legacy_thesis"])
    if not ((v2 / xc.U4_REL).is_file() and (th / xc.VAULT_REL).is_file() and (v2 / xc.COVERAGE_REL).is_file()):
        pytest.skip("legacy human records not on this machine")
    F.write_outputs(*computed, tmp_path / "paper")
    monkeypatch.setattr(xc, "load_paths", lambda: {**P, "output": tmp_path})
    xc.main()
    out = capsys.readouterr().out
    assert "OVERRIDE_CHECK_OK" in out and str(tmp_path / "paper" / "star_origins_crosscheck_2026-10.json") in out


def test_crosscheck_override_table_against_the_records(inp):
    """Check A of the cross-check: every event with a human record has an override row and vice
    versa; countries and institutions match the records. Needs the legacy trees."""
    P = F.load_paths()
    v2, th = pathlib.Path(P["legacy_v2_output"]), pathlib.Path(P["legacy_thesis"])
    xc = _xc()
    if not ((v2 / xc.U4_REL).is_file() and (th / xc.VAULT_REL).is_file() and (v2 / xc.COVERAGE_REL).is_file()):
        pytest.skip("legacy human records not on this machine")
    events = {(e["field"], e["star"]) for e in inp["events"]}
    human, book = xc.load_human(v2, th, events)
    assert len(human) == 89 and book["vault_rows"] == 16 and book["vault_rows_unmatched"] == []
    # the record filed under another OpenAlex id is found by rule (name + field + arrival year)
    assert book["poach_verdict_rows_by_alias"] == [["chemistry", "A5102954096", "A5039408031", "REJECT_local"]]
    assert [h["alias"] for h in human[("chemistry", "A5102954096")]] == ["A5039408031"]
    assert set(book["poach_verdict_rows_by_verdict"]) == {"INCLUDE", "UNCERTAIN", "REJECT_local"}
    assert book["poach_verdict_rows_by_verdict"]["REJECT_local"] == 1
    overrides = list(csv.DictReader(open(OVR, newline="", encoding="utf-8")))
    problems = xc.check_overrides(overrides, human, inp["inst"])
    assert all(v == [] for v in problems.values()), problems
    # the check bites: a wrong country and a wrong institution are both caught
    bad = copy.deepcopy(overrides)
    i = next(k for k, r in enumerate(bad) if r["discipline"] == "econ" and r["event_row"] == "91")
    bad[i]["country_code"] = "CA"
    bad[i]["institution_id"] = "I47987569"          # CIRANO, the OpenAlex rule's answer
    p2 = xc.check_overrides(bad, human, inp["inst"])
    assert len(p2["country_mismatch"]) == 1 and len(p2["institution_not_in_record"]) == 1
    # ... and so are a missing alias row and an alias the record does not support
    bad = [r for r in copy.deepcopy(overrides) if (r["discipline"], r["event_row"]) != ("chemistry", "12")]
    assert xc.check_overrides(bad, human, inp["inst"])["missing_override"] == [("chemistry", "A5102954096")]
    bad = copy.deepcopy(overrides)
    i = next(k for k, r in enumerate(bad) if r["discipline"] == "chemistry" and r["event_row"] == "12")
    bad[i]["source_docs"] = bad[i]["source_docs"].split("#")[0]
    assert len(xc.check_overrides(bad, human, inp["inst"])["alias_mismatch"]) == 1
