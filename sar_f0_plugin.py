# -*- coding: utf-8 -*-
"""Test safety for every pytest run in this repository (tests/ and pipeline/units). See tests/f0_guard.py.
Loaded by `-p sar_f0_plugin` in pytest.ini addopts (pytest runs as `python -m pytest` from the repo root).

1. Host gate: the private repository runs its tests only on its AWS test hosts. This public copy has no
   host gate: the default selection in pytest.ini runs on any machine and leaves out the tests marked
   ssd (they read the OpenAlex extraction), estimate (an R estimate), legacy (the author's private
   trees) and live (a live web API).
2. Disk guard: unless $SAR_HOST is ec2-r1 (the data host) or $SAR_DISK_TESTS is 1, an audit hook refuses
   Python-level opens, listings and writes under the ssd_root that config/paths.yaml names, so a default
   run never touches the extraction. To run the `ssd` tests: point $SAR_SSD_ROOT at the extraction, set
   SAR_DISK_TESTS=1 and select them with `-m ssd`.
3. Paths default: $SAR_PATHS_CONFIG is set to config/paths_october.yaml when it is unset or blank, so the
   tests read the October 2026 version whatever config/paths.yaml selects. A value already set is kept.
Lives at the repo root, not under pipeline/: the ported code carries no auto-executed file of ours. Not a
conftest.py: several tests/ modules put the repo root first on sys.path, and a root conftest.py would
then answer the ported u6 tests' bare `from conftest import make_inputs`.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import sys

import pytest

# Restricted inputs below are not shipped; AWS-only tools keep their host guard.
PUBLIC_REQUIREMENTS = {
    'tests/test_r1_calls_lib.py::test_the_committed_dose_keep_file_is_well_formed': ['data/cal2026-10r1/inputs/dose_keep_r1.csv'],  # Restricted inputs, not shipped.
    'tests/test_r1_check_paper_tree.py::test_math_p2_date_shift_artifact_check_is_october_only': ['tests/fixtures/r1_paper/base_tree_2026-10-11'],  # Restricted inputs, not shipped.
    'tests/test_r1_check_paper_tree.py::test_math_p2_date_shift_m_check_fails_when_ledger_and_artifact_disagree': ['tests/fixtures/r1_paper/base_tree_2026-10-11'],  # Restricted inputs, not shipped.
    'tests/test_r1_check_paper_tree.py::test_rob_tables_m_ledger_with_departure_rows_printed_fails': ['tests/fixtures/r1_paper/base_tree_2026-10-11'],  # Restricted inputs, not shipped.
    'tests/test_r1_check_paper_tree.py::test_rob_tables_m_ledger_without_departure_cells': ['tests/fixtures/r1_paper/base_tree_2026-10-11'],  # Restricted inputs, not shipped.
    'tests/test_r1_check_paper_tree.py::test_table_cell_checks_name_their_tree_path_and_gate2_explains_them': ['tests/fixtures/r1_paper/base_tree_2026-10-11'],  # Restricted inputs, not shipped.
    'tests/test_r1_chemmath_m.py::test_an_in_process_prodlib_exit_is_a_stop_with_its_code': ['data/cal2026-10r1/inputs/p2_decisions.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_chemmath_m.py::test_edge_proof_reports_the_october_comparison_and_freezes_the_products': ['data/cal2026-10r1/inputs/p2_decisions.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_chemmath_m.py::test_mode_b0_sets_no_switch': ['data/cal2026-10r1/inputs/p2_decisions.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_chemmath_m.py::test_preconditions_stop_on_unpinned_input_missing_exclusion_or_unsigned_switch': ['data/cal2026-10r1/inputs/p2_decisions.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_classify.py::test_committed_base_inputs_tsv_is_current': ['data/cal2026-10r1/inputs/add_list_r1.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_config.py::test_a_ruling_that_contradicts_the_signed_file_stops': ['data/cal2026-10r1/inputs/p2_decisions.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_config.py::test_an_unsigned_or_missing_ruling_stops': ['data/cal2026-10r1/inputs/p2_decisions.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_config.py::test_b0_loads_with_every_switch_off_and_every_ruling_signed': ['data/cal2026-10r1/inputs/p2_decisions.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_config.py::test_b0_stage_section_matches_octobers_restake_source': ['data/cal2026-10r1/inputs/p2_decisions.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_config.py::test_config_check_cli_refuses_off_host_and_writes_resolved': ['data/cal2026-10r1/inputs/p2_decisions.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_config.py::test_counts_b0_matches_the_october_tables': ['data/cal2026-10r1/inputs/flips_r1.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_config.py::test_h8_h9_are_the_signed_flips': ['data/cal2026-10r1/inputs/flips_r1.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_config.py::test_m_refuses_an_add_list_that_is_not_ok': ['data/cal2026-10r1/inputs/add_list_r1_summary.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_config.py::test_m_refuses_an_undecided_verdict_row': ['data/cal2026-10r1/inputs/p2_decisions.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_config.py::test_paths_resolve_repo_and_work_tokens_and_refuse_absolute': ['data/cal2026-10r1/inputs/p2_decisions.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_config.py::test_unknown_missing_or_b0_on_switch_stops': ['data/cal2026-10r1/inputs/p2_decisions.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_config_m.py::test_m_config_loads_with_an_ok_add_list_and_every_registered_switch_is_on': ['data/cal2026-10r1/inputs/add_list_r1_summary.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_config_m.py::test_m_expect_counts_equal_the_signed_lists': ['data/cal2026-10r1/inputs/flips_r1.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_config_m.py::test_m_loads_or_stops_only_at_the_add_list_gate': ['data/cal2026-10r1/inputs/add_list_r1_summary.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_config_m.py::test_m_pins_every_roster_variant_chemmath_m_reads': ['data/cal2026-10r1/inputs/rosters/roster_gold_chemistry_r1.parquet'],  # Restricted inputs, not shipped.
    'tests/test_r1_config_m.py::test_m_pins_the_merged_rosters_once_committed': ['data/cal2026-10r1/inputs/rosters/roster_econ_verified_r1.parquet'],  # Restricted inputs, not shipped.
    'tests/test_r1_config_m.py::test_m_redates_map_covers_every_signed_econ_redate': ['data/cal2026-10r1/inputs/fixes_1001.csv'],  # Restricted inputs, not shipped.
    'tests/test_r1_config_m.py::test_m_verdict_source_pins_the_signed_lists': ['data/cal2026-10r1/inputs/p2_decisions.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_dossier_pack.py::test_the_committed_target_list_holds_ids_and_codes_only': ['data/cal2026-10r1/inputs/j0_dossier_targets.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_econ920_m.py::test_cli_refuses_off_host_and_a_b0_config': ['data/cal2026-10r1/inputs/p2_decisions.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_events.py::test_dropped_events_are_exactly_the_drop_stars': ['data/cal2026-10r1/inputs/flips_r1.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_events.py::test_every_event_star_has_a_signed_verdict': ['data/cal2026-10r1/inputs/flips_r1.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_events.py::test_fixes_asserts': ['data/cal2026-10r1/inputs/flips_r1.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_events.py::test_m_counts_on_the_signed_lists': ['data/cal2026-10r1/inputs/flips_r1.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_events.py::test_m_refuses_an_addlist_summary_that_is_not_ok': ['data/cal2026-10r1/inputs/add_list_r1_summary.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_events.py::test_new_rows_end_like_their_table': ['data/cal2026-10r1/inputs/flips_r1.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_events.py::test_new_rows_shape': ['data/cal2026-10r1/inputs/flips_r1.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_events.py::test_p05_follows_the_source': ['data/cal2026-10r1/inputs/flips_r1.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_events.py::test_redate_rewrites_only_event_id_and_arrival': ['data/cal2026-10r1/inputs/flips_r1.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_events.py::test_s14_keeps_2000_when_verified': ['data/cal2026-10r1/inputs/person_overrides.csv'],  # Restricted inputs, not shipped.
    'tests/test_r1_events.py::test_s14_out_of_window_stops': ['data/cal2026-10r1/inputs/person_overrides.csv'],  # Restricted inputs, not shipped.
    'tests/test_r1_events.py::test_s14_redate_row_changes_only_that_event': ['data/cal2026-10r1/inputs/person_overrides.csv'],  # Restricted inputs, not shipped.
    'tests/test_r1_explicit_paths.py::test_b0_stage_section_reproduces_octobers_restake_source': ['data/cal2026-10r1/inputs/p2_decisions.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_fig4.py::test_cli_writes_counts_and_fails_on_a_switcher_mismatch': ['@aws'],  # AWS-only host guard.
    'tests/test_r1_final.py::test_canon_layout_covers_every_canon_read_and_carries_october_files': ['data/cal2026-10r1/inputs/rosters/roster_econ_verified_r1.parquet'],  # Restricted inputs, not shipped.
    'tests/test_r1_final.py::test_figure_caption_names_the_rows_sentence_of_the_base_tree': ['tests/fixtures/r1_paper/base_tree_2026-10-11'],  # Restricted inputs, not shipped.
    'tests/test_r1_final.py::test_final_and_finalb0_tables_load_and_name_existing_scripts': ['tools/r1_pack_tree.py'],  # Restricted inputs, not shipped.
    'tests/test_r1_final.py::test_gate2_stage_reads_label_conflicts_as_repin_writes_them': ['tools/repin_thesis_2026-10/repin.py'],  # Restricted inputs, not shipped.
    'tests/test_r1_final.py::test_gate2_stage_reads_the_figure_ledger_and_never_rewrites_the_caption': ['tests/fixtures/r1_paper/base_tree_2026-10-11'],  # Restricted inputs, not shipped.
    'tests/test_r1_final.py::test_printed_keys_on_the_scratch_tree_include_the_base_tree_claims': ['tests/fixtures/r1_paper/base_tree_2026-10-11'],  # Restricted inputs, not shipped.
    'tests/test_r1_final_b0_expected.py::test_reference_only_pins_equal_the_archived_copies': ['data/cal2026-10/paper_layer/MANIFEST.sha256'],  # Restricted inputs, not shipped.
    'tests/test_r1_gaps_zenou_m.py::test_a_canon_without_a_run_config_in_its_counts_is_refused': ['data/cal2026-10r1/inputs/flips_r1.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_gaps_zenou_m.py::test_b0_canon_checks_identity_but_not_the_signed_rank': ['data/cal2026-10r1/inputs/flips_r1.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_gaps_zenou_m.py::test_lost_event_fails': ['data/cal2026-10r1/inputs/flips_r1.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_gaps_zenou_m.py::test_m_mode_reports_diffs_not_mismatches': ['data/cal2026-10r1/inputs/flips_r1.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_gaps_zenou_m.py::test_missing_pairs_is_fatal_in_m': ['data/cal2026-10r1/inputs/flips_r1.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_gaps_zenou_m.py::test_moved_year_fails': ['data/cal2026-10r1/inputs/flips_r1.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_gaps_zenou_m.py::test_not_a_star_fails': ['data/cal2026-10r1/inputs/flips_r1.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_gaps_zenou_m.py::test_not_monash_fails': ['data/cal2026-10r1/inputs/flips_r1.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_gaps_zenou_m.py::test_percentile_must_match_the_signed_rank': ['data/cal2026-10r1/inputs/flips_r1.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_gates.py::test_gate1_refuses_config_m': ['data/cal2026-10r1/inputs/p2_decisions.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_number_diff.py::test_old_side_layout_matches_the_f1_upload': ['data/cal2026-10r1/aws/uploads/v3up_2026-10-13.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_rank_stage.py::test_named_asserts_are_the_rk6b06_values': ['data/cal2026-10r1/inputs/flips_r1.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_rank_stage.py::test_the_rk6b_reference_is_named_alike_everywhere': ['data/cal2026-10r1/aws/runs/rk6b-06/launch_record.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_recover.py::test_a_control_failure_fails_the_recovery': ['@aws'],  # AWS-only host guard.
    'tests/test_r1_recover.py::test_a_kit_copy_that_differs_from_the_history_fails': ['@aws'],  # AWS-only host guard.
    'tests/test_r1_recover.py::test_a_prep_rk1_that_does_not_reproduce_the_payload_fails': ['@aws'],  # AWS-only host guard.
    'tests/test_r1_recover.py::test_full_recovery_passes_and_uploads_a_manifest': ['@aws'],  # AWS-only host guard.
    'tests/test_r1_recover.py::test_launch_side_files_are_rebuilt_and_prep_rk1_reproduces_its_inputs': ['@aws'],  # AWS-only host guard.
    'tests/test_r1_recover.py::test_refuses_a_destination_outside_r1_and_refuses_off_aws': ['@aws'],  # AWS-only host guard.
    'tests/test_r1_recover.py::test_the_summary_carries_codes_not_fail_texts': ['@aws'],  # AWS-only host guard.
    'tests/test_r1_restake_r1.py::test_signed_counts_are_173_97_107': ['data/cal2026-10r1/inputs/flips_r1.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_rk6_requests.py::test_build_ranks_every_g0_person_and_every_open_candidate': ['@aws'],  # AWS-only host guard.
    'tests/test_r1_rk6_requests.py::test_build_refuses_a_failed_recovery_or_a_changed_rk1': ['@aws'],  # AWS-only host guard.
    'tests/test_r1_rk6_requests.py::test_build_refuses_an_rk6a_run_that_did_not_pass': ['@aws'],  # AWS-only host guard.
    'tests/test_r1_rk6_requests.py::test_build_refuses_s3_copies_that_differ_from_the_git_pins': ['@aws'],  # AWS-only host guard.
    'tests/test_r1_rk6_requests.py::test_summarize_counts_and_writes_the_review_pack': ['@aws'],  # AWS-only host guard.
    'tests/test_r1_rk6_requests.py::test_summarize_fails_when_the_control_failed': ['@aws'],  # AWS-only host guard.
    'tests/test_r1_rk6_requests.py::test_summarize_recounts_the_control_and_fails_on_a_missing_row': ['@aws'],  # AWS-only host guard.
    'tests/test_r1_run_config.py::test_missing_config_key_or_unknown_step_stops': ['data/cal2026-10r1/inputs/p2_decisions.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_run_config.py::test_plan_renders_every_b0_step_with_no_placeholder_left': ['data/cal2026-10r1/inputs/p2_decisions.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_run_config.py::test_plan_runs_nothing': ['data/cal2026-10r1/inputs/p2_decisions.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_run_config.py::test_step_renders_argv_runs_and_writes_step_report': ['data/cal2026-10r1/inputs/p2_decisions.json'],  # Restricted inputs, not shipped.
    'tests/test_r1_table_j0.py::test_b0_chain_paths_cover_every_repo_input_of_the_chain_rows': ['data/departure_verification_2026-09-10'],  # Restricted inputs, not shipped.
    'tests/test_r1_table_j0.py::test_fingerprint_inputs_are_precise': ['data/cal2026-10r1/aws/uploads/symlinks_legacy_v2_output.tsv'],  # Restricted inputs, not shipped.
    'tests/test_r1_table_j1a.py::test_every_script_exists_and_every_repo_input_is_tracked_or_a_required_late_input': ['data/cal2026-10r1/aws/uploads/symlinks_legacy_v2_output.tsv'],  # Restricted inputs, not shipped.
    'tests/test_r1_test_runner.py::test_a_missing_module_is_a_red_fail_and_a_syntax_error_is_not': ['@aws'],  # AWS-only host guard.
    'tests/test_r1_test_runner.py::test_a_missing_test_file_is_not_a_red_fail': ['@aws'],  # AWS-only host guard.
    'tests/test_r1_test_runner.py::test_an_overlay_is_laid_into_the_checkout_after_every_git_clean': ['@aws'],  # AWS-only host guard.
    'tests/test_r1_test_runner.py::test_an_unmet_expectation_makes_the_run_a_mismatch': ['@aws'],  # AWS-only host guard.
    'tests/test_r1_test_runner.py::test_no_tests_collected_is_never_a_pass': ['@aws'],  # AWS-only host guard.
    'tests/test_r1_test_runner.py::test_noregress_accepts_old_failures_and_rejects_new_ones': ['@aws'],  # AWS-only host guard.
    'tests/test_r1_test_runner.py::test_noregress_fails_when_a_test_that_passed_in_the_baseline_is_skipped_now': ['@aws'],  # AWS-only host guard.
    'tests/test_r1_test_runner.py::test_noregress_needs_at_least_the_baseline_test_count': ['@aws'],  # AWS-only host guard.
    'tests/test_r1_test_runner.py::test_red_fails_green_passes_and_the_run_is_ok': ['@aws'],  # AWS-only host guard.
    'tests/test_r1_test_runner.py::test_the_checkout_is_restored_after_the_run': ['@aws'],  # AWS-only host guard.
}


def public_requirement_reason(nodeid, exists, env, requirements=PUBLIC_REQUIREMENTS):
    """Exact test prerequisites; missing restricted inputs and AWS host gates only."""
    for requirement in requirements.get(nodeid.split("[", 1)[0], ()):
        if requirement == "@aws":
            if str(env.get("SAR_HOST", "")).strip() not in ("ec2-r1-test", "ec2-r1"):
                return "AWS-only tool: requires SAR_HOST=ec2-r1-test or ec2-r1"
        elif not exists(requirement):
            return "requires " + requirement + " (restricted input, not shipped)"
    return None

#: the paths config the tests read unless the environment names one (item 3 above)
OCTOBER_PATHS = pathlib.Path(__file__).resolve().parent / "config" / "paths_october.yaml"
if not os.environ.get("SAR_PATHS_CONFIG", "").strip():
    os.environ["SAR_PATHS_CONFIG"] = str(OCTOBER_PATHS)

_spec = importlib.util.spec_from_file_location("sar_f0_guard", pathlib.Path(__file__).resolve().parent / "tests" / "f0_guard.py")
_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_guard)

if os.environ.get("SAR_HOST", "").strip() != _guard.DATA_HOST and os.environ.get("SAR_DISK_TESTS", "") != "1":
    _root = _guard.configured_ssd_root()
    if _root:
        sys.addaudithook(_guard.make_guard((_root,)))


def pytest_configure(config):
    """Public copy: no host gate (the private repository stops here unless $SAR_HOST names one of its
    AWS test hosts). The default marker selection in pytest.ini keeps the run self-contained."""
    return None


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    """R1 F0 (P3b): add the markers tests/f0_guard.py F0_MARKS assigns. tryfirst: pytest's own `-m`
    deselection (_pytest/mark, a plain hookimpl) must see them."""
    for item in items:
        marker = _guard.marker_for(item.nodeid)
        if marker:
            item.add_marker(getattr(pytest.mark, marker))
        reason = public_requirement_reason(
            item.nodeid, lambda rel: (OCTOBER_PATHS.parent.parent / rel).exists(), os.environ)
        if reason:
            item.add_marker(pytest.mark.skip(reason=reason))
