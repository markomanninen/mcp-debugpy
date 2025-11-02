"""Diagnostic helper: start StdioDAPClient and print detailed startup info."""

import asyncio
import json
import os
from pathlib import Path

from src.dap_stdio_client import StdioDAPClient


async def main():
    client = StdioDAPClient()
    try:
        print("Starting client.start()...")
        await client.start()
    except Exception as e:
        print("client.start() raised:", repr(e))
    finally:
        print(
            "proc:",
            getattr(client.proc, "pid", None),
            "returncode:",
            getattr(client.proc, "returncode", None),
        )
        print("endpoints_file:", client._endpoints_file)
        debugpy_dir = Path.home() / ".debugpy"
        print("~/.debugpy exists:", debugpy_dir.exists())
        if debugpy_dir.exists():
            for p in sorted(debugpy_dir.glob("debugpy-endpoints-*.json")):
                try:
                    stat = p.stat()
                    print(" -", p, "size", stat.st_size, "mtime", stat.st_mtime)
                    try:
                        print("   content:", p.read_text())
                    except Exception as re:
                        print("   read fail:", re)
                except Exception:
                    pass
        print("stderr tail:", client._format_stderr_tail())

        try:
            await client.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
