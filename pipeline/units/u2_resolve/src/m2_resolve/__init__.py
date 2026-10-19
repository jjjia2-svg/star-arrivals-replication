"""U2 entity resolution / disambiguation (M2): merges the author_ids that OpenAlex split for one real person back into a single person_id.

resolve.py = the only producer of person_map (R1-R5).
gate.py    = acceptance + diagnostics + manual-review queue; it does not produce person_map (G1-G4).
For conventions and redlines see ../../CONTRACT.md + ../../README.md; every identification threshold is null -> RedlineUnsigned (a value must be set by hand).
"""
