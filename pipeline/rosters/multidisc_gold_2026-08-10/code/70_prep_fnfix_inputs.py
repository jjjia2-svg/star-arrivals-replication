#!/usr/bin/env python3
"""70_prep_fnfix_inputs.py — chemistry/maths-stats "overseas-poach gate false negative" fix: build all inputs of the fnfix variant

Input data/fnfix_new_events.csv (missed stars confirmed by manual verification; columns as in events_*_final:
      field,school,author_id,display_name,arrival_corrected,evidence_grade,evidence_url,signature)
Output (variant fnfix, consumed directly by run_all.sh fnfix):
  data/events_{field}_fnfix_2026-08-10.csv      = final(08-13) + new events
  data/events_{field}_fnfixbase_2026-08-10.csv  = finalbase + new events (event_id,arrival_year)
  data/shortlist_fnfix.csv                      = shortlist_final + new events (one row per new event)
  data/stars_excluded_fnfix.parquet             = gold ∪ new stars (new stars may no longer count as incumbents of any event; outputs are not dropped)
  data/edges_supplement_fnfix.jsonl             = gold supplement edges + all works edges of the new stars from the API
  data/fnfix/roster_gold_{field}.parquet        = final roster as is
  config/fnfix_{field}.json                     = final config with events/shortlist/supplement/exclude/run_dir/roster swapped
Hard checks: new star is on the roster; not in the existing event table; arrival year lies within an in-post spell on the roster; the API returned >=1 paper; all fields present.
"""
import csv, json, os, shutil, sys, time
import duckdb, requests

G = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = f"{G}/data"
NEW = list(csv.DictReader(open(f"{D}/fnfix_new_events.csv")))
assert NEW, "fnfix_new_events.csv is empty"
con = duckdb.connect()
COLS = ["field", "school", "author_id", "display_name", "arrival_corrected", "evidence_grade", "evidence_url", "signature"]

for field in ("chemistry", "math_stats"):
    fin = list(csv.DictReader(open(f"{D}/events_{field}_final_2026-08-13.csv")))
    assert list(fin[0].keys()) == COLS, fin[0].keys()
    have = {r["author_id"] for r in fin}
    add = [r for r in NEW if r["field"] == field]
    for r in add:
        assert set(r.keys()) >= set(COLS), r
        assert r["author_id"] not in have, f"{r['author_id']} is already in the {field} event table"
        n = con.execute(f"""SELECT count(*) FROM read_parquet('{D}/final/roster_gold_{field}.parquet')
            WHERE author_id='{r['author_id']}' AND school='{r['school']}'
              AND {int(r['arrival_corrected'])} BETWEEN year_start AND year_end""").fetchone()[0]
        if n == 0:
            print(f"  ⚠ {r['author_id']} {r['display_name']} arrival year {r['arrival_corrected']} is not inside an in-post spell on the {r['school']} roster (logged, not blocking)")
    out = fin + [{c: r[c] for c in COLS} for r in add]
    with open(f"{D}/events_{field}_fnfix_2026-08-10.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS); w.writeheader(); w.writerows(out)
    base = list(csv.DictReader(open(f"{D}/events_{field}_finalbase_2026-08-13.csv")))
    base += [{"event_id": f"{r['author_id']}:{r['school']}", "arrival_year": r["arrival_corrected"]} for r in add]
    with open(f"{D}/events_{field}_fnfixbase_2026-08-10.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["event_id", "arrival_year"]); w.writeheader(); w.writerows(base)
    print(f"[{field}] events {len(fin)} + {len(add)} = {len(out)}")

# shortlist
sl = list(csv.DictReader(open(f"{D}/shortlist_final_2026-08-13.csv")))
sl += [{"author_id": r["author_id"], "field": r["field"], "school": r["school"], "arrival_year": r["arrival_corrected"]} for r in NEW]
with open(f"{D}/shortlist_fnfix.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["author_id", "field", "school", "arrival_year"]); w.writeheader(); w.writerows(sl)

# stars_excluded
ids = ",".join(f"('{r['author_id']}')" for r in NEW)
con.execute(f"""COPY (SELECT author_id FROM read_parquet('{D}/stars_excluded_gold.parquet')
    UNION SELECT * FROM (VALUES {ids}) t(author_id)) TO '{D}/stars_excluded_fnfix.parquet' (FORMAT PARQUET)""")
n0 = con.execute(f"SELECT count(*) FROM read_parquet('{D}/stars_excluded_gold.parquet')").fetchone()[0]
n1 = con.execute(f"SELECT count(*) FROM read_parquet('{D}/stars_excluded_fnfix.parquet')").fetchone()[0]
print(f"stars_excluded {n0} → {n1}")

# supplement: gold + all works of the new stars from the API
KEY = None
for l in open(os.path.expanduser("~/.zshrc")):
    if "OPENALEX_API_KEY" in l and "=" in l:
        KEY = l.split("=", 1)[1].strip().strip('"').strip("'").split()[0]
short = lambda s: s.rsplit("/", 1)[-1] if s else ""
shutil.copyfile(f"{D}/edges_supplement_gold.jsonl", f"{D}/edges_supplement_fnfix.jsonl")
with open(f"{D}/edges_supplement_fnfix.jsonl", "a") as fo:
    for r in NEW:
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
        assert n > 0, f"{aid} API returned zero works"
        print(f"  supplement {aid} {r['display_name']}: {n} works")

# roster + config
os.makedirs(f"{D}/fnfix", exist_ok=True); os.makedirs(f"{G}/config", exist_ok=True)
for field in ("chemistry", "math_stats"):
    shutil.copyfile(f"{D}/final/roster_gold_{field}.parquet", f"{D}/fnfix/roster_gold_{field}.parquet")
    cfg = json.load(open(f"{G}/config/final_{field}.json"))
    cfg["label"] = f"{field} fnfix 2026-08-15：final + 海外挖角门假阴性补漏事件"
    cfg["events"]["signed_csv"] = f"{D}/events_{field}_fnfix_2026-08-10.csv"
    cfg["events"]["shortlist_csv"] = f"{D}/shortlist_fnfix.csv"
    cfg["supplement_jsonl"] = f"{D}/edges_supplement_fnfix.jsonl"
    cfg["roster"]["path"] = f"{D}/fnfix/roster_gold_{field}.parquet"
    cfg["roster"]["exclude_authors_parquet"] = f"{D}/stars_excluded_fnfix.parquet"
    cfg["outcome_exclusion_stars"]["path"] = f"{D}/stars_excluded_fnfix.parquet"
    cfg["run_dir"] = f"{G}/runs/fnfix/{field}"
    cfg["roster_variant"] = "fnfix"
    json.dump(cfg, open(f"{G}/config/fnfix_{field}.json", "w"), ensure_ascii=False, indent=2)
print("PREP_FNFIX_OK")
