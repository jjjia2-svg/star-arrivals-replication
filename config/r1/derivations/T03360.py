import sys,json,glob
K=sys.argv[1]
fin=json.load(open(K+'/papers/cleaning_final.json'))
FIELD={'economics':'econ','chemistry':'chemistry','mathematics_statistics':'math_stats'}
req=[]
for f in json.load(open(K+'/papers/_files.json')):
    p=json.load(open(f)); k=p['key']; c=fin[k]
    Ys={int(r['Y']) for r in p['requests']}
    if p.get('arrival_year'): Ys.add(int(p['arrival_year'])-1)
    for Y in sorted(Ys):
        req.append({'key':f'{k}|Y{Y}','person':k,'ids':p['ids'],'Y':Y,'field':FIELD.get(p['discipline'],p['discipline']),
                    'exclude_wids':c['namesake_wids'],'min_year':None,'cleaning':True})
json.dump(req,open(K+'/rk4in/requests.json','w'),indent=0)
print('requests',len(req),'people',len({r['person'] for r in req}))
