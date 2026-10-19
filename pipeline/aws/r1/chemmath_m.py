#!/usr/bin/env python3
"""R1 F14 + J0-MEAS.3h: the M chemistry / mathematics frames driver (J1a stage frames_chemmath_m; the J1b
no-research-centre build calls it with --roster-variant incfel). Runs only on an R1 instance ($SAR_HOST).

    chemmath_m.py --mode m --config config/r1/M.json --events-dir DIR --roster-chemistry FILE
                  --roster-math-stats FILE --roster-variant fnfix|incfel --stars-excluded-base FILE
                  --event-tables-all DIR --calls DIR --out STAGE_OUT
                  [--fields chemistry,math_stats] [--scratch DIR] [--supplement-extra FILE ...] [--repo DIR]
    chemmath_m.py --mode b0 --config config/r1/B0.json --october-ref DIR --out STAGE_OUT
                  [--fields chemistry,math_stats] [--scratch DIR] [--repo DIR] [--edge-proof]

The October driver pipeline/frames/cal2026-10/run_cal_frames_chemmath.py is NOT edited. Its 08-28 premises
(preconditions(): the October event tables byte-identical to the 08-28 tables; run_prodlib(): the prodlib
frame BYTE_EQUAL to the 08-28 staged sha) cannot hold for M and are replaced here; everything else is
reused by import (run_stage, run_make_slim, products_of, freeze, h1_characterise, json_equal_modulo_paths,
stage.build_shadow / render_config / run_prodlib, inpost_filter).

Per field, in order (accounting recorded at each step in build_report_<field>.json):
  P  preconditions (m): the run config loads (pipeline.lib.r1_config: a missing, unsigned or unknown
     switch / ruling is a STOP), is M, and its `rosters` switch is on; every input inside the repository
     is pinned (config pins, or a frozen data MANIFEST line) with a matching sha256; the event tables
     carry the 08-28 header line and integer arrival_corrected; the rosters carry the 5 gold columns and
     the variant's basename; the calls stage said OK.
     M stars_excluded = the 08-28 list - the flips DROP stars that are not M event stars + every M event
     star of the three fields + their rank_adds alias ids (the A5044432173 precedent and
     October's every-event-star rule); added / removed ids recorded.
  S  shadow: stage.build_shadow(explicit tables, stars_excluded=<M list>, rosters=<M rosters>). The econ
     subtree is skipped (chemistry / mathematics read no econ shadow input; asserted on every rendered
     prodlib config), so the M chem/maths build does not depend on the econ M inputs. Optional
     --supplement-extra files (F18/N3) are appended to the shadow's edges_supplement_fnfix.jsonl.
  N2 the `chemmath_edges` switch on = this process started with SAR_PATHS_CONFIG = the edge-table shadow
     paths file (edge_table.py shadow, exported by the stage cmd), checked here; off = no such env.
  1  prodlib (stage.render_config + stage.run_prodlib, the pinned trio). The key diff against the B0 render
     is recorded and may only be the snapshot glob prefix (the N2 data root); every event of the table must
     reach prodlib (events_diag.n_events). build_frame.py's own exit (it runs in process) is STOP PRODLIB_EXIT.
  2  D2 in-post filter: inpost_filter.spells_from_roster(<the roster>, None, identity=True) + run, ONE
     roster file for prodlib's pool, the union builder's dept channel and the spells (sha asserted equal to
     the shadow link); a strict removal walk closes the step.
  3  V3-NET (switch network_freeze): network_freeze.apply on the 16-column frame, graph from the rendered
     prodlib config, event table = the M table; a strict removal walk closes the step.
  4  chain (run_chain_m = run_cal_frames_chemmath.run_chain line for line + one post_union hook after the
     union outputs are installed and before p1-gold): union-gold -> [S6 dose post-step: dose_chemmath.apply
     (delta), installed over the union frame] -> p1-gold -> p2-gold --panel3 full -> make_slim.
  5  G-DOSE advisory (J0-MEAS.3h): each union build report's G_DOSE_advisory (n, missing_side,
     max_abs_diff, share_exact_1e-9, share_le_0.01) copied into STAGE_OUT/report_gdose_chemmath.json,
     never gated (multidisc_gold 10_build_union_frame_gold.py: "no hard gate").
  6  coverage (N3): missing_persons.chemmath_dirs on the p1-gold dir, written through
     missing_persons.write_report (name coverage_chemmath) in the mode the `agg_missing` switch names; a
     STOP code stops the run with the person ids.
  7  products: run_cal_frames_chemmath.freeze into STAGE_OUT/frames_<field>/ (the data/frames basenames,
     relationships, union build report, inpost report, build_report_<field>.json, staging manifest,
     MANIFEST.sha256); in M the build report also carries October's schema (canon_schema) and each y-step
     report is published as STAGE_OUT/yrebuild_chemmath/g_yrebuild_<field>.json (M review #8).
Mode b0 (the switch-off proof; J0-MEAS.3j / batch B4): B0 config, October tables / rosters / 08-28 list
through stage.build_shadow's October defaults, no N2 env, no V3-NET, no dose; the products must equal
--october-ref's data/cal2026-10/frames_<field>/ under October's acceptance (relationships and p2 BYTE_EQUAL,
union report equal modulo paths and H1 at the advisory path, p1 within H1, pairs / slims content-equal),
else STOP B0_NOT_OCTOBER.
Mode b0 --edge-proof (the S10 reverse proof's driver: pipeline/aws/r1/reverse_proof_s10.py, J0-MEAS.3j / B4
only; no stage passes it): the same b0 run, except (a) the process MUST start with SAR_PATHS_CONFIG = an
edge-table shadow paths file (edge_table.ensure_shadow) that swaps the 07-05 name to ANY target - the cut, the
full 11-school table or the re-materialised 07-05 copy - and the target is recorded (plain b0 refuses that env:
STOP EDGE_ENV); (b) the October comparison is reported (report_chemmath_m.json edge_proof, the run report's
vs_october) instead of STOP B0_NOT_OCTOBER, and every product is frozen, so the proof can compare them under its
own rules (ORDER_ONLY, the roster channel on the full table). J1a / J1b (mode m) and plain b0 are unchanged.
Out of scope (since 2026-10-15): F20, the new-star departure ledger and departure frames.

STAGE_OUT: report_chemmath_m.json (OK) or stop_report_chemmath_m.json (STOP; code + ids),
report_gdose_chemmath.json, report_coverage_chemmath.json / stop_report_coverage_chemmath.json,
chemmath_m_run_report.json (full detail, paths), RESULT.txt (OK | STOP <code>). Exit 0 OK, 3 STOP.
Scratch (builder run dirs, shadows): --scratch, else $SAR_OUT_ROOT, else $WORK/tmp/chemmath_m_<out>_<time>;
it must be empty. The DuckDB-heavy builders cap their own memory and spill under it: put it on the large
root volume.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import csv
import datetime
import io
import json
import os
import pathlib
import string
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
_MARK = pathlib.Path("pipeline/frames/cal2026-10/stage.py")


def _find_repo() -> pathlib.Path:
    """The checkout this file sits in, else $REPO_DIR (a stage runs a copy under $WORK)."""
    cands = []
    if len(HERE.parents) >= 3 and (HERE.parents[2] / _MARK).is_file():      # <repo>/pipeline/aws/r1
        cands.append(HERE.parents[2])
    env = os.environ.get("REPO_DIR", "").strip()
    if env:
        cands.append(pathlib.Path(env))
    for c in cands:
        if (c / _MARK).is_file():
            return c.resolve()
    raise SystemExit("chemmath_m: cannot find the repository (run it from the checkout or set $REPO_DIR)")


REPO = _find_repo()
for _p in (REPO / "pipeline" / "aws" / "r1", REPO / "pipeline" / "frames" / "cal2026-10"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))

import stage                                                             # noqa: E402
import run_cal_frames_chemmath as rcf                                    # noqa: E402
import inpost_filter as ipf                                              # noqa: E402
import network_freeze as nf                                              # noqa: E402
import missing_persons as mp                                             # noqa: E402
import dose_chemmath as dc                                               # noqa: E402
import edge_table as et                                                  # noqa: E402
from pipeline.lib import r1_config as r1c                                # noqa: E402
from tools.content_equal import content_equal                            # noqa: E402

fs08 = stage.fs08
sha = fs08.sha

HOSTS = ("ec2-r1-test", "ec2-r1")
FIELDS = stage.FIELDS_GOLD
ALL_FIELDS = stage.FIELDS
MODES = ("m", "b0")
VARIANTS = ("fnfix", "incfel")
EVENT_NAME = "events_{f}_cal2026-10.csv"
ROSTER_NAME = {"fnfix": "roster_gold_{f}_r1.parquet", "incfel": "roster_gold_{f}_r1_incfel.parquet"}
ROSTER_COLS = ("dept_key", "school", "author_id", "year_start", "year_end")
PMAP_REL = "multidisc_v2_2026-08-04/data/person_map_multidisc_seeds.parquet"
SUP_REL = f"{stage.GOLD}/data/edges_supplement_fnfix.jsonl"
FROZEN_MANIFESTS = ("data/cal2026-08-28/MANIFEST.sha256", "data/MANIFEST.sha256")
ECON_UNUSED = "unused: the chemistry/mathematics M driver skips the econ shadow subtree"
REPORT = "chemmath_m"
EXIT_STOP = 3
M_ONLY = ("events_dir", "roster_chemistry", "roster_math_stats", "roster_variant", "stars_excluded_base",
          "event_tables_all", "calls")
B0_ONLY = ("october_ref", "edge_proof")
EDGE_PROOF_RULE = ("b0 --edge-proof (S10 reverse proof driver, J0-MEAS.3j): the edge-table shadow env is required "
                   "and its target recorded; the October comparison is reported, never a STOP; every product is frozen")
GDOSE_KEYS = ("n", "missing_side", "max_abs_diff", "share_exact_1e-9", "share_le_0.01")
GDOSE_RULE = "G-DOSE advisory of the union builder, copied per field; never gated (J0-MEAS.3h)"
#: October's y-step report directory (data/cal2026-10/yrebuild_chemmath/), published under STAGE_OUT (M review #8)
YREBUILD_DIR = "yrebuild_chemmath"


class Stop(RuntimeError):
    """A STOP of this driver: a code and ids (event ids, author ids or (pid, event) pairs)."""

    def __init__(self, code: str, ids=(), detail: str = ""):
        self.code = code
        self.ids = sorted((list(i) if isinstance(i, tuple) else i) for i in ids)
        self.detail = detail
        super().__init__(f"STOP {code}: {detail} {self.ids[:20]}")


def log(msg: str) -> None:
    print(f"[chemmath_m] {msg}", flush=True)


def write_json(p: pathlib.Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True, default=str) + "\n",
                 encoding="utf-8")


def read_csv(p) -> list[dict]:
    return list(csv.DictReader(io.StringIO(pathlib.Path(p).read_bytes().decode("utf-8"))))


# ---------------------------------------------------------------------------------------------
# config, env, inputs
# ---------------------------------------------------------------------------------------------

def load_config(path, repo: pathlib.Path = None):
    """pipeline.lib.r1_config.load; any ConfigStop (missing / unsigned / unknown switch, a ruling, a pin)
    becomes STOP CONFIG_<code>."""
    try:
        return r1c.load(path, repo=repo or REPO)
    except r1c.ConfigStop as e:
        raise Stop(f"CONFIG_{e.code}", detail=str(e)) from None


def check_mode(cfg, mode: str) -> None:
    want = {"m": "M", "b0": "B0"}[mode]
    if cfg.name != want:
        raise Stop("CONFIG_MODE", detail=f"--mode {mode} needs the {want} config, got {cfg.name}")


def edge_env(cfg, *, proof: bool = False) -> dict:
    """N2: the chemmath_edges switch against this process's env. On = SAR_PATHS_CONFIG is the edge-table
    shadow's paths file (manifest beside it, 07-05 name -> the 11-school table, derived_root inside the
    shadow) and $SAR_SSD_ROOT is unset; off = SAR_PATHS_CONFIG is not such a file. proof (b0 --edge-proof, the
    S10 reverse proof): the switch is off AND SAR_PATHS_CONFIG must be such a shadow, swapping the 07-05 name to
    any target (recorded). Returns the record, with real_derived = the real <ssd_root>/derived the B0 render uses."""
    val = cfg.switch("chemmath_edges")
    pc = os.environ.get("SAR_PATHS_CONFIG", "").strip()
    mf_p = pathlib.Path(pc).parent / et.MANIFEST_NAME if pc else None
    is_shadow = bool(pc) and pathlib.Path(pc).name == et.PATHS_NAME and mf_p.is_file()
    rec = {"switch": val, "paths_config": pc or None, "edge_shadow": is_shadow}
    if proof:
        if val != et.TABLE_0705:
            raise Stop("EDGE_ENV", detail="--edge-proof is a switch-off run: chemmath_edges must be off (B0)")
        rec.update(_edge_shadow(mf_p, is_shadow, target=None,
                                not_shadow="--edge-proof needs SAR_PATHS_CONFIG = an edge-table shadow paths file "
                                           "(edge_table.ensure_shadow), exported before this process starts"))
        rec["edge_proof"] = True
        return rec
    if val == et.TABLE_0705:
        if is_shadow:
            raise Stop("EDGE_ENV", detail="chemmath_edges is off but SAR_PATHS_CONFIG is the edge-table shadow")
        rec["real_derived"] = str(stage.derived_root())
        return rec
    if val != et.TABLE_11:
        raise Stop("EDGE_ENV", detail=f"unknown chemmath_edges value {val!r}")
    rec.update(_edge_shadow(mf_p, is_shadow, target=et.TABLE_11,
                            not_shadow="chemmath_edges is on but SAR_PATHS_CONFIG is not the edge-table shadow "
                                       "paths file (the stage cmd must export it from edge_table.py shadow)"))
    return rec


def _edge_shadow(mf_p, is_shadow: bool, *, target, not_shadow: str) -> dict:
    """The edge-table shadow this process runs under: $SAR_SSD_ROOT unset, SAR_PATHS_CONFIG the shadow's paths
    file, only the 07-05 name swapped (to `target`'s name, or to any table when target is None) and derived_root()
    inside the shadow. Returns real_derived, shadow_derived and target."""
    if os.environ.get("SAR_SSD_ROOT", "").strip():
        raise Stop("EDGE_ENV", detail="$SAR_SSD_ROOT is set: it would override the edge-table shadow")
    if not is_shadow:
        raise Stop("EDGE_ENV", detail=not_shadow)
    m = json.loads(mf_p.read_text(encoding="utf-8"))
    if m.get("swapped_name") != et.TABLE_0705 or (
            target is not None and pathlib.Path(m.get("target", "")).name != target):
        raise Stop("EDGE_ENV", detail=f"the edge-table shadow swaps {m.get('swapped_name')} -> {m.get('target')}")
    shadow_derived = pathlib.Path(m["shadow_ssd_root"]) / "derived"
    if pathlib.Path(stage.derived_root()).resolve() != shadow_derived.resolve():
        raise Stop("EDGE_ENV", detail=f"derived_root() is {stage.derived_root()}, not the shadow {shadow_derived}")
    return {"real_derived": str(pathlib.Path(m["real_ssd_root"]) / "derived"), "shadow_derived": str(shadow_derived),
            "target": m["target"]}


def manifest_pin(repo: pathlib.Path, rel: str) -> str | None:
    for mf in FROZEN_MANIFESTS:
        p = repo / mf
        if p.is_file():
            for ln in p.read_text(encoding="utf-8").splitlines():
                h, _, r = ln.partition("  ")
                if r == rel:
                    return h
    return None


def pin_check(cfg, repo: pathlib.Path, files: dict) -> dict:
    """Every input file inside the repository must be pinned (the run config's pins, else a frozen data
    MANIFEST line) with an equal sha256; files outside it (earlier stages' outputs under $WORK) are
    recorded with their sha256."""
    repo = pathlib.Path(repo).resolve()
    pins = (cfg.raw.get("pins") or {})
    out = {}
    for name, p in sorted(files.items()):
        p = pathlib.Path(p).resolve()
        if not p.is_file():
            raise Stop("MISSING_INPUT", detail=f"{name}: {p}")
        rec = {"sha256": sha(p)}
        if p.is_relative_to(repo):
            rel = p.relative_to(repo).as_posix()
            want, src = pins.get(rel), "config"
            if want is None:
                want, src = manifest_pin(repo, rel), "manifest"
            if want is None:
                raise Stop("UNPINNED_INPUT", detail=rel)
            if want != rec["sha256"]:
                raise Stop("PIN_MISMATCH", detail=rel)
            rec.update(rel=rel, pinned_by=src)
        else:
            rec["outside_repo"] = str(p)
        out[name] = rec
    return out


def check_rosters(rosters: dict, variant: str) -> dict:
    """The variant's basenames (fnfix roster_gold_<f>_r1.parquet, incfel roster_gold_<f>_r1_incfel.parquet)
    and the 5 gold columns."""
    import pyarrow.parquet as pq                                         # noqa: PLC0415
    if variant not in VARIANTS:
        raise Stop("ROSTER_VARIANT", detail=f"variant {variant!r}")
    if set(rosters) != set(FIELDS):
        raise Stop("ROSTER_VARIANT", detail=f"rosters for {sorted(rosters)}")
    out = {}
    for f, p in sorted(rosters.items()):
        p = pathlib.Path(p)
        want = ROSTER_NAME[variant].format(f=f)
        if p.name != want:
            raise Stop("ROSTER_VARIANT", [f], f"--roster-variant {variant} reads {want}, got {p.name}")
        if not p.is_file():
            raise Stop("MISSING_INPUT", [f], str(p))
        cols = pq.read_schema(p).names
        if sorted(cols) != sorted(ROSTER_COLS):
            raise Stop("ROSTER_SHAPE", [f], f"{p.name} columns {cols}, want {list(ROSTER_COLS)}")
        out[f] = {"name": p.name, "sha256": sha(p), "variant": variant}
    return out


def check_tables(tables: dict) -> dict:
    """Header line equal to the 08-28 table's; chem/maths rows of their own field with an integer
    arrival_corrected."""
    out = {}
    for f in ALL_FIELDS:
        p = pathlib.Path(tables[f])
        if not p.is_file():
            raise Stop("MISSING_INPUT", [f], str(p))
        ref = stage.CAL08 / f"events_{f}_cal.csv"
        if p.read_bytes().split(b"\n", 1)[0] != ref.read_bytes().split(b"\n", 1)[0]:
            raise Stop("EVENT_HEADER", [f], f"{p.name} header differs from the 08-28 table")
        rows = read_csv(p)
        if f in FIELDS:
            bad = [f"{r['author_id']}:{r['school']}" for r in rows
                   if r.get("field") != f or not str(r.get("arrival_corrected", "")).strip().isdigit()]
            if bad:
                raise Stop("EVENT_ARRIVAL", bad, f"{f}: rows of another field or without an integer arrival")
        out[f] = {"n_events": len(rows), "sha256": sha(p)}
    return out


def t1_of(table) -> dict:
    """event id (author:school) -> arrival_corrected - 1 (prodlib's t_minus_1 for these fields)."""
    return {f"{r['author_id']}:{r['school']}": int(r["arrival_corrected"]) - 1 for r in read_csv(table)}


def read_calls(calls_dir) -> dict:
    """The F8 calls stage: RESULT.txt OK, dose_excludes.csv / adds.csv (person_id, work_id, source) and
    rank_adds.json ({main id: [alias ids]})."""
    d = pathlib.Path(calls_dir)
    res = (d / "RESULT.txt").read_text(encoding="utf-8").strip() if (d / "RESULT.txt").is_file() else ""
    if res != "OK":
        raise Stop("CALLS_NOT_OK", detail=f"{d}/RESULT.txt says {res!r}")

    def pairs(name):
        return frozenset((r["person_id"], r["work_id"]) for r in read_csv(d / name))
    rank_adds = json.loads((d / "rank_adds.json").read_text(encoding="utf-8"))
    return {"dose_excludes": pairs("dose_excludes.csv"), "adds": pairs("adds.csv"), "rank_adds": rank_adds}


def drop_stars(cfg) -> set:
    """person ids with verdict DROP in the config's signed flips list (pinned by the config loader)."""
    tok = cfg.raw["signed"]["flips"]
    rows = json.loads((cfg.repo / tok[len("repo:"):]).read_text(encoding="utf-8"))["rows"]
    return {r["person_id"] for r in rows if r.get("verdict") == "DROP"}


def m_stars_excluded(base, tables: dict, drop: set, rank_adds: dict, out) -> dict:
    """M list = base - (drop - M event stars) + M event stars of the three fields + their rank_adds aliases,
    sorted, one author_id column (the 08-28 file's shape). Returns the record (added / removed ids)."""
    import pyarrow as pa                                                 # noqa: PLC0415
    import pyarrow.parquet as pq                                         # noqa: PLC0415
    base_ids = set(pq.read_table(base).column("author_id").to_pylist())
    stars = stage.event_stars({f: pathlib.Path(tables[f]) for f in ALL_FIELDS})
    m_stars = {a for v in stars.values() for a in v}
    aliases = {al for s in m_stars for al in (rank_adds.get(s) or ())}
    returned = (set(drop) - m_stars) & base_ids
    final = (base_ids - returned) | m_stars | aliases
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"author_id": pa.array(sorted(final), pa.string())}), out)
    return {"base": len(base_ids), "base_sha256": sha(base), "m_event_stars": len(m_stars),
            "alias_ids": sorted(aliases - m_stars), "added": sorted(final - base_ids),
            "removed": sorted(base_ids - final), "drop_stars_that_are_m_event_stars": sorted(set(drop) & m_stars),
            "total": len(final), "sha256": sha(out),
            "rule": "08-28 list - DROP stars that are not M event stars + every M event star of the three "
                    "fields + their rank_adds alias ids (ruling pending)"}


def check_stars_excluded(mlist, tables: dict) -> int:
    """Every chemistry / mathematics event star is in the stars_excluded list (stage.build_shadow asserts
    the same; this names the stars as a STOP before any work)."""
    import pyarrow.parquet as pq                                         # noqa: PLC0415
    have = set(pq.read_table(mlist).column("author_id").to_pylist())
    stars = stage.event_stars({f: pathlib.Path(tables[f]) for f in FIELDS})
    outside = sorted(a for f in FIELDS for a in stars[f] if a not in have)
    if outside:
        raise Stop("STAR_NOT_EXCLUDED", outside, "event stars outside the stars_excluded list")
    return len(have)


# ---------------------------------------------------------------------------------------------
# shadow
# ---------------------------------------------------------------------------------------------

@contextlib.contextmanager
def econ_subtree_skipped(note: dict):
    """stage.build_shadow without its econ subtree (the chem/maths configs read none of it)."""
    orig = stage._econ_subtree

    def skip(root, sh, v2, tables, stars, rec, *, stage_cfg):            # noqa: ARG001
        rec["econ_subtree"] = "skipped (chemistry/mathematics M driver)"
        note["econ_subtree_skipped"] = True
    stage._econ_subtree = skip
    try:
        yield
    finally:
        stage._econ_subtree = orig


def make_shadow_b0(root: pathlib.Path, stage_cfg: dict):
    """October: the B0 stage section, the October tables, the 08-28 list and the frozen rosters."""
    return stage.build_shadow(root / "shadow_b0", "cal2026-10", stage_cfg=stage_cfg)


def m_stage_cfg(events_dir) -> dict:
    """build_shadow's stage section for M: events_root (unused with explicit tables, required by the
    function) and the econ keys, which name nothing because the econ subtree is skipped."""
    return {"events_root": pathlib.Path(events_dir), "restake_csv": ECON_UNUSED, "restake_label": ECON_UNUSED,
            "names_csvs": [ECON_UNUSED]}


def make_shadow_m(root: pathlib.Path, tables: dict, events_dir, mlist, rosters: dict, extra=()):
    note: dict = {}
    with econ_subtree_skipped(note):
        sh, rec = stage.build_shadow(root / "shadow_m", {f: pathlib.Path(tables[f]) for f in ALL_FIELDS},
                                     stage_cfg=m_stage_cfg(events_dir), stars_excluded=pathlib.Path(mlist),
                                     rosters={f: pathlib.Path(p) for f, p in rosters.items()})
    rec.update(note)
    if extra:
        base = sh.path(SUP_REL).read_bytes()
        parts = [base] + [pathlib.Path(p).read_bytes() for p in extra]
        for b in parts:
            if b and not b.endswith(b"\n"):
                raise Stop("SUPPLEMENT_SHAPE", detail="a supplement part does not end with a newline")
        sh.write(SUP_REL, b"".join(parts), "r1:edges_supplement_fnfix ⧺ " + " ⧺ ".join(pathlib.Path(p).name for p in extra))
        rec["supplement_extra"] = [{"name": pathlib.Path(p).name, "sha256": sha(p)} for p in extra]
    return sh, rec


# ---------------------------------------------------------------------------------------------
# prodlib, D2, V3-NET
# ---------------------------------------------------------------------------------------------

def render_b0(field: str, shadow_root, run_dir, real_derived) -> dict:
    """stage.render_config with ${DERIVED} = the REAL derived root (what B0 renders)."""
    tpl = (stage.CONFIGS / f"{field}.json").read_text(encoding="utf-8")
    vals = {"DERIVED": str(real_derived), "LEGACY_V2": str(stage.legacy_v2()), "SHADOW": str(shadow_root),
            "RUN_DIR": str(run_dir)}
    return json.loads(string.Template(tpl).substitute(vals))


def render_diff(m: dict, b0: dict, m_derived, real_derived) -> dict:
    """The keys where the M render differs from the B0 render, and whether every difference is only the
    derived root (a snapshot glob, or the template's documentation note that names ${DERIVED})."""
    keys = sorted(k for k in set(m) | set(b0) if m.get(k) != b0.get(k))
    snap = []
    md, rd = str(m_derived), str(real_derived)
    notes = {k for k in keys if k != "snapshot" and isinstance(m.get(k), str) and isinstance(b0.get(k), str)
             and k.startswith("_") and m[k].replace(md, rd) == b0[k]}
    ok = set(keys) - notes <= {"snapshot"}
    if "snapshot" in keys:
        ms, bs = m.get("snapshot") or {}, b0.get("snapshot") or {}
        for k in sorted(set(ms) | set(bs)):
            a, b = ms.get(k), bs.get(k)
            if a == b:
                continue
            snap.append(k)
            if not (isinstance(a, str) and isinstance(b, str) and a.startswith(md) and b.startswith(rd)
                    and a[len(md):] == b[len(rd):]):
                ok = False
    return {"keys": keys, "snapshot_keys": snap, "only_snapshot_prefix": ok}


def describe_csv(path) -> dict:
    """Size, line ends and field counts of a CSV, with its header line only (no data rows)."""
    p = pathlib.Path(path)
    if not p.is_file():
        return {"name": p.name, "missing": True}
    b = p.read_bytes()
    lines = b.split(b"\n")
    if lines and lines[-1] == b"":
        lines = lines[:-1]
    crlf = sum(1 for ln in lines if ln.endswith(b"\r"))
    counts = sorted({len(next(csv.reader([ln.decode("utf-8", "replace").rstrip("\r")]))) for ln in lines if ln})
    return {"name": p.name, "bytes": len(b), "lines": len(lines), "crlf": crlf, "lf_only": len(lines) - crlf,
            "field_counts": counts, "header": lines[0].decode("utf-8", "replace").rstrip("\r") if lines else ""}


def _csv_paths(obj) -> list:
    """Every string value ending in .csv inside a rendered prodlib config."""
    if isinstance(obj, dict):
        return [p for v in obj.values() for p in _csv_paths(v)]
    if isinstance(obj, list):
        return [p for v in obj for p in _csv_paths(v)]
    return [obj] if isinstance(obj, str) and obj.endswith(".csv") else []


def run_prodlib_m(field: str, root: pathlib.Path, shadow_root: pathlib.Path, tag: str, rec: dict, *,
                  real_derived, n_events: int):
    """stage.render_config + stage.run_prodlib; the October BYTE_EQUAL-to-08-28 premise is replaced by:
    the key diff against the B0 render is at most the snapshot glob prefix, no econ shadow path is read,
    and every event of the table reaches prodlib."""
    mirror = root / f"{tag}_prodlib_{field}"
    run_dir = mirror / "runs" / field
    cfg = stage.render_config(field, shadow_root, run_dir)
    rec["config_diff_vs_b0"] = d = render_diff(cfg, render_b0(field, shadow_root, run_dir, real_derived),
                                               stage.derived_root(), real_derived)
    if not d["only_snapshot_prefix"]:
        raise Stop("PRODLIB_CONFIG", [field], f"rendered config differs from the B0 render in {d['keys']}")
    if "/cal2026-10/econ" in json.dumps(cfg):
        raise Stop("PRODLIB_CONFIG", [field], "the chem/maths config names the (skipped) econ shadow subtree")
    try:
        out = stage.run_prodlib(field, mirror, cfg, rec)
    except Exception:
        # j1a-17: a builder error (e.g. the CSV sniffer) leaves no trace of its inputs; log every CSV the config names
        for csv_path in _csv_paths(cfg):
            log(f"[{field}] prodlib input " + json.dumps(describe_csv(csv_path), sort_keys=True))
        raise
    except SystemExit as e:
        # build_frame.py runs IN this process (runpy): its own STOP is a sys.exit, which ended the driver with that
        # code and no RESULT.txt or stop report (S10 t-big-04: rc=3, nothing to read). stage.run_prodlib holds the
        # builder's stdout in a buffer, so its message is lost; the exit code and the field are kept.
        raise Stop("PRODLIB_EXIT", [field], f"build_frame.py exited with {e.code!r} (an in-process prodlib STOP)") from None
    br = rec["prodlib"][field]["build_report"]
    n = (br.get("events_diag") or {}).get("n_events")
    rec["events_in_table"], rec["events_in_prodlib"] = n_events, n
    rec["events_dropped_zero_pairs"] = (br.get("export") or {}).get("dropped_event_ids")
    if n != n_events:
        raise Stop("PRODLIB_EVENTS", [field], f"prodlib read {n} events, the table holds {n_events}")
    rec["frame_sha256"], rec["frame_rows"] = sha(out), out.read_bytes().count(b"\n") - 1
    return out, cfg


def _walk(frame_in, frame_out, removed) -> dict:
    return fs08.strict_removal_walk(pathlib.Path(frame_in), pathlib.Path(frame_out),
                                    lambda c: (c[0], c[3]) in removed)


def d2_step(field: str, frame, roster, sh, root: pathlib.Path, tag: str) -> dict:
    """D2 with ONE roster file (the one the shadow links for prodlib's pool and the dept channel)."""
    link = sh.path(f"{stage.GOLD}/data/fnfix/roster_gold_{field}.parquet")
    if sha(roster) != sha(link):
        raise Stop("ROSTER_NOT_ONE_FILE", [field], "the in-post spells and the shadow's roster link differ")
    spells, sources = ipf.spells_from_roster(pathlib.Path(roster), None, identity=True)
    ipd = root / f"{tag}_inpost_{field}"
    out = ipd / "frame_inpost.csv"
    rep = ipf.run(pathlib.Path(frame), spells, sources, out, ipd / "inpost_report.json")
    cls = ipf.classify(pathlib.Path(frame), spells)["cls"]
    removed = {k for k, c in cls.items() if c != "kept"}
    w = _walk(frame, out, removed)
    if not (w["closed"] and w["rows_removed"] == sum(v for k, v in rep["rows_by_class"].items() if k != "kept")):
        raise Stop("D2_ACCOUNTING", [field], f"{w}")
    return {"input": pathlib.Path(frame), "output": out, "report": rep, "cls": cls, "walk": w}


def net_step(run_cfg, field: str, frame, prod_cfg: dict, table, root: pathlib.Path, tag: str):
    """V3-NET on the 16-column frame (before the union rung)."""
    d = root / f"{tag}_v3net_{field}"
    try:
        out, rep = nf.apply(run_cfg, frame, d / "frame_v3net.csv", graph=nf.graph_from_prodlib_config(prod_cfg),
                            event_table=table, report_path=d / "v3net_report.json")
    except nf.NetworkFreezeStop as e:
        raise Stop(f"V3NET_{e.code}", e.ids, str(e)) from None
    if rep is None:
        return pathlib.Path(frame), None
    w = _walk(frame, out, {tuple(x) for x in rep["removed_relations"]})
    if not (w["closed"] and w["rows_removed"] == rep["rows_dropped"]):
        raise Stop("V3NET_ACCOUNTING", [field], f"{w}")
    rep["walk"] = w
    return out, rep


# ---------------------------------------------------------------------------------------------
# the chain
# ---------------------------------------------------------------------------------------------

def run_chain_m(field: str, root: pathlib.Path, sh, tag: str, network_frame: pathlib.Path, origin: str,
                post_union=None) -> dict:
    """run_cal_frames_chemmath.run_chain line for line, plus `post_union(field, sh, union_stage)` after the
    union outputs are installed and before p1-gold (its return value is kept as stages['post_union'])."""
    shadow_root = sh.root.parent
    sh.install(rcf.prodlib_rel(field), network_frame, origin)
    stages: dict[str, dict] = {}
    st = rcf.run_stage("union-gold", root / f"{tag}_union_{field}", ("--field", field), shadow_root)
    stages["union"] = st
    for name in (f"analysis_frame_{field}_2026-08-10.csv", "relationships.csv",
                 "build_report.json", "funnel.json"):
        sh.install(f"{rcf.GOLD}/data/fnfix/union_frame_{field}/{name}",
                   st["run_dir"] / f"data/fnfix/union_frame_{field}/{name}",
                   f"{tag}-stage:union-gold {field}")
    if post_union is not None:
        stages["post_union"] = post_union(field, sh, st)
    st = rcf.run_stage("p1-gold", root / f"{tag}_p1_{field}", ("--field", field), shadow_root)
    stages["p1"] = st
    sh.install(f"{rcf.GOLD}/data/fnfix/analysis_frame_{field}_new_gold_2026-08-10.csv",
               st["run_dir"] / f"data/fnfix/analysis_frame_{field}_new_gold_2026-08-10.csv",
               f"{tag}-stage:p1-gold {field}")
    st = rcf.run_stage("p2-gold", root / f"{tag}_p2_{field}", ("--field", field, "--panel3", "full"),
                       shadow_root)
    stages["p2"] = st
    for name in ("becoming_none.csv", "pairs_none.parquet", "pairs_slim_none.parquet"):
        sh.install(f"{rcf.GOLD}/data/fnfix/panels23_{field}_gold/{name}",
                   st["run_dir"] / f"data/fnfix/panels23_{field}_gold/{name}",
                   f"{tag}-stage:p2-gold {field}")
    stages["slim"] = rcf.run_make_slim(field, sh.path(f"{rcf.GOLD}/data/fnfix/panels23_{field}_gold/pairs_none.parquet"),
                                       root / f"{tag}_slim_{field}")
    return stages


def make_dose_hook(ctx: dict, field: str, prod_cfg: dict, F: dict):
    """The S6 post_union hook: dose_chemmath.apply (delta) on the union frame, installed over it."""
    sh, table, dose = ctx["sh"], ctx["tables"][field], ctx["dose"]
    ri = dc.RuleInputs(edges_glob=prod_cfg["snapshot"]["edges_glob"], works_glob=prod_cfg["snapshot"]["works_glob"],
                       supplement_jsonl=str(sh.path(SUP_REL)), person_map=str(sh.path(PMAP_REL)),
                       union_stars=frozenset(stage.event_stars({field: pathlib.Path(table)})[field]))
    t1 = t1_of(table)

    def hook(f, sh_, st):
        rel = f"{stage.GOLD}/data/fnfix/union_frame_{f}/analysis_frame_{f}_2026-08-10.csv"
        src = st["run_dir"] / f"data/fnfix/union_frame_{f}/analysis_frame_{f}_2026-08-10.csv"
        out = ctx["scratch"] / f"{ctx['tag']}_dose_{f}" / "union_frame_dose.csv"
        try:
            rep = dc.apply(src, out, rule_inputs=ri, excludes=dose["excludes"], addbacks=dose["addbacks"],
                           t1_by_event=t1, mode="delta")
        except dc.DoseChemmathStop as e:
            raise Stop(f"DOSE_{e.code}", e.ids, str(e)) from None
        sh_.install(rel, out, f"{ctx['tag']}-stage:r1 S6 dose_chemmath (delta) {f}")
        F["dose"] = rep
        return {"dose_frame": str(out), "dose_frame_sha256": sha(out), "union_frame_sha256": sha(src)}
    return hook


# ---------------------------------------------------------------------------------------------
# reports and comparisons
# ---------------------------------------------------------------------------------------------

def gdose_advisory(union_report) -> dict:
    """J0-MEAS.3h: the union build report's G_DOSE_advisory counts, copied; never gated."""
    g = json.loads(pathlib.Path(union_report).read_text(encoding="utf-8")).get("G_DOSE_advisory") or {}
    return {k: g.get(k) for k in GDOSE_KEYS}


def compare_products(field: str, prod, ref) -> dict:
    """The products (dict name -> path, or a frames_<field> dir) against <ref>/data/cal2026-10/frames_<field>/
    (anchored in its MANIFEST.sha256) under October's acceptance rules."""
    f = field
    fr = pathlib.Path(ref) / "data" / "cal2026-10" / f"frames_{f}"
    if not isinstance(prod, dict):
        prod = {name.format(f=f): pathlib.Path(prod) / name.format(f=f) for name in rcf.PRODUCTS}
    for name in rcf.PRODUCTS:
        n = name.format(f=f)
        try:
            rcf.anchor_frozen(fr / n, fr / "MANIFEST.sha256", f"data/cal2026-10/frames_{f}/{n}")
        except (AssertionError, OSError) as e:
            raise Stop("REF_ANCHOR", [f], f"{n}: {e}") from None
    V: dict = {"relationships": "BYTE_EQUAL" if sha(prod[f"relationships_{f}.csv"]) == sha(fr / f"relationships_{f}.csv") else "NOT_EQUAL",
               "p2_becoming": "BYTE_EQUAL" if sha(prod[f"p2_becoming_{f}.csv"]) == sha(fr / f"p2_becoming_{f}.csv") else "NOT_EQUAL",
               "union_build_report": rcf.json_equal_modulo_paths(prod[f"union_build_report_{f}.json"],
                                                                 fr / f"union_build_report_{f}.json"),
               "p1_frame": rcf.h1_characterise(fr / f"p1_frame_{f}.csv", prod[f"p1_frame_{f}.csv"])}
    for name in (f"pairs_none_{f}.parquet", f"p3_slim_{f}.parquet", f"p3_slim_ev_{f}.parquet"):
        r = content_equal(prod[name], fr / name)
        V[name] = {"content": "EQUAL" if r.equal else "NOT_EQUAL", "rows": (r.rows_a, r.rows_b),
                   "schema_equal": r.schema_equal}
    bad = [k for k, v in V.items()
           if v == "NOT_EQUAL" or (isinstance(v, dict) and (v.get("ok") is False or v.get("content") == "NOT_EQUAL"
                                                            or v.get("equal_modulo_paths_and_h1_advisory") is False))]
    V["all_equal"] = not bad
    V["differ"] = bad
    return V


def apply_agg_allowlist(res: dict, allow: dict) -> dict:
    """W2-2 (2026-10-16): October's own chemistry agg_missing persons, listed by id in the run
    config's agg_missing_allow.<field>.persons, leave the stop list (fields.<f>.missing.allowlisted_persons);
    every other missing person stays in missing.persons, so coverage_gate still stops on it. An allowlisted id
    that is not missing is reported (allowlisted_not_missing), never a stop. Ids only (P_A...)."""
    out = {**res, "fields": {}}
    for f, v in (res.get("fields") or {}).items():
        ok = {mp.norm_id(x) for x in ((allow or {}).get(f) or {}).get("persons", [])}
        missing = [mp.norm_id(x) for x in v["missing"]["persons"]]
        out["fields"][f] = {**v, "missing": {**v["missing"], "persons": sorted(x for x in missing if x not in ok),
                                             "allowlisted_persons": sorted(x for x in missing if x in ok)},
                            "allowlisted_not_missing": sorted(ok - set(missing))}
    return out


def coverage_step(ctx: dict, fields, out: pathlib.Path, R: dict) -> None:
    """N3: missing_persons on each field's p1-gold dir, one report (coverage_chemmath) in the agg_missing
    switch's mode; a STOP code stops the run with the person ids. The run config's agg_missing_allow (W2-2:
    October's own chemistry agg_missing persons) is applied first; a config without it allows nobody."""
    mode = ctx["cfg"].switch("agg_missing")
    res = {"fields": {}}
    for f in fields:
        res["fields"].update(mp.chemmath_dirs([ctx["p1_dirs"][f]], str(ctx["sh"].path(PMAP_REL)),
                                              ctx["globs"][f][0], ctx["globs"][f][1])["fields"])
    res = apply_agg_allowlist(res, ctx["cfg"].raw.get("agg_missing_allow") or {})
    code, ids = mp.coverage_gate(res, mode, 1)
    rc = mp.write_report(out, "coverage_chemmath", res, mode=mode, round=1)
    R["coverage"] = {"mode": mode, "code": code, "n_persons": len(ids),
                     "fields": {f: v["missing"]["rows"] for f, v in res["fields"].items()},
                     "cross_check": {f: v["cross_check"]["status"] for f, v in res["fields"].items()},
                     "allowlisted": {f: v["missing"]["allowlisted_persons"] for f, v in res["fields"].items()}}
    if rc == mp.EXIT_STOP:
        raise Stop(code, ids, "chem/maths coverage (person-years with papers and no aggregate)")


# ---------------------------------------------------------------------------------------------
# setup per mode, the field loop
# ---------------------------------------------------------------------------------------------

def setup_b0(cfg, a, scratch: pathlib.Path, R: dict) -> dict:
    stage_cfg = cfg.resolved("stage")
    tables, _tag = stage.event_tables("cal2026-10", root=pathlib.Path(stage.stage_value(stage_cfg, "events_root")))
    sh, rec = make_shadow_b0(scratch, stage_cfg)
    R["shadow"] = {"events": rec.get("events"), "tables": rec.get("tables"), "entries": len(sh.entries)}
    return {"mode": "b0", "tag": "b0", "cfg": cfg, "sh": sh, "scratch": scratch, "tables": tables,
            "rosters": {f: stage.RAW / f"roster_gold_{f}.parquet" for f in FIELDS}, "net": False, "dose": None,
            "real_derived": pathlib.Path(R["edges"]["real_derived"]), "p1_dirs": {}, "globs": {}}


def setup_m(cfg, a, scratch: pathlib.Path, R: dict) -> dict:
    if not cfg.is_on("rosters"):
        raise Stop("SWITCH_ROSTERS_OFF", detail="--mode m reads the R1 rosters; the config's rosters switch is off")
    rosters = {"chemistry": pathlib.Path(a.roster_chemistry), "math_stats": pathlib.Path(a.roster_math_stats)}
    R["rosters"] = check_rosters(rosters, a.roster_variant)
    events_dir, all_dir = pathlib.Path(a.events_dir), pathlib.Path(a.event_tables_all)
    tables = {"econ": all_dir / EVENT_NAME.format(f="econ")}
    for f in FIELDS:
        tables[f] = events_dir / EVENT_NAME.format(f=f)
        twin = all_dir / EVENT_NAME.format(f=f)
        if twin.is_file() and tables[f].is_file() and twin.read_bytes() != tables[f].read_bytes():
            raise Stop("EVENT_TABLES_DISAGREE", [f], "--events-dir and --event-tables-all hold different tables")
    R["tables"] = check_tables(tables)
    base = pathlib.Path(a.stars_excluded_base)
    files = {"roster_chemistry": rosters["chemistry"], "roster_math_stats": rosters["math_stats"],
             "stars_excluded_base": base, **{f"events_{f}": tables[f] for f in ALL_FIELDS}}
    for i, p in enumerate(a.supplement_extra or ()):
        files[f"supplement_extra_{i}"] = pathlib.Path(p)
    R["pins"] = pin_check(cfg, REPO, files)
    calls = read_calls(a.calls)
    R["calls"] = {"dose_excludes": len(calls["dose_excludes"]), "adds": len(calls["adds"]),
                  "rank_adds": len(calls["rank_adds"])}
    mlist = scratch / "stars_excluded_r1.parquet"
    R["stars_excluded"] = m_stars_excluded(base, tables, drop_stars(cfg), calls["rank_adds"], mlist)
    check_stars_excluded(mlist, tables)
    sh, rec = make_shadow_m(scratch, tables, events_dir, mlist, rosters, a.supplement_extra or ())
    R["shadow"] = {"events": rec.get("events"), "tables": rec.get("tables"), "entries": len(sh.entries),
                   "rosters": rec.get("rosters"), "stars_excluded_chemmath": rec.get("stars_excluded_chemmath"),
                   "econ_subtree_skipped": rec.get("econ_subtree_skipped", False),
                   "supplement_extra": rec.get("supplement_extra")}
    ex_on, ab_on = cfg.is_on("dose_excludes"), cfg.is_on("add_backs")
    dose = None
    if ex_on or ab_on:
        if cfg.switch("dose_mode") != r1c.SWITCHES["dose_mode"]["on"]:
            raise Stop("SWITCH_DOSE_MODE", detail="dose excludes / add-backs on but dose_mode is not delta")
        dose = {"excludes": calls["dose_excludes"] if ex_on else frozenset(),
                "addbacks": calls["adds"] if ab_on else frozenset()}
    R["switches"] = {k: cfg.switch(k) for k in ("network_freeze", "dose_excludes", "dose_mode", "add_backs",
                                                 "rosters", "chemmath_edges", "agg_missing")}
    return {"mode": "m", "tag": "m", "cfg": cfg, "sh": sh, "scratch": scratch, "tables": tables,
            "rosters": rosters, "net": cfg.is_on(nf.SWITCH), "dose": dose,
            "real_derived": pathlib.Path(R["edges"]["real_derived"]), "p1_dirs": {}, "globs": {}}


def _lines(p) -> int:
    return pathlib.Path(p).read_bytes().count(b"\n") - 1


def run_field(field: str, ctx: dict, F: dict):
    sh, tag, root = ctx["sh"], ctx["tag"], ctx["scratch"]
    table = ctx["tables"][field]
    n_events = len(read_csv(table))
    t0 = time.time()
    log(f"[{field}] prodlib")
    frame, pcfg = run_prodlib_m(field, root, sh.root.parent, tag, F.setdefault("prodlib", {}),
                                real_derived=ctx["real_derived"], n_events=n_events)
    log(f"[{field}] D2 in-post filter")
    filt = d2_step(field, frame, ctx["rosters"][field], sh, root, tag)
    F["inpost"] = {k: filt["report"][k] for k in ("relations_by_class", "rows_by_class", "persons_by_class",
                                                  "events_left_with_zero_rows", "input", "output")}
    F["inpost"]["walk"] = filt["walk"]
    net_frame, origin = filt["output"], f"{tag}-stage:inpost_filter {field} (on the prodlib frame {sha(frame)[:12]})"
    if ctx["net"]:
        log(f"[{field}] V3-NET")
        net_frame, nrep = net_step(ctx["cfg"], field, filt["output"], pcfg, table, root, tag)
        F["v3net"] = {k: nrep[k] for k in ("relations_by_class", "rows_by_class", "rows_dropped",
                                           "events_left_with_zero_rows", "input", "output", "walk",
                                           "removed_relations")}
        origin += " + network_freeze (V3-NET)"
    hook = make_dose_hook(ctx, field, pcfg, F) if ctx["dose"] is not None else None
    log(f"[{field}] chain (union-gold{' + dose' if hook else ''} -> p1-gold -> p2-gold -> make_slim)")
    stages = run_chain_m(field, root, sh, tag, net_frame, origin, post_union=hook)
    prod = rcf.products_of(field, stages)
    F["stages"] = rcf._stage_summary(stages)
    F["products_sha256"] = {k: sha(v) for k, v in prod.items()}
    F["accounting"] = {"rows_prodlib": _lines(frame), "rows_after_d2": _lines(filt["output"]),
                       "rows_after_v3net": _lines(net_frame), "rows_union": _lines(prod["union_frame"]),
                       "rows_p1": _lines(prod[f"p1_frame_{field}.csv"]),
                       "rows_p2": _lines(prod[f"p2_becoming_{field}.csv"]),
                       "dose_rows_changed": (F.get("dose") or {}).get("rows_changed")}
    F["union_build_report"] = {k: v for k, v in json.loads(
        prod[f"union_build_report_{field}.json"].read_text("utf-8")).items()
        if k in ("frame", "GATE", "G_ROW", "G_SUM", "alias", "relationships_pre_guard")}
    ctx["p1_dirs"][field] = pathlib.Path(stages["p1"]["run_dir"]) / "data" / "fnfix"
    ctx["globs"][field] = (pcfg["snapshot"]["edges_glob"], pcfg["snapshot"]["works_glob"])
    F["secs"] = round(time.time() - t0, 1)
    return prod, filt


def canon_schema(field: str, prod: dict, filt: dict, F: dict) -> None:
    """M review #8 (canon M keeps October's basenames and report schema): the keys the paper ledgers read
    from frames_<field>/build_report_<field>.json, in October's shape, on this run's products - october.inpost with
    its spells record (ledger_carried checks the roster the in-post filter read) and the new-side counts of
    October's accounting (relationships, p1_frame, p2_becoming, slim: ledger_main and ledger_carried compare them
    with the frames). M's own keys stay."""
    F["october"] = {"inpost": {**F["inpost"], "spells": filt["report"]["spells"]},
                    "note": "config M's build under October's report key: canon M keeps October's schema (R1P3-37)"}
    with open(prod[f"relationships_{field}.csv"], newline="", encoding="utf-8") as fh:
        rel = {(r["pid"], r["event_id"]): r["channel"] for r in csv.DictReader(fh)}
    import pyarrow.parquet as pq                                         # noqa: PLC0415
    acc = F.setdefault("accounting", {})
    acc["relationships"] = {"relations_new": len(rel), "by_channel_new": dict(collections.Counter(rel.values())),
                            "persons_new": len({q for q, _ in rel}), "events_new": len({e for _, e in rel})}
    acc["p1_frame"] = {"rows_new": _lines(prod[f"p1_frame_{field}.csv"])}
    acc["p2_becoming"] = {"rows_new": _lines(prod[f"p2_becoming_{field}.csv"])}
    acc["slim"] = {"slim": {"rows": pq.ParquetFile(prod[f"p3_slim_{field}.parquet"]).metadata.num_rows}}


def publish_yrebuild(p1_dirs: dict, fields, out: pathlib.Path) -> dict:
    """M review #8: each field's y-step report g_yrebuild_<field>.json (left in the p1-gold run dir, scratch) ->
    STAGE_OUT/yrebuild_chemmath/, October's layout (data/cal2026-10/yrebuild_chemmath/), which FINAL's canon
    reads (ledger_main, ledger_carried). A missing report is a STOP."""
    d = pathlib.Path(out) / YREBUILD_DIR
    d.mkdir(parents=True, exist_ok=True)
    rec = {}
    for f in fields:
        src = pathlib.Path(p1_dirs[f]) / f"g_yrebuild_{f}.json"
        if not src.is_file():
            raise Stop("YREBUILD_REPORT_MISSING", [f], f"no {src.name} in the p1-gold run dir")
        dst = d / src.name
        dst.write_bytes(src.read_bytes())
        rec[f] = sha(dst)
    return rec


# ---------------------------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------------------------

def scratch_root(a, out: pathlib.Path) -> pathlib.Path:
    v = a.scratch or os.environ.get("SAR_OUT_ROOT", "").strip()
    if not v:
        work = os.environ.get("WORK", "").strip()
        if not work:
            raise Stop("SCRATCH", detail="give --scratch, $SAR_OUT_ROOT or $WORK")
        v = str(pathlib.Path(work) / "tmp" / f"chemmath_m_{out.name}_{datetime.datetime.now():%Y%m%d%H%M%S}")
    p = pathlib.Path(v).resolve()
    if p.is_relative_to(REPO / "data"):
        raise Stop("SCRATCH", detail="the scratch root must not be under data/")
    p.mkdir(parents=True, exist_ok=True)
    if any(p.iterdir()):
        raise Stop("SCRATCH", detail=f"the scratch root must be empty: {p}")
    return p


def _flat_ids(ids) -> list[str]:
    out = set()
    for i in ids:
        for x in (i if isinstance(i, (list, tuple)) else [i]):
            out.add(str(x))
    return sorted(out)


def summary(R: dict) -> dict:
    """report_chemmath_m.json: counts, codes and ids only (run_stages.name_free keeps these)."""
    s = {"mode": R["mode"], "result": R.get("result"), "fields": {}}
    for f, F in (R.get("fields") or {}).items():
        acc = F.get("accounting") or {}
        dose = F.get("dose") or {}
        s["fields"][f] = {**{k: v for k, v in acc.items() if k.startswith("rows_")},
                          "n_events_prodlib": (F.get("prodlib") or {}).get("events_in_prodlib"),
                          "n_dose_relations_affected": (dose.get("relations") or {}).get("affected"),
                          "n_dose_relations_changed": (dose.get("relations") or {}).get("changed"),
                          "n_dose_unmapped_identity": (dose.get("person_map") or {}).get("unmapped_identity"),
                          "n_v3net_rows_dropped": (F.get("v3net") or {}).get("rows_dropped")}
    se = R.get("stars_excluded")
    if se:
        s["stars_excluded"] = {"n_total": se["total"], "n_added": len(se["added"]), "n_removed": len(se["removed"]),
                               "ids": sorted(set(se["added"]) | set(se["removed"]))}
    if "coverage" in R:
        s["coverage"] = {"code": R["coverage"]["code"], "n_persons": R["coverage"]["n_persons"]}
    if R.get("edge_proof"):
        s["edge_proof"] = R["edge_proof"]
    return s


def run(a) -> int:
    t0 = time.time()
    out = pathlib.Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    for stale in ("RESULT.txt", f"report_{REPORT}.json", f"stop_report_{REPORT}.json", "report_gdose_chemmath.json"):
        (out / stale).unlink(missing_ok=True)
    fields = tuple(f for f in a.fields.split(",") if f)
    R: dict = {"schema": "sar.r1.chemmath_m_run.v1", "mode": a.mode, "fields_run": list(fields),
               "repo": str(REPO), "fields": {},
               "out_of_scope": "F20 (new-star departure ledger and departure frames): author ruling 2026-10-15"}
    try:
        if not fields or not set(fields) <= set(FIELDS):
            raise Stop("FIELDS", detail=f"--fields {a.fields!r}")
        scratch = scratch_root(a, out)
        R["scratch"] = str(scratch)
        cfg = load_config(a.config)
        check_mode(cfg, a.mode)
        R["config"] = {"name": cfg.name, "sha256": cfg.sha256}
        R["edges"] = edge_env(cfg, proof=a.edge_proof)
        ctx = setup_b0(cfg, a, scratch, R) if a.mode == "b0" else setup_m(cfg, a, scratch, R)
        prods, filts = {}, {}
        for f in fields:
            prods[f], filts[f] = run_field(f, ctx, R["fields"].setdefault(f, {}))
            if a.mode == "m":
                canon_schema(f, prods[f], filts[f], R["fields"][f])
        R["gdose"] = {f: gdose_advisory(prods[f][f"union_build_report_{f}.json"]) for f in fields}
        write_json(out / "report_gdose_chemmath.json", {"rule": GDOSE_RULE, "mode": a.mode, "fields": R["gdose"]})
        coverage_step(ctx, fields, out, R)
        if a.mode == "b0":
            R["vs_october"] = {f: compare_products(f, prods[f], pathlib.Path(a.october_ref)) for f in fields}
            bad = sorted(f for f, v in R["vs_october"].items() if not v["all_equal"])
            if a.edge_proof:            # S10: reported, never a STOP; the products are frozen below for the proof
                R["edge_proof"] = {"rule": EDGE_PROOF_RULE, "target": pathlib.Path(R["edges"]["target"]).name,
                                   "b0_vs_october": {f: {"all_equal": bool(v["all_equal"]), "differ": list(v["differ"])}
                                                     for f, v in R["vs_october"].items()}}
            elif bad:
                raise Stop("B0_NOT_OCTOBER", bad, f"{ {f: R['vs_october'][f]['differ'] for f in bad} }")
        R["products"] = {f: rcf.freeze(f, prods[f], filts[f], {ctx["tag"]: ctx["sh"]}, R["fields"][f],
                                       out_root=out) for f in fields}
        if a.mode == "m":
            R["yrebuild"] = publish_yrebuild(ctx["p1_dirs"], fields, out)
        R["result"] = "OK"
        write_json(out / f"report_{REPORT}.json", summary(R))
        (out / "RESULT.txt").write_text("OK\n", encoding="utf-8")
        log(f"OK in {time.time() - t0:.0f} s -> {out}")
        return 0
    except Stop as e:
        R["result"] = "STOP"
        R["stop"] = {"code": e.code, "ids": e.ids, "detail": e.detail}
        write_json(out / f"stop_report_{REPORT}.json",
                   {"result": "STOP", "code": e.code, "mode": a.mode, "ids": _flat_ids(e.ids),
                    "n_ids": len(e.ids), "pairs": [i for i in e.ids if isinstance(i, list)]})
        (out / "RESULT.txt").write_text(f"STOP {e.code}\n", encoding="utf-8")
        log(f"STOP {e.code}: {e.detail} {e.ids[:20]}")
        return EXIT_STOP
    finally:
        R["secs"] = round(time.time() - t0, 1)
        write_json(out / "chemmath_m_run_report.json", R)


def parse(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--mode", required=True, choices=MODES)
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True, help="STAGE_OUT")
    ap.add_argument("--fields", default=",".join(FIELDS))
    ap.add_argument("--scratch", default=None)
    ap.add_argument("--repo", default=None, help="must be the checkout this runs against (default: found)")
    ap.add_argument("--events-dir", dest="events_dir")
    ap.add_argument("--roster-chemistry", dest="roster_chemistry")
    ap.add_argument("--roster-math-stats", dest="roster_math_stats")
    ap.add_argument("--roster-variant", dest="roster_variant", choices=VARIANTS)
    ap.add_argument("--stars-excluded-base", dest="stars_excluded_base")
    ap.add_argument("--event-tables-all", dest="event_tables_all")
    ap.add_argument("--calls")
    ap.add_argument("--supplement-extra", dest="supplement_extra", action="append", default=[])
    ap.add_argument("--october-ref", dest="october_ref")
    ap.add_argument("--edge-proof", dest="edge_proof", action="store_true",
                    help="b0 only, the S10 reverse proof's driver mode (reverse_proof_s10.py): run under an edge-table "
                         "shadow (any target), report the October comparison instead of STOP B0_NOT_OCTOBER and "
                         "freeze every product")
    a = ap.parse_args(argv)
    if a.mode == "m":
        miss = [k for k in M_ONLY if not getattr(a, k)]
        if miss:
            ap.error(f"--mode m needs {', '.join('--' + k.replace('_', '-') for k in miss)}")
        given = [k for k in B0_ONLY if getattr(a, k)]
        if given:
            ap.error(" and ".join("--" + k.replace("_", "-") for k in given) + " are b0 flags" if len(given) > 1
                     else f"--{given[0].replace('_', '-')} is a b0 flag")
    else:
        given = [k for k in M_ONLY if getattr(a, k)] + (["supplement_extra"] if a.supplement_extra else [])
        if given:
            ap.error(f"--mode b0 takes no M input ({', '.join('--' + k.replace('_', '-') for k in given)})")
        if not a.october_ref:
            ap.error("--mode b0 needs --october-ref")
    if a.repo and pathlib.Path(a.repo).resolve() != REPO:
        ap.error(f"--repo {a.repo} is not the checkout this file binds to ({REPO})")
    return a


def main(argv=None) -> int:
    if os.environ.get("SAR_HOST", "").strip() not in HOSTS:
        raise SystemExit("R1 rule: chemmath_m.py runs only on an R1 instance ($SAR_HOST)")
    return run(parse(argv))


if __name__ == "__main__":
    sys.exit(main())
