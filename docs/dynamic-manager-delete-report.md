# Dynamic manager deletion checks

Removed the hard-coded deepseek-4 deletion ban in both backend and UI. Any identity is protected while actually managing an unfinished project; snapshot manager_projects lists exact project names/statuses and the delete tooltip/rejection explain those bindings. Current selected manager takes precedence over historical completed workflows in frontend identity normalization. Ordinary idle worker archival removes it from project rosters and retains the existing change notification flow; changing its connection while participating remains protected.

Live inspection: current project a7b98970696845ba99a6eb98f1a7f4c3 explicitly selects deepseek-1. Another blocked workflow in project 2481457293934dd183a2aa78f8776465 (name: 新项目) still uses deepseek-4. No identity was deleted, no manager was silently reassigned, and no blocked project was stopped.

Validation: 23 registry/dynamic-delete tests, real Edge deletion-control test after selecting deepseek-1, three-size manager layout, reading persistence and agent panel checks passed. Activated new backend by graceful idle restart after confirming no active/queued runs; authenticated health and returned manager bindings verified. Source, executable copies and archive updated.
