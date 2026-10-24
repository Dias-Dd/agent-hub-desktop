# Screenshot service repair

Before: the active frozen desktop service failed on the same about page that rendered successfully from ordinary Python. Its error wrapper only returned stderr, losing exit status and missing-output diagnostics. An Edge crash was also present in Windows Application events; this alone does not establish the precise historical cause.

Changed: external browser startup clears frozen DLL search override during process creation and removes inherited WebView/Qt/Python host settings. Failure messages and audit records retain exit code (decimal/hex), PNG presence, stderr and stdout. Added a no-model frozen executable browser probe.

Validation: 46 route/automation regression tests pass. Frozen executable probe passed. Following the user's explicit approval, backed up production DB, paused dispatch, stopped current rounds, replaced and restarted the desktop service, preserved persistent sessions, and queued manager field-check continuation. Actual production browser_render API then passed four consecutive calls: about, history, about, history, each a fresh 1280x800 PNG. No old screenshot substituted. Production service is running the new backend. These checks demonstrate rendering availability, not full product acceptance.

Backup: work/before-browser-fix-restart.sqlite3 and work/before-browser-startup-fix.zip in task workspace.
