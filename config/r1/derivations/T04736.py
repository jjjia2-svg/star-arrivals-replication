import sys,json,collections,pandas as pd
K=sys.argv[1]
c=json.load(open(K+'/census/census_full.json'))['census']
info={(a['name'],x['dept']):(a.get('came_from_country') or 'unknown',a.get('came_from') or '') for x in c for a in x['arrivals']}
d=pd.read_csv(K+'/census/census_ranked.csv')
new=d[d.top10&~d.is_event&~d.decided_before].copy()
new['from_country']=[info.get((n,dp),('unknown',''))[0] for n,dp in zip(new.name,new.dept)]
new['from_au']=new.from_country.str.contains('Australia',case=False,na=False)
print(collections.Counter('Australia' if a else ('unknown' if f.lower().startswith('unknown') or f=='' else 'abroad') for a,f in zip(new.from_au,new.from_country)))
ab=new[~new.from_au & ~new.from_country.str.lower().str.startswith('unknown')]
print('abroad (known):',len(ab)); print(ab.groupby(['post_type']).size().to_dict())
print(ab.groupby('dept').size().to_dict())
new.to_csv(K+'/census/census_new_candidates.csv',index=False)
