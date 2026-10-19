import sys,json,pandas as pd
K=sys.argv[1]; o=K+'/fetch4/out/'
a=pd.concat([pd.read_csv(o+f,dtype={'ext':str}) for f in ['ranks_0705_A.csv','ranks_0705_B.csv','ranks_11_A.csv','ranks_11_B.csv']])
a=a[~a.key.str.startswith('CONTROL')]; a['ext']=a.ext.replace({'705':'0705'})
a['person']=a.key.str.rsplit('|',n=1).str[0]
fin=json.load(open(K+'/papers/cleaning_final.json'))
files={json.load(open(f))['key']:json.load(open(f)) for f in json.load(open(K+'/papers/_files.json'))}
rows=[]
for k,p in files.items():
    d=k.split('|')[0]; prod='11' if d=='econ' else '0705'; alt=None if d=='econ' else '11'
    Y=(int(p['arrival_year'])-1) if p.get('arrival_year') else None
    x=a[(a.person==k)&(a.Y==Y)] if Y else a[a.person==k]
    def g(ext,pas):
        z=x[(x.ext==ext)&(x['pass']==pas)]; return None if z.empty or pd.isna(z.pct.iloc[0]) else (float(z.pct.iloc[0]),int(z.aage.iloc[0]) if not pd.isna(z.aage.iloc[0]) else None)
    rows.append({'person':k,'decision':p['decision'],'Y':Y,'n_namesake':len(fin[k]['namesake_wids']),'prod_raw':g(prod,'A'),'prod_clean':g(prod,'B'),'alt_raw':g(alt,'A') if alt else None,'alt_clean':g(alt,'B') if alt else None,'agent_first_pub':fin[k]['first_pub']})
df=pd.DataFrame(rows)
def v(t): return t[0] if t else None
df['prod_clean_pct']=df.prod_clean.apply(v); df['alt_clean_pct']=df.alt_clean.apply(v)
df['status']=[('PASS prod' if (pc or 0)>=.9 else ('PASS alt only' if (ac or 0)>=.9 else 'FAIL')) for pc,ac in zip(df.prod_clean_pct,df.alt_clean_pct)]
df.to_csv(K+'/rk4_cleaned.csv',index=False)
print(df.groupby(['decision','status']).size())
print(df[['person','decision','Y','n_namesake','prod_raw','prod_clean','alt_raw','alt_clean','status']].to_string())
