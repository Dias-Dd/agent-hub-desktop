# Demo edges and manager control update

- Reproduced centred flex fixed-width pages cropped on the left: original preview failed at 1440x900, 1024x600, 600x800; updated bounds measurement passed all three. Manual zoom/pan, selections, feedback and reload remain tested. Fit mode does not restore old pan offsets.
- Demo completion publishes the review without a folder link; production still requires one. DesignFlow now exercises publication with no folder artifact.
- project_complete is a two-call manager confirmation. First call changes no project completion/queue state and returns test questions; second carries comprehensive_tests and vm_ui_tests statements, including disclosed untested scope. No automatic execution, truth evaluation, or requirement that every test passed. Existing busy-member check retained; final confirmation saved in completion record.
- Default periodic manager patrol 600 seconds; persistent global settings in configuration centre. Old workflow-specific idle toggle retained. Message wakes and explicit timers independent. Existing settings migrate on startup, without waking/stopping agents.
- Removed hardcoded unlimited DeepSeek resources label; manager policy chooses task-fit/availability/quota, allows reasonable wait, asks progress before force stop. VM administrator channel and ability to install guest SDK/dependencies explicitly documented, with actual elevated state authoritative.
- Member/platform input summaries carry UTC+8 timestamps. Single user input remains verbatim; project_mailbox already exposes exact creation time.
- Immediate-message insertion serialized with dispatch; prioritized prepared messages, no ordinary resource dependency for immediate control; idempotent retries cannot repeatedly preempt later turns. Startup migration preserves this behaviour. Current turn must still finish stopping before another starts.

## Verification
Local fake-provider/backend suites: required_folder_link 7, designs 13, manager_patrol_config 24 (includes registry baseline), manager_force_stop_patrol 12, quota_roster_menu 16, automation 26, manager_input 8, codebuddy_wait_resources 7, coordination_repairs 14. Browser: design review+reload (2 tests, three sizes), manager layout, reading, nine-agent, patrol UI (including persistent global save). No real inference or live project mutations.

Baseline source/application archive: ../agent-message-hub-before-demo-edges-app.zip. Build released immutably; no replacement of a running executable and no automatic Hub restart.

Packaged checks: basic smoke ok (16 assets); actual native WebView2 window smoke ok, Mica=true, transparent WebView=true, caption right gap=0, native max hit=9/close hit=20, round preference=2. No live service restart.
