# Discussion chat and full-page demo repair (2026-10-22)

Discussion inputs were rendered twice from planning history and the durable message queue. Their execution result also appeared under the user bubble, repeating the manager response and producing a large block of raw plan content. Project snapshots now expose the exact discussion/run linkage. The UI merges only bound copies and keeps genuinely repeated user messages. Manager output remains in manager history/live output; pending input and timestamps remain visible.

The preview previously assumed 1280x900, but the current frozen weather design uses a 1760x1080 sheet including annotations. On load the host measures the document's rendered extent, sizes the canvas accordingly, and fits the entire sheet. Zoom, middle-button pan, normalized region selection, feedback drafts and reopen recovery remain available. Measurement uses allow-same-origin without allow-scripts; the response CSP still forbids scripts, network requests, forms and external resources. A malicious-script fixture confirms scripts do not execute.

Edge's detached launcher can exit with code 0 before its browser opens DevTools. The renderer now waits for the isolated browser endpoint, then closes that browser explicitly. Browser tests use real CDP page results rather than accepting empty dump-dom output.

Validation: manager layout (1440x900, 1024x600, 600x800); reading preservation; Agent grid; discussion queue/history/stream/composer (1993x1248 plus the three sizes); demo fit/zoom/pan/selection/multi-page feedback/reload (three sizes); 13 design backend tests; discussion identity and project separation; project controls. A read-only copy of the actual frozen weather daily-detail page was visually verified at 1967x1248: all right-side annotations and bottom footer visible. Evidence: data/weather-preview-fixed.png. No model inference, production task interruption, design edits or service restart.

Activation requires exiting the running Hub through the system tray and reopening the updated executable.
