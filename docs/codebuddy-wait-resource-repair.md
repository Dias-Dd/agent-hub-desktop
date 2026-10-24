# CodeBuddy session and manager waiting repair (2026-10-22)

Observed causes
- Hy3's original CodeBuddy conversation 01a160dd-0778-7550-99c3-302d6f1ce9a5 exists beneath the weather draft-1 project directory. The production task launched from the product root with --resume, so the official CLI logged SessionNotFoundError and exited 0 without a final stream result. This was not an observed quota or authentication error.
- The manager repeatedly called Start-Sleep for 180/240/240 seconds and created no timers. Timer tools were advertised and available. Long command waits occupied its round while new reports accumulated.
- A manager follow-up task was registered as wildcard (*) because the fallback extractor omitted .cs/.xaml/.csproj/.sln. It serialized unrelated work behind Step-5, and the skeleton task behind that follow-up. During investigation the manager cancelled both queued Luna tasks and reassigned the skeleton; those cancellations were preserved.

Changes
- WorkBuddy/CodeBuddy print-mode resumes from the saved original conversation directory, uses the locally documented --add-dir flag for the current approved task directory, and explicitly directs current operations to that directory. Session identity is retained. Missing-session diagnostics are correlated by session ID and timestamp, including detached CLI child errors. No replacement sessions or automatic retries.
- Shared scheduling policy: finish the round while waiting for member reports; those reports wake the manager. Use a persistent schedule_wake reminder only when a fallback check is needed, then finish. Do not use sleep/Start-Sleep or busy polling to wait for members. The timer service itself was not changed.
- Recognize .NET/WinUI/PowerShell paths, including compound .xaml.cs. Manager follow-up messages preserve their preceding assignment's explicit file scope and include newly identified files. Startup rebuilds resource edges only for queued work; running/terminal work and explicit task order are preserved. Real overlapping paths still serialize.

Validation
- 6 new tests: original-directory resume plus --add-dir/current-target prompt and project isolation; scoped current-run error diagnostics without log leakage; .NET path extraction; follow-up resource ordering; queued migration with stale edges; shared wait policy.
- Regressions: 6 ACP directory, 7 CLI diagnostics, 22 automation, 8 manager-input, 29 Harness, 14 coordination/resource and 22 integration tests all passed.
- The installed official codebuddy --help confirms --resume and --add-dir. No inference probe or failed-task replay was performed.
- Production was read only throughout this repair. No Hub restart, manual agent wake or task cancellation was performed by this development session. Existing manager actions were observed only.

Activation: exit Hub through its system tray and reopen the updated executable. Original conversations and prior manager reassignments remain intact.
