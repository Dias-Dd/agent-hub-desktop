# 2026-10-19 access recovery

At inspection, neither 8765 nor 8766 was listening. Two desktop EXE processes existed initially but exited before relaunch; no captured exception establishes their original exit cause.

Restored the original non-simulation supervisor on 8765 and relaunched the existing packaged desktop with its own existing LocalAppData database on 8766. HTTP root, authenticated health, and authenticated state all returned 200 on both ports; five projects were present on each and no model execution was active. Packaged isolated smoke test passed all ten static asset checks and same-origin credential exchange.

The current desktop EXE is a PyInstaller bundle of desktop/launch_desktop.py and Python Hub, not the separately implemented rust-hub binary. Its default port is 8766, its database is LocalAppData/AgentMessageHubDesktop/data, and closing its owner window shuts down that desktop service. The original website is a separate supervisor service on 8765 with the workspace database. No histories were merged, reset, or migrated during recovery. No model inference was started.

Open-Desktop.cmd opens the actual current desktop executable. This restores access; the original desktop exit cause remains unconfirmed and Rust desktop integration remains incomplete.
