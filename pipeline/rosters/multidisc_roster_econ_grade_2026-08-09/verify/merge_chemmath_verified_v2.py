#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Merge all chemistry/maths manual-verification returns -> ledger CSV + gold parquet + rejected list (v2 · after the gaps were filled)

Three additions over merge_chemmath_verified.py (everything else is unchanged verbatim, so the old numbers can be compared directly):
  1) Two new events: `A5044701593:anu(msi)` (the MSI half of event A5044701593; the event population
     is MSI ∪ RSFAS, both halves count) and `A5005527509:adelaide` (Adelaide chemistry, never verified before).
  2) 73 academic-appointment incumbents who were "in the department, id mismatched" are re-matched to ids:
     after the new id is filled back, **the original rejected record is voided (superseded)** and the
     person is not counted twice. Re-matches judged no_id are recorded as confirmed but without an id
     (they go into the confirmed_no_openalex_id list).
  3) 7 people on the A5005527509 roster were already verified in the A5060018496:adelaide round (same
     department, same person, year span already covers 2015) → not sent for verification again;
     `A5005527509:adelaide` is simply added to their event_keys (no new people).
"""
import pandas as pd, glob, os, re, json, sys

# --- M3 port: repo path resolution (legacy hard-coded the author's machine) — config/paths.yaml ---
import pathlib as _sar_pl, sys as _sar_sys
_sar_repo = next(p for p in _sar_pl.Path(__file__).resolve().parents if p.name == "rosters").parents[1]
if str(_sar_repo) not in _sar_sys.path:
    _sar_sys.path.append(str(_sar_repo))
from pipeline.lib.paths import (derived_root as _sar_derived_root,  # noqa: E402,F401
                                snapshot_root as _sar_snapshot_root,
                                ssd_root as _sar_ssd_root,
                                legacy_thesis as _sar_legacy_thesis,
                                require_readable as _sar_rd,
                                require_writable as _sar_rw,
                                output_target as _sar_out,
                                deferred_output_target as _sar_lazyout,
                                staged_run_dir as _sar_staged)
BASE = str(_sar_staged(_sar_legacy_thesis() / "v2_output/multidisc_roster_econ_grade_2026-08-09"))
VER = os.path.join(BASE, "verify", "verified")
BAT = os.path.join(BASE, "verify", "batches")
VER_GF = os.path.join(BASE, "verify", "verified_gapfill")
BAT_GF = os.path.join(BASE, "verify", "batches_gapfill")
VER_RM = os.path.join(BASE, "verify", "verified_rematch")

EV2DEPT = {
 'A5014715335:deakin':('deakin_chem','deakin','chemistry'),
 'A5060018496:adelaide':('adelaide_chem','adelaide','chemistry'),
 'A5005527509:adelaide':('adelaide_chem','adelaide','chemistry'),                      # NEW
 'A5048687133:anu':('anu_chem','anu','chemistry'),
 'A5017128684:anu':('anu_chem','anu','chemistry'),
 'A5020302210:anu':('anu_chem','anu','chemistry'),
 'A5044701593:anu':('anu_mathstats','anu','math_stats'),
 'A5044701593:anu(msi)':('anu_mathstats','anu','math_stats'),                # NEW
 'A5030193476:melbourne':('melbourne_chem','melbourne','chemistry'),
 'A5012602442:melbourne':('melbourne_mathstats','melbourne','math_stats'),
 'A5000405788:melbourne':('melbourne_mathstats','melbourne','math_stats'),
 'A5102954096:monash':('monash_chem','monash','chemistry'),
 'A5006982852:monash':('monash_chem','monash','chemistry'),
 'A5066540462:monash':('monash_chem','monash','chemistry'),
 'A5006183789:monash':('monash_chem','monash','chemistry'),
 'A5006430396:monash':('monash_chem','monash','chemistry'),
 'A5074011742:monash':('monash_mathstats','monash','math_stats'),
 'A5074032970:monash':('monash_mathstats','monash','math_stats'),
 'A5023907914:monash':('monash_mathstats','monash','math_stats'),
 'A5014535747:monash':('monash_mathstats','monash','math_stats'),
 'A5051533068:monash':('monash_mathstats','monash','math_stats'),
 'A5079308734:monash':('monash_mathstats','monash','math_stats'),
 'A5113900323:monash':('monash_mathstats','monash','math_stats'),
 'A5027699970:sydney':('sydney_chem','sydney','chemistry'),
 'A5014057252:sydney':('sydney_chem','sydney','chemistry'),
 'A5027646711:sydney':('sydney_mathstats','sydney','math_stats'),
 'A5052182828:sydney':('sydney_mathstats','sydney','math_stats'),
 'A5100397166:sydney':('sydney_mathstats','sydney','math_stats'),
 'A5069934510:unsw':('unsw_chem','unsw','chemistry'),
 'A5000883844:unsw':('unsw_chem','unsw','chemistry'),
 'A5076950458:unsw':('unsw_chem','unsw','chemistry'),
 'A5027893501:unsw':('unsw_chem','unsw','chemistry'),
 'A5044731110:unsw':('unsw_mathstats','unsw','math_stats'),
 'A5042200719:unsw':('unsw_mathstats','unsw','math_stats'),
 'A5022427262:unsw':('unsw_mathstats','unsw','math_stats'),
 'A5069315147:unsw':('unsw_mathstats','unsw','math_stats'),
 'A5061150027:unsw':('unsw_mathstats','unsw','math_stats'),
 'A5046503140:uq':('uq_mathstats','uq','math_stats'),
 'A5051266677:uq':('uq_mathstats','uq','math_stats'),
 'A5035305002:uwa':('uwa_chem','uwa','chemistry'),
 'A5029928521:uwa':('uwa_chem','uwa','chemistry'),
 'A5083769806:uwa':('uwa_mathstats','uwa','math_stats'),
}
# public copy: the seven roster members are listed by OpenAlex author id (the private original matched
# their names; the public roster carries no names)
REUSE_A5005527509 = {"A5033537928", "A5112730630", "A5053013149", "A5085428976",
                     "A5052949556", "A5077370760", "A5016259898"}

VCOLS = ['cluster','name','author_id','confidence_in','verdict','evidence_url','evidence_type',
         'year_start_verified','year_end_verified','id_issue','notes']

# ---------- back up the old outputs before overwriting (rollback possible) ----------
import shutil
BK = os.path.join(BASE, "verify", "_backup_pre_gapfill_2026-08-10")
os.makedirs(BK, exist_ok=True)
for f in ["chemmath_roster_verified_all.csv", "rejected_persons_chemmath.csv",
          "uncertain_persons_chemmath.csv", "confirmed_no_openalex_id_chemmath.csv"]:
    s = os.path.join(BASE, "verify", f)
    if os.path.exists(s) and not os.path.exists(os.path.join(BK, f)):
        shutil.copy2(s, os.path.join(BK, f))
_pq = os.path.join(BASE, "roster_clean_chemmath_verified.parquet")
if os.path.exists(_pq) and not os.path.exists(os.path.join(BK, "roster_clean_chemmath_verified.parquet")):
    shutil.copy2(_pq, os.path.join(BK, "roster_clean_chemmath_verified.parquet"))

# ---------- load: the original 61 batches ----------
vfs = sorted(glob.glob(os.path.join(VER, "batch_*_verified.csv")))
assert len(vfs) == 61, len(vfs)
parts = []
for f in vfs:
    d = pd.read_csv(f, dtype=str, keep_default_na=False)
    d = d.rename(columns={'id_issue(并号/同名/无)': 'id_issue'})
    d['src_batch'] = os.path.basename(f).replace('_verified.csv', '')
    parts.append(d)
V = pd.concat(parts, ignore_index=True)

bparts = []
for f in sorted(glob.glob(os.path.join(BAT, "batch_*.csv"))):
    d = pd.read_csv(f, dtype=str, keep_default_na=False)
    d['in_batch'] = os.path.basename(f).replace('.csv', '')
    bparts.append(d)
B = pd.concat(bparts, ignore_index=True)

# ---------- load: the gap-filling batch ----------
gfs = sorted(glob.glob(os.path.join(VER_GF, "gf_batch_*_verified.csv")))
gbs = sorted(glob.glob(os.path.join(BAT_GF, "gf_batch_*.csv")))
assert len(gfs) == len(gbs) == 13, (len(gfs), len(gbs))
gp = []
for f in gfs:
    d = pd.read_csv(f, dtype=str, keep_default_na=False)
    d['src_batch'] = os.path.basename(f).replace('_verified.csv', '')
    gp.append(d[[c for c in VCOLS if c in d.columns] + ['src_batch']])
VG = pd.concat(gp, ignore_index=True)
gb = []
for f in gbs:
    d = pd.read_csv(f, dtype=str, keep_default_na=False)
    d['in_batch'] = os.path.basename(f).replace('.csv', '')
    gb.append(d)
BG = pd.concat(gb, ignore_index=True)
V = pd.concat([V, VG], ignore_index=True)
B = pd.concat([B, BG[[c for c in B.columns if c in BG.columns]]], ignore_index=True)

for df in (V, B):
    df['_k'] = df['cluster'] + '||' + df['name'] + '||' + df['author_id']
assert V['_k'].duplicated().sum() == 0, V.loc[V['_k'].duplicated(), '_k'].tolist()[:10]
assert B['_k'].duplicated().sum() == 0, B.loc[B['_k'].duplicated(), '_k'].tolist()[:10]
M = V.merge(B[['_k', 'matched_name', 'confidence', 'years', 'events', 'titles', 'in_batch']],
            on='_k', how='left', validate='1:1')
assert M['events'].notna().all(), M.loc[M['events'].isna(), ['cluster','name','author_id']].head(20)

# ---------- rank_tag table (v2 + gapfill) ----------
MT = pd.read_csv(os.path.join(BASE,'match','roster_openalex_match_v2.csv'), dtype=str, keep_default_na=False)
MG = pd.read_csv(os.path.join(BASE,'match','roster_openalex_match_gapfill.csv'), dtype=str, keep_default_na=False)
MT = pd.concat([MT[['cluster','name','rank_tag','score','inst_hit','n_candidates','match_method']],
                MG[['cluster','name','rank_tag','score','inst_hit','n_candidates','match_method']]],
               ignore_index=True)
MT['_k2'] = MT['cluster'] + '||' + MT['name']
MT = MT.drop_duplicates('_k2')
M['_k2'] = M['cluster'] + '||' + M['name']
M = M.merge(MT[['_k2','rank_tag','score','inst_hit','n_candidates','match_method']], on='_k2', how='left', validate='m:1')
assert M['rank_tag'].notna().all(), M.loc[M['rank_tag'].isna(), ['cluster','name']].head(20)
M['verdict'] = M['verdict'].str.strip().str.lower()

# ---------- 73 people re-matched: void the old rejected rows, write new rows ----------
rmfs = sorted(glob.glob(os.path.join(VER_RM, "rm_batch_*_verified.csv")))
assert len(rmfs) == 5, len(rmfs)
rp = []
for f in rmfs:
    d = pd.read_csv(f, dtype=str, keep_default_na=False)
    d['src_batch'] = os.path.basename(f).replace('_verified.csv', '')
    rp.append(d)
RM = pd.concat(rp, ignore_index=True)
RM['verdict'] = RM['verdict'].str.strip().str.lower()
assert len(RM) == 73, len(RM)

# Re-matching needs the OLD rejected list to get cluster/events/snapshot year. But this script overwrites that file at the end,
# so a snapshot is frozen first and every rerun reads the snapshot — this keeps it repeatable (idempotent).
p_rej_live = os.path.join(BASE, "verify", "rejected_persons_chemmath.csv")
p_rej_snap = os.path.join(BASE, "verify", "rejected_persons_chemmath_prev_2026-08-10.csv")
if not os.path.exists(p_rej_snap):
    pd.read_csv(p_rej_live, dtype=str, keep_default_na=False).to_csv(p_rej_snap, index=False)
REJ_OLD = pd.read_csv(p_rej_snap, dtype=str, keep_default_na=False)
REJ_OLD['_rk'] = REJ_OLD['dept_key'] + '||' + REJ_OLD['display_name'] + '||' + REJ_OLD['author_id']
rejmap = REJ_OLD.set_index('_rk').to_dict('index')

def dept_of(ev):
    ds = {EV2DEPT[x] for x in str(ev).split(';') if x in EV2DEPT}
    assert len(ds) == 1, (ev, ds)
    return list(ds)[0]

# the 7 people in A5005527509 ∩ A5060018496:adelaide: add A5005527509:adelaide to their event_keys (no new people)
sum_years = {}
for _, r in MG[MG['cluster'] == 'adelaide-chem-A5005527509'].iterrows():
    sum_years[str(r['name']).lower()] = str(r['years'])
mask7 = (M['cluster'] == 'adelaide-deakin-chem') & (M['author_id'].isin(REUSE_A5005527509))
n7 = int(mask7.sum())
M.loc[mask7, 'events'] = M.loc[mask7, 'events'].apply(
    lambda e: ';'.join(sorted({x for x in (set(str(e).split(';')) | {'A5005527509:adelaide'}) if x})))
M.loc[mask7, 'years'] = [
    ';'.join(sorted({x for x in (set(str(y).split(';')) | set(sum_years.get(str(n).lower(), '').split(';'))) if x}))
    for y, n in zip(M.loc[mask7, 'years'], M.loc[mask7, 'name'])]

M[['dept_key', 'school', 'field']] = M['events'].apply(lambda e: pd.Series(dept_of(e)))
M['_rk'] = M['dept_key'] + '||' + M['name'] + '||' + M['author_id']

RM['_rk'] = RM['dept_key'] + '||' + RM['name'] + '||' + RM['old_author_id']
missing = set(RM['_rk']) - set(M['_rk'])
assert not missing, f"rematch rows with no matching old row in the ledger: {sorted(missing)[:5]}"

superseded = set(RM['_rk'])
M['superseded_by_rematch'] = M['_rk'].isin(superseded)
n_sup = int(M['superseded_by_rematch'].sum())
KEEP = M[~M['superseded_by_rematch']].copy()

# New rows: assembled from the old rejected record + the re-match return
newrows = []
for _, r in RM.iterrows():
    old = rejmap.get(r['_rk'], {})
    vd = {'confirmed': 'confirmed', 'no_id': 'confirmed', 'uncertain': 'uncertain',
          'rejected': 'rejected'}[r['verdict']]
    aid = r['new_author_id'].strip() if r['verdict'] == 'confirmed' else ''
    newrows.append({
        'cluster': old.get('cluster', ''), 'name': r['name'], 'author_id': aid,
        'confidence_in': 'rematch', 'verdict': vd,
        'evidence_url': r['evidence_url'], 'evidence_type': r['evidence_type'],
        'year_start_verified': r['year_start_verified'], 'year_end_verified': r['year_end_verified'],
        'id_issue': r['id_issue'],
        'notes': f"[重配号 2026-08-10 · 旧号 {r['old_author_id']} 已作废] " + str(r['notes']),
        'src_batch': r['src_batch'], 'matched_name': '', 'confidence': 'rematch',
        'years': f"{old.get('year_start_old','')};{old.get('year_end_old','')}".strip(';'),
        'events': old.get('event_keys', ''), 'titles': '', 'in_batch': r['src_batch'],
        'rank_tag': 'include', 'score': '', 'inst_hit': '', 'n_candidates': '', 'match_method': 'rematch_human',
        'dept_key': r['dept_key'], 'school': old.get('school', ''), 'field': old.get('field', ''),
        'superseded_by_rematch': False, '_k': '', '_k2': '', '_rk': '',
    })
NEW = pd.DataFrame(newrows)
M = pd.concat([KEEP, NEW], ignore_index=True).fillna('')

# ---------- roster snapshot years ----------
def yrs(s):
    v = [int(x) for x in re.findall(r'\d{4}', str(s))]
    return (min(v), max(v)) if v else (None, None)
M[['year_start_orig', 'year_end_orig']] = M['years'].apply(lambda s: pd.Series(yrs(s)))

# ---------- verified years ----------
CAP = 2025
def parse_y(x, cap_open):
    t = str(x).strip().lower()
    if re.fullmatch(r'\d{4}', t): return int(t), False
    if t in ('ongoing', 'present', '至今', 'current', 'now'):
        return (CAP, True) if cap_open else (None, False)
    m = re.findall(r'\d{4}', t)
    if m: return int(m[0] if not cap_open else m[-1]), False
    return None, False

ys_list, ye_list, note_list, src_list = [], [], [], []
for _, r in M.iterrows():
    ys, _ = parse_y(r['year_start_verified'], False)
    ye, was_open = parse_y(r['year_end_verified'], True)
    notes, srcs = [], []
    if ys is None:
        ys = r['year_start_orig']; notes.append('起年用名册快照年(未核实到)'); srcs.append('snapshot_start')
    else:
        srcs.append('verified_start')
    if ye is None:
        ye = r['year_end_orig']; notes.append('末年用名册快照年(未核实到)'); srcs.append('snapshot_end')
    else:
        srcs.append('verified_end')
        if was_open: notes.append(f'原写 ongoing/present，按面板末年封顶 {CAP}')
    if ys is not None and ye is not None and ys > ye:
        notes.append(f'年段倒置已互换(原 {ys}-{ye})'); ys, ye = ye, ys
    ys_list.append(ys); ye_list.append(ye); note_list.append('；'.join(notes)); src_list.append('+'.join(srcs))
M['year_start'] = ys_list; M['year_end'] = ye_list
M['year_note'] = note_list; M['year_source'] = src_list
M['year_corrected'] = (M['year_start'] != M['year_start_orig']) | (M['year_end'] != M['year_end_orig'])

# ---------- id quality -> confidence ----------
def id_grade(t):
    t = str(t).strip()
    if t == '' or t in ('无', '无编号', '无ID', '无(未配号)'): return 'clean'
    if re.search(r'轻微|轻度|\(轻\)|疑似|可能|疑\)', t): return 'mild'
    return 'bad'
M['id_grade'] = M['id_issue'].apply(id_grade)
CONF = {'clean': 'high', 'mild': 'medium', 'bad': 'low'}
M['confidence'] = M['id_grade'].map(CONF)
M.loc[M['author_id'].str.strip() == '', 'confidence'] = 'none'
M.loc[(M['year_source'] == 'snapshot_start+snapshot_end') & (M['confidence'] == 'high'), 'confidence'] = 'medium'

# ---------- reject cause (old rules carried over verbatim) ----------
TAG_RE = re.compile(r'^\s*[\[【]([^\]】]{1,40})[\]】]|type\s*=\s*([^\s.,;，。]{1,30})')
def cause(row):
    t = (str(row['notes']) + ' ' + str(row['id_issue'])).lower()
    tt = str(row['notes'])
    m = TAG_RE.search(tt)
    tag = ''.join(x for x in (m.groups() if m else ()) if x)
    tagA = bool(tag) and bool(re.search(r'人不在|不在该系|不在本系|不在这个系|系错|学科错配|双错|非化学|非本系|非该系', tag))
    tagB = bool(tag) and bool(re.search(r'编号|配号|号', tag))
    tagD = bool(tag) and bool(re.search(r'兼职|兼任|名誉|访问|honorary|adjunct', tag))
    idw = bool(re.search(r'配号错|配号配错|配错人|编号错|编号是另一个人|号不可用|号被并|并号|同名|拆号|分号|碎片|错配|需重新配号|重配号', t))
    p_in = bool(re.search(r'人在系|系属本身无误|人确在|人在该系|人在这个系|在系里属实|人在本系|人本身在系|系属无误|系归属无误|\(a\)\s*通过', tt)) \
           or bool(re.search(r'person ok|person confirmed|person is confirmed|roster ok|dept ok|department ok', t))
    not_in_en = bool(re.search(r'wrong department|not in (?:the )?(?:department|school|dept)|not a member of|'
                               r'different department|substantive .{0,20}appointment is .{0,40}(?:department|school)|'
                               r'was not in |not an? .{0,25}(?:department|school) member', t))
    if not_in_en and not p_in: return 'A_系归属错(不在该系)'
    if idw and (p_in or (tagB and not tagA)): return 'B_配号错(ID是另一个人/并号不可用)'
    if re.search(r'(?:honorary staff|adjunct and honorary|honorary (?:research )?(?:professor|fellow)|'
                 r'adjunct professor|名誉(?:教授|研究员)|荣誉教授)\s*[』」\'"”]?\s*[栏节]', t):
        return 'D_名誉/兼任/访问(非在编)'
    if tag:
        if tagD: return 'D_名誉/兼任/访问(非在编)'
        if tagA: return 'A_系归属错(不在该系)'
        if tagB: return 'B_配号错(ID是另一个人/并号不可用)'
    person_in = bool(re.search(r'人在系|系属本身无误|人确在|人在该系|人在这个系|编号错·人在系|在系里属实|人在本系|系属无误|系归属无误', tt))
    not_in = bool(re.search(r'人不在|系错|非化学|不在该系|不在本系|不在这个系|非rsfas|非 rsfas|不在系|学科错配|非该系|另一个系|系归属错|不属于该系|非数学系|非本系|'
                            r'系不对|不在化学|学科不是化学|非研究人员|行政人员|不是化学系|不属 chemistry|不属chemistry|非学术人员', t))
    visiting = bool(re.search(r'访问学者|访问教授|兼职|honorary|adjunct|名誉衔|visiting|emerit|荣休|客座|外聘|挂名', t))
    idwrong = bool(re.search(r'配号错|配错人|编号错|编号是另一个人|号不可用|不可用，需重配|并号|同名|拆号|分号|碎片|错配|需重新配号|重配号', t))
    nobody = bool(re.search(r'查无此人|无此人|查不到|无任何证据|年段无交集|无交集|查无|年份错|不成立|窗口内零产出|窗内无|已离职|离职|年段不符|年份不成立', t))
    if not_in and not person_in: return 'A_系归属错(不在该系)'
    if idwrong: return 'B_配号错(ID是另一个人/并号不可用)'
    if visiting: return 'D_名誉/兼任/访问(非在编)'
    if nobody: return 'C_查无此人或名册年段不成立'
    if not_in: return 'A_系归属错(不在该系)'
    return 'E_其他/未归类'
M['reject_cause'] = ''
rej_mask = M['verdict'] == 'rejected'
M.loc[rej_mask, 'reject_cause'] = M[rej_mask].apply(cause, axis=1)

# ---------- dup flags ----------
M['no_openalex_id'] = M['author_id'].str.strip() == ''
dupg = M[(M['verdict'] == 'confirmed') & (~M['no_openalex_id'])].groupby(['dept_key', 'author_id'])['name'].agg(list)
dupmap = {k: v for k, v in dupg.items() if len(v) > 1}
M['dup_person_flag'] = ''
for (dk, aid), names in dupmap.items():
    sel = (M['dept_key'] == dk) & (M['author_id'] == aid) & (M['verdict'] == 'confirmed')
    M.loc[sel, 'dup_person_flag'] = '同系同号多行: ' + ' / '.join(names)

M['human_verified'] = True
M['verify_source'] = 'batch_human_核 2026-08-10 (chem/math 61批 + 缺口补齐 13批 + 重配号 5批)'

# ---------- output 1: ledger ----------
all_cols = ['dept_key','school','field','cluster','event_keys','name','matched_name','author_id',
            'verdict','confidence_in','confidence','year_start','year_end','year_start_orig','year_end_orig',
            'year_corrected','year_source','year_note','evidence','evidence_url','id_issue','id_grade',
            'reject_cause','no_openalex_id','dup_person_flag','rank_tag','titles','notes','src_batch','verify_source']
M['event_keys'] = M['events']
M['evidence'] = M['evidence_type']
OUT = M.sort_values(['dept_key','author_id','name']).reset_index(drop=True)
p_all = os.path.join(BASE, 'verify', 'chemmath_roster_verified_all.csv')
OUT[all_cols].to_csv(p_all, index=False)

# ---------- output 2: parquet ----------
C = M[(M['verdict'] == 'confirmed') & (~M['no_openalex_id'])].copy()
C = C[C['year_start'].notna() & C['year_end'].notna() & (C['year_start'] != '') & (C['year_end'] != '')]
rows = []
for (dk, aid), g in C.groupby(['dept_key', 'author_id']):
    g = g.sort_values(['year_start', 'year_end'])
    cur = None
    for _, r in g.iterrows():
        if cur is None:
            cur = r.to_dict(); cur['_names'] = [r['name']]; cur['_ev'] = set(str(r['events']).split(';')); continue
        if int(r['year_start']) <= int(cur['year_end']) + 1:
            if int(r['year_start']) < int(cur['year_start']): cur['year_start'] = r['year_start']
            if int(r['year_end']) > int(cur['year_end']): cur['year_end'] = r['year_end']
            cur['_names'].append(r['name']); cur['_ev'] |= set(str(r['events']).split(';'))
            if r['rank_tag'] == 'include': cur['rank_tag'] = 'include'
            for f in ('id_issue','year_note','evidence','evidence_url'):
                if str(r[f]).strip() and str(r[f]).strip() not in str(cur[f]):
                    cur[f] = (str(cur[f]) + ' | ' + str(r[f])).strip(' |')
            if ['high','medium','low'].index(r['confidence']) > ['high','medium','low'].index(cur['confidence']):
                cur['confidence'] = r['confidence']
            cur['year_start_orig'] = min(cur['year_start_orig'], r['year_start_orig'])
            cur['year_end_orig'] = max(cur['year_end_orig'], r['year_end_orig'])
        else:
            rows.append(cur); cur = r.to_dict(); cur['_names'] = [r['name']]; cur['_ev'] = set(str(r['events']).split(';'))
    rows.append(cur)
P = pd.DataFrame(rows)
P['dup_person_flag'] = P['_names'].apply(lambda n: '' if len(n) == 1 else '同系同号已合并: ' + ' / '.join(sorted(set(n))))
P['event_keys'] = P['_ev'].apply(lambda s: ';'.join(sorted(x for x in s if x)))
P['year_corrected'] = (P['year_start'] != P['year_start_orig']) | (P['year_end'] != P['year_end_orig'])
P['human_verified'] = True
pq_cols = ['dept_key','school','author_id','year_start','year_end','evidence','confidence','human_verified',
           'evidence_url','year_start_orig','year_end_orig','year_corrected','id_issue','year_note',
           'verify_source','dup_person_flag','field','event_keys','rank_tag']
P = P[pq_cols].copy()
for c in ['year_start','year_end','year_start_orig','year_end_orig']:
    P[c] = P[c].astype('int64')
for c in ['dept_key','school','author_id','evidence','confidence','evidence_url','id_issue','year_note',
          'verify_source','dup_person_flag','field','event_keys','rank_tag']:
    P[c] = P[c].astype(str)
P = P.sort_values(['dept_key','author_id','year_start']).reset_index(drop=True)
p_pq = os.path.join(BASE, 'roster_clean_chemmath_verified.parquet')
P.to_parquet(p_pq, index=False)

# ---------- output 3: rejected ----------
R = M[M['verdict'] == 'rejected'].copy()
R['display_name'] = R['name']
R = R.rename(columns={'year_start_orig':'year_start_old','year_end_orig':'year_end_old'})
rej_cols = ['dept_key','school','field','author_id','display_name','year_start_old','year_end_old',
            'reject_cause','rank_tag','evidence_url','evidence','id_issue','notes','cluster','event_keys','src_batch']
p_rej = os.path.join(BASE, 'verify', 'rejected_persons_chemmath.csv')
R[rej_cols].sort_values(['dept_key','display_name']).to_csv(p_rej, index=False)

# ---------- output 4: confirmed but no id ----------
N = M[(M['verdict'] == 'confirmed') & (M['no_openalex_id'])].copy()
p_noid = os.path.join(BASE, 'verify', 'confirmed_no_openalex_id_chemmath.csv')
N[['dept_key','school','field','name','year_start','year_end','evidence','evidence_url','rank_tag',
   'titles','notes','cluster','event_keys','src_batch']].to_csv(p_noid, index=False)

# ---------- output 5: uncertain ----------
U = M[M['verdict'] == 'uncertain'].copy()
p_unc = os.path.join(BASE, 'verify', 'uncertain_persons_chemmath.csv')
U[['dept_key','school','field','name','author_id','year_start_orig','year_end_orig','id_issue','rank_tag',
   'evidence','evidence_url','notes','cluster','event_keys','src_batch']].to_csv(p_unc, index=False)

# ---------- stats ----------
stats = {}
stats['n_rows'] = len(M)
stats['superseded_by_rematch'] = n_sup
stats['A5005527509_reused_from_A5060018496_round'] = n7
stats['verdict'] = M['verdict'].value_counts().to_dict()
_sf = M.groupby(['school','field','verdict']).size().unstack(fill_value=0)
_sf.index = ['|'.join(i) for i in _sf.index]
stats['by_school_field'] = _sf.to_dict('index')
stats['by_dept'] = M.groupby(['dept_key','verdict']).size().unstack(fill_value=0).to_dict('index')
stats['reject_cause'] = M.loc[M['verdict']=='rejected','reject_cause'].value_counts().to_dict()
stats['parquet_rows'] = len(P)
stats['parquet_persons'] = P['author_id'].nunique()
stats['parquet_dept_person_pairs'] = int(P.groupby(['dept_key','author_id']).ngroups)
stats['parquet_person_years'] = int((P['year_end'] - P['year_start'] + 1).sum())
stats['parquet_by_dept'] = P.groupby('dept_key').agg(rows=('author_id','size'), persons=('author_id','nunique')).to_dict('index')
stats['parquet_include_rows'] = int((P['rank_tag']=='include').sum())
stats['parquet_conf'] = P['confidence'].value_counts().to_dict()
stats['no_id_confirmed'] = len(N)
stats['uncertain'] = len(U)
stats['rematch_verdicts'] = RM['verdict'].value_counts().to_dict()

# number of incumbents per event
ev_rows = []
for _, r in P.iterrows():
    for e in str(r['event_keys']).split(';'):
        if e: ev_rows.append({'event': e, 'author_id': r['author_id'], 'rank_tag': r['rank_tag'],
                              'dept_key': r['dept_key']})
EV = pd.DataFrame(ev_rows)
stats['event_in_post'] = EV.groupby('event').agg(
    dept=('dept_key','first'), persons=('author_id','nunique'),
    include=('rank_tag', lambda s: int((s=='include').sum()))).to_dict('index')
json.dump(stats, open(os.path.join(BASE,'verify','merge_stats_v2.json'),'w'), ensure_ascii=False, indent=1, default=str)
print(json.dumps({k: v for k, v in stats.items() if k not in ('by_school_field','by_dept','event_in_post','parquet_by_dept')},
                 ensure_ascii=False, indent=1, default=str))
print('\nWROTE:', p_all, p_pq, p_rej, p_noid, p_unc, sep='\n  ')
