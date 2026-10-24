# Early VM elevation request

Cause: VM startup was dispatched only after OwnedHub initialization and virtual_machine then waited on the page ui_ready event for up to 30 seconds. Thus the UAC request appeared well after the main app opened.

Change: start a single VM worker immediately after the lightweight HTTP shell starts and before the backend initializer starts. Remove the ui_ready wait and the duplicate post-backend dispatch. The existing VmBridge control/launch helper remains responsible for actual Windows elevation and reusing an alive compatible helper. Consent wait happens on the VM worker, not on the UI/backend. No service registration, UAC policy change, credential migration, live VM operation, or real model call was performed.

Validation: test_early_vm_start (4 passed) proves VM authorization requested with deliberately blocked backend and unset UI-ready event, visible shell still available within 2 seconds, no duplicate after cancelled consent, no request in smoke/no-saved-VM cases. test_vm_bridge (16 passed) includes reuse of an alive protocol-4 helper without ShellExecute. test_startup_dependencies (4 passed). test_fast_start actual browser passed, including usable local tabs/draft before backend, backend controls enabled independently of slow VM. These tests mock elevation; no surprise real UAC dialog is launched in the development session.

Backup: ../agent-message-hub-before-early-uac-app.zip. Immutable package; running Hub unchanged until user exits/reopens.

Additional verification: manager layout/reading/nine browser suites passed; packaged basic smoke and actual fast-start native window smoke passed (Mica true, transparent WebView true, caption gap 0).
