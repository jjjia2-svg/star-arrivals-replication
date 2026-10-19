import csv, glob, os
done_perm, done_null = {}, {}
for f in glob.glob('out/P3cutpos_*_perm_*.csv'):
    fld = os.path.basename(f).split('P3cutpos_')[1].split('_perm_')[0]
    for r in csv.DictReader(open(f)):
        done_perm.setdefault(fld, set()).add(int(r['perm']))
for f in glob.glob('out_null/NULLpos_*_null_*.csv'):
    for r in csv.DictReader(open(f)):
        done_null.setdefault(r['label'].replace('NULLpos_', ''), set()).add(int(r['sim']))
local = set(int(x) for x in open('local_done_econ.txt').read().split()) if os.path.exists('local_done_econ.txt') else set()

def chunks(xs, size):
    if not xs: return []
    runs, cur = [], [xs[0]]
    for x in xs[1:]:
        if x == cur[-1] + 1: cur.append(x)
        else: runs.append(cur); cur = [x]
    runs.append(cur)
    return [c[i:i+size] for c in runs for i in range(0, len(c), size)]

jobs = []
need = sorted(set(range(0, 501)) - done_perm.get('econ', set()) - local)
for c in chunks(need, 5):
    jobs.append(f'Rscript run_perm.R p3tp P3cutpos_econ p3_afar_pos_econ.parquet P3cut_pos_econ.json 20260830 {c[0]} {c[-1]}')
print(f'  econ permutations still missing: {len(need)}')
for fld, pq, size in (('econ','p3_afar_pos_econ.parquet',5),
                      ('chemistry','p3_afar_pos_chemistry.parquet',25),
                      ('math_stats','p3_afar_pos_math_stats.parquet',25)):
    miss = sorted(set(range(1, 201)) - done_null.get(fld, set()))
    print(f'  null {fld} still missing: {len(miss)}')
    for c in chunks(miss, size):
        jobs.append(f'Rscript run_null.R NULLpos_{fld} {pq} 20260830 {c[0]} {c[-1]} out_null')
for fld in ('chemistry','math_stats'):
    if 0 not in done_perm.get(fld, set()):
        jobs.append(f'Rscript run_perm.R p3tp P3cutpos_{fld} p3_afar_pos_{fld}.parquet P3cut_pos_{fld}.json 20260830 0 0')
open('jobs_todo.txt','w').write('\n'.join(jobs) + '\n')
print(f'  TOTAL UNITS: {len(jobs)}')
