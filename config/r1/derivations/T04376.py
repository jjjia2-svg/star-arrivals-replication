import sys,json,collections
F,K=sys.argv[1:3]
t=open(F).read(); o=json.loads(t[t.find('{'):]); o=o.get('result',o)
if isinstance(o,str): o=json.loads(o)
json.dump(o,open(K+'/census/census_full.json','w'),ensure_ascii=False)
c=o['census']; print('segments',len(c),'missing',o['missing'])
A=[dict(a,dept=x['dept']) for x in c for a in x['arrivals']]
print('arrivals',len(A),'with openalex id',sum(1 for a in A if a.get('openalex_id')))
print(collections.Counter(a['dept'] for a in A))
print(collections.Counter(a['post_type'] for a in A))
