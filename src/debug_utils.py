"""
Lightweight logging helpers for debugging MCP server and DAP client behaviour.

Logs are written to the path specified by the `MCP_DEBUG_LOG` environment
variable. If unset, the default is `<repo>/mcp_server.log`. Set
`MCP_DEBUG_LOG=0` to disable logging entirely.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path

_LOG_SETTING = os.environ.get("MCP_DEBUG_LOG")
_LOCK = threading.Lock()

if _LOG_SETTING and _LOG_SETTING.strip() == "0":

    def log_debug(message: str) -> None:
        """Logging disabled; no-op."""
        return

else:
    _LOG_PATH = (
        Path(_LOG_SETTING).expanduser()
        if _LOG_SETTING
        else Path(__file__).resolve().parents[1] / "mcp_server.log"
    )

    def log_debug(message: str) -> None:
        """Append a timestamped message to the debug log."""
        try:
            timestamp = datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
            with _LOCK:
                _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
                with _LOG_PATH.open("a", encoding="utf-8") as fh:
                    fh.write(f"{timestamp} {message}\n")
        except Exception:
            # Logging must never raise.
            pass
