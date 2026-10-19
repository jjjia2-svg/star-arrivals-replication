"""m4_dose/run_dose.py — M4 orchestration: candidate pairs -> main/secondary dose -> PAIRWISE_DOSE written to disk.

Flow (read frozen handles -> call pure functions -> atomic write + freeze + reconcile):
  1. Injected parameters are read explicitly key by key (a missing key raises KeyError; no default magic numbers).
  2. The two RED dose floors are read via require() (a null value -> RedlineUnsigned, fail loud —
     redlines.yaml currently holds null, so a value must be set before a real-data run; M4 only imports
     and passes it, and never assigns it inside m4_dose/).
  3. Idempotency/resume (#30): idempotency_key = stage|config_sha|stars_set_hash|
     merkle|rule_version; if the ledger shows ok and the dataset is valid -> skip, no recomputation.
  4. Candidate pairs: degree-1 = candidate_pairs (coauthor_pre_arrival frozen at t-1, #8);
     degree-2 = degree2_closure (persistent .db, both bridge edges frozen, #5); degree-1 takes precedence
     in de-duplication H2 (the deg1 set goes into exclude_pids). t_minus_1 is read directly from events throughout (#1).
  5. Per pair: main dose = coupling.pair_coupling (delegates to identity, #14);
     **for a degree-2 unfrozen channel (either bridge edge > t-1) the main dose is forced to 0.0 and never quietly computed**
     (#5, #7b); the secondary doses topic/embed fill only their secondary columns and never enter coupling_share
     (#16); coverage diagnostics; frozen_at_year == events.t_minus_1 (#24).
  6. MNAR (caveat#1, #18b): if the refs missing rate over the works involved > mnar_missing_threshold
     -> diag is flagged mnar_robustness_required=true + WARN (not a silent log line).
  7. Write: PK uniqueness guard (#27b) -> canonical-sort by the full PK -> deterministic parquet
     (fixed U1 writer parameters) -> two-phase COMMIT (write_dataset_commit, all-or-nothing,
     #29) -> two passes byte-identical (#27).
  8. Reconcile: reconcile_fetch six-key tally (tolerance = reconcile.diff_tolerance=0,
     unbalanced -> SystemExit(15)); diagnostics go to the diag.json sidecar, not mixed into TALLY (as in #47).
  9. ledger.append (.append only, .emit is banned — DRIFT-L1, #28).

Products (all under tmp / the passed-in out_root; this unit never fixes an SSD path itself):
  out_root/_frozen/{dose.parquet, work_embeddings.parquet, manifest_header.json,
  COMMIT} + posting_by_year/ (auxiliary) + tally.json + diag.json.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import warnings
from datetime import datetime, timezone

from common._redlines import require
from common.atomic_io import atomic_write_bytes
from common.ledger import Ledger
from common.manifest import dataset_is_valid, write_dataset_commit
from common.reconcile import reconcile_fetch
from common.schema import PAIRWISE_DOSE
from identity import dose as identity_dose
from m1_ingest._writer_util import write_rows_parquet

from . import (
    candidate_pairs,
    coupling,
    cutoff,
    degree2_closure,
    embed,
    io_load,
    posting_index,
    topic_vec,
)

_PK: tuple = ("incumbent_person_id", "star_person_id", "event_id", "degree")
_UNIT_EPS = 1e-9  # float residual clamp (pure numerical hygiene, not a specification choice; anything beyond 1e-9 still raises)


def _need(config: dict, key: str):
    """Read an injected parameter explicitly: a missing key -> KeyError (an unreadable key raises, no default magic number)."""
    if key not in config:
        raise KeyError(
            f"config lacks {key!r} — U5 injected parameters must be given explicitly"
        )
    return config[key]


def _assert_pk_unique(rows) -> None:
    """#27b: no duplicate rows on PK=(incumbent, star, event_id, degree) — the last guard for H2 de-duplication."""
    seen = set()
    for r in rows:
        k = tuple(r[c] for c in _PK)
        if k in seen:
            raise ValueError(f"PAIRWISE_DOSE duplicate PK: {k} — degree-1-first de-duplication was broken")
        seen.add(k)


def _unit_interval(value: float, *, name: str, who) -> float:
    """#26: dose/coverage in [0,1]; only float residuals within 1e-9 are clamped, anything out of range raises."""
    v = float(value)
    if -_UNIT_EPS < v < 0.0:
        return 0.0
    if 1.0 < v < 1.0 + _UNIT_EPS:
        return 1.0
    if not (0.0 <= v <= 1.0):
        raise RuntimeError(f"{name}={v!r} is outside [0,1] (row {who}) — upstream bug, fail-loud")
    return v


def run_m4_dose(inputs, *, config: dict, out_root, ledger_path, p_level: str,
                embedder, force_recompute: bool = False,
                closure_edges=None, incumbent_pool=None) -> dict:
    """Full M4 dose orchestration (single p_level). inputs = io_load.U5Inputs handle.

    embedder: deterministic sentence-vector callable (the real model is bound further out per config embed_model_name;
    this layer only requires determinism).
    Note: embedder=None = **secondary dose embed deferred**: the embed_cos column is written as NA (None),
      diag/return records embed_deferred=true, work_text is not read; vectors are never faked and the main line is never blocked
      (the main dose coupling never touches abstracts anyway — #16 main/secondary isolation).
    closure_edges: author-level edge set used only for degree-2 closure (None = same edge set as the dose). In real runs on
      the two universities, the dose domain is the edges of incumbents + stars, while the closure domain also includes
      all edges of the intermediaries (the #9 full-edge-table rule holds in the closure domain).
    incumbent_pool: incumbent endpoint pool (None = no filtering). Real runs restrict to incumbents; deg1/deg2 use the same pool;
      Note: restricts endpoints only, never the intermediary bridges.
    Returns a report dict (skipped / n_rows / refs_missing_rate / embed_deferred / product paths).
    """
    # -- 1. injected parameters (a missing key blows up) --------------------
    cap_k = int(_need(config, "degree2_cap_k"))
    cap_per_star = int(_need(config, "degree2_incumbent_cap_per_star"))
    mnar_thr = float(_need(config, "mnar_missing_threshold"))
    db_path = _need(config, "duckdb_db_path")
    model_sha = str(_need(config, "embed_model_sha"))
    rule_version = str(_need(config, "rule_version"))
    config_sha = str(_need(config, "config_sha"))
    merkle = str(_need(config, "source_snapshot_merkle"))
    stars_hash = str(_need(config, "stars_set_hash"))

    # -- 2. RED floors (unset -> RedlineUnsigned; M4 only reads and passes them, never assigns) ----------
    idf_floor = float(require("dose", "hub_ref_idf_floor"))
    coverage_floor = float(require("dose", "coverage_floor"))

    # -- 3. idempotency / resume (#30) -------------------------------------
    out_root = pathlib.Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    ledger_path = pathlib.Path(ledger_path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    stage = f"m4_dose_{p_level}"
    idem_key = "|".join((stage, config_sha, stars_hash, merkle, rule_version))
    ledger = Ledger(ledger_path)
    if (not force_recompute) and ledger.already_done(idem_key) \
            and dataset_is_valid(out_root):
        return {"skipped": True, "idempotency_key": idem_key,
                "out_root": str(out_root)}

    # -- 4. candidate pairs (deg1 + deg2, t_minus_1 read directly from events) ---------------------
    star_pids = inputs.star_pids[p_level]  # io_load has already folded using the fixed column mapping (#4)
    io_load.assert_events_have_t_minus_1(inputs.events)  # B-EVENTS-T1
    person_edges, n_unmapped_edges = candidate_pairs.person_level_edges(
        inputs.authorship_edges, inputs.person_map
    )
    if closure_edges is None:
        closure_person_edges = person_edges          # default: closure domain = dose domain (historical behaviour)
    else:
        closure_person_edges, _n_unmapped_closure = candidate_pairs.person_level_edges(
            closure_edges, inputs.person_map
        )
    pool = set(incumbent_pool) if incumbent_pool is not None else None
    works_by_id = {w["work_id"]: w for w in inputs.works}
    refs_map = coupling.refs_by_work(inputs.refs_edges)
    ref_idf = coupling.build_ref_idf(inputs.refs_edges, idf_floor=idf_floor)

    pair_specs: list = []  # (inc, star, event_id, t_minus_1, degree, bridge_frozen)
    for ev in inputs.events:
        star = ev["star_person_id"]
        if star not in star_pids:
            continue  # build pairs only for real stars (#4)
        t1 = ev["t_minus_1"]  # read directly, never compute arrival-1 (#1)
        deg1_rows = candidate_pairs.enumerate_degree1_pairs(
            [ev], star_pids, person_edges
        )
        # H2 de-duplication: the deg1 direct-link set is the FULL set taken BEFORE pool filtering — a true deg1 person is never counted again as deg2
        deg1_incs = {r["incumbent_person_id"] for r in deg1_rows}
        if pool is not None:
            deg1_rows = [r for r in deg1_rows
                         if r["incumbent_person_id"] in pool]  # endpoint pool (endpoints only)
        for r in deg1_rows:
            # degree-1 row: no bridge edge to judge -> flag True (an empty bridge set is vacuously true; the row's frozenness
            # is guaranteed by coauthor_pre_arrival being frozen at t-1, #8)
            pair_specs.append((r["incumbent_person_id"], star,
                               ev["event_id"], t1, 1, True))
        for d in degree2_closure.close_degree2(
            db_path, closure_person_edges, star, t1,
            cap_k=cap_k, cap_per_star=cap_per_star, exclude_pids=deg1_incs,
            include_pids=pool,
        ):
            pair_specs.append((d["incumbent_person_id"], star, ev["event_id"],
                               t1, 2, d["degree2_bridge_frozen"]))

    # -- 5. works involved (per person x t1, through the single truncation entry point) ------------------
    # Real-data-scale optimisation (semantics unchanged): each t1 passes the single truncation entry point once, and the
    # result is indexed by person; each channel receives the subset "that person's rows <= t1" — passing the subset
    # through the channel's own internal truncation gives the same result (idempotent), and unit tests/spies (#7/#25)
    # still observe the truncation calls as usual.
    _frozen_idx_by_t1: dict = {}

    def _rows_of(t1: int, *persons):
        if t1 not in _frozen_idx_by_t1:
            idx: dict = {}
            for row in cutoff.filter_works_until(person_edges, t1):
                idx.setdefault(row["person_id"], []).append(row)
            _frozen_idx_by_t1[t1] = idx
        idx = _frozen_idx_by_t1[t1]
        out: list = []
        for p in persons:
            out.extend(idx.get(p, []))
        return out

    involved_works: set = set()
    for inc, star, _eid, t1, _deg, _fr in pair_specs:
        for row in _rows_of(t1, inc, star):
            involved_works.add(row["work_id"])

    # Secondary dose embedding: computed only for the works involved; missing source text -> fail loud.
    # Note: embedder=None = deferred mode: work_text is not read, no vectors are produced (never faked), embed_cos
    #   is written as NA — the secondary dose is only a robustness check and never blocks the main line (#16 main/secondary isolation).
    embed_deferred = embedder is None
    if embed_deferred:
        emb_rows = []
        emb_by_work: dict = {}
    else:
        text_by_id = {t["work_id"]: t for t in inputs.work_text}
        embed_input = []
        for wid in sorted(involved_works):
            if wid not in text_by_id:
                raise ValueError(
                    f"work_text lacks the original text of work {wid!r} — a missing input for the secondary dose is not silently skipped"
                )
            embed_input.append(text_by_id[wid])
        emb_rows = embed.embed_works(embed_input, embedder=embedder,
                                     model_sha=model_sha)
        emb_by_work = {r["work_id"]: r["embedding"] for r in emb_rows}

    # -- 6. MNAR diagnostics (caveat#1, #18b) ----------------------------------
    n_involved = len(involved_works)
    n_refs_missing = sum(
        1 for w in sorted(involved_works)
        if not works_by_id[w]["has_references"]
    )
    refs_missing_rate = (n_refs_missing / n_involved) if n_involved else 0.0
    mnar_required = refs_missing_rate > mnar_thr
    if mnar_required:
        warnings.warn(
            f"[{stage}] refs missing rate {refs_missing_rate:.1%} > "
            f"{mnar_thr:.0%} — MNAR (missing not at random) risk, downstream must run robustness checks "
            "(mnar_robustness_required=true, caveat#1)",
            UserWarning,
            stacklevel=2,
        )

    # -- 7. build rows pair by pair (11 columns) -------------------------------------------------
    rows: list = []
    n_boundary = 0
    for inc, star, eid, t1, degree, bridge_frozen in pair_specs:
        who = (inc, star, eid, degree)
        if degree == 2 and not bridge_frozen:
            share = 0.0  # #5: for an unfrozen channel the main dose is recorded as 0 and never quietly computed (#7b)
        else:
            refs_inc = coupling.person_refs_until(inc, _rows_of(t1, inc),
                                                  refs_map, t1)
            refs_star = coupling.person_refs_until(star, _rows_of(t1, star),
                                                   refs_map, t1)
            share = coupling.pair_coupling(refs_inc, refs_star, ref_idf)  # delegate (#14)
        tcos = topic_vec.pair_topic_cos(
            topic_vec.person_topic_vec(inc, _rows_of(t1, inc), works_by_id, t1),
            topic_vec.person_topic_vec(star, _rows_of(t1, star), works_by_id, t1),
        )
        if embed_deferred:
            ecos = None   # deferred: NA (never fake a 0 similarity — NA is never treated as 0)
        else:
            vec_i = embed.person_embed_vec(inc, _rows_of(t1, inc), emb_by_work, t1)
            vec_s = embed.person_embed_vec(star, _rows_of(t1, star), emb_by_work, t1)
            ecos = (identity_dose.embed_cos(vec_i, vec_s)
                    if (vec_i is not None and vec_s is not None) else 0.0)
        cov = coupling.pair_coverage(inc, star, _rows_of(t1, inc, star),
                                     works_by_id, t1)
        boundary = cov < coverage_floor  # RED coverage_floor downgrade gate
        if boundary:
            n_boundary += 1
        rows.append({
            "incumbent_person_id": inc,
            "star_person_id": star,
            "event_id": eid,
            "coupling_share": _unit_interval(share, name="coupling_share", who=who),
            "topic_cos": _unit_interval(tcos, name="topic_cos", who=who),
            "embed_cos": (None if ecos is None
                          else _unit_interval(ecos, name="embed_cos", who=who)),
            "coupling_coverage": _unit_interval(cov, name="coupling_coverage",
                                                who=who),
            "frozen_at_year": int(t1),  # == events.t_minus_1 (§⑤ #24)
            "degree": degree,
            "degree2_bridge_frozen": bool(bridge_frozen),
            "boundary_sensitive": bool(boundary),
        })

    _assert_pk_unique(rows)  # §⑤ #27b
    rows.sort(key=lambda r: tuple(r[c] for c in _PK))  # canonical-sort by the full PK

    # -- 8. reconcile gate (balance first, then COMMIT; tally is written atomically by reconcile) ------------
    op_ids = {"|".join(str(r[c]) for c in _PK) for r in rows}
    reconcile_fetch(
        expected=len(pair_specs), kept=len(rows), failed=0, skipped=0,
        op_ids_expected=op_ids, op_ids_seen=op_ids,
        stage=stage, tally_path=out_root / "tally.json",
    )

    # -- 9. deterministic parquet -> two-phase COMMIT (all-or-nothing, #29/#27) ------
    build_dir = out_root / "_build_tmp"
    build_dir.mkdir(parents=True, exist_ok=True)
    dose_tmp = build_dir / "dose.parquet"
    emb_tmp = build_dir / "work_embeddings.parquet"
    write_rows_parquet(rows, dose_tmp, schema=PAIRWISE_DOSE, pk_cols=_PK,
                       label="dose.parquet")
    embed.write_frozen_embeddings(emb_rows, emb_tmp)
    payload = {
        "dose.parquet": dose_tmp.read_bytes(),
        "work_embeddings.parquet": emb_tmp.read_bytes(),
    }
    shutil.rmtree(build_dir)
    provenance = {
        "source_snapshot_merkle": merkle,
        "config_sha": config_sha,
        "rule_version": rule_version,
        "stars_set_hash": stars_hash,
    }
    write_dataset_commit(out_root, payload, provenance=provenance).stage().commit()

    # -- 10. auxiliary inverted index (acceleration path, not a frozen payload; H4 year source = works) -----------------
    posting_index.build_posting_by_year(
        inputs.refs_edges, works_by_id, out_root / "posting_by_year",
        ref_idf=ref_idf, idf_floor=idf_floor,
    )

    # -- 11. diagnostics sidecar (kept out of the six TALLY keys, as in #47) ---------------------
    diag = {
        "stage": stage,
        "p_level": p_level,
        "n_pairs_enumerated": len(pair_specs),
        "n_rows": len(rows),
        "n_involved_works": n_involved,
        "refs_missing_rate": refs_missing_rate,
        "mnar_robustness_required": mnar_required,
        "mnar_missing_threshold": mnar_thr,
        "coverage_floor": coverage_floor,
        "n_boundary_sensitive": n_boundary,
        "n_unmapped_edge_authors": n_unmapped_edges,
        "n_unmapped_star_authors": inputs.n_unmapped_star_authors,
        "embed_deferred": embed_deferred,   # secondary-dose deferred flag
        "incumbent_pool_applied": pool is not None,
        "incumbent_pool_size": (len(pool) if pool is not None else None),
    }
    atomic_write_bytes(
        out_root / "diag.json",
        json.dumps(diag, ensure_ascii=False, sort_keys=True).encode("utf-8"),
    )

    # -- 12. ledger (.append only — DRIFT-L1, #28) ---------------------------
    ledger.append(
        op_id=stage, status="ok", shard_id=p_level, idempotency_key=idem_key,
        ts=datetime.now(timezone.utc).isoformat(), reason="",
    )

    return {
        "skipped": False,
        "stage": stage,
        "idempotency_key": idem_key,
        "n_rows": len(rows),
        "refs_missing_rate": refs_missing_rate,
        "mnar_robustness_required": mnar_required,
        "embed_deferred": embed_deferred,   # stated explicitly in the return value (secondary dose deferred, main line not blocked)
        "out_root": str(out_root),
        "dose_parquet": str(out_root / "_frozen" / "dose.parquet"),
    }
