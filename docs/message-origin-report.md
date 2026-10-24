# Generated task message attribution

Platform-generated task envelopes can have legacy sender=user. These are dispatch inputs, not user-authored conversation. Frontend recognizes a task envelope only when its exact task ID exists in project task records (or server origin=platform_task). Generated envelopes are excluded from manager user conversation and shown in activity as platform dispatch. Unknown task-like user quotations remain ordinary messages.

Project snapshots annotate generated message origin without rewriting stored sender/auth/history. The active frontend has been updated and reloaded; server metadata applies after next application restart, while frontend project-task matching works immediately. Browser regression covers attribution, activity placement and unknown quoted IDs; manager layout at three sizes, reading-state and agent-panel regressions pass.
