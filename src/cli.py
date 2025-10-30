"""Console wrapper for running the MCP server as an installed script.

This module exposes a `main()` function that re-uses the existing server
startup path from `src/mcp_server.py`. It intentionally keeps behavior
minimal and relies on the server's help guard to print usage when
`--help` is requested.
"""

import sys
from pathlib import Path

# Importing the module will register the MCP tools; use the server's
# own entry behavior when run as a script.
try:
    # Adjust sys.path to ensure `src` is importable when installed in editable mode
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root / "src") not in sys.path:
        sys.path.insert(0, str(project_root / "src"))
    import mcp_server as server
except Exception:
    # Fall back to relative import if the above failed (development installs)
    try:
        from . import mcp_server as server
    except Exception:
        import mcp_server as server


def main(argv=None):
    """Run the MCP server using the same behavior as `python src/mcp_server.py`.

    The mcp server module handles `--help` internally; here we just pass
    through the CLI arguments and call into the same startup logic.
    """
    if argv is None:
        argv = sys.argv[1:]
    # Delegate to the mcp_server module's main logic if available
    if hasattr(server, 'print_help') and ('--help' in argv or '-h' in argv):
        server.print_help()
        return 0
    # Start the MCP event loop; the module's __main__ behavior uses mcp.run()
    try:
        # Call mcp.run() if exposed (normal startup path)
        if hasattr(server, 'mcp') and hasattr(server, 'mcp'):
            server.mcp.run()
            return 0
    except SystemExit:
        raise
    except Exception as exc:
        print(f"Error starting MCP server: {exc}")
        return 2
    # Fallback: call module-level main if present
    if hasattr(server, 'main'):
        try:
            return server.main(argv)
        except SystemExit:
            raise
        except Exception as exc:
            print(f"Error running server main: {exc}")
            return 2
    print("Unable to start MCP server: entrypoint not found")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
