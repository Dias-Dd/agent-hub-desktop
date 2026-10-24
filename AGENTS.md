# Agent Message Hub maintenance

## UI changes: mandatory layout and interaction checks
User requires that future UI changes never hide original output, push the composer/send button out of reach, or create clipped content without a working scroll path. Preserve reading expansion, scroll, selection and draft input on refresh. Keep manager history/plans in a bounded scroll area and the composer visible. Verify long replies plus long approval cards at normal, short and narrow viewport sizes. Run tests/test_manager_layout.py, tests/test_reading_browser.py and tests/test_nine_browser.py after UI changes; fix failures before deploying. Do not treat JS syntax checks or DOM existence as layout verification. Keep these regression fixtures aligned with real rendered layout.
