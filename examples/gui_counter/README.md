# GUI Counter Example

Tkinter desktop widget that exercises the stdio DAP tooling with a stateful GUI.

1. Run the unit tests:
   ```bash
   python -m pytest -q examples/gui_counter/tests
   ```
   The failing `xfail` highlights the buggy `decrement` implementation.

2. Launch the GUI under the MCP server:
   ```json
   {
     "name": "dap_launch",
     "input": {
       "program": "examples/gui_counter/app.py",
       "breakpoints": [27],
       "wait_for_breakpoint": true
     }
   }
   ```
   When the breakpoint hits `CounterModel.decrement`, inspect `self.value` to see the wrong arithmetic before it updates the label.

3. Continue execution (`dap_continue`) to watch the GUI refresh, then fix the bug and remove the `xfail` once the tests pass.
