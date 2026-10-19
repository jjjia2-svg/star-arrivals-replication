#!/usr/bin/env python3
"""R1 J0-MEAS.3j / S10 reverse proof: N2's real-data test (big host, batch B4; not a J0 stage, not a gate).

  reverse_proof_s10.py prove --out DIR [--ref DIR] [--fields chemistry math_stats] [--driver-extra JSON]
  (R1 instance only; every input location comes from the paths config in force, $SAR_PATHS_CONFIG)

What it proves. J1a builds chemistry / maths on u1_full_11school_2026-07-16 by staging it under the
u1_edges_full_2026-07-05 name in a shadow data root (pipeline/aws/r1/edge_table.py, N2). This checks that
wiring on real data, in four steps:

  1 cut       the 11-school table cut to the works of the 07-05 table: W = distinct work_id of the 07-05
              works and authorship_edges; authorship_edges / works / works_affil keep the rows whose
              work_id is in W; work_first_pub keeps the author_ids of the 07-05 work_first_pub;
              fwci_baseline_pop is copied whole (only the unused machineold variant reads it); every
              other subtable is linked, not copied (no chem/maths reader reads it: edge_table
              GOLD_READERS); a 07-05 subtable with no parquet file (canonical_id_map: 0 rows, U1's
              provenance.json only) that the 11-school table lacks is recorded as absent_empty_in_0705 and
              not linked (edge_table applies the same rule; t-big-03). Each written subtable is
              <sub>/bucket=000/part-0.parquet under
              <out>/cut/u1_cut. PREMISE: the cut equals the 07-05 table by content (EXCEPT ALL both
              ways over all columns, every column cast to VARCHAR so a pandas categorical and a plain
              string compare as values; the column-name sets must match), plus works_0705_not_in_11.
              Only the four subtables the chain reads decide (PREMISE_SUBTABLES); pop is reported.
  2 cut run   W2-CHEMM's driver pipeline/aws/r1/chemmath_m.py --mode b0 --edge-proof (October inputs, every
              other switch off) with SAR_PATHS_CONFIG = the shadow whose 07-05 name points at the cut,
              --october-ref = the root above the ref dir (october_root) and one --fields string. --edge-proof
              is what lets b0 run under the shadow (plain b0 refuses it: EDGE_ENV) and freeze its products
              whatever its own strict October comparison says (plain b0: STOP B0_NOT_OCTOBER, nothing frozen);
              the driver's report must name the table it ran on (the wiring control; ReverseProofStop else).
  3 compare   its products against October's (the tracked data/cal2026-10/frames_<field>/) under the
              October acceptance rules (run_cal_frames_chemmath.py, phase C/O): relationships and p2
              BYTE_EQUAL; the union build report equal modulo run-dir paths with H1 at the advisory path
              only (json_equal_modulo_paths); p1 within H1 (fwci_frac / fwci_frac_ex_star <= 8 ULP, no
              other column; h1_characterise); parquet content-equal (tools.content_equal). A CSV that
              differs ONLY in row order is ORDER_ONLY and accepted (ruling: the cut's parquet layout
              changes DuckDB's scan order); for p1 the order-only test is applied with the H1 rule on
              both files sorted by (incumbent_person_id, event_id, year) and recorded as ORDER_ONLY+H1.
  4 on run    the same driver on the FULL 11-school table (the J1a switch value): the set of
              (pid, event_id) whose channel is dept_only or both must equal October's, except relations
              the union builder's age-gap guard explains (10_build_union_frame_gold.py:458-482: a new
              dept_only relation with |star_first - person_first| > 60 is dropped). A relation present
              on one side only is explained when the side that lacks it shows a gap beyond the guard:
              (a) the builder lists it in age_gap_guard.dropped_examples; or (b) the gap is derived from
              that side's own dept_only p1 rows (gap = S(event) - P(person) is additive, so a gap can be
              walked through other relations of the same person and event: class Potentials); or (c) the
              person's robust first year is recomputed from that side's edge table folded through the
              person map (the builder's pedges + robust_first_pub) and the event's star year is taken
              from >= 2 anchor persons whose builder gaps agree with it (the positive control; any
              disagreement voids the event, a star person is never derived this way because the builder
              adds supplement works the edge table lacks). The explained counts must also fit inside the
              builder's own new_rel_dropped count. Anything else is ROSTER_CHANNEL_DIFF, with the ids.

  On PREMISE_FAIL the cut run is recorded but does not decide: a WIRING run on a re-materialised copy of
  the 07-05 table (<out>/wiring/u1_0705_copy, same writer, same shadow) must reproduce October instead,
  which proves the wiring while the data difference itself is what design v3 asks for. That holds for a cut
  run that STOPs too (t-big-04: rc=3, and the proof stopped before it reached the wiring run): on
  PREMISE_FAIL its rc and STOP code are recorded (runs.cut, compare.cut = null) and the proof goes on.

Verdict (RESULT.txt, summary_3j.json): REVERSE_PROOF_OK | PREMISE_FAIL+WIRING_OK | DIFF |
ROSTER_CHANNEL_DIFF (DIFF wins over ROSTER_CHANNEL_DIFF). Any other driver failure STOPs (RESULT STOP, exit 1)
with a ReverseProofStop that carries the driver's STOP code and detail (stop_report_chemmath_m.json, its run
report) and the last DRIVER_LOG_TAIL lines of <out>/<label>/driver.log, so the junit report shows them.
The summary holds counts, ids (OpenAlex author / work ids, event ids) and fixed tokens only: no display
name and no path (check_ids_counts runs before it is written; the S3 -> Mac rule). Every write goes under
--out (write_json / write_text refuse anything else; the cut refuses an out that nests with an input).
The driver's own scratch is its business: SAR_OUT_ROOT is pointed at <out>/<label>/sar_out_root.
Author ruling 2026-10-15: F20 (star departures) is out of scope; nothing here touches departures.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import pathlib
import re
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))
import edge_table as et                                                     # noqa: E402

HOSTS = et.HOSTS
SCHEMA = "sar.r1.reverse_proof_s10.v1"
ITEM = "J0-MEAS.3j"
SUMMARY_NAME = "summary_3j.json"
RESULT_NAME = "RESULT.txt"
FIELDS = ("chemistry", "math_stats")
CUT_NAME = "u1_cut"
REMAT_NAME = "u1_0705_copy"
#: how each subtable of the cut is made (anything else the 07-05 table holds is linked, unread)
FILTER_WORK = ("authorship_edges", "works", "works_affil")
FILTER_AUTHOR = ("work_first_pub",)
COPY_WHOLE = ("fwci_baseline_pop",)
#: a 07-05 subtable without a parquet file that the 11-school table lacks: recorded, nothing written
ABSENT_EMPTY = "absent_empty_in_0705"
#: the subtables the chem/maths chain reads through the 07-05 name: these decide the premise
PREMISE_SUBTABLES = FILTER_WORK + FILTER_AUTHOR
#: == run_cal_frames_chemmath.PRODUCTS (asserted at compare time)
PRODUCTS = ("p1_frame_{f}.csv", "p2_becoming_{f}.csv", "pairs_none_{f}.parquet",
            "relationships_{f}.csv", "union_build_report_{f}.json",
            "p3_slim_{f}.parquet", "p3_slim_ev_{f}.parquet")
ROSTER_CHANNELS = ("dept_only", "both")
#: the union builder's person map, relative to legacy_thesis (10_build_union_frame_gold.py:91, PMAP)
PMAP_REL = "v2_output/multidisc_v2_2026-08-04/data/person_map_multidisc_seeds.parquet"
VERDICTS = ("REVERSE_PROOF_OK", "PREMISE_FAIL+WIRING_OK", "DIFF", "ROSTER_CHANNEL_DIFF")
OK_VERDICTS = VERDICTS[:2]
MAX_ANCHORS = 30
_TOKEN = re.compile(r"^[A-Za-z0-9_.:+\-]{0,200}$")
#: driver.log lines a driver failure carries into its ReverseProofStop (the junit failure text)
DRIVER_LOG_TAIL = 60
#: ids of a driver STOP kept in the run record / summary
STOP_IDS_KEPT = 20


class ReverseProofStop(RuntimeError):
    """A step could not run (driver failure, missing input); the proof has no verdict. `run` = the driver's run
    record when the driver ran and exited non-zero (rc, stop_code, stop_ids), else None."""

    def __init__(self, msg: str, *, run: dict | None = None):
        super().__init__(msg)
        self.run = run


# ---------------------------------------------------------------------------------------------
# write boundary and the summary rule
# ---------------------------------------------------------------------------------------------

def _abs(p) -> pathlib.Path:
    return pathlib.Path(os.path.abspath(os.path.expanduser(str(p))))


def _guard(path, out) -> pathlib.Path:
    """`path` (symlinks resolved as far as they exist) lies under `out`, else PermissionError."""
    p = _abs(path)
    if not et._inside(p, _abs(out)):
        raise PermissionError(f"reverse proof writes only under its out dir {out}; refused {p}")
    return p


def write_text(path, text: str, *, out) -> pathlib.Path:
    p = _guard(path, out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def write_json(path, obj, *, out) -> pathlib.Path:
    return write_text(path, json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=True) + "\n", out=out)


def check_ids_counts(obj, where: str = "summary") -> None:
    """Counts, booleans, ids and fixed tokens only: every string (key or value) is one ASCII token with no
    space and no '/', so neither a display name nor a path can pass."""
    if obj is None or isinstance(obj, (bool, int, float)):
        return
    if isinstance(obj, str):
        if not _TOKEN.match(obj):
            raise ValueError(f"{where}: {obj[:40]!r} is not an id, a count or a token")
        return
    if isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            check_ids_counts(v, f"{where}[{i}]")
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str) or not _TOKEN.match(k):
                raise ValueError(f"{where}: key {str(k)[:40]!r} is not a token")
            check_ids_counts(v, f"{where}.{k}")
        return
    raise ValueError(f"{where}: {type(obj).__name__} is not allowed in the summary")


# ---------------------------------------------------------------------------------------------
# 1 the cut, the re-materialised 07-05 copy, the premise
# ---------------------------------------------------------------------------------------------

def _sql(s) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def _ident(c: str) -> str:
    return '"' + c.replace('"', '""') + '"'


def _rp(table, sub: str) -> str:
    return f"read_parquet({_sql(f'{table}/{sub}/**/*.parquet')}, hive_partitioning=0)"


def _refuse_nesting(out: pathlib.Path, *tables: pathlib.Path) -> None:
    for t in tables:
        if et._inside(out, t) or et._inside(t, out):
            raise ValueError(f"the out dir ({out}) and an input table ({t}) must not nest")


def _materialise(dest: pathlib.Path, plan: list, con, out: pathlib.Path) -> dict:
    """plan: (sub, how, source table, WHERE clause or None). Writes <dest>/<sub>/bucket=000/part-0.parquet
    or, for how == link_unread, a symlink to the source subtable."""
    _guard(dest, out).mkdir(parents=True)
    done = {}
    for sub, how, src, where in plan:
        if how == ABSENT_EMPTY:
            done[sub] = {"how": how}
            continue
        if how == "link_unread":
            os.symlink(src / sub, _guard(dest / sub, out))
            done[sub] = {"how": how}
            continue
        f = _guard(dest / sub / "bucket=000" / "part-0.parquet", out)
        f.parent.mkdir(parents=True)
        con.execute(f"COPY (SELECT t.* FROM {_rp(src, sub)} t{where or ''}) TO {_sql(f)} (FORMAT PARQUET)")
        n = con.execute(f"SELECT count(*) FROM read_parquet({_sql(f)})").fetchone()[0]
        done[sub] = {"how": how, "rows": int(n)}
    return done


def cut(real_0705, real_11, out, con) -> dict:
    """<out>/cut/u1_cut = the 11-school table cut to the 07-05 works (module docstring, step 1)."""
    real_0705, real_11, out = _abs(real_0705), _abs(real_11), _abs(out)
    _refuse_nesting(out, real_0705, real_11)
    for t in (real_0705, real_11):
        if not t.is_dir():
            raise FileNotFoundError(f"input table is not a directory: {t}")
    dest = out / "cut" / CUT_NAME
    if os.path.lexists(dest):
        raise FileExistsError(f"the cut already exists: {dest}")
    subs0, subs11 = et._subtables(real_0705), et._subtables(real_11)
    lack0 = [s for s in PREMISE_SUBTABLES if s not in subs0]
    if lack0:
        raise ValueError(f"the 07-05 table lacks {lack0}; the cut rule needs them")
    need = sorted(set(subs0) | set(et.SUBTABLES))
    # a 07-05 subtable with no parquet file (canonical_id_map: 0 rows) is not needed by the shadow
    # (edge_table._plan, same rule) and is recorded, not linked, when the 11-school table lacks it (t-big-03)
    empty0 = set(subs0) - set(et._subtables_with_data(real_0705)) - set(et.SUBTABLES)
    lack11 = [s for s in need if s not in subs11 and s not in empty0]
    if lack11:
        raise ValueError(f"the 11-school table lacks {lack11}, which the shadow would need")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE rp_w AS SELECT DISTINCT work_id FROM (
        SELECT work_id FROM {_rp(real_0705, 'works')} UNION ALL
        SELECT work_id FROM {_rp(real_0705, 'authorship_edges')}) WHERE work_id IS NOT NULL""")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE rp_a AS SELECT DISTINCT author_id
        FROM {_rp(real_0705, 'work_first_pub')} WHERE author_id IS NOT NULL""")
    plan = []
    for sub in need:
        if sub in empty0 and sub not in subs11:
            plan.append((sub, ABSENT_EMPTY, real_11, None))
        elif sub in FILTER_WORK:
            plan.append((sub, "filter_work_id", real_11, " WHERE t.work_id IN (SELECT work_id FROM rp_w)"))
        elif sub in FILTER_AUTHOR:
            plan.append((sub, "filter_author_id", real_11,
                         " WHERE t.author_id IN (SELECT author_id FROM rp_a)"))
        elif sub in COPY_WHOLE:
            plan.append((sub, "copy_whole", real_11, None))
        else:
            plan.append((sub, "link_unread", real_11, None))
    done = _materialise(dest, plan, con, out)
    n_w = con.execute("SELECT count(*) FROM rp_w").fetchone()[0]
    return {"dir": str(dest), "works_W": int(n_w), "subtables": done}


def rematerialise(real_0705, out, con) -> dict:
    """<out>/wiring/u1_0705_copy = the 07-05 table rewritten by the same writer (the wiring control)."""
    real_0705, out = _abs(real_0705), _abs(out)
    _refuse_nesting(out, real_0705)
    dest = out / "wiring" / REMAT_NAME
    if os.path.lexists(dest):
        raise FileExistsError(f"the re-materialised copy already exists: {dest}")
    subs0 = et._subtables(real_0705)
    lack = [s for s in et.SUBTABLES if s not in subs0]
    if lack:
        raise ValueError(f"the 07-05 table lacks {lack}")
    plan = [(s, "copy_whole" if s in et.SUBTABLES else "link_unread", real_0705, None) for s in subs0]
    return {"dir": str(dest), "subtables": _materialise(dest, plan, con, out)}


def _cols(con, table, sub) -> list[tuple[str, str]]:
    return [(r[0], str(r[1])) for r in con.execute(f"DESCRIBE SELECT * FROM {_rp(table, sub)}").fetchall()]


def premise(cut_dir, real_0705, con) -> dict:
    """The cut equals the 07-05 table by content (module docstring, step 1)."""
    cut_dir, real_0705 = _abs(cut_dir), _abs(real_0705)
    subs = {}
    for sub in et._subtables(real_0705):
        if (cut_dir / sub).is_symlink() or not (cut_dir / sub).is_dir():
            subs[sub] = {"compared": False, "decides": False}
            continue
        ca, cb = _cols(con, real_0705, sub), _cols(con, cut_dir, sub)
        na, nb = [c for c, _ in ca], [c for c, _ in cb]
        rec = {"compared": True, "decides": sub in PREMISE_SUBTABLES,
               "columns_equal": sorted(na) == sorted(nb), "column_order_equal": na == nb,
               "type_diff_columns": sorted(c for c, t in ca if c in dict(cb) and dict(cb)[c] != t)}
        rec["rows_0705"] = int(con.execute(f"SELECT count(*) FROM {_rp(real_0705, sub)}").fetchone()[0])
        rec["rows_cut"] = int(con.execute(f"SELECT count(*) FROM {_rp(cut_dir, sub)}").fetchone()[0])
        if rec["columns_equal"]:
            sel = ", ".join(f"CAST({_ident(c)} AS VARCHAR) AS {_ident(c)}" for c in na)
            qa = f"SELECT {sel} FROM {_rp(real_0705, sub)}"
            qb = f"SELECT {sel} FROM {_rp(cut_dir, sub)}"
            key = next((k for k in ("work_id", "author_id") if k in na), None)
            for name, x, y in (("0705", qa, qb), ("cut", qb, qa)):
                rec[f"only_in_{name}"] = int(con.execute(
                    f"SELECT count(*) FROM ({x} EXCEPT ALL {y})").fetchone()[0])
                rec[f"sample_ids_only_in_{name}"] = [r[0] for r in con.execute(
                    f"SELECT DISTINCT {_ident(key)} FROM ({x} EXCEPT ALL {y}) ORDER BY 1 LIMIT 10"
                ).fetchall()] if key else []
        else:
            rec["only_in_0705"] = rec["only_in_cut"] = None
        subs[sub] = rec
    w0 = (f"SELECT work_id FROM {_rp(real_0705, 'works')} UNION SELECT work_id "
          f"FROM {_rp(real_0705, 'authorship_edges')}")
    wc = f"SELECT work_id FROM {_rp(cut_dir, 'works')} UNION SELECT work_id FROM {_rp(cut_dir, 'authorship_edges')}"
    missing = f"SELECT work_id FROM ({w0}) WHERE work_id IS NOT NULL EXCEPT SELECT work_id FROM ({wc})"
    n_missing = int(con.execute(f"SELECT count(*) FROM ({missing})").fetchone()[0])
    sample = [r[0] for r in con.execute(f"SELECT work_id FROM ({missing}) ORDER BY 1 LIMIT 20").fetchall()]
    ok = n_missing == 0 and all(
        s["columns_equal"] and s["only_in_0705"] == 0 and s["only_in_cut"] == 0
        for k, s in subs.items() if s["decides"])
    ok = ok and all(k in subs for k in PREMISE_SUBTABLES)
    return {"ok": ok, "verdict": "PREMISE_OK" if ok else "PREMISE_FAIL", "subtables": subs,
            "works_0705_not_in_11": n_missing, "works_0705_not_in_11_sample": sample}


# ---------------------------------------------------------------------------------------------
# 2 the chem/maths driver (W2-CHEMM) through N2's shadow
# ---------------------------------------------------------------------------------------------

def october_root(ref_dir) -> pathlib.Path:
    """chemmath_m.py --october-ref: the root holding data/cal2026-10/frames_<field>/ (in place the repo root; J0's
    sandbox copy /work/ref/october), from this proof's ref dir = that root's data/cal2026-10 (paths key `cal`)."""
    r = _abs(ref_dir)
    if r.parts[-2:] != ("data", "cal2026-10"):
        raise ValueError(f"the October ref dir must be <root>/data/cal2026-10 (chemmath_m.py --october-ref takes "
                         f"<root>): {r}")
    return r.parent.parent


def _read_json(p: pathlib.Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError):
        return {}


def log_tail(p: pathlib.Path, n: int = DRIVER_LOG_TAIL) -> list[str]:
    """The last n lines of a log (undecodable bytes replaced; a missing log gives [])."""
    if not p.is_file():
        return []
    return p.read_bytes().decode("utf-8", errors="replace").splitlines()[-n:]


def driver_stop(stage_out: pathlib.Path) -> dict:
    """What chemmath_m.py left about how it ended: RESULT.txt, the name-free stop_report_chemmath_m.json (code, ids)
    and the run report's stop detail. stop_code None = the driver wrote no STOP (an exception, or an in-process
    builder that exited)."""
    stage_out = pathlib.Path(stage_out)
    res = (stage_out / "RESULT.txt").read_text(encoding="utf-8").strip() if (stage_out / "RESULT.txt").is_file() else None
    sr = _read_json(stage_out / "stop_report_chemmath_m.json")
    run_stop = _read_json(stage_out / "chemmath_m_run_report.json").get("stop") or {}
    code = sr.get("code") or run_stop.get("code")
    if code is None and res and res.startswith("STOP "):
        code = res.split(" ", 1)[1].strip()
    ids = [str(x) for x in (sr.get("ids") or [])]
    return {"result": res, "stop_code": code, "stop_ids": ids[:STOP_IDS_KEPT], "n_stop_ids": len(ids),
            "stop_detail": run_stop.get("detail")}


def make_driver(*, repo, py, config, fields, real_ssd_root, base_paths, october_ref, extra=(), env=None):
    """A driver(label, target, out) that runs chemmath_m.py --mode b0 --edge-proof (October inputs, every switch
    off, the October comparison reported and every product frozen) with SAR_PATHS_CONFIG = a shadow whose 07-05
    name points at `target` (edge_table.ensure_shadow), --october-ref = the October root and ONE comma-separated
    --fields string. The driver's report must name `target` as the table it ran on (STOP otherwise). Returns the
    run record."""
    repo, config, october_ref = _abs(repo), _abs(config), _abs(october_ref)

    def drive(label: str, target, out) -> dict:
        out = _abs(out)
        if os.environ.get("SAR_SSD_ROOT", "").strip():
            raise ReverseProofStop("$SAR_SSD_ROOT is set; it would override the shadow's ssd_root")
        d = _guard(out / label, out)
        d.mkdir(parents=True, exist_ok=True)
        mf, paths_file = et.ensure_shadow(real_ssd_root, d / et.WORK_SUBDIR, target, base_paths)
        stage_out, sar_out = d / "stage_out", d / "sar_out_root"
        stage_out.mkdir()
        sar_out.mkdir()
        argv = [str(py), str(repo / "pipeline" / "aws" / "r1" / "chemmath_m.py"), "--mode", "b0", "--edge-proof",
                "--config", str(config), "--october-ref", str(october_ref), "--out", str(stage_out),
                "--fields", ",".join(fields), *map(str, extra)]
        envd = {**os.environ, **(env or {}), "SAR_PATHS_CONFIG": str(paths_file),
                "SAR_R1_CONFIG": str(config), "SAR_OUT_ROOT": str(sar_out), "PYTHONHASHSEED": "0"}
        t0 = time.time()
        with open(_guard(d / "driver.log", out), "wb") as log:
            proc = subprocess.run(argv, cwd=repo, env=envd, stdout=log, stderr=subprocess.STDOUT)
        rec = {"label": label, "rc": proc.returncode, "secs": round(time.time() - t0, 1),
               "stage_out": stage_out, "target_name": pathlib.Path(str(target)).name,
               "swapped_name": mf["swapped_name"]}
        rep_p = stage_out / "report_chemmath_m.json"
        rep = json.loads(rep_p.read_text(encoding="utf-8")) if rep_p.is_file() else {}
        rec["edge_target"] = (rep.get("edge_proof") or {}).get("target")
        stop = driver_stop(stage_out)
        rec.update({k: stop[k] for k in ("stop_code", "stop_ids", "n_stop_ids")})
        write_json(d / "run.json", {**{k: v for k, v in rec.items() if k != "stage_out"}, "argv": argv,
                                    "paths_file": str(paths_file), "result": stop["result"],
                                    "stop_detail": stop["stop_detail"],
                                    "target_realpath": mf["target_realpath"]}, out=out)
        if proc.returncode != 0:
            tail = log_tail(d / "driver.log")
            raise ReverseProofStop(
                f"driver run '{label}' failed rc={proc.returncode}: {stop['result'] or 'no RESULT.txt'}"
                f" (STOP code {stop['stop_code']}, {stop['n_stop_ids']} ids {stop['stop_ids']};"
                f" detail: {stop['stop_detail']}); see {d / 'driver.log'}\n"
                f"--- last {len(tail)} lines of driver.log ---\n" + "\n".join(tail),
                run={k: v for k, v in rec.items() if k != "stage_out"})
        if rec["edge_target"] != rec["target_name"]:
            raise ReverseProofStop(f"driver run '{label}' ran its edge proof on {rec['edge_target']}, not on "
                                   f"{rec['target_name']}; see {d / 'driver.log'}")
        return rec

    return drive


# ---------------------------------------------------------------------------------------------
# 3 the October acceptance rules
# ---------------------------------------------------------------------------------------------

def _october():
    """run_cal_frames_chemmath (imported on demand: it pulls the October stage modules)."""
    d = str(REPO / "pipeline" / "frames" / "cal2026-10")
    if d not in sys.path:
        sys.path.insert(0, d)
    import run_cal_frames_chemmath as rc                                    # noqa: E402
    return rc


def _lines(p: pathlib.Path) -> list[bytes]:
    return p.read_bytes().split(b"\n")


def csv_status(new: pathlib.Path, ref: pathlib.Path) -> str:
    """BYTE_EQUAL, ORDER_ONLY (same header, same multiset of lines) or NOT_EQUAL."""
    bn, br = pathlib.Path(new).read_bytes(), pathlib.Path(ref).read_bytes()
    if bn == br:
        return "BYTE_EQUAL"
    ln, lr = bn.split(b"\n"), br.split(b"\n")
    if ln[0] == lr[0] and collections.Counter(ln[1:]) == collections.Counter(lr[1:]):
        return "ORDER_ONLY"
    return "NOT_EQUAL"


def _sorted_copy(src: pathlib.Path, dst: pathlib.Path, key_cols: tuple[str, ...]) -> pathlib.Path:
    lines = _lines(src)
    tail = lines[-1] == b""
    body = lines[1:-1] if tail else lines[1:]
    hdr = next(csv.reader([lines[0].decode("utf-8").replace("\r", "")]))
    ix = [hdr.index(c) for c in key_cols]

    def key(ln: bytes):
        row = next(csv.reader([ln.decode("utf-8").replace("\r", "")]))
        return tuple(row[i] for i in ix), ln
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(b"\n".join([lines[0], *sorted(body, key=key)]) + (b"\n" if tail else b""))
    return dst


def _p1_status(rc, new: pathlib.Path, ref: pathlib.Path, scratch: pathlib.Path) -> dict:
    h = rc.h1_characterise(ref, new)
    rec = {k: h[k] for k in ("differing_lines", "worst_ulp") if k in h}
    if h["ok"]:
        return {"status": "BYTE_EQUAL" if h.get("byte_equal") else "H1", "ok": True, **rec}
    if "reason" not in h:              # same line count and header: try the order-only reading
        key = ("incumbent_person_id", "event_id", "year")
        h2 = rc.h1_characterise(_sorted_copy(ref, scratch / f"ref_{ref.name}", key),
                                _sorted_copy(new, scratch / f"new_{new.name}", key))
        if h2["ok"]:
            return {"status": "ORDER_ONLY+H1", "ok": True,
                    **{k: h2[k] for k in ("differing_lines", "worst_ulp")}}
    cols = [c if _TOKEN.match(c) else "unexpected_shape" for c in h.get("unexpected_columns", [])]
    return {"status": "NOT_EQUAL", "ok": False, **rec, "unexpected_columns": cols}


def compare(products, ref_dir, fields, scratch) -> dict:
    """products/frames_<f>/ against ref_dir/frames_<f>/ under the October rules (module docstring, step 3)."""
    rc = _october()
    from tools.content_equal import content_equal                          # noqa: E402
    assert tuple(rc.PRODUCTS) == PRODUCTS, "run_cal_frames_chemmath.PRODUCTS moved"
    products, ref_dir, scratch = _abs(products), _abs(ref_dir), _abs(scratch)
    res = {"fields": {}}
    for f in fields:
        files = {}
        for tmpl in PRODUCTS:
            name = tmpl.format(f=f)
            a, b = products / f"frames_{f}" / name, ref_dir / f"frames_{f}" / name
            if not (a.is_file() and b.is_file()):
                files[name] = {"status": "MISSING", "ok": False, "new_present": a.is_file(),
                               "ref_present": b.is_file()}
            elif name.endswith(".csv") and name.startswith("p1_frame_"):
                files[name] = _p1_status(rc, a, b, scratch / f)
            elif name.endswith(".csv"):
                st = csv_status(a, b)
                files[name] = {"status": st, "ok": st in ("BYTE_EQUAL", "ORDER_ONLY")}
            elif name.endswith(".json"):
                j = rc.json_equal_modulo_paths(a, b)
                ok = bool(j["equal_modulo_paths_and_h1_advisory"])
                st = ("BYTE_EQUAL" if j["byte_equal"] else "EQUAL_MODULO_PATHS" if j["equal_modulo_paths"]
                      else "EQUAL_MODULO_PATHS_H1" if ok else "NOT_EQUAL")
                files[name] = {"status": st, "ok": ok, "n_diffs": len(j["diffs"]),
                               "h1_advisory_n": j["h1_ulp_in_advisory"]["n"],
                               "h1_advisory_worst_ulp": j["h1_ulp_in_advisory"]["worst_ulp"]}
            else:
                r = content_equal(a, b)
                files[name] = {"status": "CONTENT_EQUAL" if r.equal else "NOT_EQUAL", "ok": bool(r.equal),
                               "rows_new": r.rows_a, "rows_ref": r.rows_b}
        res["fields"][f] = {"ok": all(v["ok"] for v in files.values()), "files": files}
    res["ok"] = all(v["ok"] for v in res["fields"].values())
    return res


# ---------------------------------------------------------------------------------------------
# 4 the roster channel and the age-gap guard
# ---------------------------------------------------------------------------------------------

def _rows(p: pathlib.Path) -> tuple[list[str], list[list[str]]]:
    """Split on \\n and strip every \\r (frames_stage.read_frame_rows: the network rows carry CRs)."""
    lines = [ln.replace("\r", "") for ln in p.read_bytes().decode("utf-8").split("\n") if ln.strip("\r")]
    return next(csv.reader([lines[0]])), [next(csv.reader([ln])) for ln in lines[1:]]


def _roster_set(rel_csv: pathlib.Path) -> set[tuple[str, str]]:
    hdr, rows = _rows(rel_csv)
    ip, ie, ic = hdr.index("pid"), hdr.index("event_id"), hdr.index("channel")
    return {(r[ip], r[ie]) for r in rows if r[ic] in ROSTER_CHANNELS}


def _dept_gaps(p1_csv: pathlib.Path) -> tuple[list[tuple[str, str, float]], int]:
    """(pid, event, age_gap) of every dept_only relation with a gap (the union builder's own age_gap_of;
    network / both rows keep the 07-24 frame's value and are not used). Returns (triples, n_conflicts)."""
    hdr, rows = _rows(p1_csv)
    ip, ie = hdr.index("incumbent_person_id"), hdr.index("event_id")
    ig, ic = hdr.index("age_gap"), hdr.index("channel")
    seen: dict = collections.defaultdict(set)
    for r in rows:
        if r[ic] == "dept_only" and r[ig] not in ("", "NA", "nan", "None"):
            seen[(r[ip], r[ie])].add(float(r[ig]))
    conflicts = sum(1 for v in seen.values() if len(v) > 1)
    return sorted((p, e, next(iter(v))) for (p, e), v in seen.items() if len(v) == 1), conflicts


class Potentials:
    """gap(p, e) = S(e) - P(p) on the bipartite graph of known gaps; None when p and e are not connected
    or their component is inconsistent."""

    def __init__(self, triples):
        adj: dict = collections.defaultdict(list)
        for p, e, g in triples:
            adj[("p", p)].append((("e", e), float(g)))
            adj[("e", e)].append((("p", p), float(g)))
        self.val: dict = {}
        self.comp: dict = {}
        self.bad: set = set()
        cid = 0
        for start in sorted(adj):
            if start in self.val:
                continue
            cid += 1
            self.val[start], self.comp[start] = 0.0, cid
            todo = [start]
            while todo:
                n = todo.pop()
                for m, g in adj[n]:
                    want = self.val[n] - g if n[0] == "e" else self.val[n] + g
                    if m in self.val:
                        if abs(self.val[m] - want) > 1e-6:
                            self.bad.add(cid)
                    else:
                        self.val[m], self.comp[m] = want, cid
                        todo.append(m)

    def gap(self, p: str, e: str):
        a, b = ("p", p), ("e", e)
        if a not in self.val or b not in self.val or self.comp[a] != self.comp[b] or self.comp[a] in self.bad:
            return None
        return self.val[b] - self.val[a]


def _robust_first_pub():
    """identity.first_pub.robust_first_pub from THIS repository's ported unit, origin-asserted
    (the r1_dose_excl.py precedent: a stray `identity` package elsewhere on sys.path must not win)."""
    import importlib
    src = REPO / "pipeline" / "units" / "u0_foundation" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    mod = importlib.import_module("identity.first_pub")
    origin = pathlib.Path(mod.__file__).resolve()
    if not et._inside(origin, src):
        raise ImportError(f"identity.first_pub resolves outside the repository's units: {origin}")
    return mod.robust_first_pub


def first_pub_direct(con, table, pmap, pids, fp_gap: int) -> dict:
    """Each pid's robust first year from `table`, folded through the person map exactly as the union
    builder's pedges (10_build_union_frame_gold.py:197-232): DISTINCT edge years of every author id of the
    pid's person, works joined, NULL years dropped; robust_first_pub(max_leading_gap=fp_gap)."""
    rfp = _robust_first_pub()
    pids = sorted(set(pids))
    con.execute("CREATE OR REPLACE TEMP TABLE rp_needp (bare VARCHAR)")
    if pids:
        con.executemany("INSERT INTO rp_needp VALUES (?)", [(p,) for p in pids])
    con.execute(f"""CREATE OR REPLACE TEMP TABLE rp_alias AS
        WITH canon AS (SELECT n.bare, m.person_id FROM rp_needp n
                       JOIN read_parquet({_sql(pmap)}) m ON m.author_id = n.bare)
        SELECT c.bare AS pid, m2.author_id FROM canon c
        JOIN read_parquet({_sql(pmap)}) m2 ON m2.person_id = c.person_id""")
    con.execute("INSERT INTO rp_alias SELECT bare, bare FROM rp_needp "
                "WHERE bare NOT IN (SELECT pid FROM rp_alias)")
    years: dict = collections.defaultdict(set)
    for pid, yr in con.execute(f"""
            SELECT DISTINCT a.pid, e.publication_year FROM {_rp(table, 'authorship_edges')} e
            JOIN rp_alias a ON e.author_id = a.author_id
            JOIN {_rp(table, 'works')} w ON e.work_id = w.work_id
            WHERE e.publication_year IS NOT NULL""").fetchall():
        years[pid].add(int(yr))
    return {p: (int(rfp(sorted(years[p]), max_leading_gap=int(fp_gap))) if years.get(p) else None)
            for p in pids}


def explain_direct(rels, triples, pf: dict, *, guard_max: float, stars: set,
                   max_anchors: int = MAX_ANCHORS) -> dict:
    """gap(p, e) = S(e) - pf[p] with S(e) from >= 2 non-star anchor persons whose builder gaps all agree."""
    by_e: dict = collections.defaultdict(list)
    for q, e, g in triples:
        by_e[e].append((q, float(g)))
    out = {}
    for p, e in rels:
        if p in stars:
            out[(p, e)] = {"how": "void_star", "gap": None}
            continue
        anchors = sorted((q, g) for q, g in by_e.get(e, []) if q != p and q not in stars
                         and pf.get(q) is not None)[:max_anchors]
        s_vals = [g + pf[q] for q, g in anchors]
        if len(anchors) < 2 or max(s_vals) - min(s_vals) > 1e-6:
            out[(p, e)] = {"how": "void_control", "gap": None}
            continue
        if pf.get(p) is None:
            out[(p, e)] = {"how": "direct_na", "gap": None}
            continue
        g = float(s_vals[0] - pf[p])
        out[(p, e)] = {"how": "direct" if abs(g) > guard_max else "direct_within_guard", "gap": g}
    return out


def _explain(rels, report: dict, p1_csv: pathlib.Path, direct: dict | None, table) -> tuple[dict, dict]:
    """rel -> 'dropped_example' | 'derived' | 'direct' | None (unexplained), on the side that LACKS rel."""
    gm = float(report["age_gap_guard_max"])
    examples = {(str(p), str(e)): float(g) for p, e, g in report["age_gap_guard"]["dropped_examples"]}
    triples, conflicts = _dept_gaps(p1_csv)
    pot = Potentials(triples)
    res, pending = {}, []
    diag = collections.Counter(conflicting_gaps=conflicts)
    for rel in rels:
        if rel in examples and abs(examples[rel]) > gm:
            res[rel] = "dropped_example"
            continue
        g = pot.gap(*rel)
        if g is not None:
            res[rel] = "derived" if abs(g) > gm else None
            diag["derived_within_guard"] += abs(g) <= gm
            continue
        pending.append(rel)
    if pending and direct and direct.get("pmap") and table is not None:
        stars = {e.split(":", 1)[0] for _p, e, _g in triples} | {e.split(":", 1)[0] for _p, e in pending}
        need = {p for p, _ in pending} | {q for q, e, _g in triples if e in {e2 for _, e2 in pending}}
        pf = first_pub_direct(direct["con"], table, direct["pmap"], need, int(report["fp_gap"]))
        d = explain_direct(pending, triples, pf, guard_max=gm, stars=stars)
        for rel in pending:
            res[rel] = "direct" if d[rel]["how"] == "direct" else None
            diag[d[rel]["how"]] += 1
        diag["direct_used"] = 1
    else:
        res.update({rel: None for rel in pending})
        diag["underivable"] += len(pending)
    return res, dict(diag)


def roster_channel(on_dir, ref_dir, fields, *, direct: dict | None = None) -> dict:
    """The (pid, event) set with channel dept_only/both of the full-table run against October's
    (module docstring, step 4). direct = {con, pmap, on_table, oct_table} enables route (c)."""
    on_dir, ref_dir = _abs(on_dir), _abs(ref_dir)
    out = {"fields": {}}
    for f in fields:
        a, b = on_dir / f"frames_{f}", ref_dir / f"frames_{f}"
        s_on, s_ref = _roster_set(a / f"relationships_{f}.csv"), _roster_set(b / f"relationships_{f}.csv")
        rep_on = json.loads((a / f"union_build_report_{f}.json").read_text(encoding="utf-8"))
        rep_ref = json.loads((b / f"union_build_report_{f}.json").read_text(encoding="utf-8"))
        lost, gained = sorted(s_ref - s_on), sorted(s_on - s_ref)
        ex_l, dg_l = _explain(lost, rep_on, a / f"p1_frame_{f}.csv", direct,
                              direct.get("on_table") if direct else None)
        ex_g, dg_g = _explain(gained, rep_ref, b / f"p1_frame_{f}.csv", direct,
                              direct.get("oct_table") if direct else None)
        hows = collections.Counter(v for v in [*ex_l.values(), *ex_g.values()] if v)
        unexplained = sorted([list(r) for r, v in [*ex_l.items(), *ex_g.items()] if v is None])
        n_l, n_g = sum(1 for v in ex_l.values() if v), sum(1 for v in ex_g.values() if v)
        cnt = {"on_new_rel_dropped": int(rep_on["age_gap_guard"]["new_rel_dropped"]),
               "oct_new_rel_dropped": int(rep_ref["age_gap_guard"]["new_rel_dropped"]),
               "lost_explained": n_l, "gained_explained": n_g}
        exceeded = n_l > cnt["on_new_rel_dropped"] or n_g > cnt["oct_new_rel_dropped"]
        out["fields"][f] = {
            "oct": len(s_ref), "on": len(s_on), "lost": len(lost), "gained": len(gained),
            "explained": {k: hows.get(k, 0) for k in ("dropped_example", "derived", "direct")},
            "n_unexplained": len(unexplained), "unexplained": unexplained[:50],
            "guard_counts": cnt, "guard_count_exceeded": exceeded,
            "diagnostics": {"lost": dg_l, "gained": dg_g}, "network_ignored": True,
            "ok": not unexplained and not exceeded}
    out["ok"] = all(v["ok"] for v in out["fields"].values())
    return out


# ---------------------------------------------------------------------------------------------
# the proof
# ---------------------------------------------------------------------------------------------

def verdict(*, premise_ok: bool, products_ok: bool, roster_ok: bool) -> str:
    if not products_ok:
        return "DIFF"
    if not roster_ok:
        return "ROSTER_CHANNEL_DIFF"
    return "REVERSE_PROOF_OK" if premise_ok else "PREMISE_FAIL+WIRING_OK"


def _summary(fields, cut_info, prem, runs, cmp, roster, v, failures) -> dict:
    s = {"schema": SCHEMA, "item": ITEM, "verdict": v, "ok": v in OK_VERDICTS, "fields": list(fields),
         "failures": failures,
         "cut": {"works_W": cut_info["works_W"], "subtables": cut_info["subtables"]},
         "premise": prem,
         "runs": {k: {"rc": r["rc"], "secs": r["secs"], "target": r["target_name"], "stop_code": r.get("stop_code"),
                      "stop_ids": [x for x in (r.get("stop_ids") or []) if _TOKEN.match(str(x))]}
                  for k, r in runs.items()},
         "compare": cmp, "roster_channel": roster,
         "edge_via": "SAR_PATHS_CONFIG", "f20_departures": "out_of_scope"}
    s = json.loads(json.dumps(s))
    check_ids_counts(s)
    return s


def prove(real_0705, real_11, out, ref_dir, *, fields=FIELDS, driver, con=None, direct=None) -> dict:
    """Steps 1-4 (module docstring); writes <out>/summary_3j.json and <out>/RESULT.txt."""
    out = _abs(out)
    out.mkdir(parents=True, exist_ok=True)
    if con is None:
        import duckdb                                                       # noqa: E402
        con = duckdb.connect()
        con.execute(f"SET temp_directory={_sql(_guard(out / '_duck_tmp', out))}")
    prem = None
    try:
        cut_info = cut(real_0705, real_11, out, con)
        prem = premise(cut_info["dir"], real_0705, con)
        try:
            runs = {"cut": driver("cut", cut_info["dir"], out)}
            cmp = {"cut": compare(runs["cut"]["stage_out"], ref_dir, fields, _guard(out / "_cmp" / "cut", out)),
                   "wiring": None}
        except ReverseProofStop as exc:
            if prem["ok"] or exc.run is None:
                raise
            # PREMISE_FAIL: the cut is not the 07-05 table, so its run is recorded (rc, STOP code) and does not
            # decide; the wiring run below does (module docstring). t-big-04 stopped here instead.
            runs, cmp = {"cut": exc.run}, {"cut": None, "wiring": None}
        runs["on"] = driver("on", _abs(real_11), out)
        roster = roster_channel(runs["on"]["stage_out"], ref_dir, fields,
                                direct={**direct, "con": con} if direct else None)
        if not prem["ok"]:
            remat = rematerialise(real_0705, out, con)
            runs["wiring"] = driver("wiring", remat["dir"], out)
            cmp["wiring"] = compare(runs["wiring"]["stage_out"], ref_dir, fields,
                                    _guard(out / "_cmp" / "wiring", out))
    except ReverseProofStop as exc:
        note = ("premise not computed" if prem is None else
                f"premise {prem['verdict']} (works_0705_not_in_11={prem['works_0705_not_in_11']}, "
                f"sample {prem['works_0705_not_in_11_sample'][:5]}; deciding subtables (only_in_0705, only_in_cut): "
                f"{ {k: (s.get('only_in_0705'), s.get('only_in_cut')) for k, s in prem['subtables'].items() if s.get('decides')} })")
        write_text(out / RESULT_NAME, "RESULT STOP\n", out=out)
        write_text(out / "stop.txt", f"{exc}\n{note}\n", out=out)
        raise ReverseProofStop(f"{exc}\n{note}", run=exc.run) from exc
    products_ok = cmp["cut"]["ok"] if prem["ok"] else cmp["wiring"]["ok"]
    v = verdict(premise_ok=prem["ok"], products_ok=products_ok, roster_ok=roster["ok"])
    failures = ([] if prem["ok"] else ["premise"]) + ([] if products_ok else ["products"]) \
        + ([] if roster["ok"] else ["roster_channel"])
    s = _summary(fields, cut_info, prem, runs, cmp, roster, v, failures)
    write_json(out / SUMMARY_NAME, s, out=out)
    write_text(out / RESULT_NAME, f"RESULT {v}\n", out=out)
    return s


def prove_from_config(out, *, fields=FIELDS, driver_extra=(), ref_dir=None) -> dict:
    """prove() with every location from the paths config in force ($SAR_PATHS_CONFIG)."""
    from analysis.lib.paths import config_file, load_paths                 # noqa: E402
    base = config_file()
    P = load_paths(base)
    real_root = pathlib.Path(P["ssd_root"])
    derived = real_root / "derived"
    real_0705, real_11 = derived / et.TABLE_0705, derived / et.TABLE_11
    ref = _abs(ref_dir) if ref_dir else pathlib.Path(P["cal"])
    pmap = pathlib.Path(P["legacy_thesis"]) / PMAP_REL
    config = REPO / "config" / "r1" / "B0.json"
    drv = make_driver(repo=REPO, py=sys.executable, config=config, fields=tuple(fields),
                      real_ssd_root=real_root, base_paths=base, october_ref=october_root(ref),
                      extra=tuple(driver_extra))
    return prove(real_0705, real_11, out, ref, fields=tuple(fields), driver=drv,
                 direct={"pmap": pmap if pmap.is_file() else None, "on_table": real_11,
                         "oct_table": real_0705})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("prove", help="run the S10 reverse proof (steps 1-4) into --out")
    pr.add_argument("--out", required=True)
    pr.add_argument("--ref", default=None, help="October reference root holding frames_<field>/ "
                                                "(default: the paths config's `cal`)")
    pr.add_argument("--fields", nargs="+", default=list(FIELDS), choices=list(FIELDS))
    pr.add_argument("--driver-extra", default="[]", help="JSON list of extra chemmath_m.py arguments")
    a = ap.parse_args(argv)
    if os.environ.get("SAR_HOST", "").strip() not in HOSTS:
        raise SystemExit("R1 rule: reverse_proof_s10.py runs only on an R1 instance ($SAR_HOST)")
    s = prove_from_config(a.out, fields=a.fields, driver_extra=json.loads(a.driver_extra), ref_dir=a.ref)
    print(f"RESULT {s['verdict']}")
    return 0 if s["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
