# Independent Git worktrees and manager integration — 2026-10-22

## Workflow

Actual persisted projects use local Git worktrees for formal execution; static product demos and standalone connection tests retain their existing directories. The project root is the manager/integration directory. Each project/member pair owns a stable branch and worktree under the Hub data directory, with no remote upload. Existing work and conversation identities are retained.

A new worker launch prepares the worktree and records its directory in executions.cwd before starting the provider. Existing absolute task paths are mapped into that directory. The same launch wrapper covers Codex, Antigravity, DeepSeek API/Harness and linked CLI adapters. Their existing session-directory recovery remains responsible for resuming the conversation with the new authorized target directory. On restart, the original branch/worktree are reused rather than replaced.

Completed worker turns are saved as Git commits before their manager report is produced. Reports include the branch, commit, directory and baseline. Failed/interrupted work remains uncommitted and is reported honestly. Read-only inspections do not stage or commit their generated files. A per-Agent checkpoint barrier prevents a new turn from writing while its preceding report is saving changes; it does not require user approval or serialize other Agents.

## One MCP tool

- project_git(action="status"): current project branches and whether their tips are integrated.
- project_git(action="commit", message="..."): save the caller's files. Manager commits use the integration directory.
- project_git(action="integrate", agent="..."): manager merges that member's committed branch into the project root. A successful merge returns the integration commit; the manager runs appropriate integration verification.

Conflicts or local edits that prevent merging return a structured result and preserve all files. The manager can resolve and git add the files, then call commit, or use git merge --abort. No forced choice, hard reset, clean, force push or automated conflict overwrite is performed. The platform does not add a requirement that every branch be merged before the manager may submit completion; completion remains under the existing rule and manager judgment.

## Resource ordering

Formal projects no longer generate cross-Agent file-occupation dependencies: even same-file edits can proceed in parallel in separate worktrees. Queued legacy resource edges are removed during startup migration. Explicit task predecessors and per-Agent execution ordering remain. Static demo resource handling remains unchanged. Managers and workers receive a short Git workflow instruction instead of the old generic instruction to serialize same-file edits across isolated directories.

## Existing files

The first baseline records current source files without resetting or discarding the manager's working directory. Existing repositories are reused. New local caches, build outputs, credentials and private certificate files are excluded through repository-local info/exclude; already tracked files are not silently removed. Git identity and signing options are supplied per command, not written to the user's global configuration. Hub checkpoint commits do not introduce commit-hook gates.

## Verification

14 new real-Git tests passed: same-file parallel edits, automatic commits in the actual manager-report path, explicit HTTP integration, merge conflicts and manual resolution, dirty integration directory preservation, failed work preservation, no automatic readonly commits, excluded new credentials/build outputs, stable worktree reuse and fast-forwarding, restart recovery, separate projects, absolute-path mapping, demo behavior, manager authority, and the real provider worker launch wrapper.

Regression suites passed: coordination/resources 14, automation 22, manager input 8, Harness 29, integrations 22, ACP directory continuity 6, CodeBuddy directory/wait repair 6, force-stop/patrol 10, design lifecycle 13, project controls 14, connection tests 26. No actual model inference was used for these checks.

A pre-change source ZIP and executable were saved in outputs. No Git repository, worktree, commit or task changes were made to the running production project by this development session. Activate through a normal tray exit/reopen; subsequent formal worker launches use the new workflow. Existing failed/cancelled tasks are not replayed.
