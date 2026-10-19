"""Historical roster, byline line, steps 0-2: precondition gate / department matching / year determination
(candidate layer, not authoritative).

In plain words: from the raw byline strings of the full U1 works_affil, pick out the (paper, author) pairs that
print one of the two universities' economics departments (step 1), then join authorship_edges to get the
publication year and aggregate into candidate evidence points "person X has a byline in department Y in year Z"
(step 2). Output = byline_dept_hits / byline_year_evidence + human-review sidecars; every row is pending and
is promoted to the official level only once it is human_verified.

The design is grounded in a full works_affil evidence scan (403,107 candidate strings measured):
  - Binding is at the level of a single byline string: the raw string of one row may contain another
    university's economics department (joint appointment), so a row-level institution id would bind wrongly.
  - ±window: journal catch-all strings concatenate every author's affiliation into one string (a Piraeus
    economics department plus a distant UNSW in the same string); the token must fall within ±80 characters
    of the phrase.
  - Nearest university first: when tokens of both universities are in the window, bind the one nearest the
    phrase (prevents mis-binding in multi-department catch-all strings).
  - Token case / whole word: the lowercase substring 'unsw' hits New BrUNSWick (Rutgers, 2,518 rows) -> UNSW is
    case-sensitive and whole-word; bare 'New South Wales' is a state name -> full name only.
  - Exclude token: the Monash Malaysia campus is outside the scope (11 Australian universities).
The only legitimate source of the year is the (work_id, author_id) join to authorship_edges.publication_year
(never read an aggregated year field from the author profile; a source-level guard for this module is
test_hist_step2_year).
Writes are deterministic parquet (canonical sort + zstd / dictionary off / no statistics / no embedded arrow
metadata).
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import sys
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from common.schema import BYLINE_DEPT_HITS, BYLINE_YEAR_EVIDENCE
from identity.exit_codes import (
    EXIT_BYLINE_EMPTY_HITS_FAIL,
    EXIT_BYLINE_SCHEMA_FAIL,
    EXIT_BYLINE_YEAR_NULL_FAIL,
    EXIT_ROSTER_REGISTRY_MISSING,
    EXIT_ROSTER_UPSTREAM_FAIL,
)

RAW_COL = "raw_affiliation_strings"
_WINDOW_CHARS = 80

# Per-school curated binding/exclusion tokens (grounded in evidence, see the module docstring); a school that is
# not registered never gets a default.
# Tokens for the 9 added schools: all nine disable bare city/state/brand names (Sydney/Melbourne/Adelaide/
# Queensland/Western Australia/Deakin/Macquarie); abbreviation tokens are always case-sensitive and whole-word
# (the UNSW / New BrUNSWick precedent).
_BIND_TOKENS: dict[str, list[dict]] = {
    "monash_econ": [
        {"text": "Monash", "case_sensitive": False, "word_boundary": False},
    ],
    "unsw_econ": [
        {"text": "University of New South Wales", "case_sensitive": False, "word_boundary": False},
        {"text": "UNSW", "case_sensitive": True, "word_boundary": True},
    ],
    # Bare "Melbourne" is a city name and collides with RMIT / Melbourne Polytechnic / address strings -> full name only.
    "melbourne_econ": [
        {"text": "University of Melbourne", "case_sensitive": False, "word_boundary": False},
    ],
    # Bare "Sydney" collides with UNSW Sydney (the other school in this sample!) / UTS / Western Sydney -> full name only
    # ("University of Technology Sydney" does not contain that substring, checked literally).
    "sydney_econ": [
        {"text": "University of Sydney", "case_sensitive": False, "word_boundary": False},
    ],
    # Lowercase "anu" hits words like M**anu**script / V**anu**atu -> ANU is case-sensitive and whole-word.
    "anu_econ": [
        {"text": "Australian National University", "case_sensitive": False, "word_boundary": False},
        {"text": "ANU", "case_sensitive": True, "word_boundary": True},
    ],
    # Bare "Queensland" is a state name and collides with QUT/USQ/CQU/state treasury ("Queensland University of Technology"
    # does not contain the "University of Queensland" substring, checked literally).
    "uq_econ": [
        {"text": "University of Queensland", "case_sensitive": False, "word_boundary": False},
        {"text": "UQ", "case_sensitive": True, "word_boundary": True},
    ],
    # Bare "Western Australia" is a state name and collides with Curtin/Murdoch/ECU; lowercase "uwa" is a common syllable
    # in personal and place names (S**uwa**/R**uwa**npura) -> full name + case-sensitive whole-word UWA.
    "uwa_econ": [
        {"text": "University of Western Australia", "case_sensitive": False, "word_boundary": False},
        {"text": "UWA", "case_sensitive": True, "word_boundary": True},
    ],
    # In 2001-02 the university officially called itself "Adelaide University" (confirmed by the 2001 home-page title in
    # 12 snapshots) -> both full names are needed, otherwise early years are missed; from 2026 the same string also refers
    # to the merged new university (same lineage, harmless for Table A). Bare "Adelaide" is disabled.
    "adelaide_econ": [
        {"text": "University of Adelaide", "case_sensitive": False, "word_boundary": False},
        {"text": "Adelaide University", "case_sensitive": False, "word_boundary": False},
    ],
    # Bare "Deakin" collides with Deakin ACT 2600 (a Canberra suburb address string) and with personal names / institutes that contain "Deakin".
    "deakin_econ": [
        {"text": "Deakin University", "case_sensitive": False, "word_boundary": False},
    ],
    # The old official name has a comma, "University of Technology, Sydney" (original 2014 snapshot title), and the comma
    # was dropped around 2015 -> accept both forms; lowercase "uts" hits outp**uts**/inp**uts** -> UTS is case-sensitive and
    # whole-word.
    "uts_econ": [
        {"text": "University of Technology Sydney", "case_sensitive": False, "word_boundary": False},
        {"text": "University of Technology, Sydney", "case_sensitive": False, "word_boundary": False},
        {"text": "UTS", "case_sensitive": True, "word_boundary": True},
    ],
    # Bare "Macquarie" collides with Macquarie Bank/Group (economists at financial institutions do publish papers!)/Macquarie
    # Street/Port Macquarie -> full name only.
    "macquarie_econ": [
        {"text": "Macquarie University", "case_sensitive": False, "word_boundary": False},
    ],
}
_EXCLUDE_TOKENS: dict[str, list[str]] = {
    "monash_econ": ["Malaysia"],
    "unsw_econ": [],
    "melbourne_econ": [],
    "sydney_econ": [],
    # ANU note: any string containing Arndt-Corden/Crawford does not belong to anu_econ (the Crawford School
    # contains the "Arndt-Corden Department of Economics", a major development-economics centre, but it belongs to the
    # College of Asia & the Pacific and is not in the same community as RSE/CBE -> not covered by the derived general rule).
    # Use the exact unit names, not bare "Crawford".
    "anu_econ": ["Arndt-Corden", "Crawford School"],
    "uq_econ": [],
    "uwa_econ": [],
    "adelaide_econ": [],  # UniSA merger contamination is a person-level problem at the 2026 boundary year, not a token problem
    "deakin_econ": [],    # No evidence for GIFT City yet; add it once real strings appear (same path as the Monash Malaysia precedent)
    "uts_econ": [],
    "macquarie_econ": [],
}

# Per-phrase extra required token: for "Economics Program" the binding word
# "Research School of Social Sciences" is registered as a second condition, so that the bare phrase cannot collide with a
# same-named program at another school. Semantics: besides the school token, at least one requires token must be within
# the ±window of that (school, phrase) occurrence, otherwise it is not bound (unbound reason=required_token_missing).
# Behavior of unregistered (school, phrase) pairs is unchanged - the monash/unsw config is byte-for-byte identical
# (the yaml emits the key only when non-empty).
_PHRASE_REQUIRES: dict[str, dict[str, list[dict]]] = {
    "anu_econ": {
        "Economics Program": [
            {"text": "Research School of Social Sciences", "case_sensitive": False,
             "word_boundary": False},
        ],
    },
}


# ── config: phrase whitelist (authoritative source = Table A dept_name_variants) + binding mechanism, frozen SHA ────
def build_phrase_config(table_a_rows) -> list[dict]:
    cfgs = []
    for r in table_a_rows:
        dk = r["dept_key"]
        if dk not in _BIND_TOKENS:
            raise KeyError(f"dept_key {dk!r} has no curated binding token — register it in _BIND_TOKENS first, no default is given")
        cfg = {
            "dept_key": dk,
            "openalex_inst_id": r["openalex_inst_id"],
            "phrases": list(r["dept_name_variants"]),
            "bind_tokens": [dict(t) for t in _BIND_TOKENS[dk]],
            "exclude_tokens": list(_EXCLUDE_TOKENS[dk]),
            "window_chars": _WINDOW_CHARS,
        }
        # per-phrase requires is emitted only when non-empty -
        # the existing monash/unsw yaml stays byte-identical (frozen SHA unchanged).
        req = _PHRASE_REQUIRES.get(dk)
        if req:
            cfg["phrase_requires"] = {p: [dict(t) for t in toks] for p, toks in req.items()}
        cfgs.append(cfg)
    return cfgs


def write_phrase_config(cfgs, cfg_dir) -> dict[str, str]:
    """One <dept_key>.yaml per school (safe_dump with sorted keys -> deterministic bytes); returns {dept_key: sha256}."""
    cfg_dir = pathlib.Path(cfg_dir)
    cfg_dir.mkdir(parents=True, exist_ok=True)
    shas = {}
    for cfg in cfgs:
        data = yaml.safe_dump(cfg, sort_keys=True, allow_unicode=True).encode("utf-8")
        target = cfg_dir / f"{cfg['dept_key']}.yaml"
        target.write_bytes(data)
        shas[cfg["dept_key"]] = hashlib.sha256(data).hexdigest()
    return shas


def load_phrase_config(cfg_dir, dept_keys) -> list[dict]:
    cfg_dir = pathlib.Path(cfg_dir)
    return [yaml.safe_load((cfg_dir / f"{dk}.yaml").read_text(encoding="utf-8")) for dk in dept_keys]


# ── matching core (pure functions) ────────────────────────────────────────────────────────
def _fold_lower(s: str) -> str:
    """Length-preserving lowercase fold: 'İ'.lower() becomes 2 characters, which would misalign the phrase coordinates
    (lowered string) with the token / stamp-slice coordinates (original string) -> characters whose length changes are
    kept as they are. Phrases are all ASCII and unaffected."""
    return "".join(c.lower() if len(c.lower()) == 1 else c for c in s)


def _token_spans(s: str, tok: dict) -> list[tuple[int, int]]:
    text = tok["text"]
    if tok.get("word_boundary"):
        flags = 0 if tok.get("case_sensitive") else re.IGNORECASE
        return [m.span() for m in re.finditer(r"\b" + re.escape(text) + r"\b", s, flags)]
    # The case-insensitive substring path must use the length-preserving fold (_fold_lower), in the same coordinate
    # system as the phrase coordinates of match_string (low = _fold_lower(affil_str)). s.lower() changes the length for
    # characters such as 'İ' -> the token span shifts -> window in/out and the stamp slice flip. Folding hay and needle
    # with the same function keeps the coordinates one-to-one.
    hay = s if tok.get("case_sensitive") else _fold_lower(s)
    needle = text if tok.get("case_sensitive") else _fold_lower(text)
    spans, i = [], hay.find(needle)
    while i != -1:
        spans.append((i, i + len(needle)))
        i = hay.find(needle, i + 1)
    return spans


def _gap(span: tuple[int, int], lo: int, hi: int) -> int | None:
    """Distance from the span to the phrase if it overlaps the [lo,hi) window (overlap = 0); None if it does not overlap."""
    if span[0] >= hi or span[1] <= lo:
        return None
    return 0


def _dist(span: tuple[int, int], ps: int, pe: int) -> int:
    if span[1] <= ps:
        return ps - span[1]
    if span[0] >= pe:
        return span[0] - pe
    return 0


# Stamp test (found in a real-data smoke run): archive sources (RePEc style) stamp an author's "current unit" onto all
# of the author's historical papers, in the form university first + a pure separator directly followed by the department
# name ('Monash University - Department of Economics' / 'Monash University, Department of Economics' /
# '... > Department ...') - this pulled the candidate year of one author (Yves Zenou) back to 1998 (true arrival 2016).
# A paper's real printed byline either puts the department first, or puts the university first with a real hierarchy level
# in between ('UNSW Australia Business School, School of Economics, High Street...').
# Criterion: if the separator segment between token and phrase contains only the university's own words plus punctuation
# -> stamped; any other organization word (Business/School/Faculty...) -> printed. This only attaches a mechanical
# label; how to use the label is left open.
_SEP_NOISE_WORDS = {"university", "of", "new", "south", "wales", "australia",
                    "sydney", "the", "monash", "unsw"}


def _sep_is_pure(sep: str) -> bool:
    letters = re.findall(r"[A-Za-z]+", sep)
    return all(w.lower() in _SEP_NOISE_WORDS for w in letters)


def _occurrence_style(affil_str: str, spans_in_window, ps: int, pe: int) -> str:
    """Stamp signature = a university token with a "pure separator, directly followed" link before the phrase - if it
    exists the string is stamped; a token that appears again as a suffix (e.g. '..., Monash Business School') does
    not clean it."""
    for sp in spans_in_window:
        if sp[1] <= ps and _sep_is_pure(affil_str[sp[1]:ps]):
            return "stamped"
    return "printed"


def match_string(affil_str: str, cfgs) -> tuple[list[tuple[str, str, str]], list[tuple[str, str]]]:
    """One byline string -> (bound: [(dept_key, phrase, match_style)], unbound: [(phrase, reason)]).

    Each phrase occurrence is decided independently: exclude token in the window -> excluded_token; no school token
    in the window -> no_bind_token; (school, phrase) has phrase_requires and no required token in the window ->
    required_token_missing (ANU "Economics Program" + RSSS two-condition rule);
    tokens of several schools in the window -> bind the nearest school (ties bind all). style: a pure-separator
    university token before the phrase -> stamped (a suffix token does not clean a stamped signature); otherwise printed.
    """
    low = _fold_lower(affil_str)  # Length-preserving fold: coordinates correspond one-to-one with the original string
    # phrase text -> list of schools that have it (shared phrases such as 'Department of Economics' exist at both schools)
    phrase_owners: dict[str, list[dict]] = {}
    for cfg in cfgs:
        for p in cfg["phrases"]:
            phrase_owners.setdefault(p, []).append(cfg)

    tok_spans = {c["dept_key"]: [sp for t in c["bind_tokens"] for sp in _token_spans(affil_str, t)]
                 for c in cfgs}
    excl_spans = {c["dept_key"]: [sp for x in c["exclude_tokens"]
                                  for sp in _token_spans(affil_str, {"text": x})]
                  for c in cfgs}

    bound: set[tuple[str, str, str]] = set()
    unbound: set[tuple[str, str]] = set()
    for phrase, owners in phrase_owners.items():
        pl = phrase.lower()
        ps = low.find(pl)
        while ps != -1:
            pe = ps + len(pl)
            eligible: list[tuple[int, str, str]] = []
            any_excluded = False
            any_req_missing = False
            for cfg in owners:
                dk = cfg["dept_key"]
                w = cfg["window_chars"]
                lo, hi = ps - w, pe + w
                if any(_gap(sp, lo, hi) is not None for sp in excl_spans[dk]):
                    any_excluded = True
                    continue
                in_win = [sp for sp in tok_spans[dk] if _gap(sp, lo, hi) is not None]
                if not in_win:
                    continue
                # Two-condition phrase: the school token in the window is not enough; the required token must also be in the window.
                req_toks = cfg.get("phrase_requires", {}).get(phrase)
                if req_toks and not any(
                    _gap(sp, lo, hi) is not None
                    for t in req_toks for sp in _token_spans(affil_str, t)
                ):
                    any_req_missing = True
                    continue
                dmin = min(_dist(sp, ps, pe) for sp in in_win)
                style = _occurrence_style(affil_str, in_win, ps, pe)
                eligible.append((dmin, dk, style))
            if eligible:
                best = min(d for d, _, _ in eligible)
                for d, dk, style in eligible:
                    if d == best:
                        bound.add((dk, phrase, style))
            elif any_excluded:
                unbound.add((phrase, "excluded_token"))
            elif any_req_missing:
                unbound.add((phrase, "required_token_missing"))
            else:
                unbound.add((phrase, "no_bind_token"))
            ps = low.find(pl, ps + 1)
    return sorted(bound), sorted(unbound)


# ── Step 0: precondition gate (HALT-or-go) ─────────────────────────────────────────────
def _halt(code: int, msg: str) -> None:
    print(f"[byline] HALT({code}): {msg}", file=sys.stderr)
    sys.exit(code)


def _parquet_files(d) -> list[pathlib.Path]:
    d = pathlib.Path(d)
    if not d.exists():
        return []
    return sorted(p for p in d.rglob("*.parquet") if "SAMPLE" not in p.name)


def probe_upstream(works_affil_dir, authorship_dir) -> dict:
    wa = _parquet_files(works_affil_dir)
    ae = _parquet_files(authorship_dir)
    if not wa:
        _halt(EXIT_ROSTER_UPSTREAM_FAIL, f"works_affil full table not present (no non-SAMPLE parquet): {works_affil_dir}")
    if not ae:
        _halt(EXIT_ROSTER_UPSTREAM_FAIL, f"authorship_edges full table not present: {authorship_dir}")

    wa_schema = pq.ParquetFile(str(wa[0])).schema_arrow
    for col in ("work_id", "author_id", "institution_id", RAW_COL):
        if col not in wa_schema.names:
            _halt(EXIT_ROSTER_UPSTREAM_FAIL, f"works_affil is missing column {col}")
    raw_t = wa_schema.field(RAW_COL).type
    if not (pa.types.is_list(raw_t) and pa.types.is_string(raw_t.value_type)):
        _halt(EXIT_ROSTER_UPSTREAM_FAIL, f"{RAW_COL} was flattened to {raw_t} (must be list<string>) — essential for disambiguation and department assignment")
    raw_label = "list<string>"  # Normalized label (pyarrow str() gives 'list<item: string>')

    ae_schema = pq.ParquetFile(str(ae[0])).schema_arrow
    for col in ("work_id", "author_id", "publication_year"):
        if col not in ae_schema.names:
            _halt(EXIT_ROSTER_UPSTREAM_FAIL, f"authorship_edges is missing column {col}")

    return {
        "works_affil_files": len(wa),
        "authorship_files": len(ae),
        "raw_affil_type": raw_label,
        "publication_year_type": str(ae_schema.field("publication_year").type),
        "probed_files": [wa[0].name, ae[0].name],
    }


def probe_registry(table_a_path, dept_keys) -> dict:
    p = pathlib.Path(table_a_path)
    if not p.exists():
        _halt(EXIT_ROSTER_REGISTRY_MISSING, f"Table A not present: {p}")
    by = {r["dept_key"]: r for r in pq.read_table(str(p)).to_pylist()}
    rec = {}
    for dk in dept_keys:
        r = by.get(dk)
        if r is None:
            _halt(EXIT_ROSTER_REGISTRY_MISSING, f"Table A has no entity row for {dk} — never let an empty whitelist silently match 0")
        if not r["dept_name_variants"]:
            _halt(EXIT_ROSTER_REGISTRY_MISSING, f"Table A {dk}.dept_name_variants is empty")
        if r["human_verified"] is not True:
            _halt(EXIT_ROSTER_REGISTRY_MISSING, f"Table A {dk} has not been manually verified (human_verified!=True) — a whitelist must be manually verified before it may be used as a filter")
        rec[dk] = {"openalex_inst_id": r["openalex_inst_id"],
                   "dept_name_variants": list(r["dept_name_variants"])}
    return rec


# ── Deterministic writes ──────────────────────────────────────────────────────────────
_ARROW_TYPES = {
    "str": pa.string(),
    "int16": pa.int16(),
    "int32": pa.int32(),
    "float32": pa.float32(),
    "list<str>": pa.list_(pa.string()),
    "list<int16>": pa.list_(pa.int16()),
    "bool": pa.bool_(),
    "category": pa.string(),
}
# Byte-stable across platforms for new tables (zstd / dictionary off / no statistics / no embedded arrow metadata).
# Note: Table A/Table B keep the old u0p5 write parameters (the old bytes are already on disk, deliberately not synced) - only the new byline_* tables use these.
_DET_KW: dict = {
    "compression": "zstd",
    "use_dictionary": False,
    "write_statistics": False,
    "store_schema": False,
}


def _sort_key(row: dict, cols) -> tuple:
    return tuple((row[c] is None, "" if row[c] is None else row[c]) for c in cols)


def _write_det(rows: list[dict], schema_map: dict[str, str], target, sort_cols) -> None:
    rows = sorted(rows, key=lambda r: _sort_key(r, sort_cols))
    arrays = {c: pa.array([r[c] for r in rows], type=_ARROW_TYPES[t]) for c, t in schema_map.items()}
    table = pa.table({c: arrays[c] for c in schema_map})
    target = pathlib.Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, str(target), row_group_size=max(1, table.num_rows), **_DET_KW)


_UNBOUND_SCHEMA = {"work_id": "str", "author_id": "str", "matched_phrase": "str",
                   "reason": "str", "affil_str": "str"}
_MISMATCH_SCHEMA = {"work_id": "str", "author_id": "str", "dept_key": "str"}


# ── Step 1: department matching → byline_dept_hits + byline_unbound sidecar ────────────────
def _iter_rows_full(files):
    cols = ["work_id", "author_id", "institution_id", RAW_COL]
    for f in files:
        pf = pq.ParquetFile(str(f))
        for batch in pf.iter_batches(columns=cols, batch_size=8192):
            yield from batch.to_pylist()


def _iter_rows_prefiltered(files, cfgs):
    """duckdb pre-filter = a semantic superset (case-insensitive substring of any phrase); it only speeds things up and never changes the semantics."""
    import duckdb

    con = duckdb.connect()
    phrases = sorted({p for c in cfgs for p in c["phrases"]})
    conds = " OR ".join(
        f"contains(lower(array_to_string({RAW_COL}, ' | ')), ?)" for _ in phrases
    )
    params = [p.lower() for p in phrases]
    paths = [str(f) for f in files]
    res = con.execute(
        f"SELECT work_id, author_id, institution_id, {RAW_COL} "
        f"FROM read_parquet({paths!r}) WHERE {conds}",
        params,
    )
    reader = (res.to_arrow_reader(8192) if hasattr(res, "to_arrow_reader")
              else res.fetch_record_batch(8192))
    for batch in reader:
        yield from batch.to_pylist()


def build_dept_hits(works_affil_dir, cfgs, out_dir, *, use_prefilter: bool = False) -> dict:
    files = _parquet_files(works_affil_dir)
    if not files:
        _halt(EXIT_ROSTER_UPSTREAM_FAIL, f"works_affil not present: {works_affil_dir}")
    # Probing only the first file is not enough - check the raw column type of every file (read from the footer, takes seconds);
    # a later file that has been flattened -> HALT 25 (the full path would silently drop rows / the prefilter path would crash with a raw error; neither is allowed).
    for f in files:
        rt = pq.ParquetFile(str(f)).schema_arrow.field(RAW_COL).type
        if not (pa.types.is_list(rt) and pa.types.is_string(rt.value_type)):
            _halt(EXIT_ROSTER_UPSTREAM_FAIL, f"{f.name}: {RAW_COL} is not list<string> ({rt})")

    school_inst = {c["dept_key"]: c["openalex_inst_id"] for c in cfgs}
    # (work, author, dept, phrase, style) → set[institution_id]; unbound → (w, a, phrase, reason, s)
    hit_insts: dict[tuple, set] = {}
    unbound: set[tuple] = set()
    rows_iter = _iter_rows_prefiltered(files, cfgs) if use_prefilter else _iter_rows_full(files)
    for row in rows_iter:
        raw = row[RAW_COL]
        if not raw:
            continue
        for s in raw:
            if s is None:
                continue
            b, ub = match_string(s, cfgs)
            for dk, phrase, style in b:
                hit_insts.setdefault(
                    (row["work_id"], row["author_id"], dk, phrase, style), set()
                ).add(row["institution_id"])
            for phrase, reason in ub:
                unbound.add((row["work_id"], row["author_id"], phrase, reason, s))

    out_dir = pathlib.Path(out_dir)
    ub_rows = [dict(zip(_UNBOUND_SCHEMA, t)) for t in unbound]
    # Fix: the sort key must cover all columns (the same 4-tuple with different raw strings gives tied sort keys -> set iteration order
    # drifts with PYTHONHASHSEED -> bytes differ across processes; confirmed with two seeds on real data).
    _write_det(ub_rows, _UNBOUND_SCHEMA, out_dir / "byline_unbound.parquet",
               ("work_id", "author_id", "matched_phrase", "reason", "affil_str"))

    if not hit_insts:
        _halt(EXIT_BYLINE_EMPTY_HITS_FAIL, "department-name whitelist matched 0 in total = the pipeline is broken (sidecar already written, no silent empty table)")

    def _pick_inst(dk: str, insts: set) -> str | None:
        if school_inst.get(dk) in insts:
            return school_inst[dk]
        non_null = sorted(i for i in insts if i is not None)
        return non_null[0] if non_null else None

    hit_rows = [
        {"work_id": w, "author_id": a, "dept_key": dk, "matched_phrase": ph,
         "institution_id": _pick_inst(dk, insts), "match_style": style}
        for (w, a, dk, ph, style), insts in hit_insts.items()
    ]
    _write_det(hit_rows, dict(BYLINE_DEPT_HITS), out_dir / "byline_dept_hits.parquet",
               ("work_id", "author_id", "dept_key", "matched_phrase", "match_style"))

    per_dept: dict[str, int] = {}
    for (_, _, dk, _ph, _st) in hit_insts:
        per_dept[dk] = per_dept.get(dk, 0) + 1
    return {"n_hits": len(hit_rows), "n_unbound": len(ub_rows), "per_dept": per_dept}


# ── Step 2: year determination → byline_year_evidence + byline_year_mismatch sidecar ──────
def build_year_evidence(hits_path, authorship_dir, out_dir) -> dict:
    hit_cols = pq.ParquetFile(str(hits_path)).schema_arrow.names
    if "match_style" not in hit_cols:
        _halt(EXIT_BYLINE_SCHEMA_FAIL,
              "hits is missing the match_style column (old 5-column file?) — n_printed_style would silently be all 0, rejected")
    hits = pq.read_table(str(hits_path)).to_pylist()
    depts_by_pair: dict[tuple, set] = {}
    printed_triples: set[tuple] = set()  # (work, author, dept) has support in printed form
    for h in hits:
        depts_by_pair.setdefault((h["work_id"], h["author_id"]), set()).add(h["dept_key"])
        if h.get("match_style") == "printed":
            printed_triples.add((h["work_id"], h["author_id"], h["dept_key"]))

    files = _parquet_files(authorship_dir)
    if not files:
        _halt(EXIT_ROSTER_UPSTREAM_FAIL, f"authorship_edges not present: {authorship_dir}")
    year_by_pair: dict[tuple, int] = {}
    for f in files:
        pf = pq.ParquetFile(str(f))
        for batch in pf.iter_batches(columns=["work_id", "author_id", "publication_year"],
                                     batch_size=65536):
            for r in batch.to_pylist():
                key = (r["work_id"], r["author_id"])
                if key in depts_by_pair and r["publication_year"] is not None:
                    y = int(r["publication_year"])
                    prev = year_by_pair.get(key)
                    if prev is not None and prev != y:
                        raise RuntimeError(
                            f"publication_year conflict (upstream data damaged; never a silent last-wins): {key} {prev} vs {y}"
                        )
                    year_by_pair[key] = y

    out_dir = pathlib.Path(out_dir)
    mismatch_pairs = sorted(set(depts_by_pair) - set(year_by_pair))
    mm_rows = [{"work_id": w, "author_id": a, "dept_key": dk}
               for (w, a) in mismatch_pairs for dk in sorted(depts_by_pair[(w, a)])]
    _write_det(mm_rows, _MISMATCH_SCHEMA, out_dir / "byline_year_mismatch.parquet",
               ("work_id", "author_id", "dept_key"))

    if not year_by_pair:
        _halt(EXIT_BYLINE_YEAR_NULL_FAIL,
              "no valid publication_year after the join (year source is broken; mismatch sidecar already written)")

    agg: dict[tuple, set] = {}
    printed_agg: dict[tuple, set] = {}
    for (w, a), year in year_by_pair.items():
        for dk in depts_by_pair[(w, a)]:
            agg.setdefault((a, dk, year), set()).add(w)
            if (w, a, dk) in printed_triples:
                printed_agg.setdefault((a, dk, year), set()).add(w)

    ev_rows = []
    for (a, dk, year), works in agg.items():
        src = sorted(works)
        if not src:
            raise RuntimeError(f"year point has no source work (red test #4): {(a, dk, year)}")
        ev_rows.append({"author_id": a, "dept_key": dk, "year": year,
                        "n_papers_that_year": len(src),
                        "n_printed_style": len(printed_agg.get((a, dk, year), ())),
                        "source_work_ids": src})
    _write_det(ev_rows, dict(BYLINE_YEAR_EVIDENCE), out_dir / "byline_year_evidence.parquet",
               ("author_id", "dept_key", "year"))
    return {"n_year_points": len(ev_rows), "n_mismatch": len(mm_rows)}
