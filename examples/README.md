# Example Scenarios

These self-contained projects illustrate how to apply the MCP + DAP tooling to real-world Python workflows.

| Example | Highlights | Try This |
| ------- | ---------- | -------- |
| `examples/math_bug` | Simple arithmetic module with an intentionally broken `subtract` implementation. Shows the classic “unit test fails, set breakpoint, inspect locals” loop. | Run `pytest -q examples/math_bug/tests` (xfail marks signal known bug). Launch under the MCP server with `dap_launch({"program": "examples/math_bug/calculator.py", "breakpoints": [33]})` and inspect variables with `dap_locals`. |
| `examples/async_worker` | Asynchronous job dispatcher that mishandles task cancellation. Demonstrates debugging across async call stacks. | Run `pytest -q examples/async_worker/tests` and inspect the xfailed test output. Use `dap_launch` to stop on `worker.py` and walk the awaited coroutines. |
| `examples/gui_counter` | Tkinter desktop counter that updates the wrong value when decrementing. Useful for GUI breakpoints and state inspection. | Run `pytest -q examples/gui_counter/tests`, then launch with `dap_launch({"program": "examples/gui_counter/app.py", "breakpoints": [27]})` and trigger GUI buttons while inspecting locals. |
| `examples/web_flask` | Flask REST endpoint misreporting totals thanks to flawed business logic. Perfect for debugging request handlers. | Run `pytest -q examples/web_flask/tests`, launch with `dap_launch({"program": "examples/web_flask/app.py", "breakpoints": [19]})`, then hit `http://127.0.0.1:5001/total` in another terminal. |

Each example has its own README with debugging suggestions and breakpoint locations.

> ℹ️ Both projects ship with `pytest.mark.xfail` tests—run them to see the failure signatures without breaking CI. Fix the bug and the xfail will flip to a surprise pass, reminding you to remove the marker.
