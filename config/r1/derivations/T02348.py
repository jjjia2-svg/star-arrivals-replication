import json,sys,re,collections
t=open(sys.argv[1]).read()
try: o=json.loads(t)
except Exception as e:
    i=t.find('{'); o=json.loads(t[i:])
if 'result' in o and isinstance(o['result'],(dict,str)): o=o['result'] if isinstance(o['result'],dict) else json.loads(o['result'])
print(o.keys())
json.dump(o,open(sys.argv[2]+'/verify_result.json','w'),ensure_ascii=False)
r=o['report']; open(sys.argv[2]+'/report_zh.md','w').write(r)
print('report chars',len(r)); 
d=o['decisions']; print('decisions',len(d)); print(collections.Counter((x['discipline'][:4],x['decision']) for x in d))
print('needs_rank',len(o['needs'])); print('missing',o['missing'])
