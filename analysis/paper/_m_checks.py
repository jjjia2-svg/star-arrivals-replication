"""Checks the paper generators share under the canon switch. Each keeps October's output as it was; under M it
does what the new numbers need (final-03, 2026-10-18)."""
from __future__ import annotations

import hashlib
from pathlib import Path


def star_stocks(con, restake, field: str) -> dict:
    """{(author_id, arrival_true): after_stock} for one field's restake rows that have a stock. An M row with no
    stock (a candidate that is not an event) is left out; the caller still checks every event has one."""
    return {(a, int(y)): int(s) for a, y, s in con.execute(
        f"SELECT author_id, arrival_true, after_stock FROM read_csv_auto('{restake}') "
        f"WHERE field='{field}' AND after_stock IS NOT NULL").fetchall()}


def cell_is(cell: dict, path) -> bool:
    """A report cell names this estimate file and records its sha256. Only the file name is compared: the cell's
    path is the one on the instance that wrote the report."""
    p = Path(path)
    return Path(str(cell.get("json", ""))).name == p.name and \
        cell.get("json_sha256") == hashlib.sha256(p.read_bytes()).hexdigest()


def spell_start_note(ceil: dict, last_year: int = 2024) -> str:
    """The cross-check clause of roster_spell_max_start: the chem/math start years after each ceiling, up to
    last_year, that no verified spell may have. October (chem 2023, math 2020) gives its clause word for word."""
    parts = []
    for d in ("chem", "math"):
        lo = ceil[d] + 1
        if lo <= last_year:
            parts.append(f"no {d} start in {lo}" if lo == last_year else f"no {d} start in {lo}-{last_year}")
    if parts:
        return "(cross-checked: roster_chemmath_verified has " + ", ".join(parts) + ")"
    return f"(no year up to {last_year} to cross-check: every chem and math ceiling is later)"


def check_thesis_values(N: dict, want: dict, keys, mode: str) -> None:
    """October: each derived value must equal the thesis appendix's (the spec, never tuned). M: the values are the
    new numbers the final job installs, so nothing is asserted."""
    if mode != "october":
        return
    for k in sorted(keys):
        assert N[k] == want[k], (f"{k}: derived {N[k]!r} != thesis appendix {want[k]!r} — "
                                 "report this as a finding; do NOT tune the derivation to match")


def added_sheet_has_evidence(fieldnames) -> bool:
    """The econ added-roster sheet is October's form: its entries carry the evidence the fellow/DECRA and
    arc.gov.au rules read (evidence_url among the columns). R1's sheet is a spell table with none."""
    return "evidence_url" in (fieldnames or ())


def roster_counts(con, parquet) -> tuple[int, int]:
    """(people, spells) of a roster parquet: distinct author_id, and rows (one row per spell)."""
    people, spells = con.execute(
        f"SELECT count(DISTINCT author_id), count(*) FROM parquet_scan('{parquet}')").fetchone()
    return int(people), int(spells)


def report_describes_roster(block: dict, people: int, spells: int) -> bool:
    """A prep_final_report roster block counts this roster: the same people and the same spells."""
    return block.get("people") == people and block.get("spells") == spells


def _sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def nocentre_roster(roster, pins: dict, repo) -> Path | None:
    """The no-research-centre roster a run config pins beside the roster in force. The pin with the roster's
    sha256 is <name>.parquet and its twin <name>_incfel.parquet (config/r1/M.json, ruling R1P3-27: the roster
    the J1b no-centre unit reads). None when no pin has the roster's bytes or no twin is pinned; a twin whose
    bytes differ from its pin stops."""
    sha = _sha256(roster)
    for rel, pin in sorted(pins.items()):
        if pin != sha or not rel.endswith(".parquet") or rel.endswith("_incfel.parquet"):
            continue
        twin = rel[:-len(".parquet")] + "_incfel.parquet"
        if twin in pins:
            p = Path(repo) / twin
            got = _sha256(p)
            assert got == pins[twin], f"{twin}: sha256 {got} != its run-config pin {pins[twin]}"
            return p
    return None


def people_left_out(con, full, part) -> int:
    """People (distinct author_id) of the roster `full` who are not on the roster `part`."""
    return int(con.execute(
        f"SELECT count(DISTINCT author_id) FROM parquet_scan('{full}') WHERE author_id NOT IN "
        f"(SELECT author_id FROM parquet_scan('{part}') WHERE author_id IS NOT NULL)").fetchone()[0])


#: the schema of the cloud custody record rob_post_r1.py canon-pack writes for the J1b robustness batch
J1B_CUSTODY_SCHEMA = "sar.r1.rob_canon_custody.v1"


def rob_run(custody: dict) -> str:
    """The run a robustness ledger's inputs come from, as its cloud custody record names it: the J1b canon-pack
    record (its schema) or October's record (no schema). Any other schema stops."""
    schema = custody.get("schema")
    if schema is None:
        return "October (cal2026-10)"
    if schema == J1B_CUSTODY_SCHEMA:
        return "R1 M (J1b)"
    raise ValueError(f"unknown cloud custody schema {schema!r}")


def rob_source_note(rob_key: str, cloud_key: str, run: str) -> str:
    """ledger_robustness's _source_note, from canon.key() of its robustness and cloud roots and the run.
    October's keys and run give its note word for word."""
    return ("Section 4.2 ledger, generated by analysis/paper/ledger_robustness.py from the frozen "
            f"{run} robustness artifacts under {rob_key}/ and the "
            f"custody-chained cloud cells under {cloud_key}/ (each sha256-checked against its "
            "freeze MANIFEST or the custody record). Checks already "
            "ledgered in data_numbers_p1p2.json (LOEO, double-star, permutation P1/P2, by_route) and "
            "data_numbers_p3afar.json (Panel 3 date shift, dose cuts, null simulation, permutation) "
            "are not duplicated here; the table generator reads them from those ledgers.")
