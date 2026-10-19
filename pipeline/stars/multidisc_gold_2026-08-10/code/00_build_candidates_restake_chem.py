import csv
rc=list(csv.DictReader(open('data/poach_fn_recheck_chemistry_2026-08-15.csv')))
chk={r['author_id']:r for r in csv.DictReader(open('data/poach_fn_CHECK_chemistry.csv'))}
rows=[]
for r in rc:
    if r['verdict']=='confirmed':
        c=chk[r['author_id']]; school=c['depts'].split(';')[0].replace('_chem','')
        # A5055198364: unsw arrival 2014
        if r['author_id']=='A5055198364': school='unsw'
        inwin = 2005 <= int(c['arrival_roster']) <= 2023
        rows.append({"author_id":r['author_id'],"name":r['name'],"field":"chemistry","school":school,
                     "arrival_true":r['arrival_true'],"arrival_roster":c['arrival_roster'],
                     "in_window":inwin,"post_at_arrival":r['post_at_arrival'][:80]})
with open('data/fnfix_candidates_restake.csv','w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
for r in rows: print(r['author_id'], r['name'], r['school'], r['arrival_true'], 'roster', r['arrival_roster'], 'inwin', r['in_window'])
