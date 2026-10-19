import sys,json
K,F=sys.argv[1:3]
t=open(F).read(); o=json.loads(t[t.find('{'):]); o=o.get('result',o)
if isinstance(o,str): o=json.loads(o)
M={p['key']:p for b in o['marked'] if b for p in b['people']}
C={p['key']:p for b in o['checked'] if b for p in b['people']}
final={}
for k,m in M.items():
    c=C.get(k,{})
    ns=(set(m['namesake_wids'])-set(c.get('wrongly_excluded_wids',[])))|set(c.get('missed_namesake_wids',[]))
    of=set(m['other_field_wids'])-set(c.get('other_field_disagree_wids',[]))
    fp=c.get('true_first_pub_year') or m.get('true_first_pub_year')
    final[k]={'name':m['name'],'namesake_wids':sorted(ns),'other_field_wids':sorted(of),'first_pub':fp,'check_verdict':c.get('verdict'),'check_note':c.get('note','')[:300],'mark_summary':m['summary'][:400]}
json.dump(final,open(K+'/papers/cleaning_final.json','w'),ensure_ascii=False,indent=1)
print('people',len(final),'checked',len(C),'amended',sum(v['check_verdict']=='amend' for v in final.values()))
for k,v in final.items(): print(f"{k:24} namesake {len(v['namesake_wids']):4} other_field {len(v['other_field_wids']):4} first_pub {v['first_pub']} {v['check_verdict']}")
