# Agent Hub Desktop

[简体中文](README.md) · [English](README.en.md)

**A Windows desktop workspace for coordinating AI agents.** Connect different harnesses, CLIs and APIs to a project, and let a manager agent organize discussions, assign work, track progress and deliver results.

Keep your existing model accounts and execution tools while managing collaboration in one interface. Agent Hub is not a model service and does not include subscriptions or API credits.

## Features

- **Project collaboration:** manager conversations, group chat, task queues, progress and original output.
- **Discuss before executing:** review a plan before approving work. Optionally build a demo, approve its design and then proceed to implementation, or skip the demo.
- **One agent or a team:** one agent can manage and do the work; multiple agents can divide tasks, report results and integrate changes.
- **Modular integrations:** built-in and custom Python adapters share an interface. JSON Lines subprocess bridges are also supported.
- **Project tools:** authorized file operations, commands, Git workspaces, browser rendering, artifact publishing and Hyper-V VM tools.
- **Execution controls:** stop locks, queue management, persistent reminders and, where supported, quota and recovery observations.
- **Desktop UI:** Chinese and English, separate windows, tray notifications, light/dark themes with independent palettes, Windows 10 Acrylic and Windows 11 Mica. Material appearance depends on system transparency settings and graphics support.

## Built-in integrations

| Integration | How it connects |
| --- | --- |
| DeepSeek Harness | Official ACP channel; prefers the account signed in to DSH. Account access does not require a separate API key |
| Codex, Antigravity | Their local official execution channels, subject to actual login state and capabilities |
| OpenCode | Providers already configured and authorized locally; third-party subscription/API support depends on OpenCode and the provider |
| CodeBuddy, ORI | Their local CLIs; CodeBuddy retains the `workbuddy` source module identifier |
| DeepSeek API, OpenRouter API, Gemini API | Their corresponding API configuration and credentials |

Authentication, tools, session resumption, model catalogs and balance access vary by integration. Listing a model does not prove invocation rights. Unknown quota does not mean unlimited quota.

## Quick start

### Run from source

Requirements: **Windows 10 2004 (build 19041) or later / Windows 11**, **Python 3.11+ with Tkinter**, and **Microsoft WebView2 Runtime**. Model calls also require the relevant harness to be installed and signed in, or your own API credentials.

```powershell
git clone https://github.com/Dias-Dd/agent-hub-desktop.git
cd agent-hub-desktop
python desktop/launch_desktop.py --data .\local-data
```

`local-data` keeps this run separate from an installed application's default data. The core service uses the Python standard library; PyInstaller is not needed to run from source. The source entry opens the workspace directly. The separate first-run setup program is intended for the packaged installation.

### Create your first project

1. Open **Agent panel → Add Agent** and choose an integration.
2. Install and sign in to its harness, or configure API credentials as requested, then read the model catalog.
3. Select a model and effort level, confirm execution authorization and add the agent. **A real connection test invokes the model and may consume credits.**
4. Create a project, choose its working directory and manager, and select team members. A single-agent setup also works.
5. Describe your goal in manager chat, review the plan and approve work. If you choose a demo first, approve the design before implementation.
6. Follow progress, output and deliverables in chat, project status and the sidebar. Use stop controls when needed.

Configure credentials through the integration's environment variables or existing credential flow. After changing user environment variables, fully quit and reopen the app. `.env.example` is a reference template: the app **does not automatically load `.env` files**.

## Connect your own harness manually

**Your platform is not listed? Add an adapter without modifying the application.** Place `adapter.json` and your script under `adapters/custom/<your-module>/` in the data directory, then refresh custom integrations in the Add Agent UI. You can also copy a similar built-in module in full and change its ID and configuration.

- Default installed path: `%LOCALAPPDATA%\AgentMessageHubDesktop\data\adapters\custom`
- With the source command above: `.\local-data\adapters\custom`
- Prefer `hub-module-v1` Python modules. Use `hub-jsonl-v1` for separate executables, Node.js, PowerShell or another runtime.

See the **[Manual Harness Integration Guide](docs/HARNESS_INTEGRATION.en.md)** for folder layout, a basic example, authentication, sessions, tools, quotas and troubleshooting.

## Installer and first-run setup

The repository contains source and build scripts; cloning it does not provide a compiled Agent Hub installer. If you already have `AgentHub-Setup-0.1.0.exe`:

1. Run the installer and select Simplified Chinese or English.
2. Add agents and select a manager in the separate setup program, or skip and configure them later in the workspace.
3. Optionally connect a Hyper-V VM. Setup can open management tools or Windows Features; it does not automatically install system features or restart Windows.
4. Finish to open the workspace. Reopen the configuration guide from the Start menu later.

If WebView2 Runtime is missing, the installer uses Microsoft's bootstrapper to download it. Hyper-V and Windows support for it are required only for VM tools, not for the workspace itself.

## Build the installer

Install Inno Setup, then run these commands from the repository root. Adjust the compiler path to your installation:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r desktop/requirements-build.txt
.\desktop\build_installer.ps1 -Python .\.venv\Scripts\python.exe -Compiler "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

Output: `desktop/installer-dist/AgentHub-Setup-0.1.0.exe`, including the main app, separate configuration program, MCP tool transport and diagnostic exporter. The script verifies the signatures of the Inno Setup compiler and Microsoft WebView2 bootstrapper.

## Data, permissions and diagnostics

Installed data defaults to `%LOCALAPPDATA%\AgentMessageHubDesktop\data`. Source runs use `--data`. It stores projects, messages, execution state, sessions and integration settings. Uninstalling the app preserves this data.

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
| `desktop/` | Native Windows host, setup and packaging |
| `tools/` | VM bridge and supporting utilities |
| `tests/` | Automated tests |

```powershell
python -m unittest discover -s tests -p test_manager_owned_plan.py
python -m unittest discover -s tests -p test_native_backdrop.py
python -m unittest discover -s tests -p test_unified_modules.py
```

UI changes must also run `test_manager_layout.py`, `test_reading_browser.py` and `test_nine_browser.py`; these browser tests require Microsoft Edge. Older records in `docs/` may contain obsolete identities or settings. Use this README, the [integration guide](docs/HARNESS_INTEGRATION.en.md) and current source as the reference. Some historical tests also retain old identity fixtures.

## License

[Apache License 2.0](LICENSE). Bundled Microsoft WebView2 binary dependencies are subject to their own licenses.
