# Antigravity Claude test failure fix

Actual rejection: claude-opus-5-5-low conflicts with --effort=medium. Run 1ae931953d6b4818bb238e5965023f94 reported zero turns and zero tokens.

Model suffix now determines supported effort. Existing profiles/catalogs are repaired at startup without inference or budget changes. Provider rejection before init is retained rather than hidden behind missing-init validation. Old test snapshots expose recorded provider errors without rewriting execution history.

Validation: diagnostics 7 passed; integrations 22 passed; manager layout, reading browser, nine browser passed. No real inference retest was sent. Desktop restart from tray is required for backend activation.
