# Manager reply deduplication and model-level quota visibility

Observed (read-only live audit): latest discussion history contains manager reply run 23513c5caa994a4faa45aa804b654255, and an additional user-delivered execution receipt with request_key execution:23513c5caa994a4faa45aa804b654255:user. Both were rendered in the manager timeline. MiniMax opencode/minimax-m3.1-flash-free already had an explicit persisted Free usage limit reached block, no known reset time. The discussion snapshot omitted this block and considered the member ready; account overview lacked a readable percentage and monitoring skipped the model rejection.

Fixes:
- Deduplicate generated manager receipts by run identity only when the currently displayed discussion history already contains the same reply. Never delete message records or deduplicate arbitrary equal text. Independent manual manager messages and legitimate repeated user messages remain.
- Include quota_exhausted/rejection/reset information in discussion team and blocked_agents, plus quota_exhausted in runtime capabilities. Known exhausted models are ready=false. Refresh queued discussion snapshots at provider execution time using the same allowed roster and save the actual refreshed snapshot for audit.
- Recognize explicit Free usage limit reached variants; transient HTTP429/rate limits remain separate.
- Monitor persisted model-rejection state even without numeric quota APIs. No invented percentage. Deduplicate unchanged alerts; clear/positive authoritative state allows recovery and another exhaustion alert. State IDs include agent/connection/model, avoiding false recovery when a binding changes. Use existing urgent manager notification/preemption and paused/finished-project behaviour.
- Outgoing copies of platform quota notices are attributed to 平台, not manager.

Tests: model_quota_visibility 4; quota_cancellation 8; discussion_quota_workbuddy 26; quota_roster_menu 16; integrations 22; vm_bridge 16 passed. Actual discussion browser fixture includes the duplicate execution receipt and an independent manager message; same-run receipt is hidden and independent message retained. Manager layout/reading/nine browser checks passed. No real model inference, live DB edits, Hub restart, or project advancement.

Backup: ../agent-message-hub-before-reply-quota-fix-app.zip. Source ZIP refreshed with immutable runtime; current app stays unchanged until reopened.

Packaged startup smoke passed (16 assets, native desktop and VM helper available). Frontend action signatures regenerated (89 actions).
