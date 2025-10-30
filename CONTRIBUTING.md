# Contributing

Thanks for checking out the MVP Agent Debug project! The goal is to keep a clear, reproducible showcase of the stdio-based DAP flow combined with MCP tooling.

## Getting Started

1. Clone the repo and create a virtual environment (or run `./setup.sh`).
2. Activate the venv: `source .venv/bin/activate`.
3. Install dependencies if skipping the script:
   ```bash
   pip install -r requirements.txt -r requirements-dev.txt
   ```

## Running Tests

Run the targeted suite before committing changes:

```bash
python -m pytest tests/test_mcp_server.py
```

The example suites can be exercised as well (all contain intentional `xfail`s):

```bash
python -m pytest examples/math_bug/tests -q
python -m pytest examples/async_worker/tests -q
python -m pytest examples/gui_counter/tests -q
python -m pytest examples/web_flask/tests -q
```

Refer to `docs/testing.md` for more detail.

## Code Style

- Keep imports sorted and prefer standard library solutions.
- Add concise docstrings or comments only when behaviour is non-obvious.
- Stick to ASCII unless working in a file that already uses Unicode characters.

## Pull Requests

- Describe the motivation for the change and how you tested it.
- Mention any follow-up work or caveats.
- Ensure `setup.sh` still runs cleanly.

Thanks for helping improve the project!
