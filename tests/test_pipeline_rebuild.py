"""The rebuild-comparison harness (M3 Task 3) and its first real proof.

Two halves, and the first one exists to make the second one worth believing:

1. **Falsifiability of `tools/content_equal.py`.** M3's acceptance criterion (plan deviation **D1**)
   is *content*-equality for parquet, because byte-equality is physically unreachable for the frozen
   frames: the legacy builders set `preserve_insertion_order=false` on a parallel `COPY` with no
   outer `ORDER BY`, so row order moves with the core count (not one of the 9 frozen parquets is
   sorted), and the frozen econ slim is SNAPPY/int64 while chem/math are ZSTD/int32. A weaker gate
   is only honest if it still fails on a real difference, so every way a rebuild could be wrong -
   a flipped value, a missing/extra/duplicated row, a renamed column, a changed dtype, NULL for
   empty string, one ULP of float - is tested here to FAIL.
2. **The first real rebuild.** `p3_afar_math_stats.parquet` is the cheapest frame in the set
   (44,706 rows from a 326 KB parquet plus two repo CSVs, no SSD needed). It is rebuilt with the
   already-ported builder into a temp directory routed through the Task-2 write barrier, and
   compared with the harness against the frozen copy in `data/frames/`. (2026-09-23: `data/frames/` is
   the October caliber; the copy this 08-28 rebuild is compared with is the 2026-08-28 one, frozen at
   `data/cal2026-08-28/frames/` — see the T7 block comment.)

Fixtures are generated under pytest's `tmp_path` - never inside the repo tree.
"""
from __future__ import annotations

import collections
import dataclasses
import hashlib
import json
import os
import pathlib
import struct
import sys
import time
import warnings

import duckdb
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from analysis.lib.paths import load_paths                                    # noqa: E402
from tools.content_equal import (                                            # noqa: E402
    ContentEqualError, MissingArtifact, Result, UnreadableArtifact, content_equal,
)

P = load_paths()


# --------------------------------------------------------------------------------------------
# fixtures helpers
# --------------------------------------------------------------------------------------------

def _pq(path: pathlib.Path, sql: str, compression: str = "ZSTD") -> pathlib.Path:
    """Write `sql`'s result to `path` as parquet. Fixtures only; never touches the repo tree."""
    duckdb.connect().execute(
        f"COPY ({sql}) TO '{path}' (FORMAT PARQUET, COMPRESSION {compression})")
    return path


ROWS = "SELECT * FROM (VALUES (1, 2000, 0), (1, 2001, 1), (2, 2000, 0)) t(grp, year, y)"


# --------------------------------------------------------------------------------------------
# 1. parquet: the content path
# --------------------------------------------------------------------------------------------

def test_case1_identical_parquet_is_equal_in_content_mode(tmp_path):
    a, b = _pq(tmp_path / "a.parquet", ROWS), _pq(tmp_path / "b.parquet", ROWS)
    r = content_equal(a, b)
    assert isinstance(r, Result)
    assert r.equal is True and r.mode == "content"
    assert (r.rows_a, r.rows_b, r.only_in_a, r.only_in_b) == (3, 3, 0, 0)
    assert r.schema_equal is True
    assert "VERDICT: EQUAL" in r.detail


def test_case2_one_flipped_value_is_not_equal_and_the_detail_names_it(tmp_path):
    a = _pq(tmp_path / "a.parquet", ROWS)
    b = _pq(tmp_path / "b.parquet",
            "SELECT * FROM (VALUES (1, 2000, 0), (1, 2001, 1), (2, 2000, 1)) t(grp, year, y)")
    r = content_equal(a, b)
    assert r.equal is False and r.mode == "content"
    assert (r.only_in_a, r.only_in_b) == (1, 1)
    assert "(2, 2000, 0)" in r.detail and "(2, 2000, 1)" in r.detail, (
        "the detail must show the differing rows, not only their count:\n" + r.detail)
    assert "VERDICT: NOT EQUAL" in r.detail


def test_case3_same_rows_in_a_different_order_are_equal(tmp_path):
    """The whole point of D1: the frozen parquets are unsorted, so row order cannot be a verdict."""
    a = _pq(tmp_path / "a.parquet", ROWS)
    b = _pq(tmp_path / "b.parquet",
            "SELECT * FROM (VALUES (2, 2000, 0), (1, 2001, 1), (1, 2000, 0)) t(grp, year, y)")
    assert content_equal(a, b).equal is True


def test_case4_duplicate_row_multiset_semantics(tmp_path):
    """`EXCEPT ALL` is a multiset difference; plain `EXCEPT` would call both of these equal."""
    a = _pq(tmp_path / "a.parquet", "SELECT * FROM (VALUES (1),(1),(2)) t(grp)")
    b = _pq(tmp_path / "b.parquet", "SELECT * FROM (VALUES (1),(2)) t(grp)")
    r = content_equal(a, b)
    assert r.equal is False and (r.rows_a, r.rows_b) == (3, 2) and (r.only_in_a, r.only_in_b) == (1, 0)

    # same row COUNT, different multiplicities - the case a row count alone cannot see
    c = _pq(tmp_path / "c.parquet", "SELECT * FROM (VALUES (1),(2),(2)) t(grp)")
    r2 = content_equal(a, c)
    assert r2.equal is False and (r2.rows_a, r2.rows_b) == (3, 3) and (r2.only_in_a, r2.only_in_b) == (1, 1)


# --------------------------------------------------------------------------------------------
# 2. schema: the documented rule
# --------------------------------------------------------------------------------------------

def test_case5a_renamed_column_is_reported_and_not_equal(tmp_path):
    a = _pq(tmp_path / "a.parquet", ROWS)
    b = _pq(tmp_path / "b.parquet",
            "SELECT * FROM (VALUES (1, 2000, 0), (1, 2001, 1), (2, 2000, 0)) t(grp, yr, y)")
    r = content_equal(a, b)
    assert r.equal is False and r.schema_equal is False
    assert any("year" in d for d in r.schema_diff) and any("yr" in d for d in r.schema_diff)
    assert r.only_in_a is None and r.only_in_b is None, (
        "with different column sets there is no honest row comparison to run - it must be reported "
        "as skipped, never silently run on the intersection")
    assert "column sets differ" in r.detail


def test_case5b_dtype_change_is_reported_and_not_equal_even_though_the_rows_match(tmp_path):
    """The load-bearing case. DuckDB widens INTEGER to BIGINT inside `EXCEPT ALL`, so the row
    comparison sees NOTHING - both directions return 0. A dtype difference between a rebuild and
    its own frozen counterpart is a finding (recon H2), so the schema is part of the verdict."""
    a = _pq(tmp_path / "a.parquet", "SELECT 1::BIGINT AS grp, 2000::INTEGER AS year")
    b = _pq(tmp_path / "b.parquet", "SELECT 1::INTEGER AS grp, 2000::INTEGER AS year")
    r = content_equal(a, b)
    assert (r.only_in_a, r.only_in_b) == (0, 0), "sanity: the rows really do compare equal"
    assert r.equal is False and r.schema_equal is False
    assert any("grp" in d and "BIGINT" in d and "INTEGER" in d for d in r.schema_diff)
    assert "schema: DIFFERENT" in r.detail


def test_case5c_extra_column_is_reported_and_not_equal(tmp_path):
    a = _pq(tmp_path / "a.parquet", ROWS)
    b = _pq(tmp_path / "b.parquet",
            "SELECT *, 9 AS extra FROM (VALUES (1, 2000, 0), (1, 2001, 1), (2, 2000, 0)) t(grp, year, y)")
    r = content_equal(a, b)
    assert r.equal is False and r.schema_equal is False
    assert any("extra" in d for d in r.schema_diff)


def test_case5d_column_order_alone_is_reported_and_not_equal(tmp_path):
    a = _pq(tmp_path / "a.parquet", "SELECT 1 AS grp, 2000 AS year")
    b = _pq(tmp_path / "b.parquet", "SELECT 2000 AS year, 1 AS grp")
    r = content_equal(a, b)
    assert (r.only_in_a, r.only_in_b) == (0, 0), "the projection is by NAME, so the rows match"
    assert r.equal is False and any("order" in d for d in r.schema_diff)


# --- the one documented, opt-in axis: a caller-declared column TYPE change -------------------

def test_case5e_a_declared_type_change_is_the_only_accepted_schema_difference(tmp_path):
    a = _pq(tmp_path / "a.parquet", "SELECT 1::BIGINT AS grp, 2000::INTEGER AS year")
    b = _pq(tmp_path / "b.parquet", "SELECT 1::INTEGER AS grp, 2000::INTEGER AS year")
    r = content_equal(a, b, accept_type_change=[("grp", "BIGINT", "INTEGER")])
    assert r.equal is True
    assert r.accepted_schema_diff and "grp" in r.accepted_schema_diff[0]
    assert "SCHEMA DIFFERENCE ACCEPTED BY CALLER" in r.detail, (
        "an accepted difference must stay visible in the Result, never disappear")


def test_case5f_a_declared_type_change_still_catches_a_real_difference_on_that_axis(tmp_path):
    """Naming an axis as harmless must not blind the harness on that axis."""
    a = _pq(tmp_path / "a.parquet", "SELECT 7::BIGINT AS grp, 2000::INTEGER AS year")
    b = _pq(tmp_path / "b.parquet", "SELECT 8::INTEGER AS grp, 2000::INTEGER AS year")
    accept = [("grp", "BIGINT", "INTEGER")]
    r = content_equal(a, b, accept_type_change=accept)
    assert r.equal is False and (r.only_in_a, r.only_in_b) == (1, 1)

    # ... and the acceptance is scoped to the declared column: a type change elsewhere still fails
    c = _pq(tmp_path / "c.parquet", "SELECT 7::BIGINT AS grp, 2000::BIGINT AS year")
    d = _pq(tmp_path / "d.parquet", "SELECT 7::INTEGER AS grp, 2000::INTEGER AS year")
    r2 = content_equal(c, d, accept_type_change=accept)
    assert r2.equal is False and any("year" in x for x in r2.schema_diff)

    # ... and it can never cover a rename or an extra column
    e = _pq(tmp_path / "e.parquet", "SELECT 7::BIGINT AS grp")
    f = _pq(tmp_path / "f.parquet", "SELECT 7::INTEGER AS grp2")
    assert content_equal(e, f, accept_type_change=[("grp", "BIGINT", "INTEGER")]).equal is False
    with pytest.raises(ContentEqualError):
        content_equal(a, b, accept_type_change=[("grp", "BIGINT")])          # malformed declaration


# --------------------------------------------------------------------------------------------
# 3. NULLs and floats
# --------------------------------------------------------------------------------------------

def test_case6_null_handling(tmp_path):
    """Correct = NULL equals NULL (SQL set operations are NOT DISTINCT FROM, and a frozen frame's
    NULLs must survive a rebuild as NULLs), while NULL differs from the empty string and from any
    value. "Missing" and "present but empty" are different facts about the data."""
    a = _pq(tmp_path / "a.parquet", "SELECT 1 AS grp, NULL::VARCHAR AS note")
    b = _pq(tmp_path / "b.parquet", "SELECT 1 AS grp, NULL::VARCHAR AS note")
    assert content_equal(a, b).equal is True                                   # NULL == NULL

    c = _pq(tmp_path / "c.parquet", "SELECT 1 AS grp, ''::VARCHAR AS note")
    r = content_equal(a, c)
    assert r.equal is False and (r.only_in_a, r.only_in_b) == (1, 1)           # NULL != ''

    # a column that is all-NULL on one side and populated on the other
    d = _pq(tmp_path / "d.parquet",
            "SELECT * FROM (VALUES (1, NULL), (2, NULL)) t(grp, note)")
    e = _pq(tmp_path / "e.parquet",
            "SELECT * FROM (VALUES (1, 'x'), (2, 'y')) t(grp, note)")
    r2 = content_equal(d, e)
    assert r2.equal is False and (r2.only_in_a, r2.only_in_b) == (2, 2)


def test_case7_float_precision_has_no_tolerance(tmp_path):
    x = 0.1
    x_ulp = struct.unpack("<d", struct.pack("<Q", struct.unpack("<Q", struct.pack("<d", x))[0] + 1))[0]
    assert x != x_ulp and abs(x - x_ulp) < 1e-16                                # one ULP apart
    a = _pq(tmp_path / "a.parquet", f"SELECT {x!r}::DOUBLE AS v")
    b = _pq(tmp_path / "b.parquet", f"SELECT {x!r}::DOUBLE AS v")
    c = _pq(tmp_path / "c.parquet", f"SELECT {x_ulp!r}::DOUBLE AS v")
    assert content_equal(a, b).equal is True                                    # bit-identical
    assert content_equal(a, c).equal is False                                   # one ULP -> caught


def test_case7b_signed_zero_is_caught_and_nan_still_round_trips(tmp_path):
    """T3 review MAJOR-3. `EXCEPT ALL` compares floats with IEEE-754 equality, under which
    `-0.0 = 0.0` is TRUE although the stored bytes differ — a real hole in "no tolerance anywhere".
    It is closed by an explicit zero-sign companion expression, not by a warning. `NaN = NaN` stays
    equal on purpose: a NaN must survive a rebuild round-trip."""
    nan_a = _pq(tmp_path / "n1.parquet", "SELECT 'NaN'::DOUBLE AS v")
    nan_b = _pq(tmp_path / "n2.parquet", "SELECT 'NaN'::DOUBLE AS v")
    assert content_equal(nan_a, nan_b).equal is True

    # (a) a DuckDB-written negative zero
    z_pos = _pq(tmp_path / "z1.parquet", "SELECT 0.0::DOUBLE AS v")
    z_neg = _pq(tmp_path / "z2.parquet", "SELECT -0.0::DOUBLE AS v")
    assert z_pos.read_bytes() != z_neg.read_bytes(), "the stored bytes really do differ"
    r = content_equal(z_pos, z_neg)
    assert r.equal is False and (r.only_in_a, r.only_in_b) == (1, 1)
    assert r.float_columns == ("v",) and "float column(s) present" in r.detail

    # (b) the reviewer's construction: a genuine pyarrow negative zero, and DuckDB's own writer
    #     preserving the sign on round-trip
    import pyarrow as pa, pyarrow.parquet as pq
    ap = tmp_path / "pa_neg.parquet"; bp = tmp_path / "pa_pos.parquet"
    pq.write_table(pa.table({"v": pa.array([-0.0, 1.5], pa.float64())}), ap)
    pq.write_table(pa.table({"v": pa.array([0.0, 1.5], pa.float64())}), bp)
    assert content_equal(ap, bp).equal is False, "a genuine -0.0 must not read as 0.0"
    rt = _pq(tmp_path / "rt.parquet", f"SELECT v FROM read_parquet('{ap}')")
    assert content_equal(rt, ap).equal is True and content_equal(rt, bp).equal is False, \
        "DuckDB's writer preserves the sign bit, so a rebuild really can carry a -0.0 through"

    # (c) the harness must still catch an ordinary value difference in a float column
    v1 = _pq(tmp_path / "v1.parquet", "SELECT 1.5::DOUBLE AS v")
    v2 = _pq(tmp_path / "v2.parquet", "SELECT 1.5000000000000002::DOUBLE AS v")
    assert content_equal(v1, v2).equal is False


def test_every_float_column_M3_will_compare_carries_the_note(tmp_path):
    """T3 review MAJOR-3. The old guard globbed `data/frames/` only and asserted "no float columns
    anywhere", so it could not fire for the artifact the plan's Task 4 compares: the FWCI expected
    table has `expected_citations DOUBLE` with 60,504 of 130,061 rows exactly zero. This inventories
    every parquet M3 points the harness at and requires the float caveat to appear in the evidence
    of any comparison that touches one."""
    targets = sorted(P["frames"].glob("*.parquet")) + sorted(P["raw_verified"].glob("*.parquet"))
    fwci = (P["legacy_v2_output"] / "fwci_fullsnapshot_rebuild_2026-08-09/data"
            / "fwci_expected_fullsnapshot_2026-08-09.parquet")
    if fwci.exists():
        targets.append(fwci)
    assert targets, "no artifacts found to inventory"
    con = duckdb.connect()
    with_floats = []
    for f in targets:
        types = {t for _, t, *_ in con.execute("DESCRIBE SELECT * FROM read_parquet(?)",
                                               [str(f)]).fetchall()}
        if types & {"FLOAT", "DOUBLE", "REAL"}:
            with_floats.append(f)
    print(f"\n[float inventory] {len(targets)} artifacts scanned, "
          f"{len(with_floats)} with float columns: {[f.name for f in with_floats]}")
    for f in with_floats:
        r = content_equal(f, f)
        assert r.equal and r.float_columns, f"{f.name}: float columns not reported"
        assert "float column(s) present" in r.detail, f"{f.name}: the float caveat did not fire"


# --------------------------------------------------------------------------------------------
# 4. CSV / text: the byte path
# --------------------------------------------------------------------------------------------

def test_case8_csv_is_compared_byte_for_byte_and_crlf_is_never_normalised(tmp_path):
    """The old79/new38 splitter emits CRLF while its parent frame is LF (recon H3). Normalising
    line endings would hide exactly the difference the replication package must show."""
    a = tmp_path / "a.csv"; a.write_bytes(b"event_id,y\r\nE1,1\r\nE2,0\r\n")
    b = tmp_path / "b.csv"; b.write_bytes(b"event_id,y\r\nE1,1\r\nE2,0\r\n")
    r = content_equal(a, b)
    assert r.equal is True and r.mode == "bytes"
    assert r.sha256_a == r.sha256_b == hashlib.sha256(a.read_bytes()).hexdigest()

    c = tmp_path / "c.csv"; c.write_bytes(b"event_id,y\nE1,1\nE2,0\n")
    r2 = content_equal(a, c)
    assert r2.equal is False and r2.mode == "bytes"
    assert "first difference at byte 10" in r2.detail
    assert "CRLF" in r2.detail, "the line-ending difference must be named:\n" + r2.detail


# --------------------------------------------------------------------------------------------
# 5. degenerate inputs: an error, never a pass
# --------------------------------------------------------------------------------------------

def test_case9_empty_and_missing_files(tmp_path):
    e1 = tmp_path / "e1.csv"; e1.write_bytes(b"")
    e2 = tmp_path / "e2.csv"; e2.write_bytes(b"")
    r = content_equal(e1, e2)
    assert r.equal is True and r.mode == "bytes" and (r.size_a, r.size_b) == (0, 0)
    assert "EMPTY" in r.detail, "two empty files are byte-equal, but that must be visible"

    good = tmp_path / "g.csv"; good.write_bytes(b"a\n")
    with pytest.raises(MissingArtifact):
        content_equal(tmp_path / "nope.csv", good)
    with pytest.raises(MissingArtifact):
        content_equal(good, tmp_path / "nope.csv")
    with pytest.raises(ContentEqualError):
        content_equal(tmp_path, good)                                          # a directory

    # an empty file that CLAIMS to be parquet is unreadable, not equal-to-another-empty-file
    z1 = tmp_path / "z1.parquet"; z1.write_bytes(b"")
    z2 = tmp_path / "z2.parquet"; z2.write_bytes(b"")
    with pytest.raises(UnreadableArtifact):
        content_equal(z1, z2)

    with pytest.raises(ContentEqualError):                                     # apples vs oranges
        content_equal(good, _pq(tmp_path / "p.parquet", ROWS))


def test_a_result_is_falsy_when_it_is_not_equal(tmp_path):
    """`assert content_equal(a, b)` must not pass on a truthy dataclass - the one way a harness
    like this silently stops testing anything."""
    a = _pq(tmp_path / "a.parquet", ROWS)
    b = _pq(tmp_path / "b.parquet", "SELECT * FROM (VALUES (9, 1999, 1)) t(grp, year, y)")
    assert not content_equal(a, b)
    assert bool(content_equal(a, a)) is True


# --------------------------------------------------------------------------------------------
# 6. the first real rebuild proof
# --------------------------------------------------------------------------------------------

def _skip_loudly(reason: str):
    """A skipped rebuild proof is a finding, not a pass: print it and warn before skipping so it is
    visible in the run's output and not just as a dot (plan Task 7 Step 2)."""
    msg = f"REBUILD PROOF NOT EXECUTED: {reason}"
    print("\n*** " + msg)
    warnings.warn(msg, stacklevel=2)
    pytest.skip(msg)


def test_the_write_barrier_refuses_the_frozen_frames_directory():
    """The route the rebuild takes. `data/frames/` holds the frozen artifacts the comparison reads;
    a builder must be incapable of writing there, and this is the mechanism that stops it."""
    from pipeline.lib.paths import WriteBarred, output_target
    with pytest.raises(WriteBarred):
        output_target(P["frames"], what="a rebuild")


def test_p3_afar_math_stats_rebuild_is_content_equal_to_the_frozen_frame(tmp_path, monkeypatch):
    """M3's cheapest acceptance proof (recon §7 Tier 0): rebuild the smallest frame with the
    already-ported builder and compare it with the frozen copy under the D1 criterion."""
    import analysis.robustness.p3_afar.build_afar as _ba
    from analysis.robustness.p3_afar.build_afar import SOURCES, build_afar
    from pipeline.lib.paths import output_target

    # 2026-09-23: data/frames/ is the October caliber (cal2026-10). build_afar.py's proof is the 2026-08-28
    # caliber — its SOURCES read the 08-28 pair table — so its P1/P2 inputs are the 08-28 copies of the frames
    # SOURCES resolves in data/frames/ (data/cal2026-08-28/frames/, same names: the bytes data/frames/ held
    # until the promotion) and the frozen operand is the 08-28 frame there (tag cal-2026-08-28). The builder
    # is untouched; only its source map is re-pointed for this test.
    cal = REPO / "data" / "cal2026-08-28" / "frames"
    src = SOURCES(P)[field := "math_stats"]
    assert src["pairs"] == cal / f"pairs_none_{field}.parquet"        # the shipped builder reads the 08-28 table
    src = {**src, "frame": cal / f"p1_frame_{field}.csv", "p2": cal / f"p2_becoming_{field}.csv"}
    for name, path in src.items():
        if not pathlib.Path(path).exists():
            _skip_loudly(f"input '{name}' is not on this machine: {path}")
    monkeypatch.setattr(_ba, "SOURCES", lambda p, _s=src: {field: _s})

    frozen = cal / f"p3_afar_{field}.parquet"
    before = (hashlib.sha256(frozen.read_bytes()).hexdigest(), frozen.stat().st_mtime_ns)

    out_dir = output_target(tmp_path / "afar_rebuild", what="build_afar")       # write barrier
    t0 = time.time()
    stats = build_afar(field, out_dir=out_dir)
    secs = time.time() - t0

    rebuilt = pathlib.Path(out_dir) / f"p3_afar_{field}.parquet"
    r = content_equal(rebuilt, frozen)
    print(f"\n[rebuild] p3_afar_{field}: {secs:.1f}s  {stats}\n{r.detail}")

    assert r.equal, f"REBUILD DIFFERS FROM THE FROZEN FRAME - stop, do not adjust:\n{r.detail}"
    assert r.mode == "content" and r.schema_equal is True and r.accepted_schema_diff == ()
    assert (r.rows_a, r.rows_b) == (46010, 46010)                # caliber canon (freeze 2026-08-28)
    assert (stats["pairs"], stats["ties"]) == (2770, 106)                       # data/cal2026-08-28/frames/p3_afar_counts.csv
    assert (hashlib.sha256(frozen.read_bytes()).hexdigest(), frozen.stat().st_mtime_ns) == before, \
        "the frozen frame was modified by the rebuild"


# --------------------------------------------------------------------------------------------
# 7. T3 review fix wave — each test reproduces a finding and pins its fix
# --------------------------------------------------------------------------------------------

def test_review_major1_a_glob_metacharacter_in_a_filename_cannot_produce_a_verdict(tmp_path):
    """MAJOR-1, the one genuine false EQUAL. `read_parquet` GLOB-expands its argument, so
    `t[ab].parquet` (holding 999) read as EQUAL to a frozen file (holding 1, 1) because two decoys
    matched. The exact reviewer fixture, rebuilt: it must now raise, not answer."""
    d = tmp_path / "globdemo"; d.mkdir()
    _pq(d / "ta.parquet", "SELECT 1 AS v")
    _pq(d / "tb.parquet", "SELECT 1 AS v")
    _pq(d / "t[ab].parquet", "SELECT 999 AS v")
    frozen = _pq(tmp_path / "frozen.parquet", "SELECT * FROM (VALUES (1),(1)) t(v)")
    assert (d / "t[ab].parquet").is_file() and frozen.is_file()
    with pytest.raises(ContentEqualError, match="glob"):
        content_equal(d / "t[ab].parquet", frozen)
    with pytest.raises(ContentEqualError, match="glob"):                 # and on a self-compare
        content_equal(d / "t[ab].parquet", d / "t[ab].parquet")
    # a plain filename in the same directory is unaffected
    assert content_equal(d / "ta.parquet", d / "tb.parquet").equal is True


def test_t3_final_N2_a_single_glob_match_that_is_a_DIFFERENT_file_is_refused(tmp_path):
    """T3 FINAL review, surviving mutant N2. `_assert_single_file` has two conditions - "exactly one
    file matched" AND "that file IS the one named" - and no test exercised the second, so deleting
    `or not same` left the suite green. This is the branch: DuckDB's glob reads `[!b]` as "one
    character that is not b", so `a[!b].parquet` matches the DECOY `ax.parquet` and does NOT match
    itself. One file comes back, it holds 999 rather than 1, and the count check alone would let the
    comparison run against the wrong file's contents."""
    d = tmp_path / "n2"; d.mkdir()
    _pq(d / "ax.parquet", "SELECT 999 AS v")
    _pq(d / "a[!b].parquet", "SELECT 1 AS v")
    named = d / "a[!b].parquet"
    assert named.is_file(), "the named file really is on disk"

    # the branch's premise, asserted rather than assumed: ONE match, and it is the decoy
    con = duckdb.connect()
    matched = [r[0] for r in con.execute(
        "SELECT file_name FROM parquet_file_metadata(?)", [str(named)]).fetchall()]
    assert len(matched) == 1, matched
    assert pathlib.Path(matched[0]).resolve() != named.resolve(), matched

    frozen = _pq(tmp_path / "n2_frozen.parquet", "SELECT 1 AS v")
    with pytest.raises(ContentEqualError, match="glob"):
        content_equal(named, frozen)
    with pytest.raises(ContentEqualError, match="glob"):
        content_equal(frozen, named)
    with pytest.raises(ContentEqualError, match="glob"):
        content_equal(named, named)
    # and the decoy the glob DID match holds different data, so a count-only guard would have
    # answered NOT EQUAL here and EQUAL for the pair below - a verdict about the wrong file either way
    assert content_equal(d / "ax.parquet", _pq(tmp_path / "dec.parquet", "SELECT 999 AS v")).equal


# --------------------------------------------------------------------------------------------
# 8. T4 - the FWCI expected table: a real pipeline stage re-executed and checked
# --------------------------------------------------------------------------------------------

FWCI_FROZEN = "fwci_expected_fullsnapshot_2026-08-09.parquet"
FWCI_FROZEN_OLD = "fwci_expected_oldpop_2026-08-09.parquet"
FWCI_RUN_DIR = "output/fwci/fwci_fullsnapshot_rebuild_2026-08-09/data"
#: pinned from data/MANIFEST.sha256 - a rebuild must not be able to change it
FWCI_FROZEN_SHA = "1fc323a37dc78f227885bb3d245769c2ee593fe39bf46e1e5de8a0ff19603dfe"


#: T8: the legacy half of this gate is gone. The builder's NEWPOP input is now served from the
#: repository's own frozen copy through `run_fwci.py`'s `$SAR_LEGACY_THESIS` shim, so `build` needs
#: only the data disk - for OLDPOP, the 514 MB pre-rebuild population, which is NOT frozen (it is
#: the one input in this stage the package does not ship).
needs_fwci_inputs = pytest.mark.skipif(
    not P["ssd_root"].is_dir(),
    reason="the ported builder reads the 514 MB pre-rebuild pop from the data disk (OLDPOP is the "
           "one input this stage needs that the package does not ship)")


@needs_fwci_inputs
def test_t8_the_fwci_build_reads_its_NEWPOP_from_the_frozen_repo_copy(fwci_rebuild):
    """The T4 review's carried item. `01_build_expected_full.py:45` builds NEWPOP as
    `f"{ROOT}/v2_output/.../fwci_baseline_pop_full.parquet"` — an f-string carrying no absolute path
    of its own, so the port could resolve only `ROOT` and the stage needed the author's read-only
    thesis tree for a file this package already ships, sha256-pinned, in `data/fwci/`.

    The launcher now stages a one-file shadow of the legacy layout, hard-links the FROZEN parquet
    in, checks its hash against `data/MANIFEST.sha256` before handing it over, and points
    `$SAR_LEGACY_THESIS` at it. Three claims: the run says so, the run RECORD names the shim (so the
    provenance is not a story), and the shimmed file is the manifest-pinned one.
    """
    r, _elapsed = fwci_rebuild
    assert r.returncode == 0, r.stdout + r.stderr
    assert "NEWPOP <- data/fwci/fwci_baseline_pop_full.parquet" in r.stdout, r.stdout[-3000:]

    record = json.loads((REPO / FWCI_RUN_DIR / "g_step1_expected.json").read_text())
    shim = pathlib.Path(record["source_new_pop"])
    assert "_frozen_legacy_thesis" in shim.parts, record["source_new_pop"]
    assert shim.is_file()
    frozen = P["fwci"] / "fwci_baseline_pop_full.parquet"
    assert hashlib.sha256(shim.read_bytes()).hexdigest() == \
        hashlib.sha256(frozen.read_bytes()).hexdigest()
    # and the shim is refused if the frozen copy stops matching its manifest line
    assert f"{hashlib.sha256(frozen.read_bytes()).hexdigest()}  data/fwci/" \
        f"fwci_baseline_pop_full.parquet" in (REPO / "data/MANIFEST.sha256").read_text()


@pytest.fixture(scope="module")
def fwci_rebuild():
    """Run the build stage ONCE for this module. A fixture rather than a test-order dependency:
    the byte-identity observation below must not silently skip because it was run on its own."""
    import subprocess
    t0 = time.time()
    r = subprocess.run([sys.executable, str(REPO / "pipeline/fwci/run_fwci.py"), "build"],
                       cwd=REPO, capture_output=True, text=True)
    return r, time.time() - t0


@needs_fwci_inputs
def test_t4_the_fwci_expected_table_rebuilds_equal_to_the_frozen_one(fwci_rebuild):
    """M3 Task 4, the first ported pipeline STAGE this repo re-executes end to end.

    `pipeline/fwci/.../01_build_expected_full.py` folds the 543,037-cell full-snapshot population
    into the 130,061-cell expected table that every frozen P1 frame's FWCI denominator comes from.
    It is run through `pipeline/fwci/run_fwci.py`, which stages it into the git-ignored `output/`
    tree via `output_target()` - the ported script computes its own destination from `__file__`, a
    line carrying no absolute path and therefore untouchable, so the file is moved rather than the
    constant. Both of its parquet outputs are then compared with the frozen copies in `data/fwci/`.

    The frozen artifacts are hashed before and after: a rebuild must never touch them.
    """
    frozen = P["fwci"] / FWCI_FROZEN
    frozen_old = P["fwci"] / FWCI_FROZEN_OLD
    r, elapsed = fwci_rebuild
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout, r.stdout

    rebuilt = REPO / FWCI_RUN_DIR / FWCI_FROZEN
    rebuilt_old = REPO / FWCI_RUN_DIR / FWCI_FROZEN_OLD
    assert rebuilt.is_file() and rebuilt_old.is_file(), sorted(
        p.name for p in (REPO / FWCI_RUN_DIR).glob("*")) if (REPO / FWCI_RUN_DIR).is_dir() else "no run dir"

    res = content_equal(rebuilt, frozen)
    print(f"\n[T4 fwci build] {elapsed:.1f}s  mode={res.mode}  rows={res.rows_a:,}\n{res.detail}")
    assert res.equal, res.detail
    assert res.rows_a == res.rows_b == 130_061, (res.rows_a, res.rows_b)
    assert res.float_columns == ("expected_citations",), res.float_columns
    assert "float column(s) present" in res.detail, res.detail

    res_old = content_equal(rebuilt_old, frozen_old)
    assert res_old.equal, res_old.detail
    assert res_old.rows_a == 43_175, res_old.rows_a

    # the caliber the table encodes, asserted on the rebuilt file rather than quoted from a report:
    # 60,504 of the 130,061 cells are exactly zero, and compute_fwci maps those to NA, never 0.
    zeros = duckdb.connect().execute(
        "SELECT count(*) FROM read_parquet(?) WHERE expected_citations = 0", [str(rebuilt)]
    ).fetchone()[0]
    assert zeros == 60_504, zeros

    # the frozen artifacts must be untouched. Hashed here rather than around the subprocess because
    # the fixture is module-scoped: the manifest is re-verified by tests/test_manifest.py in the
    # same run, which is the stronger check (it covers all 72 frozen files, not these two).
    assert hashlib.sha256(frozen.read_bytes()).hexdigest() == FWCI_FROZEN_SHA, \
        "the rebuild modified the frozen expected table"


@needs_fwci_inputs
def test_t4_the_fwci_rebuild_is_byte_identical_too_and_that_is_recorded_not_assumed(fwci_rebuild):
    """A finding worth pinning, because it is the OPPOSITE of what D1 measured for the frames.

    The nine frozen frame parquets cannot be reproduced byte for byte - the legacy builders write
    them with `preserve_insertion_order=false` on a parallel COPY, so row order moves with the core
    count, and seven rebuilds of `p3_afar_math_stats` gave seven different sha256s. The FWCI builder
    does not do that: a single `COPY ... TO` over a table built with an explicit `ORDER BY`. So this
    one artifact IS bit-reproducible, and the stronger claim is available here.

    It is asserted as an OBSERVATION and never as the acceptance criterion: `content_equal` above is
    what decides, exactly as D1 requires, so if a future DuckDB changes the encoding this test fails
    while the acceptance proof still stands.
    """
    r, _elapsed = fwci_rebuild
    assert r.returncode == 0, r.stdout + r.stderr
    rebuilt = REPO / FWCI_RUN_DIR / FWCI_FROZEN
    frozen = P["fwci"] / FWCI_FROZEN
    a = hashlib.sha256(rebuilt.read_bytes()).hexdigest()
    b = hashlib.sha256(frozen.read_bytes()).hexdigest()
    assert a == b, (
        f"the FWCI expected table is no longer bit-reproducible ({a} vs {b}). This is an OBSERVATION, "
        f"not the acceptance criterion - check the content_equal proof above before treating it as a "
        f"defect, and record the change.")
    assert rebuilt.stat().st_size == frozen.stat().st_size == 633_092


def test_t4_the_frozen_fwci_set_is_present_hashed_and_the_expected_table_self_compares():
    """The freeze itself: the artifacts the funnel numbers depend on are in the repo, not only in a
    read-only tree on the author's machine."""
    expect = {
        "fwci_baseline_pop_full.parquet": (4_143_092, 543_037),
        "fwci_expected_fullsnapshot_2026-08-09.parquet": (633_092, 130_061),
        "fwci_expected_oldpop_2026-08-09.parquet": (416_619, 43_175),
        "econ_units_2026-08-09.parquet": (2_062_404, 160_437),
    }
    manifest = (REPO / "data/MANIFEST.sha256").read_text()
    con = duckdb.connect()
    for name, (size, rows) in expect.items():
        f = P["fwci"] / name
        assert f.is_file(), f"{name} is not frozen"
        assert f.stat().st_size == size, (name, f.stat().st_size)
        assert con.execute("SELECT count(*) FROM read_parquet(?)", [str(f)]).fetchone()[0] == rows
        line = f"{hashlib.sha256(f.read_bytes()).hexdigest()}  data/fwci/{name}"
        assert line in manifest, f"{name} is not pinned in data/MANIFEST.sha256"
    for name in ("scan_manifest.json", "gate_a_reconcile.json", "gate_b_cell_recount.json",
                 "g_step1_expected.json", "g_c_old_vs_new.json"):
        assert (P["fwci"] / name).is_file(), f"{name} (the run record / audit verdict) is not frozen"
    # the scan's own reconciliation, read from the frozen record rather than restated in prose
    import json
    rec = json.loads((P["fwci"] / "scan_manifest.json").read_text())
    assert rec["total_lines_read"] == rec["manifest_record_count"] == 510_372_821
    assert rec["bad_lines"] == 0 and rec["shard_read_mismatches"] == 0 and rec["shards"] == 2_446
    assert rec["n_cells"] == 543_037 and rec["snapshot_manifest_date"] == "2026-06-26"


def test_t4_review_minor5_the_paper_funnel_reads_the_FROZEN_fwci_records_not_the_legacy_tree():
    """T4 review MINOR-5. Freezing the scan records bought nothing while the only consumer still read
    the legacy tree: the paper's funnel numbers continued to require the author's machine. The ledger
    now reads `data/fwci/`, and this pins both halves - that it points there, and that the numbers
    did not move (they cannot: the frozen files are byte-identical to the legacy originals)."""
    from analysis.paper import ledger_funnel
    src = pathlib.Path(ledger_funnel.__file__).read_text(encoding="utf-8")
    assert 'FW = P["fwci"]' in src, (
        "ledger_funnel no longer reads the frozen FWCI records - the freeze is inert again")
    assert "legacy_v2_output" not in src.split("FW = ", 1)[1].split("\n", 1)[0]

    if not (P["legacy_v2_output"].is_dir() and P["legacy_multiplex"].is_dir()):
        pytest.skip("author-only: ledger_funnel.build() also reads the private legacy trees")
    out = ledger_funnel.build()
    for key, want in ledger_funnel.THESIS_VALUES.items():
        if isinstance(want, int):
            assert out[key] == want, (key, out[key], want)
    assert out["works_snapshot"] == 510_372_821 and out["benchmark_cells"] == 543_037
    # and the provenance strings still name the manifests they came from
    assert "scan_manifest.json" in out["_provenance"]["works_snapshot"]


def test_t4_review_minor6_econ_units_is_registered_as_having_no_ported_producer():
    """T4 review MINOR-6. A frozen artifact whose producer is neither ported nor run belongs in the
    register whose job is 'what did not run', and in the data README a replicator reads first."""
    reg = (REPO / "pipeline/NOT_REPRODUCIBLE.md").read_text(encoding="utf-8")
    assert "econ_units_2026-08-09.parquet" in reg, "econ_units is not in NOT_REPRODUCIBLE.md"
    # T8 added an index table to the register, so "the first mention" is now the index row. Take the
    # ENTRY - the section under its own heading - which is the stronger thing to check anyway.
    # Entries are `## N. CATEGORY — <artifact>` sections.
    headings = [h for h in reg.split("\n## ")
                if h.split("\n", 1)[0].endswith("`econ_units_2026-08-09.parquet`")]
    assert len(headings) == 1, "econ_units has no entry heading of its own in the register"
    entry = headings[0]
    assert "03_econ_anchor_test.py" in entry, "the register does not name the missing producer"
    assert "3950cec3ed2c2b82a2a66b4dc3102c50dd58ada01da897890c8980f4b9b7572e" in entry
    assert "check instead" in entry.lower(), "an entry must say what a replicator can check instead"
    data_readme = (REPO / "data/fwci/README.md").read_text(encoding="utf-8")
    row = [ln for ln in data_readme.splitlines() if "econ_units" in ln and ln.startswith("|")]
    assert row, "econ_units has no row in data/fwci/README.md"
    assert "03_econ_anchor_test.py" in row[0] and "NOT_REPRODUCIBLE.md" in row[0], (
        "data/fwci/README.md describes econ_units without naming its unported producer or the "
        f"register that carries it:\n{row[0]}")


LOSSY_DECLARATIONS = [
    ("BIGINT", "DOUBLE", "SELECT 9007199254740993::BIGINT AS v", "SELECT 9007199254740992.0::DOUBLE AS v"),
    ("DECIMAL(18,3)", "DOUBLE", "SELECT 1.005::DECIMAL(18,3) AS v", "SELECT 1.005::DOUBLE AS v"),
    ("INTEGER", "VARCHAR", "SELECT 1::INTEGER AS v", "SELECT '1'::VARCHAR AS v"),
]


@pytest.mark.parametrize("ta,tb,sql_a,sql_b", LOSSY_DECLARATIONS)
def test_review_major2_a_lossy_type_axis_is_rejected_not_trusted(tmp_path, ta, tb, sql_a, sql_b):
    """MAJOR-2. Declaring one of these axes used to switch off the ROW comparison as well as the
    schema check, because `EXCEPT ALL` resolves the two types to a lossy common supertype — all
    three pairs below hold genuinely different values and read EQUAL. The axis is now restricted to
    signed-integer widening, so the declaration is refused outright."""
    a = _pq(tmp_path / "a.parquet", sql_a)
    b = _pq(tmp_path / "b.parquet", sql_b)
    with pytest.raises(ContentEqualError, match="signed-integer family"):
        content_equal(a, b, accept_type_change=[("v", ta, tb)])
    assert content_equal(a, b).equal is False, "undeclared, the schema rule catches it as before"


def test_review_major2_the_allowed_axis_is_lossless_so_a_value_difference_survives_it(tmp_path):
    """The other half of MAJOR-2: inside the signed-integer family the supertype is a lossless
    widening, so declaring the axis cannot hide a value difference. Both boundary cases the reviewer
    probed are pinned here."""
    a = _pq(tmp_path / "a.parquet", "SELECT 2147483647::INTEGER AS v")
    b = _pq(tmp_path / "b.parquet", "SELECT 2147483648::BIGINT AS v")
    assert content_equal(a, b, accept_type_change=[("v", "INTEGER", "BIGINT")]).equal is False
    c = _pq(tmp_path / "c.parquet", "SELECT 300::INTEGER AS v")
    d = _pq(tmp_path / "d.parquet", "SELECT 44::TINYINT AS v")           # the 8-bit wrap
    assert content_equal(c, d, accept_type_change=[("v", "INTEGER", "TINYINT")]).equal is False


def test_review_m15_the_declared_axis_is_direction_sensitive(tmp_path):
    """Mutation M15 survived the original suite: making the axis symmetric broke no test. Task 7
    writes its per-frame declarations by argument order (which side is the rebuild), so the
    direction is part of the contract."""
    a = _pq(tmp_path / "a.parquet", "SELECT 1::BIGINT AS grp")
    b = _pq(tmp_path / "b.parquet", "SELECT 1::INTEGER AS grp")
    fwd = [("grp", "BIGINT", "INTEGER")]
    assert content_equal(a, b, accept_type_change=fwd).equal is True
    assert content_equal(b, a, accept_type_change=fwd).equal is False, (
        "the declaration names A's type first; the reverse pairing is a DIFFERENT change and must "
        "not be accepted by it")
    assert content_equal(b, a, accept_type_change=[("grp", "INTEGER", "BIGINT")]).equal is True


def test_review_m19_a_declaration_passed_to_a_byte_comparison_is_an_error(tmp_path):
    """Mutation M19 survived: silently ignoring the declaration in byte mode broke no test."""
    a = tmp_path / "a.csv"; a.write_bytes(b"x\n")
    b = tmp_path / "b.csv"; b.write_bytes(b"x\n")
    assert content_equal(a, b).equal is True
    with pytest.raises(ContentEqualError, match="parquet only"):
        content_equal(a, b, accept_type_change=[("grp", "BIGINT", "INTEGER")])


def test_review_m13_a_stale_declaration_is_reported_not_silently_dropped(tmp_path):
    """Mutation M13 survived: dropping the stale-declaration note broke no test. A declaration that
    no longer matches anything must stay visible (it does not fail — a builder that has been fixed
    must not force the harness to be loosened)."""
    a = _pq(tmp_path / "a.parquet", "SELECT 1::INTEGER AS grp")
    b = _pq(tmp_path / "b.parquet", "SELECT 1::INTEGER AS grp")
    r = content_equal(a, b, accept_type_change=[("grp", "BIGINT", "INTEGER")])
    assert r.equal is True and "stale declaration" in r.detail and "grp: BIGINT -> INTEGER" in r.detail


def test_review_minor4_and_nit3_a_declaration_that_cannot_mean_anything_raises(tmp_path):
    a = _pq(tmp_path / "a.parquet", "SELECT 1::BIGINT AS grp")
    b = _pq(tmp_path / "b.parquet", "SELECT 1::INTEGER AS grp")
    with pytest.raises(ContentEqualError, match="twice"):                # MINOR-4
        content_equal(a, b, accept_type_change=[("grp", "BIGINT", "INTEGER"),
                                                ("grp", "INTEGER", "TINYINT")])
    with pytest.raises(ContentEqualError, match="can never mean anything"):   # NIT-3
        content_equal(a, b, accept_type_change=[("grp", "INTEGER", "INTEGER")])


def test_review_minor2_two_zero_row_parquets_are_equal_but_flagged(tmp_path):
    """MINOR-2. A broken WHERE clause still writes a valid, correctly-typed, empty parquet — the
    failure the byte path's EMPTY flag exists to surface, and more likely here than for a CSV."""
    a = _pq(tmp_path / "a.parquet", "SELECT 1 AS grp, 2 AS y WHERE false")
    b = _pq(tmp_path / "b.parquet", "SELECT 1 AS grp, 2 AS y WHERE false")
    r = content_equal(a, b)
    assert r.equal is True and (r.rows_a, r.rows_b) == (0, 0)
    assert "both sides are EMPTY (0 rows)" in r.detail


def test_review_minor3_an_uncomparable_parquet_pair_is_an_error_not_a_not_equal(tmp_path):
    """MINOR-3. The row-comparison queries sat outside the try/except, so a DuckDB binder error
    escaped as a traceback and `main()` returned 1 — the harness's own code for NOT EQUAL. A shell
    gate branching on $? would read a crash as a verdict."""
    a = _pq(tmp_path / "a.parquet", "SELECT [1,2] AS v")
    b = _pq(tmp_path / "b.parquet", "SELECT 'x' AS v")
    with pytest.raises(UnreadableArtifact):
        content_equal(a, b)
    from tools.content_equal import main
    assert main(["content_equal.py", str(a), str(b)]) == 2               # uncomparable, not "not equal"
    assert main(["content_equal.py", str(a), str(a)]) == 0
    c = _pq(tmp_path / "c.parquet", "SELECT [9,9] AS v")
    assert main(["content_equal.py", str(a), str(c)]) == 1


# --------------------------------------------------------------------------------------------
# 9. T5 - the roster layer: three of the four frozen rosters re-executed, the fourth registered
# --------------------------------------------------------------------------------------------
# What this section proves, and what it deliberately cannot.
#
# Three of the four rosters in `data/raw_verified/` have a surviving producer, and all three are
# RE-RUN here through `pipeline/rosters/run_rosters.py` into the git-ignored scratch tree and
# compared with `tools/content_equal.py`:
#
#   roster_chemmath_verified.parquet  <- merge_chemmath_verified_v2.py   (61+13+5 verified batches)
#   roster_gold_chemistry.parquet     <- 00c_prep_final_population.py    (incfel u centre layer)
#   roster_gold_math_stats.parquet    <- 00c_prep_final_population.py
#
# The fourth, `roster_econ_verified.parquet`, has NO producer anywhere on this machine - neither the
# batch-builder nor the merge script exists - and `data/incfel/`, which 00c reads, has no producer
# either. Those two are registered in `pipeline/NOT_REPRODUCIBLE.md`, and the test at the end of
# this section keeps the register honest by re-deriving the counts it quotes from the evidence files.

ROSTER_SCRATCH = "output/rosters"
GOLD_DATA = f"{P['legacy_thesis'].name}/v2_output/multidisc_gold_2026-08-10/data"   # mirror name = legacy folder name (run_rosters.py)

needs_legacy_thesis = pytest.mark.skipif(
    not (P["legacy_thesis"] / "v2_output").is_dir(),
    reason="the roster stages read the human-verification evidence from the read-only legacy tree")


def _run_roster_stage(stage: str):
    import subprocess
    t0 = time.time()
    r = subprocess.run([sys.executable, str(REPO / "pipeline/rosters/run_rosters.py"), stage],
                       cwd=REPO, capture_output=True, text=True)
    return r, time.time() - t0


@pytest.fixture(scope="module")
def roster_merge():
    return _run_roster_stage("merge")


@pytest.fixture(scope="module")
def roster_final():
    return _run_roster_stage("final")


@pytest.fixture(scope="module")
def roster_variants():
    return _run_roster_stage("variants")


@needs_legacy_thesis
def test_t5_the_chemmath_merge_reproduces_the_frozen_roster(roster_merge):
    """The acceptance case for T5. `merge_chemmath_verified_v2.py` folds 61 + 13 + 5 human-verified
    batch files, the two OpenAlex match tables and the frozen `rejected_persons_chemmath_prev`
    snapshot into the 1,550-row / 1,484-person chem-math roster that `data/raw_verified/` holds.

    It is also the provenance evidence. Recon read the mtimes - v2 edited 18:14:15, all six outputs
    18:43:48-49, v1 at 17:47:19 - but an mtime says when a file was last EDITED, not when it ran,
    and v1 writes the same five basenames, so the ordering alone cannot tell which one produced the
    frozen table. The rerun can: v2 reproduces the parquet BYTE for byte and all five ledgers byte
    for byte, which no other script on this machine does.
    """
    r, elapsed = roster_merge
    assert r.returncode == 0, r.stdout + r.stderr
    mirror = REPO / ROSTER_SCRATCH / "merge/multidisc_roster_econ_grade_2026-08-09"
    rebuilt = mirror / "roster_clean_chemmath_verified.parquet"
    frozen = REPO / "data/raw_verified/roster_chemmath_verified.parquet"
    assert rebuilt.is_file(), r.stdout

    res = content_equal(rebuilt, frozen)
    print(f"\n[T5 rosters merge] {elapsed:.1f}s  mode={res.mode}  rows={res.rows_a:,}\n{res.detail}")
    assert res.equal, res.detail
    assert res.rows_a == res.rows_b == 1_550, (res.rows_a, res.rows_b)
    assert res.schema_equal, res.schema_diff

    # 1,484 distinct people over 15 department keys, and the rank_tag ladder the population is cut
    # on - asserted on the REBUILT file, so the caliber is re-derived rather than quoted.
    people, depts = duckdb.connect().execute(
        "SELECT count(DISTINCT author_id), count(DISTINCT dept_key) FROM read_parquet(?)",
        [str(rebuilt)]).fetchone()
    assert (people, depts) == (1_484, 15), (people, depts)
    tags = dict(duckdb.connect().execute(
        "SELECT rank_tag, count(*) FROM read_parquet(?) GROUP BY 1", [str(rebuilt)]).fetchall())
    assert tags == {"include": 652, "ambiguous": 451, "exclude": 447}, tags

    # and it is byte-identical as well - recorded as the provenance finding it is, not as the gate
    assert hashlib.sha256(rebuilt.read_bytes()).hexdigest() == \
        hashlib.sha256(frozen.read_bytes()).hexdigest(), (
        "the merge no longer reproduces the frozen roster byte for byte. Content equality is the "
        "gate (plan D1) - but this file DID rebuild bit-identically, and losing that is worth "
        "knowing about.")


@needs_legacy_thesis
def test_t5_the_merge_ledgers_are_byte_identical_too(roster_merge):
    """The parquet is one of six outputs. The other five are CSV/JSON, so they are compared as
    BYTES - and all five, including the 2,593-row human-verification ledger and the run's own stats
    file, come back identical to the 2026-08-10 originals."""
    r, _ = roster_merge
    assert r.returncode == 0, r.stdout + r.stderr
    mirror = REPO / ROSTER_SCRATCH / "merge/multidisc_roster_econ_grade_2026-08-09"
    legacy = P["legacy_v2_output"] / "multidisc_roster_econ_grade_2026-08-09"
    for rel in ("verify/chemmath_roster_verified_all.csv",
                "verify/rejected_persons_chemmath.csv",
                "verify/confirmed_no_openalex_id_chemmath.csv",
                "verify/uncertain_persons_chemmath.csv",
                "verify/merge_stats_v2.json"):
        res = content_equal(mirror / rel, legacy / rel)
        assert res.mode == "bytes", res.mode
        assert res.equal, f"{rel}\n{res.detail}"


@needs_legacy_thesis
def test_t5_the_final_population_reproduces_both_frozen_gold_rosters(roster_final):
    """`00c_prep_final_population.py` = the `incfel` department rosters UNION the research-centre
    academic layer, which is the population the chemistry and math-stats frames are built on. Both
    of its outputs are frozen in `data/raw_verified/` (by way of 70's copy) and both rebuild equal.

    Note what this does NOT prove: `incfel` itself has no producer (see NOT_REPRODUCIBLE.md), so the
    stage is verified from that input onward, not from the verified roster onward.
    """
    r, elapsed = roster_final
    assert r.returncode == 0, r.stdout + r.stderr
    out = REPO / ROSTER_SCRATCH / "final" / GOLD_DATA / "final"
    for field, rows, people in (("chemistry", 533, 518), ("math_stats", 580, 573)):
        rebuilt = out / f"roster_gold_{field}.parquet"
        frozen = REPO / f"data/raw_verified/roster_gold_{field}.parquet"
        res = content_equal(rebuilt, frozen)
        print(f"\n[T5 rosters final {field}] {elapsed:.1f}s  mode={res.mode}  rows={res.rows_a:,}")
        assert res.equal, res.detail
        assert res.rows_a == res.rows_b == rows, (res.rows_a, res.rows_b)
        assert res.schema_equal, res.schema_diff
        n = duckdb.connect().execute(
            "SELECT count(DISTINCT author_id) FROM read_parquet(?)", [str(rebuilt)]).fetchone()[0]
        assert n == people, (field, n)


@needs_legacy_thesis
def test_t5_the_rank_tag_variants_reproduce_against_the_legacy_run(roster_variants):
    """`00b_prep_roster_variants.py` is the only surviving code that states the rank_tag ladder
    (`inc` = include, `incamb` = include + ambiguous). Its outputs are NOT frozen in this repo - the
    frozen chain runs through `incfel`, whose builder is lost - so the comparison is against the
    legacy run's own copies. Four for four, which is what makes the missing `incfel` branch a gap in
    the SAVED code rather than a doubt about the ladder itself."""
    r, _ = roster_variants
    assert r.returncode == 0, r.stdout + r.stderr
    out = REPO / ROSTER_SCRATCH / "variants" / GOLD_DATA
    legacy = P["legacy_v2_output"] / "multidisc_gold_2026-08-10/data"
    seen = {}
    for variant in ("inc", "incamb"):
        for field in ("chemistry", "math_stats"):
            rel = f"{variant}/roster_gold_{field}.parquet"
            res = content_equal(out / rel, legacy / rel)
            assert res.equal, f"{rel}\n{res.detail}"
            seen[rel] = res.rows_a
    assert seen == {"inc/roster_gold_chemistry.parquet": 283,
                    "inc/roster_gold_math_stats.parquet": 366,
                    "incamb/roster_gold_chemistry.parquet": 472,
                    "incamb/roster_gold_math_stats.parquet": 622}, seen
    # the ladder is monotone by construction; a variant filter that stopped filtering would not be
    assert seen["inc/roster_gold_chemistry.parquet"] < seen["incamb/roster_gold_chemistry.parquet"]


@needs_legacy_thesis
def test_t5_the_fnfix_roster_step_is_a_pure_copy_and_is_asserted_not_repeated():
    """`70_prep_fnfix_inputs.py` line 96 is `shutil.copyfile(data/final -> data/fnfix)`, and the
    repo imported the COPY. The plan says to assert that identity rather than re-perform it, because
    the rest of that script walks the live OpenAlex API. So: the three files are one file."""
    ported = (REPO / "pipeline/rosters/multidisc_gold_2026-08-10/code/70_prep_fnfix_inputs.py"
              ).read_text(encoding="utf-8")
    assert 'shutil.copyfile(f"{D}/final/roster_gold_{field}.parquet", ' \
           'f"{D}/fnfix/roster_gold_{field}.parquet")' in ported, (
        "70's roster step is no longer the plain copy this identity rests on")
    data = P["legacy_v2_output"] / "multidisc_gold_2026-08-10/data"
    for field in ("chemistry", "math_stats"):
        digests = {which: hashlib.sha256(p.read_bytes()).hexdigest() for which, p in (
            ("data/final", data / f"final/roster_gold_{field}.parquet"),
            ("data/fnfix", data / f"fnfix/roster_gold_{field}.parquet"),
            ("data/raw_verified", REPO / f"data/raw_verified/roster_gold_{field}.parquet"))}
        assert len(set(digests.values())) == 1, (field, digests)


def test_t5_the_fnfix_stage_refuses_to_run_and_says_why():
    """Behaviour, not documentation: the stage that would call the live API must exit non-zero, and
    there is no flag that turns it on."""
    import subprocess
    r = subprocess.run([sys.executable, str(REPO / "pipeline/rosters/run_rosters.py"), "fnfix"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "does not run in this repository" in r.stderr, r.stderr
    assert "live OpenAlex API" in r.stderr and "shutil.copyfile" in r.stderr, r.stderr
    forced = subprocess.run([sys.executable, str(REPO / "pipeline/rosters/run_rosters.py"),
                             "fnfix", "--execute"], cwd=REPO, capture_output=True, text=True)
    assert forced.returncode != 0, (forced.returncode, forced.stdout, forced.stderr)


def test_t5_a_ported_roster_script_refuses_to_run_where_it_sits():
    """The T4 review's MAJOR-1 hazard, for this layer. `merge_chemmath_verified_v2.py` re-creates
    `verify/_backup_pre_gapfill_2026-08-10` and overwrites `rejected_persons_chemmath.csv`; run in
    place with the legacy root it would do that inside the read-only legacy tree."""
    import subprocess
    script = REPO / ("pipeline/rosters/multidisc_roster_econ_grade_2026-08-09/verify/"
                     "merge_chemmath_verified_v2.py")
    env = dict(os.environ)
    env.pop("SAR_STAGE_ROOT", None)
    env.pop("SAR_STAGED_RUN", None)
    r = subprocess.run([sys.executable, str(script)], cwd=REPO, capture_output=True, text=True,
                       env=env)
    assert r.returncode != 0, r.stdout
    assert "refusing to run a ported pipeline script where it sits" in r.stderr, r.stderr


@needs_legacy_thesis
def test_t5_the_staging_root_is_judged_by_the_write_barrier(monkeypatch, tmp_path):
    """`staged_run_dir` relaxes exactly ONE of `output_target`'s rules (a mirror must be allowed to
    be non-empty). Every other refusal has to survive, or the relaxation is a hole."""
    from pipeline.lib.paths import (STAGE_ROOT_ENV, WriteBarred, PathUnresolved, legacy_thesis,
                                    staged_run_dir)
    monkeypatch.delenv(STAGE_ROOT_ENV, raising=False)
    with pytest.raises(WriteBarred):                       # unstaged -> never the legacy location
        staged_run_dir(legacy_thesis())
    monkeypatch.setenv(STAGE_ROOT_ENV, str(legacy_thesis() / "v2_output"))
    with pytest.raises(WriteBarred, match="read-only legacy tree"):
        staged_run_dir(legacy_thesis())
    monkeypatch.setenv(STAGE_ROOT_ENV, str(REPO / "data"))
    with pytest.raises(WriteBarred, match="source tree"):
        staged_run_dir(legacy_thesis())
    monkeypatch.setenv(STAGE_ROOT_ENV, "relative/path")
    with pytest.raises(PathUnresolved, match="absolute"):
        staged_run_dir(legacy_thesis())
    monkeypatch.setenv(STAGE_ROOT_ENV, str(tmp_path))      # legal root, mirror not built yet
    with pytest.raises(PathUnresolved, match="staging mirror does not exist"):
        staged_run_dir(legacy_thesis())
    (tmp_path / legacy_thesis().name).mkdir()
    assert staged_run_dir(legacy_thesis()) == tmp_path.resolve() / legacy_thesis().name

    # and a SYMLINK is not a way around any of it: the root is resolved before it is judged, which
    # is the exact hole T2's re-review found open for $SAR_OUT_ROOT (R1).
    sneaky = tmp_path / "sneaky"
    sneaky.symlink_to(legacy_thesis() / "v2_output")
    monkeypatch.setenv(STAGE_ROOT_ENV, str(sneaky))
    with pytest.raises(WriteBarred, match="read-only legacy tree"):
        staged_run_dir(legacy_thesis())


@needs_legacy_thesis
def test_t8_the_mirror_INTERIOR_is_judged_too_not_only_the_staging_root(monkeypatch, tmp_path):
    """The blind spot Task 5's review registered and Task 7 widened, closed here.

    Everything the test above checks is about the staging ROOT and the name hung off it - all of it
    decided before any symlink INSIDE the mirror is followed. So a mirror whose run directory is
    itself a link into the legacy tree satisfied every check and then wrote through the link. It was
    a registered blind spot rather than a live bug only because the launchers build their mirrors
    out of real directories; the identical hole for `$SAR_OUT_ROOT` was a real Task-2 finding.

    Three cases: the mirror linked into the legacy tree, the mirror linked into the repo's tracked
    source tree, and a mirror that merely escapes its own staging root. Plus the control - a real
    directory in the same place still resolves - so the fix cannot be "refuse everything".
    """
    from pipeline.lib.paths import (STAGE_ROOT_ENV, WriteBarred, legacy_thesis, staged_run_dir)
    name = legacy_thesis().name

    def _root(sub: str, target: pathlib.Path) -> None:
        root = tmp_path / sub
        root.mkdir()
        (root / name).symlink_to(target)
        monkeypatch.setenv(STAGE_ROOT_ENV, str(root))

    _root("into_legacy", legacy_thesis() / "v2_output")
    with pytest.raises(WriteBarred, match="read-only legacy tree"):
        staged_run_dir(legacy_thesis())

    _root("into_repo", REPO / "data")
    with pytest.raises(WriteBarred, match="source tree"):
        staged_run_dir(legacy_thesis())

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _root("escapes", elsewhere)
    with pytest.raises(WriteBarred, match="escapes"):
        staged_run_dir(legacy_thesis())

    control = tmp_path / "control"
    (control / name).mkdir(parents=True)
    monkeypatch.setenv(STAGE_ROOT_ENV, str(control))
    assert staged_run_dir(legacy_thesis()) == control.resolve() / name


@needs_legacy_thesis
def test_t5_the_lost_econ_roster_and_incfel_are_registered_with_checkable_counts():
    """The other half of T5 (plan deviation D2). Two artifacts in this chain have no producer on
    this machine, so what ships is data plus an honest register. This test re-derives every count
    the register quotes FROM THE EVIDENCE FILES, so the register cannot drift into being a story."""
    import collections
    import csv as _csv
    reg = (REPO / "pipeline/NOT_REPRODUCIBLE.md").read_text(encoding="utf-8")
    for token in ("roster_clean_11school_verified.parquet", "data/incfel/",
                  "econ_roster_verify_2026-08-09", "00b_prep_roster_variants.py"):
        assert token in reg, f"the register no longer names {token}"

    ev = P["legacy_v2_output"] / "econ_roster_verify_2026-08-09"
    rows = []
    for f in sorted(ev.glob("verified/*.csv")):
        rows += list(_csv.DictReader(f.open(encoding="utf-8")))
    verdicts = collections.Counter(r["verdict"].strip().lower() for r in rows)
    facts = {
        "batch files": len(list(ev.glob("batches/*.csv"))),
        "verified files": len(list(ev.glob("verified/*.csv"))),
        "verification rows": len(rows),
        "confirmed": verdicts["confirmed"],
        "rejected": verdicts["rejected"],
        "uncertain": verdicts["uncertain"],
    }
    assert facts == {"batch files": 22, "verified files": 22, "verification rows": 840,
                     "confirmed": 731, "rejected": 74, "uncertain": 35}, facts
    for value in ("22 batch", "840", "731", "74", "35"):
        assert value in reg, f"the register does not state {value}"

    con = duckdb.connect()
    econ = REPO / "data/raw_verified/roster_econ_verified.parquet"
    n, ppl = con.execute("SELECT count(*), count(DISTINCT author_id) FROM read_parquet(?)",
                         [str(econ)]).fetchone()
    assert (n, ppl) == (920, 920), (n, ppl)
    assert "920" in reg
    # the arithmetic a replicator can run without any producer: 994 machine rows - 74 rejected = 920
    audit = list(_csv.DictReader((ev / "audit/econ_roster_evidence_audit.csv").open(encoding="utf-8")))
    rejected = list(_csv.DictReader((ev / "rejected_persons.csv").open(encoding="utf-8")))
    assert (len(audit), len(rejected)) == (994, 74), (len(audit), len(rejected))
    assert len(audit) - len(rejected) == n, "the 994 - 74 = 920 identity the register offers is false"
    assert "994" in reg

    incfel = P["legacy_v2_output"] / "multidisc_gold_2026-08-10/data/incfel"
    got = {f.name: con.execute("SELECT count(*) FROM read_parquet(?)",
                               [str(f)]).fetchone()[0] for f in sorted(incfel.glob("*.parquet"))}
    assert got == {"roster_gold_chemistry.parquet": 396,
                   "roster_gold_math_stats.parquet": 552}, got
    for value in ("396", "552"):
        assert value in reg, f"the register does not state the incfel row count {value}"
    # and the ladder the register claims incfel sits in: inc 283 < incfel 396 < final 533
    assert "283" in reg and "533" in reg


# --------------------------------------------------------------------------------------------
# 10. the producers that were NOT lost, only never saved as files (author-only)
# --------------------------------------------------------------------------------------------
# The economics roster merge, its batch builder and the `incfel` roster rung were first registered
# as having no producer. They were never files in any surviving tree: they were written into a
# temporary working directory the OS has since reclaimed, or ran once as a heredoc inside a shell
# command. They survive in the author's private working records, were recovered by replaying the
# recorded operations (pinned in `tests/test_verbatim_pipeline.py::RECOVERED`), and are re-run
# here. The recovery is a claim about the past, so it is tested the only way such a claim can be:
# by what it rebuilds. These tests need the author's private legacy tree and skip without it.


@pytest.fixture(scope="module")
def roster_econ_merge():
    return _run_roster_stage("econ-merge")


@pytest.fixture(scope="module")
def roster_econ_audit():
    return _run_roster_stage("econ-audit")


@pytest.fixture(scope="module")
def roster_incfel():
    return _run_roster_stage("incfel")


@needs_legacy_thesis
def test_t5fix_the_recovered_econ_merge_rebuilds_the_frozen_roster_byte_for_byte(roster_econ_merge):
    """`merge_roster.py`, replayed from the working records (1 Write + 9 Edit), folds the 22
    human-returned batches and the 994-row audit table into the economics roster — and produces
    `data/raw_verified/roster_econ_verified.parquet` **byte for byte**.

    That byte-identity is the whole argument. A reconstruction that merely looked plausible could
    not do it; nothing else on this machine does it; and it is what moves this artifact from "human
    verification, no code" to "reproducible from the 22 human-returned batches", the same standing
    the chem/math roster has.
    """
    r, elapsed = roster_econ_merge
    assert r.returncode == 0, r.stdout + r.stderr
    mirror = REPO / ROSTER_SCRATCH / "econ-merge/econ_roster_verify_2026-08-09"
    rebuilt = mirror / "roster_clean_11school_verified.parquet"
    frozen = REPO / "data/raw_verified/roster_econ_verified.parquet"

    res = content_equal(rebuilt, frozen)
    print(f"\n[T5fix econ-merge] {elapsed:.1f}s  mode={res.mode}  rows={res.rows_a:,}\n{res.detail}")
    assert res.equal, res.detail
    assert res.rows_a == res.rows_b == 920, (res.rows_a, res.rows_b)
    assert res.schema_equal, res.schema_diff
    assert hashlib.sha256(rebuilt.read_bytes()).hexdigest() == \
        hashlib.sha256(frozen.read_bytes()).hexdigest(), "the recovered merge no longer rebuilds it byte for byte"

    # the flag distributions the register offers a replicator, re-derived from the REBUILD
    con = duckdb.connect()
    src = dict(con.execute("SELECT verify_source, count(*) FROM read_parquet(?) GROUP BY 1",
                           [str(rebuilt)]).fetchall())
    assert sorted(src.values()) == [154, 766], src
    hv = dict(con.execute("SELECT human_verified, count(*) FROM read_parquet(?) GROUP BY 1",
                          [str(rebuilt)]).fetchall())
    assert hv == {True: 885, False: 35}, hv

    # the ledger CSV is byte-identical as well
    legacy = P["legacy_v2_output"] / "econ_roster_verify_2026-08-09"
    res_all = content_equal(mirror / "econ_roster_verified_all.csv",
                            legacy / "econ_roster_verified_all.csv")
    assert res_all.mode == "bytes" and res_all.equal, res_all.detail


@needs_legacy_thesis
def test_milestone_the_reject_cause_enrichment_rebuilds_the_13th_COLUMN_byte_for_byte(roster_econ_merge):
    """`rejected_persons.csv` once came back with 12 columns while the legacy copy had 13, and the
    enrichment step was registered as lost. It was not: the producer is an inline heredoc in the
    SAME working record the register cites for `merge_roster.py` (2026-08-09T12:40:54.559Z, stamped
    at the legacy file's mtime to the second).

    Recovered from that inline command, ported at
    `pipeline/rosters/econ_roster_verify_2026-08-09/code/add_reject_cause.py` — it holds no absolute
    path at all, so it is byte-identical to the replay — and run as the second step of `econ-merge`.
    The result is the frozen 13-column file exactly: **13 of 13 columns rebuild, not 12.**
    """
    r, _ = roster_econ_merge
    assert r.returncode == 0, r.stdout + r.stderr
    rebuilt = REPO / ROSTER_SCRATCH / "econ-merge/econ_roster_verify_2026-08-09/rejected_persons.csv"
    legacy = P["legacy_v2_output"] / "econ_roster_verify_2026-08-09/rejected_persons.csv"
    res = content_equal(rebuilt, legacy)
    assert res.equal and res.mode == "bytes", (
        "the reject_cause enrichment no longer reproduces the frozen file byte for byte:\n"
        + res.detail)
    assert hashlib.sha256(rebuilt.read_bytes()).hexdigest() == \
        "0c5dd47cd8e3bfe182a2f89b9b0a2aa61f2bc794cddbb50457e3673cb570e303"

    import csv as _csv
    rows = list(_csv.DictReader(rebuilt.open(encoding="utf-8")))
    assert len(rows) == 74, len(rows)
    assert list(rows[0]).index("reject_cause") == 6, list(rows[0])
    assert len(rows[0]) == 13, len(rows[0])
    causes = collections.Counter(r["reject_cause"] for r in rows)
    assert sum(causes.values()) == 74 and "" not in causes, causes   # `unmapped: 0`
    assert len(causes) == 4, causes

    # the register must now say RECOVERED, and must not still call it lost
    reg = (REPO / "pipeline/NOT_REPRODUCIBLE.md").read_text(encoding="utf-8")
    assert "add_reject_cause.py" in reg and "13 of 13" in reg
    assert "is in no working record, no file and no shell history" not in reg, (
        "the register still says the enrichment was never recovered")


@needs_legacy_thesis
def test_t5fix_the_recovered_batch_builder_rebuilds_the_audit_table_and_all_22_batches(roster_econ_audit):
    """The other half of BLOCKER-1, and the reason the replay tool reads shell patches instead of
    ignoring them: the producing version of `build_audit.py` was reached by 1 Write + 2 Edit **plus
    one in-place `python3 - <<EOF` patch**. Replaying only the Write and the Edits gave a file that
    rebuilt 994 rows with the right columns and the right author_id set — and 154 rows of the
    free-text `reason` column wrong. With the patch read out of the record and applied, the
    audit table and all 22 batch files come back byte-identical."""
    r, elapsed = roster_econ_audit
    assert r.returncode == 0, r.stdout + r.stderr
    mirror = REPO / ROSTER_SCRATCH / "econ-audit/econ_roster_verify_2026-08-09"
    legacy = P["legacy_v2_output"] / "econ_roster_verify_2026-08-09"

    res = content_equal(mirror / "audit/econ_roster_evidence_audit.csv",
                        legacy / "audit/econ_roster_evidence_audit.csv")
    print(f"\n[T5fix econ-audit] {elapsed:.1f}s  {res.mode}  {'EQUAL' if res.equal else 'NOT EQUAL'}")
    assert res.mode == "bytes" and res.equal, res.detail

    rebuilt_batches = sorted((mirror / "batches").glob("batch_*.csv"))
    legacy_batches = sorted((legacy / "batches").glob("batch_*.csv"))
    assert len(rebuilt_batches) == len(legacy_batches) == 22, (len(rebuilt_batches), len(legacy_batches))
    for x, y in zip(rebuilt_batches, legacy_batches):
        assert x.name == y.name, (x.name, y.name)
        assert content_equal(x, y).equal, f"{x.name} differs"

    # _summary.json matches on everything except the absolute paths of the batch files, which now
    # point into the staging mirror. Compared field by field so the exception is explicit.
    import json as _json
    a = _json.loads((mirror / "audit/_summary.json").read_text())
    b = _json.loads((legacy / "audit/_summary.json").read_text())
    assert {k: v for k, v in a.items() if k != "batch_files"} == \
           {k: v for k, v in b.items() if k != "batch_files"}
    assert [p.rsplit("/", 1)[-1] for p in a["batch_files"]] == \
           [p.rsplit("/", 1)[-1] for p in b["batch_files"]]
    assert (a["total"], a["needs_verification"], a["n_batches"]) == (994, 840, 22)


@needs_legacy_thesis
def test_t5fix_the_recovered_incfel_branch_rebuilds_the_missing_rung(roster_incfel):
    """The `incfel` rung, which Task 5 also registered as having no producer. It has one: a heredoc
    executed at 2026-08-10T10:38:27.165Z, three seconds before the incfel rosters' mtime. Lifted
    whole and re-run, it reproduces both of them content-equal, and it explains why `00b`'s saved
    `VARIANTS` map cannot: `inc`/`incamb` are sets of `rank_tag`, while `incfel` applies a TITLE
    regex to the `ambiguous` tier. That is a different rule, not a different argument."""
    r, elapsed = roster_incfel
    assert r.returncode == 0, r.stdout + r.stderr
    out = REPO / ROSTER_SCRATCH / "incfel" / GOLD_DATA / "incfel"
    legacy = P["legacy_v2_output"] / "multidisc_gold_2026-08-10/data/incfel"
    for field, rows, people in (("chemistry", 396, 384), ("math_stats", 552, 545)):
        res = content_equal(out / f"roster_gold_{field}.parquet",
                            legacy / f"roster_gold_{field}.parquet")
        print(f"\n[T5fix incfel {field}] {elapsed:.1f}s  {res.mode}  rows={res.rows_a}")
        assert res.equal, res.detail
        assert res.rows_a == res.rows_b == rows, (res.rows_a, res.rows_b)
        assert res.schema_equal, res.schema_diff
        n = duckdb.connect().execute("SELECT count(DISTINCT author_id) FROM read_parquet(?)",
                                     [str(out / f"roster_gold_{field}.parquet")]).fetchone()[0]
        assert n == people, (field, n)

    # the chemistry ladder, now with EVERY rung re-executed by this repo:
    #   inc 283 (00b)  ->  incfel 396 (the recovered branch)  ->  final 533 (00c)
    con = duckdb.connect()
    rung = {name: con.execute("SELECT count(*) FROM read_parquet(?)", [str(p)]).fetchone()[0]
            for name, p in (
                ("inc", P["legacy_v2_output"] / "multidisc_gold_2026-08-10/data/inc/roster_gold_chemistry.parquet"),
                ("incfel", out / "roster_gold_chemistry.parquet"),
                ("final", REPO / "data/raw_verified/roster_gold_chemistry.parquet"))}
    assert rung == {"inc": 283, "incfel": 396, "final": 533}, rung


@needs_legacy_thesis
def test_t5fix_the_incfel_rule_is_not_reachable_from_00b(roster_incfel):
    """Why the incfel branch had to be recovered rather than re-derived from `00b`: `00b`'s variants
    are `rank_tag` SETS and it reads neither argv nor env, so no invocation of it can produce a
    title-regex tier. Asserted on both ported sources so the claim cannot rot."""
    b = (REPO / "pipeline/rosters/multidisc_gold_2026-08-10/code/00b_prep_roster_variants.py"
         ).read_text(encoding="utf-8")
    assert 'VARIANTS = {"inc": {"include"}, "incamb": {"include", "ambiguous"}}' in b
    assert "sys.argv" not in b and "os.environ" not in b, "00b does read a knob after all"
    f = (REPO / "pipeline/rosters/multidisc_gold_2026-08-10/code/00b2_prep_incfel_variant.py"
         ).read_text(encoding="utf-8")
    assert 'KEEP = re.compile(r"\\bfellow", re.I)' in f and "def academic(title)" in f


# --------------------------------------------------------------------------------------------
# 11. T6 - stars and event gates: the layer that defines the treatment
# --------------------------------------------------------------------------------------------
#
# What is checked here, and what is checked out of band. The `u4aug` stage runs in 0.4 s, so it is
# a real rebuild in this suite: it is where econ 79 + 38 = 117 happens, and both of its parquet
# outputs are compared with `content_equal` against the frozen legacy copies. The two stages that
# rank the whole snapshot population (`restake`, 2.3-2.8 min, and `suspects`, 3.1-3.6 min, over 24 GB
# of edge tables) are NOT run here - the suite must stay fast - so their results are recorded in
# `pipeline/stars/README.md`, and what this file pins instead is the shape of the
# frozen artifacts those runs reproduced, plus the three legacy inconsistencies Task 6 reported.

STARS_RUN_DIR = "output/stars/econ_fnfix_2026-08-15"
GOLD = "multidisc_gold_2026-08-10"

needs_u4_star_set = pytest.mark.skipif(
    not ((P["ssd_root"] / "derived" / "u4_star_set_p10_80ev_2026-07-22").is_dir()
         and (P["legacy_thesis"] / "v2_output").is_dir()),
    reason="00_make_u4_aug.py reads the frozen 2026-07-22 star set from the data disk and the "
           "re-stake CSV plus the econ_p10 config from the legacy thesis tree")


@pytest.fixture(scope="module")
def u4aug_rebuild():
    """Run the `u4aug` stage ONCE for this module, through the launcher."""
    import subprocess
    t0 = time.time()
    r = subprocess.run([sys.executable, str(REPO / "pipeline/stars/run_stars.py"), "u4aug"],
                       cwd=REPO, capture_output=True, text=True)
    return r, time.time() - t0


@needs_u4_star_set
@pytest.mark.parametrize("rel,rows", [("u4_aug/events/data.parquet", 38),
                                      ("u4_aug/star_set/star_set.parquet", 277)])
def test_t6_u4_aug_rebuilds_content_equal_to_the_frozen_tables(u4aug_rebuild, rel, rows):
    """M3 Task 6's acceptance rerun. `00_make_u4_aug.py` is where the 38 hand-verified fn-fix
    additions become U4-shaped events and star rows, i.e. where econ 79 + 38 = 117 happens.

    The frozen artifacts are hashed before and after: a rebuild must never touch them."""
    frozen = P["legacy_v2_output"] / "econ_fnfix_2026-08-15" / rel
    before = (hashlib.sha256(frozen.read_bytes()).hexdigest(), frozen.stat().st_mtime_ns)
    r, elapsed = u4aug_rebuild
    assert r.returncode == 0, r.stdout + r.stderr
    assert "38 new events" in r.stdout and "19 rows synthesized / 16 rows flagged" in r.stdout, r.stdout

    rebuilt = REPO / STARS_RUN_DIR / rel
    assert rebuilt.is_file(), r.stdout
    res = content_equal(rebuilt, frozen)
    assert res.equal, res.detail
    assert res.mode == "content", res.mode
    con = duckdb.connect()
    assert con.execute("SELECT count(*) FROM read_parquet(?)", [str(rebuilt)]).fetchone()[0] == rows
    assert (hashlib.sha256(frozen.read_bytes()).hexdigest(),
            frozen.stat().st_mtime_ns) == before, "the rebuild touched the frozen artifact"


@needs_u4_star_set
def test_t6_the_only_non_equality_is_the_run_local_config_and_it_is_accounted_for(u4aug_rebuild):
    """The third output, `config/econ_fnfix.json`, is NOT byte-equal, and this pins exactly why so
    the difference can never quietly become something else.

    Two causes, both known: (a) three keys are built from `BASE`, which the launcher staged into
    `output/`, so they differ ONLY by that prefix - the sub-paths are identical; (b) `label` differs
    by the suffix a recorded 2026-08-15T18:09:38Z shell command appended to the frozen file BY HAND
    (`c['label'] += …`). No script writes that suffix, so no rerun can produce it. It is a run-local
    pointer file, not a data artifact - both parquets above are content-EQUAL."""
    import json
    r, _elapsed = u4aug_rebuild
    assert r.returncode == 0, r.stdout + r.stderr
    a = json.loads((REPO / STARS_RUN_DIR / "config/econ_fnfix.json").read_text(encoding="utf-8"))
    b = json.loads((P["legacy_v2_output"] / "econ_fnfix_2026-08-15/config/econ_fnfix.json"
                    ).read_text(encoding="utf-8"))
    assert sorted(a) == sorted(b), "the key set moved - the ported version is not the one that ran"
    differing = {k for k in a if a[k] != b[k]}
    assert differing == {"events", "run_dir", "supplement_jsonl", "label"}, differing

    old_base = str(P["legacy_v2_output"] / "econ_fnfix_2026-08-15")
    new_base = str(REPO / STARS_RUN_DIR)
    for key in ("run_dir", "supplement_jsonl"):
        assert a[key].replace(new_base, old_base) == b[key], key
    for key in ("events_dir", "star_set_dir"):
        assert a["events"][key].replace(new_base, old_base) == b["events"][key], key
    assert a["events"]["mode"] == b["events"]["mode"] == "u4_frozen"
    assert b["label"] == a["label"] + "；网络侧星边 = SSD 11school 边 ∪ 新星 API 补数边（同 gold 链）", (
        "the frozen label no longer differs from the script's output by exactly the hand-added "
        "suffix - re-read the working record before trusting the provenance ruling")


def test_t6_the_signed_event_arithmetic(  ):
    """79 + 38 = 117, 35, 31 (the pre-caliber signed set, still shipped) — and since the 2026-08-28
    freeze the CANONICAL arithmetic on top of it: econ 117 − 1 (A5044432173 out) = 116, chemistry 35 + 3 =
    38, math-stats 31 + 2 = 33, all checkable from the package alone, no legacy tree and no data
    disk. The 08-28 frames ledger is the caliber's 116; since 2026-09-23 the SHIPPED frames ledger is
    the October caliber's 113 (three econ events dropped, data/cal2026-10/events_decision_2026-10.json)."""
    def rows(p):
        return sum(1 for _ in p.open(encoding="utf-8-sig")) - 1
    rv = REPO / "data/raw_verified"
    n79 = rows(rv / "event_ledger_econ79.csv")
    n38 = rows(rv / "events_econ_new38.csv")
    # 2026-09-23: data/frames/ is the October caliber, so the 08-28 arithmetic reads the 08-28 ledger's frozen
    # copy (data/cal2026-08-28/frames/, the bytes data/frames/ held until the promotion), and the shipped
    # ledger is pinned to the October count: 116 - 3 dropped econ events = 113 (`dropped` in
    # data/cal2026-10/events_decision_2026-10.json; data/cal2026-10/events_econ_cal2026-10.csv has 113 rows;
    # both listed in data/cal2026-10/MANIFEST.sha256)
    n_ledger = rows(REPO / "data/cal2026-08-28/frames/p1_events_ledger_econ.csv")
    assert (n79, n38, n_ledger) == (79, 38, 116), (n79, n38, n_ledger)
    assert n79 + n38 - 1 == n_ledger                       # the caliber removed exactly A5044432173
    dec = json.loads((REPO / "data/cal2026-10/events_decision_2026-10.json").read_text(encoding="utf-8"))
    n_dropped = sum(1 for d in dec["dropped"] if d["field"] == "econ")
    n_oct = rows(REPO / "data/frames/p1_events_ledger_econ.csv")
    assert (n_dropped, n_oct) == (3, 113) and n_ledger - n_dropped == n_oct, (n_dropped, n_oct)
    assert rows(REPO / "data/cal2026-10/events_econ_cal2026-10.csv") == n_oct
    assert rows(rv / "events_chemistry_fnfix.csv") == 35
    assert rows(rv / "events_math_stats_fnfix.csv") == 31
    # the approved caliber event tables, canonical since the freeze
    assert rows(rv / "events_econ_cal2026-08-28.csv") == 116
    assert rows(rv / "events_chemistry_cal2026-08-28.csv") == 38
    assert rows(rv / "events_math_stats_cal2026-08-28.csv") == 33
    # and the promoted tables are byte-copies of the signed cal tables
    import hashlib
    for a, b in (("data/raw_verified/events_econ_cal2026-08-28.csv", "data/cal2026-08-28/events_econ_cal.csv"),
                 ("data/raw_verified/events_chemistry_cal2026-08-28.csv", "data/cal2026-08-28/events_chemistry_cal.csv"),
                 ("data/raw_verified/events_math_stats_cal2026-08-28.csv", "data/cal2026-08-28/events_math_stats_cal.csv")):
        assert hashlib.sha256((REPO / a).read_bytes()).hexdigest() == \
            hashlib.sha256((REPO / b).read_bytes()).hexdigest(), a


@pytest.mark.skipif(not (P["ssd_root"] / "derived" / "u4_star_set_p10_80ev_2026-07-22").is_dir(),
                    reason="the frozen 2026-07-22 star set lives on the data disk")
def test_t6_a_third_of_the_econ_star_set_was_never_ranked():
    """The fact that makes 'is_star ⟺ recomputed rank ≤ 0.10·cell_n' untestable for econ, and the
    reason the p10 shortlist step matters even though it cannot re-run: `common80.py` sets
    `percentile=None, cell_n=None, is_star_1pct=True` BY FIAT for that batch — star status there
    came from human web verification, not from an automatic rank. Registered in
    pipeline/NOT_REPRODUCIBLE.md."""
    con = duckdb.connect()
    ss = P["ssd_root"] / "derived/u4_star_set_p10_80ev_2026-07-22/star_set/star_set.parquet"
    n, n_null = con.execute(
        "SELECT count(*), count(*) FILTER (WHERE percentile IS NULL) FROM read_parquet(?)",
        [str(ss)]).fetchone()
    assert (n, n_null) == (258, 97), (n, n_null)
    src = (REPO / "pipeline/drivers/final80_p10_2026-07-22/common80.py").read_text(encoding="utf-8")
    assert '"percentile": None' in src and '"is_star_1pct": True' in src


@pytest.mark.skipif(not (P["legacy_thesis"] / "v2_output").is_dir(),
                    reason="the re-stake ledger lives in the legacy thesis tree")
def test_t6_finding_f1_the_restake_pass_flag_does_not_test_the_seniority_gate():
    """FINDING, reported not fixed (pipeline/stars/README.md, F1).

    `72_restake_fnfix_stars.py:78` builds `pass_p10` from percentile and cell size only, while
    `60_…py:92` and `screening_lib.star_pass_flags` both refuse on `aage < 2`. One row of the frozen
    re-stake is affected and it is a real event: A5044432173, `aage = 0`, `after_pass = True`, and
    one of the 38 econ fn-fix additions — so in the signed 117, admitted by a check
    that does not test gate ②. This test pins the finding so that it cannot silently change (in
    either direction) without somebody reading this docstring."""
    import csv
    gold = P["legacy_v2_output"] / GOLD
    restake = list(csv.DictReader((gold / "data/fnfix_restake_2026-08-15.csv").open(encoding="utf-8")))
    assert len(restake) == 67, len(restake)
    passes = [r for r in restake if r["after_pass"] == "True"]
    assert len(passes) == 63 and len(restake) - len(passes) == 4, len(passes)
    under_age = [r for r in passes if r["aage"] and float(r["aage"]) < 2]
    assert [(r["author_id"], r["aage"]) for r in under_age] == \
        [("A5044432173", "0")], [r["author_id"] for r in under_age]

    new38 = list(csv.DictReader(
        (REPO / "data/raw_verified/events_econ_new38.csv").open(encoding="utf-8")))
    assert "A5044432173" in {r["author_id"] for r in new38}, "no longer one of the 38"

    # and the two implementations really do differ, asserted on the ported bytes
    s72 = (REPO / f"pipeline/stars/{GOLD}/code/72_restake_fnfix_stars.py").read_text(encoding="utf-8")
    s60 = (REPO / f"pipeline/stars/{GOLD}/code/60_poach_gate_false_negatives.py").read_text("utf-8")
    assert '"pass_p10": (pct >= 1 - L.P10) and cn >= L.CELL_MIN_N["floor"]' in s72
    assert '"pass_p10": (pct >= 0.90 and cn >= 30 and aage >= 2)' in s60
    lib = (REPO / "pipeline/stars/multidisc_2026-07-24/code/star_screening/screening_lib.py"
           ).read_text(encoding="utf-8")
    assert "if not age_eligible(academic_age, min_academic_age=min_academic_age):" in lib


@pytest.mark.skipif(not (P["legacy_thesis"] / "v2_output").is_dir(),
                    reason="the suspect ledgers live in the legacy thesis tree")
def test_t6_the_repaired_gate_added_62_events_and_the_suspect_counts_hold():
    """The arithmetic of the repair, from the frozen artifacts: 264/266/141 suspects, 67 re-staked,
    and econ +38 / chemistry +13 / math-stats +11 = 62 events. The two rankings that reproduce the
    suspect and re-stake tables are too slow for this suite; their results are in
    pipeline/stars/README.md."""
    gold = P["legacy_v2_output"] / GOLD

    def rows(p):
        return sum(1 for _ in p.open(encoding="utf-8")) - 1
    assert [rows(gold / f"data/poach_fn_suspects_{f}.csv")
            for f in ("econ", "chemistry", "math_stats")] == [264, 266, 141]
    assert rows(gold / "data/fnfix_restake_2026-08-15.csv") == 67
    assert rows(gold / "verify/fnfix_work_level_calls.csv") == 385
    assert [rows(gold / f"verify/fnfix_adjudication_{t}.csv") for t in ("econ", "chem", "math")] \
        == [35, 14, 13]
    # 22 + 13 = 35 chemistry, 20 + 11 = 31 math-stats, 79 + 38 = 117 econ  ->  +62
    assert rows(gold / "data/events_chemistry_final_2026-08-13.csv") == 22
    assert rows(gold / "data/events_math_stats_final_2026-08-13.csv") == 20
    assert rows(gold / "data/fnfix_new_events.csv") == 24            # 13 chem + 11 math
    assert 38 + 13 + 11 == 62


@pytest.mark.skipif(not (P["legacy_thesis"] / "v2_output").is_dir(),
                    reason="the config variants live in the legacy thesis tree")
def test_t6_the_noA5044701593_exclusion_exists_only_as_a_config_label():
    """Registered in pipeline/NOT_REPRODUCIBLE.md: the removal of one star (the config file name says
    `noA5044701593`; in the legacy tree it is a person's name) has no decision file, no adjudication
    row and no code path. It is a filename plus a `label` string, and this pins that claim."""
    import json
    cfgdir = P["legacy_v2_output"] / GOLD / "config"
    for field in ("chemistry", "math_stats"):
        cfg = json.loads((cfgdir / f"noA5044701593_{field}.json").read_text(encoding="utf-8"))
        assert "noA5044701593" in cfg["events"]["signed_csv"], cfg["events"]["signed_csv"]
        assert "a5044701593" in cfg["label"].lower(), "the label no longer names the removal"


# --- T6 review BLOCKER-1: the recovered event-selection rung ----------------------------------

needs_selector_inputs = pytest.mark.skipif(
    not (P["legacy_thesis"] / "v2_output" / "multidisc_gold_2026-08-10" / "data"
         / "fnfix_candidates_restake.csv").is_file(),
    reason="the selectors read the re-stake, the candidate table and the two human recheck ledgers "
           "from the legacy thesis tree")


def _run_stage(stage, tmp_path):
    import subprocess
    env = dict(os.environ, SAR_OUT_ROOT=str(tmp_path))
    env.pop("SAR_STAGE_ROOT", None)
    return subprocess.run([sys.executable, str(REPO / "pipeline/stars/run_stars.py"), stage],
                          cwd=REPO, capture_output=True, text=True, env=env)


@needs_selector_inputs
def test_t6fix_the_recovered_econ_selector_rebuilds_the_38_events_byte_for_byte(tmp_path):
    """The step nothing on disk performs: 67 re-staked candidates -> the 38 signed econ events.

    Recovered from a shell heredoc (it was never a file), and this is the external proof that the
    replay is the original rather than a plausible substitute - the same standard `merge_roster.py`
    met in Task 5. Compared against BOTH the legacy copy and the repo's own frozen one."""
    r = _run_stage("events-econ", tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "econ new events 38" in r.stdout, r.stdout
    built = tmp_path / "stars/econ_fnfix_2026-08-15/data/new_events_econ.csv"
    assert built.is_file(), r.stdout
    # the two economists the selector drops (percentiles .8753 and .8675) are not among the 38
    body = built.read_text(encoding="utf-8")
    assert "A5027126744" not in body and "A5105845982" not in body
    for frozen in (P["legacy_v2_output"] / "econ_fnfix_2026-08-15/data/new_events_econ.csv",
                   REPO / "data/raw_verified/events_econ_new38.csv"):
        res = content_equal(built, frozen)
        assert res.equal and res.mode == "bytes", res.detail


@needs_selector_inputs
def test_t6fix_the_recovered_chemmath_selector_rebuilds_the_24_events_and_the_wide_extra(tmp_path):
    """Its twin, and the file that explains the "+13": 14 chemistry passers, 13 events, and one row
    diverted by `in_window` into `fnfix_new_events_wide_extra.csv`."""
    r = _run_stage("events-chemmath", tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "main 24 {'chemistry': 13, 'math_stats': 11}" in r.stdout, r.stdout
    gold = P["legacy_v2_output"] / "multidisc_gold_2026-08-10" / "data"
    for name in ("fnfix_new_events.csv", "fnfix_new_events_wide_extra.csv"):
        res = content_equal(tmp_path / "stars/multidisc_gold_2026-08-10/data" / name, gold / name)
        assert res.equal and res.mode == "bytes", res.detail


@needs_selector_inputs
def test_t6fix_the_two_rules_that_live_only_in_the_recovered_selectors():
    """FINDINGS, reported not changed (pipeline/stars/README.md).

    (a) `in_window` diverts a human-confirmed, gate-passing chemistry star out of the event set, and
        the only record of why is a FILE NAME: A5062352558, `after_pass True`, `aage 11`, pct .9717.
    (b) a hard-coded `borderline = aid == 'A5016651378'` would drop a named person by id, but the
        branch is unreachable because `if not ok: continue` fires first for that id.
    Both are pinned so a re-run cannot quietly change what they mean."""
    import csv
    sel = (REPO / "pipeline/stars/multidisc_gold_2026-08-10/code/00_select_new_events_chemmath.py"
           ).read_text(encoding="utf-8")
    assert "inwin=c['in_window']=='True'" in sel
    assert "(main if inwin else wide).append(row)" in sel
    assert "borderline = aid=='A5016651378'" in sel
    assert sel.index("if not ok:") < sel.index("if borderline:"), (
        "the dead branch is no longer dead - the finding has changed")

    gold = P["legacy_v2_output"] / "multidisc_gold_2026-08-10"
    wide = list(csv.DictReader((gold / "data/fnfix_new_events_wide_extra.csv").open(encoding="utf-8")))
    assert [(w["author_id"], w["field"], w["arrival_corrected"], w["evidence_grade"])
            for w in wide] == [("A5062352558", "chemistry", "2003", "strong")], len(wide)
    restake = {r["author_id"]: r for r in csv.DictReader(
        (gold / "data/fnfix_restake_2026-08-15.csv").open(encoding="utf-8"))}
    assert restake["A5062352558"]["after_pass"] == "True", "A5062352558 no longer passes the gates"
    assert restake["A5062352558"]["aage"] == "11"
    assert restake["A5016651378"]["after_pass"] == "False", "A5016651378 now reaches the dead branch"
    chem = [a for a, r in restake.items() if r["field"] == "chemistry" and r["after_pass"] == "True"]
    assert len(chem) == 14 and 14 - 1 == 13


# --- T6 final review REOPEN-1/REOPEN-2: the candidate table and the two windows -----------------

@needs_selector_inputs
def test_t6final_the_recovered_candidate_table_rebuilds_byte_for_byte(tmp_path):
    """`fnfix_candidates_restake.csv` — the file that carries `in_window`, and the input both `72`
    and both selectors read — was never a file: four chained heredocs build it.

    All four run. Rungs 1-3 give a byte-exact 62-row prefix; rung 4 appends the last five, and its
    input — a temporary task output the OS reclaimed — is written back from the frozen payload
    `data/stage_payloads/u4_star_events.json` for the duration of the stage, parsed as data and
    never executed. The whole chain reproduces the frozen 67-row table byte for byte, and so does
    the rung's other output.

    **Escaped vs unescaped.** The payload was HTML-escaped in the working record it was recovered
    from. Reconstructing from the RAW read produces a CSV that differs from the frozen artifact at
    byte 3,623 — `&gt;` where the artifact has `->`, inside a free-text verdict note — and nowhere
    else, so the frozen payload holds the HTML-UNESCAPED text; the byte-identical rebuild below is
    the external proof that the unescaping is right."""
    r = _run_stage("candidates", tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "added econ 35 total 62" in r.stdout, r.stdout
    out = tmp_path / "stars/multidisc_gold_2026-08-10/data"
    gold = P["legacy_v2_output"] / "multidisc_gold_2026-08-10" / "data"
    for name in ("fnfix_candidates_restake.csv", "poach_fn_recheck_econ_U4flagged9_2026-08-16.csv"):
        res = content_equal(out / name, gold / name)
        assert res.equal and res.mode == "bytes", res.detail
    import csv
    rows = list(csv.DictReader((out / "fnfix_candidates_restake.csv").open(encoding="utf-8")))
    assert len(rows) == 67, len(rows)
    # the five rows beyond the 62-row prefix are exactly the confirmed U4-flagged verdicts
    u4 = {row["author_id"] for row in csv.DictReader(
        (gold / "poach_fn_recheck_econ_U4flagged9_2026-08-16.csv").open(encoding="utf-8"))
        if row["verdict"] == "confirmed"}
    assert {r["author_id"] for r in rows[-5:]} == u4 and len(u4) == 5, sorted(u4)
    # and the reconstruction cleans up after itself - nothing left in the temp area
    consumer = (REPO / "pipeline/stars/multidisc_gold_2026-08-10/code"
                / "00_build_candidates_restake_econ_u4flagged9.py").read_text(encoding="utf-8")
    import re
    declared = re.findall(r"open\('(/[^']+\.output)'\)", consumer)
    assert len(declared) == 1 and not pathlib.Path(declared[0]).exists(), (
        "the reconstructed task output was left behind in the temp area")


@needs_selector_inputs
def test_t6final_in_window_is_two_rules_and_that_is_the_2003_arrival_question():
    """REOPEN-1, the finding this task must NOT resolve. `in_window` is not one rule: chemistry and
    math-stats bound the ROSTER arrival year to 2005-2023, economics bounds the human-verified TRUE
    arrival year to 1999-2024, and the five late U4-flagged economics rows carry a literal `True`.

    Three people arriving in 2003: A5062352558 (chemistry) is excluded, A5018518935 and A5006190609
    (economics) are two of the 38. Nothing separates them but which discipline's window wrote their
    row. Pinned in both directions so the asymmetry cannot silently change before the author sees
    it."""
    import csv
    code = REPO / "pipeline/stars/multidisc_gold_2026-08-10/code"
    for f in ("00_build_candidates_restake_chem.py", "00_build_candidates_restake_math.py"):
        assert "inwin = 2005 <= int(c['arrival_roster']) <= 2023" in (code / f).read_text("utf-8"), f
    econ = (code / "00_build_candidates_restake_econ.py").read_text("utf-8")
    assert '"in_window":1999<=int(r[\'arrival_true\'])<=2024' in econ, econ
    late = (code / "00_build_candidates_restake_econ_u4flagged9.py").read_text("utf-8")
    assert '"in_window":True' in late, "the literal-True third path is gone"

    gold = P["legacy_v2_output"] / "multidisc_gold_2026-08-10"
    cand = {r["author_id"]: r for r in csv.DictReader(
        (gold / "data/fnfix_candidates_restake.csv").open(encoding="utf-8"))}
    rs = {r["author_id"]: r for r in csv.DictReader(
        (gold / "data/fnfix_restake_2026-08-15.csv").open(encoding="utf-8"))}
    new38 = {r["author_id"] for r in csv.DictReader(
        (REPO / "data/raw_verified/events_econ_new38.csv").open(encoding="utf-8"))}
    #        author_id      field        true  roster in_window  in the 38?
    for aid, field, window, in_events in (
            ("A5062352558", "chemistry", "False", False),
            ("A5018518935", "econ", "True", True),
            ("A5006190609", "econ", "True", True)):
        row = cand[aid]
        assert row["field"] == field and row["arrival_true"] == "2003" \
            and row["arrival_roster"] == "2003", row
        assert row["in_window"] == window, row
        assert rs[aid]["after_pass"] == "True", "all three pass the gates - that is the point"
        assert (aid in new38) is in_events, (aid, in_events)

    # and the asymmetry is not one border case: every chemistry candidate clears econ's window
    chem = [r for r in cand.values() if r["field"] == "chemistry"]
    assert len(chem) == 14
    assert all(1999 <= int(r["arrival_true"]) <= 2024 for r in chem)
    assert [r["author_id"] for r in chem if r["in_window"] != "True"] == ["A5062352558"]


# --------------------------------------------------------------------------------------------
# 11. T7 — the frames acceptance proof (M3's acceptance task; re-pointed at the caliber canon
#     by the 2026-08-28 freeze)
# --------------------------------------------------------------------------------------------
# One case per frozen file in `data/frames/`. Twenty-one files, seven ported builders, two
# producers recovered from the author's working records, and the D1 criterion applied per frame: CSV
# byte-identical, parquet content-equal. Every assertion goes through `tools/content_equal.py`
# rather than `pipeline/frames/make_slim.py::content_equal`, which has no schema check and
# compares a caller-chosen column subset (T3's carried finding (a)).
#
# SINCE THE 2026-08-28 FREEZE the frozen canon is the author-approved caliber rebuild, so the
# rebuild side runs through the caliber arrangement: `tests/_cal_rebuild_driver.py` builds the
# shadow legacy tree (cal event tables + supplement + the econ single-event removal staged at the exact fnfix
# paths — `frames_stage.build_shadow`, the T3 design) and drives the SAME verbatim ported builders
# through the same launcher stages in T3's dependency order, into out-of-repo scratch. The
# builders, the comparison criterion, the provenance guards and the 19-EQUAL/2-NOT-EQUAL structure
# are unchanged; what moved is the staged INPUT SET, which is exactly what the caliber is. The one
# stage still driven against the real (pre-caliber) legacy tree is `speed`:
# `p3_afar_speed_bracket.csv` has no cal builder and is the one frame left on the pre-caliber
# event set (CALIBER-STALE, pipeline/NOT_REPRODUCIBLE.md index row 9).
#
# 2026-09-23 — data/frames/ PROMOTED TO THE OCTOBER CALIBER (cal2026-10; data/frames/README.md, first canon
# paragraph). This proof still rebuilds THROUGH THE 2026-08-28 CALIBER (the driver is unchanged), so its
# frozen operand is the 2026-08-28 canon, kept byte for byte at data/cal2026-08-28/frames/ (pinned by
# data/cal2026-08-28/MANIFEST.sha256; tag cal-2026-08-28) — every frame under the SAME name, each hashing
# to the `old_sha256` that data/cal2026-10/expected_refreeze_2026-10.json recorded for data/frames/ at the
# promotion (`_anchor_frozen` checks both). Nothing beneath the operand moved: builders, criterion,
# guards, the 19-EQUAL/2-NOT-EQUAL structure. The one frame not in that directory,
# p3_afar_speed_bracket.csv, has no cal builder and was left untouched by the promotion (old == new
# sha256 there), so it stays anchored in data/frames/ + data/MANIFEST.sha256. The files the promotion
# ADDED to data/frames/ are produced by no frames-layer stage and are declared apart as the named set
# `CAL2026_10_ADDITIONS`, the way `DERIVED_FRAMES` is.
#
# The declared type axes DIED AT THE FREEZE — the outcome D1 said a later milestone may choose,
# and the axes test below is the one that fails the day it happens (it did, and was updated in the
# same commit as the freeze). Before it, three per-frame axes were needed because the frozen slims
# carried two legacy schemas (the econ heredoc's uncast DENSE_RANK BIGINT; 30_build's INTEGER
# y/D); the caliber re-freeze built ALL six frozen slims with `pipeline/frames/make_slim.py`, so
# rebuild and frozen now share one schema and the harness accepts no axis anywhere.
#
# The `ev` asymmetry (same finding): the frozen non-`ev` slims have a genuinely different column
# SET, not a different type, so they get their own comparison against the rebuild PROJECTED onto
# their columns. The projection is asserted to drop exactly `ev` and nothing else, so it cannot
# quietly hide a column difference — which is the failure mode a subset comparison invites.

import ast as _ast                                                            # noqa: E402
import csv as _csv                                                            # noqa: E402
import json as _json                                                          # noqa: E402
import re as _re                                                              # noqa: E402
import shutil as _shutil                                                      # noqa: E402
import subprocess                                                             # noqa: E402

FRAMES = P["frames"]
#: the 2026-08-28 canon this proof compares against since the 2026-09-23 promotion (block comment above)
FRAMES_0828 = REPO / "data" / "cal2026-08-28" / "frames"
#: per frame, what data/frames/ held until the promotion and what it holds now (old/new sha256)
_REFREEZE = _json.loads((REPO / "data" / "cal2026-10" / "expected_refreeze_2026-10.json")
                        .read_text(encoding="utf-8"))["frames"]


def _frozen_path(frame: str) -> pathlib.Path:
    """The frozen operand of an 08-28 rebuild: the 08-28 copy — except the one pre-caliber frame."""
    return FRAMES / frame if frame == "p3_afar_speed_bracket.csv" else FRAMES_0828 / frame


V2 = P["legacy_v2_output"]
DERIVED = P["ssd_root"] / "derived"
#: the two U1 vintages the SSD stages read. The split is load-bearing, not incidental:
#: `00_build_frame_econ920.py:33-34` records that using the 2026-07-05 edge tables for the econ
#: chain is what made the v3 gold standard FAIL.
U1_ECON, U1_GOLD = "u1_full_11school_2026-07-16", "u1_edges_full_2026-07-05"

#: per-frame record filled in by the cases below, printed as the acceptance table at the end
ACCEPTANCE: dict[str, dict] = {}


def _need(*paths: pathlib.Path) -> None:
    for path in paths:
        if not pathlib.Path(path).exists():
            _skip_loudly(f"SKIPPED-NO-SSD/INPUT: {path}")


#: the ONLY two verdicts, and the map from a comparison result to one of them. T7's final review
#: demonstrated the hole this closes: `_record` used to take the verdict as a free string, so the
#: p1-gold path passed the literal "NOT-BYTE-EQUAL (float accumulation order; characterised)" and
#: three edits - flip the two pinned entries, flip N_EQUAL, flip that literal - printed and asserted
#: "21 EQUAL / 0 NOT EQUAL" while the comparison underneath was still unequal. M3's one negative
#: result would have vanished into a string. A verdict is now DERIVED, here, from the `Result` the
#: comparator returned, exactly as `mode` and `rows` already were; there is no parameter to pass.
_VERDICT: dict[bool, str] = {True: "EQUAL", False: "NOT EQUAL"}

#: prose that CHARACTERISES a verdict without being able to change it. Recorded beside the verdict,
#: pinned separately (`EXPECTED_NOTES`), never consulted by the acceptance comparison.
ACCEPTANCE_NOTES: dict[str, str] = {}


def _record(frame: str, builder: str, result, rows=None, secs=None, rss=None,
            axis: tuple = (), note: str = "") -> None:
    """Record one acceptance row. The verdict and the mode come from `result`, not from the caller.

    `result` is a `tools.content_equal.Result` (or anything with `.equal` and `.mode`). Passing a
    bool, a string, or a hand-made stand-in raises: the derivation must be total over exactly the
    two states a comparison can be in.
    """
    equal, mode = result.equal, result.mode
    if not isinstance(equal, bool):
        raise TypeError(f"{frame}: a comparison result's .equal must be a bool, got {equal!r}")
    if mode not in ("bytes", "content"):
        raise ValueError(f"{frame}: unknown comparison mode {mode!r}")
    verdict = _VERDICT[equal]
    ACCEPTANCE[frame] = {"builder": builder, "mode": mode, "rows": rows, "verdict": verdict,
                         "secs": secs, "peak_rss_mb": rss, "accept_type_change": axis}
    if note:
        ACCEPTANCE_NOTES[frame] = note
    print(f"[acceptance] {frame:32s} {builder:26s} {mode:7s} rows={rows} {verdict}"
          + (f" - {note}" if note else "")
          + (f"  {secs:.1f}s" if secs else "") + (f"  peak {rss} MB" if rss else ""))


#: fresh out-of-repo scratch roots for the acceptance runs. `$SAR_OUT_ROOT` is single-use by
#: design (the barrier refuses a root that already holds entries), so each stage gets its own -
#: and they are deliberately NOT under `<repo>/output/`: on a cloud-synced disk, rebuilding into it
#: produced a `p1-econ 3` conflict copy mid-run, a 65,535-link directory the launcher then refused
#: as an unknown entry. That refusal was correct; running out-of-repo avoids provoking it.
_SCRATCH_ROOTS: list[str] = []


def _run_frames_stage(stage: str, args: tuple[str, ...] = (), execute: bool = False):
    """Run one launcher stage in a subprocess and return the `Rebuild` it produced.

    `/usr/bin/time -l` is used when it exists so the peak RSS is the CHILD's, measured, not this
    process's cumulative high-water mark.
    """
    import tempfile                                                          # noqa: PLC0415
    root = tempfile.mkdtemp(prefix=f"sar_t7_{stage}_")
    _SCRATCH_ROOTS.append(root)
    launcher = REPO / "pipeline" / "frames" / "run_frames.py"
    cmd = [sys.executable, str(launcher), stage]
    if execute:
        cmd.append("--execute")
    if args:
        cmd += ["--", *args]
    timer = pathlib.Path("/usr/bin/time")
    if timer.exists():
        cmd = [str(timer), "-l", *cmd]
    env = {**os.environ, "SAR_OUT_ROOT": root}
    started_ns = time.time_ns()
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, env=env)
    secs = time.time() - t0
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"run_frames.py {stage} failed ({proc.returncode}):\n{out[-4000:]}"
    m = _re.search(r"run directory -> (.+)", proc.stdout)
    assert m, f"the launcher did not name its run directory:\n{out[-2000:]}"
    rss = _re.search(r"(\d+)\s+maximum resident set size", out)
    # the launcher's own closing report: `    OK   <abs path>  (N B, sha256 <hex>)`
    produced = {path: sha for path, sha in
                _re.findall(r"^\s+OK\s+(/.+?)\s+\(\d[\d,]* B, sha256 ([0-9a-f]{64})\)$",
                            proc.stdout, _re.M)}
    assert produced, f"the launcher reported no outputs for {stage}:\n{out[-2000:]}"
    return Rebuild(pathlib.Path(m.group(1).strip()), started_ns, secs,
                   int(rss.group(1)) // (1 << 20) if rss else None, produced)


# --- T7 review MAJOR-1: a comparison must PROVE it compared a rebuild ---------------------------
# The reviewer forged the acceptance table with one line: in the speed-bracket case they replaced
# `run_dir / "data/speed_bracket.csv"` with `FRAMES / "p3_afar_speed_bracket.csv"` — the frozen file
# compared with itself — and every gate stayed green while the table still printed EQUAL. The hole
# was that the helpers took the rebuilt path as a FREE PARAMETER and never asked where it came from.
#
# Two changes close it. First, the helpers no longer accept a path: they take the producing run and
# a path RELATIVE to it, and build the path themselves, so the smuggle cannot be expressed. Second,
# every comparison asserts the four things that make "this is a rebuild" checkable rather than
# assumed: the producing root is outside the repo and outside both legacy trees, the file is not the
# frozen file (by resolved path AND by inode, so a hard link cannot pose as one), and it was written
# after the producer started.

@dataclasses.dataclass(frozen=True)
class Rebuild:
    """A producing run: the ONE directory it was allowed to write, and when it started.

    `produced` is the producer's OWN report of what it wrote — for a launcher stage, the
    `OK <path> (N B, sha256 …)` lines `run_frames.py` prints, parsed out of its stdout. When it is
    present a comparison must name a file the producer said it produced, AND that file's bytes must
    still hash to what the producer reported. That is what closes probe V5 (a fresh copy of the
    frozen file dropped into a legitimate scratch root): the copy is in the right place with the
    right mtime, but the launcher never announced it.
    """
    root: pathlib.Path
    started_ns: int
    secs: float | None = None
    rss: int | None = None
    produced: dict[str, str] | None = None      #: absolute path -> sha256, as the producer reported


def _producer_root_is_safe(root: pathlib.Path) -> None:
    """A rebuild that lives inside the repo or a legacy tree is not a rebuild - it is an artifact."""
    root = root.resolve()
    assert not root.is_relative_to(REPO), (
        f"the producing root {root} is inside the repository; a rebuild compared from there could "
        f"be a frozen artifact rather than something a builder just made")
    for key in ("legacy_v2_output", "legacy_thesis"):
        assert not root.is_relative_to(pathlib.Path(P[key]).resolve()), (root, key)


#: MILESTONE REVIEW, acceptance-honesty MAJOR. Every guard above interrogates the REBUILT operand;
#: nothing said anything about the FROZEN one. `FRAMES = P["frames"]` is redirectable through
#: `$SAR_PATHS_CONFIG` or one line of `config/paths.yaml` (a tracked file in no manifest), and the
#: reviewer pointed it at a copy holding two non-shipped files: the whole table still printed
#: "19 EQUAL / 2 NOT EQUAL / 0 skipped, of 21" and `pipeline/run_all.sh --stage frames` still said
#: PIPELINE_OK. The claim's SUBJECT was forgeable even though its numbers were not.
#:
#: Two anchors, both immune to the redirect because they resolve against the repo root: the frames
#: directory must BE `<repo>/data/frames`, and each frozen file's sha256 must match its line in
#: `data/MANIFEST.sha256`. The same pattern was already used for the FWCI cases in this very file
#: (:493, :594) — the frames block simply never got it.
_MANIFEST_TEXT = (REPO / "data" / "MANIFEST.sha256").read_text(encoding="utf-8")
_MANIFEST_0828_TEXT = (REPO / "data" / "cal2026-08-28" / "MANIFEST.sha256").read_text(encoding="utf-8")


def _anchor_frozen(frozen: pathlib.Path) -> None:
    """The frozen operand is the SHIPPED, manifest-pinned artifact — not merely a file somewhere."""
    got = hashlib.sha256(frozen.read_bytes()).hexdigest()
    if frozen.parent.resolve() == FRAMES_0828.resolve():
        # 2026-09-23: the 08-28 copy — pinned in its own manifest AND exactly the bytes data/frames/ carried
        # for this frame until the promotion (the refreeze record's old_sha256): the very artifact the
        # pre-promotion proof compared against, not merely a file of the same name.
        assert FRAMES_0828.resolve() == (REPO / "data" / "cal2026-08-28" / "frames").resolve()
        assert f"{got}  data/cal2026-08-28/frames/{frozen.name}" in _MANIFEST_0828_TEXT, (
            f"{frozen.name} does not match its line in data/cal2026-08-28/MANIFEST.sha256 (sha256 {got}). "
            f"The frozen operand of this comparison is not the 2026-08-28 artifact.")
        assert got == _REFREEZE[frozen.name]["old_sha256"], (
            f"{frozen.name}: the 08-28 copy is not what data/frames/ held until the 2026-09-23 promotion")
        return
    assert frozen.name == "p3_afar_speed_bracket.csv" and \
        _REFREEZE[frozen.name]["old_sha256"] == _REFREEZE[frozen.name]["new_sha256"] == got, (
        f"{frozen.name} is anchored in data/frames/ (the October caliber) although it is not the one frame "
        f"the promotion left untouched — an 08-28 rebuild must be compared with data/cal2026-08-28/frames/")
    assert FRAMES.resolve() == (REPO / "data" / "frames").resolve(), (
        f"the frames directory under comparison is {FRAMES.resolve()}, not this repository's "
        f"{(REPO / 'data' / 'frames').resolve()}. The acceptance table would be about some other "
        f"directory; config/paths.yaml's `frames:` key (or $SAR_PATHS_CONFIG) has been redirected.")
    got = hashlib.sha256(frozen.read_bytes()).hexdigest()
    line = f"{got}  data/frames/{frozen.name}"
    assert line in _MANIFEST_TEXT, (
        f"{frozen.name} does not match its line in data/MANIFEST.sha256 (sha256 {got}). The frozen "
        f"operand of this comparison is not the shipped artifact.")


def _resolve_rebuilt(rb: Rebuild, rel: str, frozen: pathlib.Path) -> pathlib.Path:
    """`rb.root / rel`, proven to be a file this run produced and NOT the frozen file."""
    assert not rel.startswith("/") and ".." not in rel.split("/"), rel
    _producer_root_is_safe(rb.root)
    rebuilt = rb.root / rel
    assert rebuilt.is_file(), f"the stage did not produce {rel} under {rb.root}"
    assert rebuilt.resolve() != frozen.resolve(), (
        f"the 'rebuilt' file IS the frozen file: {rebuilt}")
    a, b = rebuilt.stat(), frozen.stat()
    assert (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino), (
        f"the 'rebuilt' file shares an inode with the frozen file - it is a hard link, not a build")
    assert a.st_mtime_ns >= rb.started_ns, (
        f"{rel} predates the run that was supposed to produce it "
        f"({a.st_mtime_ns} < {rb.started_ns}) - nothing was rebuilt in this test")
    if rb.produced is not None:
        want = rb.produced.get(str(rebuilt))
        assert want is not None, (
            f"the producer never reported writing {rel}. It announced "
            f"{sorted(pathlib.Path(k).name for k in rb.produced)} - a file that merely APPEARS in "
            f"the run directory is not a rebuild (probe V5).")
        got = hashlib.sha256(rebuilt.read_bytes()).hexdigest()
        assert got == want, (
            f"{rel} has changed since the producer wrote it: reported {want}, now {got}")
    return rebuilt


def _bytes_equal(rb: Rebuild, rel: str, frame: str, builder: str, rows=None) -> None:
    """The CSV half of the D1 criterion: sha256 of the whole file, nothing normalised."""
    frozen = _frozen_path(frame)
    _anchor_frozen(frozen)
    rebuilt = _resolve_rebuilt(rb, rel, frozen)
    before = (hashlib.sha256(frozen.read_bytes()).hexdigest(), frozen.stat().st_mtime_ns)
    r = content_equal(rebuilt, frozen)
    print(f"\n[rebuild] {frame}\n{r.detail}")
    _record(frame, builder, r, rows, rb.secs, rb.rss)
    assert r.mode == "bytes"
    assert r.equal, f"REBUILD DIFFERS FROM THE FROZEN FRAME - stop, do not adjust:\n{r.detail}"
    assert (hashlib.sha256(frozen.read_bytes()).hexdigest(),
            frozen.stat().st_mtime_ns) == before, "the frozen frame was modified by the rebuild"


def _content_equal(rb: Rebuild, rel: str, frame: str, builder: str, rows: int,
                   axis: tuple = ()) -> None:
    frozen = _frozen_path(frame)
    _anchor_frozen(frozen)
    rebuilt = _resolve_rebuilt(rb, rel, frozen)
    before = (hashlib.sha256(frozen.read_bytes()).hexdigest(), frozen.stat().st_mtime_ns)
    r = content_equal(rebuilt, frozen, accept_type_change=axis)
    print(f"\n[rebuild] {frame}\n{r.detail}")
    _record(frame, builder, r, f"{r.rows_a}/{r.rows_b}", rb.secs, rb.rss, axis)
    assert r.mode == "content"
    assert (r.rows_a, r.rows_b) == (rows, rows), (r.rows_a, r.rows_b)
    assert r.equal, f"REBUILD DIFFERS FROM THE FROZEN FRAME - stop, do not adjust:\n{r.detail}"
    assert tuple(r.accepted_schema_diff) == () if not axis else r.accepted_schema_diff
    assert (hashlib.sha256(frozen.read_bytes()).hexdigest(),
            frozen.stat().st_mtime_ns) == before, "the frozen frame was modified by the rebuild"


# --- the caliber rebuild (2026-08-28 freeze): ONE orchestrated run, T3's dependency order -------
# The stages are not independent under the caliber: the shadow must exist first, chem/math gold
# stages feed each other, the econ chain feeds the slims and the A_far build reads what p2-econ
# and p2-gold installed. So the module runs `tests/_cal_rebuild_driver.py` ONCE (a subprocess, the
# same evidence path as every launcher stage) and every acceptance case below draws its `Rebuild`
# from that run. The whole chain needs the legacy tree AND the data disk — absent either, the
# cases skip loudly and the acceptance-table test names the missing root.

_CAL_RUN_CACHE: dict = {}

#: 2026-09-23: two read-only legacy inputs were overwritten through a scratch shadow's hard links
#: (pipeline/NOT_REPRODUCIBLE.md, INCIDENT entry / index row 17; their restoration from the pinned
#: bytes is pending the author's hand). The 08-28 rebuild links the legacy files as they ARE, so the
#: fixture compares every frozen-link input of the shadow with the 08-28 staging manifest
#: (data/cal2026-08-28/frames/staging_manifest_2026-08-28.json) and tolerates a deviation ONLY on
#: these two documented files — a third one stops the proof. The two are tolerated because the
#: products were measured unchanged over the mutated bytes (this proof, 2026-09-23: 19 EQUAL /
#: 2 NOT EQUAL); a restored file simply drops out of the deviation set.
LEGACY_MUTATED_2026_09_23 = frozenset({"econ_fnfix_2026-08-15/data/edges_supplement_fnfix.jsonl",
                                       "econ_final_2026-08-13/patch/works_by_author.jsonl"})


@pytest.fixture(scope="module")
def cal_run():
    if "result" in _CAL_RUN_CACHE:
        if isinstance(_CAL_RUN_CACHE["result"], str):
            _skip_loudly(_CAL_RUN_CACHE["result"])
        return _CAL_RUN_CACHE["result"]
    import tempfile                                                          # noqa: PLC0415
    for needed in (V2 / "econ_fnfix_2026-08-15/data/analysis_frame_econ920_unified_fullsnap_2026-08-13.csv",
                   DERIVED / U1_ECON, DERIVED / U1_GOLD,
                   REPO / "data/cal2026-08-28/events_econ_cal.csv"):
        if not pathlib.Path(needed).exists():
            msg = f"SKIPPED-NO-SSD/INPUT: {needed} (the caliber rebuild needs the legacy tree and the data disk)"
            _CAL_RUN_CACHE["result"] = msg
            _skip_loudly(msg)
    # resolved, so the producers' own OK-report paths (which print resolved) key consistently
    root = pathlib.Path(tempfile.mkdtemp(prefix="sar_t7_cal_")).resolve()
    _SCRATCH_ROOTS.append(str(root))
    out_json = root.parent / (root.name + ".json")
    t0 = time.time()
    proc = subprocess.run([sys.executable, str(REPO / "tests/_cal_rebuild_driver.py"),
                           str(root), str(out_json)], cwd=REPO, capture_output=True, text=True)
    assert proc.returncode == 0, f"cal rebuild driver failed:\n{(proc.stdout + proc.stderr)[-6000:]}"
    assert "CAL_REBUILD_DONE" in proc.stdout, proc.stdout[-2000:]
    raw = _json.loads(out_json.read_text(encoding="utf-8"))
    result = {k: Rebuild(pathlib.Path(v["run_dir"]), v["started_ns"], v["secs"], None,
                         v["produced"])
              for k, v in raw.items() if not k.startswith("_")}
    result["_stats"] = {k: raw[k].get("stats") for k in raw if k.startswith("slim_")}
    result["_secs_total"] = round(time.time() - t0, 1)
    # 2026-09-23: the shadow's frozen-link inputs vs the 08-28 staging manifest (see LEGACY_MUTATED_2026_09_23)
    staged = _json.loads((FRAMES_0828 / "staging_manifest_2026-08-28.json").read_text(encoding="utf-8"))
    pinned = {e["rel"]: e["sha256"] for e in staged["entries"] if e["origin"].startswith("frozen:")}
    linked = raw["_shadow"]["frozen"]
    assert set(pinned) <= set(linked), sorted(set(pinned) - set(linked))
    deviations = {rel: (pinned[rel][:12], linked[rel][:12]) for rel in pinned if linked[rel] != pinned[rel]}
    if deviations:
        msg = (f"LEGACY INPUT(S) DIFFER FROM THE 08-28 STAGING MANIFEST (pinned -> linked): {deviations}. "
               f"The rebuild ran over these bytes; pipeline/NOT_REPRODUCIBLE.md index row 17.")
        print("\n*** " + msg)
        warnings.warn(msg, stacklevel=2)
    assert set(deviations) <= LEGACY_MUTATED_2026_09_23, (
        f"a legacy input other than the two documented 2026-09-23 mutations differs from the 08-28 "
        f"staging manifest — stop, do not adjust: {deviations}")
    result["_input_deviations"] = deviations
    print(f"\n[cal rebuild] whole caliber chain in {result['_secs_total']}s "
          f"({len(result) - 2} stages)")
    _CAL_RUN_CACHE["result"] = result
    return result


@pytest.mark.parametrize("field,rows", [("math_stats", 46010), ("chemistry", 39242),
                                        ("econ", 393007)])
def test_t7_the_five_cell_leftbehind_build_reproduces_the_three_afar_panels(cal_run, field,
                                                                           rows):
    """The paper's Panel 3, rebuilt by the FIVE-cell legacy script rather than the one-cell M1
    port. Recon listed these as REBUILDABLE-NOW from `build_afar.py`; what T7 adds is that the
    builder now in the repo is the whole `50_leftbehind_build.py`, so the A_far cut is produced by
    the same run that produces the counts table it is recorded in."""
    _content_equal(cal_run["afar"], f"data/pairs_slim_lb_{field}_A_far.parquet",
                   f"p3_afar_{field}.parquet", "50_leftbehind_build.py", rows)


def test_t7_the_five_cell_build_reproduces_the_counts_table_byte_for_byte(cal_run):
    """`p3_afar_counts.csv` is the frame recon said "cannot be regenerated by anything in the repo
    today" - the A_far-only port writes no counts table. It also carries the topic cuts (H5,
    recomputed at build time — they MOVED under the caliber because the dose tables did), so it is
    the file that pins the cell definition."""
    _bytes_equal(cal_run["afar"], "data/lb_counts.csv", "p3_afar_counts.csv",
                 "50_leftbehind_build.py", rows=15)
    cuts = {r["field"]: r["cut"] for r in _csv.DictReader(
        (FRAMES_0828 / "p3_afar_counts.csv").open(encoding="utf-8-sig"))}
    assert cuts == {"econ": "0.334", "chemistry": "0.3388", "math_stats": "0.0897"}
    # 2026-09-23: they moved again under the October caliber — data/frames/p3_afar_counts.csv is the October
    # sweep's lb_counts.csv (data/cal2026-10/frames_afar/afar_run_report.json, `cuts.med_<field>.cut`)
    cuts_oct = {r["field"]: r["cut"] for r in _csv.DictReader(
        (FRAMES / "p3_afar_counts.csv").open(encoding="utf-8-sig"))}
    assert cuts_oct == {"econ": "0.3402", "chemistry": "0.3558", "math_stats": "0.0807"}


def test_t7_the_tau_profile_reproduces_byte_for_byte(cal_run):
    """`60_lb_tau.py` — the only frame builder that needed no path hunk at all, and the second half
    of the `afar` stage because it reads the manifest the first half writes."""
    _bytes_equal(cal_run["afar"], "data/lb_tau_profile.csv", "p3_afar_tau_profile.csv",
                 "60_lb_tau.py", rows=156)


def test_t7_the_recovered_speed_bracket_producer_rebuilds_the_frozen_csv_byte_for_byte():
    """**Plan D2 item (iii) is wrong and this is the proof.** `p3_afar_speed_bracket.csv` was to be
    shipped as permanently unreproducible: `grep -rn speed_bracket` over the whole thesis tree
    returns only consumers, and the paper's 0.44-0.63 / 0.44-0.64 speed intervals rest on it. It
    was never a file — it ran as a heredoc at 2026-08-17T22:12:52.577Z, whose local time 08:12:52
    is the frozen file's mtime to the second.

    This stage deliberately still runs against the REAL (pre-caliber) legacy tree: the frozen
    speed bracket is the one frame the 2026-08-28 freeze left on the pre-caliber event set (no cal
    builder exists for its capped cells — CALIBER-STALE, pipeline/NOT_REPRODUCIBLE.md row 9), so
    the byte-identical rebuild of exactly that pre-caliber artifact is still the right claim."""
    _need(*[V2 / f"p3_topicpair_2026-08-17/data/{n}" for n in (
        "pairs_slim_cap_econ_ALL.parquet", "pairs_slim_cap_chemistry_ALL.parquet",
        "pairs_slim_cap_math_stats_ALL.parquet")])
    _bytes_equal(_run_frames_stage("speed"), "data/speed_bracket.csv",
                 "p3_afar_speed_bracket.csv", "speed_bracket.py [REC]", rows=9)


@pytest.mark.parametrize("tag,frame,rows", [("old79", "p1_frame_econ_old79.csv", 75746),
                                            ("new38", "p1_frame_econ_new37.csv", 42647)])
def test_t7_the_recovered_splitter_rebuilds_both_subsets_byte_for_byte(cal_run, tag, frame,
                                                                      rows):
    """The other producer recon called missing. Byte-equality here is the strong claim: it proves
    the order-preserving partition, the verbatim field text AND the CRLF, because a single wrong
    line ending anywhere would change the sha256. The comparison is deliberately NOT normalised —
    `tools/content_equal.py` hashes the whole file (test_case8 pins that CRLF stays visible).
    The recovered splitter's own output filename stays `..._new38.csv`; run on the caliber parent
    it holds the 37 surviving fn-fix events, frozen honestly as `p1_frame_econ_new37.csv`."""
    _bytes_equal(cal_run["split"], f"data/analysis_frame_econ_fnfix_{tag}.csv", frame,
                 "split_old79_new38.py [REC]", rows=rows)


def test_t7_the_two_subsets_still_partition_the_parent_exactly(cal_run):
    """The property the splitter encodes, checked on the frozen files rather than inferred from
    the code: 75,746 + 42,647 = 118,393 rows and 79 + 37 = 116 events, disjoint (the caliber
    removed A5044432173's event — 1,012 rows — from the parent and hence from the new-events side).
    2026-09-23: checked on the 08-28 files this proof rebuilds (data/cal2026-08-28/frames/) AND on the
    October canon now in data/frames/, with the October numbers pinned from their sources."""
    def _partition(root: pathlib.Path, rows: tuple, events: tuple) -> None:
        parent = list(_csv.DictReader((root / "p1_frame_econ.csv").open(encoding="utf-8")))
        old = list(_csv.DictReader((root / "p1_frame_econ_old79.csv").open(encoding="utf-8")))
        new = list(_csv.DictReader((root / "p1_frame_econ_new37.csv").open(encoding="utf-8")))
        assert (len(old), len(new), len(parent)) == rows, (len(old), len(new), len(parent))
        e_old = {r["event_id"] for r in old}
        e_new = {r["event_id"] for r in new}
        assert (len(e_old), len(e_new)) == events and not (e_old & e_new), (len(e_old), len(e_new))
        assert e_old | e_new == {r["event_id"] for r in parent}
        assert rows[0] + rows[1] == rows[2] and events[0] + events[1] == len(e_old | e_new)

    _partition(FRAMES_0828, (75746, 42647, 118393), (79, 37))
    # October: 44,209 + 28,864 = 73,073 rows (`rows_raw` of data/cal2026-10/estimates/P1_econ_fnfix_old79.json,
    # P1_econ_fnfix_new37.json and P1_econ_fnfix.json), 76 + 37 = 113 events (three of the pre-existing 79
    # dropped — `dropped` in data/cal2026-10/events_decision_2026-10.json; the 37 fn-fix events untouched)
    oct_rows = tuple(_json.loads((REPO / "data/cal2026-10/estimates" / f"{c}.json").read_text(encoding="utf-8"))["rows_raw"]
                     for c in ("P1_econ_fnfix_old79", "P1_econ_fnfix_new37", "P1_econ_fnfix"))
    assert oct_rows == (44209, 28864, 73073), oct_rows
    _partition(FRAMES, oct_rows, (76, 37))


def test_t7_the_event_ledger_rebuilds_byte_for_byte_without_touching_the_api(cal_run):
    """`01_merge_inputs.py`. Its OpenAlex branch (H11) is switched off the way the 2026-08-16 run
    switched it off — by the supplement JSONL being present — and the run output is asserted to
    say so, because a live re-fetch would be a different artifact, not a reproduction."""
    _bytes_equal(cal_run["ledger"], "data/event_ledger_fnfix.csv",
                 "p1_events_ledger_econ.csv", "01_merge_inputs.py", rows=116)


# --- the six slims, one build per field (inside the caliber chain) ------------------------------

#: (field, rows, the axis the NON-ev comparison declares). Rows are the caliber pair-panels'
#: (T3's pinned slim shapes). The axes are EMPTY since the 2026-08-28 freeze: the frozen slims are
#: now make_slim's own outputs, so there is no schema difference left to declare (see the block
#: comment above and the axes test below).
SLIM_CASES = [
    ("math_stats", 1353396, ()),
    ("chemistry", 4805989, ()),
    ("econ", 12108166, ()),
]


@pytest.mark.parametrize("field,rows,axis", SLIM_CASES)
def test_t7_one_slim_build_reproduces_both_frozen_slims_for_its_field(cal_run, field, rows, axis):
    """`pipeline/frames/make_slim.py` — M1's single implementation replacing six legacy copies.
    One build per field is compared TWICE: against the `_ev` slim (identical schema, no axis) and
    against the non-`ev` slim (fewer columns, one declared type axis).

    The build runs inside the caliber chain (the driver subprocess), reading the CAL pair table
    the chain just produced; its produced-set still comes from the builder's OWN `OK <path>
    (<n> B, sha256 …)` report (T7 final review NEW-2 — the evidence path that made the
    copy-the-frozen-file forgery inexpressible), parsed by the driver and re-hashed by
    `_resolve_rebuilt` here."""
    rb = cal_run[f"slim_{field}"]
    stats = cal_run["_stats"][f"slim_{field}"]
    assert stats["rows"] == rows

    _content_equal(rb, f"p3_slim_ev_{field}.parquet", f"p3_slim_ev_{field}.parquet",
                   "make_slim.py", rows)

    # the `ev` asymmetry: the builder projected onto the frozen file's column set, and the drop is
    # proven to be exactly `ev` rather than papering over a column difference.
    con = duckdb.connect()
    out = rb.root / f"p3_slim_ev_{field}.parquet"
    have = [c[0] for c in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{out}')").fetchall()]
    want = [c[0] for c in con.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{FRAMES_0828 / f'p3_slim_{field}.parquet'}')").fetchall()]
    assert [c for c in have if c != "ev"] == want, (have, want)
    assert stats["noev_columns"] == want, (stats["noev_columns"], want)
    _content_equal(rb, f"p3_slim_{field}.parquet", f"p3_slim_{field}.parquet",
                   "make_slim.py", rows, axis=axis)


def test_t7_the_declared_type_axes_are_the_three_the_frozen_schemas_actually_require():
    """Pre-freeze, this test pinned WHY each of the three axes existed, and its docstring said it
    would fail the day a re-freeze made them unnecessary — the outcome D1 said a later milestone
    may choose. The 2026-08-28 freeze chose it: all six frozen slims are now make_slim's own
    outputs, one schema, so the pin flips — NO axis may be declared, and the day a re-freeze
    reintroduces a legacy-schema slim this fails again in the other direction."""
    con = duckdb.connect()

    def schema(name):
        return tuple((c[0], c[1]) for c in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{FRAMES / name}')").fetchall())

    noev = (("grp", "INTEGER"), ("year", "INTEGER"), ("y", "TINYINT"), ("D", "TINYINT"))
    ev = (("grp", "INTEGER"), ("ev", "INTEGER"), ("year", "INTEGER"),
          ("y", "TINYINT"), ("D", "TINYINT"))
    for f in ("econ", "chemistry", "math_stats"):
        assert schema(f"p3_slim_{f}.parquet") == noev, f
        assert schema(f"p3_slim_ev_{f}.parquet") == ev, f
    declared = {(c, a, b) for _, _, axis in SLIM_CASES for (c, a, b) in axis}
    assert declared == set(), (
        "an accept_type_change axis is declared although the frozen slims share make_slim's "
        "schema — a declared axis with nothing to accept is a blind spot, remove it")


# --- p1-gold: the one place a rebuild does NOT match, reported rather than tuned ----------------
# Recon predicted "byte achievable" for all twelve CSV frames. For these two it is not achievable
# AT ALL, and the proof is that the builder does not agree with ITSELF: three independent runs of
# `20_rebuild_y_gold.py --field math_stats` produced 3,319,308 / 3,319,400 / 3,319,265 bytes, and
# three of chemistry produced 7,239,495 / 7,238,951 / 7,239,229. No run matched the frozen file.
#
# The mechanism is exact and is in the code, not in the environment. `20_rebuild_y_gold.py:152-166`
# materialises its per-work unit table with `.df()` from a DuckDB query that has no `ORDER BY`,
# under `PRAGMA threads=8`; line 189 then accumulates `a["ff_n"] += fc * val` in whatever order that
# parallel scan returned. Floating-point addition is not associative, so the last bits of the two
# ratio columns move with the scan schedule. That is hazard H1 — the licensed nondeterminism recon
# measured on the parquet side — reaching a CSV frame.
#
# The comparison is NOT relaxed and no tolerance is introduced (the T6 precedent for the chemistry
# suspects file). The byte verdict stands as NOT EQUAL and is recorded as such in the acceptance
# table; what these cases add is a complete characterisation, so that a difference of any OTHER
# kind — a different row, a different column, a fourth digit — still fails here.
#
# `04_rebuild_y.py` (econ) is byte-stable across three runs and matches the frozen file exactly,
# which is why this is a property of one builder rather than of the layer: its accumulation runs
# over `sorted(set(...))` and a JSONL read, not over an unordered parallel scan.

def _ulps(x: float, y: float) -> int:
    a, b = (struct.unpack("<q", struct.pack("<d", v))[0] for v in (x, y))
    return abs(a - b)


@pytest.mark.parametrize("field", ["chemistry", "math_stats"])
def test_t7_the_gold_p1_frame_is_not_byte_reproducible_and_the_difference_is_characterised(
        cal_run, field):
    """FINDING, not a pass. See the block comment above. Unchanged by the 2026-08-28 freeze: the
    caliber rebuild re-runs the same `20_rebuild_y_gold.py`, so the frozen CAL frame carries the
    same H1 float-accumulation nondeterminism — the driver runs the stage twice per field and the
    two runs must still disagree with each other and with the shipped frame, only in the two FWCI
    ratio columns, only by last-bit ULPs."""
    rb_a, rb_b = cal_run[f"p1_{field}_a"], cal_run[f"p1_{field}_b"]
    rel = f"data/fnfix/analysis_frame_{field}_new_gold_2026-08-10.csv"
    frozen = _frozen_path(f"p1_frame_{field}.csv")
    _anchor_frozen(frozen)
    # the same provenance proof every EQUAL case gets: really produced, really not the frozen file
    a = _resolve_rebuilt(rb_a, rel, frozen)
    b = _resolve_rebuilt(rb_b, rel, frozen)

    r = content_equal(a, frozen)
    print(f"\n[rebuild] p1_frame_{field}.csv\n{r.detail}")
    _record(f"p1_frame_{field}.csv", "20_rebuild_y_gold.py", r, None, rb_a.secs, rb_a.rss,
            note="float accumulation order; characterised below")
    assert not r.equal, ("this rebuild now MATCHES the frozen frame. That is a change in behaviour, "
                         "not a fix: re-measure the three-run stability before recording it.")

    # (1) unreachable, not merely unachieved: the builder disagrees with itself
    assert not content_equal(a, b).equal, (
        "two independent runs agreed byte for byte. If that is now reproducible the finding "
        "changes and the acceptance criterion for this frame should be revisited with the author.")

    # (2) the difference is confined to the two FWCI ratio columns and to nothing else
    rows_a = list(_csv.DictReader(a.open(encoding="utf-8")))
    rows_f = list(_csv.DictReader(frozen.open(encoding="utf-8")))
    assert len(rows_a) == len(rows_f)
    assert list(rows_a[0]) == list(rows_f[0])
    differing = {k for x, y in zip(rows_a, rows_f) for k in x if x[k] != y[k]}
    assert differing == {"fwci_frac", "fwci_frac_ex_star"}, differing

    # (3) and every difference is last-bit noise, measured in ULPs rather than asserted
    worst_ulp, worst_rel = 0, 0.0
    for x, y in zip(rows_a, rows_f):
        for k in ("fwci_frac", "fwci_frac_ex_star"):
            if x[k] == y[k]:
                continue
            u, v = float(x[k]), float(y[k])
            worst_ulp = max(worst_ulp, _ulps(u, v))
            worst_rel = max(worst_rel, abs(u - v) / max(abs(u), abs(v), 1e-300))
    print(f"[finding] p1_frame_{field}.csv: worst {worst_ulp} ULP, relative {worst_rel:.3g}")
    assert 0 < worst_ulp <= 8 and worst_rel <= 1e-14, (worst_ulp, worst_rel)


@pytest.mark.parametrize("field", ["chemistry", "math_stats"])
def test_t7_the_gold_p2_becoming_panel_rebuilds_byte_for_byte(cal_run, field):
    """Recon's strongest byte target: `30_build_panels23_gold.py:233` copies with an explicit
    `ORDER BY event_id, pid, year`, so this one is thread-count independent even though the same
    script's parquet writes are not (H1)."""
    _bytes_equal(cal_run[f"p2_{field}"], f"data/fnfix/panels23_{field}_gold/becoming_none.csv",
                 f"p2_becoming_{field}.csv", "30_build_panels23_gold.py")


def test_t7_the_econ_p2_becoming_panel_rebuilds_byte_for_byte(cal_run):
    """`10_panels23_econ920.py`. It also re-emits the 663 MB `pairs_unified.csv` that every econ
    slim and the econ A_far cell read, which is why this stage closes the layer's one dependency
    on an intermediate the package does not ship."""
    _bytes_equal(cal_run["p2_econ"], "data/becoming_unified.csv",
                 "p2_becoming_econ.csv", "10_panels23_econ920.py", rows=180148)


def test_t7_the_econ_p1_frame_rebuilds_byte_for_byte(cal_run):
    """The most expensive frame in the layer and the one with the acknowledged float32
    round-trip tolerance in its own source (H8, `REPRO_F32_TOL = 1e-6`). The comparison here does
    NOT use that tolerance: it is the sha256 of the whole file."""
    _bytes_equal(cal_run["p1_econ"],
                 "data/analysis_frame_econ920_unified_fullsnap_2026-08-13.csv",
                 "p1_frame_econ.csv", "04_rebuild_y.py", rows=118393)


#: THE ACCEPTANCE TABLE, pinned (T7 review MAJOR-1b). Every other ledger in this repository is a
#: checked object - `PATCHED`, `RECOVERED`, `REPO_AUTHORED`, `N_PORTED_MANIFEST`, `LOST_INPUTS`.
#: This one was a print statement, so the milestone's headline number lived only in stdout and a
#: one-line edit could write whatever it liked into it. It is now the same kind of object as the
#: rest: frame -> (builder, comparison mode, verdict), asserted against what the cases actually
#: produced. Changing a verdict here is a deliberate, reviewable diff.
EXPECTED_ACCEPTANCE: dict[str, tuple[str, str, str]] = {
    "p3_afar_econ.parquet":            ("50_leftbehind_build.py", "content", "EQUAL"),
    "p3_afar_chemistry.parquet":       ("50_leftbehind_build.py", "content", "EQUAL"),
    "p3_afar_math_stats.parquet":      ("50_leftbehind_build.py", "content", "EQUAL"),
    "p3_afar_counts.csv":              ("50_leftbehind_build.py", "bytes",   "EQUAL"),
    "p3_afar_tau_profile.csv":         ("60_lb_tau.py",           "bytes",   "EQUAL"),
    "p3_afar_speed_bracket.csv":       ("speed_bracket.py [REC]", "bytes",   "EQUAL"),
    "p1_frame_econ_old79.csv":         ("split_old79_new38.py [REC]", "bytes", "EQUAL"),
    "p1_frame_econ_new37.csv":         ("split_old79_new38.py [REC]", "bytes", "EQUAL"),
    "p1_events_ledger_econ.csv":       ("01_merge_inputs.py",     "bytes",   "EQUAL"),
    "p3_slim_ev_econ.parquet":         ("make_slim.py",           "content", "EQUAL"),
    "p3_slim_ev_chemistry.parquet":    ("make_slim.py",           "content", "EQUAL"),
    "p3_slim_ev_math_stats.parquet":   ("make_slim.py",           "content", "EQUAL"),
    "p3_slim_econ.parquet":            ("make_slim.py",           "content", "EQUAL"),
    "p3_slim_chemistry.parquet":       ("make_slim.py",           "content", "EQUAL"),
    "p3_slim_math_stats.parquet":      ("make_slim.py",           "content", "EQUAL"),
    "p2_becoming_chemistry.csv":       ("30_build_panels23_gold.py", "bytes", "EQUAL"),
    "p2_becoming_math_stats.csv":      ("30_build_panels23_gold.py", "bytes", "EQUAL"),
    "p2_becoming_econ.csv":            ("10_panels23_econ920.py", "bytes",   "EQUAL"),
    "p1_frame_econ.csv":               ("04_rebuild_y.py",        "bytes",   "EQUAL"),
    # the two the layer does NOT reproduce byte for byte. Pinned as NOT EQUAL on purpose: the day a
    # rebuild matches, this fails and the finding is revisited rather than quietly disappearing.
    "p1_frame_chemistry.csv":  ("20_rebuild_y_gold.py", "bytes", "NOT EQUAL"),
    "p1_frame_math_stats.csv": ("20_rebuild_y_gold.py", "bytes", "NOT EQUAL"),
}
#: the characterisation that goes WITH a verdict and cannot substitute for one. Kept apart from
#: `EXPECTED_ACCEPTANCE` because the T7 final review's second smuggle was to write the finding into
#: the verdict slot: prose there is unfalsifiable, prose here is a separate, separately pinned claim.
EXPECTED_NOTES: dict[str, str] = {
    "p1_frame_chemistry.csv":  "float accumulation order; characterised below",
    "p1_frame_math_stats.csv": "float accumulation order; characterised below",
}
N_FRAMES = 21
N_EQUAL = 19
#: frozen in data/frames/ but produced by ANALYSIS code, not by a frames-layer stage: the 2026-08-30
#: Panel 3 respecification cuts (`pos` = the paper's cell, `med` = the control that reproduces the
#: `afar` stage's frames exactly), built by analysis/robustness/p3_afar_cuts/build_afar_cut.py and
#: pinned in tests/test_afar_cuts_2026_08_30.py. Declared apart on 2026-09-10 the way the
#: `p3_slim_*` files are declared as make_slim.py outputs below, so the acceptance table above keeps
#: counting only what the frames layer itself rebuilds.
DERIVED_FRAMES = frozenset({f"p3_afar_{s}_{f}.parquet" for s in ("pos", "med")
                            for f in ("econ", "chemistry", "math_stats")} | {"p3_afar_counts_by_spec.csv"})
#: 2026-09-23: the files the October promotion ADDED to data/frames/ — `old_sha256: null` in
#: data/cal2026-10/expected_refreeze_2026-10.json, "New files" in data/frames/README.md — assembled by
#: pipeline/frames/cal2026-10/assemble_frames.py from data/cal2026-10/frames_variants/ (the D7 variant slims)
#: and the October per-discipline freezes (data/cal2026-10/frames/assembly_2026-10.json). No frames-layer
#: stage produces any of them, so they are declared apart as a NAMED set (checked against the refreeze
#: record in the acceptance-table test), the way DERIVED_FRAMES is — never a silent widening.
CAL2026_10_ADDITIONS = frozenset({f"p3_slim_{f}_{v}.parquet" for f in ("econ", "chemistry", "math_stats")
                                  for v in ("p05", "dosebin3")}
                                 | {"relationships_econ.csv", "pairs_none_chemistry.parquet",
                                    "pairs_none_math_stats.parquet"})


def test_t8_the_acceptance_verdict_is_derived_from_the_comparison_not_supplied(monkeypatch):
    """T7 final review NEW-1, closed. The verdict used to be a free string parameter.

    Three claims, each falsifiable on its own:

    1. `_record` has no verdict parameter at all - the smuggle is now inexpressible, not merely
       discouraged. Checked on the live signature, so renaming a keyword does not evade it.
    2. The derivation is total and correct over both states: an unequal result records "NOT EQUAL"
       and an equal one records "EQUAL", whatever prose the caller attaches as a note.
    3. A note cannot become a verdict: it lands in a separate dict that the acceptance comparison
       never reads, and `EXPECTED_ACCEPTANCE` may only hold values the derivation can produce
       (asserted in the acceptance test itself).

    Together with (3) this is what makes the three-edit forgery fail: flipping the two pinned
    entries to "EQUAL" no longer agrees with what the cases record, because what they record comes
    from `content_equal`.
    """
    import inspect
    params = inspect.signature(_record).parameters
    assert "verdict" not in params, "the verdict is a caller-supplied parameter again"
    assert set(params) == {"frame", "builder", "result", "rows", "secs", "rss", "axis", "note"}, \
        sorted(params)

    class _Stub:
        def __init__(self, equal, mode="bytes"):
            self.equal, self.mode = equal, mode

    monkeypatch.setattr(sys.modules[__name__], "ACCEPTANCE", {})
    monkeypatch.setattr(sys.modules[__name__], "ACCEPTANCE_NOTES", {})
    _record("f_false.csv", "b.py", _Stub(False), note="a characterisation, not a verdict")
    _record("f_true.csv", "b.py", _Stub(True))
    assert ACCEPTANCE["f_false.csv"]["verdict"] == "NOT EQUAL"
    assert ACCEPTANCE["f_true.csv"]["verdict"] == "EQUAL"
    assert ACCEPTANCE_NOTES == {"f_false.csv": "a characterisation, not a verdict"}
    # the note is recorded elsewhere and leaves the verdict alone - that separation IS the fix
    assert "verdict" not in ACCEPTANCE["f_false.csv"] or \
        ACCEPTANCE["f_false.csv"]["verdict"] == "NOT EQUAL"
    assert set(ACCEPTANCE) & set(ACCEPTANCE_NOTES) == {"f_false.csv"}

    # and a result that is not a comparison result is refused rather than coerced
    with pytest.raises(TypeError):
        _record("f_bad.csv", "b.py", _Stub("EQUAL"))
    with pytest.raises(ValueError):
        _record("f_bad.csv", "b.py", _Stub(True, mode="whatever"))


def test_t7_the_acceptance_table_is_a_checked_object_not_a_print_statement():
    """M3's acceptance number, asserted. Three claims, each falsifiable:

    1. `data/frames/` holds exactly `N_FRAMES` frames-layer files (the `DERIVED_FRAMES` of
       build_afar_cut.py and the `CAL2026_10_ADDITIONS` of the 2026-09-23 promotion are declared apart)
       and the pin names exactly those — each of which exists under the same name in the 08-28 canon
       the comparisons read (data/cal2026-08-28/frames/), bar the one pre-caliber frame;
    2. `N_EQUAL` of them are pinned EQUAL - so "19 of 21" is a checked count, not prose;
    3. what the twenty cases above ACTUALLY recorded equals the pin, builder and mode included.

    (3) is the one that matters: `ACCEPTANCE` is populated by the comparison helpers, which now
    build the rebuilt path from the producing run rather than accepting one (see the MAJOR-1 block),
    so a case cannot report a verdict for a comparison it did not make. Run the whole `-k t7`
    selection - a partial selection leaves the table partial and this test says so."""
    # 2026-09-23: the declared additions are exactly the frames the promotion created (the refreeze
    # record has no pre-promotion hash for them), and every one of them is really in data/frames/
    assert CAL2026_10_ADDITIONS == {n for n, v in _REFREEZE.items() if v["old_sha256"] is None}
    assert all((FRAMES / n).is_file() for n in CAL2026_10_ADDITIONS)
    frozen = sorted(f.name for f in FRAMES.iterdir()
                    if f.is_file() and f.suffix in (".csv", ".parquet")
                    and f.name not in DERIVED_FRAMES and f.name not in CAL2026_10_ADDITIONS)
    assert len(frozen) == N_FRAMES, frozen
    assert set(EXPECTED_ACCEPTANCE) == set(frozen), set(frozen) ^ set(EXPECTED_ACCEPTANCE)
    assert all(_frozen_path(n).is_file() for n in frozen), [n for n in frozen if not _frozen_path(n).is_file()]
    assert {n for n in frozen if _frozen_path(n).parent != FRAMES_0828} == {"p3_afar_speed_bracket.csv"}
    assert sum(1 for v in EXPECTED_ACCEPTANCE.values() if v[2] == "EQUAL") == N_EQUAL
    # every pinned verdict must be one the derivation can actually produce: prose in this slot is
    # what let the T7-final smuggle print "21 EQUAL" over an unequal comparison.
    assert {v[2] for v in EXPECTED_ACCEPTANCE.values()} <= set(_VERDICT.values()), sorted(
        {v[2] for v in EXPECTED_ACCEPTANCE.values()} - set(_VERDICT.values()))
    assert set(EXPECTED_NOTES) == {k for k, v in EXPECTED_ACCEPTANCE.items() if v[2] != "EQUAL"}

    got = {k: (v["builder"], v["mode"], v["verdict"]) for k, v in ACCEPTANCE.items()}
    missing = sorted(set(EXPECTED_ACCEPTANCE) - set(got))
    if missing:
        # MILESTONE REVIEW, replicator-experience MAJOR: this used to assert a diagnosis
        # ("run the whole selection") that is wrong for the case that actually happens. On a
        # replicator's machine the comparisons do not run at all — the legacy tree and the data
        # disk are absent — and the acceptance claim collapses to zero comparisons while the
        # message blames the pytest selection. Name the real cause, and do not pretend the result.
        v2, disk = P["legacy_thesis"] / "v2_output", DERIVED
        absent = [f"the legacy tree at {v2}" for _ in (1,) if not v2.is_dir()]
        absent += [f"the data disk at {disk}" for _ in (1,) if not disk.is_dir()]
        if absent:
            pytest.skip(
                f"THE M3 ACCEPTANCE RESULT DID NOT RUN HERE. {len(missing)} of {N_FRAMES} frames "
                f"were never compared because this machine is missing " + " and ".join(absent) +
                f". The '{N_EQUAL} of {N_FRAMES} EQUAL' claim is AUTHOR-ONLY: it rebuilds the "
                f"frames from upstream intermediates this package does not ship "
                f"(pipeline/MANIFEST_intermediates.md §1). Nothing here is a pass.")
        assert not missing, (
            f"{len(missing)} frame(s) were never compared in this run: {missing}\n"
            f"Both roots are present, so this is a PARTIAL SELECTION, not a missing input. "
            f"Run the whole selection:\n"
            f"    setup/.venv/bin/python -m pytest -q tests/test_pipeline_rebuild.py -k t7")
    assert got == EXPECTED_ACCEPTANCE, {
        k: {"recorded": got.get(k), "pinned": EXPECTED_ACCEPTANCE[k]}
        for k in sorted(EXPECTED_ACCEPTANCE) if got.get(k) != EXPECTED_ACCEPTANCE[k]}
    assert ACCEPTANCE_NOTES == EXPECTED_NOTES, {"recorded": ACCEPTANCE_NOTES,
                                                "pinned": EXPECTED_NOTES}

    print("\n=== T7 acceptance table ===")
    for name in frozen:
        row = ACCEPTANCE[name]
        note = ACCEPTANCE_NOTES.get(name, "")
        print(f"  {name:32s} {row['builder']:28s} {row['mode']:7s} {row['verdict']}"
              + (f"  ({note})" if note else ""))
    print(f"  -> {N_EQUAL} EQUAL / {N_FRAMES - N_EQUAL} NOT EQUAL / 0 skipped, of {N_FRAMES}")


# ==============================================================================================
# 9. T8 - the pipeline entry point, its stage inventory, and the registers
# ==============================================================================================

def _stages_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("sar_stages", REPO / "pipeline/lib/stages.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sar_stages"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_t8_the_run_all_stage_list_is_read_from_the_launchers_not_copied_beside_them():
    """`pipeline/run_all.sh` must not hold a stage list of its own.

    Two declarations of the same thing is how this repository has been bitten twice: the driver
    coverage test was a substring search over a file whose own docstring satisfied it, and the frames
    acceptance table was a hand-written list of cases. So the entry point reads `STAGES` out of each
    launcher through `pipeline/lib/stages.py`, and this asserts three things about that arrangement:
    the shell script names no stage, every gated stage is classified, and no classification is stale.
    """
    stages = _stages_module()
    sh = (REPO / "pipeline/run_all.sh").read_text(encoding="utf-8")
    assert "pipeline.lib.stages" in sh, "run_all.sh no longer reads the inventory"

    inventory = stages.inventory()
    names = {stage for _layer, stage, _k, _r in inventory}
    assert len(names) > 15, inventory
    # the script may mention a LAYER (it is a --stage choice) but never an individual stage name
    layers = {layer for layer, _rel in stages.LAYERS}
    body = "\n".join(ln for ln in sh.splitlines() if not ln.lstrip().startswith("#"))
    # a hard-coded list would appear as QUOTED tokens (a case label, an array element); the prose
    # in the cost warnings is allowed to use the English word, and does.
    leaked = sorted(n for n in names - layers if f'"{n}"' in body or f"'{n}'" in body)
    assert leaked == [], f"run_all.sh hard-codes stage name(s) {leaked} instead of reading them"
    # and the plan really does come from the module, not from anything in the script
    assert '--plan "$CLASSES"' in sh and "PLAN=" in sh

    unclassified = [(l, s) for l, s, k, _r in inventory if k == "UNCLASSIFIED"]
    assert unclassified == [], (
        f"gated stage(s) with no cost class in pipeline/lib/stages.py::COST_CLASS: {unclassified}. "
        f"A stage that is off by default must say WHICH kind of off it is - the flag that turns it "
        f"on depends on it.")
    gated = {f"{l}:{s}" for l, s, k, _r in inventory if k != "default"}
    assert set(stages.COST_CLASS) == gated, {
        "classified but no longer gated": sorted(set(stages.COST_CLASS) - gated),
        "gated but unclassified": sorted(gated - set(stages.COST_CLASS))}
    assert set(stages.COST_CLASS.values()) <= {"ssd", "long", "api"}, stages.COST_CLASS
    assert set(stages.NO_EXECUTE) <= gated, sorted(set(stages.NO_EXECUTE) - gated)
    # T8 review MAJOR-1: what a stage NEEDS is now its own declared axis, covering EVERY stage.
    all_keys = {f"{l}:{s}" for l, s, _k, _r in inventory}
    assert set(stages.REQUIRES) == all_keys, {
        "declared but gone": sorted(set(stages.REQUIRES) - all_keys),
        "undeclared": sorted(all_keys - set(stages.REQUIRES))}
    assert all(reqs <= {"legacy", "disk"} for reqs in stages.REQUIRES.values()), stages.REQUIRES


def _probe_config(tmp_path: pathlib.Path, **overrides) -> pathlib.Path:
    """A copy of `config/paths_october.yaml` with some roots repointed at empty directories.

    Used through `$SAR_PATHS_CONFIG`, which both `analysis/lib/paths.py` and `pipeline/lib/paths.py`
    honour, so the whole repository moves together. Rewriting the tracked config from inside a test
    would work too and is what the reviewer did by hand; a switch is safer, because a test that dies
    between the edit and the restore leaves a broken checkout.
    """
    text = (REPO / "config" / "paths_october.yaml").read_text(encoding="utf-8")
    for key, value in overrides.items():
        pathlib.Path(value).mkdir(parents=True, exist_ok=True)
        text, n = _re.subn(rf'^({key}: )"[^"]*"', lambda m: m.group(1) + f'"{value}"', text,
                           flags=_re.M)
        assert n == 1, f"{key} is not a quoted top-level key in config/paths.yaml"
    cfg = tmp_path / f"paths_{'_'.join(sorted(overrides))}.yaml"
    cfg.write_text(text, encoding="utf-8")
    return cfg


def _default_plan_outcome(cfg: pathlib.Path, tmp_path: pathlib.Path) -> dict[str, bool]:
    """Run every DEFAULT-class stage under `cfg` and return `{"layer/stage": succeeded}`."""
    env = {**os.environ, "SAR_PATHS_CONFIG": str(cfg)}
    for var in ("SAR_SSD_ROOT", "SAR_LEGACY_MULTIPLEX", "SAR_LEGACY_THESIS", "SAR_OUT_ROOT"):
        env.pop(var, None)                 # an override would defeat the point of the probe
    # $SAR_OUT_ROOT is deliberately NOT set: each launcher then uses its own git-ignored scratch
    # under output/, which is what a real run does. Pointing it at a fresh tmp dir made `fwci/build`
    # fail for a reason that had nothing to do with the missing root, and the first draft of this
    # test recorded that as "fwci/build needs the legacy tree" - the measurement measuring itself.
    r = subprocess.run(["bash", str(REPO / "pipeline/run_all.sh"), "--no-proof"],
                       cwd=REPO, capture_output=True, text=True, env=env)
    out = {}
    for line in r.stdout.splitlines():
        m = _re.match(r"\s+(OK|FAILED)\s+(\S+)\s", line)
        if m:
            out[m.group(2)] = m.group(1) == "OK"
    assert out, f"the run reported no stages:\n{(r.stdout + r.stderr)[-3000:]}"
    return out



@pytest.mark.skipif(
    not ((P["legacy_thesis"] / "v2_output").is_dir() and P["ssd_root"].is_dir()),
    reason="this probe TAKES A ROOT AWAY and asserts exactly the declared stages fail; on a machine "
           "that has neither root to begin with, every stage fails in both arms and the measurement "
           "says nothing. It is the author-side check that the declaration matches reality.")
@pytest.mark.skipif(
    not ((P["legacy_thesis"] / "v2_output").is_dir() and P["ssd_root"].is_dir()),
    reason="this probe TAKES A ROOT AWAY and asserts exactly the declared stages fail; on a machine "
           "that has neither root to begin with, every stage fails in both arms and the measurement "
           "says nothing. It is the author-side check that the declaration matches reality.")
def test_t8fix_what_the_default_stages_need_is_MEASURED_not_declared_against_itself(tmp_path):
    """T8 review MAJOR-1 + MAJOR-2, closed together.

    The test this replaces asserted ``{row[3] for row in default} == {"default"}`` — the cost class
    the plan had just filtered on. It could only fail if `plan()` were broken, never if a
    `default`-class stage read the data disk, and it passed green on a commit where three of them
    did and fourteen needed the legacy tree that three documents said was unnecessary. That is the
    THIRD time in M3 a second declaration has been checked against itself (T2-R5, T7 MAJOR-1), so
    this one is measured instead: the real stages are run, twice, with a root taken away.

    Each probe repoints one root at an EMPTY directory through `$SAR_PATHS_CONFIG` and requires the
    outcome to match `pipeline/lib/stages.py::REQUIRES` exactly — in both directions. A stage that
    quietly stops needing the disk fails this as loudly as one that starts.

    Measured on 2026-08-26 and pinned below: no legacy tree -> 1 of 15 survives; no data disk ->
    12 of 15 survive; repo-only stages: NONE.
    """
    from pipeline.lib.stages import REQUIRES

    declared = {f"{l}/{s}": REQUIRES[f"{l}:{s}"] for l, s, k, _r in _stages_module().inventory()
                if k == "default"}
    assert len(declared) == 15, sorted(declared)

    for missing, key, root in (("legacy", "legacy_v2_output", tmp_path / "no_legacy/v2_output"),
                               ("disk", "ssd_root", tmp_path / "no_disk/openalex_pipeline")):
        extra = {}
        if missing == "legacy":               # the two legacy keys move together or not at all
            extra = {"legacy_thesis": str(tmp_path / "no_legacy"),
                     "legacy_multiplex": str(tmp_path / "no_legacy/multiplex_pipeline")}
        cfg = _probe_config(tmp_path, **{key: str(root)}, **extra)
        got = _default_plan_outcome(cfg, tmp_path)
        assert set(got) == set(declared), set(got) ^ set(declared)

        should_fail = {name for name, reqs in declared.items() if missing in reqs}
        did_fail = {name for name, ok in got.items() if not ok}
        assert did_fail == should_fail, {
            "missing": missing,
            "declared as needing it but SURVIVED": sorted(should_fail - did_fail),
            "not declared as needing it but FAILED": sorted(did_fail - should_fail),
            "note": "REQUIRES in pipeline/lib/stages.py is now wrong; fix the declaration, and "
                    "fix whatever document repeats it (README.md, pipeline/run_all.sh's header).",
        }
        print(f"[measured] no {missing}: {len(got) - len(did_fail)} of {len(got)} default stages "
              f"survive; failing = {sorted(did_fail)}")

    # the headline the documents must not contradict: NOTHING in the default set is repo-only
    repo_only = sorted(n for n, reqs in declared.items() if not reqs)
    assert repo_only == [], (
        f"{repo_only} are now repo-only. That is good news and it changes the README: the default "
        f"run would finally have a self-contained subset. Update the docs before relaxing this.")


def test_t8fix_the_documents_state_the_measured_requirement_rather_than_the_old_claim():
    """The three places the review found the false claim, pinned so it cannot come back as prose.

    Documentation is not usually testable, but this particular sentence was wrong in three files at
    once and the code was right — so what is checked is the AGREEMENT: every document must name the
    same counts the declaration carries, and must not contain the phrases that were false.
    """
    from pipeline.lib.stages import REQUIRES

    default = {f"{l}:{s}" for l, s, k, _r in _stages_module().inventory() if k == "default"}
    n_legacy = sum(1 for k in default if "legacy" in REQUIRES[k])
    n_disk = sum(1 for k in default if "disk" in REQUIRES[k])
    assert (len(default), n_legacy, n_disk) == (15, 14, 3), (len(default), n_legacy, n_disk)

    readme = (REPO / "README.md").read_text(encoding="utf-8")
    sh = (REPO / "pipeline/run_all.sh").read_text(encoding="utf-8")
    manifest = (REPO / "pipeline/MANIFEST_intermediates.md").read_text(encoding="utf-8")

    for text, name in ((readme, "README.md"), (sh, "pipeline/run_all.sh")):
        for banned in ("nothing beyond this repo", "No data disk.",
                       "default run needs none of it"):
            assert banned not in text, f"{name} still claims {banned!r} (T8 review MAJOR-1)"
        assert f"{n_legacy} of the 15 default stages" in text or \
               f"{n_legacy} of 15" in text, f"{name} does not state the measured legacy count"
    assert "self-contained" in readme.lower() and "not self-contained" in sh
    assert "legacy tree is an input" in manifest or "not an output" in manifest

    # MILESTONE REVIEW, process MAJOR: pipeline/README.md's verbatim-rule paragraph stated port
    # counts two tasks out of date. Derive them from the constants so a future move breaks the doc.
    import importlib.util
    spec = importlib.util.spec_from_file_location("sar_verbatim_counts",
                                                  REPO / "tests/test_verbatim_pipeline.py")
    v = importlib.util.module_from_spec(spec)
    sys.modules["sar_verbatim_counts"] = v
    spec.loader.exec_module(v)
    pr = (REPO / "pipeline/README.md").read_text(encoding="utf-8")
    for phrase in (f"**{v.N_IDENTICAL} of the {v.N_WITH_COUNTERPART}** ported files",
                   f"The other **{v.N_PATCHED}**",
                   f"({v.N_REPO_AUTHORED} of them)",
                   f"A further **{len(v.RECOVERED)}** files are RECOVERED"):
        assert phrase in pr, (
            f"pipeline/README.md no longer states {phrase!r}. The port counts live in "
            f"tests/test_verbatim_pipeline.py; move the doc in the same commit.")


def test_t8_the_default_plus_ssd_plan_covers_every_frozen_frame():
    """The other half of the old test, kept because it is not circular: `default + ssd` must between
    them rebuild every frozen frame the frames layer claims to rebuild, so "run it with the disk and
    all 21 are checked" is a fact about the plan. (The half that WAS circular - "the default plan
    needs no data disk" asserted against the class it filtered on - is replaced by the measured test
    above.)"""
    stages = _stages_module()
    import importlib.util
    spec = importlib.util.spec_from_file_location("sar_frames_launcher",
                                                  REPO / "pipeline/frames/run_frames.py")
    frames_mod = importlib.util.module_from_spec(spec)
    sys.modules["sar_frames_launcher"] = frames_mod
    spec.loader.exec_module(frames_mod)

    with_ssd = stages.plan({"default", "ssd"}, layers={"frames"})
    covered = set()
    for row in with_ssd:
        covered |= set(frames_mod.STAGES[row[2]].frames)
    frozen = {f.name for f in FRAMES.iterdir() if f.is_file() and f.suffix in (".csv", ".parquet")}
    frozen -= DERIVED_FRAMES                                      # build_afar_cut.py is analysis code, not a stage
    frozen -= CAL2026_10_ADDITIONS                                # 2026-09-23: the promotion's additions — no stage produces them (declared set, see its comment)
    slims = {n for n in frozen if n.startswith("p3_slim")}       # make_slim is a library, not a stage
    assert covered == frozen - slims, {
        "declared but not frozen": sorted(covered - frozen),
        "frozen but no stage rebuilds it": sorted(frozen - slims - covered)}
    assert len(stages.EXTRA_ARGS["frames:p1-gold"]) == 2


def test_t8_no_aws_step_and_no_17h_fetch_is_reachable_from_the_entry_point():
    """The cost discipline, mechanically. Three claims:

    1. `run_all.sh` contains no `aws` command and no reference to either launch script;
    2. the two launch scripts cannot launch anything - every `aws ec2` line in them is inside a
       quoted here-document, so running one prints its runbook and exits 0;
    3. the U1 fetch is not a stage in any launcher, so no flag can select it.
    """
    sh = (REPO / "pipeline/run_all.sh").read_text(encoding="utf-8")
    # T8 review NIT-7: this used to be `A or B` with B always true, so A was dead. The substantive
    # claim is that no line of the script INVOKES aws - the header prose may say the word.
    body = "\n".join(ln for ln in sh.splitlines() if not ln.lstrip().startswith("#"))
    assert "aws " not in body and "aws\t" not in body, body
    assert "launch_p3_dcdh" not in sh and "launch_u1_fetch" not in sh

    for name in ("launch_p3_dcdh.sh", "launch_u1_fetch.sh"):
        script = REPO / "pipeline/aws" / name
        text = script.read_text(encoding="utf-8")
        assert "<<'RUNBOOK'" in text, f"{name} no longer wraps its commands in a quoted heredoc"
        body, _sep, rest = text.partition("<<'RUNBOOK'")
        assert "aws ec2" not in body, f"{name} has an aws command OUTSIDE the heredoc"
        assert rest.rstrip().endswith("RUNBOOK"), f"{name} does not end inside the heredoc"
        r = subprocess.run(["bash", str(script)], cwd=REPO, capture_output=True, text=True)
        assert r.returncode == 0 and "documentation; nothing here is executed" in r.stdout
        for must in ("us-east-1", "instance", "cost"):
            assert must in r.stdout.lower(), (name, must)

    # (3) no launcher registers the U1 fetch as a stage, so no flag can select it. Checked on the
    # SCRIPT each stage runs, not on its name - `stars prefetch` contains the word and is a
    # live-API star-works cache, not the snapshot fetch.
    stages = _stages_module()
    for layer, rel in stages.LAYERS:
        mod = stages._load(rel)
        for stage, spec in mod.STAGES.items():
            script = spec[0] if layer == "fwci" else spec.script
            assert "run_m1_full" not in script and "u1_fetch" not in script, (layer, stage, script)
    assert "run_m1_full" not in sh and "u1_fetch" not in sh


def test_t8_the_registers_are_complete_and_agree_with_the_machine_checked_ledgers():
    """The consolidation, checked rather than asserted in prose.

    Every artifact the code declares lost or producerless must have an entry in the ONE register, and
    the register's index must not name entries that no longer exist. This is the check that stops the
    register drifting back into three places, which is where Task 8 found it.
    """
    reg = (REPO / "pipeline/NOT_REPRODUCIBLE.md").read_text(encoding="utf-8")
    import importlib.util
    spec = importlib.util.spec_from_file_location("sar_verbatim", REPO / "tests/test_verbatim_pipeline.py")
    v = importlib.util.module_from_spec(spec)
    sys.modules["sar_verbatim"] = v
    spec.loader.exec_module(v)

    for key in v.NO_PRODUCER_INPUTS:                      # ROSTER_V4_PROJ8, ADELAIDE_MERGED
        needle = {"ROSTER_V4_PROJ8": "roster_v4_proj8",
                  "ADELAIDE_MERGED": "MERGED_209plus_gapfill"}[key]
        assert needle in reg, f"{key} is declared in code but has no register entry ({needle})"
    for rel in v.LOST_INPUTS:
        stem = rel.rsplit("/", 1)[1]
        assert stem in reg or stem.replace(".py", "") in reg, f"{rel} has no register entry"
    for token in ("u1_full_11school", "u2_person_map_11school", "u3_panel_11school",
                  "90_capped_build.py", "verify_cloud_custody", "launch_u1_fetch.sh"):
        assert token in reg, f"the register no longer names {token}"

    # the recovered producers are stated as such, not quietly dropped
    assert "RECOVERED" in reg and "\n## Recovered producers" in reg
    # Checks that need the private trees are marked `[private records]`.
    assert reg.count("[package]") >= 10 and reg.count("[private records]") >= 5

    # and every check is marked one way or the other
    unmarked = [ln for ln in reg.splitlines()
                if ln.startswith("**Check instead.**")
                and "[package]" not in ln and "[private records]" not in ln
                and ln.strip() != "**Check instead.**"]
    assert unmarked == [], unmarked


def test_t8_the_intermediates_manifest_names_a_producer_and_an_availability_for_every_row():
    """`pipeline/MANIFEST_intermediates.md` is a table, so it can be checked like one: every data row
    in every table must carry a producer column and an availability tag from the declared set."""
    text = (REPO / "pipeline/MANIFEST_intermediates.md").read_text(encoding="utf-8")
    tags = ("**repo**", "**rebuildable", "**legacy**", "**SSD**", "**gone**")
    rows, checked = [ln for ln in text.splitlines() if ln.startswith("| `") or ln.startswith("| **`")], 0
    assert len(rows) >= 30, len(rows)
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        assert len(cells) >= 3, row
        assert cells[1], f"no producer named: {row}"
        assert any(tag in row for tag in tags), f"no availability tag: {row}"
        checked += 1
    assert checked == len(rows)
    # the specific claim the brief asks for, pinned: pairs_unified.csv is byte-rebuildable
    assert "d107b5843bc49dcf" in text and "BYTE-IDENTICAL" in text
    # and that hash is the real one, where the legacy tree is present
    src = P["legacy_v2_output"] / "econ_fnfix_2026-08-15/data/pairs_unified.csv"
    if src.is_file():
        assert hashlib.sha256(src.read_bytes()).hexdigest().startswith("d107b5843bc49dcf")


#: `[package]` claims that are EXECUTABLE, and the code that executes them. Run with BOTH the legacy
#: trees and the data disk pointed at empty directories, so "package" means what it says.
#: entry -> (what the register claims, a snippet evaluated in a subprocess that must not raise)
PACKAGE_CLAIMS: dict[int, tuple[str, str]] = {
    1: ("the successor's verdict is frozen at data/fwci/g_c_old_vs_new.json",
        "assert json.loads(open('data/fwci/g_c_old_vs_new.json').read())"),
    2: ("the 920-row frozen roster",
        "assert duckdb.connect().execute(\"select count(*) from "
        "read_parquet('data/raw_verified/roster_econ_verified.parquet')\").fetchone()[0] == 920"),
    5: ("the scan's own manifest, frozen and sha-pinned",
        "m = json.loads(open('data/fwci/scan_manifest.json').read()); "
        "assert m['total_lines_read'] == 510372821 and m['shards'] == 2446 and m['bad_lines'] == 0"),
    6: ("econ_units frozen, 160,437 rows, sha-pinned",
        "import hashlib; f='data/fwci/econ_units_2026-08-09.parquet'; "
        "assert duckdb.connect().execute(f\"select count(*) from read_parquet('{f}')\").fetchone()[0]"
        " == 160437; "
        "assert hashlib.sha256(open(f,'rb').read()).hexdigest()+'  '+f in "
        "open('data/MANIFEST.sha256').read()"),
    7: ("the event arithmetic 79 + 38 = 117 over the frozen pre-caliber ledgers, minus A5044432173 "
        "(the approved 2026-08-28 caliber) = 116 in the 08-28 frames ledger (data/cal2026-08-28/frames/, "
        "since 2026-09-23 the frozen copy of what data/frames/ held), minus the three October drops "
        "(data/cal2026-10/events_decision_2026-10.json) = 113 in the shipped frames ledger",
        "import csv; n=lambda p: sum(1 for _ in csv.DictReader(open(p, encoding='utf-8'))); "
        "assert n('data/raw_verified/event_ledger_econ79.csv') == 79; "
        "assert n('data/raw_verified/events_econ_new38.csv') == 38; "
        "assert n('data/cal2026-08-28/frames/p1_events_ledger_econ.csv') == 116; "
        "assert n('data/raw_verified/events_econ_cal2026-08-28.csv') == 116; "
        "assert n('data/frames/p1_events_ledger_econ.csv') == 113; "
        "assert n('data/cal2026-10/events_econ_cal2026-10.csv') == 113"),
    8: ("the event arithmetic 79->117 / 22->35 / 20->31 (pre-caliber signed set), and the "
        "caliber tables 116/38/33 beside it",
        "import csv; n=lambda p: sum(1 for _ in csv.DictReader(open(p, encoding='utf-8'))); "
        "assert n('data/raw_verified/events_chemistry_fnfix.csv') == 35; "
        "assert n('data/raw_verified/events_math_stats_fnfix.csv') == 31; "
        "assert n('data/raw_verified/events_chemistry_cal2026-08-28.csv') == 38; "
        "assert n('data/raw_verified/events_math_stats_cal2026-08-28.csv') == 33"),
    # `--list` with no stage returns 1 by design ("you gave me no stage to run"), so the claim is
    # about what it PRINTS, not about its exit code.
    14: ("run_stars.py --list prints run_screening.py as having no runnable stage",
         "import subprocess, sys; r = subprocess.run([sys.executable, "
         "'pipeline/stars/run_stars.py', '--list'], capture_output=True, text=True); "
         "assert 'run_screening.py' in r.stdout, r.stdout[-400:] + r.stderr[-400:]"),
    16: ("tools/verify_cloud_custody.py -> CUSTODY_OK",
         "import subprocess, sys; r = subprocess.run([sys.executable, "
         "'tools/verify_cloud_custody.py'], capture_output=True, text=True); "
         "assert 'CUSTODY_OK' in r.stdout, r.stdout[-600:]"),
    # 17 (2026-09-23 review): the Shadow.write fix is exercised by its own test, and the pristine
    # supplement the restoration copies from is the sha-pinned data/raw_verified file.
    17: ("tests/test_shadow_write_through.py passes; data/raw_verified/edges_supplement_econ_fnfix.jsonl "
         "is the pristine 2026-08-15 supplement (8d03564c...)",
         "import subprocess, sys, hashlib; r = subprocess.run([sys.executable, '-m', 'pytest', '-q', "
         "'-p', 'no:cacheprovider', 'tests/test_shadow_write_through.py'], capture_output=True, text=True); "
         "assert r.returncode == 0, r.stdout[-600:]; "
         "assert hashlib.sha256(open('data/raw_verified/edges_supplement_econ_fnfix.jsonl', 'rb').read())"
         ".hexdigest() == '8d03564c714c0eac02222c5f0ecc0fefb3641a4b034b142185c780d8dc57040a'"),
    # 2026-09-23 (index row 17, the shadow write-through incident): the Shadow.write fix is tested from
    # the package, and data/raw_verified/edges_supplement_econ_fnfix.jsonl is the pristine supplement —
    # the bytes the 08-28 staging manifest pinned for the legacy file (8d03564c…)
    17: ("tests/test_shadow_write_through.py passes and data/raw_verified/edges_supplement_econ_fnfix.jsonl "
         "is the pristine 8d03564c… supplement",
         "import subprocess, sys, hashlib; r = subprocess.run([sys.executable, '-m', 'pytest', '-q', "
         "'-p', 'no:cacheprovider', 'tests/test_shadow_write_through.py'], capture_output=True, text=True); "
         "assert r.returncode == 0 and ' passed' in r.stdout and 'skipped' not in r.stdout, r.stdout[-600:]; "
         "sm = json.loads(open('data/cal2026-08-28/frames/staging_manifest_2026-08-28.json').read()); "
         "want = next(e['sha256'] for e in sm['entries'] if e['rel'] == "
         "'econ_fnfix_2026-08-15/data/edges_supplement_fnfix.jsonl'); "
         "assert want.startswith('8d03564c'); "
         "assert hashlib.sha256(open('data/raw_verified/edges_supplement_econ_fnfix.jsonl','rb').read())"
         ".hexdigest() == want"),
    18: ("the recorded U1 view of the October star-origins run (120 of 256 works_affil bucket files)",
         "v = json.loads(open('config/r1/star_origins_u1_view_2026-09-23.json').read()); "
         "w = v['tables']['u1_full_11school_2026-07-16']['works_affil']; "
         "assert w['n_bucket_dirs'] == 256 and len(w['files']) == len(w['buckets_present']) == 120"),
}


def test_t8fix_every_executable_package_marker_is_verified_by_EXECUTION(tmp_path):
    """T8 review MINOR-3. The register's promise is that a check marked `[package]` runs from this
    repository alone — and the test that guarded it checked only that a MARKER WAS PRESENT, never
    that it was right. Three were wrong on the reviewed commit: entry 10 (the ULP characterisation
    needs the data disk — measured, its cases SKIP without it), entry 7 (there is no 258-row
    `star_set` anywhere in `data/`; 0 hits in `data/MANIFEST.sha256`), and entry 2 (whose index row
    marked `[package]` the same arithmetic its own body marks `[needs legacy tree]`).

    Presence is not checkable by execution for every entry — several are prose about evidence files.
    But the ones that ARE executable are executed here, with the legacy trees AND the data disk
    pointed at empty directories through `$SAR_PATHS_CONFIG`. If one of them quietly starts needing
    a root, this fails and the marker has to change.
    """
    cfg = _probe_config(tmp_path,
                        legacy_v2_output=str(tmp_path / "none/v2_output"),
                        legacy_thesis=str(tmp_path / "none"),
                        legacy_multiplex=str(tmp_path / "none/multiplex_pipeline"),
                        ssd_root=str(tmp_path / "nodisk/openalex_pipeline"))
    env = {**os.environ, "SAR_PATHS_CONFIG": str(cfg)}
    for var in ("SAR_SSD_ROOT", "SAR_LEGACY_MULTIPLEX", "SAR_LEGACY_THESIS", "SAR_OUT_ROOT"):
        env.pop(var, None)

    # MILESTONE REVIEW, register-truth MINOR: four more `[package]` markers did not run from the
    # package, and this harness could not see them because it only executed the claims it listed.
    # A marker with no executable check is now itself a finding: every index row that says
    # `[package]` must either be covered here or be named in NOT_EXECUTABLE with a reason.
    NOT_EXECUTABLE = {
        3: "the byte-for-byte rebuild is [needs legacy tree]; the [package] half is the negative "
           "claim that nothing reads the column, which is a property of code, not a computation",
        4: "no [package] claim remains on this entry - the ev20/noA5044701593 files are legacy-only",
        9: "no [package] claim remains on this entry - measured, frames/speed needs the legacy tree",
        10: "no [package] claim remains beyond the frozen frames' own hashes, which "
            "tools/verify_manifest.py already checks on every run",
        11: "[needs legacy tree] only", 12: "[needs legacy tree] only",
        13: "[needs legacy tree] only, plus entry 5's manifest claim which IS executed here",
        15: "the same frozen manifest as entry 5, executed there",
    }
    reg_lines = (REPO / "pipeline/NOT_REPRODUCIBLE.md").read_text(encoding="utf-8").splitlines()
    index_rows = {int(ln.split("|")[1].strip()): ln for ln in reg_lines
                  if ln.startswith("| ") and ln.count("|") >= 5 and ln.split("|")[1].strip().isdigit()}
    claims_package = {n for n, ln in index_rows.items() if "[package]" in ln}
    unchecked = sorted(claims_package - set(PACKAGE_CLAIMS) - set(NOT_EXECUTABLE))
    assert unchecked == [], (
        f"index row(s) {unchecked} claim `[package]` but nothing executes the claim. Add a runnable "
        f"snippet to PACKAGE_CLAIMS, or name the row in NOT_EXECUTABLE with the reason. An "
        f"unexecuted `[package]` marker is how four wrong ones shipped.")

    failures = []
    for entry, (claim, snippet) in sorted(PACKAGE_CLAIMS.items()):
        code = "import json, duckdb\n" + snippet
        r = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True,
                           env=env)
        if r.returncode != 0:
            failures.append(f"entry {entry} is marked [package] but {claim!r} does not run from the "
                            f"package alone:\n    {(r.stderr or r.stdout).strip().splitlines()[-1]}")
    assert failures == [], "\n  ".join(failures)

    # and the three corrections stay corrected: none of these may claim [package] again
    reg = (REPO / "pipeline/NOT_REPRODUCIBLE.md").read_text(encoding="utf-8")
    # only the Index table (a later table also has numbered rows)
    index_block = reg.split("\n## Index\n", 1)[1].split("\n## ", 1)[0]
    index = [ln for ln in index_block.splitlines() if ln.startswith("| ") and ln.count("|") >= 5]
    rows = {ln.split("|")[1].strip(): ln for ln in index if ln.split("|")[1].strip().isdigit()}
    assert "[private records]" in rows["10"] and "[package]` the estimate" not in rows["10"]
    assert "[private records]` the 258-row `star_set`" in rows["7"], rows["7"]
    assert "[private records]` the evidence files and the arithmetic" in rows["2"], rows["2"]
    # entries 11 and 12 record the void control rather than asserting established absence
    assert "search void" in rows["11"] and "search void" in rows["12"]
    assert "2026-07-15 … 2026-07-21" in reg and "search is void" in reg
    assert "same uncovered\nweek as entry 11" in reg
