# Agent Hub Desktop

[简体中文](README.md) · [English](README.en.md)

**An AI agent collaboration workspace for Windows and macOS.** Connect different harnesses, CLIs and APIs to a project, and let a manager agent organize discussions, assign work, track progress and deliver results.

Keep your existing model accounts and execution tools while managing collaboration in one interface. Agent Hub is not a model service and does not include subscriptions or API credits.

## Quick start

### Download and install

Visit the **[latest Release](https://github.com/Dias-Dd/agent-hub-desktop/releases/latest)** and download the installer for your system. You do not need to install Python or build the source. This README describes `main`; check the Release notes for which features are included in each installer.

- **Windows 10 2004 (build 19041) or later / Windows 11:** download and run `AgentHub-Setup-*.exe`. Choose Simplified Chinese or English. If WebView2 Runtime is missing, the installer downloads it through Microsoft's bootstrapper.
- **macOS 14+ / Apple Silicon (arm64):** download the matching `.dmg`, open it and drag Agent Hub into Applications, then launch the app. macOS support includes native Cocoa / WKWebView windows, the menu bar, settings and optional Tart VMs. See the Release notes for the exact build version, signing status and tested systems. Current Mac installers target Apple Silicon.

Before upgrading, save drafts and fully quit the previous app. On first launch, the configuration guide helps you add agents, select a manager and optionally connect a VM. You can skip agent and VM setup and configure them later in settings. Model calls still require the relevant harness to be installed and signed in, or your own API credentials.

Optional VM tools use Hyper-V on Windows and Tart on macOS. Ordinary projects do not require a VM. See the [macOS port notes](docs/MACOS_PORT.md) for further Mac usage and development details.

### Create your first project

1. Open **Agent panel → Add Agent** and choose an integration.
2. Install and sign in to its harness, or configure API credentials as requested, then read the model catalog.
3. Select a model and effort level, confirm execution authorization and add the agent. **A real connection test invokes the model and may consume credits.**
4. Create a project, choose its working directory and manager, and select team members. A single-agent setup also works.
5. Describe your goal in manager chat, review the plan and approve work. If you choose a demo first, approve the design before implementation.
6. Follow progress, output and deliverables in chat, project status and the sidebar. Use stop controls when needed.

### Connect an API with Pi

In **Add Agent**, choose **Custom API with built-in executor (Pi)**. Select a DeepSeek, OpenRouter or Gemini preset, or enter a custom service URL and protocol. Enter an API key directly, or specify an existing key environment variable. Save, read the model catalog and select a model. You can enter comma-separated model IDs if the service does not expose a catalog.

The integration supports OpenAI Chat Completions, OpenAI Responses, Anthropic Messages and Google Gemini protocols. Pi starts only while an API task runs and is reclaimed afterward; other harnesses do not start Pi. Installers bundle Node.js. Keys entered in the UI use Windows DPAPI or macOS Keychain and are not shown again. Existing API agents retain their connections, environment-variable credentials and history while moving execution to Pi.

CLI integrations continue to use their own sign-in and configuration. After changing user environment variables, fully quit and reopen the app. `.env.example` is a reference template: the app **does not automatically load `.env` files**.

## Features

- **Project collaboration:** manager conversations, group chat, task queues, progress and original output.
- **Rendering and notification settings:** choose an installed browser, a custom Chromium executable or an app-managed download; control notification events and foreground/background timing. See the [settings guide](docs/BROWSER_NOTIFICATIONS.md) (Chinese).
- **Cross-project memory:** managers can save preferences and reusable lessons. Settings provide editing, history previews, rollback and a user-controlled write lock. See the [memory guide](docs/LONG_TERM_MEMORY.md) (Chinese).
- **Discuss before executing:** review a plan before approving work. Optionally build a demo, approve its design and then proceed to implementation, or skip the demo.
- **One agent or a team:** one agent can manage and do the work; multiple agents can divide tasks, report results and integrate changes.
- **Modular integrations:** built-in and custom Python adapters share an interface. JSON Lines subprocess bridges are also supported.
- **Project tools:** authorized file operations, commands, Git workspaces, browser rendering, artifact publishing and Hyper-V (Windows) / Tart (macOS) VM tools.
- **Execution controls:** stop locks, queue management, persistent reminders and, where supported, quota and recovery observations.
- **Desktop UI:** Chinese and English, separate windows, tray notifications, light/dark themes with independent palettes, native Cocoa / WKWebView windows on macOS, Windows 10 Acrylic and Windows 11 Mica. Material appearance depends on system transparency settings and graphics support.

## Built-in integrations

| Integration | How it connects |
| --- | --- |
| Claude Code | Uses the installed official CLI and its existing account/provider configuration, with project sessions and Hub MCP. [Integration notes](docs/CLAUDE_CODE.md) (Chinese) |
| DeepSeek Harness | Official ACP channel; prefers the account signed in to DSH. Account access does not require a separate API key |
| Codex, Antigravity | Their local official execution channels, subject to actual login state and capabilities |
| OpenCode provider presets | 84 independent provider modules covering 104 region/plan variants, with isolated configuration, credentials and sessions alongside the original OpenCode integration. [Provider guide and scope](docs/OPENCODE_PROVIDERS.md) (Chinese) |
| OpenCode | Providers already configured and authorized locally; third-party subscription/API support depends on OpenCode and the provider |
| CodeBuddy, ORI | Their local CLIs; CodeBuddy retains the `workbuddy` source module identifier |
| Custom API with built-in executor (Pi) | Presets, custom URLs, protected credentials and model IDs; compatible with existing API agents. [Configuration guide](docs/MODULE_CONFIGURATION.md) |

Authentication, tools, session resumption, model catalogs and balance access vary by integration. Listing a model does not prove invocation rights. Unknown quota does not mean unlimited quota.

## Connect your own harness manually

**Your platform is not listed? Add an adapter without modifying the application.** Place `adapter.json` and your script under `adapters/custom/<your-module>/` in the data directory, then refresh custom integrations in the Add Agent UI. You can also copy a similar built-in module in full and change its ID and configuration.

- Default Windows installed path: `%LOCALAPPDATA%\AgentMessageHubDesktop\data\adapters\custom`
- Default macOS path: `~/Library/Application Support/AgentMessageHubDesktop/data/adapters/custom`
- With the source command below: `.\local-data\adapters\custom`
- Prefer `hub-module-v1` Python modules. Use `hub-jsonl-v1` for separate executables, Node.js, PowerShell or another runtime.

See the **[Manual Harness Integration Guide](docs/HARNESS_INTEGRATION.en.md)** for folder layout, a basic example, authentication, sessions, tools, quotas and troubleshooting.

## Run from source (Windows developers)

Requirements: **Windows 10 2004 (build 19041) or later / Windows 11**, **Python 3.11+ with Tkinter**, and **Microsoft WebView2 Runtime**. Model calls also require the relevant harness to be installed and signed in, or your own API credentials.

```powershell
git clone https://github.com/Dias-Dd/agent-hub-desktop.git
cd agent-hub-desktop
# For API/Pi development: install Node.js 22.19+ and npm, then prepare once.
python tools/prepare_pi.py
python desktop/launch_desktop.py --data .\local-data
```

`local-data` keeps this run separate from an installed application's default data. The Python host uses the standard library; API execution additionally uses the prepared Pi/Node bundle. If you only use CLI harnesses, you can skip Pi preparation when running from source. PyInstaller is not needed to run from source. The source entry opens the workspace directly. The separate first-run setup program is intended for the packaged installation.

## Build the installer

Install Node.js 22.19+ with npm and Inno Setup, then run these commands from the repository root. Adjust the compiler path to your installation:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r desktop/requirements-build.txt
.\desktop\build_installer.ps1 -Python .\.venv\Scripts\python.exe -Compiler "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

Output: `desktop/installer-dist/AgentHub-Setup-0.2.4.exe`, including the main app, separate configuration program, MCP tool transport and diagnostic exporter. The script verifies the signatures of the Inno Setup compiler and Microsoft WebView2 bootstrapper.

## Data, permissions and diagnostics

Installed data defaults to `%LOCALAPPDATA%\AgentMessageHubDesktop\data` on Windows and `~/Library/Application Support/AgentMessageHubDesktop/data` on macOS. Source runs use `--data`. It stores projects, messages, execution state, sessions and integration settings. Uninstalling the app preserves this data.

Adapters run with the current user's permissions; **they are not an OS sandbox**. Use trusted modules and review directories, command permissions and provider costs. Hyper-V administration may require elevation.

If a project appears stuck, export diagnostics before restarting or upgrading. Installed users can use the Start menu diagnostic tool; source users can run:

```powershell
python desktop/export_diagnostics.py --data .\local-data --output .\diagnostics.zip
```

Archives contain conversations and local paths: review them before sharing. See [diagnostic notes](docs/diagnostics.md) (Chinese). Do not commit credentials, runtime data or real keys.

## Source layout and tests

| Directory | Contents |
| --- | --- |
| `hub/` | Service, scheduling, permissions, sessions and frontend |
| `hub/builtin_adapters/` | Built-in harness/API modules |
| `hub/adapter_examples/` | Module and JSONL examples |
| `desktop/` | Native Windows / macOS hosts, setup and packaging |
| `tools/` | VM bridge and supporting utilities |
| `tests/` | Automated tests |

```powershell
python -m unittest discover -s tests -p test_manager_owned_plan.py
python -m unittest discover -s tests -p test_native_backdrop.py
python -m unittest discover -s tests -p test_unified_modules.py
```

UI changes must also run `test_manager_layout.py`, `test_reading_browser.py` and `test_nine_browser.py`; these browser tests require Microsoft Edge. Older records in `docs/` may contain obsolete identities or settings. Use this README, the [integration guide](docs/HARNESS_INTEGRATION.en.md) and current source as the reference. Some historical tests also retain old identity fixtures.

## Module configuration forms

A Python module can declare text, password, URL, dropdown, model-list, integer and checkbox fields in `adapter.json`. Add Agent renders the form automatically, validates submitted values and protects secrets. All 84 OpenCode provider modules use this declaration format while retaining their isolated configuration and sessions. See [field declarations and script access](docs/MODULE_CONFIGURATION.md).

## License

[Apache License 2.0](LICENSE). Pi, Node.js, CC Switch-derived presets and other dependencies retain their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).
