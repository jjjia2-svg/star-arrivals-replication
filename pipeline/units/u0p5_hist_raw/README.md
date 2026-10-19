# u0p5_hist_raw — crawler for historical staff pages (Wayback snapshots)

> In plain words: ask the web archive (web.archive.org) which yearly snapshots exist, 2000-2025, of the
> economics department websites of two universities; politely fetch each **raw page body** and store it
> locally (with a sha fingerprint, resumable). Purpose: add people who do not publish to the historical
> roster, and give corroborating evidence for authorship candidates (evidence=wayback_snapshot, candidate
> layer; promoted to authoritative only after manual review).

## Status

- `src/histraw/cdx.py` — CDX listing client (11 tests pass): pages through to the end (resumeKey),
  **F7, the main safeguard** (a full page with no key = possible truncation -> raise; an incomplete
  listing is never treated as complete), filter=statuscode:200 (do not copy the `!` from the official
  counter-example), collapse=timestamp:4 gives one snapshot per year, `id_` raw URL, polite serial
  requests with exponential backoff, missing years are never filled with 0. fetch/sleeper are fully
  injected, so tests use no real network.
- `src/histraw/snapshot_store.py` — disk writer (6 tests pass): **F3 safeguard** (the sha256 is taken from
  the fetched in-memory bytes, never re-read from disk), resumable (in manifest + file sha intact ->
  skip), a corrupt file raises, atomic write (.tmp -> rename), manifest.jsonl append + fsync.
- **Real smoke test passed**: the old Monash domain `buseco.monash.edu.au/eco/staff/` has **ten yearly
  snapshots, 2006-2015**; the old UNSW domain `economics.unsw.edu.au` has **eleven, 2000-2010**. The raw
  2006 Monash page was saved under `derived/u0p5_hist_raw/wayback_smoke_2026-07-06/`; its id_ form is clean
  (no toolbar) and has 48 person-name links (the real 2006 list, including people who later left).

## Not written yet

- Name parser (old page HTML -> structured roster rows; page styles vary by era -> one template per site,
  with manual review as the fallback).
- Curated full URL list (staff-page addresses of both universities for each period; matchType=prefix to
  fetch personal sub-pages) and the full polite crawl.
- Merge into table B: evidence=`wayback_snapshot` (candidate layer, pending).
- F16 approach: manual small steps on live official-site pages + robots + Wayback as the fallback; ARC
  JSON:API as a corroborating channel.

## How to run

Pure-logic tests: `python3 -m pytest units/u0p5_hist_raw -q` (no real network).
Reference for a real smoke test: `histraw.cdx.list_snapshots(fetch, url, from_year=2000, to_year=2025, sleeper=time.sleep, min_delay_s=2.0)`;
fetch sends a self-identifying User-Agent, serial and slow.
