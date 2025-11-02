# Flaky Flask debugging tests — investigation notes

This document records the failing pattern and provides a small runner that reproduces the flakiness and captures diagnostics for triage.

Symptoms
- When running the end-to-end Flask debugging tests, the test often passes on one run and fails on the next. The typical failure is a ConnectionResetError when the client tries to send the initial `initialize` DAP request: the adapter process has closed the connection or exited early. The adapter stderr often shows a debugpy internal exception `debugpy.common.messaging.NoMoreMessages`.

Likely causes
- Adapter exits before the DAP initialize handshake completes (debuggee finished early).
- Adapter internal messaging error causing it to terminate.
- Stale endpoint JSON files in `~/.debugpy` causing the client to pick an endpoint that is not listening.

Diagnostic approach taken
- Added a diagnostic helper script `scripts/diag_start_adapter.py` that starts the `StdioDAPClient` and prints which endpoints file the wrapper printed, the adapter PID/returncode and a tail of `stderr` gathered by the client.
- Created `scripts/run_flaky_tests.py` to repeatedly run selected pytest node ids until the first failure while capturing:
  - pytest stdout/stderr into timestamped logs
  - `~/.debugpy/debugpy-endpoints-*.json` contents and mtimes
  - `ps -ef` output filtered for debugpy/debugger processes
  - run of `scripts/diag_start_adapter.py` when useful

How to use

From the repository root, using the repo venv Python (adjust as needed):

```bash
# Example: run the single problematic test repeatedly until it fails
PYTHONPATH=.:src:$PYTHONPATH \
  ./.venv/bin/python scripts/run_flaky_tests.py \
    --nodeids tests/test_web_app_debug.py::test_flask_app_debugging_with_http_breakpoint \
    --outdir flake-logs
```

The script will stop on the first failing iteration. Inspect the produced `flake-logs/<timestamp>/` directory for:
- `pytest.log` — the full pytest subprocess output
- `endpoints/` — all `~/.debugpy` endpoint JSON files captured at the time of failure
- `ps.log` — process list snapshot
- `diag_start_adapter.log` — output from `scripts/diag_start_adapter.py` (if run)

Next steps
- Run the flake reproduction and attach the produced `flake-logs/<timestamp>/` folder. Based on the adapter stderr and endpoint files we can decide on a minimal fix:
  - prefer deterministic wrapper handshake (emit READY after adapter listening), or
  - ensure tests use `stop_on_entry=True` when appropriate, or
  - work around debugpy internal error (upgrade/downgrade or change startup pattern).
