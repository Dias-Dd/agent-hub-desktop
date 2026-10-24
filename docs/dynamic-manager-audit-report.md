# Dynamic project manager audit

## Cause
The installed profile deepseek-4 is disabled. Legacy defaults still selected it for new project settings and discussion initialization. Other hardcoded branches also affected routing, task attribution, manager inbox claiming, delegation, handoff and UI fallbacks.

## Changes
A shared manager resolver uses the explicit workflow/discussion manager or project setting. New projects inherit the latest enabled user-selected manager; seed identities do not define authority. Legacy records without a manager resolve their own project. No provider or identity is silently substituted for an explicitly selected manager.

Removed deepseek-4 runtime bindings from planning, project options/state, designs, workflow dispatch, result routing, provider system instructions, MCP manager tool selection, quota handoff and delegated emergency controls. All managers now use the same concise durable inbox claim logic; unselected mail stays pending, original long messages remain intact.

Manager changes normalize worker/reviewer lists in workflow, sessions and stored project options. Prepared manager tasks with no execution transfer to the new manager without replaying provider runs. Historical executed records and persistent provider conversations are preserved. Remaining seed ID references are initial identity/model catalog entries and legacy static placeholders, not special manager permissions or dispatch fallbacks.

## Verification
- test_manager_identity_audit.py: 29 passed, including new tests for removing the seed manager, custom-ID manager discussion, new project settings, worker result delivery, concise durable inbox, delegated stops, prepared-turn transfer archived project manager settings, and static prohibition of seed-ID runtime branches.
- test_dynamic_manager_participants_browser.py: passed; changed manager excluded, previous default identity selectable as worker.
- test_discussion_project_scope.py: 25 passed.
- test_dynamic_manager_delete.py: 24 passed.
- test_harness.py: 27 passed.
- test_manager_input.py: 8 passed.
- test_designs.py: 13 passed.
- test_manager_owned_review.py: 4 passed.
- test_manager_progress.py: 7 passed.
- test_project_controls.py: 14 passed.
- test_discussion_quota_workbuddy.py: 26 passed.
- test_quota_roster_menu.py: 16 passed.
- Required browser checks: manager layout (normal/short/narrow), reading preservation and nine-agent UI passed; project setup browser passed.
- Production database COPY, old manager disabled: new project, first discussion and reviewer all resolved to deepseek-1. Submission was mocked; no inference, live database modification or session reset.

Three older suites still use removed sol/flash/astra identities: test_planning (17 errors), test_workflows (9 errors), test_coordination (14 errors). Running the unmodified pre-change backup confirmed the same baseline failures. They are not represented as passing.

## Activation
Desktop executable and source archive updated. Exit from the system tray and reopen to load the backend. No automatic process shutdown or paid retest was performed.
