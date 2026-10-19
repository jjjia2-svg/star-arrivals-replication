"""Build the Panel 3 estimation panel ("slim": grp, ev, year, y, D) from a pair-year table.
The grp/ev expressions are copied verbatim from cluster_event_2026-08-16/code/make_slim_ev.py (which
itself re-derives the econ_fnfix / 30_build_panels23_gold grp); equality to the frozen slims is
enforced by tests/test_make_slim.py. Single implementation replacing 6 copies.

M3 Task 8. This builder now REPORTS what it wrote — one `OK <abs path>  (<n> B, sha256 <hex>)` line
per file, the same line the four launchers print — and returns those hashes in its stats dict. That
is not decoration: `tests/test_pipeline_rebuild.py` proves a rebuild by requiring the file it
compares to appear in the PRODUCER's report with matching bytes, and for these six frames the
produced-set used to be built by the test hashing the output after the call. One
`shutil.copyfile(<frozen frame>, out)` inserted after `make_slim(...)` therefore made both
comparisons, for three fields, compare the frozen file with itself and stay green (T7 final review,
NEW-2). The hash is now taken inside the builder, immediately after the COPY, and the `--noev`
projection — the device the ev/non-ev column asymmetry needs — is produced here too rather than in
the test, so no compared file is one the test made for itself.

**What that does and does not buy (T8 review, MINOR-1).** It does NOT make the produced-set
self-verifying: the reviewer added two lines HERE, copying the frozen frame over the output before
`_report()` hashes it, and all four of the acceptance layer's provenance guards agreed — right path,
right inode, mtime after the run started, hash matching the report. What changed is WHERE the trust
sits. Forging the produced-set now means editing a file that is sha256-pinned twice, in
`tests/pipeline_ported.sha256` and in `tests/test_verbatim_pipeline.py::REPO_AUTHORED`, so the edit
fails `tools/verify_ported.py`, `tools/repin.sh --check` and two verbatim tests — which is exactly
how the reviewer's version was caught. The honest sentence is "trust anchored in a doubly-pinned
builder", not "the report cannot lie".
"""
import duckdb, hashlib, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

def _con():
    con = duckdb.connect(); con.execute("PRAGMA threads=6"); con.execute("PRAGMA memory_limit='14GB'"); return con

def _report(path: pathlib.Path) -> str:
    """The launcher's own report line, so a caller parses one format everywhere."""
    b = pathlib.Path(path).read_bytes()
    sha = hashlib.sha256(b).hexdigest()
    print(f"    OK   {pathlib.Path(path).resolve()}  ({len(b):,} B, sha256 {sha})")
    return sha

def make_slim(field: str, src: pathlib.Path, out: pathlib.Path, noev: pathlib.Path | None = None) -> dict:
    con = _con(); src = str(src); out_path = pathlib.Path(out); out = str(out)
    if field == "econ":
        sql = f"""SELECT CAST(DENSE_RANK() OVER (ORDER BY i_id || '_' || j_id || '@' || event_id) - 1 AS INTEGER) AS grp,
                         CAST(DENSE_RANK() OVER (ORDER BY event_id) AS INTEGER) AS ev,
                         CAST(year AS INTEGER) AS year, CAST(y_any AS TINYINT) AS y, CAST(post AS TINYINT) AS D
                  FROM read_csv_auto('{src}')"""
    else:
        sql = f"""WITH p AS (SELECT DISTINCT i_id, j_id, event_id FROM read_parquet('{src}')),
                       g AS (SELECT row_number() OVER (ORDER BY event_id, i_id, j_id) AS grp,
                                    dense_rank() OVER (ORDER BY event_id) AS ev, i_id, j_id, event_id FROM p)
                  SELECT CAST(g.grp AS INTEGER) AS grp, CAST(g.ev AS INTEGER) AS ev,
                         CAST(r.year AS INTEGER) AS year, CAST(r.y_any AS TINYINT) AS y, CAST(r.post AS TINYINT) AS D
                  FROM read_parquet('{src}') r JOIN g USING (i_id, j_id, event_id)"""
    con.execute(f"COPY ({sql}) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    n, g, t, e = con.execute(f"SELECT count(*), count(DISTINCT grp), sum(y), count(DISTINCT ev) FROM read_parquet('{out}')").fetchone()
    stats = {"rows": n, "pairs": g, "ties": int(t), "events": e,
             "produced": {str(out_path.resolve()): _report(out_path)}}
    if noev is not None:
        # the frozen non-`ev` slims have a genuinely different COLUMN SET, not a different type, so
        # the comparison needs the same build projected onto their columns. Produced here, by the
        # builder, from the file it has just written — never by the consumer of the comparison.
        noev_path = pathlib.Path(noev)
        cols = [c[0] for c in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{out}')").fetchall()]
        keep = [c for c in cols if c != "ev"]
        assert len(keep) == len(cols) - 1, cols
        con.execute(f"COPY (SELECT {', '.join(keep)} FROM read_parquet('{out}')) "
                    f"TO '{noev_path}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        stats["noev_columns"] = keep
        stats["produced"][str(noev_path.resolve())] = _report(noev_path)
    return stats

def content_equal(a: pathlib.Path, b: pathlib.Path, cols=("grp", "year", "y", "D")) -> bool:
    con = _con(); c = ", ".join(cols)
    diff = con.execute(f"""SELECT count(*) FROM (
        (SELECT {c} FROM read_parquet('{a}') EXCEPT ALL SELECT {c} FROM read_parquet('{b}'))
        UNION ALL
        (SELECT {c} FROM read_parquet('{b}') EXCEPT ALL SELECT {c} FROM read_parquet('{a}')))""").fetchone()[0]
    return diff == 0

if __name__ == "__main__":
    argv = sys.argv[1:]
    noev = None
    if "--noev" in argv:
        i = argv.index("--noev"); noev = pathlib.Path(argv[i + 1]); del argv[i:i + 2]
    field, src, out = argv[0], pathlib.Path(argv[1]), pathlib.Path(argv[2])
    print(make_slim(field, src, out, noev))
