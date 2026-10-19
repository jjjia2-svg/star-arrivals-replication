import json,sys,collections
S=sys.argv[1]; o=json.load(open(S+'/verify_result.json'))
D=o['decisions']; RA=[c for r in o['reviewAdds'] for c in r['checks']]; RR=o['reviewRejects']['checks'] if o['reviewRejects'] else []
print('review checks on adds',len(RA),'upheld',sum(c['upheld'] for c in RA))
rk={}
for c in RA: rk.setdefault(c.get('key') or c['name'],[]).append(c)
byname={}
for c in RA: byname.setdefault(c['name'],[]).append(c)
adds=[d for d in D if d['decision'] in('add','add_if_alternative_table')]
tab=collections.Counter()
rows=[]
for d in adds:
    cs=rk.get(d['key']) or byname.get(d['name']) or []
    up = None if not cs else all(c['upheld'] for c in cs)
    tab[(d['discipline'][:4],d['decision'],{True:'upheld',False:'NOT upheld',None:'no review'}[up])]+=1
    rows.append({**d,'review_upheld':up,'review_note':' | '.join(c['note'] for c in cs)[:600]})
for k,v in sorted(tab.items()): print(k,v)
json.dump(rows,open(S+'/adds_with_review.json','w'),ensure_ascii=False,indent=1)
print('reject-review checks',len(RR),'rejection stands',sum(c['upheld'] for c in RR))
for c in RR:
    if not c['upheld']: print('  REJECT OVERTURNED?',c['name'],'|',c['note'][:250])
