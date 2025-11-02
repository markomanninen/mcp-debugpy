import asyncio
import glob
import json
import itertools
import socket
import os
import platform
import sys
import tempfile
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional


# Windows-specific subprocess flags to escape job object restrictions
if platform.system() == "Windows":
    import subprocess

    CREATE_BREAKAWAY_FROM_JOB = 0x01000000
    CREATE_NEW_PROCESS_GROUP = 0x00000200
else:
    CREATE_BREAKAWAY_FROM_JOB = 0
    CREATE_NEW_PROCESS_GROUP = 0

from debug_utils import log_debug

_python_executable_path: Optional[Path] = None


class StdioDAPClient:
    """
    DAP client that communicates with debugpy.adapter via stdin/stdout.
    This is the correct way to use debugpy - talk to the adapter, not directly to the target.
    """

    def __init__(self, adapter_cmd=None):
        # Launch the adapter in stdio mode
        # Use the correct Python executable from virtual environment if available
        python_exec = self._get_python_executable()
        self.adapter_cmd = adapter_cmd or [str(python_exec), "-m", "debugpy.adapter"]
        self.proc: Optional[asyncio.subprocess.Process] = None
        self._seq = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._events: asyncio.Queue = asyncio.Queue()
        self._initialized_event = asyncio.Event()
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._closed_exception: Optional[BaseException] = None
        self._endpoints_file: Optional[Path] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._stderr_lines: deque[str] = deque(maxlen=20)
        self._stderr_summary: Optional[str] = None
        self._connect_host: Optional[str] = None
        self._connect_port: Optional[int] = None

    def _get_python_executable(self) -> Path:
        """Get the correct Python executable, preferring virtual environment if available."""
        global _python_executable_path
        if _python_executable_path and _python_executable_path.exists():
            return _python_executable_path

        # Determine platform-specific paths
        is_windows = platform.system() == "Windows"

        if is_windows:
            bin_dir = "Scripts"
            python_name = "python.exe"
        else:
            bin_dir = "bin"
            python_name = "python"

        # Check if we're in a virtual environment
        venv_path = Path.cwd() / ".venv" / bin_dir / python_name
        if venv_path.exists():
            _python_executable_path = venv_path
            return venv_path

        # Check for other common venv locations
        for venv_name in [".venv", "venv", "env"]:
            venv_python = Path.cwd() / venv_name / bin_dir / python_name
            if venv_python.exists():
                _python_executable_path = venv_python
                return venv_python

        # Fall back to sys.executable
        fallback = Path(sys.executable)
        _python_executable_path = fallback
        return fallback

    async def start(self):
        """Start the debugpy.adapter subprocess."""
        self._initialized_event.clear()
        self._closed_exception = None
        self._stderr_lines.clear()
        self._stderr_summary = None
        if self._stderr_task:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except (asyncio.CancelledError, Exception):
                pass
            self._stderr_task = None

        self._connect_host = None
        self._connect_port = None
        endpoints_file: Optional[Path]

        connect_host = "127.0.0.1"

        # Use a dedicated directory with guaranteed write permissions
        debugpy_dir = Path.home() / ".debugpy"
        debugpy_dir.mkdir(exist_ok=True)

        # Create endpoint file in our controlled directory
        import uuid

        endpoint_filename = f"debugpy-endpoints-{uuid.uuid4().hex[:8]}.json"
        endpoints_file = debugpy_dir / endpoint_filename

        # Clean up ALL stale endpoint files to prevent detection issues
        # Take a snapshot of existing files BEFORE cleanup (should be empty after cleanup)
        stale_files = glob.glob(str(debugpy_dir / "debugpy-endpoints-*.json"))
        for stale_file in stale_files:
            try:
                Path(stale_file).unlink()
                log_debug(f"dap_stdio_client.start: removed stale endpoint file {stale_file}")
            except (FileNotFoundError, OSError):
                pass

        # After cleanup, the baseline for detecting new files should be empty
        existing_files_baseline = set()

        log_debug(f"dap_stdio_client.start: using endpoint file {endpoints_file}")

        try:
            # Use wrapper script to pass env var via command-line arg
            # This works around Windows asyncio env inheritance bug in MCP server context
            wrapper_path = Path(__file__).parent / "adapter_wrapper.py"
            log_debug(f"dap_stdio_client.start: Using wrapper script at {wrapper_path}")
            log_debug(
                f"dap_stdio_client.start: Passing endpoint file path as command-line arg: {endpoints_file}"
            )

            self.proc = await asyncio.create_subprocess_exec(
                self.adapter_cmd[0],  # python.exe
                str(wrapper_path),
                str(
                    endpoints_file
                ),  # Pass endpoint file path as arg instead of env var
                "--host",
                connect_host,
                "--port",
                str(self._connect_port if self._connect_port is not None else 0),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,  # DEVNULL instead of PIPE to avoid blocking
                creationflags=(
                    CREATE_NEW_PROCESS_GROUP if platform.system() == "Windows" else 0
                ),
                start_new_session=True if platform.system() != "Windows" else False,
            )
            log_debug(
                f"dap_stdio_client.start: adapter process started with PID {self.proc.pid}"
            )
        except Exception as e:
            log_debug(f"dap_stdio_client.start: failed to start adapter process: {e}")
            raise

        self._endpoints_file = endpoints_file

        # Add a small delay to let the adapter start
        await asyncio.sleep(0.1)

        # Check if process is still running
        if self.proc.returncode is not None:
            raise RuntimeError(
                f"debugpy.adapter exited early with code {self.proc.returncode}"
            )

        await self._connect_to_adapter(
            endpoints_file, self._connect_host, self._connect_port, existing_files_baseline
        )
        # Keep a reference to the reader task so it can be awaited/cancelled later
        self._reader_task_handle = asyncio.create_task(self._reader_task())

    async def _connect_to_adapter(
        self,
        endpoints_file: Optional[Path],
        override_host: Optional[str],
        override_port: Optional[int],
        existing_files_baseline: Optional[set] = None,
    ) -> None:
        timeout = 10.0  # Increased from 5.0 to handle Windows antivirus delays
        interval = 0.05

        if override_host is not None and override_port is not None:
            elapsed = 0.0
            log_debug(
                f"dap_stdio_client._connect_to_adapter: probing socket {override_host}:{override_port} for adapter"
            )
            while elapsed < timeout:
                if self.proc and self.proc.returncode is not None:
                    raise RuntimeError(
                        f"debugpy.adapter exited with code {self.proc.returncode}"
                    )
                try:
                    reader, writer = await asyncio.open_connection(
                        override_host, override_port
                    )
                except (ConnectionRefusedError, OSError):
                    await asyncio.sleep(interval)
                    elapsed += interval
                    continue

                log_debug(
                    f"dap_stdio_client: connected to adapter via reserved port {override_host}:{override_port}"
                )
                self._reader = reader
                self._writer = writer
                return

            log_debug(
                f"dap_stdio_client: timed out connecting to reserved port {override_host}:{override_port}"
            )
            if endpoints_file is None:
                raise TimeoutError(
                    f"Timed out waiting for debugpy.adapter on {override_host}:{override_port}"
                )
            log_debug("dap_stdio_client: falling back to endpoints file probing")

        if endpoints_file is None:
            raise RuntimeError(
                "No adapter endpoints file available for fallback connection strategy"
            )

        # WORKAROUND: On Windows MCP context, env vars don't pass through asyncio.create_subprocess_exec
        # So adapter creates its own random filename instead of using the one we specified
        # Solution: Look for ANY new endpoint file in the directory
        debugpy_dir = endpoints_file.parent

        # Use the baseline provided by caller, or capture current state
        if existing_files_baseline is not None:
            existing_files = existing_files_baseline
        else:
            existing_files = set(glob.glob(str(debugpy_dir / "debugpy-endpoints-*.json")))

        elapsed = 0.0
        log_debug(
            f"dap_stdio_client._connect_to_adapter: waiting up to {timeout}s for endpoints file (looking for new files in {debugpy_dir})"
        )
        actual_file = None
        while elapsed < timeout:
            if self.proc and self.proc.returncode is not None:
                raise RuntimeError(
                    f"debugpy.adapter exited with code {self.proc.returncode}"
                )
            # Check for any NEW endpoint file
            current_files = set(
                glob.glob(str(debugpy_dir / "debugpy-endpoints-*.json"))
            )
            new_files = current_files - existing_files
            if new_files:
                # Found a new file!
                actual_file = Path(list(new_files)[0])
                if actual_file.stat().st_size > 0:
                    log_debug(
                        f"dap_stdio_client: found new endpoint file: {actual_file.name}"
                    )
                    endpoints_file = actual_file  # Update to the actual file created
                    break
            await asyncio.sleep(interval)
            elapsed += interval
        else:
            log_debug("dap_stdio_client: waiting for endpoints timed out")
            # Capture stderr/stdout to see what went wrong
            if self.proc and self.proc.stderr:
                try:
                    stderr_data = await asyncio.wait_for(
                        self.proc.stderr.read(4096), timeout=1.0
                    )
                    if stderr_data:
                        log_debug(
                            f"dap_stdio_client: adapter stderr on timeout: {stderr_data.decode(errors='ignore')}"
                        )
                except asyncio.TimeoutError:
                    log_debug("dap_stdio_client: no stderr data available")
                except Exception as e:
                    log_debug(f"dap_stdio_client: error reading stderr: {e}")
            if self.proc and self.proc.stdout:
                try:
                    stdout_data = await asyncio.wait_for(
                        self.proc.stdout.read(4096), timeout=1.0
                    )
                    if stdout_data:
                        log_debug(
                            f"dap_stdio_client: adapter stdout on timeout: {stdout_data.decode(errors='ignore')}"
                        )
                except asyncio.TimeoutError:
                    log_debug("dap_stdio_client: no stdout data available")
                except Exception as e:
                    log_debug(f"dap_stdio_client: error reading stdout: {e}")
            log_debug(
                f"dap_stdio_client: process still running: {self.proc and self.proc.returncode is None}"
            )
            log_debug(
                f"dap_stdio_client: endpoints file exists: {endpoints_file.exists()}"
            )
            if endpoints_file.exists():
                log_debug(
                    f"dap_stdio_client: endpoints file size: {endpoints_file.stat().st_size}"
                )
            raise TimeoutError("Timed out waiting for debugpy.adapter endpoints")

        data = json.loads(endpoints_file.read_text())
        client_info = data.get("client")
        if not client_info:
            log_debug(f"dap_stdio_client: endpoints missing client info {data}")
            raise RuntimeError(f"Adapter did not provide client endpoint: {data}")

        host = client_info.get("host")
        port = client_info.get("port")
        if host is None or port is None:
            log_debug(
                f"dap_stdio_client: client endpoint missing host/port {client_info}"
            )
            raise RuntimeError(f"Adapter endpoint missing host/port: {client_info}")

        try:
            reader, writer = await asyncio.open_connection(host, port)
        except OSError as exc:
            log_debug(
                f"dap_stdio_client: failed to connect to adapter at {host}:{port} error={exc}"
            )
            raise RuntimeError(
                f"Unable to connect to debugpy.adapter at {host}:{port}: {exc}"
            ) from exc

        log_debug(f"dap_stdio_client: connected to adapter at {host}:{port}")

        self._reader = reader
        self._writer = writer

        try:
            endpoints_file.unlink()
        except OSError:
            pass

    async def _drain_stderr(self) -> None:
        """Continuously consume adapter stderr to surface useful diagnostics."""
        assert self.proc is not None and self.proc.stderr is not None
        stream = self.proc.stderr
        try:
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode(errors="replace").rstrip()
                if not text:
                    continue
                self._stderr_lines.append(text)
                log_debug(f"dap_stdio_client.stderr: {text}")
                if self._stderr_summary is None:
                    lowered = text.lower()
                    if (
                        "permissionerror" in lowered
                        or "operation not permitted" in lowered
                    ):
                        self._stderr_summary = text
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_debug(f"dap_stdio_client._drain_stderr error: {exc}")

    def _format_stderr_tail(self) -> Optional[str]:
        """Return the most recent stderr lines from the adapter."""
        if not self._stderr_lines:
            return None
        tail = list(self._stderr_lines)[-5:]
        pieces: List[str] = []
        if self._stderr_summary:
            pieces.append(self._stderr_summary)
        for entry in tail:
            if entry not in pieces:
                pieces.append(entry)
        return "\n".join(pieces)

    async def _send(self, msg: Dict[str, Any]):
        """Send a DAP message to the adapter."""
        if not self._writer:
            raise RuntimeError("Adapter connection not established")
        log_debug(
            f"dap_stdio_client._send: {msg.get('type')} {msg.get('command')} seq={msg.get('seq')}"
        )
        data = json.dumps(msg).encode("utf-8")
        header = f"Content-Length: {len(data)}\r\n\r\n".encode("ascii")
        self._writer.write(header + data)
        await self._writer.drain()

    async def _recv(self) -> Dict[str, Any]:
        """Receive a DAP message from the adapter."""
        if not self._reader:
            raise RuntimeError("Adapter connection not established")
        # Read headers
        content_length = None
        while True:
            line = await self._reader.readline()
            if not line:
                log_debug("dap_stdio_client._recv: adapter closed connection")
                detail = self._format_stderr_tail()

                # Check if process exited
                exit_code = None
                if self.proc and self.proc.returncode is not None:
                    exit_code = self.proc.returncode

                message = "Debug adapter connection closed"
                if exit_code is not None:
                    if exit_code == 0:
                        message += (
                            f" (program exited successfully with code {exit_code})"
                        )
                    else:
                        message += f" (program crashed with exit code {exit_code})"

                if detail:
                    message = f"{message}.\nAdapter stderr:\n{detail}"

                message += "\n\nTip: Use stop_on_entry=True or verify breakpoints are on executable lines"
                raise EOFError(message)
            if line == b"\r\n":
                break
            name, value = line.decode().split(":", 1)
            if name.lower() == "content-length":
                content_length = int(value.strip())
        assert content_length is not None
        body = await self._reader.readexactly(content_length)
        return json.loads(body.decode())

    async def _reader_task(self):
        """Background task that reads messages from the adapter."""
        try:
            while True:
                msg = await self._recv()
                # Response to a request we sent
                if "request_seq" in msg and msg.get("type") == "response":
                    fut = self._pending.pop(msg["request_seq"], None)
                    if fut and not fut.done():
                        fut.set_result(msg)
                # Adapter-emitted event
                elif msg.get("type") == "event":
                    event_name = msg.get("event")
                    log_debug(f"dap_stdio_client: received event {event_name}")
                    if event_name == "initialized":
                        self._initialized_event.set()
                    await self._events.put(msg)
                # Adapter -> client request (reverse request)
                elif msg.get("type") == "request":
                    log_debug(f"dap_stdio_client: reverse request {msg.get('command')}")
                    await self._handle_adapter_request(msg)
        except Exception as e:
            self._closed_exception = e
            log_debug(f"dap_stdio_client._reader_task error: {e}")
            if self._writer:
                try:
                    self._writer.close()
                except Exception:
                    pass
                self._writer = None
            self._reader = None
            for fut in list(self._pending.values()):
                if not fut.done():
                    fut.set_exception(e)

    async def request(self, command: str, arguments: Optional[Dict[str, Any]] = None):
        """Send a DAP request and wait for the response."""
        if self._closed_exception is not None:
            exc_type = type(self._closed_exception).__name__
            raise RuntimeError(
                f"Debug adapter connection closed unexpectedly.\n"
                f"Reason: {exc_type}: {self._closed_exception}\n\n"
                f"Common causes:\n"
                f"  - Program finished executing before breakpoint was hit\n"
                f"  - Program crashed with an unhandled exception\n"
                f"  - Breakpoint set on non-executable line (e.g., function definition)\n\n"
                f"Suggestions:\n"
                f"  - Use stop_on_entry=True in dap_launch() for full control\n"
                f"  - Set breakpoints on executable lines inside functions, not on 'def' lines\n"
                f"  - Set breakpoints where functions are called, then use dap_step_in()"
            )
        if self.proc and self.proc.returncode is not None:
            if self.proc.returncode == 0:
                raise RuntimeError(
                    f"Debug adapter process exited successfully (code {self.proc.returncode}).\n"
                    f"The program finished executing before the debugger could complete the operation.\n\n"
                    f"Suggestions:\n"
                    f"  - Use stop_on_entry=True to pause execution immediately\n"
                    f"  - Verify breakpoints are on executable lines\n"
                    f"  - Check if program logic reaches the breakpoint location"
                )
            else:
                raise RuntimeError(
                    f"Debug adapter process crashed (exit code {self.proc.returncode}).\n"
                    f"The program terminated with an error.\n\n"
                    f"Check the program output and stderr for error messages."
                )
        if not self._writer:
            raise RuntimeError("debug adapter connection not available")
        rid = next(self._seq)
        fut = asyncio.get_event_loop().create_future()
        self._pending[rid] = fut
        req = {
            "seq": rid,
            "type": "request",
            "command": command,
            "arguments": arguments or {},
        }
        await self._send(req)
        return await fut

    async def wait_for_event(self, name: str, timeout: Optional[float] = 5.0):
        """Wait for a specific DAP event."""
        while True:
            if timeout is None:
                msg = await self._events.get()
            else:
                msg = await asyncio.wait_for(self._events.get(), timeout=timeout)
            if msg.get("event") == name:
                return msg

    async def wait_for_initialized(self, timeout: Optional[float] = 5.0):
        """Wait until the adapter reports it is initialized."""
        if self._initialized_event.is_set():
            return
        if timeout is None:
            await self._initialized_event.wait()
        else:
            await asyncio.wait_for(self._initialized_event.wait(), timeout=timeout)

    def initialized_received(self) -> bool:
        """True if an 'initialized' event has been observed."""
        return self._initialized_event.is_set()

    # DAP protocol methods
    async def initialize(self):
        """Send initialize request."""
        return await self.request(
            "initialize",
            {
                "clientID": "mvp-stdio",
                "adapterID": "python",
                "pathFormat": "path",
                "linesStartAt1": True,
                "columnsStartAt1": True,
                "supportsRunInTerminalRequest": False,
                "supportsStartDebuggingRequest": False,
                "supportsConfigurationDoneRequest": True,
            },
        )

    async def configurationDone(self):
        """Signal that configuration is complete."""
        return await self.request("configurationDone", {})

    async def setBreakpoints(self, source_path: str, lines: List[int]):
        """Set breakpoints in a source file."""
        return await self.request(
            "setBreakpoints",
            {
                "source": {"path": source_path},
                "breakpoints": [{"line": line} for line in lines],
            },
        )

    async def launch(self, program: str, **kwargs):
        """Launch a program under the debugger."""
        args = {
            "name": "launch-mvp",
            "type": "python",
            "request": "launch",
            "program": program,
            "console": "internalConsole",
        }
        args.update(kwargs)
        return await self.request("launch", args)

    async def attach(self, connect_host: str, connect_port: int, **kwargs):
        """Attach to a running debugpy.listen() session."""
        args = {"connect": {"host": connect_host, "port": connect_port}}
        args.update(kwargs)
        return await self.request("attach", args)

    async def threads(self):
        """Get list of threads."""
        return await self.request("threads", {})

    async def continue_(self, threadId: int):
        """Continue execution."""
        return await self.request("continue", {"threadId": threadId})

    async def next(self, threadId: int):
        """Step over."""
        return await self.request("next", {"threadId": threadId})

    async def stepIn(self, threadId: int):
        """Step into the next function call."""
        return await self.request("stepIn", {"threadId": threadId})

    async def stepOut(self, threadId: int):
        """Step out of the current function."""
        return await self.request("stepOut", {"threadId": threadId})

    async def stackTrace(self, threadId: int):
        """Get stack trace for a thread."""
        return await self.request("stackTrace", {"threadId": threadId})

    async def scopes(self, frameId: int):
        """Get scopes for a stack frame."""
        return await self.request("scopes", {"frameId": frameId})

    async def variables(self, variablesReference: int):
        """Get variables for a scope."""
        return await self.request(
            "variables", {"variablesReference": variablesReference}
        )

    async def setExceptionBreakpoints(self, filters: Optional[List[str]] = None):
        """Configure exception breakpoints (empty list to disable)."""
        payload: Dict[str, Any] = {"filters": filters or []}
        return await self.request("setExceptionBreakpoints", payload)

    async def close(self):
        """Close the adapter connection."""
        log_debug("dap_stdio_client.close: shutting down adapter connection")
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
        self._reader = None

        if self.proc:
            if self.proc.returncode is None:
                self.proc.terminate()
                try:
                    await asyncio.wait_for(self.proc.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    self.proc.kill()
                    await self.proc.wait()
            self.proc = None
        if self._stderr_task:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._stderr_task = None

        if self._endpoints_file and self._endpoints_file.exists():
            try:
                self._endpoints_file.unlink()
            except OSError:
                pass
            self._endpoints_file = None

    async def _handle_adapter_request(self, msg: Dict[str, Any]):
        """Dispatch adapter-originated requests."""
        cmd = msg.get("command")
        if cmd == "runInTerminal":
            ok, body = await self._handle_run_in_terminal(msg)
            response = {
                "seq": next(self._seq),
                "type": "response",
                "request_seq": msg.get("seq"),
                "success": bool(ok),
                "command": cmd,
            }
            if ok:
                response["body"] = body or {}
            await self._send(response)
        else:
            # Fail fast on unsupported reverse requests so adapters do not hang.
            await self._send(
                {
                    "seq": next(self._seq),
                    "type": "response",
                    "request_seq": msg.get("seq"),
                    "success": False,
                    "command": cmd,
                    "message": f"Client does not implement '{cmd}'",
                }
            )

    async def _handle_run_in_terminal(
        self, req: Dict[str, Any]
    ) -> tuple[bool, Optional[Dict[str, Any]]]:
        """runInTerminal is disabled for security; do not execute external commands."""
        return False, None
