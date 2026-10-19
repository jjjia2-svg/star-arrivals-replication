import csv
new_ev={f"{r['author_id']}:{int(r['arrival'])}" for r in csv.DictReader(open('data/new_events_econ.csv'))}
src='data/analysis_frame_econ920_unified_fullsnap_2026-08-13.csv'
rows=list(csv.DictReader(open(src))); cols=list(rows[0].keys())
for tag,keep in (('old79', lambda r: r['event_id'] not in new_ev), ('new38', lambda r: r['event_id'] in new_ev)):
    with open(f'data/analysis_frame_econ_fnfix_{tag}.csv','w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols); w.writeheader(); n=0
        for r in rows:
            if keep(r): w.writerow(r); n+=1
    print(tag, n)
