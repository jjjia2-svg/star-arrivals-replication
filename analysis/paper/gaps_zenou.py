#!/usr/bin/env python3
"""gaps_zenou.py — the §2.2 worked example: event Zénou→Monash 2016 (econ).

Every number in the sec2_data.tex sentence block "A single event shows how the
pieces fit together" is derived here from data, none hand-typed:

  (values: October canon cal2026-10; the 2026-08-28 values in brackets)
  star_percentile 99.7 [99.7] October star_set percentile field (the July u4 star set, re-keyed)
  roster 60 [59]              relationships channel dept_only+both
  network 66 [118]            relationships channel network+both
  network_only 42 [94]        relationships channel network
  union 102 [153]             all three channels
  dose_below_01 3 [26]        per-relation dose_topic < 0.1 (P1 frame, this event)
  dose_ge_05 52 [63]          per-relation dose_topic >= 0.5
  dose_median 0.51 [0.42]     median per-relation dose_topic, rounded to 2 dp
  p2_followed 100 [151]       persons in the P2 becoming frame for this event
  p2_first_ties_post 6 [11]   of those, persons with y=1 at tau >= 0
  outside_network 36 [35]     roster members NOT in the two-hop network (dept_only)
  same_topic_outside 36 [35]  of those, dose_topic > 0 (the main specification since 2026-08-30;
                              the retired median cut gave 26 on the 08-28 frames)
  pairs 624 [590]             pairs among those 36 in the P3 pair panel (October pairs_unified)
  pairs_possible 630 [595]    C(36, 2)
  pairs_excluded_prewindow 6 [5]  630 - 624 (the builder dropped pairs with a joint paper
                              before 2010, when the observation window opens)

Reads (repo, since cal2026-10 — 2026-09-23, the October caliber is the canon):
                data/frames/relationships_econ.csv (the October relationships, pinned in
                  data/MANIFEST.sha256; was data/raw_verified/relationships_econ.csv, 08-15),
                data/frames/p1_frame_econ.csv, data/frames/p2_becoming_econ.csv (October),
                data/cal2026-10/frames_econ/star_set_econ_cal2026-10.parquet (the October star
                  set: the July u4 star set with A5091326353 re-keyed; pinned) — the percentile,
                output/cal_intermediates/cal2026-10/pairs_unified.csv (the October econ pair table,
                  git-ignored, 237 MB; its sha256 is pinned in the October build report
                  data/cal2026-10/frames_econ/build_report_econ920_2026-10.json
                  `october.pairs_unified`; the repo's p3_afar_econ.parquet is anonymized grp/ev)
Writes:         output/paper/gaps_zenou.json

cal2026-10: the October network channel keeps only network members on a verified roster and in
post at an Australian sample department in the arrival year (design D2/D4), so the event's network
count falls from 118 to 66 and the union from 153 to 102; the roster gains one entry (59 -> 60) from
the 88 added in D3. THESIS below is the October canon (what the thesis prints once the cal2026-10
repin lands); PRE_OCT_THESIS is what the 2026-08-28 thesis printed — both are written to the JSON.

Every value is asserted against the thesis sentence (THESIS dict below); a mismatch
exits non-zero. If a value's source has not survived, its key goes into UNVERIFIED
with a reason instead of being fabricated.

Written 2026-08-24 for this replication package, reusing the verified 2026-08-22
queries (the author's working scripts zenou_counts.py / zenou_afar.py, not shipped).
Run:  python3 analysis/paper/gaps_zenou.py
"""
import json, sys
from pathlib import Path
import duckdb
import csv   # R1 N11 (M mode: the events table)

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from analysis.lib.paths import load_paths
from analysis.lib import canon

P = load_paths()
EV, STAR = "A5017376589:2016", "A5017376589"
CAL10 = P["cal"]   # R1 F7: the cal root from config (October data/cal2026-10)
REL = str(P["frames"] / "relationships_econ.csv")
F1 = str(P["frames"] / "p1_frame_econ.csv")
F2 = str(P["frames"] / "p2_becoming_econ.csv")
PAIRS = P["cal_intermediates"] / "pairs_unified.csv"   # R1 F7 (October output/cal_intermediates/cal2026-10)
STAR_SET = CAL10 / "frames_econ" / "star_set_econ_cal2026-10.parquet"
BUILD_REPORT = CAL10 / "frames_econ" / "build_report_econ920_2026-10.json"
OUT_JSON = P["output"] / "paper" / "gaps_zenou.json"
# R1 M mode (P3 N11, W2-ZENOU; selected by analysis.lib.canon.mode() == 'M', i.e. $SAR_PATHS_CONFIG
# naming an M canon). The same counts are read through the canon roots, but the script asserts only
# IDENTITY, because the worked example, Figures 3 and 4 and the text all rest on Monash 2016 and a moved
# event is reported for review (no automatic re-pointing):
#   (a) <cal>/events_econ_cal2026-10.csv has exactly one row for A5017376589: event A5017376589:2016,
#       school monash, arrival_year 2016;
#   (b) the relationships table has rows for event A5017376589:2016;
#   (c) the star set has exactly one row for A5017376589;
#   (d) for a canon whose events config M wrote (<cal>/counts.json config 'M'), that row's percentile
#       equals the admitting-pass rank in data/cal2026-10r1/inputs/flips_r1.json (not shipped), field pct_own
#       (own field, 0.9986 for Zenou), within 1e-9. A canon written by config B0 (an
#       October copy) carries October's star set, whose percentile is the July u4 rank, so (d) is
#       recorded as not applicable there; (a)-(c) still hold.
# Any failure prints 'IDENTITY LOST <fact>' and exits 1 without writing the JSON. A missing input
# (frames, events, star set, build report, pairs_unified.csv, flips, counts.json) is fatal in M
# ('MISSING INPUT', exit 1), never UNAVAILABLE (exit 3): on AWS every input exists by construction, so
# a missing one is a custody failure. The THESIS-mismatch exit is skipped in M: the JSON carries
# '_october' (THESIS) and '_diff_vs_october' {key: {october, new, changed}} for the sentinel repin and
# tools/r1_number_diff.py, plus '_identity'. October mode keeps every byte and exit code.
# R1 N11: the M mode's identity inputs (read only when MODE == 'M')
MODE = canon.mode()
EVENTS = CAL10 / "events_econ_cal2026-10.csv"
COUNTS_JSON = CAL10 / canon.COUNTS
FLIPS = P["repo_root"] / "data" / "cal2026-10r1" / "inputs" / "flips_r1.json"   # signed R1 input (not shipped)
SCHOOL, YEAR, PCT_TOL = "monash", 2016, 1e-9

# the thesis sentence's numbers (sec2_data.tex, worked-example paragraph), October canon
# (measured 2026-09-23 on the cal2026-10 frames; the thesis prints them after the repin)
THESIS = {
    "star_percentile": 99.7, "roster": 60, "network": 66, "network_only": 42,
    "union": 102, "dose_below_01": 3, "dose_ge_05": 52, "dose_median": 0.51,
    "p2_followed": 100, "p2_first_ties_post": 6, "outside_network": 36,
    "same_topic_outside": 36, "pairs": 624, "pairs_possible": 630,
    "pairs_excluded_prewindow": 6,
}
# what the 2026-08-28 thesis printed (08-28 caliber frames), kept for the record and the ledger diff
PRE_OCT_THESIS = {
    "star_percentile": 99.7, "roster": 59, "network": 118, "network_only": 94,
    "union": 153, "dose_below_01": 26, "dose_ge_05": 63, "dose_median": 0.42,
    "p2_followed": 151, "p2_first_ties_post": 11, "outside_network": 35,
    "same_topic_outside": 35, "pairs": 590, "pairs_possible": 595,
    "pairs_excluded_prewindow": 5,
}


def _sha(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _cal10_pin(rel):
    """The sha256 the cal root's MANIFEST pins for key `rel` (R1 F7: MANIFEST and keys via canon)."""
    for ln in canon.manifest("cal").read_text().splitlines():
        if ln.strip() and ln.split("  ", 1)[1].strip() == rel:
            return ln.split("  ", 1)[0]
    raise AssertionError(f"{rel} not pinned in {canon.key(canon.manifest('cal'))}")

con = duckdb.connect(); con.execute("PRAGMA threads=8")
# MILESTONE REVIEW, replicator-experience MAJOR: one bucket conflated two states. A key whose source
# merely is not MOUNTED ("the legacy tree this package does not ship") was reported as
# "UNVERIFIED (no surviving source)" — the register's phrase for something that exists nowhere — and
# the script exited 0. A replicator could not tell "you are missing an input" from "this number can
# never be checked by anyone", and nothing about the run said it was degraded.
#   UNAVAILABLE  — the source exists, on a tree this package does not ship. Get the tree and it runs.
#   UNVERIFIABLE — no producer or input exists anywhere; see pipeline/NOT_REPRODUCIBLE.md.
N, UNAVAILABLE, UNVERIFIABLE = {"_provenance": {}}, [], []
UNVERIFIED = UNAVAILABLE          # kept as an alias so existing call sites read unchanged
def rec(key, val, src):
    N[key] = val; N["_provenance"][key] = src


# ---- R1 N11: the M canon - identity first, every input required ----
def _m_stop(tag, fact):
    """End an M run: 'IDENTITY LOST <fact>' or 'MISSING INPUT <fact>', exit 1, no JSON written."""
    print(f"{tag} {fact}", file=sys.stderr)
    sys.exit(1)


def _m_identity():
    """The M run's identity checks (a)-(d) of the R1 M mode comment above; returns the _identity record."""
    for p in (Path(REL), Path(F1), Path(F2), EVENTS, STAR_SET, BUILD_REPORT, PAIRS, FLIPS, COUNTS_JSON):
        if not p.is_file():
            _m_stop("MISSING INPUT", f"{canon.key(p)} is absent; an M canon carries every input, "
                                     f"so a missing one is a custody failure")
    try:
        cfg = canon.counts().get("config")
    except canon.CanonError as e:
        _m_stop("MISSING INPUT", f"{canon.key(COUNTS_JSON)}: {e}")
    if cfg not in ("M", "B0"):
        _m_stop("MISSING INPUT", f"{canon.key(COUNTS_JSON)}: config {cfg!r} is neither 'M' nor 'B0', so "
                                 f"the run that wrote this canon's events is unknown")
    try:
        _want = json.load(open(BUILD_REPORT))["october"]["pairs_unified"]["sha256"]
        assert isinstance(_want, str) and len(_want) == 64
    except (KeyError, TypeError, ValueError, AssertionError):
        _m_stop("MISSING INPUT", f"{canon.key(BUILD_REPORT)} has no october.pairs_unified.sha256, the pin "
                                 f"of {canon.key(PAIRS)}")
    for p in (EVENTS, STAR_SET):
        try:
            canon.pinned(p)
        except canon.CanonError as e:
            _m_stop("MISSING INPUT", str(e))

    # (a) the event row: Zenou, Monash, 2016
    with open(EVENTS, newline="", encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        cols = {"event_id", "star_id", "school", "arrival_year"} - set(rd.fieldnames or [])
        if cols:
            _m_stop("MISSING INPUT", f"{canon.key(EVENTS)} lacks the columns {sorted(cols)}")
        mine = [r for r in rd if (r["star_id"] or "").strip() == STAR]
    if not mine:
        _m_stop("IDENTITY LOST", f"event row for {STAR} absent from {canon.key(EVENTS)}")
    if len(mine) != 1:
        _m_stop("IDENTITY LOST", f"event row: {len(mine)} rows for {STAR} in {canon.key(EVENTS)} "
                                 f"({sorted(r['event_id'] for r in mine)}), expected one")
    row = mine[0]
    try:
        year = int(row["arrival_year"].strip())
    except (AttributeError, ValueError):
        year = row["arrival_year"]
    if year != YEAR:
        _m_stop("IDENTITY LOST", f"event row: arrival_year {row['arrival_year']!r} != {YEAR} for {STAR} "
                                 f"(the worked example and Figures 3-4 rest on {YEAR}; the author decides)")
    if (row["school"] or "").strip() != SCHOOL:
        _m_stop("IDENTITY LOST", f"event row: school {row['school']!r} != {SCHOOL!r} for {STAR} "
                                 f"(the worked example rests on {SCHOOL}; the author decides)")
    if row["event_id"].strip() != EV:
        _m_stop("IDENTITY LOST", f"event row: event_id {row['event_id']!r} != {EV!r}")

    # (b) the event in the relationships table
    n_rel = con.execute(f"SELECT count(*) FROM read_csv_auto('{REL}') WHERE event_id='{EV}'").fetchone()[0]
    if not n_rel:
        _m_stop("IDENTITY LOST", f"relationships: no row with event_id {EV} in {canon.key(Path(REL))}")

    # (c) the star-set row
    got = con.execute(f"SELECT percentile FROM read_parquet('{str(STAR_SET)}') "
                      f"WHERE author_id='{STAR}'").fetchall()
    if len(got) != 1:
        _m_stop("IDENTITY LOST", f"star set: {len(got)} rows for {STAR} in {canon.key(STAR_SET)}, expected one")
    pct = got[0][0]

    # (d) the percentile is the signed admitting-pass rank (config M only)
    ident = {"event_id": EV, "star_id": STAR, "school": SCHOOL, "arrival_year": YEAR,
             "relationship_rows": int(n_rel), "star_set_percentile": pct, "canon_config": cfg}
    if cfg == "B0":
        ident["signed_rank_check"] = ("not applicable: canon config B0 (October's star set, whose "
                                      "percentile is the July u4 rank, not the signed admitting pass)")
        return ident
    flips = json.load(open(FLIPS, encoding="utf-8"))
    if flips.get("schema") != "sar.r1.flips.v1":
        _m_stop("MISSING INPUT", f"{canon.key(FLIPS)}: not a sar.r1.flips.v1 file")
    signed = [r for r in flips.get("rows") or [] if r.get("person_id") == STAR]
    if len(signed) != 1 or signed[0].get("verdict") != "KEEP" or signed[0].get("field") != "econ":
        _m_stop("IDENTITY LOST", f"signed verdict: {canon.key(FLIPS)} has {len(signed)} row(s) for {STAR} "
                                 f"({[(r.get('field'), r.get('verdict')) for r in signed]}), expected one econ KEEP")
    try:
        pct_own = float(signed[0]["pct_own"])
    except (KeyError, TypeError, ValueError):
        _m_stop("IDENTITY LOST", f"signed verdict: {canon.key(FLIPS)} row {STAR} has no numeric pct_own")
    if pct is None or abs(float(pct) - pct_own) > PCT_TOL:
        _m_stop("IDENTITY LOST", f"percentile: star set {canon.key(STAR_SET)} gives {pct!r} for {STAR}, "
                                 f"not the signed admitting-pass rank {canon.key(FLIPS)} pct_own "
                                 f"{signed[0]['pct_own']} (tolerance {PCT_TOL})")
    ident.update({"signed_rank_check": "checked", "signed_pct_own": signed[0]["pct_own"]})
    return ident


IDENTITY = _m_identity() if MODE == "M" else None

# ---- roster / network / union: channel counts of the verified relationships ----
ch = dict(con.execute(
    f"SELECT channel, count(*) FROM read_csv_auto('{REL}') WHERE event_id='{EV}' GROUP BY 1").fetchall())
# cross-check: the P1 frame carries the same relations
ch_frame = dict(con.execute(f"""SELECT channel, count(DISTINCT incumbent_person_id)
    FROM read_csv_auto('{F1}') WHERE event_id='{EV}' GROUP BY 1""").fetchall())
assert ch == ch_frame, f"relationships vs P1 frame channel drift for {EV}: {ch} != {ch_frame}"
rec("roster", ch.get("dept_only", 0) + ch.get("both", 0), f"{REL} (dept_only+both)")
rec("network", ch.get("network", 0) + ch.get("both", 0), f"{REL} (network+both)")
rec("network_only", ch.get("network", 0), f"{REL} (network)")
rec("union", sum(ch.values()), REL)
rec("outside_network", ch.get("dept_only", 0), f"{REL} (dept_only)")

# ---- similarity doses, this event: one dose per relation (frozen, constant over years) ----
n_rel, lt01, ge05, med_ev = con.execute(f"""SELECT count(*),
    sum(CASE WHEN dose_topic<0.1 THEN 1 ELSE 0 END),
    sum(CASE WHEN dose_topic>=0.5 THEN 1 ELSE 0 END),
    quantile_cont(dose_topic, 0.5)
    FROM (SELECT DISTINCT incumbent_person_id, dose_topic
          FROM read_csv_auto('{F1}') WHERE event_id='{EV}')""").fetchone()
assert n_rel == N["union"], f"dose relations {n_rel} != union {N['union']}"
rec("dose_below_01", int(lt01), F1)
rec("dose_ge_05", int(ge05), F1)
rec("dose_median", round(med_ev, 2), f"{F1} (median per-relation dose, 2 dp; raw {med_ev:.6f})")

# ---- Panel 2: persons followed + first ties after arrival ----
p2, p2_post = con.execute(f"""SELECT count(DISTINCT pid),
    count(DISTINCT CASE WHEN y=1 AND tau>=0 THEN pid END)
    FROM read_csv_auto('{F2}') WHERE event_id='{EV}'""").fetchone()
rec("p2_followed", int(p2), F2)
rec("p2_first_ties_post", int(p2_post), f"{F2} (y=1, tau>=0)")

# ---- Panel 3: same-topic roster members outside the network, and their pairs ----
# The topic condition as the paper's MAIN specification defines it since 2026-08-30: a positive
# similarity dose, i.e. the incumbent and the star share at least one subfield. Before that date
# this line read `dose_topic >= med_all`, the econ-wide median positive dose; that cut became a
# robustness cell (Section 4.1), and a worked example must follow the main specification, not the
# retired one. The median is still computed because the retired cut is the control that proves the
# rest of this query is unchanged: at `dose_topic >= med_all` it still returns 26 persons, 325
# possible pairs and 320 in the panel, which is exactly what the thesis printed before the change.
med_all = con.execute(f"""SELECT median(dose_topic) FROM (
    SELECT DISTINCT incumbent_person_id, event_id, dose_topic
    FROM read_csv_auto('{F1}') WHERE dose_topic>0)""").fetchone()[0]
n_med = con.execute(f"""SELECT count(DISTINCT incumbent_person_id) FROM read_csv_auto('{F1}')
    WHERE event_id='{EV}' AND channel='dept_only' AND dose_topic >= {med_all}""").fetchone()[0]
far = [r[0] for r in con.execute(f"""SELECT DISTINCT regexp_replace(incumbent_person_id,'^P_','')
    FROM read_csv_auto('{F1}')
    WHERE event_id='{EV}' AND channel='dept_only' AND dose_topic > 0""").fetchall()]
rec("same_topic_outside", len(far),
    f"{F1} (dept_only, dose_topic > 0; the retired median cut {med_all:.4f} gives {n_med})")
rec("pairs_possible", len(far) * (len(far) - 1) // 2, "C(same_topic_outside, 2)")

if PAIRS.exists():
    # the git-ignored October pair table is read only if it is the one the October build wrote
    _want = json.load(open(BUILD_REPORT))["october"]["pairs_unified"]["sha256"]
    assert _sha(BUILD_REPORT) == _cal10_pin(canon.key(BUILD_REPORT))
    assert _sha(PAIRS) == _want, f"{PAIRS}: sha256 != the October build report's pairs_unified pin {_want}"
    con.execute("CREATE TEMP TABLE far AS SELECT unnest(?::VARCHAR[]) AS pid", [far])
    pairs = con.execute(f"""SELECT count(*) FROM (
        SELECT DISTINCT i_id, j_id FROM read_csv_auto('{str(PAIRS)}')
        WHERE event_id='{EV}' AND i_id IN (SELECT pid FROM far) AND j_id IN (SELECT pid FROM far))""").fetchone()[0]
    rec("pairs", int(pairs), f"{PAIRS} (pairs among the {len(far)} same-topic-outside persons)")
    rec("pairs_excluded_prewindow", N["pairs_possible"] - int(pairs),
        "pairs_possible - pairs (the P3 builder drops pairs with a joint paper before 2010)")
else:
    UNAVAILABLE += ["pairs", "pairs_excluded_prewindow"]
    N["_provenance"]["pairs"] = (
        f"UNAVAILABLE (the October econ pair table is a git-ignored intermediate): {PAIRS}. It IS "
        f"rebuildable — the cal2026-10 econ frame build writes it (sha256 pinned in "
        f"{canon.key(BUILD_REPORT)} `october.pairs_unified`).")

# ---- star percentile: the u4 star set records the within-cell citation percentile ----
if STAR_SET.exists():
    assert _sha(STAR_SET) == _cal10_pin(canon.key(STAR_SET))
    row = con.execute(f"""SELECT percentile, stock, subfield, age_bin, cell_n
        FROM read_parquet('{str(STAR_SET)}') WHERE author_id='{STAR}'""").fetchone()
    assert row is not None, f"{STAR} not in {STAR_SET}"
    rec("star_percentile", round(100 * row[0], 1),
        f"{STAR_SET} percentile={row[0]} (citation stock {row[1]}, subfield {row[2]}, "
        f"age bin {row[3]}, cell n={row[4]})")
else:
    UNAVAILABLE.append("star_percentile")
    N["_provenance"]["star_percentile"] = (
        f"UNAVAILABLE: {STAR_SET} is missing (the October star set, pinned in "
        f"{canon.key(canon.manifest('cal'))}).")

# ---- assert against the thesis sentence; never tune a mismatch away ----
mismatches = [(k, N[k], want) for k, want in THESIS.items()
              if k not in UNAVAILABLE and k not in UNVERIFIABLE and N[k] != want]
N["_event"] = EV
N["_pre_october_thesis"] = PRE_OCT_THESIS
if MODE == "M":
    # R1 N11: an M run reports every count next to its October value instead of failing on it; the
    # sentinel repin and tools/r1_number_diff.py read the new values (underscore keys are metadata)
    N["_october"] = dict(THESIS)
    N["_diff_vs_october"] = {k: {"october": want, "new": N[k], "changed": N[k] != want}
                             for k, want in THESIS.items()}
    N["_identity"] = IDENTITY
    mismatches = []
N["UNAVAILABLE"] = UNAVAILABLE
N["UNVERIFIABLE"] = UNVERIFIABLE
N["UNVERIFIED"] = UNAVAILABLE + UNVERIFIABLE      # the old key, kept as the union, for consumers
OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
json.dump(N, open(OUT_JSON, "w"), ensure_ascii=False, indent=1)
for k in THESIS:
    state = ("UNAVAILABLE" if k in UNAVAILABLE else
             "UNVERIFIABLE" if k in UNVERIFIABLE else N.get(k, "?"))
    print(f"{k:26s} = {state}")
print("wrote", OUT_JSON)
if MODE == "M":
    print(f"M canon: identity held ({EV}, {SCHOOL}, star set percentile {IDENTITY['star_set_percentile']}, "
          f"signed rank {IDENTITY['signed_rank_check'].split(':')[0]})")
    for k, d in N["_diff_vs_october"].items():
        if d["changed"]:
            print(f"CHANGED {k}: october {d['october']!r} -> new {d['new']!r}")
if mismatches:
    for k, got, want in mismatches:
        print(f"MISMATCH {k}: derived {got!r} != thesis {want!r}", file=sys.stderr)
    sys.exit(1)
if UNVERIFIABLE:
    print("UNVERIFIABLE (no producer or input exists anywhere; see "
          "pipeline/NOT_REPRODUCIBLE.md):", UNVERIFIABLE, file=sys.stderr)
if UNAVAILABLE:
    print("", file=sys.stderr)
    print("*** DEGRADED RUN " + "*" * 62, file=sys.stderr)
    print(f"*** {len(UNAVAILABLE)} of {len(THESIS)} thesis numbers were NOT checked, because their "
          f"sources are on a tree", file=sys.stderr)
    print("*** this package does not ship. They are UNAVAILABLE, not unverifiable — the sources "
          "exist.", file=sys.stderr)
    for k in UNAVAILABLE:
        print(f"***   {k}: {N['_provenance'].get(k, '')}", file=sys.stderr)
    print("*" * 78, file=sys.stderr)
    sys.exit(3)
