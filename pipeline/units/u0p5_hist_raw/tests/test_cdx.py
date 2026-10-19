"""Crawler · Wayback CDX client TDD — covers the F1-F19 fixes plus the official API usage check.

Safeguards:
  - F7, main one: a truncated listing silently missing pages -> always showResumeKey=true; a full page with
    no key = possible truncation -> raise, and an incomplete listing is never treated as complete (a
    false 100% progress display is a data-loss pattern this repository guards against).
  - filter=statuscode:200: do not copy the `!` from the official README counter-example (that excludes 200).
  - collapse=timestamp:4 = one row per year; a missing year is normal, never fill with 0.
  - Fetching the raw page requires the `id_` suffix (no toolbar banner, links not rewritten).
  - Politeness: serial + sleep between requests + exponential backoff; pure logic with injected
    fetch/sleeper, so tests use no real network.
"""
import json

import pytest


def _page(rows, resume_key=None, header=True):
    payload = []
    if header:
        payload.append(["urlkey", "timestamp", "original", "mimetype",
                        "statuscode", "digest", "length"])
    payload.extend(rows)
    if resume_key is not None:
        payload.append([])
        payload.append([resume_key])
    return json.dumps(payload).encode("utf-8")


_R1 = ["au,edu,monash,buseco)/eco/staff", "20050214000000",
       "http://buseco.monash.edu.au/eco/staff/", "text/html", "200", "DIGEST1", "1000"]
_R2 = ["au,edu,monash,buseco)/eco/staff", "20060301000000",
       "http://buseco.monash.edu.au/eco/staff/", "text/html", "200", "DIGEST2", "1100"]


# ── URL construction ────────────────────────────────────────────────────────
def test_build_cdx_query_url_params():
    from histraw.cdx import build_cdx_query_url

    u = build_cdx_query_url("http://buseco.monash.edu.au/eco/staff/",
                            from_year=2000, to_year=2025)
    assert u.startswith("http://web.archive.org/cdx/search/cdx?")
    assert "from=2000" in u and "to=2025" in u
    assert "collapse=timestamp%3A4" in u or "collapse=timestamp:4" in u
    assert "output=json" in u
    assert "showResumeKey=true" in u, "F7 guard: always ask for resumeKey explicitly"
    assert "filter=statuscode%3A200" in u or "filter=statuscode:200" in u
    assert "%21statuscode" not in u and "!statuscode" not in u, (
        "the official README counter-example carries `!` = exclude 200 — never copy it"
    )
    assert "limit=" in u, "an explicit limit makes 'page full but no key' decidable (F7)"


def test_build_cdx_query_url_prefix_mode():
    from histraw.cdx import build_cdx_query_url

    u = build_cdx_query_url("http://buseco.monash.edu.au/eco/staff/",
                            from_year=2000, to_year=2025, match_prefix=True)
    assert "matchType=prefix" in u
    assert "collapse=urlkey" in u, "fetching a sub-page = prefix + collapse=urlkey (verified)"


def test_build_cdx_query_url_collapse_none_for_full_rows():
    """prefix all-rows mode: collapse=None -> no folding, get all year-by-year snapshot rows of each URL
    (aggregated locally into "which years each person page has an archive" = year-by-year employment evidence)."""
    from histraw.cdx import build_cdx_query_url

    u = build_cdx_query_url("http://x/staff/", from_year=2000, to_year=2025,
                            match_prefix=True, collapse=None)
    assert "matchType=prefix" in u
    assert "collapse" not in u, "collapse=None -> no collapse parameter is sent"
    u2 = build_cdx_query_url("http://x/staff/", from_year=2000, to_year=2025,
                             match_prefix=True)
    assert "collapse=urlkey" in u2, "default behavior unchanged"


# ── Parsing ────────────────────────────────────────────────────────────────
def test_parse_cdx_json_rows_and_resume_key():
    from histraw.cdx import parse_cdx_json

    rows, key = parse_cdx_json(_page([_R1, _R2], resume_key="KEY123"))
    assert len(rows) == 2
    assert rows[0]["timestamp"] == "20050214000000"
    assert rows[0]["original"] == "http://buseco.monash.edu.au/eco/staff/"
    assert rows[0]["digest"] == "DIGEST1"
    assert key == "KEY123"

    rows2, key2 = parse_cdx_json(_page([_R1]))
    assert len(rows2) == 1 and key2 is None


def test_parse_cdx_json_empty_result():
    from histraw.cdx import parse_cdx_json

    rows, key = parse_cdx_json(b"[]")
    assert rows == [] and key is None


# ── Paging + F7 truncation safeguard ──────────────────────────────────────────────────────
def test_list_snapshots_paginates_until_no_key():
    from histraw.cdx import list_snapshots

    calls = []

    def fetch(url):
        calls.append(url)
        if "resumeKey" not in url:
            return _page([_R1], resume_key="K1")
        return _page([_R2])

    slept = []
    rows = list_snapshots(fetch, "http://buseco.monash.edu.au/eco/staff/",
                          from_year=2000, to_year=2025,
                          sleeper=slept.append, min_delay_s=1.5)
    assert [r["digest"] for r in rows] == ["DIGEST1", "DIGEST2"]
    assert len(calls) == 2 and "resumeKey=K1" in calls[1]
    assert slept and all(d >= 1.5 for d in slept), "polite sleep between requests (serial, do not hammer)"


def test_list_snapshots_full_page_without_key_raises():
    """F7 main safeguard: rows == limit and no resumeKey = possibly cut by an internal cap ->
    raise; an incomplete listing is never silently treated as complete."""
    from histraw.cdx import list_snapshots

    def fetch(url):
        return _page([_R1, _R2])  # 2 rows, no key

    with pytest.raises(RuntimeError, match="truncated"):
        list_snapshots(fetch, "http://x/", from_year=2000, to_year=2025,
                       sleeper=lambda s: None, limit=2)


def test_list_snapshots_invalid_json_raises_not_partial():
    from histraw.cdx import list_snapshots

    def fetch(url):
        return b"<html>503 Service Unavailable</html>"

    with pytest.raises(Exception):
        list_snapshots(fetch, "http://x/", from_year=2000, to_year=2025,
                       sleeper=lambda s: None, max_retries=0)


def test_list_snapshots_retries_with_backoff_then_succeeds():
    from histraw.cdx import list_snapshots

    attempts = []

    def fetch(url):
        attempts.append(url)
        if len(attempts) == 1:
            raise ConnectionError("503")
        return _page([_R1])

    slept = []
    rows = list_snapshots(fetch, "http://x/", from_year=2000, to_year=2025,
                          sleeper=slept.append, min_delay_s=1.0, max_retries=2)
    assert len(rows) == 1 and len(attempts) == 2
    assert any(d > 1.0 for d in slept), "exponential backoff after a failure (longer than the normal interval)"


def test_list_snapshots_dedupes_and_sorts_deterministic():
    from histraw.cdx import list_snapshots

    def fetch(url):
        return _page([_R2, _R1, _R1])  # Out of order + duplicates

    rows = list_snapshots(fetch, "http://x/", from_year=2000, to_year=2025,
                          sleeper=lambda s: None)
    assert [r["digest"] for r in rows] == ["DIGEST1", "DIGEST2"], "sorted by timestamp ascending + de-duplicated"


# ── Raw-body fetch URL (id_) + year-by-year coverage ───────────────────────────────────────────
def test_snapshot_raw_url_has_id_flag():
    from histraw.cdx import snapshot_raw_url

    u = snapshot_raw_url("20050214000000", "http://buseco.monash.edu.au/eco/staff/")
    assert u == "https://web.archive.org/web/20050214000000id_/http://buseco.monash.edu.au/eco/staff/", (
        "a missing id_ -> toolbar HTML mixed into the body = dirty data (verified)"
    )


def test_years_covered_no_zero_fill():
    from histraw.cdx import years_covered

    rows = [dict(timestamp="20050214000000"), dict(timestamp="20050601000000"),
            dict(timestamp="20080101000000")]
    assert years_covered(rows) == [2005, 2008], "a missing year stays missing (not archived), never filled with 0 or a made-up year"
