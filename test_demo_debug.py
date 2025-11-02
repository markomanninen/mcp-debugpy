#!/usr/bin/env python3
"""
Test the MCP debugger with demo_program.py
"""
import asyncio
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Import the MCP server module
import mcp_server


async def main():
    """Test debugging demo_program.py with breakpoints at lines 14 and 20"""

    config = {
        "program": r"C:\Users\elonm\Documents\GitHub\mcp-debugpy\examples\demo_program\demo_program.py",
        "cwd": r"C:\Users\elonm\Documents\GitHub\mcp-debugpy\examples\demo_program",
        "breakpoints": [14, 20],
        "stop_on_entry": True,
        "wait_for_breakpoint": True,
        "breakpoint_timeout": 180
    }

    print("=" * 60)
    print("MCP Debug Session Test - demo_program.py")
    print("=" * 60)
    print(f"\nProgram: {Path(config['program']).name}")
    print(f"Breakpoints: {config['breakpoints']}")
    print(f"Stop on entry: {config['stop_on_entry']}")
    print(f"CWD: {config['cwd']}")
    print(f"Timeout: {config['breakpoint_timeout']}s")
    print()

    try:
        # Use the dap_launch function from mcp_server
        print("Launching debug session...")
        print("(This may take up to 180 seconds)")
        print()

        result = await mcp_server.dap_launch(
            program=config["program"],
            breakpoints=config["breakpoints"],
            cwd=config["cwd"],
            stop_on_entry=config["stop_on_entry"],
            wait_for_breakpoint=config["wait_for_breakpoint"],
            breakpoint_timeout=config["breakpoint_timeout"]
        )

        print("\n" + "=" * 60)
        print("Debug Session Result")
        print("=" * 60)
        print(json.dumps(result, indent=2, default=str))
        print()

        # Check if we hit the breakpoint
        if result.get("stoppedEvent"):
            stopped = result["stoppedEvent"]
            reason = stopped.get("body", {}).get("reason", "unknown")
            print(f"[OK] Program stopped: {reason}")

            # Check breakpoint info
            if result.get("setBreakpointsRetryAfterInit"):
                bp_result = result["setBreakpointsRetryAfterInit"]
                if bp_result.get("body", {}).get("breakpoints"):
                    print("\nBreakpoints set:")
                    for bp in bp_result["body"]["breakpoints"]:
                        verified = bp.get("verified", False)
                        line = bp.get("line", "unknown")
                        source = bp.get("source", {}).get("path", "unknown")
                        print(f"  Line {line}: verified={verified}")
        else:
            print("[WARN] No stopped event captured")

        # Cleanup
        if mcp_server._dap_client:
            await mcp_server._dap_client.close()
            mcp_server._dap_client = None

        print("\n[SUCCESS] Debug session complete")

    except asyncio.TimeoutError as e:
        print(f"\n[ERROR] Timeout: {e}")
        print("\nPossible causes:")
        print("  - debugpy adapter failed to start")
        print("  - Python path not found")
        print("  - Breakpoint never hit")
        return 1
    except Exception as e:
        print(f"\n[ERROR] Debug session failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
