# Hyper-V Hub bridge (initial command/file phase)

Host: Hub and model harnesses keep existing logins. Guest: development dependencies, builds and product processes only. No model credentials are copied to Windows guest.

In an administrator PowerShell window with the already-tested $hubCredential, run tools/Start-HubVmBridge.ps1 -VmName Hub -Credential $hubCredential. Leave this window open. The script opens PowerShell Direct, probes Windows/account and verifies file transfer both directions with SHA256. It holds credentials only in memory; Ctrl+C closes its session. No ports, saved passwords, autostart or Windows changes are installed.

The local vm-bridge directory is ACL-restricted to the launching Windows account and SYSTEM. Start the bridge as the same Windows account as Hub, elevated. A single bridge processes operations sequentially; compilation does not block Hub HTTP. Queue state survives service restart; restarting the bridge marks abandoned requests not_replayed/unknown rather than repeating shell operations.

After reopening the updated Hub, authorized project executions have project_vm:
- status: check connection.
- exec with script and timeout_seconds: runs PowerShell inside C:\HubWorkspace\<project>\<agent>. Save request_id.
- status with request_id: read queued/running/completed/failed; completed is process completion, inspect exit_code/output for success.
- push/pull with path relative to current member worktree: transfer files/directories with matching guest paths. Existing directory destinations are rejected to avoid accidental directory nesting. Pull results to member worktree, then normal project_git commit/integrate applies.

Commands can modify the guest as the supplied Windows account permits. They are not a security sandbox within the guest. Read-only review runs cannot start VM operations. Timeout stops the remoting job but child process termination is not guaranteed; inspect guest before resubmitting. Closing bridge may leave an operation indeterminate; do not claim it succeeded.

Desktop screenshots and Hyper-V keyboard/mouse are NOT implemented or advertised in this phase. This code does not install GUI agents, guest dependencies, or change execution cwd of existing harnesses. Use exec explicitly for guest commands; host harness shell commands still execute on host.

Validation: 4 queue/path/ownership tests and 23 automation tests passed; script parsed by Windows PowerShell parser. Physical VM end-to-end requires user to launch the elevated bridge; not claimed tested. Old test_coordination fixture independently fails because it references removed sol/flash identities; this change does not fix that fixture.


## Configuration panel (2026-10-22)
Open Settings > Virtual machine environment > Read VM list. UAC starts a hidden elevated helper; the Hub remains unelevated. Select an existing VM, enter guest Windows username/password, connect and test. Connection runs a real command and a SHA256-verified round-trip transfer. Disconnect does not shut down the VM. Helper exits with its owning Hub process; credentials are not persisted across application exits. Existing manual version-1 workers must be closed before starting the panel helper.

Password fields are cleared immediately on submission and when closing settings. Python encrypts a one-shot handoff via Windows DPAPI CurrentUser; PowerShell decrypts it under the same elevated Windows user and removes ciphertext after consumption. No password enters project metadata, audit, model prompts, browser storage or CLI arguments. Synthetic-credential Python-to-PowerShell DPAPI compatibility was verified. UAC under a different Windows account cannot decrypt this handoff and reports connection failure.

GUI regression uses mocked Hyper-V: dropdown, connect/disconnect, password clearing. Real bridge/physical VM access still requires the user's UAC and guest credentials; not represented as tested. Three mandatory layout/reading tests pass. Desktop UIA and virtual input remain explicitly unavailable; they must be installed and tested before agents can use them. Multiple virtual input devices do not create independent focuses.


## Saved credentials and desktop deployment (2026-10-22)
This section supersedes the earlier command/file-only and nonpersistent-credential notes. Settings can encrypt and save guest credentials under vm-bridge/saved-connections using Windows DPAPI CurrentUser; only encrypted blobs are persisted, not model credentials. A saved connection can be reused after restart with one button, and deleted without disconnecting its existing session. The first connection in the new version needs password entry once; credentials from an older in-memory worker cannot be retroactively saved by this app. Saving occurs only after successful authentication and transfer verification. Windows UAC may still be needed to start the host helper.

On connection the host deploys HubDesktopAgent.ps1 as an interactive scheduled task AgentHubDesktop in the guest, triggered at that user's logon. It requires a logged-in desktop, not a model account. Desktop deployment failure is a warning: PowerShell/file operations remain available. The service uses Windows UI Automation patterns with HWND-targeted messages for legacy Edit/Button controls; no additional LLM or UFO orchestrator is installed. It does not expose an unauthenticated network port.

project_vm desktop actions: windows, ui_tree(window_handle), ui_set_value(window_handle,element_id,value), ui_invoke(window_handle,element_id), screenshot, desktop_status, desktop_release. Mutations acquire a shared 120-second desktop lease; another member must wait or ask for release. Reads do not steal the cursor. Screenshots travel as MCP images and are copied to .hub-evidence in the member worktree for publish_artifact. Text-only API transports strip base64 instead of feeding it as model text. Completion of a tool is evidence of an operation, not evidence that the application meets all requirements.

Fallback key(key_codes) and mouse(x,y,button) use Hyper-V Msvm_Keyboard and Msvm_SyntheticMouse, not host SendInput. Coordinates are guest screen pixels; button 0 moves, 1/2 click left/right. A console-session check avoids sending virtual input to a different desktop than UI Automation. These commands require the version-3 elevated helper loaded by reopening Hub/reconnecting. Not every VK code is supported: F24 returned 32773; standard Shift press/release and mouse movement returned 0 in actual VM tests.

Actual VM Hub validation: installed the interactive worker, obtained 1024x768 screenshot and visually inspected it; enumerated windows/controls; set text in a dedicated WinForms test window, invoked its button and independently read the resulting file; closed and removed the test task/window afterward. The WinForms controls did not expose Invoke/Value patterns in this environment, so targeted Win32 control messages were tested as the fallback within the control channel. Hyper-V device tests required UAC and passed for standard Shift and mouse move. No inference calls. A disconnected enhanced-session desktop initially made GDI fail; transferring the already logged-in session to console restored screenshots. No automatic Windows sign-in/unlock is implemented.

Also fixed UTF-8 result reading and ASCII-escaped JSON transport for compatibility with older Windows PowerShell workers; a real Chinese output round-trip passed. Queue consumption removes completed guest requests; recent results are bounded to 500 and screenshots are copied to host evidence. Interrupted desktop operations are not replayed. Unit/browser checks cover persistence metadata, saved reconnect/delete, screenshots, Unicode, read-only tool permissions, and layout/reading regressions. GUI/UAC connection flow is automated with fixtures; the actual guest password persistence still requires the user's first connection in the new version.


## Startup and power management
Version-4 helper starts Off/Saved VMs (resumes Paused), retries PowerShell Direct while Windows boots, then automatically deploys the interactive desktop service. A shutdown request cancels connection retries or interrupts an in-flight remoting job so the power command is not stuck behind a long build. Normal shutdown uses Stop-VM without TurnOff; forced shutdown uses explicit TurnOff and has a UI confirmation. Models cannot invoke the user-only vm_control endpoint. No automatic OS login is configured. Saved connections are chosen from last-vm.json; optional VM boot runs after the shell's first paint, in parallel with ordinary backend use. The live user VM was not power-cycled for this change.
