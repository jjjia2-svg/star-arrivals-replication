"""Wayback CDX client — list yearly snapshots (first piece of the crawler; pure logic, no real network).

In plain words: ask the web archive which snapshots of an old staff page exist for each year 2000-2025,
get the complete list (page through to the end; truncation raises), and build the URL that returns the
"raw page body" (with id_, so no toolbar is mixed in).

Safeguards:
  - F7, main one: always showResumeKey=true plus an explicit limit; a full page with no key = possible
    truncation -> raise.
  - filter=statuscode:200 (do not copy the `!` from the official counter-example); collapse=timestamp:4
    gives one snapshot per year.
  - Politeness: serial requests + sleep between requests + exponential backoff; fetch/sleeper are
    injected, so tests and production take the same path.
  - A missing year is normal (not archived); never fill with 0 or invent a year.
"""
from __future__ import annotations

import json
import urllib.parse

CDX_ENDPOINT = "http://web.archive.org/cdx/search/cdx"
_COLUMNS = ("urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length")
_DEFAULT_LIMIT = 5000


_COLLAPSE_DEFAULT = "__default__"


def build_cdx_query_url(url: str, *, from_year: int, to_year: int,
                        match_prefix: bool = False, limit: int = _DEFAULT_LIMIT,
                        resume_key: str | None = None,
                        collapse: str | None = _COLLAPSE_DEFAULT) -> str:
    params = [
        ("url", url),
        ("from", str(from_year)),
        ("to", str(to_year)),
        ("filter", "statuscode:200"),  # Positive filter on 200 — the official README's counter-example has `!`, which excludes; do not copy it
        ("output", "json"),
        ("showResumeKey", "true"),     # F7: always ask for the key explicitly
        ("limit", str(limit)),
    ]
    if match_prefix:
        params.append(("matchType", "prefix"))
        if collapse is _COLLAPSE_DEFAULT:
            collapse = "urlkey"  # Default: list sub-pages, one row per URL
    else:
        if collapse is _COLLAPSE_DEFAULT:
            collapse = "timestamp:4"  # Default: one row per year (first 4 of the 14-digit timestamp)
    if collapse is not None:
        params.append(("collapse", collapse))  # collapse=None -> all rows (aggregate year-by-year evidence locally)
    if resume_key is not None:
        params.append(("resumeKey", resume_key))
    return f"{CDX_ENDPOINT}?{urllib.parse.urlencode(params)}"


def parse_cdx_json(payload: bytes) -> tuple[list[dict], str | None]:
    """CDX json output -> (list of row dicts, resume_key|None).

    Format: first row is the header; if there is a paging key, the tail is two rows, [] and ["<key>"]
    (an oddity of the official JSON).
    """
    data = json.loads(payload.decode("utf-8"))
    if not data:
        return [], None
    resume_key = None
    if len(data) >= 2 and data[-2] == [] and len(data[-1]) == 1:
        resume_key = data[-1][0]
        data = data[:-2]
    header, rows = data[0], data[1:]
    idx = {name: header.index(name) for name in _COLUMNS if name in header}
    out = [{name: r[i] for name, i in idx.items()} for r in rows]
    return out, resume_key


def list_snapshots(fetch, url: str, *, from_year: int, to_year: int,
                   sleeper, min_delay_s: float = 1.5, max_retries: int = 3,
                   limit: int = _DEFAULT_LIMIT, match_prefix: bool = False,
                   collapse: str | None = _COLLAPSE_DEFAULT) -> list[dict]:
    """Page to the end and return the complete snapshot list. fetch: url->bytes (injected); sleeper: seconds->None (injected).

    - Sleep >= min_delay_s between requests (serial, polite); on failure back off exponentially
      (2^n times min_delay).
    - F7: a page with rows == limit and no resume key -> RuntimeError (possibly truncated, not treated as complete).
    - Returns rows sorted ascending by (timestamp, urlkey) and de-duplicated — deterministic.
    """
    rows: list[dict] = []
    resume_key = None
    first = True
    while True:
        query = build_cdx_query_url(url, from_year=from_year, to_year=to_year,
                                    match_prefix=match_prefix, limit=limit,
                                    resume_key=resume_key, collapse=collapse)
        if not first:
            sleeper(min_delay_s)
        first = False
        payload = None
        for attempt in range(max_retries + 1):
            try:
                payload = fetch(query)
                break
            except Exception:
                if attempt >= max_retries:
                    raise
                sleeper(min_delay_s * (2 ** (attempt + 1)))  # Exponential backoff
        page_rows, resume_key = parse_cdx_json(payload)
        rows.extend(page_rows)
        if resume_key is None:
            if len(page_rows) >= limit:
                raise RuntimeError(
                    f"CDX page full ({len(page_rows)} rows == limit) and no resumeKey — may be truncated by an internal limit, "
                    "an incomplete list is never treated as complete (F7)"
                )
            break

    seen: set[tuple] = set()
    deduped = []
    for r in sorted(rows, key=lambda r: (r.get("timestamp", ""), r.get("urlkey", ""))):
        key = (r.get("urlkey"), r.get("timestamp"), r.get("digest"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


def snapshot_raw_url(timestamp: str, original_url: str) -> str:
    """URL for the raw page body — must carry id_ (no toolbar banner, links not rewritten; without it the data is dirty)."""
    return f"https://web.archive.org/web/{timestamp}id_/{original_url}"


def years_covered(rows: list[dict]) -> list[int]:
    """Snapshot rows -> list of covered years (ascending, de-duplicated). A missing year stays missing; never fill with 0 or invent a year."""
    return sorted({int(r["timestamp"][:4]) for r in rows if r.get("timestamp")})
