import csv
rc=list(csv.DictReader(open('data/poach_fn_recheck_math_stats_2026-08-15.csv')))
chk={r['author_id']:r for r in csv.DictReader(open('data/poach_fn_CHECK_math_stats.csv'))}
rows=list(csv.DictReader(open('data/fnfix_candidates_restake.csv')))
cols=list(rows[0].keys())
for r in rc:
    if r['verdict']=='confirmed':
        c=chk[r['author_id']]; school=c['depts'].split(';')[0].replace('_mathstats','')
        inwin = 2005 <= int(c['arrival_roster']) <= 2023
        rows.append({"author_id":r['author_id'],"name":r['name'],"field":"math_stats","school":school,
                     "arrival_true":r['arrival_true'],"arrival_roster":c['arrival_roster'],
                     "in_window":inwin,"post_at_arrival":r['post_at_arrival'][:80]})
with open('data/fnfix_candidates_restake.csv','w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=cols); w.writeheader(); w.writerows(rows)
print(len(rows))
for r in rows:
    if r['field']=='math_stats': print(r['author_id'], r['name'], r['school'], r['arrival_true'], 'roster', r['arrival_roster'], r['post_at_arrival'][:50])
