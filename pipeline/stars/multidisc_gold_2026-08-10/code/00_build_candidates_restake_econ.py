import csv
rc=list(csv.DictReader(open('data/poach_fn_recheck_econ_2026-08-15.csv')))
chk={r['author_id']:r for r in csv.DictReader(open('data/poach_fn_CHECK_econ.csv'))}
rows=list(csv.DictReader(open('data/fnfix_candidates_restake.csv')))
cols=list(rows[0].keys()); have={r['author_id'] for r in rows}
n=0
for r in rc:
    if r['verdict']=='confirmed' and r['author_id'] not in have:
        c=chk[r['author_id']]; school=c['depts'].split(';')[0].replace('_econ','')
        rows.append({"author_id":r['author_id'],"name":r['name'],"field":"econ","school":school,
                     "arrival_true":r['arrival_true'],"arrival_roster":c['arrival_roster'],
                     "in_window":1999<=int(r['arrival_true'])<=2024,"post_at_arrival":r['post_at_arrival'][:80]}); n+=1
with open('data/fnfix_candidates_restake.csv','w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=cols); w.writeheader(); w.writerows(rows)
print("added econ", n, "total", len(rows))
open('data/_fnfix_ids_econ.txt','w').write('\n'.join(r['author_id'] for r in rows if r['field']=='econ'))
