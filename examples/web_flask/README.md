# Flask Web Example

REST endpoint whose business logic miscomputes totals—ideal for stepping through server code while issuing HTTP requests.

## Debugging the Flask App

1. Install the requirements (`pip install -r requirements.txt`) and run the tests:
   ```bash
   python -m pytest -q examples/web_flask/tests
   ```
   The `xfail` test documents the incorrect result coming from `total_cost`.

2. Launch the Flask app under debugger control via MCP:
   ```json
   {
     "name": "dap_launch",
     "input": {
       "program": "run_flask.py",
       "cwd": ".",
       "breakpoints_by_source": {
         "examples/web_flask/inventory.py": [18]
       },
       "wait_for_breakpoint": false
     }
   }
   ```
   This launches Flask under the debugger and sets a breakpoint at line 18 in `inventory.py` (the buggy line).

3. In another shell, trigger the breakpoint by making an HTTP request:
   ```bash
   curl http://127.0.0.1:5001/total
   ```

4. Wait for the stopped event in MCP:
   ```json
   {
     "name": "dap_wait_for_event",
     "input": {
       "name": "stopped",
       "timeout": 10
     }
   }
   ```

5. Once stopped at the breakpoint, inspect the variables:
   ```json
   {
     "name": "dap_locals"
   }
   ```
   You'll see `item.price=9.99` and `item.quantity=3`. The bug is on line 18: `total += item.price + item.quantity` should be `total += item.price * item.quantity`.

6. Resume execution to complete the HTTP request:
   ```json
   {
     "name": "dap_continue"
   }
   ```

7. Clean up when done:
   ```json
   {
     "name": "dap_shutdown"
   }
   ```

8. Fix `total_cost` in `inventory.py`, rerun the tests, and remove the `xfail` once the result matches expectations.

## How it Works

- **Launcher script**: `run_flask.py` at the project root imports the Flask app as a module to avoid relative import issues
- **Debugger control**: `dap_launch` starts Flask under debugger control, allowing breakpoints to be hit on HTTP requests
- **Breakpoints in modules**: Use `breakpoints_by_source` to set breakpoints in `inventory.py` (not the main program file)
- **HTTP trigger**: Making HTTP requests to the Flask app triggers breakpoints, allowing you to debug request handlers interactively
