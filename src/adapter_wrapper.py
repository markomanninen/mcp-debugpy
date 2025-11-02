"""Wrapper for debugpy.adapter that sets DEBUGPY_ADAPTER_ENDPOINTS via sys args.

This works around a Windows asyncio subprocess env var inheritance bug where
asyncio.create_subprocess_exec(env=env) doesn't pass environment variables
correctly when called from an MCP server context.
"""

import os
import sys

if __name__ == "__main__":
    # First arg is the endpoint file path
    if len(sys.argv) > 1:
        endpoint_file = sys.argv[1]
        os.environ["DEBUGPY_ADAPTER_ENDPOINTS"] = endpoint_file
        # Remove our custom arg so debugpy.adapter gets clean args
        sys.argv.pop(1)

    # Now launch debugpy.adapter with remaining args
    from debugpy.adapter.__main__ import main

    main()
