#!/usr/bin/env python3
"""count_words.py — word count under the course rule for the draft PDF.

Rule (author, 2026-09-13): at most 12,000 words INCLUDING tables, footnotes, bibliography and
appendices; EXCLUDING the title page, declarations, abstract and contents.

Method: PyMuPDF words on every page from the first body page to the end. A word is a token with at
least one letter or digit. The first body page is the page after the last front-matter page (a page
whose first lines contain "Contents", "Abstract" or "Declaration"), searched within the first 10
pages; override with --first-page (1-based).

Section split: lines are read in order; a heading is a line holding only a section number
("2", "2.2", "2.2.1") followed by a title line, or a line "References", or a line starting
"Appendix <n>:". Words are credited to the last heading seen, so subsections get their own counts.
Table and figure words are credited to the section in which they are printed.

Usage: python3 count_words.py main.pdf [--first-page N] [--json out.json]
"""
import argparse, json, re

import fitz

ap = argparse.ArgumentParser()
ap.add_argument("pdf")
ap.add_argument("--first-page", type=int, default=None)
ap.add_argument("--json", default=None)
a = ap.parse_args()
doc = fitz.open(a.pdf)

first = a.first_page
if first is None:
    last_front = -1
    for i in range(min(10, len(doc))):
        head = [l.strip() for l in doc[i].get_text().splitlines() if l.strip()][:6]
        if any(re.match(r"^(Contents|Abstract|Declarations?)\b", h) for h in head):
            last_front = i
    first = last_front + 2

NUM = re.compile(r"^\d(?:\.\d){0,2}$")
TITLE = re.compile(r"^[A-Z][^\n]{2,90}$")
counts, order, current, total = {}, [], "(before first heading)", 0
for i in range(first - 1, len(doc)):
    lines = [l.strip() for l in doc[i].get_text().splitlines()]
    j = 0
    while j < len(lines):
        l = lines[j]
        if NUM.match(l) and j + 1 < len(lines) and TITLE.match(lines[j + 1]) and not re.search(r"\d{3}", lines[j + 1]):
            current = f"{l} {lines[j + 1]}"
            j += 2
            continue
        if l == "References" or re.match(r"^Appendix \d+:", l):
            current = l
        n = sum(1 for w in l.split() if re.search(r"[A-Za-z0-9]", w))
        if current not in counts:
            counts[current] = 0
            order.append(current)
        counts[current] += n
        total += n
        j += 1

print(f"pages {first}-{len(doc)} counted (of {len(doc)})")
for k in order:
    print(f"  {counts[k]:6d}  {k}")
print(f"TOTAL {total}  (limit 12,000; margin {12000 - total:+d})")
if a.json:
    json.dump({"first_page": first, "pages": len(doc), "total": total, "sections": [{"heading": k, "words": counts[k]} for k in order]}, open(a.json, "w"), indent=1)
