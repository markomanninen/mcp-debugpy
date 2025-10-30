# Flask Web Example

REST endpoint whose business logic miscomputes totals—ideal for stepping through server code while issuing HTTP requests.

1. Install the requirements (`pip install -r requirements.txt`) and run the tests:
   ```bash
   python -m pytest -q examples/web_flask/tests
   ```
   The `xfail` test documents the incorrect result coming from `total_cost`.

2. Launch the app via MCP:
   ```json
   {
     "name": "dap_launch",
     "input": {
       "program": "examples/web_flask/app.py",
       "cwd": ".",
       "breakpoints": [19],
       "wait_for_breakpoint": true
     }
   }
   ```
   Once the breakpoint hits inside `total_cost`, use `dap_locals` to inspect `item.price` and `item.quantity`.

3. In another shell, exercise the endpoint:
   ```bash
   curl http://127.0.0.1:5001/total
   ```
   Resume (`dap_continue`) after checking locals.

4. Fix `total_cost`, rerun the tests, and remove the `xfail` once the result matches expectations.
