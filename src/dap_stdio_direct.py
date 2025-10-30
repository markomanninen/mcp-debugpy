#!/usr/bin/env python3
"""
Direct debugpy.adapter walkthrough using stdio transport.

This script intentionally drives the adapter *without* the MCP server so you can see
the low-level request/response choreography. It mirrors the protocol flow the MCP
tools now automate for you while exposing a few extra inspection steps (stepping,
event polling) for reference.

Protocol flow:
    initialize → (initialized event) → setBreakpoints → configurationDone → launch →
    stopped → inspect locals → step → continue → terminated
"""

import asyncio
from pathlib import Path
from dap_stdio_client import StdioDAPClient

APP = Path(__file__).parent / "sample_app" / "app.py"


async def main():
    print("=== Direct debugpy.adapter walkthrough (stdio transport) ===\n")

    # Create client that launches debugpy.adapter as subprocess
    print("1. Starting debugpy.adapter via stdio...")
    c = StdioDAPClient()
    await c.start()
    print("   ✓ Adapter started\n")

    # Step 1: Initialize
    print("2. Sending initialize request...")
    init_resp = await c.initialize()
    print(f"   ✓ Initialized (success={init_resp.get('success')})\n")

    # Step 2: Wait briefly for initialized event but continue even if missing
    print("3. Waiting briefly for 'initialized' event...")
    try:
        await c.wait_for_initialized(timeout=1.0)
        print("   ✓ Received 'initialized' event\n")
    except asyncio.TimeoutError:
        print("   ⚠ No 'initialized' event yet; continuing with configuration\n")

    async def wait_for_initialized_retry(reason: str, timeout: float = 5.0) -> bool:
        if c.initialized_received():
            return True
        print(f"   ↺ Waiting for 'initialized' ({reason})...")
        try:
            await c.wait_for_initialized(timeout=timeout)
            print(f"   ✓ 'initialized' event received ({reason})")
            return True
        except asyncio.TimeoutError:
            print(f"   ⚠ Still no 'initialized' event ({reason})")
            return False

    # Step 3: Set breakpoints BEFORE configurationDone
    print("4. Setting breakpoint...")
    with open(APP, "r") as f:
        lines = f.readlines()
    bp_line = next(i for i, ln in enumerate(lines, 1) if "z = add(x, y)" in ln)
    bp_resp = await c.setBreakpoints(str(APP), [bp_line])
    print(f"   ✓ Breakpoint set at {APP}:{bp_line}")
    print(f"     response: {bp_resp}")
    if bp_resp.get("body", {}).get("breakpoints"):
        verified = bp_resp["body"]["breakpoints"][0].get("verified")
        print(f"     ↳ Verified: {verified}")
    if (
        not bp_resp.get("success", True)
        and bp_resp.get("message") == "Server is not available"
    ):
        waited = await wait_for_initialized_retry("retry setBreakpoints")
        if waited:
            bp_resp = await c.setBreakpoints(str(APP), [bp_line])
            print(f"   ↺ Retry response: {bp_resp}")
    print()

    # Step 3b: Exception breakpoints (empty filters is common default)
    print("5. Setting exception breakpoints (none)...")
    exc_resp = await c.setExceptionBreakpoints([])
    print(
        f"   ✓ Exception breakpoints response (success={exc_resp.get('success', True)})"
    )
    print(f"     response: {exc_resp}\n")
    if (
        not exc_resp.get("success", True)
        and exc_resp.get("message") == "Server is not available"
    ):
        waited = await wait_for_initialized_retry("retry setExceptionBreakpoints")
        if waited:
            exc_resp = await c.setExceptionBreakpoints([])
            print(f"   ↺ Retry response: {exc_resp}\n")

    # Step 4: Launch request (adapter expects configurationDone during this)
    print("6. Launching program (request)...")
    cwd = str(Path(__file__).parent.parent)
    launch_task = asyncio.create_task(
        c.launch(program=str(APP), cwd=cwd, console="internalConsole")
    )
    await asyncio.sleep(0)  # let launch request hit the wire

    # Step 5b: configurationDone while launch is pending
    print("7. Sending configurationDone...")
    cfg_resp = await c.configurationDone()
    cfg_success = cfg_resp.get("success")
    msg = cfg_resp.get("message")
    print(f"   ✓ Configuration done (success={cfg_success})")
    if not cfg_success and msg:
        print(f"     ↳ Adapter message: {msg}")

    post_init_ready = await wait_for_initialized_retry("post-configurationDone")
    if post_init_ready:
        if not bp_resp.get("success", True):
            print("   ↺ Re-sending setBreakpoints after 'initialized'...")
            bp_resp = await c.setBreakpoints(str(APP), [bp_line])
            print(f"     response: {bp_resp}")
        if not exc_resp.get("success", True):
            print("   ↺ Re-sending setExceptionBreakpoints after 'initialized'...")
            exc_resp = await c.setExceptionBreakpoints([])
            print(f"     response: {exc_resp}")
    print()

    # Step 5c: Await launch response now that configurationDone succeeded
    print("8. Awaiting launch response...")
    launch_resp = await launch_task
    print(f"   ✓ Launch response (success={launch_resp.get('success')})\n")

    # Step 6: Wait for the program to hit the breakpoint
    print("9. Waiting for program to hit breakpoint...")
    try:
        stop_event = await c.wait_for_event("stopped", timeout=5.0)
        reason = stop_event.get("body", {}).get("reason")
        print(f"   ✓ Stopped event received (reason={reason})")
    except asyncio.TimeoutError:
        print("   ⚠ Timeout waiting for 'stopped' event; polling threads directly")
        await asyncio.sleep(0.5)

    # Capture any other events while we are paused.
    print("   ↺ Polling adapter event queue for additional context (1s)...")
    extra_events = []
    poll_deadline = asyncio.get_event_loop().time() + 1.0
    while asyncio.get_event_loop().time() < poll_deadline:
        try:
            evt = await asyncio.wait_for(c._events.get(), timeout=0.1)
            extra_events.append(evt)
        except asyncio.TimeoutError:
            break
    if extra_events:
        for evt in extra_events:
            print(f"     ↳ Event: {evt.get('event')} body={evt.get('body')}")
    else:
        print("     (no additional events observed)")

    # Step 7: Get threads
    print("10. Getting threads...")
    th = await c.threads()
    threads = th.get("body", {}).get("threads", [])

    # If no threads yet, wait a bit more
    retry_count = 0
    while not threads and retry_count < 10:
        await asyncio.sleep(0.1)
        th = await c.threads()
        threads = th.get("body", {}).get("threads", [])
        retry_count += 1

    if not threads:
        print("   ✗ No threads found")
        await c.close()
        return

    tid = threads[0]["id"]
    print(f"   ✓ Found thread {tid}\n")

    # Step 8: Get stack trace and inspect locals
    print("11. Inspecting locals at breakpoint...")
    st = await c.stackTrace(tid)
    frames = st.get("body", {}).get("stackFrames", [])

    if not frames:
        print("   ✗ No stack frames")
        await c.close()
        return

    top = frames[0]
    print(f"   Stopped at: {top.get('name')} line {top.get('line')}")

    # Get scopes
    scopes_resp = await c.scopes(top["id"])
    scopes = scopes_resp.get("body", {}).get("scopes", [])

    # Find locals scope
    locals_ref = next(
        (
            s["variablesReference"]
            for s in scopes
            if s["name"].lower().startswith("locals")
        ),
        None,
    )

    if locals_ref:
        vars_resp = await c.variables(locals_ref)
        variables = vars_resp.get("body", {}).get("variables", [])
        print("   Local variables:")
        for v in variables:
            if v["name"] in ("x", "y", "z"):
                print(f"     {v['name']} = {v['value']}")
        print()
    else:
        print("   ✗ No locals scope found\n")

    # Step 9: Step over once
    print("12. Stepping over...")
    await c.next(tid)
    await asyncio.sleep(0.3)

    st = await c.stackTrace(tid)
    frames = st.get("body", {}).get("stackFrames", [])
    if frames:
        print(f"    ✓ Now at line {frames[0].get('line')}\n")

    # Step 10: Attempt a step-in to demonstrate deeper navigation
    print("13. Attempting step-in (adapter may decline if already at leaf frame)...")
    try:
        await c.stepIn(tid)
        await asyncio.sleep(0.3)
        st = await c.stackTrace(tid)
        frames = st.get("body", {}).get("stackFrames", [])
        if frames:
            print(f"    ✓ Step-in reached line {frames[0].get('line')}")
    except Exception as exc:
        print(f"    ⚠ Step-in not available: {exc}")

    # Step 11: Attempt a step-out
    print("14. Attempting step-out...")
    try:
        await c.stepOut(tid)
        await asyncio.sleep(0.3)
        st = await c.stackTrace(tid)
        frames = st.get("body", {}).get("stackFrames", [])
        if frames:
            print(f"    ✓ Step-out reached line {frames[0].get('line')}")
    except Exception as exc:
        print(f"    ⚠ Step-out not available: {exc}")

    # Continue execution
    print("15. Continuing execution...")
    await c.continue_(tid)
    try:
        cont_evt = await c.wait_for_event("continued", timeout=1.0)
        print(f"    ↳ Continued event: {cont_evt}")
    except asyncio.TimeoutError:
        print("    (no continued event observed within 1s)")
    await asyncio.sleep(0.5)

    try:
        term_evt = await c.wait_for_event("terminated", timeout=2.0)
        print(f"15b. Terminated event received: {term_evt}")
    except asyncio.TimeoutError:
        print("15b. No terminated event observed (program likely exited)")

    await c.close()
    print("\n✓✓✓ Direct adapter walkthrough complete ✓✓✓")
    print("\nReminder: the bug is in app.py:4 - it uses * instead of +")
    print("That's why x=3, y=4 gives z=12 instead of z=7")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback

        traceback.print_exc()
