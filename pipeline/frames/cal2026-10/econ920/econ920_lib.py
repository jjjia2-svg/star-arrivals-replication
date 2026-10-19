#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""econ920/econ920_lib.py — the October caliber's ECONOMICS frames: staging, the D1-D5 row filters,
the union-rung clone runner and the row-level proofs. Repo-authored library, 2026-09-22; imported by
`run_econ920.py`, never run as a script. Edits no ported file, no legacy file, no frozen artifact.

Rules: D1-D5 of 2026-09-22. The economics NETWORK channel is NOT
regenerated: the frozen fnfix network frame (`econ_fnfix_2026-08-15/data/network_frame_fnfix.csv`,
75,284 rows = the July 79-event rows byte-preserved + the 35 prodlib new-event rows the 01_merge
stage lowercased) is FILTERED, one event is regenerated, and the UNION rung (`00_build_frame_econ920.py`,
the roster channel + the dept/network/both assignment) is RE-RUN through the clone in this directory,
followed by the ported chain exactly as `run_cal_frames.py` phase E runs it.

THE FILTERS (all byte-preserving on kept lines; every dropped (person, event) is attributed)
  (c) event set        keep only rows whose event_id (after the id correction) is in the event table.
                       A NEW event (one of the 38 of `new_events_econ.csv`) that is removed must
                       leave BEFORE the ledger stage — `01_merge_inputs.py` asserts that every
                       prodlib row's event is a new event and that every new event is in the
                       prodlib frame — so its rows are cut from the staged prodlib frame and its
                       row from the staged `new_events_econ.csv` (the 08-28 surgery, generalised
                       from A5044432173 to a set: `frames_stage.drop_event_lines`); an OLD (79) event that
                       is removed leaves at the filter stage and its ledger row is dropped.
  (d) regeneration     event A5090515599:2009 (A5091326353, wrong OpenAlex id) — every row of the old
                       id's event is dropped and the rows prodlib builds for the same event on the
                       corrected id A5091326353 (piece A's econ config/stage, the October roster
                       pool, the 126-work supplement) are spliced in under the event id
                       A5091326353:2009, normalised the way 01_merge_inputs normalises prodlib
                       rows (bool cells 4/5/8 lowercased, LF line ends). The correction table is
                       `data/cal2026-10/star_id_corrections_2026-10.csv` (old_id,new_id,arrival):
                       nothing about the correction is typed here.
  (a) verified roster  keep only rows whose incumbent person is on the roster, in EITHER id form
                       a person takes in this package (`build_verified_pool.py`, 2026-09-13):
                       `P_<author_id>` or the U2 person_id the 11-school person map assigns to
                       that author_id. Controlled: on the 920 roster this rule, applied to the
                       frozen data/frames p1/p2, reproduces exactly the 162 persons of
                       `data/robustness_2026-09-13_verified_pool/excluded_persons.csv`.
  (b) in post          keep only rows whose person has a roster spell covering the event's
                       arrival year — `inpost_filter.py` (piece A, D2), spells from the roster in
                       both id forms + the U2 person_id form, arrival read from the frame.
  Order (2026-09-23, measured): (c) and (d) at the EVENT level go in BEFORE the union clone —
  they change the clone's `dept_rel` / star-arrival sets and are not output-equivalent; (a) and
  (b) at the PERSON level are applied to the clone's OUTPUT (`postfilter_union`): they only ever
  remove network-only relations and are equivalent by construction (the one caveat, an event left
  with no relation at all, is measured). The reason is the clone's own G-DOSE gate — a
  fixed-seed 200-draw over the input's old relations with a hard 0.01 ceiling on a residual
  population whose tail exceeds it (34 of 4,470 relations > 0.01, exact share 0.893 < 0.90;
  `run_union(gdose_all=True)`): every person-level input filter changes the draw and the gate
  outcome by sample composition alone. Regenerated rows go through (a) and (b) like every other
  row (measured, not assumed to pass).

THE UNION RUNG RE-RUN (not surgered). The clone `00_build_frame_econ920_cal.py` (see DIFF.md) takes
its inputs from a JSON config: OLD_FRAME = the FILTERED network frame, ROSTER = the roster the
caliber names, LEDGER = the (corrected) event ledger, STAR_SET, SUP11/SUP_FNFIX, PATCH_A/B,
NEW_EVENTS; the SSD tables resolve through pipeline.lib.paths (the mirror). It is hard-linked into
the run tree, sha-asserted against the tracked clone, and run IN PROCESS inside a `staged_run` mark
with `identity.dose` pre-imported from this repository's ported units (origin-asserted). Its three
outputs land at the exact shadow paths the ported `04_rebuild_y.py` / `10_panels23_econ920.py` /
`50_leftbehind_build.py` resolve through `$SAR_LEGACY_THESIS`.

TWO new-events tables in an October run (one assumption, written down):
  * `new_events_econ.csv` (EVENT AGE: the 37 fn-fix events) is what the ledger stage appends to
    the 79 ledger and what the old79/new37 splitter partitions on;
  * `prodlib_events_econ.csv` (ROW PROVENANCE: the 37 + every regenerated event) is what the
    union clone's `_NEW_EV` and `04_rebuild_y.py`'s `_NEW_EV` read. Both scripts use that set for
    the prodlib-row rules of the 2026-08-15 chain — the union rung overrides a prodlib row's
    dose_topic with its own recomputation ("the same ruler for the network rows and department rows of the same event") and 04 writes a prodlib
    row's y from its own aggregate instead of anchoring it to U5's frozen pub_count ("prodlib rows'
    y/pub_count do not share a source with the U5 frozen caliber"). Those rules are about how a row was BUILT, not about when
    the event was found, so the regenerated A5091326353 rows get them; the ledger and the split keep this star in
    the old-79 group where the star's event has always been. The shadow file 04 reads is swapped to the
    provenance table for the p1-econ stage only, and restored before the split; both swaps are in
    the staging manifest.

STAR_SET for the October run = the frozen 08-15 `u4_aug/star_set/star_set.parquet` with the
corrected star's row RE-KEYED to the new id (author_id only; arrival and academic_age are the
frozen row's — the clone reads `star_first = arrival - 1 - academic_age` from it). The academic
age is cross-checked against the October re-rank (`restake_econ11_aug_2026-10.csv`, column aage)
and a mismatch STOPs. The SSD star set `04_rebuild_y.py` reads (the ex-star flags) is untouched.

SUPPLEMENTS for the October run: SUP11 frozen; SUP_FNFIX = the frozen fnfix supplement ⧺ the
star-id-correction supplement (126 rows, all already in the June snapshot — measured by piece A),
staged at the one shadow path the ledger stage, the union clone and the panels builder all read.
For the corrected star the union clone's dose side is unaffected either way: the star has snapshot edges,
and the clone uses a supplement only for persons WITHOUT snapshot edges (`sup_only`).

WHAT THE FROZEN 04 CHAIN CANNOT DO (measured in the October run 2026-09-23, reported, not
repaired): a person whose works are neither in the frozen FWCI unit table
(`econ_units_2026-08-09.parquet`, 1,026 persons) nor in the 2026-08-13 API patch
(`works_by_author.jsonl`, 112 persons) has no full-snapshot aggregate in `04_rebuild_y.py`. For a
prodlib-event row the script writes y = NA and goes on; for an OLD-event row it records
`agg_missing` in its C-PC structural anchor, sets PASS=False and EXITS 2 — the earlier reading
"writes NA and continues" was wrong for old-event rows. Measured: 2 of the 88 October roster
additions (P_A5046503193, P_A5065862323) hold dept_only rows in 2 old events with publications
(30 rows / 27 person-years; 04 counts 60 = 30 x its two variants), so the p1-econ stage is
BLOCKED; 28 prodlib-event rows of 3 persons are written NA. The unit table's producer is a
separate builder (register entry 6), not this chain; the pre-y frame is frozen so 04 re-runs in
seconds once it covers these persons. `agg_missing_persons()` quantifies it in the build report.

CONTROLS (run_econ920.py --controls, mandatory before the October run)
  C1a  the clone on the FROZEN 2026-08-15 inputs (117 events, 920 roster, fnfix ledger and star
       set, frozen supplements) must reproduce the frozen pre-y frame BYTE FOR BYTE
       (`dc9817f2…`), plus relationships.csv (`4f3c7278…`).
  C1b  the same chain on the 08-28 event set (A5044432173's event removed by filter (c)) must reproduce
       the 08-28 caliber's SURGERED pre-y frame (`8acd4a03…`, staging manifest) — i.e. the
       re-run equals the surgery, register item R-T3-1 measured rather than assumed.
  C2   the whole chain on the 08-28 inputs must reproduce data/frames/{p1_frame_econ.csv,
       p1_frame_econ_old79.csv, p1_frame_econ_new37.csv, p2_becoming_econ.csv} byte for byte and
       p3_slim_econ / p3_slim_ev_econ / p3_afar_econ content-EQUAL (the M3 D1 criterion, the one
       declared grp BIGINT axis), and the R cells P1_econ_fnfix / P1_econ_fnfix_old79 /
       P1_econ_fnfix_new37 / P2_econ_fnfix must be compare_json-EQUAL to analysis/expected.
  C3   the 08-28 inputs + filter (a) on the 920 roster (applied to C1b's union output) must
       reproduce the verified-pool cells `P1ver_econ` / `P2ver_econ`
       (data/robustness_2026-09-13_verified_pool/estimates) EQUAL — that is what those cells are —
       and, measured on the way, the filtered frames byte for byte.
  Results 2026-09-23 (data/cal2026-10/controls_report_econ920_2026-09-23.json): C1a CLEAR with the
  original proven NON-deterministic (two runs differ by 1-2 ULP in fwci_frac on 3-4 rows, all in
  the four y columns 04 overwrites; relationships byte-equal); C1b CLEAR (same characterisation
  against the surgery; relationships byte-equal; ledger byte-equal); C2 CLEAR (four frames
  byte-equal, two slims content-equal, four cells EQUAL); C3 CLEAR (162 = 162, both verified
  frames byte-equal, both cells EQUAL).
"""
from __future__ import annotations

import collections
import csv
import hashlib
import importlib
import inspect
import io
import json
import os
import pathlib
import runpy
import shutil
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
LAYER = HERE.parent                                   # pipeline/frames/cal2026-10
REPO = HERE.parents[3]
for p in (str(REPO), str(LAYER), str(REPO / "pipeline" / "stars" / "caliber_2026-08-28")):
    if p not in sys.path:
        sys.path.insert(0, p)

import frames_stage as fs08                                              # noqa: E402
import inpost_filter as ipf                                              # noqa: E402
import stage as pa_stage                                                 # noqa: E402  (piece A)
from analysis.lib.compare_json import compare as compare_json            # noqa: E402
from analysis.lib.paths import load_paths                                # noqa: E402
from pipeline.lib.paths import OUT_ROOT_ENV, PathUnresolved, staged_run  # noqa: E402
from tools.content_equal import content_equal                            # noqa: E402

PY = sys.executable
ECON = "econ_fnfix_2026-08-15"
GOLD = "multidisc_gold_2026-08-10"
CAL10 = REPO / "data" / "cal2026-10"
CAL08 = REPO / "data" / "cal2026-08-28"
RAW = REPO / "data" / "raw_verified"
#: the 2026-08-28 canon the controls reproduce. Until 2026-09-23 02:51 it sat in data/frames and
#: analysis/expected; commit 73777aa PROMOTED the October frames/golds there and moved the 08-28
#: set to data/cal2026-08-28/{frames,estimates} (+ its MANIFEST.sha256, byte-equal to tag
#: cal-2026-08-28) — the controls follow it (review fix 2026-09-23).
FRAMES = CAL08 / "frames"
FRAMES_MANIFEST = CAL08 / "MANIFEST.sha256"
FRAMES_MANIFEST_PREFIX = "data/cal2026-08-28/frames"
VERPOOL = REPO / "data" / "robustness_2026-09-13_verified_pool"
EXPECTED = CAL08 / "estimates"          # the 08-28 golds (analysis/expected holds October's since 73777aa)
EST = REPO / "analysis" / "estimation"
CLONE = HERE / "00_build_frame_econ920_cal.py"
STAR_ID_CORRECTIONS = CAL10 / "star_id_corrections_2026-10.csv"
STAR_ID_SUPPLEMENT = CAL10 / "edges_supplement_star_id_corrections_2026-10.jsonl"
ROSTER_920 = RAW / "roster_econ_verified.parquet"
ROSTER_1008 = CAL10 / "roster_econ_verified_2026-10.parquet"
EVENTS_0828 = RAW / "events_econ_cal2026-08-28.csv"
EVENTS_OCT = CAL10 / "events_econ_cal2026-10.csv"
#: = B0's stage.restake_econ_aug. Since R1 F3 the academic_age cross-check reads the run config's
#: table (restake_aug_rows), never this constant by existence; run_econ920's precondition list
#: still names it as an October input.
RESTAKE_OCT = CAL10 / "restake_econ11_aug_2026-10.csv"

#: the frozen 2026-08-15 artifacts this layer reads from the read-only legacy tree, sha256 as
#: measured 2026-09-22 (they sit in no repo manifest; `network_frame` is also the value piece B's
#: control report recorded). Anything else at these paths is not the audited input.
LEGACY_PINS = {
    f"{ECON}/data/network_frame_fnfix.csv":
        "58b3cdab5cfecdf754e9a5134cb6f1134392d6986e5f59b049e81869f700fd06",
    f"{ECON}/data/analysis_frame_dept_p01_econ920_2026-08-13.csv":
        "dc9817f2758bfa1e880160960bde97148db01e419e3217ec67cb2d164b36fb60",
    f"{ECON}/data/relationships.csv":
        "4f3c7278b8a231397d841a8c63464f4446cdef6878d144fd14f17a7168748373",
    f"{ECON}/data/event_ledger_fnfix.csv":
        "c7f7b870bcdc32264ce31bc80238082ae6cc16459c0ed57bcaa629e0cff34882",
    f"{ECON}/data/new_events_econ.csv":
        "a17a61bec22ebac9a14dfd94c1f2b72b30b9cf681f75d7d26187d2767725ff25",
    f"{ECON}/u4_aug/star_set/star_set.parquet":
        "b8a73d89e1416353b6963e2c802a3c47353582c458b21e0895d0f6ea5f3a61fc",
    f"{ECON}/code/00_build_frame_econ920.py":
        "233485392b8e9ca7c17e3f5b72c7a66c347ef3b60aefdf81c50699f740dda4c3",
    # the two legacy files the October run DERIVES from (concatenations written into the shadow):
    # pinned since the 2026-09-23 review found both overwritten through shadow hard links
    # (2026-08-28 staging manifest + the 2026-09-22 control reports record these values; the
    # supplement is byte-equal to data/raw_verified/edges_supplement_econ_fnfix.jsonl)
    f"{ECON}/data/edges_supplement_fnfix.jsonl":
        "8d03564c714c0eac02222c5f0ecc0fefb3641a4b034b142185c780d8dc57040a",
    "econ_final_2026-08-13/patch/works_by_author.jsonl":
        "9ab038093f6be2874e7ea82307b91be520d254da70d804a8878627272fef17d6",
}
#: the network-frame column order (01_merge_inputs asserts the prodlib header equals it)
FRAME_COLS = ["incumbent_person_id", "year", "star_person_id", "event_id", "treated", "post",
              "dose_coupling_baseline", "dose_topic", "dose_low_confidence", "age_gap", "fwci_frac",
              "pub_count", "fwci_frac_ex_star", "pub_count_ex_star", "fwci_mean", "fwci_mean_ex_star"]
BOOL_COLS = (4, 5, 8)          # 01_merge_inputs.py: treated / post / dose_low_confidence lowercased
#: the frozen chem/math frames the `afar` stage reads for the two other fields (data/frames is the
#: 2026-08-28 caliber set; pairs_none lives only in the cal frames dir) — linked, sha-checked
CHEMMATH_AFAR_INPUTS = {
    f"{GOLD}/data/fnfix/analysis_frame_{f}_new_gold_2026-08-10.csv": FRAMES / f"p1_frame_{f}.csv"
    for f in ("chemistry", "math_stats")
} | {
    f"{GOLD}/data/fnfix/panels23_{f}_gold/becoming_none.csv": FRAMES / f"p2_becoming_{f}.csv"
    for f in ("chemistry", "math_stats")
} | {
    f"{GOLD}/data/fnfix/panels23_{f}_gold/pairs_none.parquet": CAL08 / "frames" / f"pairs_none_{f}.parquet"
    for f in ("chemistry", "math_stats")
}

sha = fs08.sha


def log(msg: str) -> None:
    print(f"[econ920] {msg}", flush=True)


def real_v2() -> pathlib.Path:
    return fs08.real_v2()


def manifest_sha(manifest: pathlib.Path, rel: str) -> str:
    """One entry of a `sha256  path` manifest (data/MANIFEST.sha256 shape)."""
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        s, p = line.split("  ", 1)
        if p.strip() == rel:
            return s
    raise KeyError(f"{rel} not in {manifest}")


def staging_sha_0828(rel: str) -> str:
    m = json.loads((CAL08 / "frames" / "staging_manifest_2026-08-28.json").read_text("utf-8"))
    for e in m["entries"]:
        if e["rel"] == rel:
            return e["sha256"]
    raise KeyError(rel)


def assert_pins(v2: pathlib.Path) -> dict:
    out = {}
    for rel, want in LEGACY_PINS.items():
        got = sha(v2 / rel)
        assert got == want, f"legacy pin broken: {rel} {got} != {want}"
        out[rel] = got
    return out


# ---------------------------------------------------------------------------------------------
# tables: event set, id correction, new-events tables, star set
# ---------------------------------------------------------------------------------------------

def read_rows(p: pathlib.Path) -> list[dict]:
    return list(csv.DictReader(io.StringIO(p.read_bytes().decode("utf-8"))))


def id_correction(table: pathlib.Path = STAR_ID_CORRECTIONS) -> dict:
    """{'events': {old_event_id: new_event_id}, 'stars': {old_id: new_id}} for the econ rows."""
    ev, st = {}, {}
    for r in read_rows(table):
        if r["field"] != "econ":
            continue
        ev[f"{r['old_id']}:{int(r['arrival'])}"] = f"{r['new_id']}:{int(r['arrival'])}"
        st[r["old_id"]] = r["new_id"]
    return {"events": ev, "stars": st, "table": str(table.relative_to(REPO)), "sha256": sha(table)}


def event_set(table: pathlib.Path, corr: dict | None) -> set[str]:
    """The event ids of an econ event table (ledger shape, column event_id), id-corrected."""
    ids = {r["event_id"] for r in read_rows(table)}
    if corr:
        ids = {corr["events"].get(e, e) for e in ids}
    return ids


def correct_id_lines(src: pathlib.Path, corr: dict, id_cols: tuple[int, int] = (0, 1)) -> tuple[bytes, dict]:
    """A CSV whose first two columns are (event_id, star_id): the corrected rows get the new ids
    in those two cells, every other line byte-preserved. Exactly one line per correction."""
    raw = src.read_bytes()
    lines = raw.split(b"\n")
    hits = collections.Counter()
    out = []
    for i, ln in enumerate(lines):
        if i == 0 or not ln:
            out.append(ln)
            continue
        text = ln.decode("utf-8")
        cells = next(csv.reader([text.rstrip("\r")]))
        e = cells[id_cols[0]]
        if e in corr["events"]:
            old_star = e.split(":")[0]
            new_e = corr["events"][e]
            new_star = corr["stars"][old_star]
            prefix = f"{e},{old_star},"
            assert text.startswith(prefix), (src.name, text[:80])
            text = f"{new_e},{new_star}," + text[len(prefix):]
            hits[e] += 1
        out.append(text.encode("utf-8"))
    for e in corr["events"]:
        assert hits[e] <= 1, (e, hits[e])
    return b"\n".join(out), {"corrected_lines": dict(hits)}


def new_events_minus(v2: pathlib.Path, removed_stars: set[str]) -> tuple[bytes, list[str]]:
    """frozen new_events_econ.csv minus the rows of `removed_stars` (author_id), others byte-preserved
    — `frames_stage.surgery_new_events_econ` generalised from A5044432173 to a set."""
    src = v2 / f"{ECON}/data/new_events_econ.csv"
    lines = src.read_bytes().split(b"\n")
    hdr = next(csv.reader([lines[0].decode("utf-8").rstrip("\r")]))
    aid = hdr.index("author_id")
    out, removed = [], []
    for i, ln in enumerate(lines):
        if i and ln:
            cells = next(csv.reader([ln.decode("utf-8").rstrip("\r")]))
            if cells[aid] in removed_stars:
                removed.append(cells[aid])
                continue
        out.append(ln)
    assert set(removed) == removed_stars, (removed, removed_stars)
    return b"\n".join(out), removed


def new_events_rows(v2: pathlib.Path) -> list[dict]:
    return read_rows(v2 / f"{ECON}/data/new_events_econ.csv")


def provenance_table(age_table_bytes: bytes, extra_events: dict[str, dict]) -> bytes:
    """the age table + one row per regenerated event in the same columns (author_id,name,school,
    arrival,dept_id,evidence_url,verdict_source) — the union clone and 04 only read author_id and
    arrival from it (`_NEW_EV = {author_id:arrival}`)."""
    text = age_table_bytes.decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    cols = list(rows[0].keys())
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    for ev, r in sorted(extra_events.items()):
        star, arr = ev.split(":")
        w.writerow({c: "" for c in cols} | {"author_id": star, "arrival": arr,
                                           "name": r.get("name", ""), "school": r.get("school", ""),
                                           "verdict_source": r.get("source", "")})
    return buf.getvalue().encode("utf-8")


def restake_aug_rows(stage_cfg: dict | None = None) -> dict[str, dict]:
    """author_id -> row of the economics re-rank table the academic_age cross-check reads: the run
    config's stage.restake_econ_aug (B0 = RESTAKE_OCT). stage_cfg None = stage.stage_config() (an
    unset $SAR_R1_CONFIG is a STOP). Before R1 an absent table silently returned {} and skipped
    the check; now an unnamed or absent table is a STOP."""
    cfg = pa_stage.stage_config() if stage_cfg is None else stage_cfg
    return {r["author_id"]: r for r in read_rows(pathlib.Path(pa_stage.stage_value(cfg, "restake_econ_aug")))}


def roster_added_persons(stage_cfg: dict | None = None) -> set[str]:
    """{'P_'+author_id} of the October roster additions (the run config's stage.roster_added; B0 =
    data/cal2026-10/roster_added_2026-10.csv); unnamed or absent is a STOP, as above."""
    cfg = pa_stage.stage_config() if stage_cfg is None else stage_cfg
    return {"P_" + r["author_id"] for r in read_rows(pathlib.Path(pa_stage.stage_value(cfg, "roster_added")))}


def rekeyed_star_set(v2: pathlib.Path, corr: dict, out: pathlib.Path, *,
                     stage_cfg: dict | None = None) -> dict:
    """frozen u4_aug star_set with the corrected stars' author_id re-keyed; academic_age cross-checked
    against the October re-rank table (aage; restake_aug_rows)."""
    import pyarrow as pa                                                # noqa: PLC0415
    import pyarrow.parquet as pq                                        # noqa: PLC0415
    src = v2 / f"{ECON}/u4_aug/star_set/star_set.parquet"
    t = pq.read_table(src)
    rows = t.to_pylist()
    restake = restake_aug_rows(stage_cfg)
    rec = {"source": str(src), "source_sha256": sha(src), "rows": len(rows), "rekeyed": []}
    for old, new in corr["stars"].items():
        hit = [r for r in rows if r["author_id"] == old]
        assert len(hit) == 1, (old, len(hit))
        assert not any(r["author_id"] == new for r in rows), f"{new} already in the star set"
        r = hit[0]
        chk = {"old": old, "new": new, "arrival": r["arrival"], "academic_age": r["academic_age"]}
        if new in restake:
            aage = int(restake[new]["aage"])
            assert aage == r["academic_age"], (
                f"academic_age of {new}: frozen star_set {r['academic_age']} != October re-rank {aage}")
            chk["restake_aage"] = aage
            chk["restake_arrival_true"] = restake[new]["arrival_true"]
        r["author_id"] = new
        rec["rekeyed"].append(chk)
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=t.schema), out)
    rec["out_sha256"] = sha(out)
    return rec


# ---------------------------------------------------------------------------------------------
# filter (a): the verified pool, build_verified_pool.py's identity rule
# ---------------------------------------------------------------------------------------------

def person_map_path() -> pathlib.Path:
    return pa_stage.derived_root() / "u2_person_map_11school_2026-07-16" / "person_map" / "data.parquet"


def verified_forms(roster: pathlib.Path, person_map: pathlib.Path) -> tuple[set[str], dict]:
    """{'P_'+author_id} ∪ {U2 person_id of author_id} over the roster (build_verified_pool: ver_p)."""
    import duckdb                                                        # noqa: PLC0415
    con = duckdb.connect()
    forms = {t[0] for t in con.execute(
        f"select distinct 'P_'||v.author_id from read_parquet('{roster.as_posix()}') v "
        f"union select distinct pm.person_id from read_parquet('{roster.as_posix()}') v "
        f"join read_parquet('{person_map.as_posix()}') pm using(author_id)").fetchall()}
    n_auth = con.execute(f"select count(distinct author_id) from read_parquet('{roster.as_posix()}')").fetchone()[0]
    con.close()
    return forms, {"roster": str(roster), "roster_sha256": sha(roster), "roster_authors": n_auth,
                   "person_map": str(person_map), "person_map_sha256": sha(person_map),
                   "id_forms": len(forms)}


def pid_form(pid: str) -> str:
    return pid if pid.startswith("P_") else f"P_{pid}"


def excluded_persons_of_frozen_frames(forms: set[str]) -> set[str]:
    """The control for (a): the persons of data/frames p1/p2 (both id shapes) not in `forms`."""
    ex = set()
    with open(FRAMES / "p1_frame_econ.csv", "rb") as f:
        hdr = f.readline().decode().rstrip("\r\n").split(",")
        k = hdr.index("incumbent_person_id")
        for line in f:
            pid = line.decode().split(",")[k]
            if pid_form(pid) not in forms:
                ex.add(pid_form(pid))
    with open(FRAMES / "p2_becoming_econ.csv", "rb") as f:
        hdr = f.readline().decode().rstrip("\r\n").split(",")
        k = hdr.index("pid")
        for line in f:
            pid = line.decode().split(",")[k]
            if pid_form(pid) not in forms:
                ex.add(pid_form(pid))
    return ex


# ---------------------------------------------------------------------------------------------
# the network-frame filters (byte-preserving)
# ---------------------------------------------------------------------------------------------

def read_frame_lines(p: pathlib.Path) -> tuple[bytes, list[bytes], bool]:
    return ipf.read_lines(p)


def cells_of(line: bytes) -> list[str]:
    return ipf.cells(line)


def normalise_prodlib_lines(prodlib_frame: pathlib.Path, event_id: str) -> tuple[list[bytes], dict]:
    """The rows of `event_id` from a prodlib output frame, in the shape 01_merge_inputs.py gives
    prodlib rows in network_frame_fnfix.csv (bool cells lowercased, `,`-joined, LF)."""
    header, lines, _ = read_frame_lines(prodlib_frame)
    assert cells_of(header) == FRAME_COLS, cells_of(header)
    out, persons = [], set()
    for ln in lines:
        c = cells_of(ln)
        if c[3] != event_id:
            continue
        for i in BOOL_COLS:
            assert c[i] in ("True", "False", "true", "false", ""), (i, c[i])
            c[i] = c[i].lower()
        out.append(",".join(c).encode("utf-8"))
        persons.add(c[0])
    return out, {"event_id": event_id, "rows": len(out), "persons": len(persons),
                 "source": str(prodlib_frame), "source_sha256": sha(prodlib_frame)}


def filter_events(frame: pathlib.Path, keep_events: set[str], regenerate: dict[str, str],
                  spliced: dict[str, list[bytes]], out: pathlib.Path) -> dict:
    """(c) + (d): drop rows of events not in `keep_events`; drop rows of every old event id in
    `regenerate` (old -> new) and append the spliced lines of the new id; kept lines byte-identical
    and in order; the spliced block follows them (the 01_merge order: July rows, then prodlib rows).
    `keep_events` holds the NEW ids for regenerated events."""
    header, lines, trailing = read_frame_lines(frame)
    assert cells_of(header) == FRAME_COLS
    kept, dropped_ev, dropped_regen = [], collections.Counter(), collections.Counter()
    rel_seen = collections.defaultdict(set)
    for ln in lines:
        c = cells_of(ln)
        e = c[3]
        if e in regenerate:
            dropped_regen[e] += 1
            rel_seen[("regen", e)].add(c[0])
            continue
        if e not in keep_events:
            dropped_ev[e] += 1
            rel_seen[("event", e)].add(c[0])
            continue
        kept.append(ln)
    added = []
    for new_e, block in sorted(spliced.items()):
        assert new_e in keep_events, new_e
        added += block
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"\n".join([header] + kept + added) + (b"\n" if trailing else b""))
    return {"input": {"frame": str(frame), "sha256": sha(frame), "rows": len(lines)},
            "rows_kept_frozen": len(kept),
            "rows_dropped_event_not_in_set": {e: {"rows": n, "persons": len(rel_seen[("event", e)])}
                                              for e, n in sorted(dropped_ev.items())},
            "rows_dropped_regenerated_old_id": {e: {"rows": n, "persons": len(rel_seen[("regen", e)]),
                                                    "new_id": regenerate[e]}
                                                for e, n in sorted(dropped_regen.items())},
            "rows_spliced": {e: len(b) for e, b in sorted(spliced.items())},
            "output": {"frame": str(out), "sha256": sha(out), "rows": len(kept) + len(added)}}


def filter_verified(frame: pathlib.Path, forms: set[str], out: pathlib.Path) -> dict:
    """(a): keep rows whose incumbent (either id form) is in `forms`."""
    header, lines, trailing = read_frame_lines(frame)
    kept, drop_rows, drop_rel = [], 0, set()
    for ln in lines:
        c = cells_of(ln)
        if pid_form(c[0]) in forms:
            kept.append(ln)
        else:
            drop_rows += 1
            drop_rel.add((c[0], c[3]))
    out.write_bytes(b"\n".join([header] + kept) + (b"\n" if trailing else b""))
    persons = {p for p, _ in drop_rel}
    return {"input": {"frame": str(frame), "sha256": sha(frame), "rows": len(lines)},
            "rows_dropped": drop_rows, "relations_dropped": len(drop_rel), "persons_dropped": len(persons),
            "persons_dropped_ids": sorted(persons),
            "output": {"frame": str(out), "sha256": sha(out), "rows": len(kept)}}


def filter_inpost(frame: pathlib.Path, roster: pathlib.Path, person_map: pathlib.Path,
                  out: pathlib.Path, report: pathlib.Path) -> dict:
    """(b): piece A's inpost_filter on the roster's spells (both id forms + U2 person_id)."""
    spells, sources = ipf.spells_from_roster(roster, person_map, identity=False)
    rep = ipf.run(frame, spells, sources, out, report)
    return rep


def is_removed_factory(removed_events: set[str], removed_persons_by_event: dict[str, set[str]]):
    def is_removed(cells: list[str]) -> bool:
        e = cells[3]
        return e in removed_events or cells[0] in removed_persons_by_event.get(e, ())
    return is_removed


# ---------------------------------------------------------------------------------------------
# the shadow
# ---------------------------------------------------------------------------------------------

def build_econ_shadow(root: pathlib.Path, v2: pathlib.Path, *, removed_new_stars: set[str],
                      supplement_extra: pathlib.Path | None,
                      patch_extra: pathlib.Path | None = None) -> tuple[fs08.Shadow, dict]:
    """The legacy-tree shadow the ledger stage and every later ported stage resolve through
    $SAR_LEGACY_THESIS: frozen links (frames_stage.FROZEN_LINKS + the chem/math afar inputs), the
    staged new-events table and prodlib frame/report minus the removed NEW events, the supplement."""
    sh = fs08.Shadow(root / "v2_output")
    for rel in fs08.FROZEN_LINKS:
        sh.link_frozen(rel, v2 / rel)
    for rel, src in CHEMMATH_AFAR_INPUTS.items():
        sh.link_frozen(rel, src)
        sh.entries[-1]["origin"] = f"frozen-cal2026-08-28 (data/frames or data/cal2026-08-28/frames): {src.relative_to(REPO)}"
    rec: dict = {}
    if patch_extra is not None:
        # 2026-09-23: the works-by-author API patch (04_rebuild_y's second population, the union
        # rung's API-first outcomes) extended by the October roster additions that have no
        # aggregate anywhere (fetch_patch_supplement.py); frozen rows first, byte for byte
        patch_rel = PATCH_A_REL
        a, b = (v2 / patch_rel).read_bytes(), patch_extra.read_bytes()
        assert sha(v2 / patch_rel) == LEGACY_PINS[patch_rel], "the frozen 2026-08-13 patch no longer matches its pin"
        assert a.endswith(b"\n") and b.endswith(b"\n")
        sh.write(patch_rel, a + b, f"frozen 2026-08-13 API patch ⧺ {patch_extra.relative_to(REPO)} "
                                   f"({a.count(b'\n')} + {b.count(b'\n')} lines)")
        rec["patch_supplement"] = {"frozen_lines": a.count(b"\n"), "extra_lines": b.count(b"\n"),
                                   "extra": str(patch_extra.relative_to(REPO)), "extra_sha256": sha(patch_extra)}
    blob, removed = new_events_minus(v2, removed_new_stars)
    sh.write(f"{ECON}/data/new_events_econ.csv", blob,
             f"frozen new_events_econ.csv minus {sorted(removed)} (event-age table)" if removed
             else "frozen new_events_econ.csv (byte-identical)")
    rec["new_events_removed"] = removed
    removed_new_events = {f"{r['author_id']}:{int(r['arrival'])}" for r in new_events_rows(v2)
                          if r["author_id"] in removed_new_stars}
    frame_rel = fs08.ECON_RUN_FRAME
    rep_rel = f"{ECON}/runs/econ_fnfix/build_report.json"
    src_frame = v2 / frame_rel
    rep = json.loads((v2 / rep_rel).read_text(encoding="utf-8"))
    if removed_new_events:
        raw = src_frame.read_bytes()
        total_removed = 0
        for e in sorted(removed_new_events):
            tmp = root / f"_tmp_{e.replace(':', '_')}.csv"
            tmp.write_bytes(raw)
            raw, kept, n = fs08.drop_event_lines(tmp, e, 3)
            tmp.unlink()
            total_removed += n
            rec.setdefault("prodlib_frame_rows_removed", {})[e] = n
        before = dict(rep["export"])
        rep["export"]["n_events_in_frame"] = before["n_events_in_frame"] - len(
            [e for e in removed_new_events if rec["prodlib_frame_rows_removed"][e] > 0])
        rep["export"]["n_rows"] = before["n_rows"] - total_removed
        sh.write(frame_rel, raw, f"frozen prodlib frame minus events {sorted(removed_new_events)}")
        sh.write(rep_rel, json.dumps(rep, ensure_ascii=False, indent=1).encode("utf-8"),
                 f"frozen prodlib build_report, export counts {before} -> {rep['export']}")
    else:
        sh.link_frozen(frame_rel, src_frame)
        sh.link_frozen(rep_rel, v2 / rep_rel)
    sup_rel = f"{ECON}/data/edges_supplement_fnfix.jsonl"
    if supplement_extra is None:
        # an own copy, never a link: the ledger script opens it with mode 'a' (01_merge_inputs.py),
        # which fails on the read-only legacy inode on EC2 and would write through a link elsewhere
        sh.write(sup_rel, (v2 / sup_rel).read_bytes(), "frozen fnfix supplement (own copy: the ledger opens it for append)")
    else:
        a, b = (v2 / sup_rel).read_bytes(), supplement_extra.read_bytes()
        assert a.endswith(b"\n") and b.endswith(b"\n")
        sh.write(sup_rel, a + b, f"frozen fnfix supplement ⧺ {supplement_extra.relative_to(REPO)} "
                                 f"({a.count(b'\n')} + {b.count(b'\n')} lines)")
        rec["supplement"] = {"frozen_lines": a.count(b"\n"), "extra_lines": b.count(b"\n"),
                             "extra": str(supplement_extra.relative_to(REPO)), "extra_sha256": sha(supplement_extra)}
    return sh, rec


# ---------------------------------------------------------------------------------------------
# stage runners
# ---------------------------------------------------------------------------------------------

def run_stage(stage: str, scratch: pathlib.Path, args: tuple[str, ...] = (), execute: bool = False,
              shadow: pathlib.Path | None = None) -> dict:
    """One run_frames stage in a subprocess (run_cal_frames.run_stage, unchanged in substance)."""
    import re                                                            # noqa: PLC0415
    scratch.mkdir(parents=True, exist_ok=False)
    cmd = [PY, str(REPO / "pipeline/frames/run_frames.py"), stage]
    if execute:
        cmd.append("--execute")
    if args:
        cmd += ["--", *args]
    env = {**os.environ, OUT_ROOT_ENV: str(scratch), "PYTHONHASHSEED": "0"}
    env.pop("SAR_LEGACY_THESIS", None)
    if shadow is not None:
        env["SAR_LEGACY_THESIS"] = str(shadow)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, env=env)
    (scratch / f"{stage}.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"run_frames.py {stage} {args} failed ({proc.returncode}):\n"
                           + (proc.stdout + proc.stderr)[-4000:])
    m = re.search(r"run directory -> (.+)", proc.stdout)
    produced = {p: s for p, s in re.findall(
        r"^\s+OK\s+(/.+?)\s+\(\d[\d,]* B, sha256 ([0-9a-f]{64})\)$", proc.stdout, re.M)}
    assert m and produced, f"launcher reported no run dir / outputs:\n{(proc.stdout + proc.stderr)[-2000:]}"
    log(f"stage {stage} finished in {time.time() - t0:.1f} s ({len(produced)} outputs)")
    return {"run_dir": pathlib.Path(m.group(1).strip()), "produced": produced,
            "secs": round(time.time() - t0, 1), "stage": stage, "args": list(args)}


def run_make_slim(field: str, src: pathlib.Path, out_dir: pathlib.Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=False)
    ev = out_dir / f"p3_slim_ev_{field}.parquet"
    noev = out_dir / f"p3_slim_{field}.parquet"
    proc = subprocess.run([PY, str(REPO / "pipeline/frames/make_slim.py"), field, str(src),
                           str(ev), "--noev", str(noev)], cwd=REPO, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    stats = eval(proc.stdout.strip().splitlines()[-1], {"__builtins__": {}}, {})  # noqa: S307
    return {"ev": ev, "noev": noev, "stats": stats}


def preimport_dose() -> str:
    """Bind `identity.dose` to THIS repository's ported unit, origin-asserted (run_frames' rule)."""
    src = REPO / "pipeline/units/u0_foundation/src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    mod = importlib.import_module("identity.dose")
    origin = pathlib.Path(mod.__file__).resolve()
    assert origin.is_relative_to(REPO / "pipeline" / "units"), origin
    return f"identity.dose <- {origin.relative_to(REPO)}"


def run_union(cfg: dict, run_root: pathlib.Path, log_path: pathlib.Path,
              gdose_all: bool = False, override_gdose_gate: bool = False) -> dict:
    """Stage the clone (hard link, sha-asserted against the tracked file) and run it IN PROCESS
    inside a staged_run mark with `cfg` as its JSON config. A gate FAIL (`sys.exit(2)`, "gold standard not passed")
    is returned as a failure, never swallowed.

    `gdose_all=True` is a MEASUREMENT mode, never a build: the clone's G-DOSE check draws 200 old
    relations (`DataFrame.sample(n=200, random_state=42)`) and requires max |July dose - recomputed
    dose| <= 0.01 on that draw; the residuals belong to the frozen rows (byte-preserved, independent
    of any filter) while the draw depends on the input's row count. In this mode `DataFrame.sample`
    is replaced by the identity for the duration of the run, so the clone evaluates EVERY old
    relation, and the clone's module namespace is captured at its own `json.dump(report, …)` call
    (the `worst` list holds every relation whose residual exceeds 1e-9). The gate then fails by
    construction (exit 2) and the frame is not written; the returned dict carries the population.

    `override_gdose_gate=True` intercepts the clone's ONE `sys.exit(2)` (the gate line, reached
    after `build_report.json` is written) so that the clone goes on to write its frame and
    relationships. It is a DEVIATION the launcher only exercises after the evidence gate in
    `run_econ920.override_is_justified` (population measured; this draw predicted FAIL; every
    failing drawn relation is a frozen-population residual; G_ROW 0 mismatches; G_SUM ok) and it
    is recorded in the returned dict (`gate_overridden`), the build report and the staging
    manifest. It never changes a row: the gate decides only whether the file is written."""
    from contextlib import redirect_stdout                               # noqa: PLC0415
    import pandas as _pd                                                 # noqa: PLC0415
    captured: dict = {}
    orig_sample, orig_dump, orig_exit = _pd.DataFrame.sample, json.dump, sys.exit
    intercepted: list[int] = []

    def _exit(code=0):
        if code == 2 and "report_dumped" in captured and not intercepted:
            intercepted.append(code)
            return None                                    # the gate line: continue to the write-out
        return orig_exit(code)

    def _dump(obj, fp, *a, **k):
        if isinstance(obj, dict) and "G_DOSE" in obj:
            captured["report_dumped"] = True
            g = sys._getframe(1).f_globals
            captured["worst"] = list(g.get("worst", []))
            captured["diffs"] = list(g.get("diffs", []))
            captured["sampled"] = [(r.pid, r.event_id, float(r.dose_topic))
                                   for r in g["g"].itertuples()] if "g" in g else []
        return orig_dump(obj, fp, *a, **k)
    code = run_root / "code"
    code.mkdir(parents=True, exist_ok=True)
    target = code / CLONE.name
    if target.exists():
        target.unlink()
    try:
        os.link(CLONE, target)
    except OSError:
        shutil.copyfile(CLONE, target)
    assert sha(target) == sha(CLONE)
    cfg_p = run_root / "config_econ920.json"
    cfg_p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    for k in ("OUT_FRAME", "OUT_REPORT", "OUT_REL"):
        pathlib.Path(cfg[k]).parent.mkdir(parents=True, exist_ok=True)
    dose_origin = preimport_dose()
    argv0 = sys.argv
    t0 = time.time()
    buf = io.StringIO()
    code_exit = 0
    try:
        sys.argv = [str(target), str(cfg_p)]
        if gdose_all:
            _pd.DataFrame.sample = lambda self, *a, **k: self
        if gdose_all or override_gdose_gate:
            json.dump = _dump
        if override_gdose_gate:
            sys.exit = _exit
        with staged_run(target), redirect_stdout(buf):
            try:
                runpy.run_path(str(target), run_name="__main__")
            except SystemExit as exc:
                code_exit = int(exc.code or 0)
    finally:
        sys.argv = argv0
        _pd.DataFrame.sample, json.dump, sys.exit = orig_sample, orig_dump, orig_exit
        log_path.write_text(buf.getvalue(), encoding="utf-8")
    secs = round(time.time() - t0, 1)
    out = {"clone_sha256": sha(target), "config": str(cfg_p), "secs": secs, "exit": code_exit,
           "dose_module": dose_origin, "log": str(log_path),
           "gate_overridden": bool(intercepted)}
    if override_gdose_gate:
        out["drawn_relations"] = [{"pid": a, "event_id": b, "frozen_dose": c} for a, b, c in captured.get("sampled", [])]
        out["drawn_residuals_gt_1e-9"] = [{"pid": w[0], "event_id": w[1], "frozen_dose": w[2], "recomputed": w[3],
                                          "abs_diff": abs(w[2] - w[3])} for w in captured.get("worst", [])]
    if gdose_all:
        rep = json.loads(pathlib.Path(cfg["OUT_REPORT"]).read_text(encoding="utf-8"))
        diffs = captured.get("diffs", [])
        worst = sorted(captured.get("worst", []), key=lambda w: -abs(w[2] - w[3]))
        out["gdose_population"] = {
            "mode": "MEASUREMENT: DataFrame.sample -> identity; every old relation evaluated",
            "n": len(diffs), "missing_side": rep["G_DOSE"]["missing_side"],
            "share_exact_1e-9": rep["G_DOSE"]["share_exact_1e-9"], "max_abs_diff": rep["G_DOSE"]["max_abs_diff"],
            "n_gt_1e-9": len(worst), "n_gt_0.01": sum(1 for w in worst if abs(w[2] - w[3]) > 0.01),
            "n_gt_0.05": sum(1 for w in worst if abs(w[2] - w[3]) > 0.05),
            "residuals_gt_1e-9": [{"pid": w[0], "event_id": w[1], "frozen_dose": w[2], "recomputed": w[3],
                                   "abs_diff": abs(w[2] - w[3])} for w in worst],
            "gate_exit": code_exit}
        return out
    if code_exit:
        out["error"] = f"the union rung's own gate failed (exit {code_exit}) — see {log_path}"
        return out
    rep = json.loads(pathlib.Path(cfg["OUT_REPORT"]).read_text(encoding="utf-8"))
    out["report"] = {k: rep.get(k) for k in ("relationships", "alias", "need_outcomes", "outcome_src",
                                             "sup_fallback_stars", "api_only_pids", "G_SUM", "frame",
                                             "GATE", "dose_override_new_rows")}
    out["report"]["G_DOSE"] = {k: rep["G_DOSE"].get(k) for k in ("n", "missing_side", "max_abs_diff", "share_exact_1e-9")}
    out["report"]["G_ROW"] = {k: rep["G_ROW"].get(k) for k in ("sampled_both", "mismatches", "dose_tolerated_le_0.01", "fill_divergence")}
    for k in ("OUT_FRAME", "OUT_REPORT", "OUT_REL"):
        out[k] = {"path": cfg[k], "sha256": sha(pathlib.Path(cfg[k])), "lines": pathlib.Path(cfg[k]).read_bytes().count(b"\n")}
    log(f"union rung finished in {secs} s: GATE {rep.get('GATE')} rows {rep['frame']['rows']} "
        f"relationships {rep['frame']['relationships']} by_channel {rep['frame']['by_channel']}")
    return out


def run_r_cell(driver: str, label: str, frame: pathlib.Path, out_dir: pathlib.Path) -> pathlib.Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, SAR_OUT=str(out_dir), PYTHONHASHSEED="0")
    logf = out_dir / f"{label}.log"
    t0 = time.time()
    with open(logf, "wb") as lf:
        r = subprocess.run(["Rscript", str(EST / driver), label, str(frame)], cwd=REPO, env=env,
                           stdout=lf, stderr=subprocess.STDOUT, timeout=7200)
    produced = out_dir / f"{label}.json"
    if r.returncode != 0 or not produced.is_file():
        raise RuntimeError(f"{driver} {label} failed ({r.returncode}):\n"
                           + logf.read_bytes()[-2000:].decode("utf-8", "replace"))
    log(f"R {driver} {label}: {time.time() - t0:.1f} s")
    return produced


def compare_cells(new: pathlib.Path, expected: pathlib.Path) -> dict:
    d = compare_json(json.loads(new.read_text("utf-8")), json.loads(expected.read_text("utf-8")))
    return {"new": str(new), "expected": str(expected), "verdict": "EQUAL" if not d else "DIFF",
            "diffs": d[:40]}


def content_verdict(a: pathlib.Path, b: pathlib.Path, accept=()) -> dict:
    r = content_equal(a, b, accept_type_change=accept)
    return {"a": str(a), "b": str(b), "mode": r.mode, "equal": bool(r.equal), "rows_a": r.rows_a,
            "rows_b": r.rows_b, "only_in_a": r.only_in_a, "only_in_b": r.only_in_b,
            "schema_diff": list(r.schema_diff), "accepted": list(r.accepted_schema_diff),
            "sha256_a": r.sha256_a, "sha256_b": r.sha256_b}


# ---------------------------------------------------------------------------------------------
# proofs
# ---------------------------------------------------------------------------------------------

def frame_index(p: pathlib.Path) -> dict[tuple[str, str, str], bytes]:
    """(pid, event_id, year) -> the raw line (the file's own bytes, '\\r' kept)."""
    _, lines, _ = read_frame_lines(p)
    idx = {}
    for ln in lines:
        c = cells_of(ln)
        k = (c[0], c[3], c[1])
        assert k not in idx, f"duplicate key {k} in {p.name}"
        idx[k] = ln
    return idx


def union_rows_proof(frozen_pre_y: pathlib.Path, union_out: pathlib.Path,
                     regenerated_events: set[str]) -> dict:
    """G_ROW-style: every network/both row of the union output whose event is not regenerated must
    be BYTE-IDENTICAL to the frozen pre-y frame's row for the same (person, event, year) except,
    at most, in the trailing `channel` cell (a roster change can turn network into both); every
    such difference is counted by (from -> to). Rebuilt dept_only rows and the regenerated
    events' rows have no frozen source and are counted separately."""
    frozen = frame_index(frozen_pre_y)
    _, lines, _ = read_frame_lines(union_out)
    counts = collections.Counter()
    channel_moves = collections.Counter()
    bad = []
    changed_dept: list[dict] = []           # rebuilt dept_only rows that differ from the frozen row
    for ln in lines:
        c = cells_of(ln)
        k = (c[0], c[3], c[1])
        ch = c[16]
        if c[3] in regenerated_events:
            counts[f"regenerated:{ch}"] += 1
            continue
        if ch == "dept_only":
            counts["dept_only_rebuilt"] += 1
            if k in frozen:
                fc = cells_of(frozen[k])
                counts["dept_only_rebuilt_identical" if fc == c else "dept_only_rebuilt_changed"] += 1
                if fc != c:
                    cols = [FRAME_COLS[i] if i < 16 else "channel" for i in range(17) if fc[i] != c[i]]
                    ul = {}
                    for i, name in enumerate(FRAME_COLS):
                        if fc[i] != c[i] and name in FLOAT_COLS and fc[i] and c[i]:
                            ul[name] = fs08.ulps(float(fc[i]), float(c[i]))
                    changed_dept.append({"key": k, "cols": cols, "ulps": ul,
                                         "frozen": {n_: fc[FRAME_COLS.index(n_)] for n_ in cols if n_ in FRAME_COLS},
                                         "new": {n_: c[FRAME_COLS.index(n_)] for n_ in cols if n_ in FRAME_COLS}})
                    if not (set(cols) <= set(Y_SWAPPED_BY_04) and all(v <= 8 for v in ul.values())
                            and len(ul) == len(cols)):
                        counts["dept_only_rebuilt_changed_BEYOND_Y_SWAPPED"] += 1
            continue
        src = frozen.get(k)
        if src is None:
            counts["network_row_without_frozen_source"] += 1
            bad.append({"key": k, "new": ln[:160].decode("utf-8", "replace"), "class": "no_source"})
            continue
        if src == ln:
            counts["byte_identical"] += 1
            continue
        fc = cells_of(src)
        if fc[:16] == c[:16] and fc[16] != c[16]:
            counts["channel_only"] += 1
            channel_moves[f"{fc[16]}->{c[16]}"] += 1
        else:
            counts["OTHER_DIFFERENCE"] += 1
            if len(bad) < 12:
                bad.append({"key": k, "frozen": src[:200].decode("utf-8", "replace"),
                            "new": ln[:200].decode("utf-8", "replace"),
                            "cols": [FRAME_COLS[i] if i < 16 else "channel" for i in range(17) if fc[i] != c[i]]})
    closed = (counts["OTHER_DIFFERENCE"] == 0 and counts["network_row_without_frozen_source"] == 0
              and counts["dept_only_rebuilt_changed_BEYOND_Y_SWAPPED"] == 0)
    return {"closed": closed, "counts": dict(counts), "channel_moves": dict(channel_moves),
            "samples": bad, "dept_only_rebuilt_changed": changed_dept[:20],
            "dept_only_changed_note": "a rebuilt dept_only row differing from the frozen row only in the "
                                      "four y columns 04 overwrites (<= 8 ULP) is the union rung's own "
                                      "non-determinism (c1a); anything else opens the proof",
            "frozen": str(frozen_pre_y), "frozen_sha256": sha(frozen_pre_y),
            "union": str(union_out), "union_sha256": sha(union_out)}


def agg_missing_persons(pre_y: pathlib.Path, v2: pathlib.Path, prodlib_events: set[str], *,
                        stage_cfg: dict | None = None) -> dict:
    """What `04_rebuild_y.py` cannot give a y to: person-years with publications whose person is
    in neither the frozen 2026-08-09 units table nor the 2026-08-13 API patch. Old-event rows of
    such persons trip 04's C-PC anchor (`agg_missing` -> PASS False, exit 2); prodlib-event rows
    are written y = NA without blocking. Persons are cross-checked against the October roster
    additions (roster_added_persons: the run config's table, required)."""
    added = roster_added_persons(stage_cfg)
    import duckdb                                                        # noqa: PLC0415
    units = v2 / "fwci_fullsnapshot_rebuild_2026-08-09/data/econ_units_2026-08-09.parquet"
    patch = v2 / "econ_final_2026-08-13/patch/works_by_author.jsonl"
    con = duckdb.connect()
    u = {t[0] for t in con.execute(f"select distinct incumbent_person_id from read_parquet('{units.as_posix()}')").fetchall()}
    pa = {"P_" + json.loads(l)["author_id"] for l in open(patch, encoding="utf-8")}
    rows = con.execute(f"select incumbent_person_id, year, event_id, channel, pub_count from "
                       f"read_csv_auto('{pre_y.as_posix()}', all_varchar=true) "
                       f"where pub_count not in ('', '0', '0.0')").fetchall()
    con.close()
    out = {}
    for cls, pred in (("old_event_rows_blocking", lambda r: r[2] not in prodlib_events),
                      ("prodlib_event_rows_written_NA", lambda r: r[2] in prodlib_events)):
        bad = [r for r in rows if pred(r) and r[0] not in u and r[0] not in pa]
        persons = sorted({r[0] for r in bad})
        out[cls] = {"rows": len(bad), "persons": persons, "person_years": len({(r[0], r[1]) for r in bad}),
                    "events": sorted({r[2] for r in bad}),
                    "by_channel": {c: sum(1 for r in bad if r[3] == c) for c in ("network", "dept_only", "both")},
                    "persons_in_roster_added_2026-10": sum(1 for p_ in persons if p_ in added)}
    out["units"] = {"path": str(units), "sha256": sha(units), "persons": len(u)}
    out["patch"] = {"path": str(patch), "sha256": sha(patch), "persons": len(pa)}
    return out


def strict_walk(frozen: pathlib.Path, new: pathlib.Path, is_removed) -> dict:
    return fs08.strict_removal_walk(frozen, new, is_removed)


# ---------------------------------------------------------------------------------------------
# (d): the prodlib regeneration through piece A's econ config/stage
# ---------------------------------------------------------------------------------------------

def regenerate_with_prodlib(root: pathlib.Path, v2: pathlib.Path, econ_table_corrected: pathlib.Path,
                            tables_chemmath: dict[str, pathlib.Path], report: dict, *,
                            stage_cfg: dict | None = None) -> pathlib.Path:
    """Piece A's economics prodlib run (stage.py's building blocks, the working-tree versions; the
    signature of build_exclusion is inspected so the reviewed fragment rule is used when present)
    on the id-corrected econ event table + the October roster pool. Returns the prodlib frame.
    stage_cfg = the run config's `stage` section (restake / names tables of the u4_aug star set);
    None = stage.stage_config(), the October callers' route (an unset $SAR_R1_CONFIG is a STOP)."""
    cfg = pa_stage.stage_config() if stage_cfg is None else stage_cfg
    u4_inputs = pa_stage.u4_aug_inputs(cfg)
    tables = {"econ": econ_table_corrected, **tables_chemmath}
    stars = pa_stage.event_stars(tables)
    root.mkdir(parents=True, exist_ok=True)
    econ_dir = root / "cal2026-10" / "econ"
    econ_dir.mkdir(parents=True, exist_ok=True)
    rec: dict = {"tables": {f: {"path": str(p), "sha256": sha(p), "n_events": len(stars[f])}
                            for f, p in tables.items()}}
    excl_out = econ_dir / "stars_excluded_cal2026-10.parquet"
    sig = inspect.signature(pa_stage.build_exclusion)
    if "person_map" in sig.parameters:
        rec["stars_excluded"] = pa_stage.build_exclusion(stars, excl_out, person_map=person_map_path())
        rec["stars_excluded"]["rule_version"] = "working-tree stage.py: 08-28 list ∪ event stars ∪ U2 fragments"
    else:
        rec["stars_excluded"] = pa_stage.build_exclusion(stars, excl_out)
        rec["stars_excluded"]["rule_version"] = "committed stage.py: 08-28 list ∪ event stars"
    import pyarrow.parquet as pq                                         # noqa: PLC0415
    excluded = set(pq.read_table(excl_out).column("author_id").to_pylist())
    pool_out = econ_dir / "roster_pool_econ_cal2026-10.parquet"
    rec["roster_pool"] = pa_stage.build_roster_pool(excluded, pool_out)
    inst = pa_stage.school_inst(v2 / fs08.PINNED_LEGACY_CODE_ROSTERLIB)
    rec["u4_aug"] = pa_stage.build_u4_aug(v2, econ_table_corrected, inst, econ_dir / "u4_aug", **u4_inputs)
    sup_out = econ_dir / "edges_supplement_econ_cal2026-10.jsonl"
    rec["supplement"] = pa_stage.concat_supplements(sup_out)
    rec["person_map"] = pa_stage.assert_stars_in_person_map(stars["econ"])
    mirror = root / "prodlib_econ"
    cfg = pa_stage.render_config("econ", root, mirror / "runs" / "econ")
    prun: dict = {}
    out = pa_stage.run_prodlib("econ", mirror, cfg, prun)
    rec["prodlib"] = prun["prodlib"]["econ"]
    rec["unit_modules"] = prun.get("unit_modules")
    report["regeneration"] = rec
    return out


# ---------------------------------------------------------------------------------------------
# the union clone's config + the characterisation of a not-byte-equal pre-y frame
# ---------------------------------------------------------------------------------------------

#: the four columns `04_rebuild_y.py` OVERWRITES on every row (its Y_SWAP): a pre-y frame that
#: differs from its reference only here, by float last bits, feeds 04 identically (04 reads the old
#: fwci_frac only for a NA/value transition count and a 1e-6-relative reproduction anchor)
Y_SWAPPED_BY_04 = ("fwci_frac", "fwci_frac_ex_star", "fwci_mean", "fwci_mean_ex_star")
FLOAT_COLS = Y_SWAPPED_BY_04 + ("dose_topic", "age_gap")


PATCH_A_REL = "econ_final_2026-08-13/patch/works_by_author.jsonl"


def union_config(*, v2: pathlib.Path, old_frame: pathlib.Path, roster: pathlib.Path,
                 ledger: pathlib.Path, star_set: pathlib.Path, sup_fnfix: pathlib.Path,
                 new_events: pathlib.Path, out_dir: pathlib.Path,
                 patch_a: pathlib.Path | None = None) -> dict:
    """The JSON config the clone reads (make_clone.CONFIG_KEYS). SUP11 and PATCH_B are the frozen
    legacy files in every arrangement (the caliber does not touch them). PATCH_A defaults to the
    frozen legacy patch (the controls); the October run passes the SHADOW's patch — the frozen
    patch ⧺ the roster-addition supplement that `04_rebuild_y.py` aggregates from — so the union
    rung's API-first outcomes and 04's aggregates count the same works. (Review 2026-09-23: the
    committed 729788a run got that content only because `Shadow.write` had, through a hard link,
    overwritten the legacy patch itself; the clone read the real legacy path.)"""
    return {
        "OLD_FRAME": str(old_frame), "ROSTER": str(roster), "LEDGER": str(ledger),
        "STAR_SET": str(star_set),
        "SUP11": str(v2 / "netbase_supplement_2026-07-23/edges_supplement_stars11.jsonl"),
        "SUP_FNFIX": str(sup_fnfix),
        "PATCH_A": str(patch_a if patch_a is not None else v2 / PATCH_A_REL),
        "PATCH_B": str(v2 / "econ_final_2026-08-13/patch/works_meta.jsonl"),
        "NEW_EVENTS": str(new_events),
        "OUT_FRAME": str(out_dir / "analysis_frame_dept_p01_econ920_2026-08-13.csv"),
        "OUT_REPORT": str(out_dir / "build_report.json"),
        "OUT_REL": str(out_dir / "relationships.csv"),
    }


def characterise_frame(reference: pathlib.Path, new: pathlib.Path) -> dict:
    """Keyed (person, event, year) accounting of `new` against `reference` (frames_stage
    .keyed_csv_accounting), summarised: rows added/removed, modified rows by the SET of differing
    columns, the worst ULP per float column, and the verdict
      BYTE_EQUAL                       sha256 equal
      EQUAL_MODULO_Y_SWAPPED_BY_04     no row added/removed; every difference in Y_SWAPPED_BY_04
                                       and <= 8 ULP (the M3/H1 bound) — immaterial for the chain
      NOT_EQUAL                        anything else (a STOP for the caller)."""
    if sha(reference) == sha(new):
        return {"verdict": "BYTE_EQUAL", "reference": str(reference), "new": str(new),
                "sha256": sha(new)}
    acc = fs08.keyed_csv_accounting(reference, new, ("incumbent_person_id", "event_id", "year"),
                                    float_cols=FLOAT_COLS)
    by_cols = collections.Counter(tuple(m["cols"]) for m in acc["modified"])
    worst: dict[str, int] = {}
    nonfloat = collections.Counter()
    for m in acc["modified"]:
        for c in m["cols"]:
            u = m.get("ulps", {}).get(c)
            if u is None:
                nonfloat[c] += 1
            else:
                worst[c] = max(worst.get(c, 0), u)
    only_y = all(set(m["cols"]) <= set(Y_SWAPPED_BY_04) for m in acc["modified"])
    small = all(v <= 8 for v in worst.values()) and not nonfloat
    verdict = ("EQUAL_MODULO_Y_SWAPPED_BY_04" if (not acc["added"] and not acc["removed"]
                                                 and only_y and small) else "NOT_EQUAL")
    return {"verdict": verdict, "reference": str(reference), "reference_sha256": sha(reference),
            "new": str(new), "new_sha256": sha(new), "rows_reference": acc["rows_frozen"],
            "rows_new": acc["rows_new"], "rows_added": len(acc["added"]),
            "rows_removed": len(acc["removed"]), "rows_identical": acc["identical"],
            "rows_modified": len(acc["modified"]),
            "modified_by_columns": {",".join(k): v for k, v in by_cols.most_common()},
            "worst_ulp_by_column": worst, "non_float_differences_by_column": dict(nonfloat),
            "samples_modified": acc["modified"][:6], "samples_added": acc["added"][:6],
            "samples_removed": acc["removed"][:6]}


def per_event_counts(relationships: pathlib.Path, p1_frame: pathlib.Path | None,
                     p2_frame: pathlib.Path | None) -> dict:
    """event -> {network, dept_only, both, relations, p1_rows, p2_rows} from the union's
    relationships.csv (pid,event_id,channel) and the P1 / P2 frames."""
    out: dict[str, dict] = {}
    for r in read_rows(relationships):
        d = out.setdefault(r["event_id"], {"network": 0, "dept_only": 0, "both": 0, "relations": 0,
                                           "p1_rows": 0, "p2_rows": 0})
        d[r["channel"]] += 1
        d["relations"] += 1
    for p, key in ((p1_frame, "p1_rows"), (p2_frame, "p2_rows")):
        if p is None or not p.is_file():
            continue
        with open(p, "rb") as f:
            hdr = f.readline().decode().rstrip("\r\n").split(",")
            k = hdr.index("event_id")
            for line in f:
                e = line.decode().split(",")[k]
                out.setdefault(e, {"network": 0, "dept_only": 0, "both": 0, "relations": 0,
                                   "p1_rows": 0, "p2_rows": 0})[key] += 1
    return dict(sorted(out.items()))


def drop_events_from_csv(src: pathlib.Path, events: set[str], col: int, out: pathlib.Path) -> dict:
    """`src` minus every line whose `col`-th cell is in `events` (frames_stage.drop_event_lines,
    applied per event so each removal is counted); kept lines byte-preserved."""
    raw = src.read_bytes()
    removed = {}
    tmp = out.with_suffix(".tmp")
    for e in sorted(events):
        tmp.write_bytes(raw)
        raw, _kept, n = fs08.drop_event_lines(tmp, e, col)
        removed[e] = n
    tmp.unlink(missing_ok=True)
    out.write_bytes(raw)
    return {"source": str(src), "source_sha256": sha(src), "removed_lines": removed,
            "output": str(out), "output_sha256": sha(out), "lines": raw.count(b"\n")}


# ---------------------------------------------------------------------------------------------
# (a) and (b) on the union OUTPUT — byte-preserving, network rows only — and the gate-draw predictor
# ---------------------------------------------------------------------------------------------

def predict_gdose_draw(old_frame: pathlib.Path, new_events: set[str], residuals: dict[tuple[str, str], float]) -> dict:
    """The clone's own draw, replicated: `old = pd.read_csv(OLD_FRAME)`, pid = incumbent without
    `P_`, relations = drop_duplicates(pid, event_id), minus the prodlib-row events, then
    `.sample(n=min(200, len), random_state=42)`; looked up in a measured residual population
    (`run_union(gdose_all=True)`; a relation absent from it has residual 0)."""
    import pandas as pd                                                  # noqa: PLC0415
    old = pd.read_csv(old_frame)
    old["pid"] = old.incumbent_person_id.map(lambda x: x.replace("P_", "", 1))
    g_all = old[["pid", "event_id", "dose_topic"]].drop_duplicates(["pid", "event_id"])
    g = g_all[~g_all.event_id.isin(new_events)]
    g = g.sample(n=min(200, len(g)), random_state=42)
    hits = [(r.pid, r.event_id, residuals.get((r.pid, r.event_id), 0.0)) for r in g.itertuples()]
    mx = max((h[2] for h in hits), default=0.0)
    exact = sum(1 for h in hits if h[2] < 1e-9) / len(hits) if hits else 0
    return {"population_relations": len(g_all[~g_all.event_id.isin(new_events)]), "drawn": len(hits),
            "predicted_max_abs_diff": mx, "predicted_share_exact_1e-9": exact,
            "predicted_gate": "PASS" if (exact >= 0.90 and mx <= 0.01) else "FAIL",
            "drawn_relations_gt_0.01": [h for h in hits if h[2] > 0.01]}


def postfilter_union(pre_y: pathlib.Path, rel: pathlib.Path, roster: pathlib.Path,
                     person_map: pathlib.Path, out_dir: pathlib.Path, *, in_post: bool) -> dict:
    """Filters (a) (verified roster, either id form) and, with `in_post`, (b) (a roster spell
    covering the arrival year) applied to the union rung's OUTPUT: the 17-column pre-y frame and
    relationships.csv. Byte-preserving; every dropped row is asserted to be a `network` row.

    WHY the output and not the input. The clone's G-DOSE gate is a fixed-seed 200-draw over the
    input's old relations with a hard 0.01 ceiling on a residual population that has a tail above
    0.01 (measured: run_union gdose_all). The residuals belong to the frozen rows and do not
    depend on any filter; the draw depends on the row count, so a person-level pre-filter changes
    the draw and the gate outcome by sample composition alone (c3 on the 920 roster: the draw hit
    0.0698 where the 08-13 draw had 0.0019). Filtering the output is EQUIVALENT to filtering the
    input for these two filters, because every row they remove is a network-only relation of a
    person who is (a) not on the roster in any id form or (b) on it but in post nowhere in the
    arrival year: such a relation is in no dept relation, no `both` set and no `alias_dup` set
    (a dept alias would have made the person verified / in post through the shared U2 person id),
    dose vectors, first-pub years and outcomes are per person, and old rows are byte-preserved and
    dept rows built from `new_rel` either way. The ONE thing that could differ is an event whose
    every relation is removed and that has no dept relation at all (its star would then leave the
    clone's `star_arrival_by_canon`), which this function measures and reports
    (`events_left_with_zero_relations`) instead of assuming. Event-level filters ((c),(d)) are NOT
    equivalent and stay on the input."""
    out_dir.mkdir(parents=True, exist_ok=True)
    forms, fsrc = verified_forms(roster, person_map)
    fa = filter_verified(pre_y, forms, out_dir / "pre_y_a_verified.csv")
    fa["forms"] = fsrc
    cur = pathlib.Path(fa["output"]["frame"])
    fb = None
    if in_post:
        fb = filter_inpost(cur, roster, person_map, out_dir / "pre_y_b_inpost.csv",
                           out_dir / "inpost_report.json")
        cur = pathlib.Path(fb["output"]["frame"])
    # the dropped relations, and the assertion that every one of them is a network-only relation
    kept_keys = set()
    _h, lines, _t = read_frame_lines(cur)
    for ln in lines:
        c = cells_of(ln)
        kept_keys.add((c[0], c[3]))
    _h, lines0, _t = read_frame_lines(pre_y)
    dropped_keys, dropped_channels = set(), collections.Counter()
    for ln in lines0:
        c = cells_of(ln)
        if (c[0], c[3]) not in kept_keys:
            dropped_keys.add((c[0], c[3]))
            dropped_channels[c[16]] += 1
    assert set(dropped_channels) <= {"network"}, f"a non-network row was dropped: {dropped_channels}"
    dropped_bare = {(p.replace("P_", "", 1), e) for p, e in dropped_keys}
    raw = rel.read_bytes()
    rl = raw.split(b"\n")
    hdr = rl[0].decode("utf-8").rstrip("\r").split(",")
    ip, ie, ic = hdr.index("pid"), hdr.index("event_id"), hdr.index("channel")
    kept_rel, n_drop = [rl[0]], 0
    for ln in rl[1:]:
        if not ln:
            kept_rel.append(ln)
            continue
        c = ln.decode("utf-8").rstrip("\r").split(",")
        if (c[ip], c[ie]) in dropped_bare:
            assert c[ic] == "network", (c, "a relationships line of another channel was dropped")
            n_drop += 1
            continue
        kept_rel.append(ln)
    assert n_drop == len(dropped_bare), (n_drop, len(dropped_bare))
    rel_out = out_dir / "relationships.csv"
    rel_out.write_bytes(b"\n".join(kept_rel))
    events_before = {e for _p, e in {(cells_of(ln)[0], cells_of(ln)[3]) for ln in lines0}}
    events_after = {e for _p, e in kept_keys}
    return {"input": {"pre_y": str(pre_y), "sha256": sha(pre_y), "rows": len(lines0),
                      "relationships": str(rel), "relationships_sha256": sha(rel)},
            "a_verified_roster": fa,
            "b_in_post": None if fb is None else {k: fb[k] for k in ("relations_by_class", "rows_by_class",
                                                                     "persons_by_class", "events_left_with_zero_rows",
                                                                     "spells", "output")},
            "dropped_relations": len(dropped_keys), "dropped_rows_by_channel": dict(dropped_channels),
            "relationships_lines_dropped": n_drop,
            "events_left_with_zero_relations": sorted(events_before - events_after),
            "output": {"pre_y": str(cur), "sha256": sha(cur), "rows": len(lines),
                       "relationships": str(rel_out), "relationships_sha256": sha(rel_out),
                       "relationships_lines": len(kept_rel) - 1 - (1 if kept_rel[-1] == b"" else 0)}}
