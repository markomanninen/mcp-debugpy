# Math Bug Example

Small arithmetic module with an intentional defect in `subtract`. Use it to practice the MCP/DAP workflow:

1. Run the tests:
   ```bash
   python -m pytest -q examples/math_bug/tests
   ```
   The suite contains `xfail` markers so CI stays green while still signalling the bug.

2. Launch under the MCP server:
   ```json
   {
     "name": "dap_launch",
     "input": {
       "program": "examples/math_bug/calculator.py",
       "breakpoints": [33],
       "wait_for_breakpoint": true
     }
   }
   ```
   Breakpoint line 33 captures the incorrect discount calculation.

3. Use `dap_locals` to inspect variables (`subtotal`, `tax`, `discounted`), then resume with `dap_continue`.

4. Fix `subtract` and remove the `xfail` markers to confirm the loop.
