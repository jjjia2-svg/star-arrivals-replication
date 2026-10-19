#!/usr/bin/env python3
"""60_lb_tau.py — left-behind people: first-link rate of each cell by event time, year by year (is there a break in the arrival year?)"""
import os, csv, duckdb, json
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
man=json.load(open(f"{BASE}/data/lb_manifest.json"))
con=duckdb.connect(); con.execute("PRAGMA threads=6"); con.execute("PRAGMA memory_limit='14GB'")
con.execute(f"PRAGMA temp_directory='{BASE}/data/_duck_tmp'")
rows=[]
for key,m in man.items():
    field,cell=key.split("|")
    if cell not in ("A_far","A_near","B_nn","B_any"): continue
    # event time: D = post, but slim has no tau; rebuild it as year - the event's first post year
    q=f"""WITH ay AS (SELECT ev, min(year) a FROM read_parquet('{m["file"]}') WHERE D=1 GROUP BY 1)
          SELECT p.year-ay.a AS tau, count(*) n, sum(p.y) t
          FROM read_parquet('{m["file"]}') p JOIN ay USING (ev)
          WHERE p.year-ay.a BETWEEN -6 AND 6 GROUP BY 1 ORDER BY 1"""
    prof=con.execute(q).fetchall()
    for tau,n,t in prof:
        rows.append(dict(field=field,cell=cell,tau=tau,rows=n,ties=t,rate_pp=round(100.0*t/n,4)))
    print(f"{field:10s} {cell:6s}: " + " ".join(f"{100.0*t/n:5.3f}" for _,n,t in prof), flush=True)
with open(f"{BASE}/data/lb_tau_profile.csv","w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print("→ data/lb_tau_profile.csv  (columns = tau -6..+6)")
