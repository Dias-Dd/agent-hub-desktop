# Manager-reported overall progress

Manager project(progress,note) calls now bind to the active execution and workflow rather than global settings and the fixed deepseek-4 identity. Only the current manager plan/review task may report. Reports persist percentage, basis, author and timestamp per workflow. Added the tool to the DeepSeek/Harness and linked-runtime manager allowlist, preserving exclusion for ordinary members; API and MCP route to the same method.

Removed automatic percentage increments based on manager scheduling sequence. Project snapshot and right-hand progress read manager_progress; no report means an explicit awaiting-manager-report label, rather than a fabricated estimate. Validated project completion still displays 100%. Prompt instructions request initial and material milestone updates based on scope/acceptance, without additional timer/model calls. Manager may revise an estimate downward after new findings. Hovering the note shows author/time.

Validation: seven manager progress/review tests include persistence, project isolation, revised estimates and dynamic manager/member tool access; 27 Harness tests, three-size manager layout, reading state and agent panel checks pass. Executables and source archive updated. Activation may require service restart; do not infer activation merely from replacing files while an older process runs.

Activation verified: after the existing round ended and no queued/running work remained, gracefully restarted the idle desktop service, verified authenticated health and source=completed for the finished project, restored the native window. No model round interrupted. Only still-active workflows receive an enablement control; completed projects are not woken.
