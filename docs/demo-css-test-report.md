# Missing demo stylesheet fix

Cause verified on the current Calc demo: all page HTML referenced assets/demo.css. The original project held that 19,752-byte CSS, while the frozen design directory only copied manifest/page HTML. The ticket preview serves one HTML with restrictive CSP and cannot fetch a project-relative stylesheet. Browser evidence before repair shows unstyled text; after bundling it shows the full dark calculator/buttons/history/annotations correctly.

Changes: publish self-contained HTML by bundling local stylesheets, recursive local @import, CSS image/font URLs and img sources. Restrict resource resolution to the design root and supported static asset types; do not fetch external resources or enable scripts. Preserve existing CSS/media ordering. Frozen digest now covers embedded styles/assets. Missing resources produce a specific packaging error rather than a visually broken publication.

Recovery: only unapproved review snapshots with unchanged original HTML, identical page IDs/title and available original resources can be re-frozen to a new immutable directory. Old directory retained; approved designs not changed. Startup recovery performs this packaging repair without model calls, messages, project resume or task replay.

Current live repair: targeted the unapproved Calc review f45aa1ec31f54b128d72abca0a87a8a2 only, all 13 pages repaired, no remaining stylesheet links. SQLite backup made before the atomic update, preserving original frozen directory. Review remains review/version 1; new digest/directory refer to bundled HTML. Exact backup/new paths recorded in data/demo-css-live-repair.json (not included in public package). No manager or member awakened. Close/reopen the review to obtain fresh preview tickets.

Verification: design_assets 4, designs 13, required_folder_link 7, model_quota_visibility 4 passed. Mandatory manager layout/reading/nine checks and design browser/reload checks passed. Actual before/after Edge screenshots with the same style/image CSP inspected: docs/demo-css-before.png and docs/demo-css-after.png. No model inference or product redesign.

App backup: ../agent-message-hub-before-demo-css-app.zip. New immutable release, running Hub not restarted.

Packaged startup smoke passed (16 assets; native desktop and VM helper available).
