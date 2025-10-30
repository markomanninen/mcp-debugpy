
# MCP tool interface

## Available tools

- `run_tests_json(pytest_args?: string[]) -> PytestJson`: runs pytest and returns the JSON report body.
- `run_tests_focus(keyword: string) -> PytestJson`: focused run, equivalent to `pytest -k <keyword>`.
- `dap_launch(program: string, cwd?: string, breakpoints?: number[], console?: string, wait_for_breakpoint?: boolean, breakpoint_timeout?: number)` -> orchestrated launch via `debugpy.adapter` (returns initialize/configuration/launch responses and optional stopped event).
- `dap_set_breakpoints(source_path: string, lines: number[])` -> resilient setBreakpoints (waits for late `initialized` when needed).
- `dap_list_breakpoints()` -> returns the cached breakpoint map so you can confirm what has been registered.
- `dap_continue(thread_id?: number)` -> continues execution (auto-selects first thread if omitted).
- `dap_step_over(thread_id?: number)` / `dap_step_in(thread_id?: number)` / `dap_step_out(thread_id?: number)` -> step controls that reuse the last stopped thread by default.
- `dap_locals()` -> threads, stackTrace, scopes and variables for the current top frame.
- `dap_last_stopped_event()` -> most recent halted event plus cached breakpoints, useful for resuming context in later turns.
- `dap_wait_for_event(name: string, timeout?: number)` -> waits for a specific adapter event (`stopped`, `terminated`, etc.).
- `dap_shutdown()` -> terminates the running adapter session.
- `ensure_demo_program(directory?: string)` -> creates a demo script and returns launch-ready input (program path, cwd, suggested breakpoints).
- `read_text_file(path: string, max_bytes?: number)` -> fetch the contents of a UTF-8 text file so you can inspect code before debugging.

**Transport:** stdio. Use `python scripts/configure_mcp_clients.py` to have the repo update VS Code settings (add/update/remove) and generate a Claude Desktop snippet. Once configured, your MCP client launches `python src/mcp_server.py` automatically.

**Path handling:** `dap_launch` accepts either absolute paths or paths relative to the working directory you provide. If the directory is missing, the server attempts to create it. When the target script is absent, the response includes hints—use the existing sample apps or call `ensure_demo_program(directory=...)` to scaffold one.

**Key workflow reminder:** Start new debugging sessions with a single `dap_launch` call that includes your breakpoint list. The launch helper performs `initialize`, registers breakpoints, issues `configurationDone`, and starts the target. You do **not** need to call `dap_set_breakpoints` beforehand unless you are adjusting breakpoints mid-session.

### Example workflow (pseudo JSON-RPC calls)

1. Configure your MCP client (VS Code, Claude Desktop, etc.) so it references `.venv/bin/python src/mcp_server.py`.
2. Launch the debugger session:

    ```json
    {
       "name": "dap_launch",
       "input": {
          "program": "examples/demo_program/demo_program.py",
          "cwd": "examples/demo_program",
          "breakpoints": [14, 20],
          "wait_for_breakpoint": true
       }
    }
    ```

3. On `stoppedEvent`, inspect state:

   ```json
   { "name": "dap_locals" }
   ```

4. Optional: step or inspect additional context

   ```json
   { "name": "dap_step_over" }
   { "name": "dap_last_stopped_event" }
   { "name": "dap_list_breakpoints" }
   ```

5. Resume execution:

   ```json
   { "name": "dap_continue" }
   ```

6. Tear down the adapter:

   ```json
   { "name": "dap_shutdown" }
   ```

7. At any point, run tests with `{ "name": "run_tests_json" }` or `{ "name": "run_tests_focus", "input": { "keyword": "..." } }`.

If you need a fresh demo script, call `{ "name": "ensure_demo_program", "input": { "directory": "/tmp/debug_demo" } }` (or omit `directory` to use the default location) before launching the debugger. The response includes `launchInput` you can pass straight to `dap_launch`. Use `{ "name": "read_text_file", "input": { "path": "/tmp/debug_demo/demo_program.py" } }` if you want to review the script first.

*Note:* The stdio client prints incoming events as `[dap:event] ...` for debugging. Feel free to keep or remove these prints in `src/dap_stdio_client.py` depending on your logging needs.
