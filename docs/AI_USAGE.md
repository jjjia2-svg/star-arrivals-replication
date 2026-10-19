# Use of AI tools

The work used two AI tools, as the report states: Claude (Anthropic) and Codex (OpenAI).

They were used to:

- **write and review code**: the code that collects the data, builds the panels and produces the
  estimates, tables and figures, and the tests, manifests and comparisons in this repository;
- **collect the staff lists**: AI agents read archived department pages, handbooks and other public
  sources and wrote down who worked in each department and when. For each list, one agent collected
  and a second agent checked it independently. Codex collected part of the economics roster;
- **match people to OpenAlex** author ids and check arrival years;
- **draft the star-origin readings** behind Figure 1 (where each star worked before arriving); each
  drafted reading was then checked blind;
- **edit the English** of the report and of this documentation.

The rosters record the verification row by row; it is not claimed for every row. 879 of the 2,640
economics roster rows are marked `human_verified`, counted directly from that column in
`data/report/cal/roster_econ_verified_2026-10.parquet`. The other rows rest on the AI-assisted collection and its independent check. The
collection and verification records are not shipped (see `pipeline/NOT_REPRODUCIBLE.md`).

The author takes full responsibility for the content of the report and of this package.
