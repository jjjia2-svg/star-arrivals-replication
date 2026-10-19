"""Compare a rebuilt artifact with its frozen counterpart — the M3 acceptance harness.

**The criterion (plan deviation D1).** The spec asked for bit-identical rebuilds. That is
physically unreachable for the frozen parquet frames, and it is now measured rather than argued: the
legacy builders run `SET preserve_insertion_order=false` on a parallel, un-`ORDER BY`ed
`COPY … TO … PARQUET`, so row order — and every row-group boundary with it — moves from run to run.
Rebuilding `p3_afar_math_stats` five times on one machine produced **five different sha256s and five
different file sizes** (59,960 – 61,135 B), content-EQUAL every time: the rebuild is not byte-stable
against *itself*, let alone against the frozen copy. So:

* **CSV / text / JSON → bytes.** sha256 over the whole file. Nothing is normalised — in particular
  line endings are not: the old79/new38 splitter emits CRLF while its parent frame is LF, and that
  difference must stay visible in the replication package rather than be papered over.
* **parquet → content.** DuckDB `EXCEPT ALL` in BOTH directions (a multiset difference, so an extra
  duplicate row is caught where a plain `EXCEPT` would not be), plus the row count on each side,
  plus a full schema comparison. Row ORDER is not a verdict; everything else is.

**The schema rule.** A schema difference makes `equal` False. It is not a cosmetic axis: DuckDB
widens INTEGER to BIGINT inside `EXCEPT ALL`, so a dtype change between two files is *invisible* to
the row comparison — both directions return 0 rows — and would otherwise pass silently. Dtype
differences are expected between DIFFERENT frozen files (recon H2), but between a rebuild and its
own frozen counterpart a dtype difference is a finding: it means the ported builder is not emitting
what the original emitted.

The single exception is opt-in and must be named by the caller, one column at a time:
`accept_type_change=[("grp", "BIGINT", "INTEGER")]` accepts exactly that column changing exactly
that way, **in that direction** (A's type first, B's second). It is echoed in
`Result.accepted_schema_diff` and in the detail text, and it never covers a renamed column, an
extra/missing column or a column-order change.

*The axis is restricted to signed-integer widening* (`TINYINT/SMALLINT/INTEGER/BIGINT/HUGEINT`) and
every other pair is REJECTED with an error. T3 review MAJOR-2: without that restriction the axis
also switched off the row comparison for the declared column, because `EXCEPT ALL` resolves the two
types to a common supertype and a lossy supertype hides real differences — `BIGINT 2^53+1` vs
`DOUBLE 2^53`, `DECIMAL(18,3) 1.005` vs `DOUBLE 1.005`, and `INTEGER 1` vs `VARCHAR '1'` all read
EQUAL. Within the signed-integer family the common supertype is a lossless widening of both sides,
the widening cast is injective, and a real value difference therefore cannot hide (pinned by test).

**Floats.** No numeric tolerance is applied anywhere: two DOUBLEs one ULP apart compare as different.
Two IEEE-754 identities would otherwise have leaked through `EXCEPT ALL`, so:

* **signed zero is discriminated.** `-0.0 = 0.0` is true in SQL while the stored bytes differ, so
  every float column present on both sides is compared together with an explicit zero-sign companion
  expression (`CASE WHEN c = 0 THEN CAST(c AS VARCHAR) END` → `'-0.0'` vs `'0.0'`). A genuine
  negative zero — pyarrow writes one directly, and DuckDB's own writer preserves the sign on
  round-trip — is now caught. This matters inside M3: the FWCI expected table Task 4 compares has
  `expected_citations DOUBLE` with 60,504 of 130,061 rows exactly zero.
* **`NaN` still equals `NaN`**, by design — a NaN must survive a rebuild round-trip. Distinct NaN
  payloads are not distinguished.

Whenever either side has a float column the detail carries a `NOTE: float column(s) present …` line,
so no task can compare a float column without that caveat appearing in its own evidence.

Storage properties that are NOT part of the verdict, and are reported as observations only:
compression codec and row-group count.

    from tools.content_equal import content_equal
    r = content_equal(rebuilt, frozen)
    assert r.equal, r.detail

    python3 tools/content_equal.py A B      # exit 0 equal, 1 not equal, 2 uncomparable
"""
from __future__ import annotations

import dataclasses
import hashlib
import pathlib
import sys
from typing import Iterable, Sequence

#: suffixes routed to the content comparison; everything else is compared byte for byte
PARQUET_SUFFIXES = frozenset({".parquet", ".pq"})

#: the ONLY types `accept_type_change` may name, ordered narrow -> wide. Restricted to the signed
#: integer family on purpose (T3 review MAJOR-2): inside it the common supertype DuckDB resolves for
#: `EXCEPT ALL` is a lossless widening of both sides, so declaring the axis cannot hide a value
#: difference. Anything else - float, decimal, varchar, unsigned - is rejected rather than trusted.
LOSSLESS_INT_WIDENING = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT")

#: types that need the zero-sign companion expression
FLOAT_TYPES = frozenset({"FLOAT", "REAL", "DOUBLE"})

#: suffix for the generated zero-sign companion column
ZERO_SIGN_SUFFIX = "__zero_sign"

_CHUNK = 1 << 20
#: files above this size skip the (whole-file) line-ending observation; the verdict never depends on it
_LINE_SCAN_MAX = 64 << 20
#: differing rows shown in the detail text, per direction
_SAMPLE_ROWS = 3


class ContentEqualError(Exception):
    """The two artifacts cannot be compared. Never a verdict — always louder than one."""


class MissingArtifact(ContentEqualError):
    """One side does not exist. A rebuild that produced nothing must not read as a pass."""


class UnreadableArtifact(ContentEqualError):
    """One side exists but could not be read as the format its suffix claims."""


@dataclasses.dataclass(frozen=True)
class Result:
    """The verdict plus everything it was based on.

    `__bool__` returns `equal`, so `assert content_equal(a, b)` is safe: without it a dataclass is
    always truthy and a caller who forgets `.equal` would silently stop testing anything.
    """

    equal: bool
    mode: str                                   #: "bytes" | "content"
    detail: str
    path_a: str
    path_b: str
    size_a: int
    size_b: int
    sha256_a: str = ""
    sha256_b: str = ""
    #: content mode only
    rows_a: int | None = None
    rows_b: int | None = None
    schema_a: tuple[tuple[str, str], ...] | None = None
    schema_b: tuple[tuple[str, str], ...] | None = None
    schema_equal: bool | None = None
    #: every schema difference found, accepted or not
    schema_diff: tuple[str, ...] = ()
    #: the subset the caller declared through `accept_type_change`
    accepted_schema_diff: tuple[str, ...] = ()
    #: rows present in one side and not the other, as a multiset difference; None when the column
    #: sets differ and no honest row comparison exists
    only_in_a: int | None = None
    only_in_b: int | None = None
    #: float columns compared on both sides (the zero-sign companion applies to these)
    float_columns: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.equal

    def __str__(self) -> str:
        return self.detail


# --- helpers -------------------------------------------------------------------------------------

def _resolve(path, side: str) -> pathlib.Path:
    p = pathlib.Path(path)
    if not p.exists():
        raise MissingArtifact(f"side {side} does not exist: {p}")
    if p.is_dir():
        raise ContentEqualError(f"side {side} is a directory, not an artifact: {p}")
    if not p.is_file():
        raise ContentEqualError(f"side {side} is not a regular file: {p}")
    return p.absolute()


def _sha256(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _first_difference(a: pathlib.Path, b: pathlib.Path) -> int | None:
    """0-based offset of the first differing byte, or None when one file is a prefix of the other."""
    with a.open("rb") as fa, b.open("rb") as fb:
        off = 0
        while True:
            ca, cb = fa.read(_CHUNK), fb.read(_CHUNK)
            if not ca or not cb:
                return None if ca == cb else off
            for i in range(min(len(ca), len(cb))):
                if ca[i] != cb[i]:
                    return off + i
            if len(ca) != len(cb):
                return off + min(len(ca), len(cb))
            off += len(ca)


def _line_endings(p: pathlib.Path) -> tuple[int, int] | None:
    """(CRLF count, bare-LF count), or None when the file is too big to scan for the observation."""
    if p.stat().st_size > _LINE_SCAN_MAX:
        return None
    data = p.read_bytes()
    crlf = data.count(b"\r\n")
    return crlf, data.count(b"\n") - crlf


def _byte(c: int) -> str:
    return f"0x{c:02x} ({chr(c)!r})"


# --- byte mode -----------------------------------------------------------------------------------

def _byte_compare(a: pathlib.Path, b: pathlib.Path) -> Result:
    sa, sb = a.stat().st_size, b.stat().st_size
    ha, hb = _sha256(a), _sha256(b)
    equal = ha == hb and sa == sb
    lines = [f"BYTE COMPARISON ({a.suffix or 'no suffix'}) — nothing normalised, line endings included",
             f"  size    A={sa:,}  B={sb:,}",
             f"  sha256  A={ha}",
             f"          B={hb}"]
    if equal and sa == 0:
        lines.append("  NOTE: both sides are EMPTY (0 bytes) — byte-equal, but almost certainly a "
                     "producer that wrote nothing")
    if not equal:
        off = _first_difference(a, b)
        if off is None:
            lines.append(f"  one file is a prefix of the other; they diverge at byte {min(sa, sb):,} (end of the shorter)")
        else:
            with a.open("rb") as fa, b.open("rb") as fb:
                fa.seek(off); fb.seek(off)
                lines.append(f"  first difference at byte {off:,}: A={_byte(fa.read(1)[0])}  B={_byte(fb.read(1)[0])}")
        la, lb = _line_endings(a), _line_endings(b)
        if la is not None and lb is not None and la != lb:
            lines.append(f"  line endings  A: CRLF={la[0]:,} bare LF={la[1]:,}   "
                         f"B: CRLF={lb[0]:,} bare LF={lb[1]:,}   (reported, never normalised)")
    lines.append(f"VERDICT: {'EQUAL' if equal else 'NOT EQUAL'}")
    return Result(equal=equal, mode="bytes", detail="\n".join(lines), path_a=str(a), path_b=str(b),
                  size_a=sa, size_b=sb, sha256_a=ha, sha256_b=hb)


# --- content mode --------------------------------------------------------------------------------

def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _normalise_accept(accept: Iterable[Sequence[str]]) -> dict[str, tuple[str, str]]:
    """Validate the declared axis. Every rejection here is a rejection of a way it could lie."""
    out: dict[str, tuple[str, str]] = {}
    for entry in accept:
        if isinstance(entry, str) or len(tuple(entry)) != 3:
            raise ContentEqualError(
                f"accept_type_change entries are (column, type_in_A, type_in_B) triples; got {entry!r}. "
                "The declaration has to name the exact change it is accepting — that is what keeps it "
                "from covering anything else.")
        col, ta, tb = (str(x).strip() for x in entry)
        ta, tb = ta.upper(), tb.upper()
        if col in out:                                              # T3 review MINOR-4
            raise ContentEqualError(
                f"accept_type_change declares column {col!r} twice ({out[col]} and {(ta, tb)}). The "
                "declaration list is the audit record of what was consented to; silently keeping the "
                "last entry would drop half of it.")
        if ta == tb:                                                # T3 review NIT-3
            raise ContentEqualError(
                f"accept_type_change entry for {col!r} declares {ta} -> {tb}: a difference is only ever "
                "reported when the two types differ, so this declaration can never mean anything.")
        bad = [t for t in (ta, tb) if t not in LOSSLESS_INT_WIDENING]
        if bad:
            raise ContentEqualError(
                f"accept_type_change for {col!r} names {', '.join(bad)}, outside the signed-integer "
                f"family {LOSSLESS_INT_WIDENING}. Only that family is allowed, because only there is "
                f"the supertype `EXCEPT ALL` resolves a LOSSLESS widening of both sides. Declaring a "
                f"lossy pair would switch off the row comparison for this column as well as the "
                f"schema check: BIGINT 2^53+1 vs DOUBLE 2^53, DECIMAL(18,3) 1.005 vs DOUBLE 1.005 and "
                f"INTEGER 1 vs VARCHAR '1' all compare EQUAL under their common supertype "
                f"(T3 review MAJOR-2).")
        out[col] = (ta, tb)
    return out


def _schema(con, path: pathlib.Path) -> tuple[tuple[str, str], ...]:
    # DESCRIBE also returns a nullability column (r[2]); it is dropped on purpose. DuckDB's parquet
    # reader reports YES for every column, including one pyarrow wrote with nullable=False, so
    # required-vs-optional is not observable through this path and nothing is lost (T3 review NIT-2).
    rows = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]).fetchall()
    return tuple((r[0], r[1]) for r in rows)


def _assert_single_file(con, path: pathlib.Path, side: str) -> None:
    """`read_parquet` GLOB-expands its argument, so a filename containing `*`, `?` or `[…]` silently
    compares the union of whatever matched (T3 review MAJOR-1: `t[ab].parquet` holding 999 read as
    EQUAL to a frozen file holding 1,1 because two decoys matched). `_resolve` only proves a file of
    that literal name exists. This proves DuckDB read exactly that file and nothing else."""
    matched = [r[0] for r in con.execute(
        "SELECT file_name FROM parquet_file_metadata(?)", [str(path)]).fetchall()]
    same = [m for m in matched if pathlib.Path(m).resolve() == path.resolve()]
    if len(matched) != 1 or not same:
        raise ContentEqualError(
            f"side {side}: DuckDB expanded this path as a glob pattern and read "
            f"{len(matched)} file(s), not the one named:\n"
            f"    named   {path}\n"
            f"    matched {matched or '(nothing)'}\n"
            f"  A path holding a glob metacharacter (* ? [ ]) cannot be compared safely — the "
            f"comparison would run against whatever else matched. Rename the file or the directory.")


def _storage(con, path: pathlib.Path) -> str:
    bits = []
    try:
        codecs = [c for (c,) in con.execute(
            "SELECT DISTINCT compression FROM parquet_metadata(?)", [str(path)]).fetchall()]
        bits.append("/".join(sorted(codecs)) or "?")
    except Exception:                                                    # noqa: BLE001 - observation only
        bits.append("?")
    try:
        bits.append(f"{con.execute('SELECT num_row_groups FROM parquet_file_metadata(?)', [str(path)]).fetchone()[0]} row group(s)")
    except Exception:                                                    # noqa: BLE001
        pass
    return ", ".join(bits)


def _content_compare(a: pathlib.Path, b: pathlib.Path,
                     accept: dict[str, tuple[str, str]]) -> Result:
    import duckdb                                                        # only the parquet path needs it

    con = duckdb.connect()
    try:
        _assert_single_file(con, a, "A")
        _assert_single_file(con, b, "B")
        schema_a, schema_b = _schema(con, a), _schema(con, b)
        rows_a = con.execute("SELECT count(*) FROM read_parquet(?)", [str(a)]).fetchone()[0]
        rows_b = con.execute("SELECT count(*) FROM read_parquet(?)", [str(b)]).fetchone()[0]
    except ContentEqualError:
        raise
    except Exception as exc:                                             # noqa: BLE001
        raise UnreadableArtifact(f"could not read as parquet: {exc}") from exc

    names_a = [n for n, _ in schema_a]
    names_b = [n for n, _ in schema_b]
    types_a, types_b = dict(schema_a), dict(schema_b)

    diffs: list[str] = []
    accepted: list[str] = []
    for n in names_a:
        if n not in types_b:
            diffs.append(f"column {n!r} is present in A and absent in B")
    for n in names_b:
        if n not in types_a:
            diffs.append(f"column {n!r} is present in B and absent in A")
    same_names = set(names_a) == set(names_b)
    if same_names and names_a != names_b:
        diffs.append(f"column order differs: A=({', '.join(names_a)})  B=({', '.join(names_b)})")
    for n, ta in schema_a:
        tb = types_b.get(n)
        if tb is not None and tb != ta:
            line = f"column {n!r}: type {ta} (A) vs {tb} (B)"
            diffs.append(line)
            # direction-sensitive on purpose: the declaration names A's type first (T3 review M15)
            if accept.get(n) == (ta.upper(), tb.upper()):
                accepted.append(line)

    stale = [f"{c}: {ta} -> {tb}" for c, (ta, tb) in accept.items()
             if not any(d.startswith(f"column {c!r}: type") for d in diffs)]
    unaccepted = [d for d in diffs if d not in accepted]

    only_a = only_b = None
    samples: list[str] = []
    float_cols: list[str] = []
    if same_names:
        float_cols = [n for n, t in schema_a if t in FLOAT_TYPES and types_b.get(n) in FLOAT_TYPES]
        clash = [n for n in names_a if n.endswith(ZERO_SIGN_SUFFIX)]
        if float_cols and clash:
            raise ContentEqualError(
                f"column name(s) {clash} collide with the generated zero-sign companion suffix "
                f"{ZERO_SIGN_SUFFIX!r}; rename the column or the suffix before comparing floats.")
        parts = [_quote(n) for n in names_a]
        # signed zero: -0.0 = 0.0 in SQL, so a bare projection cannot see it (T3 review MAJOR-3)
        parts += [f"CASE WHEN {_quote(n)} = 0 THEN CAST({_quote(n)} AS VARCHAR) END "
                  f"AS {_quote(n + ZERO_SIGN_SUFFIX)}" for n in float_cols]
        proj = ", ".join(parts)
        both = f"(SELECT {proj} FROM read_parquet(?)) EXCEPT ALL (SELECT {proj} FROM read_parquet(?))"
        try:
            only_a = con.execute(f"SELECT count(*) FROM ({both})", [str(a), str(b)]).fetchone()[0]
            only_b = con.execute(f"SELECT count(*) FROM ({both})", [str(b), str(a)]).fetchone()[0]
            for side, (x, y), n in (("A", (a, b), only_a), ("B", (b, a), only_b)):
                if n:
                    rows = con.execute(f"SELECT * FROM ({both}) LIMIT {_SAMPLE_ROWS}",
                                       [str(x), str(y)]).fetchall()
                    samples.append(f"  first {len(rows)} row(s) only in {side} ({proj}): "
                                   + "  ".join(str(tuple(r)) for r in rows))
        except Exception as exc:                                         # noqa: BLE001 - T3 review MINOR-3
            raise UnreadableArtifact(
                f"the two files cannot be set-compared (typically a LIST/STRUCT column whose types do "
                f"not resolve): {exc}") from exc
    storage_a, storage_b = _storage(con, a), _storage(con, b)
    con.close()

    equal = (not unaccepted) and rows_a == rows_b and only_a == 0 and only_b == 0

    def _fmt(schema):
        return "[" + ", ".join(f"{n} {t}" for n, t in schema) + "]"

    lines = ["CONTENT COMPARISON (parquet; DuckDB EXCEPT ALL in both directions — row ORDER is not a verdict)",
             f"  rows    A={rows_a:,}  B={rows_b:,}",
             f"  schema  A={_fmt(schema_a)}",
             f"          B={_fmt(schema_b)}"]
    lines.append("  schema: IDENTICAL" if not diffs
                 else "  schema: DIFFERENT\n" + "\n".join(f"      - {d}" for d in diffs))
    if accepted:
        lines.append("  SCHEMA DIFFERENCE ACCEPTED BY CALLER (declared axis: signed-integer widening, "
                     "direction A->B):\n" + "\n".join(f"      + {d}" for d in accepted))
    if stale:
        lines.append("  NOTE: declared accept_type_change entries that are not present (stale "
                     "declaration, harmless): " + "; ".join(stale))
    if float_cols:
        lines.append(f"  NOTE: float column(s) present ({', '.join(float_cols)}) — signed zero IS "
                     f"discriminated (explicit zero-sign companion column); NaN compares equal to "
                     f"NaN by design; distinct NaN payloads are not compared")
    if only_a is None:
        lines.append("  rows: COMPARISON SKIPPED — the column sets differ, so there is no honest "
                     "projection to compare (comparing the intersection would hide the difference)")
    else:
        lines.append(f"  rows only in A: {only_a:,}     rows only in B: {only_b:,}")
        lines += samples
    if equal and rows_a == 0:                                            # T3 review MINOR-2
        lines.append("  NOTE: both sides are EMPTY (0 rows) — content-equal, but a broken WHERE clause "
                     "still writes a valid, correctly-typed, empty parquet")
    lines.append(f"  storage (observation only, not part of the verdict)  A: {storage_a}   B: {storage_b}")
    lines.append(f"VERDICT: {'EQUAL' if equal else 'NOT EQUAL'}")

    return Result(equal=equal, mode="content", detail="\n".join(lines), path_a=str(a), path_b=str(b),
                  size_a=a.stat().st_size, size_b=b.stat().st_size,
                  rows_a=rows_a, rows_b=rows_b, schema_a=schema_a, schema_b=schema_b,
                  schema_equal=not diffs, schema_diff=tuple(diffs),
                  accepted_schema_diff=tuple(accepted), only_in_a=only_a, only_in_b=only_b,
                  float_columns=tuple(float_cols))


# --- entry point ---------------------------------------------------------------------------------

def content_equal(path_a, path_b, *, accept_type_change: Iterable[Sequence[str]] = ()) -> Result:
    """Compare two artifacts of the same kind. See the module docstring for the criterion.

    `accept_type_change` is the one opt-in loosening: an iterable of
    `(column, type_in_A, type_in_B)` triples, each accepting exactly one column changing exactly one
    way in exactly that direction. Both types must be members of `LOSSLESS_INT_WIDENING`; anything
    else raises. It is recorded in the Result and cannot cover anything else.

    Raises `MissingArtifact` / `UnreadableArtifact` / `ContentEqualError` rather than returning a
    verdict when the comparison itself cannot be made.
    """
    a, b = _resolve(path_a, "A"), _resolve(path_b, "B")
    pq_a, pq_b = a.suffix.lower() in PARQUET_SUFFIXES, b.suffix.lower() in PARQUET_SUFFIXES
    if pq_a != pq_b:
        raise ContentEqualError(
            f"cannot compare a parquet with a non-parquet: {a.name} vs {b.name}")
    accept = _normalise_accept(accept_type_change)
    if accept and not pq_a:
        raise ContentEqualError("accept_type_change applies to parquet only; byte comparison has no schema")
    return _content_compare(a, b, accept) if pq_a else _byte_compare(a, b)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: content_equal.py A B", file=sys.stderr)
        return 2
    try:
        r = content_equal(argv[1], argv[2])
    except ContentEqualError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(r.detail)
    return 0 if r.equal else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
