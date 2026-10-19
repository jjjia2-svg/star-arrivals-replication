import sys,json,collections,pandas as pd
K,S=sys.argv[1:3]
R=json.load(open(K+'/in/requests.json')); V=json.load(open(S+'/verify_result.json')); A=json.load(open(S+'/adds_with_review.json'))
dec={d['key']:d for d in V['decisions']}; up={r['key']:r['review_upheld'] for r in A}
w=pd.concat([pd.read_parquet(K+'/fetch/out/works_11.parquet').assign(t='11'),pd.read_parquet(K+'/fetch/out/works_0705.parquet').assign(t='0705')])
w=w.groupby(['aid','wid']).agg(yr=('yr','first'),c=('c','max'),sf=('sf','first'),title=('title','first'),tables=('t',lambda x:'+'.join(sorted(set(x))))).reset_index()
people=collections.OrderedDict()
for r in R:
    if not (r['needs_paper_review'] or r['cleaning']): continue
    k=r['person']; d=dec.get(k,{}); s=d.get('decision'); u=up.get(k)
    if not ((s in ('add','add_if_alternative_table')) or s=='needs_author_ruling'): continue
    p=people.setdefault(k,{'key':k,'name':d.get('name'),'discipline':d.get('discipline'),'department':d.get('department'),'arrival_year':d.get('arrival_year'),
        'decision':s,'review_upheld':u,'facts':str(d.get('evidence'))[:1500],'requests':[], 'ids':set()})
    p['requests'].append({'Y':r['Y'],'ids':r['ids'],'reason':r['reason'],'exclude_wids_proposed':r['exclude_wids'],'min_year_proposed':r['min_year']}); p['ids'].update(r['ids'])
out=[]
for k,p in people.items():
    ww=w[w.aid.isin(p['ids'])].sort_values(['yr','wid'])
    p['works']=ww[['aid','wid','yr','c','sf','title','tables']].to_dict('records'); p['ids']=sorted(p['ids']); p['n_works']=len(ww)
    fn=f"{K}/papers/{k.replace('|','_').replace(' ','_')}.json"; json.dump(p,open(fn,'w'),ensure_ascii=False,indent=0,default=str); out.append((k,p['decision'],u,len(ww),fn))
print(len(out)); print(collections.Counter((o[1],o[2]) for o in out)); print(sum(o[3] for o in out),'works total; max',max(o[3] for o in out))
json.dump([o[4] for o in out],open(K+'/papers/_files.json','w'))
