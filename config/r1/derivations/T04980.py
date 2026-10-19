import sys,json,collections
F,K=sys.argv[1:3]
t=open(F).read(); o=json.loads(t[t.find('{'):]); o=o.get('result',o)
if isinstance(o,str): o=json.loads(o)
json.dump(o,open(K+'/census/census_verify_result.json','w'),ensure_ascii=False)
D=o['decisions']; R={c['key']:c for r in o['reviews'] for c in r['checks']}
print('decisions',len(D),'missing',o['missing']); print(collections.Counter((d.get('discipline','')[:4],d['decision']) for d in D))
print('reviews',len(R),'upheld',sum(c['upheld'] for c in R.values()))
for d in D:
    if d['decision']=='add':
        c=R.get(d['key'],{})
        print(f"{'UP' if c.get('upheld') else 'NO'} {d.get('discipline','')[:4]} {d['name'][:26]:26} {d.get('department','')[:34]:34} {d.get('arrival_year')} {d.get('arrival_post_type','')[:10]:10} p={d.get('percentile_11school')} ret={d.get('returning_alumnus')} | {c.get('note','')[:110]}")
