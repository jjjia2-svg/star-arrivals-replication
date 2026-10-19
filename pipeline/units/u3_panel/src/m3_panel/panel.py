"""U3 panel - the single producer (panel.parquet + affil_timeline.parquet).

Rebuilds the U2 person_map (disambiguated people) + U1 works_affil (each paper's listed institutions) into a researcher-by-year
unbalanced panel + per-work institution detail. **It computes only "the modal institution of the year = primary affiliation"
and never decides arrival, never decides stars, never redoes disambiguation.** U3 does not touch the identification layer.

End-to-end orchestration = build_panel(); the internal functions, in build order, each grown with TDD:
  _assert_upstream_present / _assert_registry_covers / _build_author_cmap /
  _load_person_works / _fold_institution / _remap_inst_ids / _canonicalize_affils /
  _build_affil_timeline / _apply_population_threshold / _compute_first_pub_year /
  _assemble_panel / _reconcile_panel.
★author_id canonical-space consistency (originally planned as a cross-table _assert_author_id_canonical_space, G2):
  implemented as "_build_author_cmap catches merge cycles → exit22" plus the two arms that use author_id
  (_load_person_works/_compute_first_pub_year), which normalize inline with the same canonicalize rule (not a separate assertion function).

★parquet writing reuses U1 m1_ingest._writer_util.write_rows_parquet (inheriting its 3-key deterministic kw), not hand-rolled.
★upstream read paths: derived/u1_edges/<table>/data.parquet (U1) / derived/u2_resolve/person_map/
  data.parquet (U2); reads only data.parquet, never globs data_SAMPLE.parquet.
"""
import json
import shutil
import sys
from pathlib import Path

from m3_panel._panel_redlines import (
    NONE_INST_SENTINEL,
    PANEL_AFFIL_NONE,
    POP_MIN_DISTINCT_YEARS,
)
from common.inst_lineage import (  # folding + econ-hint
    fold_to_canonical,
    in_au_econ_dept,
)
from common.manifest import dataset_is_valid, sha256_file, write_dataset_commit
from common.schema import AFFIL_TIMELINE, PANEL
from common.derived_table import (
    read_derived_table,
    read_derived_arrow,
    derived_table_present,
    derived_table_column_names,
    derived_table_content_hash,
)
from identity.constants import ENTITY_TO_IDTYPE
from identity.exit_codes import EXIT_CANONICAL_SPACE_SPLIT  # =22, U3-E author-space guard
from m1_ingest._writer_util import write_rows_parquet  # ★the only deterministic parquet writer (owner=U1)
from m1_ingest.canonical_id import (  # id normalization (used by G2/J1/J2); the real source is U1, not U0
    build_canonical_map,
    canonicalize,
    is_deleted,
)

# Red-line constants version (no 'unsigned' in it → the manifest treats it as signed → _frozen/COMMIT, dataset_is_valid=True).
# ★v2: first_pub switched to the shared robust debut year - the bump invalidates the resume anchor,
#   so old v1 products are never silently reused (changed behavior must rebuild).
RULE_VERSION = "u3_panel_v2_robust_first_pub_2026-07-16"
# Output table → (schema, pk_cols written to disk).
_OUT_SPEC = {
    "panel": (PANEL, ["person_id", "year"]),
    "affil_timeline": (AFFIL_TIMELINE,
                       ["person_id", "year", "work_id", "raw_inst_id", "raw_affil_slot"]),
}

# Upstream table → (unit subdirectory, table subdirectory). Real disk layout = derived/<unit>/<table>/data.parquet.
# Iron rule for reading upstream: read only data.parquet, never glob data_SAMPLE.parquet (avoids reading a fixture sample by mistake).
_UPSTREAM_LAYOUT = {
    "works_affil": ("u1_edges", "works_affil"),
    "authorship_edges": ("u1_edges", "authorship_edges"),
    "work_first_pub": ("u1_edges", "work_first_pub"),
    "canonical_id_map": ("u1_edges", "canonical_id_map"),
    "institutions": ("u1_edges", "institutions"),
    "person_map": ("u2_resolve", "person_map"),
}


def _upstream_dir(data_root, table):
    """Real on-disk directory of an upstream table <data_root>/derived/<unit>/<tbl>/ (single file data.parquet or bucketed
    bucket=*/part-* read transparently by common.derived_table, never reads data_SAMPLE.parquet).

    ★Convention follows U2 (resolve.py:_read_u1_table): data_root = SSD root (without derived); the orchestrator gives
      U2/U3 the same data_root.
    """
    unit, tbl = _UPSTREAM_LAYOUT[table]
    return Path(data_root) / "derived" / unit / tbl


def _cmap_legal_empty(table, table_dir) -> bool:
    """canonical_id_map only (a form caught on the first real-data run): for a 0-row table U1 writes only
    provenance.json and no part file → a legitimately empty table (0 rows = no merge mapping, every id is already canonical).
    The same form in other tables is not let through (an empty works_affil etc. = broken upstream; the semantics belong only to cmap).

    ★Legitimately empty ≠ lost file - must read row_count==0 from provenance (the real U1 emits this field);
      claiming row_count≥1 while the part is absent = corruption, not let through (silently passing would lose all redirects)."""
    if table != "canonical_id_map":
        return False
    ppath = Path(table_dir) / "provenance.json"
    if not ppath.exists():
        return False
    try:
        return json.loads(ppath.read_text(encoding="utf-8")).get("row_count") == 0
    except (json.JSONDecodeError, OSError):
        return False  # provenance itself is broken → not let through, take the strict missing-table path


def _upstream_content_hash(data_root, table) -> str:
    """Upstream content fingerprint (for resume); a legitimately empty cmap → a deterministic sentinel string, other missing tables still raise strictly."""
    d = _upstream_dir(data_root, table)
    if not derived_table_present(d) and _cmap_legal_empty(table, d):
        return "empty:canonical_id_map"
    return derived_table_content_hash(d)


def _works_dir(data_root):
    """Real on-disk directory of u1_edges/works (soft source for null-year arbitration; _load_person_works and the resume anchor share the same path,
    defined in one place to prevent drift). ★Not in _UPSTREAM_LAYOUT: works is a SOFT arbitration source, not a hard prerequisite table (absence is legal);
    putting it in _UPSTREAM_LAYOUT would make _assert_upstream_present treat it as a hard missing table and HALT."""
    return Path(data_root) / "derived" / "u1_edges" / "works"


def _works_arbitration_hash(data_root) -> str:
    """Resume fingerprint of the works arbitration soft source: present → content hash; absent → deterministic sentinel (mirrors the cmap sentinel pattern).

    Fix: works is consumed by _load_person_works (deciding "legitimately yearless: drop" vs "edge row missing year: HALT") but was not included in the
    resume upstream hash or the provenance merkle → after changing works, resume saw the 6 table shas unchanged and silently returned
    a stale panel arbitrated on the OLD works, while provenance claimed to lock the source snapshot but missed the works it really read.
    Absence needs a stable sentinel (the soft source may be absent; current behavior unchanged) - otherwise derived_table_content_hash raises
    FileNotFoundError on a missing table. Absent and present sentinels differ → works appearing/disappearing also triggers a resume rebuild (the arbitration result changes)."""
    d = _works_dir(data_root)
    if not derived_table_present(d):
        return "absent:works"
    return derived_table_content_hash(d)


def _assert_upstream_present(data_root, *, econ_dept_ids, registry_by_id):
    """Block on every upstream gap first: Path.exists() per table + injected params non-empty; if any is missing → print each one + sys.exit(2).

    ★Missing table / missing injection fails loudly, no inline workaround (institutions missing = go back to U1 and supply the U3-B coverage-domain contract).
    After existence + non-emptiness pass, check the 4-column schema of works_affil (only when present; an empty param exits first, so no empty file is read).
    """
    gaps = []
    missing = [t for t in _UPSTREAM_LAYOUT
               if not derived_table_present(_upstream_dir(data_root, t))
               and not _cmap_legal_empty(t, _upstream_dir(data_root, t))]
    for t in missing:
        hint = " (回 U1 补 institutions: U3-B 覆盖域契约)" if t == "institutions" else ""
        gaps.append(f"上游缺表: {t} → {_upstream_dir(data_root, t)}{hint}")
    if not econ_dept_ids:
        gaps.append("econ_dept_ids 为空 (U0.5 ECON_DEPT_REGISTRY 未注入?)")
    if not registry_by_id:
        gaps.append("registry_by_id 为空 (U0 build_registry_by_id 未注入?)")
    if gaps:
        for g in gaps:
            sys.stderr.write(f"[U3] {g}\n")
        sys.exit(2)

    # Here: the 6 tables are present + injections non-empty → check the 4-column schema of works_affil (read column names only, load no data).
    from common.schema import WORKS_AFFIL, assert_matches_schema

    # ★Schema reading is also inside the try → a 0-byte/corrupt parquet (ArrowInvalid) turns into a clean exit(2),
    #   fail-loud just like a schema mismatch, no traceback (SystemExit from sys.exit is not caught by Exception).
    try:
        cols = derived_table_column_names(_upstream_dir(data_root, "works_affil"))
        assert_matches_schema({c: None for c in cols}, WORKS_AFFIL, label="works_affil")
    except Exception as e:  # SchemaMismatchError | ArrowInvalid (0-byte/corrupt parquet)
        sys.stderr.write(f"[U3] works_affil schema read/validation failed (0 bytes or corrupt? check U1): {e}\n")
        sys.exit(2)


def _assert_registry_covers(econ_dept_ids, registry_by_id):
    """Every econ_dept_id must be resolvable in the registry; absent = audit gap → exit(2).

    Distinguish "folds to a non-education institution = legitimate None" (not reported) from "the id is not in the registry at all = gap" (reported).
    """
    uncovered = sorted(e for e in econ_dept_ids if e not in registry_by_id)
    if uncovered:
        sys.stderr.write(f"[U3] econ_dept_id not in registry (U0.5↔U0 definition gap): {uncovered}\n")
        sys.exit(2)


def _read_table(data_root, table, columns):
    d = _upstream_dir(data_root, table)
    if not derived_table_present(d) and _cmap_legal_empty(table, d):
        return []  # legitimately empty cmap → empty mapping

    """读上游表指定列 → list[dict] (件2: 单文件或桶化由 common.derived_table 透明读, 绝不读 SAMPLE)。"""
    return read_derived_table(_upstream_dir(data_root, table), columns)


def build_panel(data_root, out_dir, *, econ_dept_ids, registry_by_id, resume=True):
    """End-to-end orchestration: guards → normalize → fold → modal → threshold → first publication year → assemble → reconcile
    → deterministic write + COMMIT (anchored on the upstream shas; resume rebuilds if upstream changes).
    """
    import hashlib

    # Pre-run environment check: the first gate at the real-run entry of U3
    #   (the run_u3.py CLI is a stub awaiting U6 wiring, the production runner calls this function directly → the gate lives here).
    #   If any check fails → SystemExit(ENVIRONMENT_GATE_FAIL=30), nothing written to disk (preflight_result.json
    #   is the gate's own audit record, always written following the U0 preflight pattern, not a data product).
    from common.preflight import preflight_env_check
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _pf_rc = preflight_env_check(result_path=out_dir / "preflight_result.json")
    if _pf_rc != 0:
        raise SystemExit(_pf_rc)

    _assert_upstream_present(
        data_root, econ_dept_ids=econ_dept_ids, registry_by_id=registry_by_id
    )
    _assert_registry_covers(econ_dept_ids, registry_by_id)

    # Upstream shas (resume anchor) - 6 tables; resume=True and the dataset valid and sha+rule_version unchanged
    # and [the real products present + sha matching] → skip. ★Not just comparing upstream, the real output products must also be checked,
    # otherwise after deleting/half-writing panel.parquet the COMMIT is still there → silently skipped → downstream reads a missing file with zero errors.
    up_hashes = {t: _upstream_content_hash(data_root, t) for t in _UPSTREAM_LAYOUT}
    # ★works is the soft upstream of null-year arbitration (consumed by _load_person_works but once untracked) → merged into up_hashes,
    #   so it enters the resume anchor (compared below), manifest.upstream_hashes and provenance source_snapshot_merkle at the same time.
    up_hashes["works"] = _works_arbitration_hash(data_root)
    if resume and dataset_is_valid(out_dir):
        mpath = out_dir / "_frozen" / "manifest.json"
        if mpath.exists():
            old = json.loads(mpath.read_text(encoding="utf-8"))
            old_out = old.get("output_hashes", {})
            outputs_intact = all(
                (out_dir / name / "data.parquet").exists()
                and sha256_file(out_dir / name / "data.parquet") == old_out.get(name)
                for name in _OUT_SPEC
            )
            if (old.get("upstream_hashes") == up_hashes
                    and old.get("rule_version") == RULE_VERSION
                    and outputs_intact):
                return {"status": "skipped", "reason": "上游 sha + rule_version + 真产物未变"}

    # ★A real rebuild first clears _reports - leftover reports from an old run (failed / pre-fix) would be misread as audit traces
    #   of this run's products (seen on real data: a leftover u3_missing_year.csv from a HALT run). The skip branch is above and untouched.
    rep_dir = out_dir / "_reports"
    if rep_dir.exists():
        shutil.rmtree(rep_dir)

    # Read the frozen upstream tables.
    cmap_rows = _read_table(data_root, "canonical_id_map",
                            ["raw_id", "canonical_id", "id_type", "is_deleted"])
    pm_rows = _read_table(data_root, "person_map", ["author_id", "person_id"])  # ★read only 2 columns
    person_map = {r["author_id"]: r["person_id"] for r in pm_rows}
    wfp_rows = _read_table(data_root, "work_first_pub",
                           ["author_id", "first_pub_year", "first_pub_year_is_full_history"])
    inst_rows = _read_table(data_root, "institutions",
                            ["institution_id", "type", "lineage", "associated_institutions"])
    institutions_by_id = {r["institution_id"]: r for r in inst_rows}

    # author-space guard (merge cycle → exit22) + inst cmap + the set of redirect old ids (for reconciliation).
    author_cmap = _build_author_cmap(cmap_rows)
    inst_cmap = build_canonical_map(
        [r for r in cmap_rows if r.get("id_type") == ENTITY_TO_IDTYPE["institutions"]],
        id_type=ENTITY_TO_IDTYPE["institutions"],
    )
    redirect_ids = {raw for raw, (canon, _d) in inst_cmap.items() if raw != canon}

    # chain.
    person_works = _load_person_works(
        data_root, person_map=person_map, author_cmap=author_cmap, out_dir=out_dir
    )
    remapped, _n_deleted = _remap_inst_ids(person_works, inst_cmap)
    affil_rows, _counts = _canonicalize_affils(
        remapped, institutions_by_id, registry_by_id, out_dir=out_dir
    )
    timeline = _build_affil_timeline(affil_rows)
    eligible = _apply_population_threshold(person_works, out_dir=out_dir)
    # ★Production switch to the robust debut year: corpus publication years + the U1 full-history min are fed together to
    #   the shared robust function (gap = a set red-line value, passed explicitly, never silently defaulted).
    from common._redlines import require
    _person_years = {}
    for _r in person_works:
        _person_years.setdefault(_r["person_id"], set()).add(_r["publication_year"])
    first_pub_map = _compute_first_pub_year(
        person_map, wfp_rows, author_cmap=author_cmap, person_years=_person_years,
        max_leading_gap=require("academic_age", "robust_first_pub_max_gap"))
    panel = _assemble_panel(person_works, timeline, eligible, first_pub_map, econ_dept_ids)
    timeline_elig = [r for r in timeline if r["person_id"] in eligible]
    # _reconcile_panel returns a timeline with "byte-identical rows folded" (collision detail goes to _reports),
    # the write uses the returned value - the writer only canonical-sorts and does not dedup, so deduplication is the reconcile layer's job.
    timeline_elig = _reconcile_panel(panel, timeline_elig, eligible, person_works,
                                     redirect_ids=redirect_ids, out_dir=out_dir)

    # Deterministic write: the two tables go directly to out_dir/<table>/data.parquet (U2 pattern; write_rows_parquet only does
    # canonical-sort + deterministic write params, no dedup - PK uniqueness is guaranteed by _reconcile_panel above);
    # write_dataset_commit only writes _frozen/COMMIT + the manifest anchor validity.
    out_shas = {}
    for name, rows in [("panel", panel), ("affil_timeline", timeline_elig)]:
        schema, pk_cols = _OUT_SPEC[name]
        target = out_dir / name / "data.parquet"
        write_rows_parquet(rows, target, schema=schema, pk_cols=pk_cols, label=name)
        out_shas[name] = sha256_file(target)
    manifest_bytes = json.dumps(
        {"upstream_hashes": up_hashes, "output_hashes": out_shas, "rule_version": RULE_VERSION},
        sort_keys=True, ensure_ascii=False,
    ).encode("utf-8")
    provenance = {
        "rule_version": RULE_VERSION,
        "config_sha": "u3_panel",
        "source_snapshot_merkle": hashlib.sha256(
            json.dumps(up_hashes, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "stars_set_hash": "n/a-u3-no-star-layer",  # U3 does not touch the star layer
    }
    write_dataset_commit(out_dir, {"manifest.json": manifest_bytes},
                         provenance=provenance).stage().commit()
    return {
        "status": "built",
        "n_panel_rows": len(panel),
        "n_affil_rows": len(timeline_elig),
        "n_eligible_persons": len(eligible),
    }


def _build_author_cmap(cmap_rows):
    """Build author_cmap = {raw_id:(canonical,is_deleted)} from the author rows of canonical_id_map (G2/U3-E).

    ★A merge cycle = a corrupted canonical space (upstream not fully folded) → fail-loud exit(EXIT_CANONICAL_SPACE_SPLIT=22),
      never silently join on a corrupted space (losing people = the reverse of the Yves Zenou 16-ID problem). build_canonical_map replays internally
      and raises ValueError on a cycle; this function catches it and turns it into an exit.
    No redirect (empty table / all self-referencing) → empty cmap, canonicalize returns everything unchanged = inputs already canonical (normal).
    """
    author_rows = [
        r for r in cmap_rows if r.get("id_type") == ENTITY_TO_IDTYPE["authors"]
    ]
    try:
        return build_canonical_map(author_rows, id_type=ENTITY_TO_IDTYPE["authors"])
    except ValueError:
        sys.stderr.write(
            "[U3] author canonical_id_map contains a merge cycle → canonical space corrupt, "
            "HALT EXIT_CANONICAL_SPACE_SPLIT\n"
        )
        sys.exit(EXIT_CANONICAL_SPACE_SPLIT)


def _write_report_csv(out_dir, name, rows, fields):
    """Write an audit by-product csv to out_dir/_reports/name (orphan / missing-year / null-inst details etc.; never silently dropped)."""
    import csv

    rep_dir = Path(out_dir) / "_reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    with open(rep_dir / name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})


def _load_person_works(data_root, *, person_map, author_cmap=None, out_dir=None):
    """Read works_affil ⟕ authorship_edges → a long table folded to person_id (J1 step 2).

    Returns [{person_id, work_id, publication_year, institution_id, raw_affiliation_strings}, ...].
    Reading follows U2: pyarrow reads data.parquet (only data.parquet, no glob of SAMPLE); join engine = duckdb.
    ★LEFT join (works_affil on the left): a missing year is not silently dropped; null found → write csv + exit(2) (PK coverage gap).
    ★Fold to person_id first, then compute (computing per author_id for one real person with several ids would hit the Yves Zenou 16-ID problem).
    ★Orphan author_id (not in person_map): written to u3_unmapped_authors.csv + kept out of the panel (not silently dropped).
    ★Arbitration coverage domain: after the semi-join pushdown, year-null arbitration covers only rows of panel-population people -
      broken-year rows of orphan authors no longer trigger HALT (orphans never enter the panel anyway; the semantics are acceptable and stated explicitly here).
    """
    import duckdb
    import pyarrow as pa

    from common.derived_table import table_part_paths

    # ★OOM fix (real data hit exit=137): never load or materialize the whole table of 107 million rows -
    #   duckdb scans parquet directly + pushes down a semi-join on "person_map authors ∪ the raw ids that redirect to them",
    #   materializing only the rows of the panel population (semantically equivalent: filtered-out rows = orphans, which never enter the panel; see the orphan report below).
    wa_paths = [str(x) for x in table_part_paths(_upstream_dir(data_root, "works_affil"))]
    ae_paths = [str(x) for x in table_part_paths(_upstream_dir(data_root, "authorship_edges"))]
    keep_ids = set(person_map)
    if author_cmap:
        keep_ids |= {raw for raw, (canon, _d) in author_cmap.items() if canon in person_map}

    con = duckdb.connect()
    try:
        con.execute("PRAGMA memory_limit='6GB'")
        if out_dir is not None:
            tmp = Path(out_dir) / "_duckdb_tmp"
            tmp.mkdir(parents=True, exist_ok=True)
            con.execute(f"PRAGMA temp_directory='{tmp}'")  # spill to the SSD, do not hold it in memory
        con.register("keep_ids", pa.table({"author_id": pa.array(sorted(keep_ids),
                                                                 type=pa.string())}))
        joined = con.execute(
            f"SELECT wa.work_id AS work_id, wa.author_id AS author_id, "
            f"       ae.publication_year AS publication_year, "
            f"       wa.institution_id AS institution_id, "
            f"       wa.raw_affiliation_strings AS raw_affiliation_strings "
            f"FROM read_parquet({wa_paths!r}) wa "
            f"LEFT JOIN read_parquet({ae_paths!r}) ae "
            f"  ON wa.work_id = ae.work_id AND wa.author_id = ae.author_id "
            f"WHERE wa.author_id IN (SELECT author_id FROM keep_ids)"
        ).to_arrow_table().to_pylist()
        # Orphans = (work,author) rows not in keep_ids: exact count + detail (sampling capped at 100k, not silently dropped
        #   - the full set can be recomputed at any time by the same semi-join; the count semantics in the csv's first-line comment are carried by _reports).
        orphan_rows = con.execute(
            f"SELECT work_id, author_id FROM read_parquet({wa_paths!r}) "
            f"WHERE author_id NOT IN (SELECT author_id FROM keep_ids) "
            f"ORDER BY work_id, author_id LIMIT 100000"
        ).fetchall()
        n_orphan_total = con.execute(
            f"SELECT count(*) FROM read_parquet({wa_paths!r}) "
            f"WHERE author_id NOT IN (SELECT author_id FROM keep_ids)"
        ).fetchone()[0]
        # ★Rows with author_id IS NULL are swallowed by SQL three-valued logic (IN cannot keep them,
        #   NOT IN cannot put them in orphans) - the behavior is right (NULL maps to no person) but the accounting needs a category; three classes are conserved:
        #   kept + orphan + null_author = total rows of works_affil (3,116,514 rows seen on real data).
        n_null_author = con.execute(
            f"SELECT count(*) FROM read_parquet({wa_paths!r}) "
            f"WHERE author_id IS NULL"
        ).fetchone()[0]
    finally:
        con.close()
    if n_null_author and out_dir is not None:
        _write_report_csv(out_dir, "u3_null_author_rows_count.csv",
                          [{"n_null_author_rows": n_null_author}],
                          ["n_null_author_rows"])

    # 2-b: PK coverage guard - year-null rows are first arbitrated through the works table (real-data finding:
    #   3,199 papers have no publication year themselves = a data fact, not corruption):
    #   works.publication_year also null → legitimately yearless → drop + write csv (a yearless row cannot enter the person-by-year panel);
    #   works has a year but the edge row is null → real corruption, HALT; arbitration works table absent → conservative HALT (original behavior).
    missing_year = [r for r in joined if r["publication_year"] is None]
    if missing_year:
        works_dir = _works_dir(data_root)  # ★the same path as the resume anchor (_works_arbitration_hash)
        legal_null_ids: set = set()
        if derived_table_present(works_dir):
            import duckdb as _ddb

            from common.derived_table import table_part_paths as _tpp

            w_paths = [str(x) for x in _tpp(works_dir)]
            wids = sorted({r["work_id"] for r in missing_year})
            _c = _ddb.connect()
            try:
                import pyarrow as _pa

                _c.register("mm_ids", _pa.table({"work_id": _pa.array(wids,
                                                                      type=_pa.string())}))
                legal_null_ids = {row[0] for row in _c.execute(
                    f"SELECT w.work_id FROM read_parquet({w_paths!r}) w "
                    f"JOIN mm_ids USING (work_id) WHERE w.publication_year IS NULL"
                ).fetchall()}
            finally:
                _c.close()
        legal = [r for r in missing_year if r["work_id"] in legal_null_ids]
        broken = [r for r in missing_year if r["work_id"] not in legal_null_ids]
        if legal and out_dir is not None:
            _write_report_csv(out_dir, "u3_null_year_works.csv", legal,
                              ["work_id", "author_id"])
        if broken:
            if out_dir is not None:
                _write_report_csv(out_dir, "u3_missing_year.csv", broken,
                                  ["work_id", "author_id"])
            sys.stderr.write(
                f"[U3] {len(broken)} works_affil rows lack year in authorship_edges and the works table "
                f"has a year or cannot arbitrate (PK coverage gap, report to U1) → HALT\n"
            )
            sys.exit(2)
        joined = [r for r in joined if r["publication_year"] is not None]

    # 2-c: fold to person_id (keep_ids may still contain redirect-raw ids → canonicalize then look up person_map;
    #   still not found after canonicalization = outer edge of a redirect chain, handled like an orphan, not silently).
    out, late_orphans = [], []
    for r in joined:
        aid = r["author_id"]
        if author_cmap:
            aid = canonicalize(aid, author_cmap)  # redirect→canonical (space already guarded by G2)
        pid = person_map.get(aid)
        if pid is None:
            late_orphans.append({"work_id": r["work_id"], "author_id": aid})
            continue
        out.append({
            "person_id": pid,
            "work_id": r["work_id"],
            "publication_year": r["publication_year"],
            "institution_id": r["institution_id"],
            "raw_affiliation_strings": r["raw_affiliation_strings"],
        })
    orphans = ([{"work_id": w, "author_id": a} for w, a in orphan_rows] + late_orphans)
    if orphans and out_dir is not None:
        _write_report_csv(out_dir, "u3_unmapped_authors.csv", orphans,
                          ["work_id", "author_id"])
        if n_orphan_total > len(orphan_rows):
            _write_report_csv(out_dir, "u3_unmapped_authors_count.csv",
                              [{"n_orphan_total": n_orphan_total,
                                "n_in_csv": len(orphan_rows)}],
                              ["n_orphan_total", "n_in_csv"])
    return out


def _fold_institution(inst_row, registry_by_id):
    """Fold one INSTITUTIONS row to the canonical edu parent institution bare id (cannot fold → None).

    ★Key remapping (J2 crux): the INSTITUTIONS column `institution_id` → the `openalex_id` that fold_to_canonical path1 reads.
      Miss this step → folding of foreign/complex institutions always misses (the killer case of Yves Zenou's Stockholm/IFN).
    """
    inst = {
        "openalex_id": inst_row["institution_id"],
        "type": inst_row.get("type"),
        "lineage": inst_row.get("lineage") or [],
        "associated_institutions": inst_row.get("associated_institutions") or [],
    }
    return fold_to_canonical(inst, registry_by_id)


def _remap_inst_ids(rows, inst_cmap):
    """Normalize institution_id redirect→canonical bare + route is_deleted ones out (J2 step 3: normalize first).

    Returns (remapped_rows, n_deleted). is_deleted uses the U1 canonical_id version (takes the cmap tuple), not the U0 manifest one.
    """
    out, n_deleted = [], 0
    for r in rows:
        iid = r.get("institution_id")
        if iid and is_deleted(iid, inst_cmap):
            n_deleted += 1  # deleted sentinel institution listing → routed out (no institution row written)
            continue
        new = dict(r)
        new["institution_id"] = canonicalize(iid, inst_cmap) if iid else iid
        out.append(new)
    return out, n_deleted


def _canonicalize_affils(rows, institutions_by_id, registry_by_id, *, out_dir=None):
    """Three-way folding → affil rows (J2 step 3 a/b/c; null-id is not silently zeroed).

    Returns (affil_rows, counts). Each affil_row =
      {person_id, year, work_id, raw_inst_id, canonical_affil_id, raw_affil_strings}.
    (a) inst_id in institutions → fold; fold→None (hospital/government/facility) writes no institution row.
    (b) inst_id non-empty but not in institutions → count + csv (fail-loud, not silently zeroed), no row written.
    (c) inst_id empty but raw non-empty → raw-only row (canonical=raw_inst=__NONE__), counted (≠ no Australian affiliation).
    """
    affil_rows, not_in_inst, null_with_raw = [], [], []
    for r in rows:
        iid = r.get("institution_id")
        raw = r.get("raw_affiliation_strings") or []
        base = {
            "person_id": r["person_id"],
            "year": r["publication_year"],
            "work_id": r["work_id"],
            "raw_affil_strings": list(raw),
        }
        if iid:
            if iid in institutions_by_id:
                canon = _fold_institution(institutions_by_id[iid], registry_by_id)
                if canon is None:
                    continue  # (a)-None: hospital/government/facility → no institution row (the person's presence is still carried by person_works)
                affil_rows.append({**base, "raw_inst_id": iid, "canonical_affil_id": canon})
            else:
                not_in_inst.append({"work_id": r["work_id"], "institution_id": iid})  # (b)
        elif raw:
            null_with_raw.append({"work_id": r["work_id"]})  # (c)
            affil_rows.append({
                **base, "raw_inst_id": NONE_INST_SENTINEL,
                "canonical_affil_id": NONE_INST_SENTINEL,
            })
        # iid empty + raw empty → no information, no row written
    if out_dir is not None:
        if not_in_inst:
            _write_report_csv(out_dir, "u3_inst_not_in_institutions.csv", not_in_inst,
                              ["work_id", "institution_id"])
        if null_with_raw:
            _write_report_csv(out_dir, "u3_null_inst_with_raw.csv", null_with_raw, ["work_id"])
    counts = {
        "rows_inst_not_in_institutions": len(not_in_inst),
        "rows_null_inst_with_raw": len(null_with_raw),
    }
    return affil_rows, counts


def _build_affil_timeline(canon_rows):
    """Modal institution + raw_affil determinism + raw_affil_slot (M1 step 4). Returns the AFFIL_TIMELINE 9-key row set.

    ★Modal vote unit = distinct work_id (one vote per work, never counted at raw_inst_id granularity).
    ★is_modal: the one with the most votes among non-__NONE__; ties → the lexicographically smallest canonical_affil_id (deterministic).
    ★raw_affil = within that canonical cell, all raws flattened to string level, then the global lexicographic min (deterministic, across entries and works).
    ★is_modal ≠ U4 arrival (a pure per-year modal marker, cannot be used alone as arrival evidence).
    """
    from collections import defaultdict

    by_py = defaultdict(list)
    for r in canon_rows:
        by_py[(r["person_id"], r["year"])].append(r)

    out = []
    for (pid, year), rows in by_py.items():
        works_by_canon = defaultdict(set)
        raws_by_canon = defaultdict(list)
        for r in rows:
            works_by_canon[r["canonical_affil_id"]].add(r["work_id"])
            raws_by_canon[r["canonical_affil_id"]].extend(r.get("raw_affil_strings") or [])
        n_works_at = {c: len(ws) for c, ws in works_by_canon.items()}
        raw_affil_of = {c: (min(raws) if raws else "") for c, raws in raws_by_canon.items()}

        # is_modal: __NONE__ does not compete; most votes; ties → lexicographically smallest id
        candidates = {c: n for c, n in n_works_at.items() if c != NONE_INST_SENTINEL}
        modal = None
        if candidates:
            maxv = max(candidates.values())
            modal = min(c for c, n in candidates.items() if n == maxv)

        # raw_affil_slot: __NONE__ rows are ordered per work_id by raw lexicographic order 0,1,2…; non-__NONE__ rows get slot=0
        slot_of = {}
        none_by_work = defaultdict(list)
        for r in rows:
            if r["canonical_affil_id"] == NONE_INST_SENTINEL:
                none_by_work[r["work_id"]].append(r)
        for _w, nrows in none_by_work.items():
            ordered = sorted(nrows, key=lambda r: tuple(sorted(r.get("raw_affil_strings") or [])))
            for i, r in enumerate(ordered):
                slot_of[id(r)] = i

        for r in rows:
            canon = r["canonical_affil_id"]
            out.append({
                "person_id": pid,
                "year": year,
                "work_id": r["work_id"],
                "raw_inst_id": r["raw_inst_id"],
                "raw_affil_slot": slot_of.get(id(r), 0),
                "canonical_affil_id": canon,
                "n_works_at_affil": n_works_at[canon],
                "is_modal": (canon == modal),
                "raw_affil": raw_affil_of[canon],
            })
    return out


def _apply_population_threshold(person_works_rows, *, out_dir=None):
    """Population threshold (A1 step 5, C1: single rule #9). Returns eligible_persons: set.

    ★Rule = distinct publication_year >= POP_MIN_DISTINCT_YEARS(=2); the redundant ≥1 paper rule of v2 is dropped.
      n_works is no longer a threshold (only a panel column). This step consumes no events table (incumbent stripping).
    ★A sample-construction default, not an identification red line (#9).
    """
    from collections import defaultdict

    years_by_person = defaultdict(set)
    for r in person_works_rows:
        years_by_person[r["person_id"]].add(r["publication_year"])
    eligible = {p for p, ys in years_by_person.items()
                if len(ys) >= POP_MIN_DISTINCT_YEARS}
    below = sorted(p for p, ys in years_by_person.items()
                   if len(ys) < POP_MIN_DISTINCT_YEARS)
    if below and out_dir is not None:
        _write_report_csv(out_dir, "u3_below_threshold_persons.csv",
                          [{"person_id": p} for p in below], ["person_id"])
    return eligible


def _compute_first_pub_year(person_map, work_first_pub_rows, *, author_cmap=None,
                            person_years=None, max_leading_gap=None):
    """True career first-publication year + full_history flag (A1 step 6, C2: the #9→#7 chain). Returns {person_id:(year, is_full)}.

    ★Production switch: first_pub moves from the bare min to the **shared robust debut year**
      (identity.first_pub.robust_first_pub, symmetric with the U4 candidate side) -
      candidate year set = {U1 full-history fragment min years} ∪ the person's corpus publication years (person_years); robust drops
      the "lone leading old-paper year" (separated from the later career by > the set gap=10 = contamination by a namesake).
      - Why bring in the U1 full-history min: #9 requires the full-history value, not one truncated by the panel - when the early full-history years are
        continuous with the corpus career (gap ≤ 10) they are **kept** (the Yves Zenou 1991 type is not wrongly dropped); only lone, far-earlier ones (measured:
        15.25% of the panel pulled early by >10 years, median 23 years) are dropped - the contamination-resistant implementation stays faithful to the original intent of #9, not a change of rule.
      - person_years: {person_id: iterable of publication years} (derived by _load_person_works); None → empty
        (pure U1 value, convenient for unit tests). max_leading_gap: a set red-line value, passed explicitly by the caller (None → RedlineUnsigned inside
        robust, never silently defaulted).
    ★is_full_history takes the AND over multiple fragments (semantics unchanged). U3 only supplies values, does not freeze or group (freezing + grouping are in U6).
    ★author_id normalization must use the same rule as _load_person_works: when work_first_pub still holds
      a redirect author_id, not normalizing would silently drop the first publication year → a 1980s senior is treated as a newcomer (the most dangerous case of the #9→#7 chain, e.g. Yves Zenou).
    """
    from collections import defaultdict
    from identity.first_pub import robust_first_pub

    py = person_years or {}
    by_person = defaultdict(list)
    for r in work_first_pub_rows:
        aid = r["author_id"]
        if author_cmap:
            aid = canonicalize(aid, author_cmap)  # same rule as _load_person_works
        pid = person_map.get(aid)
        if pid is None:
            continue
        by_person[pid].append(
            (r["first_pub_year"], bool(r["first_pub_year_is_full_history"]))
        )
    out = {}
    for pid, frs in by_person.items():
        years = {y for y, _ in frs} | set(py.get(pid, ()))
        out[pid] = (robust_first_pub(years, max_leading_gap=max_leading_gap),
                    all(f for _, f in frs))
    return out


def _assemble_panel(person_works_rows, affil_timeline, eligible, first_pub_map, econ_dept_ids):
    """Assemble the unbalanced panel (A1 step 7). Returns the PANEL 8-column row set.

    ★Row set = {(person,year): person∈eligible AND person has ≥1 work in that year}; a missing year is never padded with a 0 row.
    ★presence/n_works_year use person_works (authorship), unaffected by J2 inst deletion (present means present).
    ★primary_affil_id = the canonical of the affil_timeline is_modal row; no modal → PANEL_AFFIL_NONE.
    ★in_au_econ_dept_modal_hint: the sentinel string never enters the contract function; the call site converts it explicitly to None.
    ★first_pub_year/flag come from the U1 full-history table (#9); person absent → NA(None)/False, never filled with 0.
    """
    from collections import defaultdict

    works_by_py = defaultdict(set)
    for r in person_works_rows:
        if r["person_id"] in eligible:
            works_by_py[(r["person_id"], r["publication_year"])].add(r["work_id"])

    modal_by_py = {}
    for r in affil_timeline:
        if r["is_modal"]:
            modal_by_py[(r["person_id"], r["year"])] = (r["canonical_affil_id"], r["raw_affil"])

    panel = []
    for (pid, year), works in works_by_py.items():
        primary, raw = modal_by_py.get((pid, year), (PANEL_AFFIL_NONE, ""))
        hint = in_au_econ_dept(
            None if primary == PANEL_AFFIL_NONE else primary, econ_dept_ids
        )  # the sentinel string never enters the contract function
        fp_year, fp_full = first_pub_map.get(pid, (None, False))
        panel.append({
            "person_id": pid,
            "year": year,
            "primary_affil_id": primary,
            "raw_affil": raw,
            "in_au_econ_dept_modal_hint": hint,
            "n_works_year": len(works),
            "first_pub_year": fp_year,
            "first_pub_year_is_full_history": fp_full,
        })
    return panel


def _halt(msg):
    sys.stderr.write(f"[U3] reconciliation failed: {msg} → HALT\n")
    sys.exit(2)


def _reconcile_panel(panel, affil_timeline, eligible, person_works_rows, *,
                     redirect_ids=frozenset(), out_dir=None):
    """Derived-class invariant reconciliation (R1 step 8: strict equality, hand-written exit(2), never assert_invariant_monotone).

    ★Strict row-count algebra ==: panel row count == Σ_{person∈eligible}(true number of years present). Monotone is an illusion and even if
      it held it is only a monotone guard (one row more or fewer still passes), missing the drift this reconciliation is meant to catch.
    ★year-subset: every person's panel years ⊆ works years (no years made up out of thin air). PK unique. canonical has no redirect old id.
    ★Honest simplification (traceable): deliberately does NOT call reconcile_fetch to write tally.json - the U3 derived layer has no fetch arithmetic arm
      (no failed/skipped concept); the hand-written strict equality is stronger than the illusory assert_invariant_monotone monotone guard borrowed via reconcile_fetch
      (it catches one row more or fewer), and the invariant coverage is complete. Only the tally provenance by-product symmetric with U1/U2 is saved.
    ★Returns the affil_timeline with "byte-identical rows folded" - see the comment at the end of the function.
    """
    from collections import defaultdict

    years_by_person = defaultdict(set)
    for r in person_works_rows:
        if r["person_id"] in eligible:
            years_by_person[r["person_id"]].add(r["publication_year"])

    expected = sum(len(ys) for ys in years_by_person.values())
    if len(panel) != expected:
        _halt(f"panel row count {len(panel)} != expected {expected} (strict equality)")

    for r in panel:
        if r["year"] not in years_by_person.get(r["person_id"], set()):
            _halt(f"panel contains a year with no works: ({r['person_id']}, {r['year']})")

    pks = [(r["person_id"], r["year"]) for r in panel]
    if len(pks) != len(set(pks)):
        _halt("panel PK (person_id, year) is duplicated")

    out_inst = {r["primary_affil_id"] for r in panel if r["primary_affil_id"] != PANEL_AFFIL_NONE}
    out_inst |= {r["raw_inst_id"] for r in affil_timeline if r["raw_inst_id"] != NONE_INST_SENTINEL}
    bad = out_inst & set(redirect_ids)
    if bad:
        _halt(f"output contains an old redirect id (canonical not fully folded): {sorted(bad)}")

    # ★Duplicate-row folding: U2 folds the two author_ids of the same real person into one person, so a same-paper same-institution double listing of that person gives completely identical
    #   (P, year, W, raw_inst_id, raw_affil_slot) duplicate rows. Measured: the PK-colliding rows are
    #   byte-identical in all 9 columns, and after deduplication the modal / vote counts do not change at all → folding = lossless + faithful to the spec "one vote per work, never double-count".
    #   Handling: ① fold byte-identical rows (keep the first occurrence; since the rows are identical this equals any retention policy);
    #         ② write collision details to _reports/u3_affil_timeline_pk_collisions.csv (an over-merge signal is not silently dropped);
    #         ③ if the PK still collides after folding (= a non-identical real collision) → HALT as before (the guard is not weakened, only provably harmless identical duplicates are let through).
    #   Rollback: restore this block to the old three lines "assert PK unique, halt on any duplicate".
    tl_pk_cols = _OUT_SPEC["affil_timeline"][1]  # [person_id, year, work_id, raw_inst_id, raw_affil_slot]
    seen_full = set()
    deduped = []
    pk_counts: dict = defaultdict(int)
    for r in affil_timeline:
        pk_counts[tuple(r.get(c) for c in tl_pk_cols)] += 1
        full_key = tuple(sorted(r.items()))          # full-column fingerprint (folds only byte-identical rows)
        if full_key in seen_full:
            continue
        seen_full.add(full_key)
        deduped.append(r)
    collided = sorted((pk for pk, n in pk_counts.items() if n > 1),
                      key=lambda pk: tuple(str(x) for x in pk))
    if collided and out_dir is not None:
        after = defaultdict(int)
        for r in deduped:
            after[tuple(r.get(c) for c in tl_pk_cols)] += 1
        _write_report_csv(
            out_dir, "u3_affil_timeline_pk_collisions.csv",
            [{**dict(zip(tl_pk_cols, pk)),
              "n_rows_before_dedup": pk_counts[pk],
              "n_rows_after_dedup": after[pk]} for pk in collided],
            list(tl_pk_cols) + ["n_rows_before_dedup", "n_rows_after_dedup"])
    tl_pks = [tuple(r.get(c) for c in tl_pk_cols) for r in deduped]
    if len(tl_pks) != len(set(tl_pks)):
        _halt(f"affil_timeline PK {tuple(tl_pk_cols)} is duplicated (not a byte-identical collision, so dedup cannot fold it)")
    return deduped
