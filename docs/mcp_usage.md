# MCP Server Usage Guide

> **Important**: `src/mcp_server.py` is designed to be launched *only* by Model Context Protocol (MCP) clients such as VS Code (with the MCP extension) or Claude Desktop. Do **not** start it manually from the command line unless you are building a custom MCP client and explicitly need a raw stdin/stdout endpoint for development experiments.

This guide walks through setup and day-to-day usage of the MCP tooling provided by this repository. It covers both VS Code and Claude Desktop, highlights every available tool, and suggests a typical troubleshooting / debugging workflow that agents can follow.

---

## 1. Client Configuration

### 1.1 VS Code (AI Toolkit + MCP)

1. Install the official "AI Toolkit" (or equivalent MCP-capable) extension.
2. Open your VS Code `settings.json` and add the MCP server entry:

   ```jsonc
   {
     "mcp.servers.agentDebug": {
       "command": "${workspaceFolder}/.venv/bin/python",
       "args": ["src/mcp_server.py"],
       "cwd": "${workspaceFolder}",
       "env": {
         "PYTHONPATH": "${workspaceFolder}/src"
       }
     }
   }
   ```

3. These values point VS Code at the repository's virtual environment and ensure the MCP server inherits the correct module path. Once saved, VS Code automatically spawns the server on demand whenever an MCP-aware surface (such as Chat) needs the tools.

### 1.2 Claude Desktop

1. Open **Settings → Model Context Protocol**.
2. Add a new server with:

   - Command: `/full/path/to/.venv/bin/python`
   - Arguments: `src/mcp_server.py`
   - Working directory: `/full/path/to/mvp-agent-debug`
   - Environment (optional): `PYTHONPATH=/full/path/to/mvp-agent-debug/src`

3. Claude launches and terminates the MCP server automatically when conversations require it.

> **Tip**: `scripts/configure_mcp_clients.py` can generate the VS Code snippet and Claude Desktop entry for you. Run it after creating the virtual environment.

### 1.3 Why you should not run `python src/mcp_server.py`

- MCP clients manage stdin/stdout connections, retries, and lifecycle.
- Launching the script manually will block your terminal and provide no usable interface because the server expects properly framed MCP JSON-RPC messages.
- Use the direct `debugpy` walkthrough (`python src/dap_stdio_direct.py`) if you need to observe adapter traffic outside the MCP stack.

---

## 2. Tool Catalog & Workflow

Each tool exposed by `src/mcp_server.py` is listed below in the order a typical agent would use them. All tool responses are JSON-serializable dictionaries designed for downstream reasoning.

### 2.1 Test Execution Tools

| Tool | Description | Usage Notes |
| --- | --- | --- |
| `run_tests_json` | Executes `pytest` with the JSON report plugin, returning structured failure details plus debug metadata (paths, exit code, venv info). | Provide targeted arguments via `pytest_args` to keep runs fast, e.g. `{"pytest_args": ["examples/gui_counter/tests", "-k", "fast"]}`. |
| `run_tests_focus` | Convenience wrapper for `pytest -k <keyword>` that returns the same JSON payload as `run_tests_json`. | Equivalent to calling `run_tests_json` with `pytest_args=["-k", keyword]`. |
| `ensure_demo_program` | Scaffolds a demo script with an intentional bug and returns `launchInput` you can send directly to `dap_launch`. | Supply `{ "directory": "/tmp/debug_demo" }` to create the sample outside the repo when needed. |
| `read_text_file` | Reads a UTF-8 text file so you can inspect or quote it during debugging. | Provide `path` (absolute or relative to `cwd`) and optional `max_bytes` to truncate large files. |

**Typical phase**: Start with `run_tests_json` (or `run_tests_focus`) to reproduce the reported failure under automation.

### 2.2 Breakpoint Management

| Tool | Description | Usage Notes |
| --- | --- | --- |
| `dap_set_breakpoints` | Registers line breakpoints in a given file. Normalizes paths and caches requests so they can be inspected later. | Send absolute or relative paths; the tool returns adapter responses plus a `trackedBreakpoints` snapshot. |
| `dap_list_breakpoints` | Reports the server-side breakpoint cache without re-sending anything to the adapter. | Useful for auditing which lines were requested across turns. |

**Typical phase**: Call immediately after or during `dap_launch` to ensure breakpoints are set before the adapter starts running user code.

### 2.3 Launching Programs

| Tool | Description | Usage Notes |
| --- | --- | --- |
| `dap_launch` | Full initialize → breakpoints → configurationDone → launch sequence against `debugpy.adapter`. Can optionally wait for the first `stopped` event. Supports both main program breakpoints and breakpoints in imported modules. **Use this for ALL debugging scenarios including web servers, scripts, and long-running processes.** | Provide `program`, optional `cwd`, `breakpoints`, `breakpoints_by_source`, and `wait_for_breakpoint`. The response includes initialization payloads, retries, and the stopped event (if requested). |

**Typical phase**: Use `dap_launch` for all programs. The debugger controls the process lifecycle and allows you to set breakpoints that trigger on specific events (like HTTP requests for web apps).

> **Best practice**: Begin every new debugging session with `dap_launch` and supply the breakpoint list there. The helper wires `initialize`, `setBreakpoints`, and `configurationDone` in the correct order, so sending a separate `dap_set_breakpoints` before launching is unnecessary.
>
> **Path handling**: `dap_launch` accepts absolute paths or paths relative to the working directory you supply. If the working directory does not exist, the server attempts to create it. When the target script is missing, the response suggests ways to scaffold it (for example, by calling `ensure_demo_program`).

#### Breakpoints in Imported Modules

The `breakpoints_by_source` parameter allows you to set breakpoints in **any source file**, not just the main program. This is essential for debugging imported modules, libraries, or multi-file applications.

##### Example: Debugging a GUI counter with breakpoints in both runner and counter module

```python
result = await dap_launch(
    program="examples/gui_counter/run_counter_debug.py",
    cwd="examples/gui_counter",
    breakpoints=[8],  # Main runner breakpoint
    breakpoints_by_source={
        "examples/gui_counter/counter.py": [16]  # Counter module breakpoint
    },
    stop_on_entry=True,
    wait_for_breakpoint=True
)
```

##### Path Resolution

Relative paths in `breakpoints_by_source` are resolved in this preference order:

1. `PROJECT_ROOT / source_path` (preferred for repo-relative paths like `"examples/gui_counter/counter.py"`)
2. `cwd / source_path` (if `cwd` is provided and source doesn't appear repo-relative)
3. `Path(source_path).resolve()` (absolute fallback)

##### Retry Logic

The tool implements a **three-phase breakpoint registration strategy** to handle debugpy adapter timing:

1. **Initial attempt** (before `configurationDone`): May fail if the adapter is not yet ready to accept breakpoint registrations.
2. **Retry after init** (after the adapter sends `initialized`): The server retries breakpoint registration for any entries that failed during the initial attempt — this retry applies to both the main-program `breakpoints` and entries passed via `breakpoints_by_source`.
3. **Retry after stop** (after the first `stopped` event): The server performs a final retry for `breakpoints_by_source` entries that still aren't verified. This final pass is primarily important for imported-module breakpoints which might be requested before the module is loaded by the debuggee.

The `setBreakpointsBySourceRetryAfterStop` field in the response shows which breakpoints were successfully registered in the final retry phase.

#### Debugging Web Applications with dap_launch

Web servers and long-running applications work perfectly with `dap_launch`:
1. The debugger starts the server process
2. Breakpoints are hit when specific endpoints are accessed
3. You trigger breakpoints via HTTP requests while the server is paused at other breakpoints

**Workflow for Flask/Django/FastAPI apps:**

1. **Create a launcher script** (e.g., `run_flask.py`) to avoid relative import issues:
   ```python
   from examples.web_flask import app
   if __name__ == "__main__":
       app.main()
   ```

2. **Launch the app under debugger control:**
   ```python
   result = await dap_launch(
       program="run_flask.py",
       cwd=".",
       breakpoints_by_source={
           "examples/web_flask/inventory.py": [18]  # Breakpoint in business logic
       },
       wait_for_breakpoint=False  # Don't wait - let HTTP request trigger it
   )
   ```

3. **Trigger the breakpoint:**
   - Make an HTTP request to your app (e.g., `curl http://127.0.0.1:5001/total`)
   - Wait for stopped event: `await dap_wait_for_event("stopped", timeout=10)`
   - The debugger will pause at your breakpoint

4. **Inspect and step:**
   - Use `dap_locals` to see request data, variables, etc.
   - Use stepping commands to trace through the logic
   - Use `dap_continue` to let the request complete

5. **Clean up:**
   - `dap_shutdown` to stop the server and debugger

**Why not dap_attach?**

The `dap_attach` approach was investigated but **does not work with debugpy**. When you run `python -m debugpy --listen`, debugpy does not respond to DAP attach requests when connecting directly. This is a fundamental limitation of debugpy's architecture. Always use `dap_launch` for all debugging scenarios.

#### Quick demo recipe

- Call `ensure_demo_program()` to create a fresh script (the response includes `launchInput`, and you can pass an explicit `directory` such as `/tmp/debug_demo`).
- Launch with `dap_launch` using the provided `launchInput` (tweak breakpoints if desired).
- Inspect locals, step, then `dap_continue` and `dap_shutdown`.
- Optional: `{ "name": "read_text_file", "input": { "path": "..." } }` to review the script before or after running.

### 2.4 Execution Control (Stepping & Continue)

| Tool | Description | Usage Notes |
| --- | --- | --- |
| `dap_continue` | Resumes execution. Automatically chooses the last stopped thread if none is provided. | Response includes the thread list and the `threadId` that was resumed. |
| `dap_step_over` | Issues the DAP `next` command for the active thread. | Selects the same thread heuristic as `dap_continue`. |
| `dap_step_in` | Issues the DAP `stepIn` request. | Adapter may reject if the current frame cannot step further. |
| `dap_step_out` | Issues the DAP `stepOut` request. | Adapter may reject if already at the top frame. |

**Typical phase**: Use after `dap_launch` when the program is paused at a breakpoint. Combine with locals inspection to reason about state changes.

### 2.5 State Inspection

| Tool | Description | Usage Notes |
| --- | --- | --- |
| `dap_locals` | Fetches threads, stack trace, scopes, and variables for the most recent paused frame. Prefers the thread/frame from the cached `stopped` event. | Returns `selectedThreadId`, `selectedFrameId`, and raw variable payloads. |
| `dap_last_stopped_event` | Surfaces the cached `stopped` event and current breakpoint registry for quick context in multi-turn conversations. | Useful when resuming from a previous conversation turn or when you need to rehydrate context without re-issuing wait calls. |

### 2.6 Event Handling & Session Lifecycle

| Tool | Description | Usage Notes |
| --- | --- | --- |
| `dap_wait_for_event` | Blocks (with timeout) for a named adapter event such as `stopped`, `continued`, or `terminated`. Updates the cached stopped event when applicable. | Use to synchronize on asynchronous adapter activity, e.g., when resuming a program that will pause later. |
| `dap_shutdown` | Gracefully closes the shared stdio adapter session. | Always call when a debugging session is finished to release the background process. |

---

## 3. Suggested Workflow for Agents

1. **Gather failing evidence**
   - `run_tests_json` → analyze the JSON report for failing tests, stack traces, and captured output.
2. **Plan breakpoint strategy**
   - `dap_set_breakpoints` targeting lines identified from the failure report.
   - Optional: `dap_list_breakpoints` to confirm current configuration.
3. **Launch and pause**
   - `dap_launch` with `wait_for_breakpoint=true` to pause immediately.
4. **Inspect state**
   - `dap_locals` and `dap_last_stopped_event` to inspect variables and thread/frame context.
5. **Control execution**
   - Use stepping tools (`dap_step_over`, `dap_step_in`, `dap_step_out`) or `dap_continue` to advance the program, interleaving with additional locals inspection as needed.
   - `dap_wait_for_event` if you expect another pause (for example, due to an exception breakpoint).
6. **Wrap up**
   - `dap_shutdown` after conclusions are drawn.
   - Re-run `run_tests_json` or `run_tests_focus` to confirm behaviour after applying a fix.

---

## 4. Troubleshooting

- **Adapter never reports `initialized`**: The MCP server automatically retries breakpoint requests once the event arrives, but if the adapter is unresponsive double-check that `program` and `cwd` are valid paths.
- **`Program path does not exist`**: The launch helper could not locate the requested script. Use repo-relative paths (e.g., `src/sample_app/app.py`) or provide an absolute path inside the repository. The response includes candidate matches to help pick the right file.
- **Stepping commands fail**: The adapter may reject step-in/out if execution is already at the boundary of a function. Inspect the returned `result` payload for additional context.
- **No threads returned**: Ensure the target script is still running; if it terminated, launch again with fresh breakpoints.
- **Need raw DAP insight**: Run `python src/dap_stdio_direct.py` to observe the request/response sequence without MCP orchestration.

---

## 5. Additional References

- `README.md` – project overview and environment setup instructions.
- `docs/testing.md` – commands for running individual pytest suites.
- `STATUS.md` / `FINAL_REPORT.md` – snapshot of current capabilities and intentional xfails.

For any client-specific quirks (e.g., custom MCP shells), adapt the configuration snippets above but keep the same command/argument contract. Remember that MCP clients own the server lifecycle; leave `python src/mcp_server.py` to them.

## How to debug the included examples

This repository includes small example programs you can use to practice attaching the MCP/debugger, setting breakpoints, inspecting locals, and stepping. Below are three quick ways to reproduce the sessions demonstrated in this guide.

### 1. Debug using an MCP-capable client (recommended)

Ensure the project's virtual environment is activated and your MCP client is configured (see section 1.1). You can also run `scripts/configure_mcp_clients.py` to generate client snippets.

Open the example file in your editor and set breakpoints (click the gutter or use your client's UI). Recommended breakpoints used in the examples in this repo:

```text
examples/demo_program/demo_program.py         -> breakpoint: calculate_average (division line, repo line 4)
examples/async_worker/worker.py               -> breakpoints: _run_job (line 20), gather_results (line 27)
examples/gui_counter/run_counter_debug.py     -> breakpoint: line 8 (main runner)
examples/gui_counter/counter.py               -> breakpoint: line 16 (increment method in imported module)
```

For the gui_counter example, you can use `breakpoints_by_source` to set breakpoints in both the runner and the imported counter module simultaneously.

Start the MCP debug session from your client (or call the server tools that issue `dap_launch` with `wait_for_breakpoint=true`). When the adapter pauses you can inspect locals either in the editor's Variables view or by calling the MCP tools such as `dap_locals` / `dap_last_stopped_event`.

### 2. Quick attach with debugpy (no MCP client)

If you want a minimal local flow without configuring an MCP client, tell debugpy to wait for a debugger and then attach from VS Code or another debugger that supports the debugpy protocol:

```bash
# macOS zsh (from repo root)
source .venv/bin/activate
.venv/bin/python -m debugpy --listen 5678 --wait-for-client examples/demo_program/demo_program.py
```

Then open an "Attach" configuration in VS Code (host 127.0.0.1, port 5678) and attach. Set the same breakpoints listed above and step/inspect as normal.

### 3. Direct adapter walkthrough (low-level DAP visibility)

Use the repository's `src/dap_stdio_direct.py` script to see a direct stdio-based DAP walkthrough. By default it targets `sample_app/app.py`; edit the `APP` constant at the top of the script to point at a different example or create a tiny wrapper that sets the desired program path.

```bash
# Run direct DAP walkthrough (sample_app/app.py by default)
source .venv/bin/activate
.venv/bin/python src/dap_stdio_direct.py
```

### Notes and tips

- If you prefer reproducing the sessions I ran earlier in this conversation, use the exact breakpoint lines called out above.
- When debugging async code, you will often see coroutine objects in locals before they run (for example `tasks = [<coroutine object _run_job ...>, ...]`). Step into a coroutine to inspect its per-call locals (e.g. `job`).
- After applying a fix, re-run `run_tests_json` or `run_tests_focus` to validate the behavior under CI-like conditions.
