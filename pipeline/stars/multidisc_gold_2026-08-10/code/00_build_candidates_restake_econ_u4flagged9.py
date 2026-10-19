import csv, json
# Write out the econ3 results (batch2 by agent; batch1 checked by hand in the main loop: 4 confirmed, 1 fake_merged)
d=json.load(open('/private/tmp/removed-session-directory/tasks/u4_star_events.output'))['result']['results']
manual=[
 {"author_id":"A5001034699","name":"A5001034699","verdict":"confirmed","arrival_true":2017,"post_at_arrival":"","prior_au_detail":"","evidence_urls":[],"refutation_attempt":"","reason":""},
 {"author_id":"A5006190609","name":"A5006190609","verdict":"confirmed","arrival_true":2003,"post_at_arrival":"","prior_au_detail":"","evidence_urls":[],"refutation_attempt":"","reason":""},
 {"author_id":"A5014756434","name":"A5014756434","verdict":"fake_merged_id","arrival_true":None,"post_at_arrival":"","prior_au_detail":"","evidence_urls":[],"refutation_attempt":"","reason":""},
 {"author_id":"A5017960988","name":"A5017960988","verdict":"confirmed","arrival_true":2019,"post_at_arrival":"","prior_au_detail":"","evidence_urls":[],"refutation_attempt":"","reason":""},
 {"author_id":"A5027090359","name":"A5027090359","verdict":"confirmed","arrival_true":2023,"post_at_arrival":"","prior_au_detail":"","evidence_urls":[],"refutation_attempt":"","reason":""},
]
rows=manual+d
cols=['author_id','name','verdict','arrival_true','post_at_arrival','prior_au_detail','evidence_urls','refutation_attempt','reason']
with open('data/poach_fn_recheck_econ_U4flagged9_2026-08-16.csv','w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=cols); w.writeheader()
    for r in rows: r=dict(r); r['evidence_urls']=';'.join(r['evidence_urls']); w.writerow({c:r.get(c) for c in cols})
# Append the candidates (5 confirmed) to the restake candidate table
cand=list(csv.DictReader(open('data/fnfix_candidates_restake.csv'))); cols2=list(cand[0].keys()); have={c['author_id'] for c in cand}
school={'A5001034699':'unsw','A5006190609':'unsw','A5017960988':'unsw','A5027090359':'unsw','A5038001711':'monash'}
for r in rows:
    if r['verdict']=='confirmed' and r['author_id'] not in have:
        cand.append({"author_id":r['author_id'],"name":r['name'],"field":"econ","school":school[r['author_id']],"arrival_true":r['arrival_true'],"arrival_roster":r['arrival_true'],"in_window":True,"post_at_arrival":r['post_at_arrival'][:80]})
with open('data/fnfix_candidates_restake.csv','w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=cols2); w.writeheader(); w.writerows(cand)
print(len(cand))
