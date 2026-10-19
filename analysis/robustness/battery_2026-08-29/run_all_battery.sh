#!/usr/bin/env bash
# analysis/robustness/battery_2026-08-29/run_all_battery.sh — Panel 1 robustness battery
# T1-T4 (2026-08-29), one entry point. Two faithfulness controls first (the driver run with
# nothing changed must be compare_json-EQUAL to the frozen gold in analysis/expected/ —
# proving the prep is the verbatim prep), then the twelve variant cells (T2 bounds x3,
# T2 own-mean x3, T3 levels x3, T4 never-exposed x3), then the 116 leave-one-event-out
# cells for the economics union placebo diagnosis (T1, parallel across BATTERY_JOBS
# processes, default 5), then the ranked LOEO summary CSV, then a sha256 MANIFEST over
# data/robustness_2026-08-29/. Everything is local; no cloud cell is touched.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"; cd "$REPO"
PY="$REPO/setup/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
DRV=analysis/robustness/battery_2026-08-29/run_p1_variant.R
D=data/frames; X=analysis/expected
OUTDIR="${SAR_ROBUST_OUTDIR:-data/robustness_2026-08-29}"   # env override (2026-09-23); old value = default
mkdir -p "$OUTDIR/control/full" "$OUTDIR/control/loeo" "$OUTDIR/loeo" \
         output/battery_tmp output/logs/battery_loeo
LOG="$OUTDIR/runlog_2026-08-29.log"; : > "$LOG"
run() { local out="$1" md="$2" lab="$3"; shift 3
        echo "== $lab" | tee -a "$LOG"
        SAR_OUT="$out" Rscript "$DRV" "$md" "$lab" "$@" >> "$LOG" 2>&1 \
          || { echo "FAILED: $lab — see $LOG"; exit 2; }; }

# control 1 — full mode, variant none: must equal the frozen gold exactly
run "$OUTDIR/control/full" full P1_econ_fnfix "$D/p1_frame_econ.csv" none
"$PY" -m analysis.lib.compare_json "$OUTDIR/control/full/P1_econ_fnfix.json" "$X/P1_econ_fnfix.json" >> "$LOG" 2>&1 \
  && echo "CONTROL EQUAL: full/none vs P1_econ_fnfix" | tee -a "$LOG" \
  || { echo "CONTROL NOT EQUAL: full/none — see $LOG"; exit 3; }

# control 2 — loeo mode, NONE: must equal the union channel of the frozen gold exactly
run "$OUTDIR/control/loeo" loeo P1_econ_fnfix "$D/p1_frame_econ.csv" NONE
"$PY" - <<'PYEOF'
import json
j = json.load(open("analysis/expected/P1_econ_fnfix.json"))
j["channels"] = {"union": j["channels"]["union"]}
json.dump(j, open("output/battery_tmp/P1_econ_fnfix_union_expected.json", "w"))
PYEOF
"$PY" -m analysis.lib.compare_json "$OUTDIR/control/loeo/P1_econ_fnfix.json" \
      output/battery_tmp/P1_econ_fnfix_union_expected.json >> "$LOG" 2>&1 \
  && echo "CONTROL EQUAL: loeo/NONE vs P1_econ_fnfix(union)" | tee -a "$LOG" \
  || { echo "CONTROL NOT EQUAL: loeo/NONE — see $LOG"; exit 3; }
echo "CONTROLS_EQUAL 2/2" | tee -a "$LOG"

# T2 — bounds under the thesis's stated fill rule (zero / person's own average)
for F in econ chemistry math_stats; do
  run "$OUTDIR" full P1bnd0_${F}    "$D/p1_frame_${F}.csv" fill0
  run "$OUTDIR" full P1bndmean_${F} "$D/p1_frame_${F}.csv" fillmean
done
# T3 — output in levels (no log transform)
for F in econ chemistry math_stats; do
  run "$OUTDIR" full P1lvl_${F} "$D/p1_frame_${F}.csv" levels
done
# T4 — comparison pool restricted to never-yet-exposed incumbents
for F in econ chemistry math_stats; do
  run "$OUTDIR" full P1nex_${F} "$D/p1_frame_${F}.csv" neverexp
done

# T1 — leave-one-event-out over ALL 116 economics events equally (one set; no batch
# structure), union channel, parallel
JOBS="${BATTERY_JOBS:-5}"
"$PY" - <<'PYEOF' > output/battery_tmp/loeo_events.txt
import csv
evs = sorted({r["event_id"] for r in csv.DictReader(open("data/frames/p1_frame_econ.csv"))})
print("\n".join(f"{e}|P1loeo_{e.replace(':', '_')}" for e in evs))
PYEOF
N_EV=$(wc -l < output/battery_tmp/loeo_events.txt | tr -d ' ')
echo "== LOEO: $N_EV events, $JOBS parallel jobs" | tee -a "$LOG"
export REPO DRV OUTDIR
# each input line is one whitespace-free word "event_id|label"; xargs passes it as $1
xargs -P "$JOBS" -n 1 bash -c '
  set -euo pipefail; cd "$REPO"
  row="$1"; ev="${row%%|*}"; lab="${row##*|}"
  SAR_OUT="$OUTDIR/loeo" Rscript "$DRV" loeo "$lab" data/frames/p1_frame_econ.csv "$ev" \
    > "output/logs/battery_loeo/$lab.log" 2>&1 \
    || { echo "FAILED: $lab — see output/logs/battery_loeo/$lab.log"; exit 2; }
  echo "done $lab"
' _ < output/battery_tmp/loeo_events.txt | tee -a "$LOG"
N_JSON=$(ls "$OUTDIR/loeo" | grep -c '^P1loeo_.*\.json$')
[ "$N_JSON" -eq "$N_EV" ] || { echo "LOEO INCOMPLETE: $N_JSON/$N_EV"; exit 4; }
echo "LOEO_COMPLETE $N_JSON/$N_EV" | tee -a "$LOG"

# ranked LOEO summary (which single removals move the placebo p most)
"$PY" - <<'PYEOF' | tee -a "$LOG"
import csv, glob, json, os
OUTDIR = os.environ.get("OUTDIR", "data/robustness_2026-08-29")
canon = json.load(open("analysis/expected/P1_econ_fnfix.json"))["channels"]["union"]
led = {r["event_id"]: r for r in csv.DictReader(open("data/frames/p1_events_ledger_econ.csv"))}
rows = []
for f in sorted(glob.glob(f"{OUTDIR}/loeo/P1loeo_*.json")):
    j = json.load(open(f)); u = j["channels"]["union"]; ev = j["loeo_event"]
    plc3 = next((p["est"] for p in u.get("placebos", []) if p["k"] == -3), None)
    L = led.get(ev, {})
    rows.append({"event_id": ev, "star_id": L.get("star_id", ""),
                 "school": L.get("school", ""), "arrival_year": L.get("arrival_year", ""),
                 "ate": u["ate"], "se": u["se"],
                 "p_joint_placebo": u["p_joint_placebo"], "p_joint_effects": u["p_joint_effects"],
                 "delta_ate_vs_canon": u["ate"] - canon["ate"],
                 "delta_p_placebo_vs_canon": u["p_joint_placebo"] - canon["p_joint_placebo"],
                 "placebo_k_minus3_est": plc3, "obs": u["obs"], "events": u["events"]})
rows.sort(key=lambda r: -r["p_joint_placebo"])
for i, r in enumerate(rows): r["rank_by_placebo_p"] = i + 1
cols = ["rank_by_placebo_p", "event_id", "star_id", "school", "arrival_year", "ate", "se",
        "p_joint_placebo", "p_joint_effects", "delta_ate_vs_canon",
        "delta_p_placebo_vs_canon", "placebo_k_minus3_est", "obs", "events"]
with open(f"{OUTDIR}/loeo_ranked.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=cols); w.writeheader()
    for r in rows: w.writerow({k: r[k] for k in cols})
print(f"canon union: ate={canon['ate']:.6f} p_placebo={canon['p_joint_placebo']:.6f}")
print("top 10 removals by placebo p:")
for r in rows[:10]:
    print(f"  {r['rank_by_placebo_p']:>3} {r['event_id']:<18} {r['school']:<12} "
          f"p={r['p_joint_placebo']:.4f} ate={r['ate']:+.4f}")
PYEOF

echo "BATTERY_OK" >> "$LOG"
"$PY" - <<'PYEOF'
import hashlib, os, pathlib
root = pathlib.Path(os.environ.get("OUTDIR", "data/robustness_2026-08-29"))
lines = [f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.as_posix()}"
         for f in sorted(root.rglob("*")) if f.is_file() and f.name != "MANIFEST.sha256"]
(root / "MANIFEST.sha256").write_text("\n".join(lines) + "\n")
print(f"MANIFEST written: {len(lines)} files")
PYEOF
echo "BATTERY_OK"
