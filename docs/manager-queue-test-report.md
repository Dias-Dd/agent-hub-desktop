# Manager queue control verification

- Added manager-only project_queue: list complete active/pending item contents; edit pending task/message; reorder selected items ahead of omitted items; delete/cancel while retaining audit/history; interrupt with new content.
- Runtime arguments injected into MCP project_queue calls; tool registered in HTTP dispatch, MCP discovery, model tool allowlists and exported frontend contract. Ordinary members cannot access the manager operation.
- Manager immediate sends force-stop the old local turn using existing revocation fences, then route new content at immediate priority. Sender/recipient/project boundaries and idempotency retained. Whole send/preemption/route serialized with runtime startup under the hub lock. Old work is not success, normal queue remains, emergency stop latches remain.
- Persist queue ranks separately from workflow history sequence and creation timestamps. Prepared dispatch, common real runtime selection, durable raw message route and Hub.poll all honour ordering. Remove only implicit ordering between the reordered member's pending tasks; keep outside prerequisites and single-active-turn behaviour. Restart migration does not recreate removed queue ordering.
- Pending edits synchronize task title, source message and already-queued prompt/actual_input. Active/history inputs not rewritten. Declared file scope/session/workdir stay intact. Deletion releases queue dependencies and does not erase rows. Audit stores before/after.

Tests: manager_queue 10 passed (actual runtime selection and prepared dispatch, persisted ordering across reinitialization, pending edit vs active input, force interruption/revocation plus new content dispatch, nonmanager/foreign member denial, raw message edit/delete/order/poll, tool exposure); manager_force_stop_patrol 12; quota_roster_menu 16; automation 26; coordination_repairs 14; manager_input 8; manager_patrol_config 24; dynamic_manager_delete 26; required_folder_link 7 passed. Fake providers only; no real model inference or live project changes.

Legacy test_codex_runtime has 6 fixture errors both before and after this change (old sol/astra IDs no longer bound to current executors); baseline reproduced from before-manager-queue app archive in an isolated temp folder. It is not reported as a passing suite. Current runtime ordering and native Codex late-result fencing are covered by the manager queue/control fixtures above.

Whole source/application backup: ../agent-message-hub-before-manager-queue-app.zip. Published immutable executable, running Hub not restarted.

Packaged smoke passed: 16 assets, native desktop available, VM helper packaged.
