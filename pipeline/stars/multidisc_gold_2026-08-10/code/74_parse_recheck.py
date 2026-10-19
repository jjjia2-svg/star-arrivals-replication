#!/usr/bin/env python3
"""74_parse_recheck.py <field> <workflow_output.json> — write the second-round recheck to CSV + summary"""
import json, csv, sys
from collections import Counter
field, path = sys.argv[1], sys.argv[2]
d = json.load(open(path))["result"]["results"]
cols=['author_id','name','verdict','arrival_true','post_at_arrival','prior_au_detail','evidence_urls','refutation_attempt','reason']
out=f"data/poach_fn_recheck_{field}_2026-08-15.csv"
with open(out,'w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=cols); w.writeheader()
    for r in d:
        r=dict(r); r['evidence_urls']=';'.join(r['evidence_urls']); w.writerow({c:r.get(c) for c in cols})
print(field, len(d), dict(Counter(r['verdict'] for r in d)), '→', out)
for r in d:
    print(f"  {r['verdict']:26s} {r['author_id']} {r['name'][:26]:26s} arr={r['arrival_true']} | {r['post_at_arrival'][:60]} | prior: {r['prior_au_detail'][:70]}")
