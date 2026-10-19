import csv
cand={r['author_id']:r for r in csv.DictReader(open('data/fnfix_candidates_restake.csv'))}
rs={r['author_id']:r for r in csv.DictReader(open('data/fnfix_restake_2026-08-15.csv'))}
rc={}
for f in ('chemistry','math_stats'):
    for r in csv.DictReader(open(f'data/poach_fn_recheck_{f}_2026-08-15.csv')): rc[r['author_id']]=r
main, wide, drop = [], [], []
for aid,c in cand.items():
    if c['field'] not in ('chemistry','math_stats'): continue
    r=rs[aid]; ok=r['after_pass']=='True'; inwin=c['in_window']=='True'
    borderline = aid=='A5016651378'  # A5016651378 SRF
    row={"field":c['field'],"school":c['school'],"author_id":aid,"display_name":c['name'].split(' (')[0],
         "arrival_corrected":c['arrival_true'],"evidence_grade":"strong",
         "evidence_url":rc[aid]['evidence_urls'].split(';')[0],"signature":"human_web_verified_round2_2026-08-15"}
    if not ok: drop.append((aid,c['name'],'restake_fail',r['after_pct'])); continue
    if borderline: drop.append((aid,c['name'],'borderline_SRF',r['after_pct'])); continue
    (main if inwin else wide).append(row)
cols=["field","school","author_id","display_name","arrival_corrected","evidence_grade","evidence_url","signature"]
with open('data/fnfix_new_events.csv','w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=cols); w.writeheader(); w.writerows(main)
with open('data/fnfix_new_events_wide_extra.csv','w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=cols); w.writeheader(); w.writerows(wide)
print("main", len(main), {f:sum(1 for r in main if r['field']==f) for f in ('chemistry','math_stats')})
print("wide-extra (out of window)", [(r['display_name'],r['arrival_corrected']) for r in wide])
print("dropped", drop)
