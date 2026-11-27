"""Tests that run alone, after the parallel part of the suite (INFRA-CI-02).

They use threads that must really meet, sleep-ordered races, leases, expiry, fixed ports or
measured durations. Next to busy workers such a test could fail, or its race could stop racing
and pass without having tested anything. ``tests/conftest.py`` gives them the ``serial`` marker.
``tests/test_ci_parallel.py`` fails when a test reaches such a primitive and is not listed here,
and when an entry names a test that no longer exists.
"""

# Every test of these files, whatever it uses.
WHOLE_FILES = frozenset(
    {
        "tests/test_ratelimit.py",  # real windows of a real Redis server clock
    }
)

# Single tests: file -> test function names (all parameter sets).
TESTS: dict[str, frozenset[str]] = {
    file: frozenset(names.split())
    for file, names in {
        "tests/auth/context/test_workspace_pipeline.py": """
            test_parallel_switches_from_the_same_version_have_exactly_one_winner
        """,
        "tests/auth/mobile/test_mobile_flow.py": """
            test_parallel_openings_of_one_keycloak_session_give_one_session
        """,
        "tests/auth/security/test_email_change_db.py": """
            test_concurrent_requests_reserve_the_address_once
            test_concurrent_confirmation_consumes_token_once
            test_competing_recovery_workers_only_one_claims
        """,
        "tests/auth/security/test_email_change_recovery.py": """
            test_periodic_worker_starts_fail_closed_in_production
            test_real_smtp_sink_recovers_after_outage
            test_provisioning_race_cannot_change_idp_onto_an_existing_local_email
        """,
        "tests/auth/security/test_email_change_review.py": """
            test_two_decisions_at_once_are_serialised_and_only_one_acts
        """,
        "tests/auth/security/test_email_change_worker.py": """
            test_two_sweeps_at_once_apply_a_change_exactly_once
            test_nobody_takes_over_while_the_external_call_is_in_flight
            test_a_lease_that_ends_during_the_call_forbids_the_local_commit
            test_the_periodic_worker_recovers_on_its_own_and_after_a_restart
            test_a_cycle_that_cannot_run_reports_not_ready_and_the_worker_goes_on
            test_parallel_requests_of_one_person_leave_one_active_request
        """,
        "tests/auth/security/test_last_permanent_factor.py": """
            test_two_removals_at_once_cannot_both_take_a_permanent_factor
        """,
        "tests/auth/security/test_password_check.py": """
            test_checks_racing_each_other_give_one_record_and_one_notice
            test_the_worker_runs_the_check_and_either_task_survives_the_others_failure
            test_the_application_wires_the_check_into_its_worker
        """,
        "tests/auth/security/test_recovery_timing.py": """
            test_the_time_to_answer_does_not_depend_on_the_account
        """,
        "tests/auth/security/test_security_units.py": """
            test_smtp_notifier_delivers_to_a_dev_mail_sink_and_survives_a_dead_one
        """,
        "tests/auth/sessions/test_sessions_db.py": """
            test_touch_skips_a_row_that_is_locked_instead_of_waiting
            test_a_sign_in_cannot_slip_past_a_concurrent_deactivation
            test_revocation_waits_for_a_request_in_flight_and_every_later_request_sees_it
            test_parallel_sign_ins_never_exceed_the_cap
        """,
        "tests/auth/users/test_users_db.py": """
            test_parallel_first_logins_of_one_subject_create_exactly_one_user
            test_a_sign_in_waits_for_a_concurrent_deactivation_and_then_sees_it
        """,
        "tests/auth/web/test_web_flow.py": """
            test_parallel_callbacks_with_one_state_succeed_once
        """,
        "tests/platform/test_platform_grants_api.py": """
            test_two_approvals_at_once_have_exactly_one_winner
            test_parallel_requests_create_one_grant
        """,
        "tests/platform/test_platform_grants_db.py": """
            test_two_administrators_revoking_each_other_at_once_leave_one
            test_a_revocation_waits_for_the_transaction_that_uses_the_grant
            test_a_grant_works_until_its_expiry_and_not_a_moment_after
        """,
        "tests/test_health.py": """
            test_liveness_touches_no_dependency_and_reveals_nothing
        """,
        "tests/test_idempotency.py": """
            test_concurrent_in_flight_request_gets_409_then_replay_after_commit
            test_many_concurrent_identical_requests_execute_exactly_once
        """,
        "tests/test_versioning_db.py": """
            test_concurrent_updates_have_exactly_one_winner
        """,
    }.items()
}


# A worker normally takes a whole file. The tests of these files are handed out one by one,
# because as whole files they decide how long the parallel part takes. Each of their tests builds
# its own database and application; the one wider fixture (the mutation sandbox) is rewritten by
# every test before use and exists once per worker.
SPLIT_FILES = frozenset(
    {
        "tests/auth/context/test_workspace_pipeline.py",
        "tests/auth/mobile/test_mobile_flow.py",
        "tests/auth/security/test_account_step_up.py",
        "tests/auth/security/test_email_change_hardening.py",
        "tests/auth/test_token_mutations.py",
        "tests/auth/web/test_web_flow.py",
        "tests/platform/test_platform_grants_api.py",
    }
)


def is_serial(file: str, test: str) -> bool:
    """``file`` is relative to the repository root, ``test`` the function name."""
    return file in WHOLE_FILES or test in TESTS.get(file, frozenset())
