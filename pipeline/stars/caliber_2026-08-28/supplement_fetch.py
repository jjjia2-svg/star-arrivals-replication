# -*- coding: utf-8 -*-
"""caliber_2026-08-28/supplement_fetch.py — the Task-2 star-works supplement machinery: the ONLY
code in the caliber rebuild allowed to touch the live OpenAlex API. Repo-authored.

What it replicates and where it deliberately differs from the ported original
(`pipeline/rosters/multidisc_gold_2026-08-10/code/70_prep_fnfix_inputs.py`, lines 62-91):

* the WIRE PROTOCOL is `70_prep`'s: `GET https://api.openalex.org/works` filtered on
  `author.id:<id>`, per-page 200, cursor pagination, `mailto` + `api_key`, polite 0.15 s between
  pages, up to 6 retries with linear backoff on failure;
* the EMITTED supplement row is byte-shape-identical to `70_prep`'s
  (`json.dumps({"work_id", "publication_year", "type", "seed_author", "authors"})` — same key
  order, same default separators, ensure_ascii, one row per line);
* the `select` asks for two EXTRA fields (`doi`, `cited_by_count`) that never enter the supplement
  row — they exist so the frozen per-star works JSON can carry the citation counts the dossier
  cross-checks pin (A5017222669's merge works), without a second fetch;
* every request is LOGGED (endpoint, params minus the api key, status, result count, elapsed) to a
  request log that is frozen with the outputs — `70_prep` logged nothing;
* the per-star cleanups (A5091826237 −4, A5017222669 −1, A5062352558's 24th call) are applied as DATA-driven filters
  from `data/cal2026-08-28/calls_2026-08-28.csv` via `cleaned_works.exclusions()` — `70_prep`
  fetched unfiltered, which is exactly the hole the A5062352558 completeness report documented.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import time

import requests

API = "https://api.openalex.org/works"
MAILTO = "jjjia2@student.unimelb.edu.au"          # the same contact 70_prep sent
SELECT = "id,doi,publication_year,type,authorships,cited_by_count"
#: the exact five keys, in the exact order, of a 70_prep supplement row
SUPPLEMENT_KEYS = ("work_id", "publication_year", "type", "seed_author", "authors")


def short(s: str | None) -> str:
    """`https://openalex.org/W123` -> `W123` — 70_prep's own lambda, named."""
    return s.rsplit("/", 1)[-1] if s else ""


def api_key() -> str | None:
    """$OPENALEX_API_KEY, or the export line in ~/.zshrc (the ported scripts' own convention)."""
    key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if key:
        return key
    zshrc = pathlib.Path("~/.zshrc").expanduser()
    if zshrc.is_file():
        for line in zshrc.read_text(errors="ignore").splitlines():
            m = re.search(r'OPENALEX_API_KEY=["\']?([^"\'\s]+)', line)
            if m:
                return m.group(1)
    return None


class RequestLog:
    """One JSON line per HTTP request. The api key NEVER enters an entry."""

    def __init__(self) -> None:
        self.entries: list[dict] = []

    def add(self, *, seed: str, params: dict, status, n_results: int, ms: int,
            attempt: int) -> None:
        clean = {k: (str(v)[:24] if k == "cursor" else v)
                 for k, v in params.items() if k != "api_key"}
        self.entries.append({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "endpoint": API, "seed": seed,
            "params": clean, "status": status, "n_results": n_results, "ms": ms,
            "attempt": attempt})

    def write(self, path: pathlib.Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for e in self.entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _get(params: dict, log: RequestLog, seed: str) -> dict:
    """One logged request with 70_prep's retry ladder (6 attempts, 2·(n+1) s backoff)."""
    for att in range(6):
        t0 = time.time()
        status: object = "EXC"
        try:
            rs = requests.get(API, params=params, timeout=60)
            status = rs.status_code
            if rs.status_code == 200:
                js = rs.json()
                log.add(seed=seed, params=params, status=status,
                        n_results=len(js.get("results", [])),
                        ms=int((time.time() - t0) * 1000), attempt=att)
                return js
        except requests.RequestException:
            pass
        log.add(seed=seed, params=params, status=status, n_results=0,
                ms=int((time.time() - t0) * 1000), attempt=att)
        time.sleep(2 * (att + 1))
    raise RuntimeError(f"OpenAlex API failed 6 times for {seed}")


def work_record(w: dict) -> dict:
    """The frozen works-JSON record: the supplement fields plus doi and cited_by_count."""
    authors = [short((a.get("author") or {}).get("id", "")) for a in w.get("authorships", [])]
    return {"work_id": short(w["id"]),
            "doi": (w.get("doi") or "").lower().replace("https://doi.org/", ""),
            "publication_year": w.get("publication_year"), "type": w.get("type"),
            "cited_by_count": w.get("cited_by_count"),
            "authors": [a for a in authors if a]}


def fetch_author_works(aid: str, key: str | None, log: RequestLog) -> list[dict]:
    """All works of one author profile, in API return order, as `work_record`s."""
    rows, cursor = [], "*"
    while cursor:
        params = {"filter": f"author.id:{aid}", "per-page": 200, "cursor": cursor,
                  "select": SELECT, "mailto": MAILTO}
        if key:
            params["api_key"] = key
        js = _get(params, log, seed=aid)
        rows.extend(work_record(w) for w in js.get("results", []))
        cursor = js.get("meta", {}).get("next_cursor")
        time.sleep(0.15)
    return rows


def fetch_works_by_id(work_ids: list[str], key: str | None, log: RequestLog,
                      seed: str) -> list[dict]:
    """Named works in ONE filter request (`ids.openalex:` OR-join). A merged-away or missing id is
    simply absent from the result — the caller decides whether that is a STOP."""
    params = {"filter": "ids.openalex:" + "|".join(work_ids), "per-page": 200,
              "select": SELECT, "mailto": MAILTO}
    if key:
        params["api_key"] = key
    js = _get(params, log, seed=seed)
    return [work_record(w) for w in js.get("results", [])]


def supplement_line(rec: dict, seed_author: str) -> str:
    """One supplement JSONL line, byte-shaped exactly like 70_prep's write."""
    return json.dumps({"work_id": rec["work_id"], "publication_year": rec["publication_year"],
                       "type": rec["type"], "seed_author": seed_author,
                       "authors": rec["authors"]}) + "\n"


def a5062352558_rows_from_cache(cache: list[dict], live: list[dict]) -> tuple[list[dict], dict]:
    """A5062352558's works, sourced from her frozen 227-work cache where possible (the cache is the
    08-15 frozen authority for membership, year and authors), fetching from the live profile only
    what the cache lacks: the `type` field (never stored by `75_prefetch_star_works.py`) and any
    works added to the profile since 08-15.

    Returns (records in cache order + live-only additions in live order, reconciliation dict).
    The caller STOPs if `missing_from_live` is non-empty (a cached work left her profile = the
    profile moved since the dossiers)."""
    live_by_id = {r["work_id"]: r for r in live}
    cache_ids = {c["work_id"] for c in cache}
    recs, diffs = [], []
    for c in cache:
        lv = live_by_id.get(c["work_id"])
        recs.append({"work_id": c["work_id"], "doi": c.get("doi", ""),
                     "publication_year": c["year"],
                     "type": lv["type"] if lv else None,
                     "cited_by_count": lv["cited_by_count"] if lv else None,
                     "authors": c["authors"]})
        if lv and (lv["publication_year"] != c["year"] or lv["authors"] != c["authors"]):
            diffs.append({"work_id": c["work_id"],
                          "cache": {"year": c["year"], "n_authors": len(c["authors"])},
                          "live": {"year": lv["publication_year"],
                                   "n_authors": len(lv["authors"])}})
    live_only = [r for r in live if r["work_id"] not in cache_ids]
    recs.extend(live_only)
    recon = {"cache_works": len(cache), "live_works": len(live),
             "missing_from_live": sorted(cache_ids - set(live_by_id)),
             "live_only_added": [r["work_id"] for r in live_only],
             "field_diffs_cache_kept": diffs}
    return recs, recon
