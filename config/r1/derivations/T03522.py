import sys,json
F,K=sys.argv[1:3]
t=open(F).read(); o=json.loads(t[t.find('{'):]); o=o.get('result',o)
if isinstance(o,str): o=json.loads(o)
json.dump(o,open(K+'/v3/verify3_result.json','w'),ensure_ascii=False)
for r in o['reviews']:
    for c in r['checks']: print('UPHELD' if c['upheld'] else 'NOT   ', c['name'],'|',c['note'][:420].replace('\n',' '))
