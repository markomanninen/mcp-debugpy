"""
MCP Server for Agent-Driven Python Debugging and Testing

IMPORTANT: This MCP server is designed to be automatically started by MCP clients
(VS Code, Claude Desktop, etc.). You do NOT need to run this manually from the
command line. The client will automatically start this server when needed.

Breakpoint registration note: the server implements a resilient registration flow
for debugger breakpoints: an initial attempt is made before `configurationDone`,
the server retries after the adapter sends `initialized` (this covers both the
main program breakpoints and entries provided via `breakpoints_by_source`), and
a final retry pass occurs after the first `stopped` event to catch imported-module
timing races where modules were not yet loaded when the earlier attempts ran.

Configuration examples:
- VS Code: Add to settings.json under "mcp.servers"
- Claude Desktop: Add to claude_desktop_config.json under "mcpServers"

The server provides tools for:
- Running pytest with JSON reports (full suite and focused subsets)
- Debug Adapter Protocol (DAP) workflows: launch, breakpoint management, stepping,
  locals inspection, event introspection, and adapter shutdown
- Capturing the latest stopped event & breakpoint cache so agents can recover state
"""

import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import aiofiles
from textwrap import dedent
from typing import Any, Dict, List, Optional, Tuple

from mcp.server.fastmcp import FastMCP

from dap_stdio_client import StdioDAPClient
from debug_utils import log_debug

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_agent_instructions() -> str:
    global _agent_instructions_cache
    if _agent_instructions_cache is not None:
        return _agent_instructions_cache

    instructions_path = PROJECT_ROOT / "agent_instructions.md"
    try:
        _agent_instructions_cache = instructions_path.read_text(encoding="utf-8")
        return _agent_instructions_cache
    except OSError:
        return (
            "Agent Debug Tools: use repo-relative paths (e.g. 'src/sample_app/app.py') "
            "and start new sessions with dap_launch including desired breakpoints."
        )


_agent_instructions_cache: Optional[str] = None
mcp = FastMCP("agent-debug-tools", instructions=_load_agent_instructions())

_breakpoint_registry: Dict[str, List[int]] = {}
_last_stopped_event: Optional[Dict[str, Any]] = None
_python_executable_path: Optional[Path] = None


@mcp.tool()
def ensure_demo_program(directory: Optional[str] = None) -> Dict[str, Any]:
    """Create a reusable demo script with an intentional bug for debugging walkthroughs."""
    if directory:
        demo_dir = Path(directory).expanduser()
        if not demo_dir.is_absolute():
            demo_dir = (Path.cwd() / demo_dir).resolve()
    else:
        demo_dir = PROJECT_ROOT / "examples" / "demo_program"
    demo_dir.mkdir(parents=True, exist_ok=True)
    demo_path = (demo_dir / "demo_program.py").resolve()
    demo_source = (
        dedent(
            """
        def calculate_average(numbers):
            total = sum(numbers)
            count = len(numbers)
            average = total / count
            return average


        def process_data(raw):
            cleaned = [value * 2 for value in raw if value > 10]
            normalized = [value / max(cleaned) for value in cleaned]
            return cleaned, normalized


        def main():
            data = [5, 15, 20, 40, 50]
            cleaned, normalized = process_data(data)
            print("Cleaned:", cleaned)
            print("Normalized:", normalized)

            empty_avg = calculate_average([])
            print("Average:", empty_avg)


        if __name__ == "__main__":
            main()
        """
        ).strip()
        + "\n"
    )
    demo_path.write_text(demo_source, encoding="utf-8")
    launch = {
        "program": str(demo_path),
        "cwd": str(demo_dir),
        "breakpoints": [14, 20],
        "wait_for_breakpoint": True,
    }
    payload: Dict[str, Any] = {
        "path": str(demo_path),
        "directory": str(demo_dir),
        "suggestedBreakpoints": [14, 20],
        "launchInput": launch,
        "notes": "Call dap_launch with the provided launchInput, then dap_locals or dap_step_over as needed.",
    }
    try:
        payload["relativePath"] = str(demo_path.relative_to(PROJECT_ROOT))
    except ValueError:
        payload["relativePathError"] = "Demo file exists outside the project workspace."
    return payload


@mcp.tool()
async def read_text_file(path: str, max_bytes: int = 65536) -> Dict[str, Any]:
    """Read a UTF-8 text file so agents can inspect generated code before debugging."""
    file_path = Path(path).expanduser()
    if not file_path.is_absolute():
        file_path = (Path.cwd() / file_path).resolve()

    # Security: Ensure the path is within the project directory
    if not file_path.is_relative_to(Path.cwd()):
        return {
            "error": "Path traversal detected",
            "requested": path,
            "resolved": str(file_path),
        }

    if not file_path.exists():
        return {
            "error": "File does not exist",
            "requested": path,
            "resolved": str(file_path),
        }
    try:
        async with aiofiles.open(file_path, mode="r", encoding="utf-8") as f:
            data = await f.read()
    except UnicodeDecodeError:
        return {
            "error": "File is not UTF-8 text",
            "resolved": str(file_path),
        }
    truncated = False
    if len(data) > max_bytes:
        data = data[:max_bytes]
        truncated = True
    return {
        "path": str(file_path),
        "content": data,
        "truncated": truncated,
    }


def _get_python_executable() -> Path:
    """Get the correct Python executable, preferring virtual environment if available."""
    global _python_executable_path
    if _python_executable_path and _python_executable_path.exists():
        return _python_executable_path

    # First check if we're already in a virtual environment via VIRTUAL_ENV
    if "VIRTUAL_ENV" in os.environ:
        venv_python = Path(os.environ["VIRTUAL_ENV"]) / "bin" / "python"
        if venv_python.exists():
            log_debug(f"_get_python_executable: using VIRTUAL_ENV {venv_python}")
            _python_executable_path = venv_python
            return venv_python

    # Check if we're in a virtual environment relative to current working directory
    cwd = Path.cwd()
    venv_path = cwd / ".venv" / "bin" / "python"
    if venv_path.exists():
        log_debug(f"_get_python_executable: using cwd .venv {venv_path}")
        _python_executable_path = venv_path
        return venv_path

    # Check for other common venv locations
    for venv_name in [".venv", "venv", "env"]:
        venv_python = cwd / venv_name / "bin" / "python"
        if venv_python.exists():
            log_debug(f"_get_python_executable: using cwd venv {venv_python}")
            _python_executable_path = venv_python
            return venv_python

    # Check parent directories for virtual environments
    for parent in cwd.parents:
        for venv_name in [".venv", "venv", "env"]:
            venv_python = parent / venv_name / "bin" / "python"
            if venv_python.exists():
                log_debug(f"_get_python_executable: using ancestor venv {venv_python}")
                _python_executable_path = venv_python
                return venv_python

    # Fall back to sys.executable
    fallback = Path(sys.executable)
    log_debug(f"_get_python_executable: falling back to sys.executable {fallback}")
    _python_executable_path = fallback
    return fallback


@mcp.tool()
def run_tests_json(pytest_args: Optional[List[str]] = None) -> Dict[str, Any]:
    """Run pytest and return parsed JSON report for downstream agents.

    Best practice: keep test runs focused by passing explicit targets (for example
    `tests/test_widget.py -k fast`). This keeps execution deterministic and reduces the
    load on agents issuing the command while still returning structured failure data and
    stdout/stderr summaries via pytest-json-report.

    Args:
        pytest_args: extra pytest args (e.g., ["-k", "unit"])
    """
    if pytest_args:
        for arg in pytest_args:
            if re.search(r'[;&|`"\'$()]', arg):
                return {"error": "Invalid characters in pytest_args"}

    report = Path(".pytest-report.json")
    python_exec = _get_python_executable()
    if not python_exec.exists():
        return {"error": "Python executable not found", "executable": str(python_exec)}

    cmd = [
        str(python_exec),
        "-m",
        "pytest",
        "--json-report",
        f"--json-report-file={report}",
    ]
    if pytest_args:
        cmd += pytest_args
    # keep output quiet but still run failures
    cmd += ["-q", "--maxfail=1"]

    # Add debugging information
    # Change to the directory containing the MCP server
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)

    # Change to project root directory
    original_cwd = os.getcwd()
    os.chdir(project_root)

    debug_info: Dict[str, Any] = {
        "python_executable": str(python_exec),
        "current_working_directory": os.getcwd(),
        "original_working_directory": original_cwd,
        "project_root": project_root,
        "virtual_env": os.environ.get("VIRTUAL_ENV"),
    }
    log_debug(f"run_tests_json: executing command={' '.join(cmd)} info={debug_info}")

    # Do not raise on fail; we want to return the JSON either way
    # Redirect all subprocess output to avoid interfering with MCP JSON protocol
    try:
        result = subprocess.run(
            cmd,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        debug_info["return_code"] = result.returncode
        log_debug(f"run_tests_json: returncode={result.returncode}")
    except FileNotFoundError as e:
        log_debug(f"run_tests_json: FileNotFoundError {e}")
        # Restore original working directory
        os.chdir(original_cwd)
        return {
            "error": "pytest executable not found",
            "note": "Ensure pytest is installed in the same environment as the MCP server.",
            "debug": debug_info,
            "exception": str(e),
        }
    if report.exists():
        data = json.loads(report.read_text())
        data["debug"] = debug_info
        log_debug("run_tests_json: report file found and parsed")
        # Restore original working directory
        os.chdir(original_cwd)
        return data
    log_debug("run_tests_json: report file missing after execution")
    # Restore original working directory
    os.chdir(original_cwd)
    return {
        "error": "Report not found",
        "note": "pytest-json-report plugin may be missing or tests did not run.",
        "debug": debug_info,
    }


@mcp.tool()
def run_tests_focus(keyword: str) -> Dict[str, Any]:
    """Run a focused subset: pytest -k <keyword> with JSON report."""
    return run_tests_json(["-k", keyword])


# --- DAP Tools ---
# We keep a single stdio DAP connection per process for simplicity
_dap_client: Optional[StdioDAPClient] = None


async def _ensure_stdio_client(restart: bool = False) -> StdioDAPClient:
    """Create (or recreate) the global stdio DAP client."""
    global _dap_client
    if _dap_client and restart:
        await _dap_client.close()
        _dap_client = None
    if _dap_client is None:
        _dap_client = StdioDAPClient()
        await _dap_client.start()
    return _dap_client


async def _require_client() -> StdioDAPClient:
    client = await _ensure_stdio_client(restart=False)
    if client is None:
        raise RuntimeError("DAP client is not initialized")
    return client


def _record_breakpoints(source: str, lines: List[int]) -> None:
    """Persist the last requested breakpoints for quick introspection."""
    normalized = str(Path(source).resolve())
    if lines:
        _breakpoint_registry[normalized] = sorted(set(lines))
    else:
        _breakpoint_registry.pop(normalized, None)


def _select_thread_id(
    threads_payload: Dict[str, Any], explicit_id: Optional[int]
) -> Optional[int]:
    """Select a thread, preferring explicit id, then last stopped thread, finally the first entry."""
    threads = (
        threads_payload.get("body", {}).get("threads", []) if threads_payload else []
    )
    if not threads:
        return None
    if explicit_id is not None:
        if any(t.get("id") == explicit_id for t in threads):
            return explicit_id
        return None
    if _last_stopped_event:
        thread_id = _last_stopped_event.get("body", {}).get("threadId")
        if thread_id is not None and any(t.get("id") == thread_id for t in threads):
            return thread_id
    return threads[0].get("id")


async def _dap_step(command: str, thread_id: Optional[int]) -> Dict[str, Any]:
    """Execute a DAP step command (`next`, `stepIn`, `stepOut`) with shared ergonomics."""
    client = await _require_client()
    th = await client.threads()
    tid = _select_thread_id(th, thread_id)
    if tid is None:
        return {"error": "No threads reported by adapter", "threads": th}
    dap_method = getattr(client, command)
    resp = await dap_method(tid)
    return {
        "threads": th,
        "result": resp,
        "selectedThreadId": tid,
        "command": command,
    }


async def _resilient_set_breakpoints(
    client: StdioDAPClient,
    source_path: str,
    lines: List[int],
    wait_timeout: float = 5.0,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Set breakpoints and retry once if adapter was not yet initialized."""
    try:
        primary = await client.setBreakpoints(source_path, lines)
    except RuntimeError as err:
        log_debug(f"_resilient_set_breakpoints: adapter unavailable: {err}")
        return {"success": False, "message": str(err)}, None
    if primary.get("success", True):
        _record_breakpoints(source_path, lines)
        return primary, None
    if primary.get("message") != "Server is not available":
        return primary, None
    if wait_timeout is not None and wait_timeout <= 0:
        if not client.initialized_received():
            return primary, None
    else:
        try:
            await client.wait_for_initialized(timeout=wait_timeout)
        except asyncio.TimeoutError:
            return primary, None
    try:
        retry = await client.setBreakpoints(source_path, lines)
    except RuntimeError as err:
        log_debug(f"_resilient_set_breakpoints retry: adapter unavailable: {err}")
        return {"success": False, "message": str(err)}, primary
    if retry.get("success", True):
        _record_breakpoints(source_path, lines)
    return retry, primary


async def _resilient_set_exception_breakpoints(
    client: StdioDAPClient,
    filters: Optional[List[str]] = None,
    wait_timeout: float = 5.0,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Send setExceptionBreakpoints with an optional retry."""
    try:
        primary = await client.setExceptionBreakpoints(filters or [])
    except RuntimeError as err:
        log_debug(f"_resilient_set_exception_breakpoints: adapter unavailable: {err}")
        return {"success": False, "message": str(err)}, None
    if primary.get("success", True):
        return primary, None
    if primary.get("message") != "Server is not available":
        return primary, None
    if wait_timeout is not None and wait_timeout <= 0:
        if not client.initialized_received():
            return primary, None
    else:
        try:
            await client.wait_for_initialized(timeout=wait_timeout)
        except asyncio.TimeoutError:
            return primary, None
    try:
        retry = await client.setExceptionBreakpoints(filters or [])
    except RuntimeError as err:
        log_debug(
            f"_resilient_set_exception_breakpoints retry: adapter unavailable: {err}"
        )
        return {"success": False, "message": str(err)}, primary
    return retry, primary


@mcp.tool()
async def dap_launch(
    program: str,
    cwd: Optional[str] = None,
    breakpoints: Optional[List[int]] = None,
    breakpoints_by_source: Optional[Dict[str, List[int]]] = None,
    stop_on_entry: bool = False,
    wait_for_breakpoint: bool = True,
    breakpoint_timeout: float = 5.0,
) -> Dict[str, Any]:
    """Launch a Python program under debugpy adapter and optionally pause at a breakpoint.

    This tool implements the DAP-recommended initialization sequence:
    initialize → setBreakpoints → launch → configurationDone → wait_for_stopped

    **Parameters:**
    - program: Path to the Python script to debug (absolute or relative to cwd)
    - cwd: Working directory for the launched process (defaults to program's parent dir)
    - breakpoints: Line numbers for breakpoints in the main program file
    - breakpoints_by_source: Dict mapping source paths to line numbers for breakpoints
      in additional files (e.g., {"examples/gui_counter/counter.py": [16]})
    - stop_on_entry: If True, adds a breakpoint at line 1 of the program
    - wait_for_breakpoint: If True, waits for a stopped event before returning
    - breakpoint_timeout: Maximum seconds to wait for stopped event

    **Common Pitfalls to Avoid:**
    1. **Don't set breakpoints on function definitions**: Set them on the first executable
       line INSIDE the function (e.g., line 41, not line 39 for a function starting at line 39).
       Python stops at function definitions during class loading, not during execution.

    2. **Use stop_on_entry for full control**: Set `stop_on_entry=True` to pause execution
       before any code runs, giving you time to inspect state before hitting your breakpoints.

    3. **Prefer function call locations**: Instead of breaking at the function definition,
       set breakpoints where the function is CALLED (e.g., in main()), then use `dap_step_in()`.

    **Recommended Debugging Pattern:**
    ```python
    # Good: Break where function is called, then step in
    dap_launch(program="script.py", breakpoints=[71])  # Line 71 calls the function
    dap_step_in()  # Step into the function

    # Also good: Break on first executable line inside function
    dap_launch(program="script.py", breakpoints=[41])  # First line inside calculate_total

    # Avoid: Breaking on function definition
    dap_launch(program="script.py", breakpoints=[39])  # Function definition - stops during class loading
    ```

    **Breakpoint Registration Flow:**
    1. Initial attempt: setBreakpoints called before configurationDone (may fail if adapter not ready)
    2. Retry after init: If adapter wasn't ready, retry after initialized event (applies to both
       main program breakpoints AND breakpoints_by_source)
    3. **Retry after stop**: After first stopped event, retry any still-unverified breakpoints_by_source
       entries. This ensures module breakpoints are registered even if modules weren't loaded yet.

    **Path Resolution for breakpoints_by_source:**
    Relative paths are resolved in this order of preference:
    1. PROJECT_ROOT / source_path (preferred for repo-relative paths)
    2. cwd / source_path (if cwd provided and source doesn't look repo-relative)
    3. Path(source_path).resolve() (fallback)

    The first existing path is chosen, or PROJECT_ROOT variant if none exist.

    **Return Value:**
    Dict containing responses from each step:
    - initialize, launch, configurationDone: DAP responses
    - setBreakpoints, setBreakpointsBySource: Initial breakpoint registration attempts
    - setBreakpointsRetryAfterInit: Retry results after initialized event (if needed)
    - setBreakpointsBySourceRetryAfterStop: Retry results after stopped event (NEW)
    - stoppedEvent: The stopped event if wait_for_breakpoint=True
    - stopOnEntryRequested: True if stop_on_entry was requested

    **Example Usage:**
    ```python
    # Launch with breakpoints in main program and imported module
    result = await dap_launch(
        program="examples/gui_counter/run_counter_debug.py",
        cwd="examples/gui_counter",
        breakpoints=[8],  # Main program breakpoint
        breakpoints_by_source={
            "examples/gui_counter/counter.py": [16]  # Module breakpoint
        },
        stop_on_entry=True,
        wait_for_breakpoint=True
    )

    # Check if breakpoints were registered
    stopped = result.get("stoppedEvent")
    retry_results = result.get("setBreakpointsBySourceRetryAfterStop", {})
    ```

    See: https://microsoft.github.io/debug-adapter-protocol/specification#launch
    """
    global _last_stopped_event

    def _resolve_cwd(
        raw: Optional[str],
    ) -> Tuple[Optional[Path], Optional[Dict[str, Any]]]:
        if not raw:
            return None, None
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        else:
            candidate = candidate.resolve()
        if not candidate.exists():
            try:
                candidate.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                return None, {
                    "error": "Working directory unavailable",
                    "requested": raw,
                    "resolved": str(candidate),
                    "exception": str(exc),
                }
        return candidate, None

    resolved_cwd, cwd_error = _resolve_cwd(cwd)
    if cwd_error:
        return cwd_error

    search_base = resolved_cwd or Path.cwd()
    raw_program = Path(program).expanduser()
    if raw_program.is_absolute():
        program_path = raw_program.resolve()
    else:
        program_path = (search_base / raw_program).resolve()

    if not program_path.exists():
        suggestions: List[str] = []
        try:
            name = raw_program.name
            if name:
                for match in PROJECT_ROOT.rglob(name):
                    suggestions.append(str(match))
                    if len(suggestions) >= 5:
                        break
        except Exception:
            suggestions = []
        return {
            "error": "Program path does not exist",
            "requested": program,
            "resolved": str(program_path),
            "workingDirectory": str(resolved_cwd or search_base),
            "suggestions": suggestions,
            "hint": "Create the script on this machine or call ensure_demo_program(directory=...) to scaffold it.",
        }

    launch_cwd = resolved_cwd or program_path.parent

    client = await _ensure_stdio_client(restart=True)
    result: Dict[str, Any] = {}

    # Step 1: Initialize
    init_resp = await client.initialize()
    result["initialize"] = init_resp

    # Step 2: Wait briefly for initialized event
    try:
        await client.wait_for_initialized(timeout=1.0)
        result["initializedEarly"] = True
    except asyncio.TimeoutError:
        result["initializedEarly"] = False

    # Step 3: Set breakpoints BEFORE configurationDone
    # Support breakpoints for the program file (convenience) and for arbitrary
    # additional source files via `breakpoints_by_source` so callers can atomically
    # register all breakpoints before the target runs (avoids races for short-lived programs).
    # Respect an explicit stop-on-entry request by ensuring a breakpoint at
    # the first line of the program is registered. We keep track of the
    # original program breakpoints so we can restore them after the first stop
    # if the caller didn't request line 1 explicitly.
    original_program_breakpoints = list(breakpoints) if breakpoints else []
    program_breakpoints = list(original_program_breakpoints)
    if stop_on_entry and 1 not in program_breakpoints:
        program_breakpoints.insert(0, 1)

    if program_breakpoints:
        bp_resp, bp_retry = await _resilient_set_breakpoints(
            client, str(program_path), program_breakpoints, wait_timeout=5.0
        )
        result["setBreakpoints"] = bp_resp
        if bp_retry:
            result["setBreakpointsInitial"] = bp_retry
        if bp_resp.get("success", True) and breakpoints:
            _record_breakpoints(str(program_path), breakpoints)
    else:
        # No program breakpoints requested; ensure we record an empty entry
        result["setBreakpoints"] = {"skipped": "no program breakpoints configured"}

    # Register any additional breakpoints specified by absolute (or repo-relative)
    # source paths. Each entry is registered with the adapter before launch so the
    # target process will pause even if it imports those modules quickly.
    if breakpoints_by_source:
        extra_results: Dict[str, Any] = {}
        for src, lines in breakpoints_by_source.items():
            # Resolve src robustly to handle callers passing repo-relative paths
            # or paths relative to the provided cwd. Build a small ordered set of
            # candidate absolute paths and pick the first that exists. Prefer
            # resolving from PROJECT_ROOT to avoid accidentally creating nested
            # duplicate paths like
            # '/.../examples/gui_counter/examples/gui_counter/counter.py'.
            src_path = Path(src)
            candidate_paths: List[Path] = []
            # Always prefer the PROJECT_ROOT-based resolution first for repo
            # relative entries, then try search_base, and finally the plain
            # resolved value. Keep ordering deterministic.
            try:
                proj_candidate = (PROJECT_ROOT / src_path).resolve()
            except Exception:
                proj_candidate = PROJECT_ROOT / src_path
            try:
                search_candidate = (search_base / src_path).resolve()
            except Exception:
                search_candidate = search_base / src_path
            try:
                plain_candidate = src_path.resolve()
            except Exception:
                plain_candidate = src_path

            # Prefer PROJECT_ROOT for repo-style paths (those starting with a
            # top-level folder name present in the repo). This avoids using a
            # cwd-prefixed duplicate when callers pass repo-relative paths.
            first_part = src_path.parts[0] if src_path.parts else None
            top_level_names = {p.name for p in PROJECT_ROOT.iterdir()}
            if src_path.is_absolute():
                candidates_order = [plain_candidate]
            else:
                if first_part and first_part in top_level_names:
                    # repo-relative: prefer PROJECT_ROOT and the plain resolution
                    # (which will often be the same) but avoid search_base which can
                    # create nested duplicate paths when search_base already points
                    # inside the repository.
                    candidates_order = [proj_candidate, plain_candidate]
                else:
                    candidates_order = [
                        proj_candidate,
                        search_candidate,
                        plain_candidate,
                    ]

            # Deduplicate while preserving order
            seen = set()
            for cand in candidates_order:
                cand_str = str(cand)
                if cand_str in seen:
                    continue
                seen.add(cand_str)
                candidate_paths.append(Path(cand_str))

            # Pick the first existing candidate, else default to PROJECT_ROOT variant
            chosen = None
            for cand in candidate_paths:
                try:
                    if cand.exists():
                        chosen = cand
                        break
                except Exception:
                    # If permission or other error, skip
                    continue
            if chosen is None:
                chosen = proj_candidate
            try:
                resp, initial = await _resilient_set_breakpoints(
                    client, str(chosen), lines, wait_timeout=5.0
                )
            except Exception as exc:  # defensive
                resp = {"success": False, "message": str(exc)}
                initial = None
            extra_results[str(chosen)] = {"response": resp}
            if initial and initial is not resp:
                extra_results[str(chosen)]["initial"] = initial
            if resp.get("success", True):
                _record_breakpoints(str(chosen), lines)
        result["setBreakpointsBySource"] = extra_results

    # Record that stop_on_entry was requested so callers can inspect the outcome
    result["stopOnEntryRequested"] = bool(stop_on_entry)

    # Step 4: Set exception breakpoints
    exc_resp, exc_retry = await _resilient_set_exception_breakpoints(
        client, [], wait_timeout=5.0
    )
    result["setExceptionBreakpoints"] = exc_resp
    if exc_retry:
        result["setExceptionBreakpointsInitial"] = exc_retry

    # Step 5: Launch (async task)
    # Ensure the launched program has the repository root on PYTHONPATH so
    # examples can use package-style imports regardless of the chosen cwd.
    launch_env = os.environ.copy()
    repo_root_str = str(PROJECT_ROOT)
    existing_pp = launch_env.get("PYTHONPATH", "")
    if existing_pp:
        # Prepend repo root to preserve existing PYTHONPATH entries
        launch_env["PYTHONPATH"] = repo_root_str + os.pathsep + existing_pp
    else:
        launch_env["PYTHONPATH"] = repo_root_str

    launch_task = asyncio.create_task(
        client.launch(
            program=str(program_path),
            cwd=str(launch_cwd),
            env=launch_env,
        )
    )

    # Ensure the launch request is sent before configurationDone, otherwise the
    # adapter rejects configurationDone and tears down the session.
    await asyncio.sleep(0)

    # Step 6: configurationDone
    cfg_resp = await client.configurationDone()
    result["configurationDone"] = cfg_resp

    # Wait for initialized if it didn't happen early
    if not result.get("initializedEarly", False):
        try:
            await client.wait_for_initialized(timeout=5.0)
            result["initializedLater"] = True
        except asyncio.TimeoutError:
            result["initializedLater"] = False

        # Retry breakpoints if they failed initially
        if breakpoints and (not result.get("setBreakpoints", {}).get("success", True)):
            bp_resp_retry, _ = await _resilient_set_breakpoints(
                client, str(program_path), breakpoints, wait_timeout=0.0
            )
            result["setBreakpointsRetryAfterInit"] = bp_resp_retry

        # Retry breakpoints_by_source if they failed initially
        if breakpoints_by_source and result.get("setBreakpointsBySource"):
            retry_by_source = {}
            for source_path_key, source_data in result[
                "setBreakpointsBySource"
            ].items():
                response = source_data.get("response", {})
                # Retry if failed or not successful
                if not response.get("success", False):
                    # Extract lines from original breakpoints_by_source dict
                    # Need to find which key matches this resolved path
                    for src_rel, lines in breakpoints_by_source.items():
                        # If source_path_key ends with the relative path, it's a match
                        if source_path_key.endswith(src_rel.replace("/", os.sep)):
                            retry_resp, _ = await _resilient_set_breakpoints(
                                client, source_path_key, lines, wait_timeout=0.0
                            )
                            retry_by_source[source_path_key] = retry_resp
                            break
            if retry_by_source:
                result["setBreakpointsBySourceRetryAfterInit"] = retry_by_source

        # Retry exception breakpoints if they failed initially
        if not exc_resp.get("success", True):
            exc_resp_retry, _ = await _resilient_set_exception_breakpoints(
                client, [], wait_timeout=0.0
            )
            result["setExceptionBreakpointsRetryAfterInit"] = exc_resp_retry

    # Step 7: Await launch response
    launch_resp = await launch_task
    result["launch"] = launch_resp

    # Step 8: Wait for stopped event if requested
    if wait_for_breakpoint and breakpoints:
        try:
            stopped = await client.wait_for_event("stopped", timeout=breakpoint_timeout)
            result["stoppedEvent"] = stopped
            if stopped:
                _last_stopped_event = stopped
        except asyncio.TimeoutError:
            result["stoppedEvent"] = {"timeout": breakpoint_timeout}
    elif not breakpoints:
        result["stoppedEvent"] = {"skipped": "no breakpoints configured"}

    # Step 9: After first stop (stop-on-entry or breakpoint), retry any
    # breakpoints_by_source that weren't successfully verified. At this point
    # the adapter is stable and we have a window before module imports happen.
    if result.get("stoppedEvent") and breakpoints_by_source:
        retry_results = {}
        for src_rel, lines in breakpoints_by_source.items():
            # Build candidate paths the same way as in step 3
            first_part = Path(src_rel).parts[0] if Path(src_rel).parts else ""
            proj_candidate = PROJECT_ROOT / src_rel
            search_candidate = (
                (search_base / src_rel) if search_base else proj_candidate
            )
            plain_candidate = Path(src_rel).resolve()

            # Prefer PROJECT_ROOT resolution if the source path looks repo-relative
            if first_part and first_part in top_level_names:
                candidates_order = [proj_candidate, plain_candidate]
            else:
                candidates_order = [proj_candidate, search_candidate, plain_candidate]

            # Deduplicate
            seen = set()
            candidate_paths = []
            for cand in candidates_order:
                cand_str = str(cand)
                if cand_str in seen:
                    continue
                seen.add(cand_str)
                candidate_paths.append(Path(cand_str))

            # Pick first existing, else default to PROJECT_ROOT
            chosen = None
            for cand in candidate_paths:
                try:
                    if cand.exists():
                        chosen = cand
                        break
                except Exception:
                    continue
            if chosen is None:
                chosen = proj_candidate

            chosen_str = str(chosen)

            # Check if this source already has verified breakpoints in the registry
            if _breakpoint_registry.get(chosen_str):
                # Already registered, skip
                continue

            # Retry setting breakpoints for this source
            try:
                resp, _ = await _resilient_set_breakpoints(
                    client, chosen_str, lines, wait_timeout=0.5
                )
                retry_results[chosen_str] = resp
                if resp.get("success", True):
                    _record_breakpoints(chosen_str, lines)
            except Exception as exc:
                retry_results[chosen_str] = {"success": False, "message": str(exc)}

        if retry_results:
            result["setBreakpointsBySourceRetryAfterStop"] = retry_results

    return result


@mcp.tool()
async def dap_validate_breakpoint_line(source_path: str, line: int) -> Dict[str, Any]:
    """Validate if a line number is a good breakpoint location.

    Analyzes the source code to warn about common mistakes like:
    - Setting breakpoints on function/class definitions
    - Setting breakpoints on comments or blank lines
    - Setting breakpoints on import statements

    Returns suggestions for better breakpoint locations nearby.
    """
    path = Path(source_path).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()

    if not path.exists():
        return {"error": "File not found", "path": str(path)}

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if line < 1 or line > len(lines):
            return {
                "error": "Line number out of range",
                "line": line,
                "total_lines": len(lines),
            }

        target_line = lines[line - 1].strip()
        warnings = []
        suggestions = []

        # Check for function/class definitions
        if target_line.startswith("def ") or target_line.startswith("async def "):
            warnings.append("This is a function definition line")
            if line < len(lines):
                suggestions.append(
                    f"Consider line {line + 1} (first line inside the function)"
                )
            suggestions.append(
                "Or set breakpoint where function is called, then use dap_step_in()"
            )

        if target_line.startswith("class "):
            warnings.append("This is a class definition line")
            suggestions.append("Set breakpoint in __init__ or a method instead")

        # Check for comments/blank lines
        if not target_line or target_line.startswith("#"):
            warnings.append("This is a comment or blank line")
            # Find next non-blank line
            for i in range(line, min(line + 5, len(lines))):
                next_line = lines[i].strip()
                if next_line and not next_line.startswith("#"):
                    preview = next_line[:50] + "..." if len(next_line) > 50 else next_line
                    suggestions.append(f"Consider line {i + 1}: {preview}")
                    break

        # Check for import statements
        if target_line.startswith("import ") or target_line.startswith("from "):
            warnings.append("This is an import statement")
            suggestions.append("Breakpoints on imports may not be useful")
            suggestions.append("Set breakpoint in a function or after imports")

        return {
            "line": line,
            "content": target_line,
            "isValid": len(warnings) == 0,
            "warnings": warnings,
            "suggestions": suggestions,
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def dap_set_breakpoints(source_path: str, lines: List[int]) -> Dict[str, Any]:
    """Set breakpoints by absolute source path and line numbers.

    Paths are normalized to absolute form before being sent to the adapter so callers can
    provide either relative or absolute locations. Breakpoint requests are memoized locally so
    `dap_list_breakpoints` can report the active configuration for agents.
    """
    client = await _require_client()
    source = str(Path(source_path).resolve())
    resp, initial = await _resilient_set_breakpoints(
        client, source, lines, wait_timeout=5.0
    )
    result = {"response": resp}
    if initial and initial is not resp:
        result["initial"] = initial
    result["trackedBreakpoints"] = _breakpoint_registry.copy()
    return result


@mcp.tool()
async def dap_list_breakpoints() -> Dict[str, Any]:
    """Return the breakpoints most recently registered with the adapter.

    This exposes the server-side cache so agents can audit which files/lines have been
    requested without needing to parse prior `dap_set_breakpoints` responses.
    """
    return {"breakpoints": _breakpoint_registry.copy()}


@mcp.tool()
async def dap_continue(thread_id: Optional[int] = None) -> Dict[str, Any]:
    """Continue execution on the specified (or last stopped) thread.

    When no `thread_id` is supplied the helper prefers the thread from the most recent
    `stopped` event, falling back to the first thread reported by the adapter.
    """
    client = await _require_client()
    th = await client.threads()
    tid = _select_thread_id(th, thread_id)
    if tid is None:
        return {"error": "No threads reported by adapter", "threads": th}
    resp = await client.continue_(tid)
    return {"threads": th, "continue": resp, "selectedThreadId": tid}


@mcp.tool()
async def dap_step_over(thread_id: Optional[int] = None) -> Dict[str, Any]:
    """Step over the next line on the active thread.

    Mirrors the `next` request from the DAP specification. Useful for keeping execution on
    the current stack frame while skipping function bodies.
    """
    return await _dap_step("next", thread_id)


@mcp.tool()
async def dap_step_in(thread_id: Optional[int] = None) -> Dict[str, Any]:
    """Step into the next function call on the active thread."""
    return await _dap_step("stepIn", thread_id)


@mcp.tool()
async def dap_step_out(thread_id: Optional[int] = None) -> Dict[str, Any]:
    """Step out of the current function on the active thread."""
    return await _dap_step("stepOut", thread_id)


@mcp.tool()
async def dap_locals() -> Dict[str, Any]:
    """Return locals from the top (or last stopped) stack frame.

    The helper reuses the most recent `stopped` event when available so agents inspect the
    context that triggered the pause without manually juggling thread and frame ids.
    """
    client = await _require_client()
    th = await client.threads()
    tid = _select_thread_id(th, None)
    if tid is None:
        return {"error": "No threads reported by adapter", "threads": th}
    st = await client.stackTrace(tid)
    frames = st.get("body", {}).get("stackFrames", [])
    if not frames:
        return {"error": "No frames", "threads": th, "stackTrace": st}
    preferred_frame_id = (
        _last_stopped_event.get("body", {}).get("frameId")
        if _last_stopped_event
        else None
    )
    frame = next((f for f in frames if f.get("id") == preferred_frame_id), frames[0])
    scopes = await client.scopes(frame["id"])
    locals_ref = None
    for sc in scopes.get("body", {}).get("scopes", []):
        if sc.get("name", "").lower().startswith("locals"):
            locals_ref = sc["variablesReference"]
            break
    if not locals_ref:
        return {
            "error": "Locals scope not found",
            "threads": th,
            "stackTrace": st,
            "scopes": scopes,
        }
    vars_payload = await client.variables(locals_ref)
    return {
        "threads": th,
        "stackTrace": st,
        "scopes": scopes,
        "variables": vars_payload,
        "selectedThreadId": tid,
        "selectedFrameId": frame.get("id"),
    }


@mcp.tool()
async def dap_wait_for_event(name: str, timeout: float = 5.0) -> Dict[str, Any]:
    """Wait for a specific DAP event (e.g., 'stopped')."""
    global _last_stopped_event
    client = await _require_client()
    try:
        event = await client.wait_for_event(name, timeout=timeout)
        if event and event.get("event") == "stopped":
            _last_stopped_event = event
        return {"event": event}
    except asyncio.TimeoutError:
        return {"timeout": timeout, "event": name}


@mcp.tool()
async def dap_last_stopped_event() -> Dict[str, Any]:
    """Return the cached `stopped` event and tracked breakpoints for quick context."""
    return {
        "stoppedEvent": _last_stopped_event,
        "breakpoints": _breakpoint_registry.copy(),
    }


@mcp.tool()
async def dap_shutdown() -> Dict[str, Any]:
    """Terminate the current DAP adapter session."""
    global _dap_client
    if _dap_client:
        await _dap_client.close()
        _dap_client = None
        return {"status": "stopped"}
    return {"status": "no-session"}


def print_help():
    """Print help information about the MCP server and its tools."""
    help_text = """
MCP Server for Agent-Driven Python Debugging and Testing

IMPORTANT: This MCP server is designed to be automatically started by MCP clients
(VS Code, Claude Desktop, etc.). You do NOT need to run this manually from the
command line. The client will automatically start this server when needed.

Configuration:
==============
Use the provided configuration helper script to set up MCP clients:

    python scripts/configure_mcp_clients.py

This script will:
• Detect existing VS Code/Claude MCP configurations
• Interactively add/update/remove MCP server entries
• Generate configuration snippets for Claude Desktop
• Handle path resolution and environment setup automatically

Manual Configuration (if needed):
=================================
VS Code - Add to settings.json under "mcp.servers":
{
  "mcp.servers.agentDebug": {
    "command": "/path/to/your/project/.venv/bin/python",
    "args": ["src/mcp_server.py"],
    "cwd": "/path/to/your/project"
  }
}

Claude Desktop - Add to claude_desktop_config.json under "mcpServers":
{
    "mcpServers": {
        "agentDebug": {
            "command": "/path/to/your/project/.venv/bin/python",
            "args": ["src/mcp_server.py"],
            "cwd": "/path/to/your/project"
        }
    }
}

Available MCP Tools:
==================

Testing Tools:
--------------
• run_tests_json(pytest_args: Optional[List[str]])
    Run pytest with JSON report output
• run_tests_focus(keyword: str)
  Run focused subset of tests using pytest -k <keyword>

Debug Adapter Protocol (DAP) Tools:
-----------------------------------
• dap_launch(program: str, cwd: Optional[str], breakpoints: Optional[List[int]],
             wait_for_breakpoint: bool, breakpoint_timeout: float)
    Launch a program under debugpy.adapter with optional breakpoints
• dap_set_breakpoints(source_path: str, lines: List[int])
    Set breakpoints by absolute source path and line numbers
• dap_continue(thread_id: Optional[int])
    Continue execution on the given thread
• dap_locals()
    Return locals from the top stack frame of the first thread
• dap_wait_for_event(name: str, timeout: float)
    Wait for a specific DAP event (e.g., 'stopped')
• dap_shutdown()
  Terminate the current DAP adapter session

Usage Workflow:
===============
1. Run configuration helper: python scripts/configure_mcp_clients.py
2. Use the tools through your MCP client interface (VS Code AI Chat, Claude Desktop)
3. The server automatically manages debugpy.adapter processes

Example Debug Session:
======================
• dap_launch({"program": "examples/math_bug/calculator.py", "breakpoints": [43]})
• dap_locals() - inspect variables at breakpoint
• dap_continue() - resume execution
• dap_shutdown() - clean up when done

Example Test Session:
====================
• run_tests_json(["-k", "math_bug"]) - run specific tests
• run_tests_focus("subtract") - focus on tests matching keyword

For more information, see README.md
"""
    print(help_text)


if __name__ == "__main__":
    # Check for help request before creating ArgumentParser
    if "--help" in sys.argv or "-h" in sys.argv:
        print_help()
        sys.exit(0)

    # If no --help, start the MCP server normally
    mcp.run()
