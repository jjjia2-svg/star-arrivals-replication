# DEVIATION — the union rung's G-DOSE gate was overridden (PROVISIONAL products)

Author ruling pending at export time (2026-09-23): the union rung's G-DOSE gate on this draw fails by sample composition alone — every failing drawn relation is a residual the frozen 08-15 rows carry (measured over the whole population, gdose phase); the gate decides only whether the clone writes its file and changes no row. Products built under this override are PROVISIONAL until the author signs the ruling; nothing canonical (data/frames, analysis/expected) is touched.

* this draw: {'n': 200, 'missing_side': 0, 'max_abs_diff': 0.06976307155210071, 'share_exact_1e-9': 0.885}
* the 08-13 draw: {'max_abs_diff': 0.0018986229421242284, 'share_exact_1e-9': 0.905}
* the whole old-relation population on the frozen inputs: {'n': 4470, 'share_exact_1e-9': 0.892841163310962, 'max_abs_diff': 0.13435585579294373, 'n_gt_0.01': 34, 'n_gt_0.05': 5}
* failing drawn relations (all frozen-population residuals): [{'pid': 'A5105845982', 'event_id': 'A5105828272:2011', 'frozen_dose': 0.6484369942598012, 'recomputed': 0.6610667189586307, 'abs_diff': 0.012629724698829503}, {'pid': 'A5047860864', 'event_id': 'A5046379417:2006', 'frozen_dose': 0.466393244601883, 'recomputed': 0.39663017304978226, 'abs_diff': 0.06976307155210071}, {'pid': 'A5050473533', 'event_id': 'A5018453582:2018', 'frozen_dose': 0.3012297424386393, 'recomputed': 0.3566681869039141, 'abs_diff': 0.055438444465274794}]
* evidence-gate conditions: {'population_measured': True, 'draw_predicted_FAIL': True, 'prediction_matches_run': True, 'every_failing_relation_is_a_frozen_population_residual': True, 'failure_is_gdose_only': True, 'G_ROW_zero_mismatches_and_G_SUM_ok': True, 'gate_was_intercepted_exactly_once': True}

Every kept network row is byte-identical to the frozen pre-y frame (build report `g_row_proof`); the gate decides only whether the clone writes its file. To withdraw: delete this directory.
