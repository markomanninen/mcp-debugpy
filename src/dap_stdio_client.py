import asyncio
import json
import itertools
import os
import subprocess
import sys
import tempfile
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

from debug_utils import log_debug


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

    def _get_python_executable(self) -> Path:
        """Get the correct Python executable, preferring virtual environment if available."""
        # Check if we're in a virtual environment
        venv_path = Path.cwd() / ".venv" / "bin" / "python"
        if venv_path.exists():
            return venv_path

        # Check for other common venv locations
        for venv_name in [".venv", "venv", "env"]:
            venv_python = Path.cwd() / venv_name / "bin" / "python"
            if venv_python.exists():
                return venv_python

        # Fall back to sys.executable
        return Path(sys.executable)

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

        env = os.environ.copy()
        fd, path = tempfile.mkstemp(prefix="debugpy-endpoints-", suffix=".json")
        os.close(fd)
        endpoints_file = Path(path)
        try:
            endpoints_file.unlink()
        except FileNotFoundError:
            pass
        env["DEBUGPY_ADAPTER_ENDPOINTS"] = str(endpoints_file)

        log_debug(
            f"dap_stdio_client.start: launching adapter cmd={self.adapter_cmd} env_file={endpoints_file}"
        )
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *self.adapter_cmd,
                "--host",
                "127.0.0.1",
                "--port",
                "0",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
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
            stderr_data = await self.proc.stderr.read() if self.proc.stderr else b""
            stdout_data = await self.proc.stdout.read() if self.proc.stdout else b""
            log_debug(
                f"dap_stdio_client.start: adapter exited early with code {self.proc.returncode}"
            )
            log_debug(f"dap_stdio_client.start: adapter stderr: {stderr_data.decode()}")
            log_debug(f"dap_stdio_client.start: adapter stdout: {stdout_data.decode()}")
            raise RuntimeError(
                f"debugpy.adapter exited early with code {self.proc.returncode}"
            )

        await self._connect_to_adapter(endpoints_file)
        if self.proc.stderr:
            self._stderr_task = asyncio.create_task(self._drain_stderr())
        # Keep a reference to the reader task so it can be awaited/cancelled later
        self._reader_task_handle = asyncio.create_task(self._reader_task())

    async def _connect_to_adapter(self, endpoints_file: Path) -> None:
        timeout = 5.0
        interval = 0.05
        elapsed = 0.0
        while elapsed < timeout:
            if self.proc and self.proc.returncode is not None:
                raise RuntimeError(
                    f"debugpy.adapter exited with code {self.proc.returncode}"
                )
            if endpoints_file.exists() and endpoints_file.stat().st_size > 0:
                break
            await asyncio.sleep(interval)
            elapsed += interval
        else:
            log_debug("dap_stdio_client: waiting for endpoints timed out")
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
                message = "Adapter stdout closed"
                if detail:
                    message = f"{message}. Adapter stderr tail:\n{detail}"
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
            raise RuntimeError(
                f"debug adapter connection closed: {self._closed_exception}"
            )
        if self.proc and self.proc.returncode is not None:
            raise RuntimeError(f"debug adapter exited with code {self.proc.returncode}")
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
        """Minimal handler for runInTerminal; fire-and-forget subprocess."""
        try:
            arguments = req.get("arguments") or {}
            cmd = arguments.get("args") or []
            if isinstance(cmd, str):
                cmd = [cmd]
            if not cmd:
                return False, None

            cwd = arguments.get("cwd")
            env_overrides = arguments.get("env") or {}
            env = os.environ.copy()
            for key, value in env_overrides.items():
                if value is None:
                    env.pop(key, None)
                else:
                    env[key] = value

            proc = subprocess.Popen(cmd, cwd=cwd, env=env)
            body = {
                "processId": proc.pid or 0,
                "shellProcessId": 0,
            }
            return True, body
        except Exception:
            return False, None
