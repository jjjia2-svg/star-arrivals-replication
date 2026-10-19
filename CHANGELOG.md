# Changelog

## 1.0 (2026-10-19)

First public release. It reproduces the report as submitted (377 events), from the data in
`data/report/`. The October 2026 (184 events) and August 2026 (187 events) versions are kept as
checks.

How this copy differs from the author's private working repository:

- **Names replaced.** Person names in data, code, tests and documentation are replaced by OpenAlex
  author ids. The rosters keep only ids, years and fixed codes.
- **Records not shipped.** The verification originals (staff pages, evidence links and notes), the
  AI-session records, and the AWS run records other than the custody records are not published.
- **English codes.** Chinese codes and notes in the data are replaced by English codes, and Chinese
  comments by their English translation, except in the files a custody record pins by hash (the
  drivers `run_p3.R` and `run_p3_evcl.R`, their earlier copies and the pinned run logs), which are
  byte copies.
- **Hashes follow the published files.** Where a file was changed for this copy, the manifests and
  pins give the published sha256; `HASH_CROSSWALK.md` gives the private value next to it.

No estimate, panel value or estimation code was changed.
