# Third-party notices

## CC Switch

The Claude Code module's `settings_path()` in
`hub/builtin_adapters/claude-code/config.py` is adapted to Python from
`get_claude_settings_path()` in CC Switch's `src-tauri/src/config.rs`.
It retains the preference for `settings.json` with a legacy `claude.json` fallback.
Our version also honors Claude Code's `CLAUDE_CONFIG_DIR` environment variable.

Source: https://github.com/farion1231/cc-switch/blob/e8e1cfbff4f2d93f2d6c4ba4ad10b511e012c733/src-tauri/src/config.rs

CC Switch is MIT licensed; the full upstream copyright and license are preserved
in [licenses/cc-switch-MIT.txt](licenses/cc-switch-MIT.txt).
No CC Switch application, proxy service or credential database is required.
The Claude Code execution transport is implemented in this repository using
the official CLI print protocol, not copied from CC Switch.

### OpenCode provider presets

`tools/vendor/cc-switch-opencode-presets.json` and the generated `opencode-*`
module manifests adapt the public presets from
[opencodeProviderPresets.ts](https://github.com/farion1231/cc-switch/blob/88c878ac9da1d89ec1b512f87b52f3641dd30e3c/src/config/opencodeProviderPresets.ts).
The snapshot groups 107 presets into 87 families, of which 84 families are generated;
AWS Bedrock and the two Oh My OpenCode plugin templates are explicitly skipped.
Marketing query parameters are removed from website links. Runtime credentials
are not part of these presets. No CC Switch executable or database is used.

The upstream MIT copyright and full license are included in the snapshot,
in every generated module entrypoint, and in `licenses/cc-switch-MIT.txt`.
The shared ACP execution and provider isolation code are implemented by Agent Hub.


## Pi and Node.js

API execution uses `@earendil-works/pi-agent-core` and `@earendil-works/pi-ai` 1.4.0 (MIT), from https://github.com/earendil-works/pi. The lockfile pins dependencies. Pi license: `hub/builtin_adapters/pi-api/engine/PI-LICENSE.txt`. Builds include collected dependency license texts and the official Node.js 22.19.0 license. Node archives are verified against the official SHA-256 checksums before packaging.
