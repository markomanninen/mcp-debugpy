# Publishing mcp-debugpy to the MCP Registry

This guide explains how to publish mcp-debugpy to the official MCP Registry.

## Prerequisites

1. **Install MCP Publisher CLI**
   ```bash
   brew install mcp-publisher
   # OR download from: https://github.com/modelcontextprotocol/registry/releases
   ```

2. **Publish to PyPI First**
   The MCP Registry references PyPI packages, so publish there first:
   ```bash
   # Install build tools
   pip install build twine

   # Build distribution
   python -m build

   # Upload to PyPI
   twine upload dist/*
   ```

## Publishing Steps

### Step 1: Initialize server.json

Run the init command in your project root:
```bash
cd /path/to/mcp-debugpy
mcp-publisher init
```

This will auto-generate a `server.json` file with detected values.

### Step 2: Edit server.json

Customize the generated file. Here's the recommended configuration:

```json
{
  "name": "io.github.markomanninen/mcp-debugpy",
  "title": "Agent Debug Tools - Python Debugging with debugpy",
  "description": "MCP server for AI-assisted Python debugging using debugpy and Debug Adapter Protocol. Features breakpoint validation, enhanced error messages, and comprehensive testing tools.",
  "version": "0.2.1",
  "packages": {
    "pypi": {
      "name": "mcp-debugpy",
      "version": ">=0.2.1"
    }
  },
  "runtime": {
    "python": {
      "command": "mcp-debug-server",
      "args": []
    }
  },
  "capabilities": [
    "debugging",
    "testing",
    "breakpoint-validation"
  ],
  "metadata": {
    "author": "markomanninen",
    "homepage": "https://github.com/markomanninen/mcp-debugpy",
    "repository": "https://github.com/markomanninen/mcp-debugpy",
    "license": "MIT",
    "tags": ["debugging", "python", "debugpy", "dap", "testing", "pytest"]
  }
}
```

### Step 3: Add MCP Metadata to README

Add this line to your README.md:
```markdown
<!-- MCP Registry Metadata -->
mcp-name: io.github.markomanninen/mcp-debugpy
```

### Step 4: Authenticate with GitHub

Since we're using the `io.github.markomanninen/*` namespace:
```bash
mcp-publisher auth
```

This will prompt you to login with GitHub OAuth.

### Step 5: Publish to Registry

```bash
mcp-publisher publish
```

The CLI will:
- Validate your server.json
- Verify namespace ownership (GitHub authentication)
- Check that the PyPI package exists
- Publish to the MCP Registry

### Step 6: Verify Publication

Visit the MCP Registry to confirm:
- https://registry.modelcontextprotocol.io
- Search for "mcp-debugpy"

## Usage After Publishing

Users can now install your server easily:

**From MCP Registry:**
```bash
# Clients can discover and install automatically
# Or manually:
pip install mcp-debugpy
```

**Configuration Example:**
```json
{
  "mcpServers": {
    "agentDebug": {
      "command": "mcp-debug-server",
      "args": []
    }
  }
}
```

## Updating the Registry

When you release a new version:

1. Update version in `pyproject.toml`
2. Publish to PyPI
3. Update `version` in `server.json`
4. Run `mcp-publisher publish` again

## Troubleshooting

**Namespace verification failed:**
- Ensure you're logged in as the correct GitHub user
- The username in the namespace must match your GitHub username

**PyPI package not found:**
- Publish to PyPI before the registry
- Wait a few minutes for PyPI to index

**server.json validation errors:**
- Check the schema at: https://github.com/modelcontextprotocol/registry/tree/main/docs/reference

## Resources

- MCP Registry: https://registry.modelcontextprotocol.io
- Publisher Guide: https://github.com/modelcontextprotocol/registry/blob/main/docs/guides/publishing/publish-server.md
- PyPI: https://pypi.org/project/mcp-debugpy/
