# Hidden completion blockers

Production workflow 8fc15e18c8e14894b06f2a875a439768 had two genuinely queued, never-started historical runs at sequence 42 and 85. project_status only returned the latest 30 steps, hiding these from the manager. Terminal interrupted/cancelled/failed rows were not the in-flight blocker.

Backed up production database to work/before-release-stale-queue.sqlite3; cancelled only the two historical queued runs via the normal deepseek_stop API. No execution marked successful and no completion gate bypassed. Manager notified through project-scoped queued message and resumed checking; subsequent observation showed a newly assigned deepseek-3 check and the manager actually running. These new tasks are real in-flight work and were preserved.

Source now returns completion_blocking_tasks independently of the 30-item history and lists concrete IDs, statuses, agents and dependency IDs in completion rejection errors. Tests: three blocker regressions and four manager-owned review checks passed. Executables staged and source/archive synchronized. Active backend not restarted while real verification work runs; enhanced diagnostics take effect on next restart. Immediate stale-queue repair already effective.
