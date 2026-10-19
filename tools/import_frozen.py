"""Copy the frozen inputs into place and write data/MANIFEST.sha256. Idempotent. Run: python3 tools/import_frozen.py

Author-only: it reads the author's private working tree (config key legacy_v2_output).

Two source roots since the 2026-08-28 freeze (author approved the caliber rebuild; decision record
not shipped):

  * sources starting with ``cal2026-08-28/`` resolve against THIS repository's ``data/`` — the
    canonical frames/event tables are now the caliber-rebuild artifacts, whose provenance chain
    (staging manifest, run report, accounting, tests) lives under ``data/cal2026-08-28/``;
  * every other source resolves against the read-only legacy ``v2_output/`` tree, exactly as
    before (the pre-caliber canon is kept in the author's private repository (tag ``pre-cal-freeze``)).

``IN_REPO`` lists frozen files that have no external source (added in place at M2/M3); they are
hashed where they stand so the manifest the tool writes is the WHOLE manifest."""
import hashlib, shutil, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from analysis.lib.paths import load_paths

G = "multidisc_gold_2026-08-10"; E = "econ_fnfix_2026-08-15"; C = "cluster_event_2026-08-16"; T = "p3_topicpair_2026-08-17"
FS = "fwci_baseline_fullsnapshot_2026-08-09"; FR = "fwci_fullsnapshot_rebuild_2026-08-09"  # M3 T4
CAL = "cal2026-08-28"                          # resolves against <repo>/data (freeze 2026-08-28)
FROZEN = [
    # frames (analysis-layer inputs). Canonical = the caliber rebuild (freeze 2026-08-28); the
    # one exception is speed_bracket, which has NO cal builder (pipeline/NOT_REPRODUCIBLE.md) and
    # stays the pre-caliber artifact, flagged in the register pending the Task-8 paper decision.
    ("data/frames/p1_frame_econ.csv",                 f"{CAL}/frames/p1_frame_econ.csv"),
    ("data/frames/p1_frame_chemistry.csv",            f"{CAL}/frames/p1_frame_chemistry.csv"),
    ("data/frames/p1_frame_math_stats.csv",           f"{CAL}/frames/p1_frame_math_stats.csv"),
    ("data/frames/p1_frame_econ_old79.csv",           f"{CAL}/frames/p1_frame_econ_old79.csv"),
    ("data/frames/p1_frame_econ_new37.csv",           f"{CAL}/frames/p1_frame_econ_new37.csv"),
    ("data/frames/p2_becoming_econ.csv",              f"{CAL}/frames/p2_becoming_econ.csv"),
    ("data/frames/p2_becoming_chemistry.csv",         f"{CAL}/frames/p2_becoming_chemistry.csv"),
    ("data/frames/p2_becoming_math_stats.csv",        f"{CAL}/frames/p2_becoming_math_stats.csv"),
    ("data/frames/p3_slim_econ.parquet",              f"{CAL}/frames/p3_slim_econ.parquet"),
    ("data/frames/p3_slim_chemistry.parquet",         f"{CAL}/frames/p3_slim_chemistry.parquet"),
    ("data/frames/p3_slim_math_stats.parquet",        f"{CAL}/frames/p3_slim_math_stats.parquet"),
    ("data/frames/p3_slim_ev_econ.parquet",           f"{CAL}/frames/p3_slim_ev_econ.parquet"),
    ("data/frames/p3_slim_ev_chemistry.parquet",      f"{CAL}/frames/p3_slim_ev_chemistry.parquet"),
    ("data/frames/p3_slim_ev_math_stats.parquet",     f"{CAL}/frames/p3_slim_ev_math_stats.parquet"),
    ("data/frames/p3_afar_econ.parquet",              f"{CAL}/frames/p3_afar_econ.parquet"),
    ("data/frames/p3_afar_chemistry.parquet",         f"{CAL}/frames/p3_afar_chemistry.parquet"),
    ("data/frames/p3_afar_math_stats.parquet",        f"{CAL}/frames/p3_afar_math_stats.parquet"),
    ("data/frames/p1_events_ledger_econ.csv",         f"{CAL}/frames/p1_events_ledger_econ.csv"),
    ("data/frames/p3_afar_counts.csv",                f"{CAL}/frames/p3_afar_counts.csv"),
    ("data/frames/p3_afar_speed_bracket.csv",         f"{T}/data/speed_bracket.csv"),
    ("data/frames/p3_afar_tau_profile.csv",           f"{CAL}/frames/p3_afar_tau_profile.csv"),
    # verified human inputs (cannot be regenerated)
    ("data/raw_verified/roster_econ_verified.parquet",     "econ_roster_verify_2026-08-09/roster_clean_11school_verified.parquet"),
    ("data/raw_verified/roster_chemmath_verified.parquet", "multidisc_roster_econ_grade_2026-08-09/roster_clean_chemmath_verified.parquet"),
    ("data/raw_verified/roster_gold_chemistry.parquet",    f"{G}/data/fnfix/roster_gold_chemistry.parquet"),
    ("data/raw_verified/roster_gold_math_stats.parquet",   f"{G}/data/fnfix/roster_gold_math_stats.parquet"),
    ("data/raw_verified/events_econ_new38.csv",            f"{E}/data/new_events_econ.csv"),
    ("data/raw_verified/events_chemistry_fnfix.csv",       f"{G}/data/events_chemistry_fnfix_2026-08-10.csv"),
    ("data/raw_verified/events_math_stats_fnfix.csv",      f"{G}/data/events_math_stats_fnfix_2026-08-10.csv"),
    # the 2026-08-28 approved event tables (canonical since the freeze; the three tables above are
    # the pre-caliber signed set, kept in place — see data/raw_verified/README.md)
    ("data/raw_verified/events_econ_cal2026-08-28.csv",       f"{CAL}/events_econ_cal.csv"),
    ("data/raw_verified/events_chemistry_cal2026-08-28.csv",  f"{CAL}/events_chemistry_cal.csv"),
    ("data/raw_verified/events_math_stats_cal2026-08-28.csv", f"{CAL}/events_math_stats_cal.csv"),
    ("data/raw_verified/event_ledger_econ79.csv",          "event_ledger_2026-07-27/event_ledger_79_2026-07-27.csv"),
    ("data/raw_verified/edges_supplement_econ_fnfix.jsonl", f"{E}/data/edges_supplement_fnfix.jsonl"),
    ("data/raw_verified/relationships_econ.csv",           f"{E}/data/relationships.csv"),
    # M3 Task 5 (fix wave): the incfel rung of the chem/math population ladder. It is the INPUT to
    # 00c, whose outputs are the two frozen gold rosters above, and it is now also reproducible -
    # `pipeline/rosters/run_rosters.py incfel` rebuilds both content-equal from the recovered
    # producer. Frozen anyway, at 13 KB, so the `final` stage has its input pinned by sha256 rather
    # than only by a rebuild, and so the ladder's middle rung is inspectable from the package.
    ("data/raw_verified/incfel/roster_gold_chemistry.parquet",  f"{G}/data/incfel/roster_gold_chemistry.parquet"),
    ("data/raw_verified/incfel/roster_gold_math_stats.parquet", f"{G}/data/incfel/roster_gold_math_stats.parquet"),
    # FWCI (M3 Task 4). The world field baseline and the expected table every frozen P1 frame's FWCI
    # denominator comes from. Legacy basenames are kept: 01_build_expected_full.py hard-codes them,
    # so the rebuild lands on the same name and the comparison needs no mapping table.
    ("data/fwci/fwci_baseline_pop_full.parquet",           f"{FS}/data/fwci_baseline_pop_full.parquet"),
    ("data/fwci/scan_manifest.json",                       f"{FS}/data/scan_manifest.json"),
    ("data/fwci/gate_a_reconcile.json",                    f"{FS}/data/gate_a_reconcile.json"),
    ("data/fwci/gate_b_cell_recount.json",                 f"{FS}/data/gate_b_cell_recount.json"),
    # the scan's own console log: the ONLY surviving source for the measured runtime (37.0 min),
    # the worker count, the throughput and the streamed gz_bytes. Frozen so run_fwci.py can build
    # its cost warning FROM the record instead of restating it (T4 review NIT-1).
    ("data/fwci/scan_full_2026-08-09.log",                 f"{FS}/logs/scan_full_2026-08-09.log"),
    ("data/fwci/fwci_expected_fullsnapshot_2026-08-09.parquet", f"{FR}/data/fwci_expected_fullsnapshot_2026-08-09.parquet"),
    ("data/fwci/fwci_expected_oldpop_2026-08-09.parquet",  f"{FR}/data/fwci_expected_oldpop_2026-08-09.parquet"),
    ("data/fwci/econ_units_2026-08-09.parquet",            f"{FR}/data/econ_units_2026-08-09.parquet"),
    ("data/fwci/g_step1_expected.json",                    f"{FR}/data/g_step1_expected.json"),
    ("data/fwci/g_c_old_vs_new.json",                      f"{FR}/data/g_c_old_vs_new.json"),
    # archived estimates (everything the paper cites, incl. cloud-only runs)
    ("data/estimates/P3evcl_econ.json",                    f"{C}/results/out/P3evcl_econ.json"),
    ("data/estimates/P3evcl_chemistry.json",               f"{C}/results/out/P3evcl_chemistry.json"),
    ("data/estimates/P1_econ920_no_zeroroster.json",       "econ_final_2026-08-13/results/out/P1_econ920_no_zeroroster.json"),
    ("data/estimates/summary_event_cluster_2026-08-16.json", f"{C}/results/summary_event_cluster_2026-08-16.json"),
    # cloud chain-of-custody (P3 main: econ + chem on r6i.16xlarge)
    ("pipeline/aws/logs/p3_main_2026-08-16/payload.md5",            f"{E}/aws/payload.md5"),
    ("pipeline/aws/logs/p3_main_2026-08-16/watcher.log",            f"{E}/aws/watcher.log"),
    ("pipeline/aws/logs/p3_main_2026-08-16/launch_time_utc.txt",    f"{E}/aws/launch_time_utc.txt"),
    ("pipeline/aws/logs/p3_main_2026-08-16/terminate_time_utc.txt", f"{E}/aws/terminate_time_utc.txt"),
    ("pipeline/aws/logs/p3_main_2026-08-16/driver.sh",              f"{E}/aws/driver.sh"),
    ("pipeline/aws/logs/p3_main_2026-08-16/bootstrap.sh",           f"{E}/aws/bootstrap.sh"),
    ("pipeline/aws/logs/p3_main_2026-08-16/run_p3.R",               f"{E}/aws/run_p3.R"),
    ("pipeline/aws/logs/p3_evcl_2026-08-16/payload.md5",            f"{C}/aws/payload.md5"),
    ("pipeline/aws/logs/p3_evcl_2026-08-16/watcher.log",            f"{C}/aws/watcher.log"),
    ("pipeline/aws/logs/p3_evcl_2026-08-16/driver.sh",              f"{C}/aws/driver.sh"),
    ("pipeline/aws/logs/p3_evcl_2026-08-16/run_p3_evcl.R",          f"{C}/aws/run_p3_evcl.R"),
]
# The EC2 fetch/ directories (result JSONs + time logs) are copied whole by copy_dir below.
COPY_DIRS = [("pipeline/aws/logs/p3_main_2026-08-16/fetch", f"{E}/aws/fetch"),
             ("pipeline/aws/logs/p3_evcl_2026-08-16/fetch", f"{C}/aws/fetch")]

# Frozen files with no external source: added in place (M2 froze the paper inputs; M3 froze the
# reconstructed U4 star-event verdict payload). Hashed where they stand, so the manifest this tool writes is
# complete — before the 2026-08-28 freeze their five lines were appended outside this tool.
IN_REPO = [
    "data/stage_payloads/u4_star_events.json",
    "data/paper_inputs/NULL_chemistry_A_far.json",
    "data/paper_inputs/NULL_econ_A_far.json",
    "data/paper_inputs/attrition.csv",
    "data/paper_inputs/dose_context.json",
    # Freeze-wave Task 8: the PRE-caliber speed bracket, kept wholesale because it has no caliber
    # builder (NOT_REPRODUCIBLE row 9) — extracted verbatim from the thesis's frozen 2026-08-22
    # ledger; see the file's _provenance and analysis/paper/ledger_p3afar.py.
    "data/paper_inputs/speed_bracket_precal_2026-08-22.json",
]

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def copy_frozen(src, out, label):
    """Copy src to out (creating parent dirs), refusing if out already exists with a hash
    that differs from src's — frozen inputs must never silently change. `label` is the
    repo-relative path used in messages (matches the manifest line). Returns out's sha256."""
    if not src.exists(): sys.exit(f"MISSING source: {src}")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and sha(out) != sha(src):
        sys.exit(f"REFUSE: {label} differs from legacy source; frozen inputs do not change")
    shutil.copy2(src, out)
    return sha(out)

def main():
    p = load_paths(); root = p["repo_root"]; v2 = p["legacy_v2_output"]
    lines = []
    for dest, rel in FROZEN:
        # cal2026-08-28/... sources are IN THIS REPOSITORY (the 2026-08-28 freeze); everything
        # else still comes from the read-only legacy tree.
        src = (root / "data" / rel) if rel.startswith("cal2026-08-28/") else (v2 / rel)
        out = root / dest
        h = copy_frozen(src, out, dest)
        lines.append(f"{h}  {dest}")
    for dest, rel in COPY_DIRS:
        src = v2 / rel
        if not src.is_dir(): sys.exit(f"MISSING source dir: {src}")
        for f in sorted(src.rglob("*")):
            if f.is_file():
                out = root / dest / f.relative_to(src)
                label = str(out.relative_to(root))
                h = copy_frozen(f, out, label)
                lines.append(f"{h}  {label}")
    for dest in IN_REPO:
        f = root / dest
        if not f.is_file(): sys.exit(f"MISSING in-repo frozen file: {dest}")
        lines.append(f"{sha(f)}  {dest}")
    (root / "data" / "MANIFEST.sha256").write_text("\n".join(lines) + "\n")
    print(f"imported {len(lines)} files; manifest written")

if __name__ == "__main__": main()
