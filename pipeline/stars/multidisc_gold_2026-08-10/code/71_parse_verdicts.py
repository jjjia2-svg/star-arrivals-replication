#!/usr/bin/env python3
"""71_parse_verdicts.py <field> <workflow_output.json> — write the manual-check workflow output to CSV + summary"""
import json, csv, sys
from collections import Counter
field, path = sys.argv[1], sys.argv[2]
d = json.load(open(path))["result"]["results"]
cols=['author_id','name','verdict','arrival_true','origin_country_pre','ever_au_fulltime_before','unit_is_dept','id_is_person','evidence_urls','reason']
out=f"data/poach_fn_verdicts_{field}_2026-08-15.csv"
with open(out,'w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=cols); w.writeheader()
    for r in d:
        r=dict(r); r['evidence_urls']=';'.join(r['evidence_urls']); w.writerow({c:r.get(c) for c in cols})
print(field, len(d), dict(Counter(r['verdict'] for r in d)), '→', out)
for r in d:
    if r['verdict'] in ('INCLUDE','UNCERTAIN'):
        print(f"  {r['verdict']:9s} {r['author_id']} {r['name']:28s} arr={r['arrival_true']} | {r['reason'][:150]}")
