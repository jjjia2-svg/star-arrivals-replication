#!/usr/bin/env python3
"""76_parse_adjudication.py <tag> <workflow_output.json> — write paper-by-paper judgements: verify/fnfix_adjudication_<tag>.csv + append to verify/fnfix_work_level_calls.csv"""
import json, csv, sys, os
tag, path = sys.argv[1], sys.argv[2]
d = json.load(open(path))["result"]
adj, calls = d["adjudications"], d["work_calls"]
cols=['author_id','name','verdict','n_pre_works','n_mine','n_not_mine','n_uncertain','contaminating_citations','contaminating_share','split_ids','identity_anchor','evidence_urls']
with open(f"verify/fnfix_adjudication_{tag}.csv","w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=cols); w.writeheader()
    for a in adj: a=dict(a); a['evidence_urls']=';'.join(a['evidence_urls']); w.writerow({c:a.get(c) for c in cols})
p="verify/fnfix_work_level_calls.csv"; new=not os.path.exists(p)
with open(p,"a",newline="") as f:
    w=csv.DictWriter(f,fieldnames=['author_id','work_id','is_mine','reason'])
    if new: w.writeheader()
    for c in calls: w.writerow({k:c.get(k) for k in ['author_id','work_id','is_mine','reason']})
print(tag, len(adj), "stars;", len(calls), "false/uncertain calls")
for a in adj:
    print(f"  {a['verdict']:9s} {a['author_id']} {a['name'][:24]:24s} pre={a['n_pre_works']} not_mine={a['n_not_mine']} unc={a['n_uncertain']} contam={a['contaminating_citations']} ({a['contaminating_share']:.1%}) split={a['split_ids'][:70]}")
