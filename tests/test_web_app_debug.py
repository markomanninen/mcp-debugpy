"""
Test web application debugging with dap_launch.

This test verifies that Flask apps can be debugged using dap_launch,
with breakpoints triggered via HTTP requests.
"""

import asyncio
import sys
from pathlib import Path

import pytest
import httpx

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mcp_server import (
    dap_launch,
    dap_wait_for_event,
    dap_locals,
    dap_continue,
    dap_shutdown,
)


@pytest.mark.asyncio
async def test_flask_app_debugging_with_http_breakpoint():
    """
    Test that Flask app can be launched with dap_launch and breakpoints
    can be triggered via HTTP requests.
    """
    project_root = Path(__file__).parent.parent

    # Launch Flask app under debugger control
    launch_result = await dap_launch(
        program="examples/web_flask/run_flask.py",
        cwd=str(project_root),
        breakpoints_by_source={
            "examples/web_flask/inventory.py": [18]  # The buggy line
        },
        wait_for_breakpoint=False,
        breakpoint_timeout=10.0,
    )

    try:
        # Verify launch was successful
        assert (
            launch_result["initialize"]["success"] is True
        ), "Initialize should succeed"
        assert launch_result["launch"]["success"] is True, "Launch should succeed"

        # Verify breakpoint was set in inventory.py
        bp_found = False
        retry_results = launch_result.get("setBreakpointsBySourceRetryAfterInit", {})

        for source_path, data in retry_results.items():
            if "inventory.py" in source_path:
                bp_found = True
                assert (
                    data["success"] is True
                ), f"Breakpoint registration should succeed for {source_path}"
                breakpoints = data.get("body", {}).get("breakpoints", [])
                assert len(breakpoints) == 1, "Should have one breakpoint"
                assert (
                    breakpoints[0]["verified"] is True
                ), "Breakpoint should be verified"
                assert breakpoints[0]["line"] == 18, "Breakpoint should be at line 18"
                break

        assert bp_found, "Breakpoint in inventory.py should be found in results"

        # Give Flask a moment to start
        await asyncio.sleep(2)

        # Create an async task that will make HTTP request and wait at breakpoint
        # We DON'T await it immediately - let it run in background
        async def trigger_breakpoint():
            """Make HTTP request that will pause at breakpoint."""
            await asyncio.sleep(0.5)  # Small delay before triggering

            # This will hang until we continue the debugger
            async with httpx.AsyncClient() as client:
                try:
                    response = await client.get(
                        "http://127.0.0.1:5001/total",
                        timeout=60.0,  # Long timeout because we'll pause at breakpoint
                    )
                    return response
                except (httpx.ConnectError, httpx.ReadTimeout):
                    return None

        # Start the HTTP request in background (it will pause at breakpoint)
        http_task = asyncio.create_task(trigger_breakpoint())

        # Wait for the stopped event (breakpoint hit)
        stopped_result = await dap_wait_for_event(name="stopped", timeout=15.0)

        assert stopped_result is not None, "Should receive stopped event"
        stopped_body = stopped_result.get("event", {}).get("body", {})
        assert stopped_body.get("reason") == "breakpoint", "Should stop at breakpoint"

        # Inspect locals to verify we're at the right location
        locals_result = await dap_locals()

        # Extract variables
        variables_list = (
            locals_result.get("variables", {}).get("body", {}).get("variables", [])
        )
        var_names = {v["name"] for v in variables_list}

        # At line 18 in total_cost function, we should see these variables
        assert "item" in var_names, "Should have 'item' variable in scope"
        assert "total" in var_names, "Should have 'total' variable in scope"
        assert "items" in var_names, "Should have 'items' variable in scope"

        # Find the item variable and verify it's the first item (widget)
        item_var = next((v for v in variables_list if v["name"] == "item"), None)
        assert item_var is not None, "Should find item variable"
        assert "widget" in item_var["value"].lower(), "First item should be widget"

        # Continue execution - but remember there are 2 items in the list!
        # The breakpoint will hit again for the second item
        continue_result = await dap_continue()
        assert (
            continue_result["continue"]["success"] is True
        ), "First continue should succeed"

        # Wait for second breakpoint hit (second item: gadget)
        stopped2 = await dap_wait_for_event("stopped", timeout=10.0)
        assert stopped2 is not None, "Should hit breakpoint again for second item"

        # Continue again to complete the loop and HTTP request
        continue2_result = await dap_continue()
        assert (
            continue2_result["continue"]["success"] is True
        ), "Second continue should succeed"

        # Now wait for the HTTP response (with reasonable timeout)
        response = await asyncio.wait_for(http_task, timeout=30.0)

        # Verify the HTTP request completed successfully
        assert response is not None, "HTTP request should complete"
        assert response.status_code == 200, "Should get 200 OK"

        json_data = response.json()
        assert "total" in json_data, "Response should have 'total' field"

        # The buggy calculation: (9.99+3) + (14.5+2) = 29.49
        # Correct would be: (9.99*3) + (14.5*2) = 58.97
        assert (
            json_data["total"] == 29.49
        ), "Should return buggy result (addition instead of multiplication)"

    finally:
        # Always clean up
        shutdown_result = await dap_shutdown()
        assert shutdown_result["status"] == "stopped", "Shutdown should stop debugger"


@pytest.mark.asyncio
async def test_flask_breakpoint_hit_twice_in_loop():
    """
    Test that breakpoint is hit multiple times as we iterate through items.
    This verifies the loop debugging works correctly.
    """
    project_root = Path(__file__).parent.parent

    # Launch Flask
    launch_result = await dap_launch(
        program="examples/web_flask/run_flask.py",
        cwd=str(project_root),
        breakpoints_by_source={"examples/web_flask/inventory.py": [18]},
        wait_for_breakpoint=False,
    )

    try:
        assert launch_result["launch"]["success"] is True

        # Wait for Flask to start
        await asyncio.sleep(2)

        # Trigger HTTP request in background
        async def make_request():
            await asyncio.sleep(0.5)
            async with httpx.AsyncClient() as client:
                try:
                    return await client.get("http://127.0.0.1:5001/total", timeout=60.0)
                except (httpx.ConnectError, httpx.ReadTimeout):
                    return None

        http_task = asyncio.create_task(make_request())

        # First breakpoint hit (first item: widget)
        stopped1 = await dap_wait_for_event("stopped", timeout=10.0)
        assert stopped1 is not None, "Should hit first breakpoint"

        locals1 = await dap_locals()
        vars1 = {
            v["name"]: v["value"] for v in locals1["variables"]["body"]["variables"]
        }
        assert "item" in vars1, "Should have item variable"
        assert "widget" in vars1["item"].lower(), "First item should be widget"

        # Continue to next iteration
        await dap_continue()

        # Second breakpoint hit (second item: gadget)
        stopped2 = await dap_wait_for_event("stopped", timeout=10.0)
        assert stopped2 is not None, "Should hit second breakpoint"

        locals2 = await dap_locals()
        vars2 = {
            v["name"]: v["value"] for v in locals2["variables"]["body"]["variables"]
        }
        assert "item" in vars2, "Should have item variable"
        assert "gadget" in vars2["item"].lower(), "Second item should be gadget"

        # Continue to complete the request
        await dap_continue()

        # Verify HTTP request completes
        response = await asyncio.wait_for(http_task, timeout=30.0)
        assert response is not None, "HTTP request should complete"
        assert response.status_code == 200, "Should get 200 OK"

    finally:
        await dap_shutdown()
