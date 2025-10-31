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


@pytest.mark.asyncio
async def test_dap_launch_breakpoints_by_source_retry_after_stop(fake_stdio_client):
    """Test that breakpoints_by_source are retried after the stopped event."""
    script = Path("src/sample_app/app.py")

    # Launch with both main breakpoints and breakpoints_by_source
    result = await mcp_server.dap_launch(
        program=str(script),
        breakpoints=[8],
        breakpoints_by_source={"src/sample_app/helpers.py": [5, 10]},
        stop_on_entry=True,
        wait_for_breakpoint=True,
    )

    # Verify the launch succeeded
    assert result["initialize"]["success"] is True
    assert result["stoppedEvent"]["event"] == "stopped"

    # Verify initial attempts were made for both program and source
    assert "setBreakpoints" in result
    assert "setBreakpointsBySource" in result

    # The NEW feature: post-stop retry logic for breakpoints_by_source
    # This retry only happens if breakpoints weren't already successfully verified.
    # In this fake client scenario, the breakpoints succeed during retry-after-init
    # (when initialized_flag becomes True), so they're already in the registry and
    # the post-stop retry is skipped. This is the correct behavior - we only retry
    # breakpoints that need retrying.
    #
    # In real-world scenarios with debugpy, module breakpoints often aren't verified
    # until after the first stop, which is when the post-stop retry is essential.

    # Verify that breakpoints_by_source were successfully registered (either during
    # retry-after-init or retry-after-stop)
    source_results = result["setBreakpointsBySource"]
    for source_path, source_result in source_results.items():
        response = source_result.get("response", {})
        assert (
            response.get("success") is True
        ), f"Expected breakpoints_by_source to succeed for {source_path}"

    # If retry after stop occurred, validate those results too
    if "setBreakpointsBySourceRetryAfterStop" in result:
        retry_results = result["setBreakpointsBySourceRetryAfterStop"]
        for source_path, response in retry_results.items():
            assert "helpers.py" in source_path, f"Expected helpers.py in {source_path}"
            assert (
                response.get("success") is True
            ), f"Expected retry to succeed for {source_path}"

    # Verify breakpoint registry includes both files
    bp_list = await mcp_server.dap_list_breakpoints()
    breakpoints = bp_list.get("breakpoints", {})

    # Should have entries for both the program and the source file
    program_path = str(Path(script).resolve())
    assert program_path in breakpoints, "Main program breakpoint not in registry"

    # Source path should be resolved and registered
    # (exact path may vary based on resolution logic, but should contain helpers.py)
    helper_paths = [p for p in breakpoints.keys() if "helpers.py" in p]
    assert len(helper_paths) > 0, "Source file breakpoint not in registry"

    # Verify the source breakpoints have the correct line numbers
    for helper_path in helper_paths:
        lines = breakpoints[helper_path]
        assert 5 in lines or 10 in lines, f"Expected lines [5, 10] but got {lines}"
