#!/usr/bin/env python3
"""afar_event_map.py — proven ev -> event_id maps for the A_far frames (T6 support, 2026-08-29).

The frozen `data/frames/p3_afar_{field}.parquet` files carry only an integer event code `ev`
(the DENSE_RANK of event_id in the A_far pair set — `50_leftbehind_build.py` line 95). The
T6 sensitivity variants (star-departure A/B, double-star drops) are EVENT-level operations,
so they need the code -> event_id map. This script re-derives the A_far pair-set selection
with the exact SQL of the ported builder (dose / channel / pre-tie tables, the same median
cut, the same DENSE_RANK), emits the map, and PROVES it by rebuilding the full A_far frame
and requiring content-equality (every column, rows compared sorted by (grp, year)) with the
frozen parquet. A map is only written if its proof passes.

--spec (2026-09-10): `med` (default) is the retired median cut and proves against
data/frames/p3_afar_{field}.parquet (86/33/31 events) — the 2026-08-29 behaviour, unchanged;
`pos` is the paper's Panel 3 since 2026-08-30 (dose > 0, the predicate of
analysis/robustness/p3_afar_cuts/build_afar_cut.py) and proves against
data/frames/p3_afar_pos_{field}.parquet (108/38/32 events). Everything else — the SQL, the
pair-set joins, the DENSE_RANK, the content-equality proof — is one code path for both.

Inputs (all canon):
  frame  data/frames/p1_frame_{field}.csv          (dose_topic per person x event)
  p2     data/frames/p2_becoming_{field}.csv       (channel / pre-tie / any-tie per person x event)
  pairs  chemistry, math_stats: data/cal2026-08-28/frames/pairs_none_{field}.parquet (shipped)
         econ: pairs_unified.csv is NOT shipped (663 MB) — pass --pairs-econ with a copy
         regenerated through the caliber shadow (frames_stage.build_shadow + run_frames.py
         p2-econ --execute; ~80 s, needs the data disk). The regenerated becoming_unified.csv
         must be byte-identical (sha256) to data/frames/p2_becoming_econ.csv — checked here —
         which pins the regeneration to the canon caliber.

Output: <outdir>/afar_event_map_{field}.csv (ev, event_id) + afar_event_map_report.json.

R1 frames-dir mode (2026-10-16, R1 F6): `--spec pos --frames-dir DIR` reads p1_frame_<f>.csv,
p2_becoming_<f>.csv and the proof frame p3_afar_pos_<f>.parquet of all three fields from DIR, the
chemistry/math_stats pairs_none_<f>.parquet from --pairs-dir, and the econ pairs from --pairs-econ (the
run's own econ chain; never --regen-econ through the October shadow). --pairs-dir, --pairs-econ,
--outdir and --tmpdir are then required. Every missing input prints `AFAR_MAP_STOP missing <path>` and
exits 2 before anything is written; the econ becoming check is mandatory (becoming_unified.csv beside
--pairs-econ must be BYTE_EQUAL to DIR/p2_becoming_econ.csv). The report adds frames_dir, every pairs
path with its sha256, each proof frame's path and sha256, and the duckdb threads/memory. --threads and
--memory-limit (defaults 6 / 10GB) set the duckdb PRAGMAs in both modes. Without --frames-dir and
--pairs-dir every path, PRAGMA and report key is October's.
"""
import argparse
import hashlib
import json
import pathlib
import re
import sys

import duckdb
import pandas as pd

REPO = pathlib.Path(__file__).resolve().parents[3]

AFAR_SQL_DOSE = """CREATE OR REPLACE TEMP TABLE dose AS
    SELECT event_id, regexp_replace(incumbent_person_id,'^P_','') AS pid, max(dose_topic) AS dose
    FROM read_csv_auto('{frame}') WHERE dose_topic IS NOT NULL GROUP BY 1,2"""
AFAR_SQL_CH = """CREATE OR REPLACE TEMP TABLE ch AS
    SELECT event_id, regexp_replace(pid,'^P_','') AS pid,
           max(CASE WHEN channel IN ('network','both') THEN 1 ELSE 0 END) AS in_net,
           max(CASE WHEN y=1 AND tau<0 THEN 1 ELSE 0 END) AS pre_tie,
           max(CASE WHEN y=1 THEN 1 ELSE 0 END) AS any_tie
    FROM read_csv_auto('{p2}') GROUP BY 1,2"""
AFAR_SQL_PA = """CREATE OR REPLACE TEMP TABLE pa AS
    SELECT DISTINCT pr.event_id, pr.i_id, pr.j_id, least(di.dose,dj.dose) AS dmin,
           ci.in_net AS net_i, cj.in_net AS net_j
    FROM {rd}('{pairs}') pr
    JOIN dose di ON di.event_id=pr.event_id AND di.pid=pr.i_id
    JOIN dose dj ON dj.event_id=pr.event_id AND dj.pid=pr.j_id
    JOIN ch ci ON ci.event_id=pr.event_id AND ci.pid=pr.i_id AND ci.pre_tie=0
    JOIN ch cj ON cj.event_id=pr.event_id AND cj.pid=pr.j_id AND cj.pre_tie=0"""
AFAR_SQL_REBUILD = """
    WITH keep AS (SELECT event_id,i_id,j_id FROM pa WHERE {topic} AND net_i=0 AND net_j=0)
    SELECT CAST(DENSE_RANK() OVER (ORDER BY p.i_id||'_'||p.j_id||'@'||p.event_id)-1 AS INTEGER) AS grp,
           CAST(DENSE_RANK() OVER (ORDER BY p.event_id) AS INTEGER) AS ev,
           CAST(p.year AS INTEGER) AS year, CAST(p.y_any AS TINYINT) AS y,
           CAST(p.post AS TINYINT) AS D, p.event_id AS event_id
    FROM {rd}('{pairs}') p JOIN keep k
      ON k.event_id=p.event_id AND k.i_id=p.i_id AND k.j_id=p.j_id"""


SPECS = ("med", "pos")
#: where each spec's frozen frame and its maps live; `med` is the 2026-08-29 layout, untouched
FROZEN_FRAME = {"med": "data/frames/p3_afar_{field}.parquet",
                "pos": "data/frames/p3_afar_pos_{field}.parquet"}
DEFAULT_OUTDIR = {"med": "data/robustness_2026-08-29_b/afar_event_map",
                  "pos": "data/robustness_2026-09-10_p3pos/afar_event_map"}
GENERATED = {"med": "2026-08-29", "pos": "2026-09-10"}
DEFAULT_FRAMES = REPO / "data/frames"
DEFAULT_PAIRS_DIR = REPO / "data/cal2026-08-28/frames"   # October: chemistry/math_stats pairs_none
DEFAULT_TMPDIR = "/private/tmp/sar_afar_map_tmp"          # macOS only; R1 stages pass --tmpdir
MEMORY_LIMIT = re.compile(r"^[0-9]+(\.[0-9]+)?(KB|MB|GB|TB|KiB|MiB|GiB|TiB)$")


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def frozen_frame_path(spec: str, field: str, frames_dir: pathlib.Path | None) -> pathlib.Path:
    """October: REPO/FROZEN_FRAME[spec]; frames-dir mode: the same basename inside frames_dir."""
    name = FROZEN_FRAME[spec].format(field=field)
    return REPO / name if frames_dir is None else pathlib.Path(frames_dir) / pathlib.PurePosixPath(name).name


def map_field(con: duckdb.DuckDBPyConnection, field: str, pairs: str,
              spec: str = "med", frames_dir: pathlib.Path | None = None) -> tuple[pd.DataFrame, dict]:
    """frames_dir None = October (data/frames and FROZEN_FRAME[spec]); otherwise p1, p2 and the proof
    frame are read from frames_dir."""
    assert spec in SPECS, spec
    fd = DEFAULT_FRAMES if frames_dir is None else pathlib.Path(frames_dir)
    rd = "read_csv_auto" if pairs.endswith(".csv") else "read_parquet"
    con.execute(AFAR_SQL_DOSE.format(frame=fd / f"p1_frame_{field}.csv"))
    con.execute(AFAR_SQL_CH.format(p2=fd / f"p2_becoming_{field}.csv"))
    med = con.execute("SELECT quantile_cont(dose,0.5) FROM dose WHERE dose>0").fetchone()[0]
    # the one line that differs between the specs — build_afar_cut.py's `pos` predicate is `>`
    topic = f"dmin >= {med}" if spec == "med" else "dmin > 0"
    con.execute(AFAR_SQL_PA.format(rd=rd, pairs=pairs))
    rebuilt = con.execute(AFAR_SQL_REBUILD.format(topic=topic, rd=rd, pairs=pairs)).df()
    frozen_path = frozen_frame_path(spec, field, frames_dir)
    frozen = pd.read_parquet(frozen_path)
    a = rebuilt[["grp", "ev", "year", "y", "D"]].sort_values(["grp", "year"]).reset_index(drop=True)
    b = frozen.sort_values(["grp", "year"]).reset_index(drop=True)
    equal = len(a) == len(b) and a.astype("int64").equals(b.astype("int64"))
    assert equal, (f"{field}: rebuilt A_far frame is NOT content-equal to the frozen parquet "
                   f"({len(a)} vs {len(b)} rows) — the map would be unproven, nothing written")
    mp = rebuilt[["ev", "event_id"]].drop_duplicates().sort_values("ev").reset_index(drop=True)
    proof = {"cut": round(float(med), 4) if spec == "med" else 0.0, "rows": len(a),
             "events": len(mp), "content_equal_to_frozen": True}
    if spec != "med":
        proof["predicate"] = topic
        proof["frozen_frame"] = FROZEN_FRAME[spec].format(field=field)
    if frames_dir is not None:
        proof["frozen_frame"] = str(frozen_path)
        proof["frozen_frame_sha256"] = sha(frozen_path)
    return mp, proof


def regen_econ_pairs(scratch: pathlib.Path) -> str:
    """Regenerate the cal pairs_unified.csv (663 MB, not shipped) through the caliber shadow +
    the p2-econ stage (~80 s, needs the data disk). Returns the produced path."""
    import os
    import subprocess
    cal = REPO / "pipeline/stars/caliber_2026-08-28"
    if str(cal) not in sys.path:
        sys.path.insert(0, str(cal))
    import frames_stage as fs  # noqa: PLC0415
    scratch.mkdir(parents=True, exist_ok=True)
    fs.build_shadow(scratch / "shadow")
    stage = scratch / "p2econ"
    if stage.exists():
        import shutil
        shutil.rmtree(stage)
    stage.mkdir()
    env = {**os.environ, "SAR_OUT_ROOT": str(stage), "SAR_LEGACY_THESIS": str(scratch / "shadow")}
    proc = subprocess.run([sys.executable, str(REPO / "pipeline/frames/run_frames.py"),
                           "p2-econ", "--execute"], cwd=REPO, capture_output=True,
                          text=True, env=env)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    out = stage / "frames/p2-econ/econ_fnfix_2026-08-15/data/pairs_unified.csv"
    assert out.is_file(), out
    return str(out)


def stop(msg: str) -> int:
    print(f"AFAR_MAP_STOP {msg}")
    return 2


def preflight(args) -> int:
    """frames-dir mode: every input exists and the econ pairs belong to the frames given (becoming
    check), before anything is written. Returns 0 or the STOP exit code 2."""
    fd, pdir = pathlib.Path(args.frames_dir), pathlib.Path(args.pairs_dir)
    need = [fd / f"{stem}_{f}.{ext}" for f in ("chemistry", "math_stats", "econ")
            for stem, ext in (("p1_frame", "csv"), ("p2_becoming", "csv"), ("p3_afar_pos", "parquet"))]
    need += [pdir / f"pairs_none_{f}.parquet" for f in ("chemistry", "math_stats")]
    for p in need:
        if not p.is_file():
            return stop(f"missing {p}")
    if not args.pairs_econ:
        return stop("missing --pairs-econ (frames-dir mode maps econ from the run's own pairs_unified.csv)")
    pe = pathlib.Path(args.pairs_econ)
    if not pe.is_file():
        return stop(f"missing {pe}")
    becoming = pe.parent / "becoming_unified.csv"
    if not becoming.is_file():
        return stop(f"missing {becoming} (the econ becoming check is mandatory in frames-dir mode)")
    if sha(becoming) != sha(fd / "p2_becoming_econ.csv"):
        return stop(f"{becoming} is not BYTE_EQUAL to {fd / 'p2_becoming_econ.csv'}: the econ pairs beside it "
                    f"are not the chain of the frames given; refusing to map from them")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--pairs-econ", help="regenerated cal pairs_unified.csv (663 MB, not shipped)")
    ap.add_argument("--regen-econ", action="store_true",
                    help="regenerate pairs_unified.csv via the caliber shadow + p2-econ (~80 s, "
                         "data disk required), then map econ from it")
    ap.add_argument("--spec", choices=SPECS, default="med",
                    help="which frozen A_far frame to map and prove against: med = the retired "
                         "median cut (2026-08-29 layout, default); pos = dose > 0, the paper's "
                         "Panel 3 since 2026-08-30 (maps go to data/robustness_2026-09-10_p3pos/)")
    ap.add_argument("--outdir", help=f"default per --spec: {DEFAULT_OUTDIR}")
    ap.add_argument("--tmpdir", help=f"duckdb spill dir (default {DEFAULT_TMPDIR}; required with "
                                     f"--frames-dir: /private does not exist on Linux)")
    ap.add_argument("--frames-dir", help="R1: read p1_frame/p2_becoming/p3_afar_pos_<f> of all three fields "
                                         "from DIR (requires --spec pos; refuses --regen-econ)")
    ap.add_argument("--pairs-dir", help="dir holding pairs_none_<f>.parquet for chemistry/math_stats "
                                        "(default data/cal2026-08-28/frames; required with --frames-dir)")
    ap.add_argument("--threads", type=int, default=6, help="duckdb PRAGMA threads (default 6)")
    ap.add_argument("--memory-limit", default="10GB", help="duckdb PRAGMA memory_limit (default 10GB)")
    args = ap.parse_args(argv)
    if args.threads < 1:
        ap.error(f"--threads must be >= 1, got {args.threads}")
    if not MEMORY_LIMIT.match(args.memory_limit):
        ap.error(f"--memory-limit must look like 10GB / 512MB / 64GiB, got {args.memory_limit!r}")
    frames_dir = None
    if args.frames_dir is not None:
        if args.spec != "pos":
            ap.error("--frames-dir proves against p3_afar_pos_<f>.parquet only: it requires --spec pos")
        if args.regen_econ:
            ap.error("--frames-dir refuses --regen-econ: the econ pairs come from the run's own chain "
                     "(--pairs-econ), never from the October shadow")
        for flag in ("pairs_dir", "outdir", "tmpdir"):
            if getattr(args, flag) is None:
                ap.error(f"--frames-dir requires --{flag.replace('_', '-')}")
        rc = preflight(args)
        if rc:
            return rc
        frames_dir = pathlib.Path(args.frames_dir)
    if args.tmpdir is None:
        args.tmpdir = DEFAULT_TMPDIR
    pairs_dir = DEFAULT_PAIRS_DIR if args.pairs_dir is None else pathlib.Path(args.pairs_dir)
    kw = {} if frames_dir is None else {"frames_dir": frames_dir}
    if args.outdir is None:
        args.outdir = str(REPO / DEFAULT_OUTDIR[args.spec])
    if args.regen_econ and not args.pairs_econ:
        args.pairs_econ = regen_econ_pairs(pathlib.Path(args.tmpdir) / "econ_regen")
    out = pathlib.Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={args.threads}")
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
    pathlib.Path(args.tmpdir).mkdir(parents=True, exist_ok=True)
    con.execute(f"PRAGMA temp_directory='{args.tmpdir}'")
    report: dict = {"generated": GENERATED[args.spec], "fields": {}}
    if args.spec != "med":
        report["spec"] = args.spec
    if frames_dir is not None:
        report["frames_dir"] = str(frames_dir)
        report["pairs"] = {}
        report["duckdb"] = {"threads": args.threads, "memory_limit": args.memory_limit}
    for field in ("chemistry", "math_stats"):
        pairs = str(pairs_dir / f"pairs_none_{field}.parquet")
        if frames_dir is not None:
            report["pairs"][field] = {"path": pairs, "sha256": sha(pathlib.Path(pairs))}
        mp, proof = map_field(con, field, pairs, args.spec, **kw)
        mp.to_csv(out / f"afar_event_map_{field}.csv", index=False)
        report["fields"][field] = proof
        print(f"{field}: {proof}")
    if args.pairs_econ:
        # pin the regeneration to the canon caliber: the same stage run emits becoming_unified,
        # which must be byte-identical to the shipped canon frame
        becoming = pathlib.Path(args.pairs_econ).parent / "becoming_unified.csv"
        canon_becoming = (DEFAULT_FRAMES if frames_dir is None else frames_dir) / "p2_becoming_econ.csv"
        if becoming.is_file():
            got, want = sha(becoming), sha(canon_becoming)
            assert got == want, (
                f"regenerated becoming_unified.csv {got} != shipped canon {want} — the "
                f"pairs_unified beside it is NOT the canon caliber's; refusing to map from it")
            report["econ_becoming_sha_check"] = "BYTE_EQUAL"
        else:
            report["econ_becoming_sha_check"] = "SKIPPED (becoming_unified.csv not beside pairs)"
        report["econ_pairs_sha256"] = sha(pathlib.Path(args.pairs_econ))
        if frames_dir is not None:
            report["pairs"]["econ"] = {"path": args.pairs_econ, "sha256": report["econ_pairs_sha256"]}
        mp, proof = map_field(con, "econ", args.pairs_econ, args.spec, **kw)
        mp.to_csv(out / "afar_event_map_econ.csv", index=False)
        report["fields"]["econ"] = proof
        print(f"econ: {proof}")
    else:
        print("NOTE: --pairs-econ not given; econ map not built (see docstring for the regen)")
        report["econ"] = "NOT BUILT: no pairs_unified.csv given (--pairs-econ / --regen-econ)"
    (out / "afar_event_map_report.json").write_text(
        json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print("AFAR_MAP_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
