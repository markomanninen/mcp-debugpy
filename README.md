# MVP: Agent-steerable test & debug loop (MCP + DAP + pytest)

[![CI](https://github.com/markomanninen/mcp-debugpy/actions/workflows/ci.yml/badge.svg)](https://github.com/markomanninen/mcp-debugpy/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/markomanninen/mcp-debugpy?label=release&sort=semver)](https://github.com/markomanninen/mcp-debugpy/releases)

This minimal project shows how an agent could drive your Python test/debug loop:

- **pytest JSON** reports for machine-readable failures
- **DAP (Debug Adapter Protocol)** control of a live `debugpy` session (breakpoints, continue, variables)
- **MCP server** exposing tools: run tests, read JSON, and send DAP commands

## Quick start

```bash
git clone <this-folder>
cd mvp-agent-debug
./setup.sh

# In a new terminal, activate the venv and run demos/tests as needed:
source .venv/bin/activate
python src/dap_stdio_direct.py        # direct adapter walkthrough (waits for breakpoint)
python -m pytest tests/test_mcp_server.py  # verify MCP tooling via fakes
```

Install (from source):

```bash
python -m pip install -e '.[dev]'
```

**IMPORTANT:** Install git hooks to run CI checks before every commit:

```bash
./scripts/install-hooks.sh
```

This prevents CI failures by automatically running ruff, black, mypy, and pytest before allowing commits.

Run the CLI after activating the project virtualenv:

```bash
mcp-debug-server --help
```

Then register the MCP server with VS Code and/or Claude so they can launch it automatically:

```bash
python scripts/configure_mcp_clients.py
```

Open your MCP-aware chat surface and invoke tools like `run_tests_json` or `dap_launch` (see [`docs/mcp_usage.md`](docs/mcp_usage.md) for a full walkthrough).

The sample app intentionally contains a bug to demonstrate failing tests and an interactive breakpoint.

### Optional helper

Run `python scripts/configure_mcp_clients.py` to detect existing VS Code/Claude MCP entries, interactively add/update/remove them, and generate a Claude snippet. Works on macOS, Linux, and Windows.

## Developer tooling

This repository uses pre-commit hooks and CI for linting, formatting, and typing checks.

Install hooks locally:

```bash
source .venv/bin/activate
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

If you prefer to run hooks manually, the CI runs `ruff`, `black --check`, and `mypy` before `pytest`.

📘 For a step-by-step walkthrough of every MCP tool (including suggested agent workflows for VS Code and Claude), see [`docs/mcp_usage.md`](docs/mcp_usage.md).

## Using the MCP tooling

**IMPORTANT**: MCP servers are automatically managed by MCP clients. You do NOT need to manually start this server from the command line. Instead, configure it in your MCP client (VS Code or Claude Desktop) and it will automatically start when needed.

### Configuration

#### VS Code

Add to your `settings.json`:

```json
{
  "mcp.servers.agentDebug": {
    "command": "/path/to/your/project/.venv/bin/python",
    "args": ["src/mcp_server.py"],
    "cwd": "/path/to/your/project",
    "env": {
      "PYTHONPATH": "/path/to/your/project/src"
    }
  }
}
```

#### Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "agentDebug": {
      "command": "/path/to/your/project/.venv/bin/python",
      "args": ["src/mcp_server.py"],
      "cwd": "/path/to/your/project",
      "env": {
        "PYTHONPATH": "/path/to/your/project/src"
      }
    }
  }
}
```

### Manual Testing (Protocol Development Only)

In normal usage you should never run `python src/mcp_server.py` yourself—MCP clients spawn and manage the process automatically. The notes below are only for developers building custom MCP clients or experimenting with raw protocol traffic.

#### Step 1 – Register the server with your MCP client

- **VS Code (AI Chat + MCP extension)** — run the helper script (supports add/update/remove) or add the entry manually.

  ```bash
  # Optional helper that updates VS Code settings and writes a Claude snippet
  python scripts/configure_mcp_clients.py
  ```

  If configuring by hand, add this to `settings.json`:

  ```jsonc
  {
    "mcp.servers.agentDebug": {
      "command": "${workspaceFolder}/.venv/bin/python", // Windows: ".venv\\Scripts\\python.exe"
      "args": ["src/mcp_server.py"],
      "cwd": "${workspaceFolder}"
    }
  }
  ```

  VS Code will spawn and manage the server automatically whenever you open the chat.

- **Claude Desktop** — open *Settings → Model Context Protocol → Add server* and enter (or paste the generated snippet):

  ```text
  Command: /full/path/to/.venv/bin/python
  Arguments: src/mcp_server.py
  Working dir: /full/path/to/mvp-agent-debug
  ```

  Claude starts the process on demand and tears it down when idle.

- **Manual / CLI usage (protocol debugging only)** — launching `python src/mcp_server.py` directly will block your terminal waiting for MCP-framed JSON messages. Do this only if you are writing a custom MCP client and need a raw stdin/stdout endpoint.

#### Step 2 – Launch the sample app under debugpy

- Example tool request:

  ```json
  {
    "name": "dap_launch",
    "input": {
      "program": "src/sample_app/app.py",
      "cwd": ".",
      "breakpoints": [8],
      "wait_for_breakpoint": true
    }
  }
  ```

The response includes the initialize/launch payloads plus an eventual `stoppedEvent` once line 8 is hit. If you prefer to skip the terminal noise, remove or keep the `[dap:event] …` debug prints in `src/dap_stdio_client.py`—they are purely diagnostic.

#### Step 3 – Inspect and resume

- Call `dap_locals` to fetch the threads, stack frames, scopes, and locals.
- Use `dap_continue` (optionally with a specific `thread_id`) to resume execution.
- Call `dap_shutdown` when you are finished; it tears down the adapter process cleanly.

#### Step 4 – Run tests via MCP

- Example tool request:

  ```json
  { "name": "run_tests_json" }
  ```

Or focus on a subset with `run_tests_focus`.

## Repository layout

- `src/sample_app/app.py` – tiny app with a bug (drives sample failure)
- `src/sample_app/tests/test_app.py` – pytest suite covering the bug
- `src/dap_stdio_client.py` – stdio client talking to `debugpy.adapter`, handling reverse requests
- `src/dap_stdio_direct.py` – direct adapter walkthrough (initialize → breakpoints → configurationDone → launch → stepping)
- `src/mcp_server.py` – stdio MCP surface combining pytest helpers and DAP launch/inspect tools
- `tests/test_mcp_server.py` – unit tests that fake the adapter to verify retries and control flow
- `examples/` – additional mini-projects with xfailed tests and detailed READMEs
  - `examples/math_bug` – arithmetic bug demo
  - `examples/async_worker` – async gather bug demo
  - `examples/gui_counter` – Tkinter counter UI showcasing GUI debugging
  - `examples/web_flask` – Flask endpoint for server-side walkthroughs
- `docs/testing.md` – consolidated instructions for all automated tests
- `STATUS.md` / `FINAL_REPORT.md` – project snapshot for maintainers

### Requirements

- `requirements.txt` – runtime dependencies (MCP server, debugpy, Flask)
- `requirements-dev.txt` – test-only dependencies (pytest, pytest-asyncio, JSON reporting)

### Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for local setup tips and testing guidance.

### Security

Bind debug servers to `127.0.0.1` and use SSH tunnels for remote hosts.
