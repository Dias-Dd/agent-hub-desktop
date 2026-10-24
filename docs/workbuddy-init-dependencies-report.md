# WorkBuddy startup and dependency recovery

## Findings and repair

Two independent startup issues were reproduced. Hub synthesized HTTP(S)_PROXY from Windows settings for WorkBuddy; the installed WorkBuddy bundle's Axios setProxy branch then threw `Right-hand side of instanceof is not callable` while testing its bundled proxy-agent constructor. The supported WorkBuddy network configuration is now left to WorkBuddy, without synthesizing those variables; explicit parent environment configuration is retained, and system proxy settings/install files are unchanged. WorkBuddy print execution uses the same corrected environment.

For this installed lite-wb build, `--acp` alone fell through to an internal agent render without an ACP connection and exited without protocol output. The official `--serve --acp --acp-transport stdio --host 127.0.0.1 --port 0` entry successfully establishes ACP, with default HTTP authentication retained. Catalog probe initializes and creates a fresh metadata session only; never sends session/prompt. Dynamic primary-agent menu has 9 models, while installed product catalog has additional choices. The merged catalog preserves source labels and unknown pricing/account eligibility.

A repeatable real probe (`tools/probe_workbuddy_startup.py --model hy3 --model hy4-preview`) confirms ACP v1 handshake, session creation and official config-option acknowledgement of both selected IDs, without inference. Two repeated catalog probes succeeded. After activating packaged desktop, the live integration_probe API returned 9 dynamic models and 54 merged candidates. Selection acknowledgement does not establish actual inference entitlement or free pricing.

## Automatic dependencies

Desktop launch now inspects enabled connections with enabled Agent profiles, before starting/restoring Hub. Installed DeepSeek Harness, Antigravity and WorkBuddy desktop hosts start when absent, with hidden startup flags; existing hosts are not duplicated. Codex/OpenCode/Ori independent CLIs continue starting on demand. Host launches are detached from Hub CLI job lifetimes, clear inherited Electron console/frozen-app DLL settings during spawn, and do not send tasks. No Windows boot startup is registered.

When a configured local Windows proxy port is unavailable, the helper may launch a recognized proxy GUI from Windows Run registration or known installation roots. It never executes arbitrary registration command text, changes proxy configuration or downloads software. Missing programs/proxy are recorded rather than blocking the panel. Startup results are recorded in the user's data/startup-dependencies.json.

Real recovery on this machine started absent DeepSeek Harness and Antigravity hosts. Repeated checks returned running/running with proxy ready. WorkBuddy connection was disabled, so its GUI was not auto-started. The previously closed Hub was opened from the new executable and its visible window restored; no model task was resumed/replayed as part of dependency probing.

## Validation

WorkBuddy startup tests: 3 pass (environment, supported transport, merged catalog/no inference). Dependency tests: 3 pass (enabled-used filtering, existing-process reuse, duplicate-host prevention); source native window/background lifecycle test passes. Quota/catalog/registry tests: 25 pass; registry tests: 21 pass. Packaged smoke: ok=true, assets=10, native_available=true. Public real ACP probe and production probe both pass. Optional dependency-start exceptions no longer prevent panel launch. Source, build source, three executable copies, README and source archive updated.
