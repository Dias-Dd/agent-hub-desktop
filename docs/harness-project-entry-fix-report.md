# Harness project task entry fix

Cause: the previous dynamic manager audit used self.hub in the module-level execute(runtime, run) function. Any Harness project task reaching the manager condition could fail before ACP startup. Ordinary dialogue tests did not exercise that branch.

Fix: use runtime.hub. Unexpected exceptions now retain redacted exception class/message and source location in execution_events (no raw traceback/source or credentials). Deterministic local errors stop automatic manager retries while retaining messages and provider conversations.

Tests: test_harness.py 29 passed, including real adapter execution flow with fake ACP for a nondefault project manager, and injected internal exception verifying diagnostics, redaction and no retry. test_manager_identity_audit.py 29 passed; test_manager_input.py 8 passed; test_manager_owned_review.py 4 passed; test_designs.py 13 passed. Global-self symbol scan passed for every hub Python module. No real model inference was made.

Current project was found in needs_attention with its session and mail preserved. No live database edits or automatic model restart were performed. Exit desktop from tray and reopen to activate corrected adapter; the existing needs_attention recovery schedule remains intact.
