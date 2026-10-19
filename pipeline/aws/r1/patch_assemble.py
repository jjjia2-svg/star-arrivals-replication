#!/usr/bin/env python3
"""R1 F18 (C7), instance side: the outcome patch from the raw OpenAlex pages the Mac fetched
(tools/r1_patch_fetch.py fetch-only + upload; a Mac tool, not shipped). No network: it reads pages pulled from S3 r1/patch_raw/<tag>/
and writes works_by_author rows in the exact shape of the 2026-08-13 patch, through October's own row
function (econ920/fetch_patch_supplement.patch_row and KEYS; that file is not edited).

  patch_assemble.py [--raw /work/patch_raw/<tag> ... --manifest <committed patch_raw_<tag>.json> ...
                     --known-patches <frozen 08-13 patch> --known-patches <patch_supplement_2026-10 jsonl> ...]
                    --out $STAGE_OUT [--repo $REPO_DIR]
  -> works_by_author_supplement_r1.jsonl   one line per (person, work), manifest order (person, then page), each
                                           json.dumps({k: patch_row(aid, w)[k] for k in KEYS}, ensure_ascii=False)
     report_patch_assemble.json            tags, per-person work counts, empty profiles, output sha256
With no --raw/--manifest (config M lists no tag) it writes an empty jsonl and a report with status 'no tags'.

STOP (exit 3, stop_report_patch_assemble.json {code, ids, message}, no jsonl):
  SHA_MISMATCH / MISSING / UNPINNED   the pulled tag differs from the committed upload record
  BAD_PAGES                           manifest.tsv, page numbering, the cursor end or a result count disagree
  KNOWN_PERSON                        a fetched person already has rows in a known patch (no double rows into 04)
  DUP_PERSON / DUP_TAG                a person fetched under two tags / a tag given twice
  BAD_RECORD                          a --manifest that is not an upload record
Runs only on an R1 instance ($SAR_HOST).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys

AWS_HOSTS = ("ec2-r1-test", "ec2-r1")
OUT_NAME = "works_by_author_supplement_r1.jsonl"
REPORT_NAME = "report_patch_assemble.json"
STOP_NAME = "stop_report_patch_assemble.json"
SCHEMA = "sar.r1.patch_raw_upload.v1"
MANIFEST_COLS = ("person", "page", "path", "sha256", "bytes", "n_results")
SKIP_NAMES = {".DS_Store"}
PAGE = re.compile(r"^(A\d+)/page_(\d{3,})\.json$")
PERSON = re.compile(r"^(?:P_)?(A\d{4,12})$")


class AssembleStop(Exception):
    """A refusal the stage reports as STOP (exit 3) with the ids involved."""

    def __init__(self, code: str, message: str, ids=()):
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.ids = code, message, sorted(set(ids))


def sha256_file(p: pathlib.Path) -> str:
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def _fps(repo: pathlib.Path):
    """October's row writer, imported from the checkout (the stage may run a copy of this file)."""
    for p in (repo, repo / "pipeline" / "stars" / "caliber_2026-08-28", repo / "pipeline" / "frames" / "cal2026-10" / "econ920"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    import fetch_patch_supplement as fps                            # noqa: PLC0415
    return fps


# ---- checks -------------------------------------------------------------------------------------
def check_tag(tdir, rec: dict) -> list:
    """The pulled tag against its committed upload record: every pinned file present with its sha256, nothing
    extra. Then manifest.tsv against the pages. -> manifest rows (dicts), in fetch order."""
    tdir = pathlib.Path(tdir)
    tag = rec.get("tag")
    if rec.get("schema") != SCHEMA or not isinstance(rec.get("files"), dict) or not tag:
        raise AssembleStop("BAD_RECORD", f"{tdir.name}: not a {SCHEMA} upload record")
    files = {}
    for p in sorted(tdir.rglob("*")):
        rel = p.relative_to(tdir).as_posix()
        if p.is_symlink():
            raise AssembleStop("UNPINNED", f"{tag}: symlink {rel}")
        if p.is_file() and p.name not in SKIP_NAMES:
            files[rel] = p
    missing = sorted(set(rec["files"]) - set(files))
    if missing:
        raise AssembleStop("MISSING", f"{tag}: {len(missing)} pinned file(s) not pulled ({', '.join(missing[:5])})",
                           ids=[m.split('/')[0] for m in missing if PAGE.match(m)])
    extra = sorted(set(files) - set(rec["files"]))
    if extra:
        raise AssembleStop("UNPINNED", f"{tag}: {len(extra)} file(s) the committed record does not pin "
                                       f"({', '.join(extra[:5])})", ids=[e.split('/')[0] for e in extra if PAGE.match(e)])
    bad = sorted(k for k, p in files.items() if sha256_file(p) != rec["files"][k])
    if bad:
        raise AssembleStop("SHA_MISMATCH", f"{tag}: {len(bad)} file(s) differ from the committed record "
                                           f"({', '.join(bad[:5])})", ids=[b.split('/')[0] for b in bad if PAGE.match(b)])
    if "manifest.tsv" not in files:
        raise AssembleStop("BAD_PAGES", f"{tag}: no manifest.tsv")
    lines = files["manifest.tsv"].read_text(encoding="utf-8").splitlines()
    if not lines or tuple(lines[0].split("\t")) != MANIFEST_COLS:
        raise AssembleStop("BAD_PAGES", f"{tag}: manifest.tsv header")
    rows = [dict(zip(MANIFEST_COLS, x.split("\t"))) for x in lines[1:] if x]
    pages = {k for k in files if PAGE.match(k)}
    if {r["path"] for r in rows} != pages or len(rows) != len(pages):
        raise AssembleStop("BAD_PAGES", f"{tag}: manifest.tsv and the pages disagree")
    for r in rows:
        m = PAGE.match(r["path"])
        if m.group(1) != r["person"] or int(m.group(2)) != int(r["page"]) or rec["files"][r["path"]] != r["sha256"]:
            raise AssembleStop("BAD_PAGES", f"{tag}: manifest row {r['path']} disagrees with itself", ids=[r["person"]])
    persons = list(dict.fromkeys(r["person"] for r in rows))
    if persons != list(rec.get("persons") or []):
        raise AssembleStop("BAD_PAGES", f"{tag}: the record's persons differ from manifest.tsv")
    return rows


def known_persons(paths) -> set:
    """Every author_id with a row in a known patch (the frozen 08-13 patch, October's patch_supplement_2026-10, ...)."""
    out = set()
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    m = PERSON.match(str(json.loads(line).get("author_id", "")))
                    if m:
                        out.add(m.group(1))
    return out


def person_rows(tdir: pathlib.Path, rows: list, fps) -> tuple:
    """-> ({aid: [patch rows]}, {aid: n works}) from the cursor pages, after checking each walk is whole."""
    by, counts = {}, {}
    for aid in dict.fromkeys(r["person"] for r in rows):
        mine = sorted((r for r in rows if r["person"] == aid), key=lambda r: int(r["page"]))
        if [int(r["page"]) for r in mine] != list(range(1, len(mine) + 1)):
            raise AssembleStop("BAD_PAGES", f"{aid}: pages are not 1..{len(mine)}", ids=[aid])
        out = []
        for i, r in enumerate(mine):
            js = json.loads((tdir / r["path"]).read_bytes())
            res = js.get("results") or []
            if len(res) != int(r["n_results"]):
                raise AssembleStop("BAD_PAGES", f"{r['path']}: {len(res)} results, manifest says {r['n_results']}", ids=[aid])
            last = js.get("meta", {}).get("next_cursor") in (None, "")
            if last != (i == len(mine) - 1):
                raise AssembleStop("BAD_PAGES", f"{aid}: the cursor walk does not end at the last page", ids=[aid])
            out.extend(fps.patch_row(aid, w) for w in res)
        by[aid], counts[aid] = out, len(out)
    return by, counts


# ---- main ---------------------------------------------------------------------------------------
def assemble(raws, manifests, known, fps) -> dict:
    recs = [json.loads(pathlib.Path(m).read_text(encoding="utf-8")) for m in manifests]
    by_tag = {}
    for rec in recs:
        if rec.get("tag") in by_tag:
            raise AssembleStop("DUP_TAG", f"tag {rec.get('tag')} given twice")
        by_tag[rec.get("tag")] = rec
    dirs = {pathlib.Path(r).name: pathlib.Path(r) for r in raws}
    if set(dirs) != set(by_tag) or len(dirs) != len(raws):
        raise SystemExit(f"--raw dirs {sorted(dirs)} and --manifest tags {sorted(map(str, by_tag))} must pair one to one "
                         f"(each raw dir is named after its tag)")
    order, rows_by_tag = [], {}
    for tag, rec in by_tag.items():
        rows_by_tag[tag] = check_tag(dirs[tag], rec)
        order += [(tag, aid) for aid in dict.fromkeys(r["person"] for r in rows_by_tag[tag])]
    seen = [aid for _, aid in order]
    dup = sorted({a for a in seen if seen.count(a) > 1})
    if dup:
        raise AssembleStop("DUP_PERSON", f"{len(dup)} person(s) fetched under two tags", ids=dup)
    clash = sorted(set(seen) & known_persons(known))
    if clash:
        raise AssembleStop("KNOWN_PERSON", f"{len(clash)} person(s) already have rows in a known patch "
                                           "(rows would enter 04 twice)", ids=clash)
    text, counts = [], {}
    for tag in by_tag:
        by, c = person_rows(dirs[tag], rows_by_tag[tag], fps)
        counts.update(c)
        for aid in by:
            text += [json.dumps({k: r[k] for k in fps.KEYS}, ensure_ascii=False) + "\n" for r in by[aid]]
    return {"tags": list(by_tag), "counts": counts, "text": "".join(text),
            "known_patches": {pathlib.Path(k).name: sha256_file(k) for k in known},
            "records": {t: {"persons": len(r["persons"]), "n_pages": r.get("n_pages")} for t, r in by_tag.items()}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1 F18: works_by_author rows from raw OpenAlex pages (instance, no network)")
    ap.add_argument("--raw", action="append", default=[], type=pathlib.Path, help="a pulled r1/patch_raw/<tag>/ dir")
    ap.add_argument("--manifest", action="append", default=[], type=pathlib.Path,
                    help="the committed data/cal2026-10r1/aws/uploads/patch_raw_<tag>.json (not shipped)")
    ap.add_argument("--known-patches", action="append", default=[], type=pathlib.Path,
                    help="a works_by_author jsonl whose persons must not be fetched again (08-13 patch, October supplement)")
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--repo", type=pathlib.Path, default=pathlib.Path(os.environ.get("REPO_DIR") or pathlib.Path(__file__).resolve().parents[3]))
    a = ap.parse_args(argv)
    if os.environ.get("SAR_HOST", "").strip() not in AWS_HOSTS:
        raise SystemExit("R1 rule (design v3 §4): patch_assemble.py runs only on an R1 instance ($SAR_HOST)")
    if bool(a.raw) != bool(a.manifest):
        raise SystemExit("--raw and --manifest go together (one per tag)")
    if a.raw and not a.known_patches:
        raise SystemExit("--known-patches is required with pages: the frozen 08-13 patch and patch_supplement_2026-10")
    for p in [*a.raw, *a.manifest, *a.known_patches]:
        if not p.exists():
            raise SystemExit(f"input missing: {p}")
    if any((a.out / n).exists() for n in (OUT_NAME, REPORT_NAME, STOP_NAME)):
        raise SystemExit(f"{a.out} already holds patch_assemble outputs; give a fresh --out")
    fps = _fps(a.repo.resolve())
    a.out.mkdir(parents=True, exist_ok=True)
    try:
        res = assemble(a.raw, a.manifest, a.known_patches, fps) if a.raw else \
            {"tags": [], "counts": {}, "text": "", "known_patches": {}, "records": {}}
    except AssembleStop as e:
        (a.out / STOP_NAME).write_text(json.dumps({"code": e.code, "ids": e.ids, "message": e.message, "result": "STOP"},
                                                  indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"STOP {e.code}: {e.message}", file=sys.stderr)
        return 3
    out = a.out / OUT_NAME
    out.write_bytes(res["text"].encode("utf-8"))
    counts = res["counts"]
    rep = {"schema": "sar.r1.patch_assemble.v1", "result": "OK", "status": "assembled" if res["tags"] else "no tags",
           "tags": res["tags"], "n_rows": sum(counts.values()), "n_persons": len(counts), "counts": counts,
           "n_empty": sum(1 for v in counts.values() if v == 0), "empty": [k for k, v in counts.items() if v == 0],
           "records": res["records"], "known_patches": res["known_patches"], "output": {OUT_NAME: sha256_file(out)}}
    (a.out / REPORT_NAME).write_text(json.dumps(rep, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"OK {rep['status']}: {rep['n_rows']} rows, {rep['n_persons']} persons ({rep['n_empty']} empty profiles)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
