# GUI Counter Example

Tkinter desktop widget that exercises the stdio DAP tooling with a stateful GUI.

# GUI Counter Example

A small Tkinter demo that exercises the MCP/stdio DAP tooling and demonstrates debugging an imported module.

Quick steps

1. Run the unit tests (the suite includes an xfail highlighting the intentionally buggy `decrement`):

```bash
python -m pytest -q examples/gui_counter/tests
```

2. Launch the runner under the MCP server using `dap_launch` (example payload):

```json
{
  "name": "dap_launch",
  "input": {
    "program": "examples/gui_counter/run_counter_debug.py",
    "cwd": "examples/gui_counter",
    "breakpoints": [24],
    "breakpoints_by_source": { "examples/gui_counter/counter.py": [10, 14] },
    "wait_for_breakpoint": true
  }
}
```

Notes on breakpoints and why this example is useful

- The runner (`run_counter_debug.py`) creates a `CounterModel` and immediately exercises `increment`, `decrement`, and `reset` while printing the results. Because the demo is short-lived the example is useful to confirm the MCP server's breakpoint registration semantics.
- The MCP server implements a resilient, three-phase breakpoint registration strategy:

  1. initial attempt (before `configurationDone`) — may fail if the adapter isn't ready
  2. retry-after-init (after the adapter reports `initialized`) — applies to both main-program breakpoints and `breakpoints_by_source` entries
  3. retry-after-stop (after the first `stopped` event) — a final attempt, primarily important for imported-module breakpoints that may be set before the module is loaded

In this example we set breakpoints both in the runner and in `counter.py` so you can observe these behaviors in action.

When the decrement breakpoint hits, inspect `self.value` to observe the incorrect arithmetic (the demo intentionally uses `self.value += 1` inside `decrement`).

3. Continue execution (`dap_continue`) to let the program finish and review the printed output. After fixing the bug, re-run the tests and remove the xfail.

Quick local run without MCP client

```bash
python3 examples/gui_counter/run_counter_debug.py
```

You should see something like:

```text
initial 0
inc -> 1
dec -> 2   # wrong — decrement should reduce the value
reset -> 0
final 0
```

If you'd like, I can apply a minimal fix to `examples/gui_counter/counter.py` or add a unit test that prevents this regression.
