import sys,json,re,glob,pandas as pd
K,S,R,L=sys.argv[1:5]
m=pd.read_parquet(K+'/fetch5/out/matches.parquet'); m=m[(m.rk==1)&m.author_id.notna()].copy()
s1=pd.read_parquet(K+'/fetch5/out/screen_11.parquet'); s1=s1[s1.field=='chemmath'].set_index(['aid','Y'])
def pct(a,y):
    if not y or (a,int(y)) not in s1.index: return (None,None,None)
    x=s1.loc[(a,int(y))]; x=x.iloc[0] if isinstance(x,pd.DataFrame) else x
    return (float(x.pct),int(x.cn2),int(x.aage))
rows=[]
for r in m.itertuples():
    best=None
    for y in [r.start_year, r.alt_start_year]:
        if y and y==y:
            p,cn,ag=pct(r.author_id,int(y)-1)
            if p is not None and (best is None or p>best[0]): best=(p,cn,ag,int(y))
    rows.append({'name':r.name,'dept':r.dept,'post_type':r.post_type,'author_id':r.author_id,'start':r.start_year,'n_at_school':r.n_at_school,
                 'pct':best[0] if best else None,'cell_n':best[1] if best else None,'aage':best[2] if best else None,'arr_used':best[3] if best else None})
d=pd.DataFrame(rows)
ev=set(pd.read_csv(R+'/data/cal2026-10/events_chemistry_cal2026-10.csv').author_id)|set(pd.read_csv(R+'/data/cal2026-10/events_math_stats_cal2026-10.csv').author_id)
dec=set()
for f in glob.glob(L+'/multidisc_gold_2026-08-10/data/poach_fn_verdicts_*_2026-08-15.csv')+[L+'/multidisc_2026-07-24/data/star_verification_verdicts.csv']+glob.glob(L+'/multidisc_v2_2026-08-04/verify/star_recheck_*.csv'):
    t=open(f,errors='ignore').read(); dec|=set(re.findall(r'A\d{6,}',t))
for fn in [S+'/v2/verify_result.json',K+'/v3/verify3_result.json',K+'/q1/q1_result.json']:
    t=open(fn).read(); dec|=set(re.findall(r'A\d{6,}',t))
d['is_event']=d.author_id.isin(ev); d['decided_before']=d.author_id.isin(dec)
d['top10']=(d.pct>=0.9)&(d.cell_n>=30)&(d.aage>=2)
d.to_csv(K+'/census/census_ranked.csv',index=False)
print('matched',len(d),'| top10',int(d.top10.sum()),'| of which current events',int((d.top10&d.is_event).sum()),'| decided before',int((d.top10&~d.is_event&d.decided_before).sum()),'| NEW',int((d.top10&~d.is_event&~d.decided_before).sum()))
new=d[d.top10&~d.is_event&~d.decided_before]
print(new.groupby(['dept','post_type']).size().to_string())
