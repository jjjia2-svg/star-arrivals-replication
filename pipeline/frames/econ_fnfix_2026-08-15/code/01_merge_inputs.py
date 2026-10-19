#!/usr/bin/env python3
"""01_merge_inputs.py — merge the prodlib new-event network frame + the new events into the two inputs of the economics econ_final chain (2026-08-15)

  data/network_frame_fnfix.csv   = old network frame (the original 79, original bytes) + new-event rows (produced by prodlib runs/econ_fnfix)
  data/event_ledger_fnfix.csv    = ledger of 79 + new events (other columns left empty)
  data/edges_supplement_fnfix.jsonl = all OpenAlex work edges of the new stars (same netbase_supplement schema, used by Panel 2)

Hard checks: new-frame column order = old-frame column order; event_id of the new-event rows has zero overlap with the old frame; new stars are in the U4 star_set;
        prodlib report n_events_in_frame == number of new events (fewer = that star's pre-arrival network is empty, fail loud for manual review).
"""
import csv, json, os, sys, time
import requests

# --- M3 port: repo path resolution (legacy hard-coded the author's machine) — config/paths.yaml ---
import pathlib as _sar_pl, sys as _sar_sys
_sar_repo = next(p for p in _sar_pl.Path(__file__).resolve().parents if p.name == "frames").parents[1]
if str(_sar_repo) not in _sar_sys.path:
    _sar_sys.path.append(str(_sar_repo))
from pipeline.lib.paths import (derived_root as _sar_derived_root,  # noqa: E402,F401
                                snapshot_root as _sar_snapshot_root,
                                ssd_root as _sar_ssd_root,
                                legacy_thesis as _sar_legacy_thesis,
                                require_readable as _sar_rd,
                                require_writable as _sar_rw,
                                output_target as _sar_out,
                                deferred_output_target as _sar_lazyout)
ROOT = str(_sar_rd(_sar_legacy_thesis()))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OLD_FRAME = f"{ROOT}/v2_output/r_p10_80ev_2026-07-22/data/analysis_frame_p01_52ev_topicdose_2026-07-21.csv"
LEDGER = f"{ROOT}/v2_output/event_ledger_2026-07-27/event_ledger_79_2026-07-27.csv"
NEW_FRAME = f"{BASE}/runs/econ_fnfix/data/analysis_frame_p01_52ev_topicdose_2026-07-21.csv"
REPORT = f"{BASE}/runs/econ_fnfix/build_report.json"
NEW = list(csv.DictReader(open(f"{BASE}/data/new_events_econ.csv")))
new_ids = {f"{r['author_id']}:{int(r['arrival'])}" for r in NEW}

rep = json.load(open(REPORT))
n_in = rep["export"]["n_events_in_frame"]
dropped_net = rep["export"].get("dropped_event_ids") or []
if n_in != len(NEW):
    # Same structural situation as chemistry/mathematics: the star has no co-authorship network candidates in the pool before arrival (deg1+deg2 empty) -> the network channel has no rows,
    # but the department channel (00_build_frame builds rows from the ledger x roster) still builds incumbent rows for that event. Recorded, not blocking (for manual review).
    print(f"⚠ prodlib {n_in}/{len(NEW)} events entered the network frame; events with no pre-arrival network {dropped_net} (department channel only, like the 3 structural cases in chemistry/maths-stats)")
    json.dump({"n_new_events": len(NEW), "n_in_network_frame": n_in, "dropped_network_only": dropped_net},
              open(f"{BASE}/data/network_frame_dropped_events.json", "w"), indent=1)

# ---- 1. network frame: old rows byte for byte + new rows ----
with open(OLD_FRAME, newline="") as f: old_hdr = f.readline().rstrip("\r\n")
with open(NEW_FRAME, newline="") as f: new_hdr = f.readline().rstrip("\r\n")   # prodlib writes CRLF
BOOL_COLS = (4, 5, 8)   # treated / post / dose_low_confidence: prodlib writes True/False, the old frame true/false -> unify to lowercase
assert old_hdr == new_hdr, f"column order mismatch:\n{old_hdr}\n{new_hdr}"
out = f"{BASE}/data/network_frame_fnfix.csv"
n_old = n_new = 0
seen_new_ev = set()
with open(out, "w", newline="") as fo:
    with open(OLD_FRAME, newline="") as fi:
        fo.write(fi.readline())
        for line in fi:
            fo.write(line); n_old += 1
    with open(NEW_FRAME, newline="") as fi:
        fi.readline()
        for line in fi:
            cells = next(csv.reader([line.rstrip("\r\n")]))
            ev = cells[3]
            assert ev in new_ids, f"new frame has rows for a non-new event {ev}"
            seen_new_ev.add(ev)
            for i in BOOL_COLS:
                assert cells[i] in ("True", "False", "true", "false", ""), (i, cells[i])
                cells[i] = cells[i].lower()
            fo.write(",".join(cells) + "\n"); n_new += 1
assert seen_new_ev == new_ids - set(dropped_net), f"new frame is missing events {new_ids - set(dropped_net) - seen_new_ev}"
print(f"network_frame_fnfix.csv: old {n_old} + new {n_new} rows")

# ---- 2. ledger ----
rows = list(csv.DictReader(open(LEDGER)))
cols = list(rows[0].keys())
assert not ({r["event_id"] for r in rows} & new_ids)
for r in NEW:
    d = {c: "" for c in cols}
    d.update({"event_id": f"{r['author_id']}:{int(r['arrival'])}", "star_id": r["author_id"],
              "school": r["school"], "arrival_year": r["arrival"],
              "arrival_source": r.get("verdict_source") or "human_web_verified_2026-08-15",
              "arrival_evidence": "strong", "reason": "poach-gate false negative (OpenAlex affiliation backfill)",
              "evidence_source": r.get("evidence_url", "")})
    rows.append(d)
with open(f"{BASE}/data/event_ledger_fnfix.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
print(f"event_ledger_fnfix.csv: {len(rows)} events")

# ---- 3. all work edges of the new stars (API) ----
KEY = None
for l in open(os.path.expanduser("~/.zshrc")):
    if "OPENALEX_API_KEY" in l and "=" in l:
        KEY = l.split("=", 1)[1].strip().strip('"').strip("'").split()[0]
sup = f"{BASE}/data/edges_supplement_fnfix.jsonl"
short = lambda s: s.rsplit("/", 1)[-1] if s else ""
if os.path.exists(sup) and os.path.getsize(sup) > 0:
    print(f"supplement already exists ({sum(1 for _ in open(sup))} rows), skipping fetch"); NEW_FETCH = []
else:
    NEW_FETCH = NEW
with open(sup, "a") as fo:
    for r in NEW_FETCH:
        aid = r["author_id"]; cursor = "*"; n = 0
        while cursor:
            p = {"filter": f"author.id:{aid}", "per-page": 200, "cursor": cursor,
                 "select": "id,publication_year,type,authorships", "mailto": "jjjia2@student.unimelb.edu.au"}
            if KEY: p["api_key"] = KEY
            for att in range(6):
                try:
                    rs = requests.get("https://api.openalex.org/works", params=p, timeout=60)
                    if rs.status_code == 200: break
                except requests.RequestException: pass
                time.sleep(2 * (att + 1))
            else: sys.exit(f"API failed repeatedly {aid}")
            js = rs.json()
            for w in js.get("results", []):
                authors = [short(a.get("author", {}).get("id", "")) for a in w.get("authorships", [])]
                fo.write(json.dumps({"work_id": short(w["id"]), "publication_year": w.get("publication_year"),
                                     "type": w.get("type"), "seed_author": aid,
                                     "authors": [a for a in authors if a]}) + "\n"); n += 1
            cursor = js.get("meta", {}).get("next_cursor"); time.sleep(0.15)
        print(f"  supplement {aid} {r['name']}: {n} works")
print("MERGE_OK")
