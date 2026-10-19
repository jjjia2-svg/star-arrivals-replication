"""U4 orchestrator (run_u4) — entry point for the full-machine run on real data.

This stage lands preflight first (input readiness check + row counts; parquet metadata only, no full scan), so that before the real-data smoke run
you can confirm all tables are present and estimate the scale (local machine vs AWS). build_u4 (split into cells → compute ranks → pick stars → arrival → freeze + Zenou gold-standard check) is added later.

Injection follows the U3 full-smoke driver: registry = the full snapshot education set → registry_by_id
→ econ_dept_ids = fold of table A → call the orchestrator; smoke-test Monash + UNSW first.
"""
from __future__ import annotations

from pathlib import Path

# --- M3 port: repo path resolution (legacy hard-coded the author's machine) — config/paths.yaml ---
import pathlib as _sar_pl, sys as _sar_sys
_sar_repo = next(p for p in _sar_pl.Path(__file__).resolve().parents if p.name == "units").parents[1]
if str(_sar_repo) not in _sar_sys.path:
    _sar_sys.path.append(str(_sar_repo))
from pipeline.lib.paths import derived_root as _sar_derived_root  # noqa: E402

# Roster version (hand-checked corrected version): all U4 roster reads
#   use this version — 6 people have year_start = the evidence year from CV/ORCID/Wayback (hv=True) and A5018638208 is flagged
#   adjunct_q3. Written by u0p5 roster.star_arrival_fix (the canonical old file is kept as is, never overwritten).
#   Single source of truth: real_inputs/_resume fingerprints etc. all import from here; do not scatter the literal.
ROSTER_SUB = "u0p5_roster/roster_v2026-07-10_starfix"
ROSTER_FILES: tuple[str, str] = (
    f"{ROSTER_SUB}/dept_roster_panel_monash.parquet",
    f"{ROSTER_SUB}/dept_roster_panel_unsw.parquet",
)

# Registry v3 (11 schools) roster — the two-school default remains available as a fallback.
#   v3 = the 11-school roster promoted after hand review of 4 categories of boundary cases (registry_v3_2026-07-12/:
#   3 frozen rosters Monash STARFIX/UNSW/UQ carried over byte for byte + 8 new schools finalized under the boundary rules).
#   The two-school ROSTER_FILES default literals are unchanged (single source of truth for real_inputs); v3 is a new optional path.
ROSTER_SUB_V3 = "u0p5_roster/registry_v3_2026-07-12"
_V3_SCHOOLS: tuple[str, ...] = (
    "adelaide", "anu", "deakin", "macquarie", "melbourne",
    "monash", "sydney", "unsw", "uq", "uts", "uwa",
)
ROSTER_FILES_V3: tuple[str, ...] = tuple(
    f"{ROSTER_SUB_V3}/dept_roster_panel_{_s}.parquet" for _s in _V3_SCHOOLS
)

_ROSTER_VERSIONS: dict[str, tuple[str, ...]] = {
    "two": ROSTER_FILES,
    "v3": ROSTER_FILES_V3,
}


def roster_files_for(registry_version: str = "two") -> tuple[str, ...]:
    """Pick the roster file set by registry version (relative to the derived root): "two" (default, the frozen two schools) / "v3" (11 schools).

    Unknown version → fail-loud. The identification rule is untouched — this only selects a roster version and never changes roster content.
    """
    try:
        return _ROSTER_VERSIONS[registry_version]
    except KeyError:
        raise ValueError(
            f"unknown registry_version: {registry_version!r} (supported: {sorted(_ROSTER_VERSIONS)})")

# U4 input tables (relative to the derived root); dir = bucketed multi-part, .parquet = single file.
U4_INPUTS: dict[str, str] = {
    "works": "u1_edges_full_2026-07-05/works",
    "work_first_pub": "u1_edges_full_2026-07-05/work_first_pub",
    "fwci_baseline_pop": "u1_edges_full_2026-07-05/fwci_baseline_pop",
    "institutions": "u1_edges_full_2026-07-05/institutions",
    "authorship_edges": "u1_edges_full_2026-07-05/authorship_edges",
    "person_map": "u2_person_map_2026-07-05/person_map",
    "panel": "u3_panel_2026-07-06/panel",
    "affil_timeline": "u3_panel_2026-07-06/affil_timeline",
    "roster_monash": ROSTER_FILES[0],
    "roster_unsw": ROSTER_FILES[1],
}


def preflight(derived_root, *, tables: dict[str, str] = U4_INPUTS) -> dict:
    """Check that the U4 input tables are ready + row counts (parquet metadata, no full scan).

    Returns {table: {"present": bool, "n_rows": int, "n_files": int}}.
    A missing table does not blow up (reports present=False); the caller decides whether to stop.
    """
    import pyarrow.parquet as pq

    root = Path(derived_root)
    report: dict = {}
    for name, subpath in tables.items():
        p = root / subpath
        if p.is_file():
            files = [p]
        elif p.is_dir():
            files = sorted(p.rglob("*.parquet"))
        else:
            files = []
        n_rows = sum(pq.ParquetFile(str(f)).metadata.num_rows for f in files)
        report[name] = {"present": bool(files), "n_rows": n_rows, "n_files": len(files)}
    return report


def map_incumbents(roster_rows, author_to_person: dict) -> dict:
    """Roster rows (table B) + author→person map → incumbents (with person_id).

    roster_rows: table B rows {author_id, dept_key, display_name, year_start, year_end, ...}.
    author_to_person: {author_id: person_id} (person_map, only 2 columns read).
    Unmapped people (no disambiguated identity = no works) are listed in a separate unmapped report and are never silently mixed into the incumbents.
    Returns {"incumbents": [...with person_id...], "unmapped": [author_id...]}.
    """
    incumbents, unmapped = [], []
    for r in roster_rows:
        aid = r["author_id"]
        pid = author_to_person.get(aid)
        if pid is None:
            unmapped.append(aid)
            continue
        incumbents.append({
            "author_id": aid, "person_id": pid, "dept_key": r["dept_key"],
            "display_name": r.get("display_name"),
            "year_start": r.get("year_start"), "year_end": r.get("year_end"),
        })
    return {"incumbents": incumbents, "unmapped": unmapped}


def load_incumbents(
    derived_root,
    *,
    roster_files=ROSTER_FILES,
    person_map_dir="u2_person_map_2026-07-05/person_map",
) -> dict:
    """Real read: the two-school roster + person_map (only author_id/person_id read) → map_incumbents."""
    import pyarrow.parquet as pq

    root = Path(derived_root)
    roster_rows: list[dict] = []
    for rf in roster_files:
        roster_rows += pq.read_table(str(root / rf)).to_pylist()

    pm_dir = root / person_map_dir
    pmf = pm_dir if pm_dir.is_file() else sorted(pm_dir.rglob("*.parquet"))[0]
    pm = pq.read_table(str(pmf), columns=["author_id", "person_id"]).to_pylist()
    author_to_person = {r["author_id"]: r["person_id"] for r in pm}

    return map_incumbents(roster_rows, author_to_person)


def pick_arrival_year(roster_rows):
    """Several roster records for the same person → pick the most credible arrival year (formalised rule of the assembly script).

    roster_rows: [{year_start, confidence, human_verified}] (several may coexist).
    Priority: 1. human_verified  2. confidence=='high'  3. earliest non-null year_start.
    All year_start None → None (arrival cannot be located → the caller skips; never hard-code a year).
    Zenou case: 1995 (low / unchecked, contaminated backfill) vs 2016 (high / human-verified) → pick 2016.
    """
    usable = [r for r in roster_rows if r.get("year_start") is not None]
    if not usable:
        return None
    best = min(usable, key=lambda r: (
        0 if r.get("human_verified") else 1,
        0 if r.get("confidence") == "high" else 1,
        r["year_start"],
    ))
    return best["year_start"]


# For each author at year Y: stock (full-count citations) + subfield + academic-age band → naive rank percentile within the cell. Reference pool = all author_ids.
# Ranking is the naive rank method: rank = RANK() DESC
#   (= 1 + #{strictly higher than me}, ties share the rank), pct = 1 − rank/cell_n; the star decision in star_flags takes rank
#   for exact integer arithmetic (rank ≤ p·N), while pct is only written to disk / displayed. An earlier
#   "mid-rank method (RANK ASC−1+0.5×ties)/N" was withdrawn; its leftover code has been rewritten.
# Two candidate overrides (everyone else in the pool is untouched; only the candidates we care about are refined):
#   1. Subfield {OV}: roster-based, all candidates go to economics (candidates = hand-checked members of the economics departments); the pool uses sf_modal, the mode over paper counts.
#   2. Debut year {FPOV}: "robust debut year" (the robust_first_pub shared pure function, which drops old lone lead-author papers of a same-name other person).
# Pool-side debut year uses the **robust** version instead of a bare MIN(yr): the rfp CTE = the SQL window version of
#   robust_first_pub (DISTINCT years + LEAD gap<= {GAP} filter); measured equal to the Python shared pure function person by person
#   with 0 mismatches; after pool cleaning, none of the 15 people on the 1% list moved and the four headline events were all stable. The candidate FPOV is still
#   a Python shared-function override (same semantics at both ends, symmetric). The stock definition is unchanged: SUM over all yr<=Y (including citations of papers from the dropped years).
# {SOV} person-folded stock override is a native production SQL CTE (the DIAG derivation of
#   stock_fold_diag promoted to production): candidate stock is the "sum over sibling ids in the folded person_id cluster" instead of the bare author_id
#   (SOV values are computed by build_star_set and injected; pool members are not folded, i.e. the whole pool uses bare author_id).
#   The empty placeholder "('__none__',0)" = no override (matches no aid).
# Academic age aage = Y − fp (after override) goes to the seniority threshold in star_flags. This SQL is the **only** production path for star decisions;
# the m7a_star.build_star/classify_all_cells pair is a diagnostic reference and **not production-equivalent** (no roster subfield / robust debut year /
# seniority gate; they have diverged — see the star_identify docstring), so do not use it as a validation oracle.
_STAR_CELL_SQL = """
WITH agg0 AS (SELECT aid, SUM(c) stock FROM aw WHERE yr <= {Y} GROUP BY aid),
rfp AS (SELECT aid, MIN(yr) FILTER (WHERE nxt IS NULL OR nxt - yr <= {GAP}) fp
        FROM (SELECT aid, yr, LEAD(yr) OVER (PARTITION BY aid ORDER BY yr) nxt
              FROM (SELECT DISTINCT aid, yr FROM aw WHERE yr <= {Y}))
        GROUP BY aid),
fpov(aid, fp) AS (VALUES {FPOV}),
sov(aid, stock) AS (VALUES {SOV}),
agg AS (SELECT a.aid, COALESCE(s.stock, a.stock) stock, COALESCE(o.fp, r.fp) fp
        FROM agg0 a JOIN rfp r ON a.aid = r.aid
        LEFT JOIN fpov o ON a.aid = o.aid
        LEFT JOIN sov s ON a.aid = s.aid),
sfc AS (SELECT aid, sf, COUNT(*) n FROM aw WHERE yr <= {Y} AND sf IS NOT NULL GROUP BY aid, sf),
sf_modal AS (SELECT aid, sf FROM (SELECT aid, sf, ROW_NUMBER() OVER (PARTITION BY aid ORDER BY n DESC, sf) rk FROM sfc) WHERE rk=1),
ov(aid, sf) AS (VALUES {OV}),
sf AS (
    SELECT m.aid, m.sf FROM sf_modal m WHERE m.aid NOT IN (SELECT aid FROM ov)
    UNION ALL SELECT aid, sf FROM ov
),
pool AS (SELECT a.aid, a.stock, sf.sf subfield, cbin(CAST({Y}-a.fp AS INTEGER)) age_bin,
                CAST({Y}-a.fp AS INTEGER) aage
         FROM agg a JOIN sf ON a.aid = sf.aid),
ranked AS (SELECT aid, stock, subfield, age_bin, aage,
    RANK() OVER (PARTITION BY subfield, age_bin ORDER BY stock DESC) AS rnk,
    COUNT(*) OVER (PARTITION BY subfield, age_bin) AS cell_n
    FROM pool)
SELECT aid, subfield, age_bin, aage, stock,
       1.0 - CAST(rnk AS DOUBLE) / cell_n AS pct, cell_n, rnk
FROM ranked WHERE aid IN ({IDS})
"""


# Department → OpenAlex institution id (used by the panel fallback to infer the arrival year; measured anchors: Zenou 2016→Monash I56590836, A5002921489→UNSW I31746571)
DEPT_INST = {"monash_econ": "I56590836", "unsw_econ": "I31746571"}

# Caveat on the time basis of stock: the main specification keeps the snapshot, the paper records this caveat, and a 95-person
#   subset serves as a robustness check. The main computation is unchanged; this note is written into the manifest_header with every frozen star_set,
#   and downstream use / the paper must carry this statement when citing stock. All numbers come from a dedicated measurement run.
STOCK_ASOF_NOTE: dict = {
    "signed": "签6 2026-07-16 (选定 b): 主口径保持快照 + caveat + 子集稳健性",
    "basis": ("stock = 2026 快照终身被引 (cited_by_count) 截到任年−1 发表的 works — "
              "含**到任后**收到的引用 (快照终身被引口径, 非 as-of 到任时点)"),
    "forward_inflation": ("前视膨胀实锤 (E3 度量): as-of-(t−1)/快照 比值中位 0.36 ≈ "
                          "快照虚大 ~2.8x (5% 星子集中位 0.41; Zenou 44.7% / A5059428122 "
                          "27.3% / A5059554264 28.2%)"),
    "asof_subset": ("可精算子集 = 95/211 (arrival≥2012, work 级 counts_by_year 固定 "
                    "2012→2026 窗口); 116/211 (arrival<2012) 不可精算 — 95 人子集留稳健性"),
    "pool_note": ("排名是圈内相对比较; 池侧同口径 as-of 对全体作者 API 不可行 → "
                  "判星名单净影响无法度量, 只有候选侧膨胀幅度"),
    "measurement_artifact": (str(_sar_derived_root()) + "/"
                             "f_measure_2026-07-16/asof_stock/ (summary.json + 明细 csv)"),
}


def _derive_panel_arrivals(con, root, missing, *, panel_sub="u3_panel_2026-07-06",
                           person_map_sub="u2_person_map_2026-07-05", min_years=2):
    """Roster lacks the arrival year → infer it from the panel: the first year in which primary_affil_id = the department's institution and the person stays in the department for >= min_years years.

    missing: [(author_id, name, dept_key)]. Returns {author_id: arrival} (those that cannot be inferred are absent).
    The UNSW official_roster did not capture start years → this fills them from the panel (the year the unit id becomes that department); A5054240727 2011 verified on the web.
    """
    from collections import defaultdict
    by_dept: dict = defaultdict(list)
    for aid, _name, dept in missing:
        if dept in DEPT_INST:
            by_dept[dept].append(aid)
    pan = (root / panel_sub / "panel").as_posix()
    pm = (root / person_map_sub / "person_map").as_posix()
    out: dict = {}
    for dept, aids in by_dept.items():
        ids = ",".join("'" + a + "'" for a in aids)
        q = f"""
        WITH pm AS (SELECT author_id, person_id FROM read_parquet('{pm}/**/*.parquet') WHERE author_id IN ({ids})),
        pan AS (SELECT person_id, year FROM read_parquet('{pan}/**/*.parquet') WHERE primary_affil_id='{DEPT_INST[dept]}')
        SELECT pm.author_id, MIN(pan.year) arr
        FROM pm JOIN pan ON pm.person_id = pan.person_id
        GROUP BY pm.author_id HAVING COUNT(*) >= {min_years}
        """
        for aid, arr in con.execute(q).fetchall():
            out[aid] = arr
    return out


def _foreign_poach_flags(con, root, author_arrivals, *, panel_sub="u3_panel_2026-07-06",
                         person_map_sub="u2_person_map_2026-07-05",
                         edges_sub="u1_edges_full_2026-07-05", signal_discards=None):
    """For each candidate → whether it is a pure foreign poach: look at all of its unit rows before arrival → is_foreign_poach (decides, after cleaning contamination, whether the person was in Australia).

    author_arrivals: {author_id: arrival}.
    Contamination (CEPR blow-up / backfill stamping the current unit) is cleaned inside is_foreign_poach with pollution_guard (the Zenou lesson).

    signal_discards: {author_id: [{institution_id,
    year_from, year_to, ...}]} — hand-reviewed "discarded signal" decisions (part-time/honorary affiliations and
    mis-attributed authorships do not count as "has worked in Australia"). An affiliation row matching (author, canonical institution, year window)
    is **not used as evidence of earlier Australian employment** (removed row by row from the is_foreign_poach input); poach is then
    judged organically on the remaining clean evidence — the flag is never forced down.
    Two fail-loud mismatch cases: 1. the entry's author is not among the candidates / has no arrival year → ValueError;
    2. the entry matches 0 rows (institution/year window disagrees with the on-disk evidence) → ValueError (an invalid discard is never silent).
    Returns {"flags": {author_id: bool},
          "signal_discards_applied": {author_id: {"n_rows_discarded", "entries": [...]}}}.
    """
    from collections import defaultdict
    from m7a_star.foreign_poach import is_foreign_poach

    sd = {aid: list(entries) for aid, entries in (signal_discards or {}).items()}
    unknown_sd = sorted(set(sd) - set(author_arrivals))
    if unknown_sd:
        raise ValueError(
            f"_foreign_poach_flags: signal-discard author_id not in the candidate set or without an arrival year "
            f"{unknown_sd} — misspelled id or wrong roster version, no match; stop")
    if not author_arrivals:
        return {"flags": {}, "signal_discards_applied": {}}
    vals = ",".join(f"('{a}',{y})" for a, y in author_arrivals.items())
    atl = (root / panel_sub / "affil_timeline").as_posix()
    pm = (root / person_map_sub / "person_map").as_posix()
    inst = (root / edges_sub / "institutions").as_posix()
    q = f"""
    WITH ar(aid, arr) AS (VALUES {vals}),
    sp AS (SELECT ar.aid, ar.arr, pm.person_id FROM ar
           JOIN read_parquet('{pm}/**/*.parquet') pm ON ar.aid = pm.author_id)
    SELECT sp.aid, a.year, a.raw_affil, a.canonical_affil_id, i.country_code
    FROM sp JOIN read_parquet('{atl}/**/*.parquet') a
        ON sp.person_id = a.person_id AND a.year < sp.arr
    LEFT JOIN read_parquet('{inst}/**/*.parquet') i ON a.canonical_affil_id = i.institution_id
    """
    rows_by: dict = defaultdict(list)
    hits = {aid: [0] * len(entries) for aid, entries in sd.items()}
    for aid, yr, raw, canon, cc in con.execute(q).fetchall():
        ents = sd.get(aid)
        if ents is not None:
            hit = next((i for i, e in enumerate(ents)
                        if canon == e["institution_id"]
                        and e["year_from"] <= yr <= e["year_to"]), None)
            if hit is not None:
                hits[aid][hit] += 1          # Discard: not used as evidence of earlier Australian employment (count recorded as a diagnostic)
                continue
        rows_by[aid].append({"raw_affil": raw, "canonical_affil_id": canon, "country_code": cc})
    zero = [f"{aid}[{i}] inst={e['institution_id']} {e['year_from']}-{e['year_to']} 命中0行"
            for aid, ents in sorted(sd.items())
            for i, e in enumerate(ents) if hits[aid][i] == 0]
    if zero:
        raise ValueError(
            "_foreign_poach_flags: discard-signal entries do not match any pre-arrival evidence row on disk (0 rows hit) — "
            "wrong institution id / year window / roster version; an ineffective discard is never silent: " + "; ".join(zero))
    for aid in sd:                           # A person whose rows are all discarded must still get a flag (empty evidence → False)
        rows_by.setdefault(aid, [])
    flags = {aid: is_foreign_poach(rws) for aid, rws in rows_by.items()}
    applied = {
        aid: {"n_rows_discarded": sum(hits[aid]),
              "entries": [{**{k: e[k] for k in ("dept_key", "institution_id",
                                                "year_from", "year_to", "reason")},
                           "n_rows_matched": hits[aid][i]}
                          for i, e in enumerate(ents)]}
        for aid, ents in sorted(sd.items())}
    return {"flags": flags, "signal_discards_applied": applied}


def build_star_set(derived_root, *, edges_sub="u1_edges_full_2026-07-05",
                   roster_files=ROSTER_FILES,
                   person_map_sub="u2_person_map_2026-07-05",
                   panel_sub="u3_panel_2026-07-06",
                   exclude_candidates=None, poach_overrides=None,
                   signal_discards=None, work_pollution_discards=None,
                   registry_rows=None, overmerge_person_ids=None,
                   discipline_gate_mode="exclude"):
    """Whole run: two-school roster candidates → pick arrival year → rank within the cell of the whole author pool at t−1 → pick stars (definition A).

    Candidate stock is folded to person: the dual-computation diagnostic of stock_fold_diag
      is now the production rule: candidate stock = the sum of works over all sibling ids in the folded person_id cluster (truncated at ≤t−1,
      same as production), injected into the same ranking SQL via SOV. Rules carried over unchanged:
      - clusters flagged suspected_overmerge are **not folded** (they absorb other people's citations; overmerge_person_ids is injected, and star-cluster splits
        become clean once human review resolves them); such candidates keep the bare-id stock and are listed separately in the report for human review;
      - candidates not in person_map (the 10-of-211 kind that bypass U2 disambiguation) cannot be folded → stock is **honestly NULL**
        (even if the bare id has works, it is not passed off as person-level stock); an all-None row means the same as "not in the pool";
      - the reference pool = all bare author_ids; the pool side is not folded; FPOV academic age still uses the bare-id robust debut year
        (folding the person would change academic age = a different identification decision, listed only, not decided).
      The cause of a NULL stock is no longer silent: result["stock_fold_report"] has one row per candidate, with a null_stock_reason column ∈
      {"truncation_empty" (truncation at arrival year−1 leaves nothing), "not_in_person_map"} + would_enter_pool
      (bare side empty but siblings have works ≤t−1 → a signal for human review; a cell is never forged).
    The pool-side debut year is switched to robust in the rfp CTE of _STAR_CELL_SQL (see the note there).
    Discipline gate and sanity flag:
      registry_rows: table A registry rows (dept_key + subfield_excluded) are injected → the discipline gate has a
        **real consumer** (fixes a previously dead config): if a candidate's modal subfield (whole period) ∈ that school's
        excluded set, result["discipline_flags"] gets a discipline_flag.
        None (default / all existing calls) → result["discipline_flags"]=None, no behaviour change.
      result["sanity_age_flags"] (always output): academic_age≤1 → sanity_flag_age
        goes into the human review list (the A5086383420/A5053503664 type of wrong-id / wrong-year signal). Neither flag enters the stars rows (frozen surface untouched).

    person_map_sub / panel_sub can be injected (new upstream directories);
      defaults = the production literals of the earlier runs (existing usage has zero regression); the panel fallback (_derive_panel_arrivals)
      and the poach query (_foreign_poach_flags) both use the injected values — this prevents a silent fork of "changed the roster but still pointing at the old panel".
    Consuming hand-review decisions:
      exclude_candidates: {author_id: reason} — the part-time decision (A5018638208) is applied at the **point where candidates are drawn**
        (roster rows stay, they just do not enter star decisions); who was dropped is recorded in result["excluded_candidates"].
      poach_overrides: {author_id: False} — hand-review decisions (A5086095616 prior_au_employment)
        override the timeline decision; who was changed is recorded in result["poach_overridden"].
      The author_ids in both maps must really be in the candidate set, otherwise ValueError (a mistyped id is caught, fail-loud).
      None = no decisions injected (pure-function unit-test mode); the production orchestration run_u4_full reads the decision file from
      m7a_star.adjudications and injects it fail-loud.
    signal_discards: {author_id: [{institution_id, year_from,
      year_to, evidence+URL...}]} — "part-time/honorary affiliations and mis-attributed authorships before full-time arrival do not count as 'has worked in Australia'":
      matching affiliation rows are discarded one by one in _foreign_poach_flags (not used as evidence of earlier Australian employment), and poach is
      judged organically on the remaining clean evidence (the only legitimate way for A5006190609/A5059428122/A5059554264 to be restored to True;
      forcing True without evidence is still blocked by the adjudications prohibition). Diagnostic counts go to
      result["signal_discards_applied"]; mismatches (person not a candidate / entry matches 0 rows) → ValueError.
    work_pollution_discards: {author_id: [{work_id, ...}]} —
      exactly excludes, by work_id, a single same-name contamination paper that OpenAlex disambiguation wrongly merged into an author (A5071656006's 1985
      meteorology paper: its gap to the true health-economics debut in 1995 is exactly max_leading_gap=10, which robust_first_pub cannot remove).
      The matching (author, work) pairs are removed pair by pair from the stock pool aw → both stock (SUM) and robust debut year (MIN/robust_first_pub)
      are fixed; it acts only on the named works of the named authors (exact; other people citing the same work are unaffected).
      Diagnostics go to result["work_pollution_discarded"]; 0 matching rows (mistyped id) → ValueError, fail-loud.

    Reference pool = all author_ids (global economics population); stock = full-count raw citations;
    cell = subfield × academic age × year, with a double cell gate (100/max(20,30)=30).
    Ranking is the naive rank method (leftover code of the withdrawn mid-rank method rewritten):
    rank = 1 + #{strictly higher in the cell} (ties share the rank), percentile = 1 − rank/N;
    star decision = star_flags takes rank for exact integer arithmetic (rank ≤ p·N, tied groups enter or leave together), independent of the
    round(…,4) of the written percentile (the flag does not use the rounded value).
    Three corrections: 1. candidate subfield = roster-based, all go to economics (candidates = hand-checked members of the economics departments; a 2020 JEL article
    defines a field as a set of journals, but real-data checks show OpenAlex per-paper labels are noisy and arXiv/preprints cannot be assigned to a field, so the journal method fails → use
    the roster identity directly, which fixes A5027090359/A5017960988 being mislabelled); 2. seniority threshold star.min_academic_age (drops the degenerate academic-age 0-1 band, fixes A5046393143);
    3. robust debut year robust_first_pub (drops same-name contamination). **The pure-foreign-poach filter and the write to disk are later layers, not here.** Returns
    [{author_id, name, dept, arrival, subfield, age_bin, academic_age, stock, percentile, cell_n,
    is_star_1pct, is_star_5pct, age_eligible}]; candidates with no arrival year are skipped (no_arrival is counted and reported separately).
    Candidates not in the pool (no works at all ≤t−1): percentile / both flags / age_eligible / **cell_n are all None** —
    "no cell at all" ≠ "a cell with 0 people", so cell_n is not recorded as 0.
    """
    import duckdb
    import sys
    from collections import defaultdict
    import pyarrow.parquet as pq
    from identity.cohort import cohort_bin
    from common._redlines import RED
    from m7a_star.pctile_engine import star_flags, age_eligible
    from m6_generation.academic_age import robust_first_pub

    if discipline_gate_mode not in ("exclude", "flag"):
        raise ValueError(
            f"build_star_set: discipline_gate_mode={discipline_gate_mode!r} must be "
            "'exclude' (default: drop by discipline) | 'flag' (rollback path: flag only) — a typo is rejected")

    cmn = RED["star"]["cell_min_n"]
    gate1 = max(cmn["pct_1"], cmn["floor"])
    gate5 = max(cmn["pct_5"], cmn["floor"])
    p1 = RED["star"]["percentile_primary"]               # top 1% percentile 0.01 (star_flags cutoff = 1−p, not hard-coded)
    p5 = max(RED["star"]["percentile_robustness"])       # top 5% percentile 0.05
    econ_sf = RED["subfield_whitelist"]["include"][0]    # economics subfield (roster-based: all candidates go to it)
    min_age = RED["star"]["min_academic_age"]            # seniority threshold (null → star_flags raises)
    min_gap = RED["academic_age"]["robust_first_pub_max_gap"]   # robust debut-year gap threshold
    if min_gap is None:                                  # unset → never silently default (the SQL uses it, so blow up early)
        from common._redlines import RedlineUnsigned
        raise RedlineUnsigned("build_star_set: academic_age.robust_first_pub_max_gap is not set (null)")

    root = Path(derived_root)
    con = duckdb.connect()
    con.execute("PRAGMA threads=6")
    con.create_function("cbin", lambda a: cohort_bin(int(a)), ["INTEGER"], "VARCHAR")

    # Candidates: two-school roster → group multiple rows by author_id → arrival year (roster first, panel inference if missing)
    rows = []
    for rf in roster_files:
        rows += pq.read_table(str(root / rf)).to_pylist()
    by_author: dict = defaultdict(list)
    for r in rows:
        if r["author_id"] is not None:      # roster row with an empty author id → cannot enter the author pool
            by_author[r["author_id"]].append(r)

    # Dropped at the point where candidates are drawn (part-time decision): roster rows stay, they do not enter star decisions.
    excl = dict(exclude_candidates or {})
    unknown_excl = sorted(set(excl) - set(by_author))
    if unknown_excl:
        raise ValueError(
            f"build_star_set: excluded author_id not among the roster candidates {unknown_excl} — "
            "misspelled id or wrong roster version; stop"
        )
    for aid in excl:
        by_author.pop(aid)

    cand, no_arrival, miss = {}, [], []
    for aid, rs in by_author.items():
        arr = pick_arrival_year(rs)
        name, dept = rs[0].get("display_name"), rs[0].get("dept_key")
        if arr is not None:
            cand[aid] = (name, dept, arr)          # roster has a hand-checked arrival year (mostly Monash)
        else:
            miss.append((aid, name, dept))         # roster lacks the year (mostly UNSW) → panel fallback
    panel_arr = _derive_panel_arrivals(con, root, miss,
                                       panel_sub=panel_sub, person_map_sub=person_map_sub)
    for aid, name, dept in miss:
        if aid in panel_arr:
            cand[aid] = (name, dept, panel_arr[aid])
        else:
            no_arrival.append(aid)
    ep = (root / edges_sub).as_posix()
    # Missing citation count = bad data, blow up loudly (missing ≠ 0, SUM would silently undercount) — this keeps the fail-loud stock rule,
    # instead of silently dropping with `cited_by_count IS NOT NULL` as the old code did. Measured: 0 null rows in the whole database (OpenAlex gives 0, not null);
    # this gate prevents a future degraded data source from silently undercounting someone's stock and flipping is_star.
    # Rows missing publication_year (measured about 18,000 / 0.04%; no year = cannot be placed in time) are still filtered —
    #   no hard stop and the rows stay dropped, but the number dropped is recorded (in the manifest and one line of the run log; "dropped quietly" becomes "dropped and counted");
    #   unlike "missing citations fail-loud": a missing citation count signals a data accident, while a missing year is the normal state of OpenAlex metadata.
    n_null_c = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{ep}/authorship_edges/**/*.parquet') e "
        f"JOIN read_parquet('{ep}/works/**/*.parquet') w ON e.work_id=w.work_id "
        f"WHERE w.cited_by_count IS NULL"
    ).fetchone()[0]
    if n_null_c:
        raise ValueError(
            f"build_star_set: {n_null_c} works counted in the stock lack cited_by_count "
            f"(missing ≠ 0, never silently dropped) — clean or fill them first"
        )
    # Count the join rows removed by the NOT NULL filter (same definition as the aw filter below:
    # the number of rows with missing publication_year after the edges×works join; isolated works without edges never enter stock anyway and are not counted).
    n_dropped_null_pub_year = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{ep}/authorship_edges/**/*.parquet') e "
        f"JOIN read_parquet('{ep}/works/**/*.parquet') w ON e.work_id=w.work_id "
        f"WHERE w.publication_year IS NULL"
    ).fetchone()[0]
    sys.stderr.write(
        f"[U4/build_star_set] dropped {n_dropped_null_pub_year} rows lacking publication_year "
        f"(excluded from stock/circle; recorded as dropped, behaviour unchanged)\n"
    )
    # work_pollution_discards: exactly remove a same-name contamination paper by (author_id, work_id).
    #   0 matching rows (mistyped id / invalid discard) → ValueError fail-loud (same discipline as the signal_discards zero-hit rule).
    wpd = {aid: [e["work_id"] for e in entries]
           for aid, entries in (work_pollution_discards or {}).items()}
    excl_pairs = [(aid, wid) for aid, wids in wpd.items() for wid in wids]
    excl_clause = ""
    if excl_pairs:
        keyset = ",".join("'" + aid + "|" + wid + "'" for aid, wid in excl_pairs)
        hit = dict(con.execute(
            f"SELECT (e.author_id||'|'||w.work_id) k, COUNT(*) "
            f"FROM read_parquet('{ep}/authorship_edges/**/*.parquet') e "
            f"JOIN read_parquet('{ep}/works/**/*.parquet') w ON e.work_id=w.work_id "
            f"WHERE (e.author_id||'|'||w.work_id) IN ({keyset}) GROUP BY k").fetchall())
        zero = [f"{aid}|{wid}" for aid, wid in excl_pairs
                if hit.get(f"{aid}|{wid}", 0) == 0]
        if zero:
            raise ValueError(
                "build_star_set: work_pollution_discards match no (author, work) on disk "
                "(0 rows hit) — a misspelled id or void discard is never silent: " + "; ".join(sorted(zero)))
        excl_clause = f" AND (e.author_id||'|'||w.work_id) NOT IN ({keyset})"
    con.execute(
        f"CREATE TEMP TABLE aw AS SELECT e.author_id aid, w.publication_year yr, "
        f"w.cited_by_count c, w.subfield_id sf "
        f"FROM read_parquet('{ep}/authorship_edges/**/*.parquet') e "
        f"JOIN read_parquet('{ep}/works/**/*.parquet') w ON e.work_id=w.work_id "
        f"WHERE w.publication_year IS NOT NULL{excl_clause}"
    )

    # Discipline gate **at the point where candidates are drawn**, now with production semantics instead of a mere flag (non-economics excluded by discipline): when a registry is injected, a candidate whose modal subfield (mode over the whole period; discipline is an attribute of the person) ∈
    #   that school's excluded set gets discipline_flag=True and (in the default exclude mode) is **excluded from the candidates**:
    #   not in the pool, no star decision; everyone excluded goes into result["discipline_excluded"] (auditable and reversible —
    #   to revert, use discipline_gate_mode="flag"). Zero signal (modal None, cannot be assessed) is **not excluded**.
    #   registry_rows=None (existing calls) → the gate does not run, no behaviour change.
    from m7a_star.discipline_gate import (discipline_flag_rows, excluded_ids_by_dept,
                                          modal_subfield_from_counts, sanity_age_flag_rows)
    discipline_flags = None
    discipline_excluded: list = []
    if registry_rows is not None:
        _gate_cands = [{"author_id": aid, "name": v[0], "dept": v[1]}
                       for aid, v in sorted(cand.items())]
        modal_by_author: dict = {}
        if _gate_cands:
            _gids = ",".join("'" + c["author_id"] + "'" for c in _gate_cands)
            _sfc = con.execute(
                f"SELECT aid, sf, COUNT(*) n FROM aw WHERE aid IN ({_gids}) "
                f"AND sf IS NOT NULL GROUP BY aid, sf").fetchall()
            _counts: dict = defaultdict(dict)
            for _aid, _sf, _n in _sfc:
                _counts[_aid][_sf] = _n
            modal_by_author = {a: modal_subfield_from_counts(c) for a, c in _counts.items()}
        discipline_flags = discipline_flag_rows(_gate_cands, modal_by_author,
                                                excluded_ids_by_dept(registry_rows))
        if discipline_gate_mode == "exclude":
            for _row in discipline_flags:
                if _row["discipline_flag"] is True:      # None (cannot be assessed) is never dropped
                    cand.pop(_row["author_id"])
                    discipline_excluded.append({
                        **_row, "reason": "subfield_excluded (签1 2026-07-16: 按学科剔, "
                                          "回滚=discipline_gate_mode='flag')"})

    # Person-folding plan — read the full person_map clusters (author→person + cluster members),
    #   reusing build_fold_plan/folded_stocks promoted from the stock_fold_diag diagnostic (single source of truth: production and diagnostics use the same folding).
    from m7a_star.stock_fold_diag import build_fold_plan, folded_stocks
    author_to_person: dict = {}
    members_by_person: dict = defaultdict(list)
    _pm_dir = root / person_map_sub / "person_map"
    _pm_files = [_pm_dir] if _pm_dir.is_file() else sorted(_pm_dir.rglob("*.parquet"))
    for _f in _pm_files:
        for _r in pq.read_table(str(_f), columns=["author_id", "person_id"]).to_pylist():
            author_to_person[_r["author_id"]] = _r["person_id"]
            members_by_person[_r["person_id"]].append(_r["author_id"])
    fold_plan = build_fold_plan(
        sorted(cand), author_to_person, dict(members_by_person),
        overmerge_person_ids=frozenset(overmerge_person_ids or ()))
    fold_report_by: dict = {}

    by_year: dict = defaultdict(list)
    for aid, (_, _, arr) in cand.items():
        by_year[arr - 1].append(aid)

    out = []
    for Y in sorted(by_year):
        cids = by_year[Y]
        ids = ",".join("'" + a + "'" for a in cids)
        # Candidate subfield = roster-based: all 145 candidates are hand-checked members of the economics departments → all go to economics
        # (subfield_whitelist.include[0]), ranked against global economists of the same academic age. We do not guess each paper's field: OpenAlex per-paper
        # labels are noisy (the QJE paper of A5017960988 was labelled "sociology"), modern economics often posts preprints/datasets (arXiv → "physics", Dataverse
        # has no field), so the journal method does not work here; and "these people are economists" is a fact checked in the roster. Reference: a 2020 JEL article.
        ov = ",".join(f"('{aid}','{econ_sf}')" for aid in cids)
        # Candidate robust debut-year override: drops old lone lead-author papers of same-name other people (robust_first_pub pure function; candidates only, the pool is untouched)
        yrows = con.execute(f"SELECT aid, yr FROM aw WHERE yr <= {Y} AND aid IN ({ids})").fetchall()
        cand_years: dict = defaultdict(list)
        for aid, yr in yrows:
            cand_years[aid].append(yr)
        fpov_map = {aid: robust_first_pub(cand_years[aid], max_leading_gap=min_gap)
                    for aid in cids if cand_years.get(aid)}
        fpov = ",".join(f"('{aid}',{fp})" for aid, fp in fpov_map.items()) or "('__none__',0)"
        # Person-folded stock: sum over sibling ids of the folded cluster ≤Y → injected as SOV into the same ranking machine (overrides only candidates in the pool;
        #   overmerge clusters and ids not in the map are not folded inside folded_stocks).
        folded = folded_stocks(con, fold_plan, Y=Y, aids=cids)
        sov_pairs = [(aid, folded[aid]) for aid in cids
                     if aid in folded and cand_years.get(aid)]
        sov = ",".join(f"('{a}',{int(s)})" for a, s in sov_pairs) or "('__none__',0)"
        got = {r[0]: r for r in con.execute(
            _STAR_CELL_SQL.format(Y=Y, IDS=ids, OV=ov, FPOV=fpov,
                                  SOV=sov, GAP=int(min_gap))).fetchall()}
        for aid in cids:
            name, dept, arr = cand[aid]
            plan_e = fold_plan[aid]
            status = plan_e["fold_status"]
            r = got.get(aid)
            if status == "not_in_person_map":
                r = None    # Hard rule: if it cannot be folded → honestly NULL (even if the bare id has works, it is not passed off as person-level stock)
            _rep = {"author_id": aid, "name": name, "dept": dept,
                    "person_id": plan_e["person_id"], "fold_status": status,
                    "n_siblings": len(plan_e["sibling_ids"]),
                    "stock": None, "null_stock_reason": None, "would_enter_pool": False}
            if not r:
                # Not in the pool (no works ≤t−1): cell_n=None, not 0 ("no cell" ≠ "a cell with 0 people")
                # The cause of a NULL stock is no longer silent: reason column = truncation_empty / not in map; siblings have works → would_enter signal for human review.
                _rep["null_stock_reason"] = (
                    "not_in_person_map" if status == "not_in_person_map"
                    else "truncation_empty")
                _rep["would_enter_pool"] = bool(status == "folded" and aid in folded)
                fold_report_by[aid] = _rep
                out.append({"author_id": aid, "name": name, "dept": dept, "arrival": arr,
                            "subfield": econ_sf, "age_bin": None, "academic_age": None,
                            "stock": None, "percentile": None, "cell_n": None,
                            "is_star_1pct": None, "is_star_5pct": None, "age_eligible": None})
                continue
            _, sf, ab, aage, stock, pct, cn, rnk = r
            _rep["stock"] = int(stock)
            fold_report_by[aid] = _rep
            # The star decision takes rank (exact integer arithmetic); pct is only written to disk (round 4; the flag does not use the rounded value)
            s1, s5 = star_flags(rnk, cn, aage, gate1=gate1, gate5=gate5, min_academic_age=min_age, p1=p1, p5=p5)
            out.append({
                "author_id": aid, "name": name, "dept": dept, "arrival": arr,
                "subfield": sf, "age_bin": ab, "academic_age": int(aage), "stock": int(stock),
                "percentile": round(pct, 4), "cell_n": cn,
                "is_star_1pct": s1, "is_star_5pct": s5,
                "age_eligible": age_eligible(aage, min_academic_age=min_age),
            })
    # Pure-foreign-poach filter: for each candidate look at the unit rows before arrival → is_foreign_poach (judge presence in Australia after cleaning contamination)
    # Signal discards are removed row by row inside _foreign_poach_flags (organic judgment, the flag is never forced down).
    fp_res = _foreign_poach_flags(con, root,
                                  {s["author_id"]: s["arrival"] for s in out},
                                  panel_sub=panel_sub, person_map_sub=person_map_sub,
                                  edges_sub=edges_sub,
                                  signal_discards=signal_discards)
    fp = fp_res["flags"]
    for s in out:
        s["is_foreign_poach"] = fp.get(s["author_id"], False)
    # Hand-review override of the poach flag (A5086095616: prior Australian employment → not a pure foreign poach;
    #   the star flags are computed as usual, only is_foreign_poach changes — the criterion is "never worked in Australia before").
    pov = dict(poach_overrides or {})
    unknown_pov = sorted(set(pov) - {s["author_id"] for s in out})
    if unknown_pov:
        raise ValueError(
            f"build_star_set: poach-override author_id not in the candidate set {unknown_pov} — "
            "misspelled id or wrong roster version; stop"
        )
    for s in out:
        if s["author_id"] in pov:
            s["is_foreign_poach"] = pov[s["author_id"]]
    # The discipline gate has moved up to the point where candidates are drawn (judged right after the aw table is built, excluding by default); only the sanity gate remains here.
    # Sanity gate: academic_age≤1 raises a flag
    #   and goes into the human review list (not dropped automatically; the orchestration layer run_u4_full merges it into human_adjudication_queue).
    sanity_age_flags = sanity_age_flag_rows(out)
    # The dropped count is returned with result → freeze_star_set writes it into manifest_header (counted drop).
    return {"stars": out, "no_arrival": no_arrival,
            "n_dropped_null_pub_year": int(n_dropped_null_pub_year),
            "excluded_candidates": excl, "poach_overridden": pov,
            "signal_discards_applied": fp_res["signal_discards_applied"],
            "work_pollution_discarded": {aid: sorted(wids)
                                         for aid, wids in sorted(wpd.items())},
            "discipline_flags": discipline_flags,
            "discipline_excluded": discipline_excluded,
            "sanity_age_flags": sanity_age_flags,
            "stock_fold_report": [fold_report_by[a] for a in sorted(fold_report_by)]}


class GoldenFailure(RuntimeError):
    """Zenou gold-standard gate failed → stop production (never write a star set that is missing Zenou)."""


def assert_zenou_golden(stars):
    """Five hard Zenou checks: found + top 1% + foreign poach + Monash + arrival 2016. Any failure → blow up."""
    z = next((s for s in stars if s["author_id"] == "A5017376589"), None)
    ok = bool(z and z["is_star_1pct"] and z["is_foreign_poach"]
              and z["arrival"] == 2016 and z["dept"] == "monash_econ")
    if not ok:
        raise GoldenFailure(f"Yves Zenou golden test failed: {z}")


def resolve_provenance(derived_root, *, edges_sub="u1_edges_full_2026-07-05") -> dict:
    """Deterministically resolve the two provenance values from existing artifacts.

    - source_snapshot_merkle: read the **existing** value in the direct upstream U1's real-run reproducibility record
      <derived_root>/<edges_sub>/_manifest/run_manifest.json — meaning = the Merkle root of the frozen M0
      snapshot propagated through U1 (U0 common/manifest.py rule: only read stored values to pass on / compare,
      never recompute the merkle).
    - config_sha: deterministic SHA256 of the configuration contracts/redlines.yaml
      (common._redlines.sha256_of_red, same definition as preflight environment gate 3) = the fingerprint of the RED this process actually consumes.
    Unreadable / empty → ValueError fail-loud (never emit a placeholder string; the intent of the lineage fingerprint is that all four members of the 4-tuple are non-empty).
    """
    import json
    from common._redlines import sha256_of_red

    mf = Path(derived_root) / edges_sub / "_manifest" / "run_manifest.json"
    if not mf.is_file():
        raise ValueError(
            f"resolve_provenance: upstream U1 run_manifest not found at {mf} — "
            "source_snapshot_merkle cannot be read deterministically; fail-loud (never fill a placeholder string)"
        )
    merkle = json.loads(mf.read_text(encoding="utf-8")).get("source_snapshot_merkle")
    if not merkle:
        raise ValueError(
            f"resolve_provenance: source_snapshot_merkle in {mf} is missing/empty — "
            "an empty value is never passed through"
        )
    return {"source_snapshot_merkle": merkle, "config_sha": sha256_of_red()}


def freeze_star_set(result, out_dir, *, source_snapshot_merkle: str | None = None,
                    config_sha: str | None = None, derived_root=None,
                    edges_sub="u1_edges_full_2026-07-05"):
    """Write to disk: Zenou gold-standard gate → only if it passes write star_set.parquet (canonical-sorted by author_id, deterministic)
    + the provenance sidecar (manifest_header.json 4-tuple + dropped-row accounting).

    Fix (original defect: a bare write_table, no fingerprint computed, no provenance written):
      - stars_set_hash = freeze.stars_set_hash({author_id: arrival}) (deterministic, invariant to order;
        it takes normalised content, not raw parquet bytes, so it is stable across pyarrow versions). It binds
        the author_id→arrival of all frozen candidates and makes no "who is a star" identification decision (neutral for identification).
      - The 4-tuple mirrors write_fwci_baseline in the same library: stars_set_hash / source_snapshot_merkle /
        config_sha / rule_version (read from RED).
    Original defect: merkle/config_sha defaulted to an empty string and were silently written (the real-data
    manifest showed both empty). An explicitly passed value takes priority; if not passed, given derived_root → resolve_provenance
    resolves and injects them deterministically; with neither, or an empty string → ValueError fail-loud, a placeholder is never written.
    result must carry n_dropped_null_pub_year (the number dropped for missing publication_year, counted by build_star_set)
    → written into manifest_header ("dropped quietly" becomes "dropped and counted"); a missing key raises KeyError.
    If the gate fails (assert_zenou_golden) nothing is written to disk (resolving / fingerprinting / writing all come after the gate).
    """
    import json
    import pyarrow as pq_pa
    import pyarrow.parquet as pq
    from common._redlines import RED
    from m7a_star.freeze import stars_set_hash
    stars = result["stars"]
    assert_zenou_golden(stars)                       # If the gate fails nothing is written (fingerprint + write both come after it)
    # Provenance injection (all after the gate, before the write; if resolving fails → nothing is written).
    if source_snapshot_merkle is None or config_sha is None:
        if derived_root is None:
            raise ValueError(
                "freeze_star_set: source_snapshot_merkle/config_sha not injected explicitly and no "
                "derived_root given to resolve them — fail-loud (never write an empty-string placeholder again)"
            )
        pv = resolve_provenance(derived_root, edges_sub=edges_sub)
        if source_snapshot_merkle is None:
            source_snapshot_merkle = pv["source_snapshot_merkle"]
        if config_sha is None:
            config_sha = pv["config_sha"]
    if not source_snapshot_merkle or not config_sha:
        raise ValueError(
            "freeze_star_set: provenance value is an empty string — a placeholder string is never written to disk"
        )
    n_dropped = result["n_dropped_null_pub_year"]    # The accounting field must be present (a missing key blows up)
    rows = sorted(stars, key=lambda s: s["author_id"])
    set_hash = stars_set_hash({s["author_id"]: s["arrival"] for s in rows})
    n_fp_stars = sum(1 for s in rows if s["is_star_5pct"] and s["is_foreign_poach"])
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pq.write_table(pq_pa.Table.from_pylist(rows), str(out / "star_set.parquet"))
    header = {
        "table": "star_set",
        "stars_set_hash": set_hash,
        "source_snapshot_merkle": source_snapshot_merkle,
        "config_sha": config_sha,
        "rule_version": RED.get("rule_version", ""),
        "n_candidates": len(rows),
        "n_foreign_poach_stars": n_fp_stars,
        "n_dropped_null_pub_year": n_dropped,        # Counted drop
        "stock_asof_note": STOCK_ASOF_NOTE,          # Caveat on the time basis of stock goes along with the file
    }
    (out / "manifest_header.json").write_text(
        json.dumps(header, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")
    return {"n_candidates": len(rows),
            "n_foreign_poach_stars": n_fp_stars,
            "n_dropped_null_pub_year": n_dropped,
            "stars_set_hash": set_hash,
            "path": str(out / "star_set.parquet"),
            "provenance_path": str(out / "manifest_header.json")}


# =============================================================================
# U4 first shipment wave — wiring of the fwci_baseline / paper_contrib tables
# (additions only: the star-decision / ranking frozen zone above — _STAR_CELL_SQL/build_star_set/freeze_star_set — is untouched)
# =============================================================================

def ship_fwci_baseline(derived_root, out_dir, *, edges_sub="u1_edges_full_2026-07-05"):
    """Thin wiring: read U1 fwci_baseline_pop (bucketed or single file, transparent) → build_fwci_baseline
    (expected=mean + the included_types whitelist, symmetric with the denominator; all-None subfield → HALT is inside)
    → inject via resolve_provenance (empty value fail-loud) → write_fwci_baseline.

    Three fail-loud points: 1. pop table missing / 0 rows → ValueError (an empty baseline would make everything downstream missing_cell,
    never silent); 2. U1 run_manifest missing / merkle empty → resolve_provenance ValueError,
    nothing written; 3. snapshot_year not set → require raises inside write (it is set, so this passes).
    Returns {"n_rows", "path", "header"}.
    """
    from common.derived_table import read_derived_table
    from m5_output.fwci_baseline_build import build_fwci_baseline, write_fwci_baseline

    pop_dir = Path(derived_root) / edges_sub / "fwci_baseline_pop"
    pop_rows = read_derived_table(pop_dir)
    if not pop_rows:
        raise ValueError(
            f"ship_fwci_baseline: fwci_baseline_pop absent or has 0 rows ({pop_dir}) — "
            "an empty baseline would make every downstream fwci a missing_cell; fail-loud, never silently written to disk"
        )
    rows = build_fwci_baseline(pop_rows)
    if not rows:
        raise ValueError(
            "ship_fwci_baseline: 0 rows after the whitelist filter (is no pop row an article/review?) — "
            "an empty baseline is never silently written to disk; check upstream first"
        )
    pv = resolve_provenance(derived_root, edges_sub=edges_sub)   # On failure → nothing is written
    tdir = Path(out_dir) / "fwci_baseline"
    header = write_fwci_baseline(
        rows, tdir,
        source_snapshot_merkle=pv["source_snapshot_merkle"], config_sha=pv["config_sha"])
    return {"n_rows": len(rows), "path": str(tdir / "data.parquet"), "header": header}


def ship_leave_star_baseline(derived_root, out_dir, *, star_work_ids, affected_cells,
                             edges_sub="u1_edges_full_2026-07-05"):
    """Leave-star-out: recompute expected on a small scope from the works table for the affected cells
    (excluding star works; does not modify POP; no conflict with "the denominator side does not drop stars" — it only builds a reference baseline for the affected cohort).

    The denominator keeps the symmetric definition: included_types whitelist (inside rebuild) + paratext symmetric drop (the SQL of this function,
    real key fwci.paratext_symmetric_drop=true). The cell set is passed explicitly as part of the definition (small scope ≠ global);
    empty cells → ValueError, never a silent full scan. Writes the sidecar table fwci_baseline_leave_star
    (a comparison/diagnostic artifact outside the six main tables; the table name is explicitly marked leave_star) with its own provenance header.
    """
    import json
    import duckdb
    from common._redlines import RED, require
    from common.schema import FWCI_BASELINE
    from m1_ingest._writer_util import write_rows_parquet
    from m5_output.fwci_baseline_build import rebuild_leave_star_baseline

    cells = set(affected_cells)
    if not cells:
        raise ValueError("ship_leave_star_baseline: affected_cells is empty — "
                         "the affected cell set must be passed explicitly (small-scope recompute, never a silent full scan)")
    star_ids = set(star_work_ids)
    wdir = (Path(derived_root) / edges_sub / "works").as_posix()
    subs = ",".join("'" + str(c[0]) + "'" for c in cells)
    yrs = ",".join(str(int(c[1])) for c in cells)
    typs = ",".join("'" + str(c[2]) + "'" for c in cells)
    con = duckdb.connect()
    try:
        works_rows = [
            {"work_id": r[0], "subfield_id": r[1], "publication_year": r[2],
             "work_type": r[3], "cited_by_count": r[4]}
            for r in con.execute(
                # Coarse filter (component IN; the exact combination filter is done by cells inside rebuild); paratext symmetric drop = symmetric denominator
                f"SELECT work_id, subfield_id, publication_year, work_type, cited_by_count "
                f"FROM read_parquet('{wdir}/**/*.parquet') "
                f"WHERE subfield_id IN ({subs}) AND publication_year IN ({yrs}) "
                f"AND work_type IN ({typs}) "
                f"AND (is_paratext IS NULL OR is_paratext = FALSE)"
            ).fetchall()]
    finally:
        con.close()
    rows = rebuild_leave_star_baseline(works_rows, star_ids, cells)
    pv = resolve_provenance(derived_root, edges_sub=edges_sub)   # On failure → nothing is written
    tdir = Path(out_dir) / "fwci_baseline_leave_star"
    write_rows_parquet(rows, tdir / "data.parquet", schema=FWCI_BASELINE,
                       pk_cols=("subfield_id", "year", "work_type"),
                       label="fwci_baseline_leave_star")
    header = {
        "table": "fwci_baseline_leave_star",
        "leave_star": True,
        "source_snapshot_merkle": pv["source_snapshot_merkle"],
        "config_sha": pv["config_sha"],
        "rule_version": RED.get("rule_version", ""),
        "stars_set_hash": "",                     # Keys as in the main table, injected by U5
        "snapshot_year": require("fwci", "snapshot_year"),
        "n_star_works_excluded": len(star_ids),
        "n_cells": len(cells),
    }
    (tdir / "manifest_header.json").write_text(
        json.dumps(header, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")
    return {"n_rows": len(rows), "path": str(tdir / "data.parquet"), "header": header}


def _read_author_person(derived_root, *, person_map_sub="u2_person_map_2026-07-05") -> dict:
    """person_map is read in full, only 2 columns → {author_id: person_id} (do not consume the NULL quality columns; guard)."""
    import pyarrow.parquet as pq

    pm_dir = Path(derived_root) / person_map_sub / "person_map"
    files = [pm_dir] if pm_dir.is_file() else sorted(pm_dir.rglob("*.parquet"))
    if not files:
        raise ValueError(f"_read_author_person: person_map absent ({pm_dir}) — fail-loud")
    out: dict = {}
    for f in files:
        for r in pq.read_table(str(f), columns=["author_id", "person_id"]).to_pylist():
            out[r["author_id"]] = r["person_id"]
    return out


def finalize_paper_contrib(rows, diag_rows, *, star_author_ids, author_person, out_dir):
    """paper_contrib shipping tail: isc two-stage backfill → 256-bucket write
    (PK conflict blows up) → diagnostics sidecar → _reports (subfield-fallback safeguard 1: [inferred] share + FWCI-NA count).

    Input rows = assembled 8-key rows (fwci passes through as is — nothing is capped);
    star_author_ids = the star author_id set folded from the frozen star_set
    (no person_map mapping → counted with a WARN, never silent; see fold_star_authors_to_persons).
    Returns {"n_rows", "n_dedup_dropped", "n_works", "n_star_persons",
    "n_unmapped_star_authors", "unmapped_star_author_ids", "inferred_ratio", "na_counts"}.
    """
    from m1_ingest._writer_util import write_rows_parquet
    from m5_output.assemble_contrib import (PAPER_CONTRIB_DIAG,
                                            fold_star_authors_to_persons,
                                            backfill_isc, write_fwci_na_report)
    from m5_output.fallback_reports import write_inferred_report
    from m5_output.write_paper_contrib import write_paper_contrib

    fold = fold_star_authors_to_persons(star_author_ids, author_person)
    filled = backfill_isc(rows, fold["star_person_ids"])
    wres = write_paper_contrib(filled, out_dir)          # 256 buckets; same PK with conflicting payload → blow up
    diag = [dict(d) for d in diag_rows]
    write_rows_parquet(diag, Path(out_dir) / "paper_contrib_diag" / "data.parquet",
                       schema=PAPER_CONTRIB_DIAG, pk_cols=("work_id",),
                       label="paper_contrib_diag")
    stats = write_inferred_report(diag, out_dir)         # Subfield-fallback safeguard 1 (share written to _reports)
    na_counts = write_fwci_na_report(diag, out_dir)      # Accounting: FWCI-NA count
    return {
        "n_rows": wres["n_rows"],
        "n_dedup_dropped": wres["n_dedup_dropped"],
        "n_works": len(diag),
        "n_star_persons": len(fold["star_person_ids"]),
        "n_unmapped_star_authors": len(fold["unmapped_star_author_ids"]),
        "unmapped_star_author_ids": fold["unmapped_star_author_ids"],
        "inferred_ratio": stats["ratio"],
        "na_counts": na_counts,
    }


def ship_paper_contrib(derived_root, out_dir, *, star_rows,
                       edges_sub="u1_edges_full_2026-07-05",
                       person_map_sub="u2_person_map_2026-07-05",
                       roster_files=ROSTER_FILES,
                       field_expected=None, field_of_work=None):
    """Production shipping orchestration of paper_contrib (M5-T1/T2/T3 + two-stage isc):

    roster incumbents (table B × person_map; scope = the two schools' roster persons) → pop→baseline expected
    (same build as ship_fwci_baseline: same source, same list) → assemble (isc stage one False;
    fwci passes through as is) → star_pool_author_ids (frozen star_set rows; full 5% pool ∧ foreign_poach)
    → finalize (backfill + 256 buckets + sidecar + _reports).

    **No capping (recorded as is)**: the pipeline does no winsorization at all;
    each paper's fwci enters the store as is, and skewness is handled in the regression layer (none of the 8 benchmark papers
    reviewed caps fwci; paratext dropping is unchanged). The former winsorization
    guard stage (which halted shipping while the pool scope was unset) has been removed, so this function now runs straight through to the write.
    """
    from common.derived_table import read_derived_table
    from m5_output.assemble_contrib import (assemble_paper_contrib,
                                            star_pool_author_ids)
    from m5_output.fwci_baseline_build import build_fwci_baseline

    author_person = _read_author_person(derived_root, person_map_sub=person_map_sub)
    roster_rows: list[dict] = []
    import pyarrow.parquet as pq
    for rf in roster_files:
        roster_rows += pq.read_table(str(Path(derived_root) / rf)).to_pylist()
    mapped = map_incumbents([r for r in roster_rows if r.get("author_id") is not None],
                            author_person)
    incumbent_pids = {i["person_id"] for i in mapped["incumbents"]}
    if not incumbent_pids:
        raise ValueError("ship_paper_contrib: roster in-post members fold to 0 people via person_map — "
                         "empty scope = assembly failure; fail-loud")

    pop_dir = Path(derived_root) / edges_sub / "fwci_baseline_pop"
    pop_rows = read_derived_table(pop_dir)
    if not pop_rows:
        raise ValueError(f"ship_paper_contrib: fwci_baseline_pop absent or has 0 rows ({pop_dir}) "
                         "— no source for the expected values; fail-loud")
    expected_by_cell = {
        (r["subfield_id"], r["year"], r["work_type"]): r["expected_citations"]
        for r in build_fwci_baseline(pop_rows)}

    asm = assemble_paper_contrib(
        derived_root, incumbent_person_ids=incumbent_pids, author_person=author_person,
        expected_by_cell=expected_by_cell, field_expected=field_expected,
        field_of_work=field_of_work, edges_sub=edges_sub)
    # fwci passes through as is (the former winsor stage has been removed; nothing is capped).
    return finalize_paper_contrib(
        asm["rows"], asm["diag"], star_author_ids=star_pool_author_ids(star_rows),
        author_person=author_person, out_dir=out_dir)


# =============================================================================
# U4 third shipment wave — frozen_star_rows reads the frozen artifact + stars_set_hash binding check
# (additions only: the star-decision / ranking frozen zone is untouched)
# =============================================================================

class FrozenStarSetMismatch(RuntimeError):
    """The frozen star_set fingerprint binding check failed (hash recomputed from the on-disk rows ≠ the hash in manifest_header)
    → HALT: the frozen artifact was altered or the wrong file was read; never continue shipping with a distorted star set."""


def load_frozen_star_rows(frozen_dir) -> dict:
    """Read the frozen star_set (read-only) + stars_set_hash binding check.

    Check = recompute freeze.stars_set_hash({author_id: arrival}) == the stars_set_hash
    stored in manifest_header.json; unequal → FrozenStarSetMismatch HALT. parquet / header absent,
    or header fingerprint empty → ValueError (no binding = cannot verify; never trust the bare parquet).
    Returns {"rows": [...], "header": {...}, "stars_set_hash": str}.
    """
    import json
    import pyarrow.parquet as pq
    from m7a_star.freeze import stars_set_hash

    d = Path(frozen_dir)
    ppath = d / "star_set.parquet"
    hpath = d / "manifest_header.json"
    if not ppath.is_file():
        raise ValueError(f"load_frozen_star_rows: frozen star_set.parquet not found at {ppath} — "
                         "fail-loud (never continue empty-handed)")
    if not hpath.is_file():
        raise ValueError(f"load_frozen_star_rows: manifest_header.json not found at {hpath} — "
                         "no bound fingerprint, so it cannot be verified; fail-loud")
    header = json.loads(hpath.read_text(encoding="utf-8"))
    bound = header.get("stars_set_hash")
    if not bound:
        raise ValueError(
            f"load_frozen_star_rows: stars_set_hash in {hpath} is missing/empty — "
            "no bound fingerprint, so it cannot be verified; fail-loud")
    rows = pq.read_table(str(ppath)).to_pylist()
    recomputed = stars_set_hash({r["author_id"]: r["arrival"] for r in rows})
    if recomputed != bound:
        raise FrozenStarSetMismatch(
            f"load_frozen_star_rows: fingerprint binding check failed — recomputed from rows on disk {recomputed} ≠ "
            f"manifest_header bound {bound} (frozen file was altered / wrong file read) → HALT, needs human inspection")
    return {"rows": rows, "header": header, "stars_set_hash": recomputed}


# =============================================================================
# U4 second shipment wave — wiring of the events (star arrival events) table
# (additions only: the star-decision / ranking frozen zone and the first-wave ship_* are untouched)
# =============================================================================

def ship_events(derived_root, out_dir, *, frozen_star_rows, evidence_by_star,
                truth_evidence_by_star, modal_inst_year_by_star,
                edges_sub="u1_edges_full_2026-07-05", hv_arrival_basis=None):
    """Production shipping orchestration of events (the M7a-T6/T7/T8 chain + a hard consistency gate):

    frozen star_set rows folded into the shipping set (is_star_5pct ∧ is_foreign_poach, the single star list)
    → per star derive_star_event (pollution_guard cleaning → timeline → detect_arrival/
    detect_departure → truth_dates evidence annotation → the 11 EVENTS columns)
    → hard consistency gate: events.arrival_year (detect_arrival route) must equal, for every shipped star, the frozen
    star_set.arrival (pick_arrival_year route, fingerprint bound).

    Supplementary rule (hv_arrival_basis): for shipped stars whose arrival year carries **human-verified evidence**
    (roster human_verified / human_verified_web / the adjudication arrival_verifications, with year
    == the frozen year — criterion in adjudications.human_verified_arrival_basis) — when the two routes disagree, this is
    **downgraded to a diagnostic record**: the difference is still written to arrival_mismatch_report.json (marked
    "explained: human_verified evidence prevails" + hv_basis + halt=False), and the event row
    is written with the **authoritative frozen year** via build_event_at_authoritative_year, with no HALT.
    **Stars without human-verified evidence get no relaxation**: routes disagree → report (halt=True) + raise
    ArrivalMismatch, and the events table is not written at all — a disagreement at the identification layer goes to a human, the code never picks a route itself.

    → resolve_provenance (empty value fail-loud) → write_events (schema/PK/single star list/atomic write)
    + the pollution-drop count goes to `_reports/events_pollution_dropped.csv`.

    Inputs (synthetic supply here; real-data assembly is done in run_u4_full):
        frozen_star_rows: frozen star_set rows (author_id/arrival/dept/both flags/is_foreign_poach).
        evidence_by_star: {author_id: evidence rows} (the shape pollution_guard takes, derived from the U3 affil_timeline).
        truth_evidence_by_star: {author_id: {six source names: year}} (output of evidence_assembly; missing = no evidence file).
        modal_inst_year_by_star: {author_id: bool} (U3 is_modal side evidence, consume-only;
            a shipped star with no supply → blow up, never silently default to False).
        hv_arrival_basis: {author_id: basis string} (human-verified criterion map; None = empty map → the original discipline).
    Returns {"n_events", "path", "provenance_path", "stars_set_hash",
          "n_polluted_dropped", "p01_event_ids", "n_explained_mismatch", "explained_ids"}.
    """
    import json as _json
    from common.atomic_io import atomic_write_bytes
    from m7a_star.events_pipeline import (ArrivalMismatch, arrival_consistency_diff,
                                          build_event_at_authoritative_year,
                                          derive_star_event, ship_set_ids)
    from m7a_star.freeze import stars_set_hash
    from m7a_star.write_events import write_events

    frozen = [dict(s) for s in frozen_star_rows]
    ship_ids = ship_set_ids(frozen)
    if not ship_ids:
        raise ValueError(
            "ship_events: ship set is empty (no is_star_5pct ∧ is_foreign_poach rows) — "
            "an empty events table is never produced silently (S8-8)"
        )
    frozen_by_id = {s["author_id"]: s for s in frozen}

    # Input coverage guard: if any shipped star lacks its evidence / side-evidence supply, blow up (never silently skip a person or default).
    missing_ev = sorted(sid for sid in ship_ids if sid not in evidence_by_star)
    if missing_ev:
        raise ValueError(f"ship_events: shipped stars lack an evidence-row supply {missing_ev} — fail-loud")
    missing_modal = sorted(sid for sid in ship_ids if sid not in modal_inst_year_by_star)
    if missing_modal:
        raise ValueError(
            f"ship_events: shipped stars lack an is_modal side-evidence supply {missing_modal} "
            "(U3 is consume-only; never default to False)"
        )
    unknown_dept = sorted({frozen_by_id[sid]["dept"] for sid in ship_ids}
                          - set(DEPT_INST))
    if unknown_dept:
        raise ValueError(
            f"ship_events: dept of frozen rows not in the DEPT_INST map {unknown_dept} "
            "(outside the two-university smoke-test scope) — fail-loud"
        )

    # Run the assembly chain for each shipped star (pure-function layer).
    derived: dict = {}
    for sid in sorted(ship_ids):
        derived[sid] = derive_star_event(
            star_person_id=sid,
            dept_id=DEPT_INST[frozen_by_id[sid]["dept"]],
            evidence_rows=evidence_by_star[sid],
            truth_evidence=truth_evidence_by_star.get(sid, {}),
            modal_inst_year=modal_inst_year_by_star[sid],
        )
    events_by_star = {sid: d["event"] for sid, d in derived.items()}

    # Hard consistency gate: compare the two arrival-year routes person by person; unequal → branch:
    #   human-verified evidence (hv_arrival_basis) → downgraded to a diagnostic record (explained), the event row uses the authoritative frozen year;
    #   no human-verified evidence → report + HALT (the events table is not written at all) — the original discipline is not relaxed.
    diff = arrival_consistency_diff(events_by_star, frozen)
    reports_dir = Path(out_dir) / "_reports"
    hv = dict(hv_arrival_basis or {})
    explained = [d for d in diff if d["star_person_id"] in hv]
    unexplained = [d for d in diff if d["star_person_id"] not in hv]
    if diff:
        for d in diff:                       # Add audit detail to the report: the judged institution / structural note / evidence file
            sid = d["star_person_id"]
            det = derived.get(sid)
            d["detected_arrival_institution"] = (
                det["arrival"]["arrival_institution"] if det else None)
            d["arrival_inst_mismatch"] = bool(det and det["arrival_inst_mismatch"])
            d["truth_evidence"] = dict(truth_evidence_by_star.get(sid, {}))
            if sid in hv:                    # Human-verified web evidence prevails → diagnostic record, no HALT
                d["explained"] = "human_verified evidence prevails"
                d["hv_basis"] = hv[sid]
                d["halt"] = False
            else:
                d["explained"] = None
                d["halt"] = True
        reports_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(
            reports_dir / "arrival_mismatch_report.json",
            _json.dumps({"table": "events", "gate": "arrival_consistency (两路到任年)",
                         "n_mismatch": len(diff), "n_explained": len(explained),
                         "n_halt": len(unexplained), "diff": diff},
                        ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8"))
    if unexplained:
        raise ArrivalMismatch(
            f"ship_events consistency gate: {len(unexplained)} shipped stars have unequal arrival years on the two paths and no manually verified evidence "
            f"— HALT, difference report = {reports_dir / 'arrival_mismatch_report.json'}; "
            "a disagreement in the identification layer is for a human to resolve; the code never picks one path", unexplained)

    # Explained stars: rebuild the event row with the authoritative frozen year (human verification prevails; the disagreement is in the diagnostic report).
    for d in explained:
        sid = d["star_person_id"]
        rebuilt = build_event_at_authoritative_year(
            star_person_id=sid,
            dept_id=DEPT_INST[frozen_by_id[sid]["dept"]],
            timeline=derived[sid]["timeline"],
            truth_evidence=truth_evidence_by_star.get(sid, {}),
            modal_inst_year=modal_inst_year_by_star[sid],
            arrival_year=frozen_by_id[sid]["arrival"])
        derived[sid]["event"] = rebuilt["event"]

    # Pass → provenance (fail-loud) → write (single star list / schema / PK / atomic write are all inside write_events).
    pv = resolve_provenance(derived_root, edges_sub=edges_sub)
    set_hash = stars_set_hash({s["author_id"]: s["arrival"] for s in frozen})
    n_dropped_total = sum(d["n_polluted_dropped"] for d in derived.values())
    res = write_events(
        [d["event"] for _, d in sorted(derived.items())],
        Path(out_dir) / "events",
        ship_star_ids=ship_ids, stars_set_hash=set_hash,
        source_snapshot_merkle=pv["source_snapshot_merkle"],
        config_sha=pv["config_sha"], n_polluted_dropped=n_dropped_total)

    # Pollution-drop counts are recorded (_reports csv, atomic write).
    reports_dir.mkdir(parents=True, exist_ok=True)
    csv_lines = ["star_person_id,n_polluted_dropped"] + [
        f"{sid},{derived[sid]['n_polluted_dropped']}" for sid in sorted(ship_ids)]
    atomic_write_bytes(reports_dir / "events_pollution_dropped.csv",
                       ("\n".join(csv_lines) + "\n").encode("utf-8"))

    # p01 analysis set = the is_star_1pct subset of the same table (never produce a second events table).
    p01_ids = sorted(sid for sid in ship_ids if frozen_by_id[sid].get("is_star_1pct"))
    return {"n_events": res["n_events"], "path": res["path"],
            "provenance_path": res["provenance_path"], "stars_set_hash": set_hash,
            "n_polluted_dropped": n_dropped_total, "p01_event_ids": p01_ids,
            "n_explained_mismatch": len(explained),
            "explained_ids": sorted(d["star_person_id"] for d in explained)}


# =============================================================================
# U4 third shipment wave — run_u4_full overall orchestration
# (additions only: the star-decision / ranking frozen zone and the first/second-wave ship_* are untouched. M6 generations are not in this wave.)
# =============================================================================

class StarSetDrift(RuntimeError):
    """Star-flag consistency gate: the rebuilt star_set differs from the frozen artifact in identification flags / arrival years → HALT.

    All three shipped tables are bound to the frozen star set; a rebuild drift = the engine/upstream changed, and the list is never silently swapped — the difference report
    goes to _reports/star_flag_mismatch.json for a human to decide (identification-layer decisions are made by a human, never self-learned).
    """


# Field-by-field definition of the consistency gate (percentile is explicitly not included — the naive rank method means values may differ):
#   both flags + age_eligible = gate (a); arrival = the content of the stars_set_hash idempotency key;
#   is_foreign_poach = the defining key of the shipping set; dept = the department an event belongs to.
_CONSISTENCY_FIELDS = ("is_star_1pct", "is_star_5pct", "age_eligible",
                       "arrival", "is_foreign_poach", "dept")


# OpenAlex disambiguation review list (**register only, do not fix**): two canonical mis-attributions
# confirmed in the first events-route run — a raw string was wrongly merged by OpenAlex disambiguation into Monash (I56590836), making the detect
# route produce a false arrival year. The authority for arrival years is the human-verified roster (released under the human-verification rule above); these two
# belong to the "OpenAlex same-name / institution disambiguation review" (person_map vs raw author_id issue), and this pipeline does not change the data.
OPENALEX_DISAMBIG_REVIEW: tuple = (
    {"author_id": "A5017376589", "display_name": "Yves Zenou",
     "raw_affil": "Centre for Economic Policy Research (CEPR)",
     "wrong_canonical": "I56590836 (Monash University)",
     "years_observed": [2005],
     "symptom": "events detect 路线判 2005 假 Monash 到任 (真到任 2016, 名册人核)",
     "evidence": "10b _reports/arrival_mismatch_report.json + 证据表 §一 (三源互证 2016-01)"},
    {"author_id": "A5044501609", "display_name": "A5044501609",
     "raw_affil": "CESifo",
     "wrong_canonical": "I56590836 (Monash University)",
     "years_observed": [2017, 2019],
     "symptom": "events detect 路线判 2017 假 Monash 到任 (真到任 2023, econews 官宣人核)",
     "evidence": "10b _reports/arrival_mismatch_report.json + 证据表 §一 (joined January 2023)"},
)


def star_flag_consistency_diff(rebuilt_rows, frozen_rows) -> list[dict]:
    """Pure decision of the star-flag consistency gate: compare rebuilt vs frozen person by person and field by field, return the difference rows (empty = pass).

    The member sets must be equal (extra/missing people = field="membership"); for those present, each field
    (_CONSISTENCY_FIELDS) must be equal (None is compared too — thin-sample None and False are different truths).
    percentile is not compared (it may differ; the distribution of differences is reported separately). Only differences are reported; it never picks a side.
    """
    rb = {r["author_id"]: r for r in rebuilt_rows}
    fz = {r["author_id"]: r for r in frozen_rows}
    diff: list[dict] = []
    for aid in sorted(set(fz) - set(rb)):
        diff.append({"author_id": aid, "field": "membership",
                     "frozen": "present", "rebuilt": "missing"})
    for aid in sorted(set(rb) - set(fz)):
        diff.append({"author_id": aid, "field": "membership",
                     "frozen": "missing", "rebuilt": "present"})
    for aid in sorted(set(rb) & set(fz)):
        for f in _CONSISTENCY_FIELDS:
            if rb[aid].get(f) != fz[aid].get(f):
                diff.append({"author_id": aid, "field": f,
                             "frozen": fz[aid].get(f), "rebuilt": rb[aid].get(f)})
    return diff


def percentile_diff_rows(rebuilt_rows, frozen_rows) -> dict:
    """Distribution of old vs new percentile differences (a by-product of gate (a): the new formula is in use, differences are allowed but must leave a trace).

    Returns {"rows": [{author_id, frozen_pct, rebuilt_pct, abs_diff}...],
          "summary": {n_compared, n_changed, max_abs_diff, mean_abs_diff, n_none_pairs}}.
    Both sides None (candidates not in the pool) → n_none_pairs, not in the numeric distribution; one-sided None belongs to the consistency gate
    (the flags must already differ), and is treated as None here without forcing a computation.
    """
    fz = {r["author_id"]: r.get("percentile") for r in frozen_rows}
    rows, diffs, n_none = [], [], 0
    for r in sorted(rebuilt_rows, key=lambda x: x["author_id"]):
        aid = r["author_id"]
        if aid not in fz:
            continue
        old, new = fz[aid], r.get("percentile")
        if old is None and new is None:
            n_none += 1
            continue
        if old is None or new is None:
            n_none += 1
            rows.append({"author_id": aid, "frozen_pct": old, "rebuilt_pct": new,
                         "abs_diff": None})
            continue
        d = abs(float(new) - float(old))
        diffs.append(d)
        rows.append({"author_id": aid, "frozen_pct": float(old),
                     "rebuilt_pct": float(new), "abs_diff": d})
    summary = {
        "n_compared": len(diffs),
        "n_changed": sum(1 for d in diffs if d > 1e-12),
        "max_abs_diff": max(diffs) if diffs else 0.0,
        "mean_abs_diff": (sum(diffs) / len(diffs)) if diffs else 0.0,
        "n_none_pairs": n_none,
    }
    return {"rows": rows, "summary": summary}


def _tree_fingerprint(path) -> str:
    """Content fingerprint for the resume anchor: file → sha256; directory → files (parquet/json) sorted by relative path,
    rel+sha aggregated into one sha256 (deterministic, layout-independent); absent → "ABSENT"."""
    import hashlib
    from common.derived_table import _sha256_file

    p = Path(path)
    if p.is_file():
        return _sha256_file(p)
    if not p.exists():
        return "ABSENT"
    h = hashlib.sha256()
    for f in sorted(x for x in p.rglob("*")
                    if x.is_file() and x.suffix in (".parquet", ".json")):
        h.update(f.relative_to(p).as_posix().encode("utf-8"))
        h.update(b"\t")
        h.update(_sha256_file(f).encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


# Required inputs consumed by run_u4_full (work_first_pub in U4_INPUTS belongs to the M6 generation step and is not part of this run).
_FULL_RUN_REQUIRED = ("works", "authorship_edges", "fwci_baseline_pop", "institutions",
                      "person_map", "panel", "affil_timeline",
                      "roster_monash", "roster_unsw")

_WAYBACK_SUB = "u0p5_hist_raw/wayback_full_2026-07-06/parsed/wayback_staff_lines.parquet"


def _resume_fingerprint(derived_root, *, frozen_hash, pv, wayback_sub) -> dict:
    """Global input fingerprint (resume anchor): content hash of the small tables + U1 reproducibility-record merkle (the large tables works/edges/
    institutions are not rehashed — their provenance root is the existing merkle in the U1 run_manifest,
    manifest rule: compare against stored values, never recompute) + configuration fingerprint + frozen star-set fingerprint."""
    from common._redlines import RED

    root = Path(derived_root)
    upstream = {
        "person_map": _tree_fingerprint(root / U4_INPUTS["person_map"]),
        "panel": _tree_fingerprint(root / U4_INPUTS["panel"]),
        "affil_timeline": _tree_fingerprint(root / U4_INPUTS["affil_timeline"]),
        "roster_monash": _tree_fingerprint(root / U4_INPUTS["roster_monash"]),
        "roster_unsw": _tree_fingerprint(root / U4_INPUTS["roster_unsw"]),
        "fwci_baseline_pop": _tree_fingerprint(root / U4_INPUTS["fwci_baseline_pop"]),
        "wayback_staff_lines": _tree_fingerprint(root / wayback_sub),
    }
    return {"rule_version": RED.get("rule_version", ""),
            "config_sha": pv["config_sha"],
            "source_snapshot_merkle": pv["source_snapshot_merkle"],
            "frozen_stars_set_hash": frozen_hash,
            "upstream": upstream}


# The registry (table A, dept_key + subfield_excluded) that the run_u4_full discipline gate reads by default.
#   On the real disk it is registry v3 (11 schools); the test universe writes its own small file with the same schema.
REGISTRY_SUB_DEFAULT = ("u0p5_roster/registry_v3_2026-07-12/"
                        "econ_dept_registry_11schools.parquet")


def run_u4_full(derived_root, out_root, *, frozen_dir,
                edges_sub="u1_edges_full_2026-07-05",
                wayback_sub=_WAYBACK_SUB, star_change_mode="halt",
                registry_sub=REGISTRY_SUB_DEFAULT,
                overmerge_queue_sub=None) -> dict:
    """U4 shipping orchestration: preflight → hand-review decisions (fail-loud) → fwci_baseline → star_set rebuild
    (gate) → paper_contrib (isc takes the **rebuilt** rows) → events (arrival-year consistency hard gate).

    Re-ordered, with two modes (needed for reruns after evidence-based corrections):
      - Stage order: star_set comes before paper_contrib — the isc backfill must take the star set **rebuilt in this run**
        (in halt mode gate a guarantees rebuilt ≡ frozen, so the semantics are exactly equivalent to the old order; in diff mode the new list is the truth).
      - star_change_mode="halt" (default, original behaviour): rebuilt ≠ frozen → StarSetDrift HALT.
      - star_change_mode="diff" (rerun after arrival years / eligibility were corrected by evidence, **the list may change**):
        rebuilt ≠ frozen → the differences go to _reports/star_set_diff.json (person by person, field by field: in/out/flag change/year change)
        and shipping continues; the stars_set_hash idempotency key is no longer forced equal (both values are recorded);
        the Zenou anchor is not relaxed — Zenou appearing in the differences = HALT at once (if Zenou moves, stop);
        if the events consistency gate fails, the events table is still not written and a difference report is written, but the whole run does not raise
        (status SHIPPED_EVENTS_HALTED; the report goes to a human).
      - The hand-review decision file (m7a_star.adjudications) is a required input:
        file missing → HALT; roster version guard verify_roster_matches_fixes (the roster must really carry the corrected years);
        the A5018638208 part-time candidate exclusion + the A5086095616 poach=False override are injected into build_star_set.

    Production wiring of the discipline gate, person folding and human-review list:
      - registry_sub (default registry v3): reads the table A registry → the build_star_set discipline gate
        **excludes by default** candidates of excluded disciplines; the excluded go to _reports/discipline_excluded.json
        (auditable and reversible). File absent → ValueError fail-loud (a dead config must never silently recur).
      - overmerge_queue_sub (injectable, default None = empty set): the suspected_overmerge human-review queue csv
        (produced by the person_map wave) → flagged clusters are not folded when folding persons.
      - Fold diagnostics _reports/stock_fold_report.csv (with the cause column) + human-review list
        _reports/human_adjudication_queue.csv (2. affiliation flag <0.05; 3. academic age ≤1 sanity gate;
        **flags never drop anyone**; dropping or keeping is a human decision).

    On-disk layout (parent-directory scheme): <out_root>/{fwci_baseline, paper_contrib, paper_contrib_diag,
    star_set, events}/ + _reports/ + _tally/ + _ledger/ + _manifest/.
    Accounting: each stage runs reconcile_fetch on a six-key tally (in-memory counts vs read back from disk) + Ledger events.
    Resume anchor: if the global input fingerprint (rule_version/config_sha/U1 merkle/frozen fingerprint/small-table content hash/
    decision-file sha) is unchanged and the real artifacts are present with matching sha → skip the stage; if any changed → rebuild.
    HALT semantics: gate fails → intermediate files already written are kept + _reports difference report + run_summary records the status
    (never repair the data, never let the code pick a route).
    """
    import datetime
    import hashlib
    import json
    from common.atomic_io import atomic_write_bytes
    from common.ledger import Ledger
    from common.reconcile import reconcile_fetch
    from m7a_star.adjudications import (load_star_adjudications,
                                        verify_roster_matches_fixes)

    if star_change_mode not in ("halt", "diff"):
        raise ValueError(
            f"run_u4_full: star_change_mode={star_change_mode!r} must be 'halt' | 'diff'")

    root = Path(derived_root)
    out = Path(out_root)
    man_dir = out / "_manifest"
    reports_dir = out / "_reports"
    summary: dict = {"status": "RUNNING", "derived_root": str(root),
                     "out_root": str(out), "frozen_dir": str(frozen_dir),
                     "star_change_mode": star_change_mode}

    def _write_summary():
        man_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(man_dir / "run_summary.json", json.dumps(
            summary, ensure_ascii=False, sort_keys=True, indent=1,
            default=str).encode("utf-8"))

    # ---- Environment check before the run (first gate) ----
    #   pyarrow pin / OpenAlex key / redlines SHA / rapidfuzz — if any fails →
    #   SystemExit(ENVIRONMENT_GATE_FAIL=30), nothing is written (preflight_result.json is the gate's
    #   own audit record, always written following the U0 preflight pattern; it does not count as a data artifact).
    from common.preflight import preflight_env_check
    man_dir.mkdir(parents=True, exist_ok=True)
    _pf_rc = preflight_env_check(result_path=man_dir / "preflight_result.json")
    if _pf_rc != 0:
        raise SystemExit(_pf_rc)

    # ---- preflight: inputs complete (a missing table is named and HALTs; no artifact is written) ----
    rep = preflight(root)
    missing = [t for t in _FULL_RUN_REQUIRED if not rep[t]["present"]]
    if missing:
        raise ValueError(
            f"run_u4_full preflight: required input tables missing {missing} — HALT, no output written")
    summary["preflight_rows"] = {t: rep[t]["n_rows"] for t in _FULL_RUN_REQUIRED}

    # ---- Registry table A (the real consumer of the discipline gate), read fail-loud ----
    import csv as _csv
    import pyarrow.parquet as _pq_reg
    _reg_path = root / registry_sub
    if not _reg_path.is_file():
        raise ValueError(
            f"run_u4_full: registry table A not found at {_reg_path} — with no input the discipline gate would be a dead configuration "
            "— fail-loud; pass the right registry_sub or supply the file")
    registry_rows = _pq_reg.read_table(str(_reg_path)).to_pylist()
    # ---- suspected_overmerge human-review queue (injectable; flagged clusters are not folded) ----
    overmerge_pids: set = set()
    if overmerge_queue_sub is not None:
        _q_path = root / overmerge_queue_sub
        if not _q_path.is_file():
            raise ValueError(
                f"run_u4_full: overmerge queue not found at {_q_path} — injected explicitly but the file is missing; fail-loud")
        with open(_q_path, newline="", encoding="utf-8") as _fh:
            overmerge_pids = {row["person_id"] for row in _csv.DictReader(_fh)}
    summary["registry_sub"] = str(registry_sub)
    summary["n_overmerge_queue_person_ids"] = len(overmerge_pids)

    # ---- Hand-review decisions (fail-loud, before any write) + roster version guard ----
    adj = load_star_adjudications(root)                 # missing file / missing authorization → ValueError
    import pyarrow.parquet as _pq_adj
    _roster_rows_check: list[dict] = []
    for _rf in ROSTER_FILES:
        _roster_rows_check += _pq_adj.read_table(str(root / _rf)).to_pylist()
    verify_roster_matches_fixes(_roster_rows_check, adj["year_fixes"])
    summary["adjudications"] = {
        "path": adj["path"], "sha256": adj["sha256"],
        "n_exclude_candidates": len(adj["exclude_candidates"]),
        "n_poach_overrides": len(adj["poach_overrides"]),
        "n_year_fixes_verified_in_roster": len(adj["year_fixes"]),
        "n_signal_discards": sum(len(v) for v in adj["signal_discards"].values()),
        "n_arrival_verifications": len(adj["arrival_verifications"]),
    }

    # ---- OpenAlex disambiguation review list: register only, do not fix ----
    reports_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(reports_dir / "openalex_disambig_review.json", json.dumps(
        {"register_only": True,
         "purpose": "canonical 错挂登记 — 归 OpenAlex 同名/机构消歧大审查, 本管线不改数据",
         "entries": list(OPENALEX_DISAMBIG_REVIEW)},
        ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8"))

    # ---- provenance (fail-loud) + frozen-artifact fingerprint binding check (if it fails no artifact is written) ----
    pv = resolve_provenance(root, edges_sub=edges_sub)
    frozen = load_frozen_star_rows(frozen_dir)          # FrozenStarSetMismatch → HALT
    summary["frozen_stars_set_hash"] = frozen["stars_set_hash"]
    summary["provenance"] = pv

    # ---- resume anchor (includes the decision-file sha — if the decisions change, old artifacts are never reused) ----
    fingerprint = _resume_fingerprint(root, frozen_hash=frozen["stars_set_hash"],
                                      pv=pv, wayback_sub=wayback_sub)
    fingerprint["adjudications_sha"] = adj["sha256"]
    # The registry / overmerge queue go into the resume anchor (if they change, the old star set is never reused).
    fingerprint["registry_sha"] = _tree_fingerprint(_reg_path)
    fingerprint["overmerge_queue_sha"] = (
        _tree_fingerprint(root / overmerge_queue_sub)
        if overmerge_queue_sub is not None else "NONE")
    fp_hash = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
    summary["inputs_fingerprint_sha"] = fp_hash
    anchors_path = man_dir / "resume_anchors.json"
    anchors: dict = (json.loads(anchors_path.read_text("utf-8"))
                     if anchors_path.is_file() else {})

    ledger = Ledger(_ensure_dir(out / "_ledger") / "events.jsonl")

    def _now():
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    def _log(stage, status, reason):
        ledger.append(op_id=f"u4_ship:{stage}", status=status, shard_id="monash+unsw",
                      idempotency_key=f"{stage}:{fp_hash}", ts=_now(), reason=reason)

    def _stage_resumable(stage, artifact_rels):
        a = anchors.get(stage)
        if not a or a.get("inputs_sha") != fp_hash:
            return False
        for rel, sha in a.get("artifacts", {}).items():
            if _tree_fingerprint(out / rel) != sha:
                return False
        return set(a.get("artifacts", {})) == set(artifact_rels)

    def _record_stage(stage, artifact_rels, result_summary):
        anchors[stage] = {
            "inputs_sha": fp_hash,
            "artifacts": {rel: _tree_fingerprint(out / rel) for rel in artifact_rels},
            "result_summary": result_summary,
        }
        man_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(anchors_path, json.dumps(
            anchors, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8"))

    def _tally(stage, *, expected, kept, failed=0, skipped=0, artifact_rels=()):
        present = {rel for rel in artifact_rels if (out / rel).exists()}
        return reconcile_fetch(
            expected=expected, kept=kept, failed=failed, skipped=skipped,
            op_ids_expected=set(artifact_rels), op_ids_seen=present,
            stage=f"u4_ship:{stage}", tally_path=out / "_tally" / f"{stage}.json")

    def _disk_rows(table_dir_or_file) -> int:
        import pyarrow.parquet as pq
        p = Path(table_dir_or_file)
        files = [p] if p.is_file() else sorted(p.rglob("*.parquet"))
        return sum(pq.ParquetFile(str(f)).metadata.num_rows for f in files)

    # ================= stage 1: fwci_baseline =================
    stage = "fwci_baseline"
    arts = ("fwci_baseline",)
    if _stage_resumable(stage, arts):
        summary[stage] = {"resume": "skipped_resume",
                          **anchors[stage].get("result_summary", {})}
        _log(stage, "skip", "resume_anchor_match")
    else:
        res = ship_fwci_baseline(root, out, edges_sub=edges_sub)
        kept = _disk_rows(out / "fwci_baseline" / "data.parquet")
        _tally(stage, expected=res["n_rows"], kept=kept, artifact_rels=arts)
        stage_sum = {"n_rows": res["n_rows"], "n_rows_disk": kept}
        summary[stage] = {"resume": "rebuilt", **stage_sum}
        _record_stage(stage, arts, stage_sum)
        _log(stage, "ok", "fresh_build")
    _write_summary()

    # ============ stage 2: star_set rebuild + three gates (re-ordered: before paper_contrib,
    #              isc must take the rows rebuilt in this run; in halt mode gate a guarantees equivalence with the old order) ============
    stage = "star_set"
    arts = ("star_set",)
    if _stage_resumable(stage, arts):
        summary[stage] = {"resume": "skipped_resume",
                          **anchors[stage].get("result_summary", {})}
        summary["percentile_diff"] = summary[stage].get("percentile_diff")
        if star_change_mode == "diff":
            # diff mode: frozen ≠ rebuilt; the truth under the resume anchor = the star set already on disk (sha verified)
            import pyarrow.parquet as _pq_ss
            rebuilt_rows = _pq_ss.read_table(
                str(out / "star_set" / "star_set.parquet")).to_pylist()
        else:
            rebuilt_rows = frozen["rows"]    # Anchor for a passed gate: frozen rows == rebuilt rows (person by person)
        _log(stage, "skip", "resume_anchor_match")
    else:
        result = build_star_set(root, edges_sub=edges_sub,
                                exclude_candidates=adj["exclude_candidates"],
                                poach_overrides=adj["poach_overrides"],
                                signal_discards=adj["signal_discards"],
                                work_pollution_discards=adj["work_pollution_discards"],
                                registry_rows=registry_rows,
                                overmerge_person_ids=overmerge_pids)
        # Candidates excluded by default by the discipline gate go into an auditable report (reversible: discipline_gate_mode='flag').
        reports_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(reports_dir / "discipline_excluded.json", json.dumps(
            {"table": "star_set", "gate": "subfield_excluded (签1 2026-07-16, 默认排除)",
             "n_excluded": len(result["discipline_excluded"]),
             "excluded": result["discipline_excluded"],
             "flags_all": result["discipline_flags"]},
            ensure_ascii=False, sort_keys=True, indent=1, default=str).encode("utf-8"))
        # Person-fold diagnostic report (cause column: truncation_empty / not_in_person_map).
        import io as _io

        def _csv_bytes(rows, cols):
            buf = _io.StringIO()
            w = _csv.DictWriter(buf, fieldnames=list(cols))
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k) for k in cols})
            return buf.getvalue().encode("utf-8")

        _sfr = result["stock_fold_report"]
        if _sfr:
            atomic_write_bytes(reports_dir / "stock_fold_report.csv",
                               _csv_bytes(_sfr, _sfr[0].keys()))
        # Human-review list (affiliation flag <0.05 + academic age ≤1; flags never drop anyone, dropping or keeping is a human decision).
        from m7a_star.nominal_gate import (build_nominal_affil_flags,
                                           human_adjudication_queue)
        nominal_rows = build_nominal_affil_flags(
            root, [{"author_id": s["author_id"], "name": s["name"], "dept": s["dept"]}
                   for s in result["stars"]],
            edges_sub=edges_sub, dept_inst=DEPT_INST)
        adjq = human_adjudication_queue(result["sanity_age_flags"], nominal_rows)
        atomic_write_bytes(
            reports_dir / "human_adjudication_queue.csv",
            _csv_bytes(adjq, ("author_id", "name", "dept", "source",
                              "detail", "disposition")))
        # Diagnostic accounting of signal discards (rows matched per person per entry; written even for an empty map — "nothing discarded" is also a record).
        atomic_write_bytes(reports_dir / "signal_discards_applied.json", json.dumps(
            {"table": "star_set", "adjudications_sha": adj["sha256"],
             "n_authors": len(result["signal_discards_applied"]),
             "applied": result["signal_discards_applied"]},
            ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8"))
        diff = star_flag_consistency_diff(result["stars"], frozen["rows"])
        # Zenou anchor (identical in both modes): Zenou appearing in the differences = stop at once (if Zenou moves, stop).
        zenou_diff = [d for d in diff if d["author_id"] == "A5017376589"]
        if diff and (star_change_mode == "halt" or zenou_diff):
            reports_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(reports_dir / "star_flag_mismatch.json", json.dumps(
                {"table": "star_set", "gate": "star_flag_consistency (重建 vs 冻结)",
                 "n_mismatch": len(diff), "fields": list(_CONSISTENCY_FIELDS),
                 "diff": diff}, ensure_ascii=False, sort_keys=True,
                indent=1, default=str).encode("utf-8"))
            summary["status"] = "HALT_STAR_FLAG_DRIFT"
            summary[stage] = {"resume": "halted", "n_mismatch": len(diff)}
            _write_summary()
            if zenou_diff:
                raise StarSetDrift(
                    f"run_u4_full Yves Zenou anchor: Yves Zenou differs from the baseline {zenou_diff} — the record moved, "
                    f"stop immediately (even in diff mode); report = "
                    f"{reports_dir / 'star_flag_mismatch.json'}")
            raise StarSetDrift(
                f"run_u4_full star-flag consistency gate: {len(diff)} places where rebuilt ≠ frozen — HALT, difference report = "
                f"{reports_dir / 'star_flag_mismatch.json'}; a disagreement in the identification layer is for a human to resolve")
        if diff:
            # diff mode (the list may change): differences are an expected output; write a structured report and continue shipping.
            reports_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(reports_dir / "star_set_diff.json", json.dumps(
                {"table": "star_set",
                 "gate": "star_set_diff (重建 vs 基线; diff 模式 — 名单允许变)",
                 "n_mismatch": len(diff), "fields": list(_CONSISTENCY_FIELDS),
                 "diff": diff}, ensure_ascii=False, sort_keys=True,
                indent=1, default=str).encode("utf-8"))
        # Old vs new percentile difference distribution (allowed to differ, written to a report)
        pdiff = percentile_diff_rows(result["stars"], frozen["rows"])
        reports_dir.mkdir(parents=True, exist_ok=True)
        csv_lines = ["author_id,frozen_pct,rebuilt_pct,abs_diff"] + [
            f"{r['author_id']},{r['frozen_pct']},{r['rebuilt_pct']},{r['abs_diff']}"
            for r in pdiff["rows"]]
        atomic_write_bytes(reports_dir / "percentile_diff.csv",
                           ("\n".join(csv_lines) + "\n").encode("utf-8"))
        # Freeze (the Zenou gold-standard gate is inside freeze_star_set; if it fails → GoldenFailure, nothing is written)
        fres = freeze_star_set(result, out / "star_set", derived_root=root,
                               edges_sub=edges_sub)
        # Idempotency key: in halt mode it must == the frozen artifact (gate a passed ⇒ mathematically equal; a defensive tripwire);
        # in diff mode the list may change → both values are recorded, not forced equal.
        hash_matches = fres["stars_set_hash"] == frozen["stars_set_hash"]
        if star_change_mode == "halt" and not hash_matches:
            summary["status"] = "HALT_STARS_SET_HASH_DRIFT"
            _write_summary()
            raise StarSetDrift(
                f"run_u4_full: stars_set_hash idempotency key drifted (rebuilt {fres['stars_set_hash']} "
                f"≠ frozen {frozen['stars_set_hash']}) — HALT")
        kept = _disk_rows(out / "star_set" / "star_set.parquet")
        _tally(stage, expected=len(result["stars"]), kept=kept, artifact_rels=arts)
        stage_sum = {
            "n_candidates": fres["n_candidates"], "n_rows_disk": kept,
            "n_foreign_poach_stars": fres["n_foreign_poach_stars"],
            "n_dropped_null_pub_year": fres["n_dropped_null_pub_year"],
            "stars_set_hash": fres["stars_set_hash"],
            "stars_set_hash_matches_frozen": hash_matches,
            "n_star_set_diff": len(diff),
            "excluded_candidates": sorted(result["excluded_candidates"]),
            "poach_overridden": result["poach_overridden"],
            "signal_discards_applied": result["signal_discards_applied"],
            "no_arrival": sorted(result["no_arrival"]),
            "percentile_diff": pdiff["summary"],
            # Accounting of the three gates (discipline / person fold / human-review list)
            "n_discipline_excluded": len(result["discipline_excluded"]),
            "discipline_excluded_ids": sorted(
                r["author_id"] for r in result["discipline_excluded"]),
            "n_stock_fold_null": sum(
                1 for r in result["stock_fold_report"]
                if r["null_stock_reason"] is not None),
            "n_human_adjudication_rows": len(adjq),
        }
        summary[stage] = {"resume": "rebuilt", **stage_sum}
        summary["percentile_diff"] = pdiff["summary"]
        rebuilt_rows = result["stars"]
        _record_stage(stage, arts, stage_sum)
        _log(stage, "ok", "fresh_build")
    _write_summary()

    # ================= stage 3: paper_contrib (isc takes the rows rebuilt in this run) =================
    stage = "paper_contrib"
    arts = ("paper_contrib", "paper_contrib_diag")
    if _stage_resumable(stage, arts):
        summary[stage] = {"resume": "skipped_resume",
                          **anchors[stage].get("result_summary", {})}
        _log(stage, "skip", "resume_anchor_match")
    else:
        res = ship_paper_contrib(root, out, star_rows=rebuilt_rows,
                                 edges_sub=edges_sub)
        kept = _disk_rows(out / "paper_contrib")
        # PK-uniqueness read-back check (gate e; the write layer already dedups, this is an on-disk reconciliation with a receipt)
        import duckdb
        con = duckdb.connect()
        try:
            n_all, n_pk = con.execute(
                f"SELECT COUNT(*), COUNT(DISTINCT (work_id, incumbent_person_id, "
                f"person_id)) FROM read_parquet("
                f"'{(out / 'paper_contrib').as_posix()}/**/*.parquet')").fetchone()
        finally:
            con.close()
        if n_all != n_pk:
            raise ValueError(
                f"run_u4_full: paper_contrib PK on disk is not unique ({n_all} rows / {n_pk} PKs) "
                "— was the write-layer guard bypassed? fail-loud")
        _tally(stage, expected=res["n_rows"] + res["n_dedup_dropped"], kept=kept,
               skipped=res["n_dedup_dropped"], artifact_rels=arts)
        stage_sum = {
            "n_rows": res["n_rows"], "n_rows_disk": kept, "pk_unique": True,
            "n_dedup_dropped": res["n_dedup_dropped"], "n_works": res["n_works"],
            "n_star_persons": res["n_star_persons"],
            "n_unmapped_star_authors": res["n_unmapped_star_authors"],
            "inferred_ratio": res["inferred_ratio"], "na_counts": res["na_counts"],
        }
        summary[stage] = {"resume": "rebuilt", **stage_sum}
        _record_stage(stage, arts, stage_sum)
        _log(stage, "ok", "fresh_build")
    _write_summary()

    # ================= stage 4: events (three real-data assembly parts + hard gate) =================
    stage = "events"
    arts = ("events",)
    if _stage_resumable(stage, arts):
        summary[stage] = {"resume": "skipped_resume",
                          **anchors[stage].get("result_summary", {})}
        _log(stage, "skip", "resume_anchor_match")
    else:
        from m7a_star.adjudications import human_verified_arrival_basis
        from m7a_star.events_pipeline import ArrivalMismatch, ship_set_ids
        from m7a_star.real_inputs import (load_star_evidence, load_star_modal_flags,
                                          load_star_truth_evidence)

        ship_ids = sorted(ship_set_ids(rebuilt_rows))
        by_id = {s["author_id"]: s for s in rebuilt_rows}
        ev = load_star_evidence(root, ship_ids, edges_sub=edges_sub)
        # The human-verified years in the adjudication arrival_verifications with source_kind=orcid_employment
        # go into the truth file through the existing ORCID channel of evidence_assembly (a year enters the file only when passed explicitly).
        orcid_by_star = {aid: v["year"]
                         for aid, v in adj["arrival_verifications"].items()
                         if v.get("source_kind") == "orcid_employment"}
        truth = load_star_truth_evidence(root, ship_ids, wayback_sub=wayback_sub,
                                         orcid_by_star=orcid_by_star)
        modal = load_star_modal_flags(
            root, {sid: (by_id[sid]["arrival"], by_id[sid]["dept"]) for sid in ship_ids},
            dept_inst_map=DEPT_INST)
        # Human-verified criterion map (roster hv rows + adjudication arrival_verifications,
        # the year must == the frozen arrival year — the criterion pure function is in adjudications).
        hv_basis = human_verified_arrival_basis(
            _roster_rows_check, adj["arrival_verifications"], rebuilt_rows)
        reports_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(reports_dir / "wayback_match_report.json", json.dumps(
            truth["wayback_report"], ensure_ascii=False, sort_keys=True,
            indent=1).encode("utf-8"))
        summary["wayback_report"] = truth["wayback_report"]
        events_halted = False
        try:
            res = ship_events(root, out, frozen_star_rows=rebuilt_rows,
                              evidence_by_star=ev["evidence_by_star"],
                              truth_evidence_by_star=truth["truth_evidence_by_star"],
                              modal_inst_year_by_star=modal, edges_sub=edges_sub,
                              hv_arrival_basis=hv_basis)
        except ArrivalMismatch:
            # The events table is still not written + the difference report is written (HALT discipline unchanged).
            summary[stage] = {
                "resume": "halted", "n_ship_stars": len(ship_ids),
                "mismatch_report": str(reports_dir / "arrival_mismatch_report.json")}
            if star_change_mode == "halt":
                summary["status"] = "HALT_EVENTS_ARRIVAL_MISMATCH"
                _write_summary()
                raise
            # diff mode: the whole run does not blow up — the first three tables are shipped, the events disagreement report goes to a human.
            events_halted = True
            summary["status"] = "SHIPPED_EVENTS_HALTED"
            _write_summary()
            # The ledger status enum has no "halt" → permanent (the events table is definitely not produced in this run; the report goes to a human).
            _log(stage, "permanent", "arrival_mismatch_report")
        if not events_halted:
            kept = _disk_rows(out / "events" / "data.parquet")
            _tally(stage, expected=len(ship_ids), kept=kept, artifact_rels=arts)
            stage_sum = {
                "n_events": res["n_events"], "n_rows_disk": kept,
                "n_ship_stars": len(ship_ids),
                "n_polluted_dropped": res["n_polluted_dropped"],
                "p01_event_ids": res["p01_event_ids"],
                "stars_set_hash": res["stars_set_hash"],
                "n_explained_mismatch": res["n_explained_mismatch"],
                "explained_ids": res["explained_ids"],
            }
            summary[stage] = {"resume": "rebuilt", **stage_sum}
            _record_stage(stage, arts, stage_sum)
            _log(stage, "ok", "fresh_build")

    if summary["status"] == "RUNNING":
        summary["status"] = "SHIPPED"
    _write_summary()
    return {"status": summary["status"],
            "fwci_baseline": summary["fwci_baseline"],
            "paper_contrib": summary["paper_contrib"],
            "star_set": summary["star_set"],
            "events": summary["events"],
            "percentile_diff": summary.get("percentile_diff"),
            "wayback_report": summary.get("wayback_report"),
            "provenance": pv,
            "inputs_fingerprint_sha": fp_hash}


def _ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p
