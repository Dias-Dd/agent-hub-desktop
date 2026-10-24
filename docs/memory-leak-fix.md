# Panel memory investigation — 2026-10-22

Found and reproduced a detached DOM retention chain in paginated list history buttons.
The callback created inside list() shared its lexical scope with pool/desired, retaining the previous button and recursively all older render trees. Moving callback construction into a separate factory breaks this chain without discarding history or refreshing the page.

Before: 500 forced changing snapshots retained 704,206 DOM nodes / 50,713 listeners, embedder heap about 115 MB; visible DOM remained about 1,250 elements.
After: 500 snapshots, five GC checkpoints: 5,014 DOM nodes / 343 listeners throughout; embedder heap about 2.26–2.74 MB; JS heap about 2.16–2.24 MB. Clicking history still reveals 60 rows.

These are isolated real Edge fixture measurements, not the entire application working set. Historical 7 GB was not captured; the production renderer was observed rising again to about 1 GB after the reported refresh. This leak plausibly explains the long-running growth, but does not prove that every byte of the historical peak had this cause.

Checks: test_memory_browser.py, test_manager_layout.py (1440x900 / 1024x600 / 600x800), test_reading_browser.py, test_nine_browser.py passed. No model calls or production restart.
