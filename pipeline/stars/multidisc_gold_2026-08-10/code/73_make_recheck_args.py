#!/usr/bin/env python3
"""73_make_recheck_args.py <field> <field_label> <tag> — build the args JSON of the second-round recheck from the first-round verdicts (printed to stdout)"""
import csv, json, sys
field, label, tag = sys.argv[1], sys.argv[2], sys.argv[3]
rows=[r for r in csv.DictReader(open(f'data/poach_fn_verdicts_{field}_2026-08-15.csv')) if r['verdict'] in ('INCLUDE','UNCERTAIN')]
chk={r['author_id']:r for r in csv.DictReader(open(f'data/poach_fn_CHECK_{field}.csv'))}
people=[]
for r in rows:
    c=chk[r['author_id']]
    people.append({"author_id":r['author_id'],"name":r['name'],"depts":c['depts'],"arrival_roster":c['arrival_roster'],
      "round1_verdict":r['verdict'],"round1_arrival":r['arrival_true'],"round1_origin":r['origin_country_pre'][:80],
      "round1_reason":r['reason'][:280],"round1_urls":';'.join(r['evidence_urls'].split(';')[:2]),
      "au_only":c['au_only'],"mixed":c['mixed'],"ov_only":c['ov_only'],"au_only_first":c['au_only_first']})
sys.stderr.write(f"{field}: {len(people)} people\n")
print(json.dumps({"field":label,"tag":tag,"people":people},ensure_ascii=False,separators=(',',':')))
