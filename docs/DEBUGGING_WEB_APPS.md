# Debugging Web Applications with dap_launch

This document explains the **correct and only** way to debug web applications (Flask, Django, FastAPI, etc.) using this MCP debugging server.

## TL;DR

**Use `dap_launch` for ALL debugging, including web apps.** The `dap_attach` approach does not work with debugpy.

## How to Debug Web Apps

### 1. Create a Launcher Script

Create a script like `run_flask.py` that imports your web app as a module:

```python
from examples.web_flask import app

if __name__ == "__main__":
    app.main()
```

This avoids relative import issues when the debugger launches your app.

### 2. Launch with dap_launch

Use the MCP `dap_launch` tool to start your web app under debugger control:

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

**Key points:**

- Use `breakpoints_by_source` to set breakpoints in your business logic files
- Set `wait_for_breakpoint=false` since you'll trigger breakpoints via HTTP requests
- The debugger starts and controls the Flask/Django/FastAPI process

### 3. Trigger Breakpoints via HTTP

Make HTTP requests to your app to trigger breakpoints:

```bash
curl http://127.0.0.1:5001/total
```

### 4. Wait for Stopped Event

```json
{
  "name": "dap_wait_for_event",
  "input": {
    "name": "stopped",
    "timeout": 10
  }
}
```

### 5. Inspect and Debug

```json
{"name": "dap_locals"}
{"name": "dap_step_over"}
{"name": "dap_continue"}
```

### 6. Clean Up

```json
{"name": "dap_shutdown"}
```

## Why Not dap_attach?

The `dap_attach` approach was thoroughly investigated but **does not work with debugpy**.

### What We Found

When you run:

```bash
python -m debugpy --listen 5678 -m your.app
```

And then try to connect to it directly:

1. ✅ `initialize` request works and gets a response
2. ❌ `attach` request sent but **debugpy never responds**
3. ❌ Connection times out

### Why It Fails

- **debugpy is not a full DAP server** when started with `--listen`
- It's designed for IDE integration (VS Code), not pure DAP attach scenarios
- The adapter (`debugpy.adapter`) doesn't support `--connect-to` flag
- Direct TCP connection to debugpy doesn't follow standard DAP protocol for attach

### What We Tried

1. **DirectDAPClient**: Created a TCP client to connect directly to debugpy
   - Result: debugpy doesn't respond to attach requests

2. **StdioDAPClient with --connect-to**: Modified to launch adapter with connection flag
   - Result: `debugpy.adapter` doesn't support `--connect-to` flag

3. **Multiple debugpy command variations**: Tested different flags and modes
   - Result: All failed with the same issue - no response to attach requests

### Conclusion

**debugpy fundamentally does not support the DAP attach workflow for already-running processes.** This is not a bug in our implementation - it's how debugpy works.

## The Solution: dap_launch for Everything

`dap_launch` works perfectly for all scenarios:

- ✅ **Regular scripts**: Debugger starts and stops with the script
- ✅ **Web servers**: Debugger starts Flask/Django/FastAPI and keeps it alive
- ✅ **Long-running processes**: Debugger controls the entire lifecycle
- ✅ **Breakpoints on HTTP requests**: Set breakpoints, trigger via curl/browser
- ✅ **Module imports**: Use `breakpoints_by_source` for any file

## Example: Complete Flask Debugging Session

```json
// 1. Launch Flask under debugger
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

// 2. Trigger breakpoint (in bash)
// curl http://127.0.0.1:5001/total

// 3. Wait for stopped event
{
  "name": "dap_wait_for_event",
  "input": {
    "name": "stopped",
    "timeout": 10
  }
}

// 4. Inspect variables
{
  "name": "dap_locals"
}

// 5. Continue execution
{
  "name": "dap_continue"
}

// 6. Shutdown
{
  "name": "dap_shutdown"
}
```

## References

- [agent_instructions.md](agent_instructions.md) - Complete MCP tool documentation
- [docs/mcp_usage.md](docs/mcp_usage.md) - Detailed usage guide
- [examples/web_flask/README.md](examples/web_flask/README.md) - Flask example walkthrough
