"""Snapshot writer — store the web archive's raw page bodies locally, resumable (F3/F8 safeguards).

In plain words: following the CDX list, fetch each old page's "raw body" and store it; record a sha
fingerprint for each (taken from the fetched in-memory bytes, never re-read from disk — F3); it can
resume at any point (in manifest + file intact = skip); a corrupt file raises, nothing is silently
trusted. Before writing, the body passes an integrity gate (A8): an empty/truncated/non-HTML soft-404
body is not written, not recorded in the manifest and not counted in n_fetched (resume fetches it again).

Suspect pages (empty / too short / no HTML marker) are handled by QUARANTINE-AND-SKIP rather than by
raising and stopping the crawl: the evidence goes to the side file quarantine.jsonl, the crawl continues,
and the quarantine count appears explicitly in the run summary, never silently. Real IO/network errors
and a corrupt file / sha mismatch still raise (fail-loud is unchanged).
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re

from histraw.cdx import list_snapshots, snapshot_raw_url, years_covered

# A8: body integrity gate before writing (a data-integrity constant, not an identification choice).
# Byte floor: a fetched body below this size counts as empty/truncated (Wayback rate limiting often
# returns a 200 with an empty or half body). The floor is 256: real archived staff pages are
# KB-sized (fixtures ~12KB), so 256 is still far below any legitimate page; since suspect pages are
# quarantined instead of stopping the crawl, the floor can be raised without risking a halted crawl.
_MIN_SNAPSHOT_BYTES = 256
# HTML sanity: the body must contain at least one HTML structure marker; this rejects non-HTML soft-404/error bodies.
_HTML_SANITY_RE = re.compile(
    rb"<!doctype\s+html|"
    rb"<(?:html|head|body|div|table|ul|ol|li|tr|td|p|a|span|nav|section|h[1-6])[\s/>]",
    re.I)


def _validate_snapshot_body(body: bytes) -> str | None:
    """Return None = passes the gate; return a sentence = why it fails (for raise/quarantine). Never silently let an empty/truncated/non-HTML body through."""
    if not body:
        return "空正文 (0 字节)"
    if len(body) < _MIN_SNAPSHOT_BYTES:
        return f"正文过短 ({len(body)} 字节 < 地板 {_MIN_SNAPSHOT_BYTES}) — 疑似截断/软404"
    if not _HTML_SANITY_RE.search(body):
        return "正文无任何 HTML 结构标记 — 疑似软404/非HTML错误体"
    return None


class SnapshotStore:
    def __init__(self, store_dir):
        self.dir = pathlib.Path(store_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._manifest_path = self.dir / "manifest.jsonl"
        # Side list of quarantined suspect pages (JSON Lines, append order = processing order).
        # Created only on the first quarantine; not used in resume decisions (a quarantined page is always re-fetched on resume).
        self._quarantine_path = self.dir / "quarantine.jsonl"
        self._by_key: dict[tuple[str, str], dict] = {}
        if self._manifest_path.exists():
            for line in self._manifest_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self._by_key[(rec["timestamp"], rec["original"])] = rec

    @staticmethod
    def _filename(timestamp: str, original: str) -> str:
        urlhash = hashlib.sha256(original.encode("utf-8")).hexdigest()[:12]
        return f"{timestamp}__{urlhash}.raw"

    def save_snapshot(self, fetch, timestamp: str, original: str) -> dict:
        """Fetch one snapshot's raw body and write it. Already in manifest and file sha intact -> skip (resumable);
        file sha mismatch -> RuntimeError (a corrupt file is never silently trusted);
        suspect page (empty / too short / no HTML marker) -> quarantine and skip, return {"quarantined": True, ...}
        (real IO/network errors still raise)."""
        key = (timestamp, original)
        fname = self._filename(timestamp, original)
        target = self.dir / fname

        prev = self._by_key.get(key)
        if prev is not None:
            if not target.exists():
                raise RuntimeError(f"manifest has a record but the file is missing: {fname} — the archive was modified, check by hand")
            disk_sha = hashlib.sha256(target.read_bytes()).hexdigest()
            if disk_sha != prev["sha256"]:
                raise RuntimeError(
                    f"file sha does not match the manifest: {fname} ({disk_sha[:12]} != {prev['sha256'][:12]}) — corrupt file, fail loudly"
                )
            return dict(prev, skipped=True)

        body = fetch(snapshot_raw_url(timestamp, original))
        reason = _validate_snapshot_body(body)  # A8: an empty/truncated/soft-404 body is never written as a valid snapshot
        if reason is not None:
            # A suspect page is quarantined and skipped instead of raising:
            # not written to the snapshot store, not in manifest/_by_key (resume re-fetches it); the
            # evidence goes to the side file quarantine.jsonl (append+fsync, append order = processing
            # order, byte-deterministic); the caller counts rec["quarantined"] into the run summary,
            # never silently.
            qrec = {"timestamp": timestamp, "original": original, "reason": reason,
                    "n_bytes": len(body),
                    "body_sha256": hashlib.sha256(body).hexdigest()}
            with self._quarantine_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(qrec, ensure_ascii=False, sort_keys=True) + "\n")
                f.flush()
                os.fsync(f.fileno())
            return dict(qrec, quarantined=True)
        sha = hashlib.sha256(body).hexdigest()  # F3: the sha is taken from the in-memory buffer, not re-read from disk
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(body)
        os.replace(tmp, target)  # Atomic rename: a kill midway never leaves a half-written file looking final

        rec = {"timestamp": timestamp, "original": original,
               "filename": fname, "sha256": sha, "n_bytes": len(body)}
        with self._manifest_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._by_key[key] = rec
        return dict(rec, skipped=False)


def crawl_page_history(fetch, url: str, *, store_dir, from_year: int, to_year: int,
                       sleeper, min_delay_s: float = 1.5, max_retries: int = 3) -> dict:
    """Assembler: complete CDX list -> politely fetch each raw body and write it -> summary. Serial throughout, with sleeps."""
    rows = list_snapshots(fetch, url, from_year=from_year, to_year=to_year,
                          sleeper=sleeper, min_delay_s=min_delay_s,
                          max_retries=max_retries)
    store = SnapshotStore(store_dir)
    n_fetched = 0
    # Quarantined pages are not counted in n_fetched; their count goes explicitly into the summary
    # (>0 means the run is not clean), never silently; details are in store_dir/quarantine.jsonl.
    n_quarantined = 0
    for r in rows:
        sleeper(min_delay_s)
        rec = store.save_snapshot(fetch, r["timestamp"], r["original"])
        if rec.get("quarantined"):
            n_quarantined += 1
        elif not rec.get("skipped"):
            n_fetched += 1
    return {"url": url, "n_snapshots": len(rows), "n_fetched": n_fetched,
            "n_quarantined": n_quarantined,
            "years": years_covered(rows), "store_dir": str(store.dir)}
