Current execution engine: official DeepSeek Harness via ACP; see [Harness integration](deepseek-harness.md). The direct API loop remains available only as an explicit legacy/test engine.

# Nine DeepSeek agents — 2026-10-19

All nine execution routes use the official DeepSeek API model `deepseek-flash`. Every agent's current model name and system prompt identify it as DeepSeek. Agent IDs map as follows:

| Old ID | New ID | Role |
|---|---|---|
| flash-1 | deepseek-1 | Backend |
| flash-2 | deepseek-2 | Frontend |
| flash-3 | deepseek-3 | Testing |
| argon | deepseek-4 | Project manager |
| opus | deepseek-5 | Architecture/review |
| sol-1 | deepseek-6 | Implementation |
| sol-2 | deepseek-7 | Reliability |
| astra | deepseek-8 | Technical lead |
| deepseek | deepseek-9 | Supporting engineer |

There is no Hub monetary budget, provider call allowance, project call allowance or per-turn API-request count limit for DeepSeek. Remaining amounts/calls are null with an explicit unlimited flag, not a fabricated large balance. Usage tracking remains. Provider account funds, rate limits, model context/output capacity, project authorization, task timeouts, emergency stops and message-loop controls still apply. Plans require explicit user approval.

The default manager is deepseek-4. Each identity has independent, project-scoped API history. Existing platform messages/tasks/executions and provider sessions are preserved. Historical executions retain their original actual provider/model; provider-private conversation state is not represented as having been transferred to another model. Existing DeepSeek history for the renamed ninth identity can be adopted through legacy context-key lookup.

Both the 8765 workspace service and the 8766 desktop service were migrated with separate database/credential backups under their data directories. The migration has an audit record. There were no in-flight executions at migration. The old Codex/Antigravity execution routes are disabled. The obsolete per-call budget/approval endpoint is retired in favor of the unified runtime.

Validation: seven targeted tests passed, including a real Edge frontend check; they cover nine identities/routes and independent contexts, plan approval, manager-only dispatch, tools/stops, and 36 mock API requests in one turn. Official /models validation passed. One real no-tools API selftest by deepseek-1 completed and identified itself as DeepSeek Flash. No project implementation was started by these tests. Previous mixed-provider test fixtures are retained as legacy coverage and were not reported as passing under the new topology.

Launch: Open-Desktop.cmd in the outer project, or the current desktop/dist/AgentMessageHubDesktop.exe. The desktop uses its existing LocalAppData database on 8766. Start the original supervisor with Start-Hub.ps1 -NoSim for 8765. Do not import old seed databases over current data.
