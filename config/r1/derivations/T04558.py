import sys,json,re
K=sys.argv[1]
q1=json.load(open(K+'/q1/q1_result.json'))['people']; v3=json.load(open(K+'/v3/verify3_result.json'))['decisions']
F=lambda d:'econ' if str(d).startswith('econ') else ('chemistry' if str(d).startswith('chem') else 'math_stats')
uni={}; req={}
def add(name,ids,arr,disc,src):
    ids=[i for i in re.findall(r'A\d{6,}',str(ids))]
    if not ids or not arr: return
    f=F(disc)
    for i in ids: uni[(i,'econ' if f=='econ' else 'chemmath')]={'author_id':i,'field':'econ' if f=='econ' else 'chemmath'}
    for Y in {int(arr)-1,int(arr)-2}:
        req[f'{src}|{name}|{ids[0]}|{Y}']={'key':f'{src}|{name}|{ids[0]}|{Y}','ids':[ids[0]],'Y':Y,'field':f,'cleaning':False}
for p in q1:
    if p['decision'] in('reinstate','reinstate_if_fellowship_counts','insufficient_evidence') or p.get('needs_rank'):
        add(p['name'],p.get('openalex_id'),p.get('arrival_year'),p.get('discipline'),'q1')
for d in v3:
    if d['decision'] in('add','add_if_alternative_table','needs_author_ruling','insufficient_evidence','already_covered'):
        add(d['name'],d.get('openalex_id'),d.get('arrival_year'),d.get('discipline'),'v3')
json.dump(list(uni.values()),open(K+'/rk5in/extra_universe.json','w')); json.dump(list(req.values()),open(K+'/rk5in/requests.json','w'))
print('extra ids',len(uni),'requests',len(req))
