# Manual Harness Integration

[Project home](../README.en.md) · [简体中文](HARNESS_INTEGRATION.md)

This guide covers custom CLIs, compatible APIs and agent platforms. A **harness** is the program or service that invokes models, maintains sessions and executes tools. An adapter translates its protocol into Agent Hub's interface. Adding an integration does not require changing the application.

## 1. Choose an integration method

| Method | Best for | Runtime |
| --- | --- | --- |
| Copy a complete built-in module | A similar provider or compatible API; reuse its tool loop and session handling | Same as the original module |
| `hub-module-v1` | Python integrations using the SDK and login, model or quota hooks | Bundled Python in the installed app; the launching Python in source runs |
| `hub-jsonl-v1` | Standalone programs, Node.js, PowerShell or a separate Python environment | Your installed runtime or a standalone EXE |

Built-in and custom Python modules share the loader, SDK and hooks. Their locations and default configuration differ; built-ins do not have a separate privileged integration protocol.

## 2. Install and add an adapter

Installed data defaults to `%LOCALAPPDATA%\AgentMessageHubDesktop\data` on Windows and `~/Library/Application Support/AgentMessageHubDesktop/data` on macOS. With `--data .\local-data`, use the repository's `local-data` directory instead.

```text
<data-directory>/adapters/
├─ builtin/
│  ├─ deepseek-harness/
│  ├─ pi-api/
│  └─ ...
└─ custom/
   └─ my-chat-api/
      ├─ adapter.json
      └─ adapter.py
```

1. Create your folder and add `adapter.json` and the entrypoint.
2. Open **Add Agent → Refresh custom integrations**. The UI's custom-directory button can show the actual path.
3. Choose the module, sign in or configure credentials, then read or confirm its model catalog.
4. Select a model and effort level, name the agent and explicitly authorize execution.
5. Test basic chat first, then sessions and tools as supported. Real model calls may incur charges.

Ordinary discovery reads JSON without executing user scripts. Explicit login checks, catalog probes and execution run the relevant code. Catalog access does not prove authentication, costs or complete functionality.

Use a unique `id`: lowercase letters, digits and hyphens, beginning with a letter or digit, up to 48 characters. Duplicate custom IDs disable all matching entries instead of choosing one arbitrarily.

## 3. Use the built-in API executor or copy a module

For a supported API protocol, no custom script is required: select **Custom API with built-in executor (Pi)** in Add Agent, choose a preset or enter the protocol and service URL, then enter a key or key environment variable. Save, read models or enter model IDs manually, and add an agent. If the separate first-run guide cannot configure a module, skip agent setup and configure it in the main app.

Pi agent-core handles streaming model/tool loops. Hub retains project authorization, tool dispatch, stop controls and durable history. Node runs only for API tasks and exits afterward; other harnesses do not start it. The installer includes the runtime. Source users prepare it with `python tools/prepare_pi.py` using Node.js 22.19+ and npm. This integration does not load Pi CLI extensions or automatically compact history: context overflow is reported explicitly. Supported protocols do not imply every provider has been tested with a real account.

To create a separately named module, copy the **entire** `builtin/pi-api` folder into `custom/my-api`, change the manifest `id` and `name`, and update the declaration's preset/default values as appropriate. Keep the entrypoint and supporting Python files. The installed app supplies the shared Pi bridge and Node runtime; there is no need to copy `node_modules` or the Node binary. Validate your endpoint, model IDs and tools before using it for a project.

Existing `deepseek-api`, `openrouter-api` and `gemini-api` entries remain for compatibility with old agents. Their execution now delegates to Pi; they are not the recommended templates for new API integrations. [Field declarations and runtime details](MODULE_CONFIGURATION.md).

## 4. Write a Python module: basic API example

This adapter makes a real request to your Chat Completions compatible endpoint using the standard library and forwards successful conversation history. It supports **text chat only**, without tools, native session resumption or streaming. It is not a full project execution adapter.

### adapter.json

Replace `provider-model-id` with a model the service actually supports.

```json
{
  "version": 1,
  "id": "my-chat-api",
  "name": "My Chat API",
  "protocol": "hub-module-v1",
  "entrypoint": "adapter.py",
  "models": [{"id": "provider-model-id", "efforts": ["default"]}],
  "capabilities": {"tools": false, "resume": false, "streaming": false},
  "configuration": {
    "version": 1,
    "title": "My API settings",
    "fields": [
      {"name": "endpoint", "type": "url", "label": "Full Chat Completions URL", "required": true, "default": "https://example.com/v1/chat/completions"},
      {"name": "api_key", "type": "secret", "label": "API Key", "required": true}
    ]
  }
}
```

### adapter.py

```python
import json
import urllib.error
import urllib.request


def execute(context, run):
    context.guard(run)
    request = context.request(run)
    config = context.user_configuration()
    messages = [{"role": "system", "content": request["system"]}]
    messages.extend(request["history"])
    messages.append({"role": "user", "content": request["prompt"]})
    payload = {"model": request["model"], "messages": messages, "stream": False}
    http_request = urllib.request.Request(
        config["endpoint"],
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + config["api_key"],
            "Content-Type": "application/json",
        },
    )
    try:
        timeout = min(request["timeout_seconds"], 60)
        with urllib.request.urlopen(http_request, timeout=timeout) as response:
            body = json.load(response)
        reply = body["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Provider HTTP {error.code}; not retried") from None
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        raise RuntimeError("Provider connection or response failed; not retried") from None
    context.guard(run)
    return {"status": "completed", "text": reply}
```

The declaration generates inputs in Add Agent. Enter the service's complete Chat Completions endpoint and your key, save, and add the agent. Without a custom `configure` hook, ordinary fields are persisted and secrets use Windows DPAPI or macOS Keychain. Empty secret inputs retain saved values; secrets are not returned to the browser. The example is intended for those desktop platforms. An `environment` mapping remains available for modules that prefer references to existing host environment variables; `.env` files are not loaded automatically.

`resume: false` does not mean there is no history. The SDK saves successful exchanges and provides them as `history` on the next turn. This example forwards that history; it is not a provider-native session and does not contain complete tool traces.

## 5. Who implements each capability?

| Capability | Agent Hub | Adapter |
| --- | --- | --- |
| Projects, identities, grants, queues, stop locks, delivery | Manage and persist state | Use the current request without expanding authority |
| Model invocation, login, credential protocol | Provide setup entry points | Connect to the actual provider |
| History and session mapping | Save successful exchanges and isolate project/agent context | Forward history or resume the correct native session |
| Tools | Provide and validate the current allowed tools | Translate calls, run the provider tool loop and return real results |
| Models, efforts, balances | Store and display supported observations | Read provider data without inventing support or unlimited quota |
| Cancellation | Revoke platform authority; JSONL processes can be terminated | Cooperate with stop checks and cancel remote requests |

Setting `tools: true` does not implement tools for an arbitrary service. The SDK cannot invent an unknown platform's login or session protocol. Reusing a similar built-in module can save that implementation work.

### Main Python interfaces

- `execute(context, run)` is required. Basic modules return a nonempty string or `{"status":"completed","text":"actual reply"}`; add `session_id` for a native session.
- `context.request(run)` includes `system`, `prompt`, `history`, `session_id`, `model`, `effort`, `cwd`, `permission`, `tools` and `timeout_seconds`. Forward the system constraints and history, not just the prompt.
- `context.guard(run)` checks stop state, authorization and time budget. Call it before tools and further requests, and while waiting. Set timeouts and implement cancellation for blocking calls.
- `context.public_reply(run, text)` streams text; `context.record(run_id, kind, data)` records sanitized events.
- `context.tool(run, name, arguments, allowed_names)` invokes a platform tool. Derive allowed names from the current `tools` function list.
- `context.sessions.get/bind/state` supports advanced session handling. See built-in examples and the [SDK source](../hub/module_sdk.py).

A tool loop converts the current definitions to the provider format, passes model tool requests to `context.tool`, and returns the real results to the model. Return `completed` only after a confirmed finish. Do not bypass platform checks or fabricate task, delivery or VM success.

After successful native resumption, do not replay the same history again. Report resume failures explicitly instead of silently replacing session IDs and losing context. A native session's original directory may differ from the current authorized directory; consult the built-in harness implementation.

### Declarative fields and optional hooks

See [module configuration](MODULE_CONFIGURATION.md) for text, secret, URL, dropdown, list, integer and boolean fields; option defaults; server validation; and `context.user_configuration()`. Forms currently target Python `hub-module-v1` modules in the main Add Agent screen. JSONL integrations continue to manage their external program's configuration.


| Function | Return value and purpose |
| --- | --- |
| `probe(registry, connection)` | An object containing `models`, with actual `id`, optional `name` and `efforts`; catalog discovery must not send inference |
| `probe_model(registry, connection, model)` | Actual efforts, such as `{"id": model, "efforts": ["default"]}` |
| `setup_status(registry, connection)` | A `state` of `ready`, `login`, `missing` or `unknown`, with a readable `message` |
| `setup_login(registry, connection)` | Open the platform's real login UI, interactive CLI or official page |
| `configure(registry, connection, config=None)` | Optional custom read/save hook after field validation; return `config` without plaintext secrets. Without a hook, Hub stores declared fields automatically |
| `quota(registry, connection)` | Official observations such as `official_balance`, `official_windows` and `quota_observed_at` |

A balance observation can use `official_balance: [{"name":"Account balance","amount":"12.34","currency":"CNY"}]`. Window observations can include `remaining` (remaining percent), `resets_at` (Unix seconds) and `name`. On failure, report an error and retain the previous observation rather than inventing zero or unlimited quota. One-click refresh availability also depends on the integration's UI support.

The manifest can include `setup.website`, `setup.login_url` and `setup.note`. Use real HTTPS addresses, not published placeholders. If reliable login detection is unavailable, ask for explicit manual confirmation rather than treating a readable catalog as a successful inference test.

## 6. Standalone programs: hub-jsonl-v1

JSONL starts one subprocess per turn, using the turn's `cwd`. Example manifest:

```json
{
  "version": 1,
  "id": "my-cli",
  "name": "My CLI",
  "protocol": "hub-jsonl-v1",
  "command": ["${python}", "${adapter_dir}/bridge.py"],
  "models": [{"id": "provider-model-id", "efforts": ["default"]}],
  "capabilities": {"tools": false, "resume": false, "streaming": false},
  "environment": {}
}
```

`command` is an argument array, not a shell command string. `${adapter_dir}` expands to the adapter directory. `${python}` uses an external local Python installation: **the installed app's bundled Python is not an external Python command for JSONL**. You can instead use your own EXE or another runtime.

The first stdin line is a `run` object with the request fields described above, `protocol: "hub-jsonl-v1"` and an additional `session_cwd`. Write UTF-8 stdout as one JSON object per line. Put logs on stderr, not stdout.

```json
{"type":"text","text":"Optional incremental text"}
{"type":"result","status":"completed","text":"Actual final reply"}
```

`text` events provide streaming output. The final result may omit `text` to use the accumulated chunks. A nonempty reply and explicit completion are required: exit code 0 or EOF alone is not success. Report errors with `{"type":"error","message":"Readable error"}`.

For tools, declare `tools: true` and send calls from the request's allowed list:

```json
{"type":"tool_call","id":"call-1","name":"project_status","arguments":{"view":"status"}}
```

Read the matching `tool_result` from stdin, containing either `result` or `error`, and continue the model loop. With `resume: true`, return a valid `session_id` and restore that ID next turn without silently substituting another one.

Persist required native state before sending completion; the process is reclaimed afterward. Terminating a process does not guarantee cancellation of a remote paid request. The repository's echo-only [protocol example](../hub/adapter_examples/bridge.py.example) does not invoke a model and must not be treated as proof of a real connection.

## 7. Validation and troubleshooting

Test in order: discovery → login/credentials → real chat → a second contextual turn → tools, if supported → read-only authorization → stop/timeout → resumption after restart. Full project execution requires a tool-capable adapter; a text-only adapter is insufficient.

| Symptom | Check |
| --- | --- |
| Module missing from Add Agent | Actual data directory, folder depth, manifest name, unique ID, valid JSON and entrypoint |
| Model listed but invocation fails | Login, provider authorization, real model ID, effort and costs/quota |
| Environment changes not applied | Fully quit the app and background processes, reopen, and verify mapping direction |
| Chat works but execution/delegation does not | Implement actual tools and use the current definitions and real tool results |
| Context is lost | Forward `history` or correctly restore `session_id`, without duplicate replay |
| JSONL exits but fails | Send a final result and nonempty text; keep logs out of stdout |
| Remote job continues after stop | Implement SDK/API cancellation; local termination alone cannot guarantee remote cancellation |

Modules run as the current user, not in an OS sandbox. Do not write files or run commands outside the grant, or send credentials to the model. Back up custom modules; do not assume upgrades overwrite locally edited built-ins.

Further references: [module interface](harness-modules.md) and [JSONL compatibility protocol](custom-harness.md) (Chinese), [SDK](../hub/module_sdk.py), [built-in implementations](../hub/builtin_adapters/) and [integration tests](../tests/test_unified_modules.py).
