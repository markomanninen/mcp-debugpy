#!/usr/bin/env bash
set -euo pipefail

# Create venv
python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt

echo "=== Smoke-testing MCP tooling and examples ==="
python -m pytest tests/test_mcp_server.py \
    examples/math_bug/tests \
    examples/async_worker/tests \
    examples/gui_counter/tests \
    examples/web_flask/tests || true

cat <<'INSTRUCTIONS'

Next steps:
  source .venv/bin/activate
  python scripts/configure_mcp_clients.py  # register VS Code / Claude MCP entries
  # ...or follow docs/mcp_usage.md for manual configuration details
  python src/dap_stdio_direct.py           # optional direct adapter walkthrough
  # After configuration, use your MCP chat to call run_tests_json, dap_launch, etc.

Each example README (examples/*/README.md) shows how to launch via dap_launch.
INSTRUCTIONS
