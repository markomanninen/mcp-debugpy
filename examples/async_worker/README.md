# Async Worker Example

Asynchronous job dispatcher that forgets to await `asyncio.gather`. Ideal for stepping through coroutines and inspecting tasks.

1. Run the async tests:
   ```bash
   python -m pytest -q examples/async_worker/tests
   ```
   The first test asserts the current failure (`TypeError`), while the second is marked `xfail` to highlight the desired behaviour.

2. Launch with the MCP tool:
   ```json
   {
     "name": "dap_launch",
     "input": {
       "program": "examples/async_worker/worker.py",
       "breakpoints": [24],
       "wait_for_breakpoint": true
     }
   }
   ```
   When execution stops at `gather_results`, examine `tasks` and `results` via `dap_locals`.

3. After fixing the missing `await`, re-run the tests—`test_gather_results_success` should now pass, prompting you to drop the `xfail`.
