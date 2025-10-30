import asyncio
from pathlib import Path
from typing import Any, Dict, List

import pytest

import mcp_server


@pytest.fixture(autouse=True)
def reset_mcp_client():
    # Ensure a clean client between tests
    mcp_server._dap_client = None
    yield
    mcp_server._dap_client = None


@pytest.fixture
def fake_stdio_client(monkeypatch):
    instances: List["FakeDAPClient"] = []

    class FakeDAPClient:
        def __init__(self):
            self.started = False
            self.initialized_flag = False
            from typing import Optional

            self.wait_for_initialized_calls: List[Optional[float]] = []
            self.set_breakpoints_calls = 0
            self.set_exception_calls = 0
            self._exception_failures_remaining = 1
            self.launch_kwargs: Dict[str, Any] | None = None
            self.wait_for_event_calls: List[tuple[str, float | None]] = []
            self.continue_thread = None
            self.closed = False
            instances.append(self)

        async def start(self):
            self.started = True

        async def initialize(self):
            return {"success": True}

        async def wait_for_initialized(self, timeout: float | None = None):
            self.wait_for_initialized_calls.append(timeout)
            if timeout == 1.0 and not self.initialized_flag:
                raise asyncio.TimeoutError
            self.initialized_flag = True

        def initialized_received(self) -> bool:
            return self.initialized_flag

        async def setBreakpoints(self, source_path: str, lines: List[int]):
            self.set_breakpoints_calls += 1
            if not self.initialized_flag:
                return {"success": False, "message": "Server is not available"}
            return {
                "success": True,
                "body": {
                    "breakpoints": [
                        {
                            "verified": True,
                            "id": 0,
                            "source": {"path": source_path},
                            "line": lines[0] if lines else None,
                        }
                    ]
                },
            }

        async def setExceptionBreakpoints(self, filters: List[str]):
            self.set_exception_calls += 1
            if self._exception_failures_remaining > 0:
                self._exception_failures_remaining -= 1
                return {"success": False, "message": "Server is not available"}
            return {"success": True}

        async def launch(self, **kwargs):
            self.launch_kwargs = kwargs
            return {"success": True}

        async def configurationDone(self):
            return {"success": True}

        async def wait_for_event(self, name: str, timeout: float | None = None):
            self.wait_for_event_calls.append((name, timeout))
            return {"event": name, "body": {"reason": "breakpoint"}}

        async def threads(self):
            return {"body": {"threads": [{"id": 1}]}}

        async def continue_(self, threadId: int):
            self.continue_thread = threadId
            return {"success": True}

        async def stackTrace(self, threadId: int):
            return {
                "body": {
                    "stackFrames": [
                        {"id": 42, "name": "compute", "line": 8},
                    ]
                }
            }

        async def scopes(self, frameId: int):
            return {
                "body": {
                    "scopes": [
                        {"name": "Locals", "variablesReference": 99},
                    ]
                }
            }

        async def variables(self, variablesReference: int):
            return {
                "body": {
                    "variables": [
                        {"name": "x", "value": "3"},
                        {"name": "y", "value": "4"},
                    ]
                }
            }

        async def close(self):
            self.closed = True

    monkeypatch.setattr(mcp_server, "StdioDAPClient", FakeDAPClient)
    return instances


@pytest.mark.asyncio
async def test_dap_launch_handles_late_initialized(fake_stdio_client):
    script = Path("src/sample_app/app.py")
    result = await mcp_server.dap_launch(str(script), breakpoints=[8])

    assert fake_stdio_client, "Expected fake client to be instantiated"
    client = fake_stdio_client[0]

    assert client.started
    assert client.set_breakpoints_calls >= 2  # initial fail + retry
    assert client.set_exception_calls >= 2
    assert result["initializedEarly"] is False
    assert result["initializedLater"] is True
    assert result["setBreakpoints"]["success"] is True
    assert result["setBreakpointsInitial"]["success"] is False
    assert result["setExceptionBreakpoints"]["success"] is True
    assert result["setExceptionBreakpointsInitial"]["success"] is False
    assert result["stoppedEvent"]["event"] == "stopped"
    assert result["stoppedEvent"]["body"]["reason"] == "breakpoint"
    assert client.wait_for_event_calls == [("stopped", 5.0)]


@pytest.mark.asyncio
async def test_dap_set_breakpoints_reuses_session(fake_stdio_client):
    script = Path("src/sample_app/app.py")
    await mcp_server.dap_launch(str(script), breakpoints=[8])
    client = fake_stdio_client[0]
    client.initialized_flag = True  # ensure success on direct call

    result = await mcp_server.dap_set_breakpoints(str(script), [8])

    assert len(fake_stdio_client) == 1
    assert "initial" not in result
    assert result["response"]["success"] is True
    assert client.set_breakpoints_calls >= 3  # includes previous launch calls


@pytest.mark.asyncio
async def test_dap_locals_and_continue(fake_stdio_client):
    script = Path("src/sample_app/app.py")
    await mcp_server.dap_launch(str(script), breakpoints=[8])

    locals_result = await mcp_server.dap_locals()
    continue_result = await mcp_server.dap_continue()

    assert "error" not in locals_result
    variables = locals_result["variables"]["body"]["variables"]
    assert {"name": "x", "value": "3"} in variables
    assert {"name": "y", "value": "4"} in variables
    assert continue_result["continue"]["success"] is True
    assert continue_result["threads"]["body"]["threads"][0]["id"] == 1


@pytest.mark.asyncio
async def test_dap_shutdown_closes_session(fake_stdio_client):
    script = Path("src/sample_app/app.py")
    await mcp_server.dap_launch(str(script), breakpoints=[8])
    client = fake_stdio_client[0]

    result = await mcp_server.dap_shutdown()
    assert result == {"status": "stopped"}
    assert client.closed is True
    assert mcp_server._dap_client is None

    # second shutdown should report no active session
    result_second = await mcp_server.dap_shutdown()
    assert result_second == {"status": "no-session"}
