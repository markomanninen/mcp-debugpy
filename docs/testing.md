# Testing Guide

This document summarizes every automated test suite included in the repository and how to run them.

## Table of Contents

1. [Environment Setup](#environment-setup)
2. [Core Functional Tests](#core-functional-tests)
   - [MCP server unit tests](#mcp-server-unit-tests)
   - [Sample app tests](#sample-app-tests)
3. [Example Project Suites](#example-project-suites)
   - [Math bug (synchronous)](#math-bug-synchronous)
   - [Async worker](#async-worker)
   - [Tkinter GUI counter](#tkinter-gui-counter)
   - [Flask web endpoint](#flask-web-endpoint)
4. [Running Everything at Once](#running-everything-at-once)
5. [Understanding xfail Marks](#understanding-xfail-marks)
6. [Using MCP + DAP for Manual Validation](#using-mcp--dap-for-manual-validation)
7. [IDE / Agent Compatibility](#ide--agent-compatibility)

---

## Environment Setup

```bash
./setup.sh            # creates .venv and installs dependencies
source .venv/bin/activate
```

Optional extras:
- `pip install -r requirements.txt` installs runtime dependencies (MCP, debugpy, Flask).
- `pip install -r requirements-dev.txt` installs pytest-related tooling if you skip `setup.sh`.
- GUI demo (`examples/gui_counter`) relies on Tkinter; macOS/Linux ship it by default. On Windows, ensure the Python build includes Tk support.

## Core Functional Tests

### MCP server unit tests

These use a fake `StdioDAPClient` to validate launch retry logic, breakpoint retries, locals inspection, and graceful shutdown.

```bash
python -m pytest tests/test_mcp_server.py
```

Expected: all 4 tests pass.

### Sample app tests

The original `src/sample_app` contains intentional bugs. The tests live under `src/sample_app/tests` and fail until you fix them.

```bash
python -m pytest src/sample_app/tests -q
```

Expected: 2 failures (documented in `STATUS.md`).

## Example Project Suites

Each example has its own README with debugging instructions. The tests are designed to highlight the bug with `xfail` markers so the suite reports green while still capturing the regression.

### Math bug (synchronous)

```bash
python -m pytest examples/math_bug/tests -q
```

Expected: 2 passes, 2 xfails. Use `dap_launch` on `examples/math_bug/calculator.py` line 33 to inspect the incorrect subtraction.

### Async worker

```bash
python -m pytest examples/async_worker/tests -q
```

Expected: 1 pass, 1 xfail. Launch `examples/async_worker/worker.py` and stop at `gather_results` to inspect the missing `await`.

### Tkinter GUI counter

```bash
python -m pytest examples/gui_counter/tests -q
```

Expected: 1 pass, 1 xfail. Launch the GUI app and break on `CounterModel.decrement`.

### Flask web endpoint

```bash
python -m pytest examples/web_flask/tests -q
```

Expected: 1 pass, 1 xfail. Launch `examples/web_flask/app.py`, inspect `total_cost`, and curl `http://127.0.0.1:5001/total`.

## Running Everything at Once

```bash
python -m pytest tests/test_mcp_server.py \
    examples/math_bug/tests \
    examples/async_worker/tests \
    examples/gui_counter/tests \
    examples/web_flask/tests
```

This aggregates the “green except for documented xfails” view.

## Understanding xfail Marks

- `pytest.mark.xfail(strict=True)` treats an accidental pass as a failure, reminding you to remove the marker after fixing the bug.
- Use `-rxX` (e.g., `pytest -rxXs`) to see the xfail reasons in the pytest summary.

## Using MCP + DAP for Manual Validation

1. Configure your MCP client:
   - Run `python scripts/configure_mcp_clients.py` to detect existing entries and interactively add/update/remove the `agentDebug` server. The script also writes (or removes) a Claude Desktop snippet under `scripts/`.
   - **VS Code** – ensure an entry exists under `mcp.servers` that points to `python src/mcp_server.py` inside the repo’s virtualenv.
   - **Claude Desktop** – add the generated snippet (or equivalent settings) via *Settings → Model Context Protocol*.
   - **CLI/manual (protocol development only)** – if you are building a custom MCP client, you may activate the venv and run `python src/mcp_server.py` to expose the stdin/stdout endpoint.
2. From your MCP-aware client, call:
   - `dap_launch` with the relevant example (see per-example README for breakpoints).
   - `dap_locals`, `dap_continue`, `dap_wait_for_event`, `dap_shutdown` to orchestrate execution.
   - `run_tests_json` or `run_tests_focus` for pytest flows.

For manual debugging without MCP, run `python src/dap_stdio_direct.py` to see the stdio launch flow.

## IDE / Agent Compatibility

- **VS Code:** Supports MCP via the open tooling (see Claude MCP instructions) and natively handles DAP, so integrating the stdio client is straightforward.
- **Claude Desktop / Claude API:** Claude 3.5 can connect to MCP servers; configure it per the snippets above so it launches `python src/mcp_server.py` on demand.
- **OpenAI Codex / GPT-4o:** No MCP support as of Jan 2025. They can run CLI commands but lack a native MCP interface.
- **Gemini CLI:** Gemini Advanced exposes API keys but doesn’t speak MCP directly; you’d need a translation layer.

In short, today’s production-ready MCP consumers are VS Code (with MCP extensions), Claude Desktop, and compatible shells like [mcp-shell](https://github.com/modelcontextprotocol/clients). Others require custom integration.
