import sys,json,collections
F,K=sys.argv[1:3]
t=open(F).read(); o=json.loads(t[t.find('{'):]); o=o.get('result',o)
if isinstance(o,str): o=json.loads(o)
json.dump(o,open(K+'/q1/q1_result.json','w'),ensure_ascii=False)
P=o['people']; R=[c for r in o['reviews'] for c in r['checks']]
up={c['key']:c for c in R}
print('people',len(P),'missing',o['missing'],'reviews',len(R),'upheld',sum(c['upheld'] for c in R))
print(collections.Counter((p.get('discipline','')[:4],p['decision']) for p in P))
print('--- reinstatements')
for p in P:
    if p['decision'] in ('reinstate','reinstate_if_fellowship_counts'):
        c=up.get(p['key'],{})
        print(f"{'UP ' if c.get('upheld') else 'NO '} {p['decision'][:12]:12} {p.get('discipline','')[:4]} {p['name'][:24]:24} {str(p.get('department'))[:30]:30} {p.get('arrival_year')} {p.get('arrival_post_type','')[:12]:12} p11={p.get('percentile_11school')} nr={p.get('needs_rank')} | {c.get('note','')[:110]}")
