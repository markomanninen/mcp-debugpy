from pathlib import Path

import sys
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

pytestmark = pytest.mark.asyncio


async def test_mcp_end_to_end() -> None:
    """Exercise the full MCP tool surface against the real debugpy adapter."""
    sample_app = SRC / "sample_app" / "app.py"

    # Import the MCP server module after ensuring the project root is on sys.path
    mcp_server = __import__("src.mcp_server", fromlist=["mcp_server"])  # type: ignore

    demo = mcp_server.ensure_demo_program()
    assert Path(demo["path"]).exists()
    assert demo.get("launchInput", {}).get("breakpoints") == [14, 20]
    demo_text = await mcp_server.read_text_file(demo["path"])
    assert "calculate_average" in demo_text.get("content", "")

    # Pytest helpers should round-trip JSON summaries.
    report = mcp_server.run_tests_json(["tests/test_mcp_server.py"])
    summary = report.get("summary", {})
    assert summary.get("total") == summary.get("passed")

    focus_report = mcp_server.run_tests_focus("xfail")
    focus_summary = focus_report.get("summary", {})
    assert focus_summary.get("collected")

    # Launch the debug session and ensure we halt on the configured breakpoint.
    launch = await mcp_server.dap_launch(
        program=str(sample_app),
        cwd=str(PROJECT_ROOT),
        breakpoints=[8],
        wait_for_breakpoint=True,
        breakpoint_timeout=5.0,
    )
    assert launch.get("initialize", {}).get("success") is True
    assert launch.get("stoppedEvent", {}).get("event") == "stopped"

    # Breakpoint cache should record the normalized path.
    bp_cache = await mcp_server.dap_list_breakpoints()
    assert str(sample_app.resolve()) in bp_cache.get("breakpoints", {})

    # Inspect locals at the paused frame.
    locals_payload = await mcp_server.dap_locals()
    assert locals_payload.get("selectedThreadId")
    variables = locals_payload.get("variables", {}).get("body", {}).get("variables", [])
    names = {var.get("name"): var.get("value") for var in variables}
    assert names.get("x") == "3"
    assert names.get("y") == "4"

    # Step around the paused frame using the exposed helpers.
    for api_name in ("dap_step_over", "dap_step_in", "dap_step_out"):
        result = await getattr(mcp_server, api_name)()
        assert result.get("result", {}).get("success") is True

    # Resume execution and wait for the terminate signal.
    cont = await mcp_server.dap_continue()
    assert cont.get("continue", {}).get("success") is True

    term = await mcp_server.dap_wait_for_event("terminated", timeout=5.0)
    assert term.get("event", {}).get("event") == "terminated"

    # Cached stopped event should still be exposed for reference.
    state = await mcp_server.dap_last_stopped_event()
    assert state.get("stoppedEvent", {}).get("event") == "stopped"

    # Shut down the adapter to keep the test process clean.
    shutdown = await mcp_server.dap_shutdown()
    assert shutdown.get("status") == "stopped"
