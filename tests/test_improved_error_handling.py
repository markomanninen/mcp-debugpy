"""Tests for improved error handling and validation features."""

import asyncio
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest

import mcp_server
from dap_stdio_client import StdioDAPClient


@pytest.fixture(autouse=True)
def reset_mcp_client():
    """Ensure a clean client between tests."""
    mcp_server._dap_client = None
    yield
    mcp_server._dap_client = None


class TestBreakpointValidation:
    """Test suite for dap_validate_breakpoint_line tool."""

    @pytest.mark.asyncio
    async def test_validate_function_definition_line(self):
        """Test that function definition lines are flagged as invalid."""
        # Create a temporary Python file with a function
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def my_function():\n")
            f.write("    return 42\n")
            temp_path = f.name

        try:
            result = await mcp_server.dap_validate_breakpoint_line(temp_path, 1)

            assert result["isValid"] is False
            assert "This is a function definition line" in result["warnings"]
            assert len(result["suggestions"]) > 0
            assert any("line 2" in s for s in result["suggestions"])
            assert result["content"] == "def my_function():"
        finally:
            Path(temp_path).unlink()

    @pytest.mark.asyncio
    async def test_validate_async_function_definition(self):
        """Test that async function definitions are flagged."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("async def async_function():\n")
            f.write("    await something()\n")
            temp_path = f.name

        try:
            result = await mcp_server.dap_validate_breakpoint_line(temp_path, 1)

            assert result["isValid"] is False
            assert "This is a function definition line" in result["warnings"]
            assert "dap_step_in()" in str(result["suggestions"])
        finally:
            Path(temp_path).unlink()

    @pytest.mark.asyncio
    async def test_validate_class_definition(self):
        """Test that class definitions are flagged."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("class MyClass:\n")
            f.write("    def __init__(self):\n")
            f.write("        pass\n")
            temp_path = f.name

        try:
            result = await mcp_server.dap_validate_breakpoint_line(temp_path, 1)

            assert result["isValid"] is False
            assert "This is a class definition line" in result["warnings"]
            assert any("__init__" in s for s in result["suggestions"])
        finally:
            Path(temp_path).unlink()

    @pytest.mark.asyncio
    async def test_validate_comment_line(self):
        """Test that comments are flagged."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("# This is a comment\n")
            f.write("x = 5\n")
            temp_path = f.name

        try:
            result = await mcp_server.dap_validate_breakpoint_line(temp_path, 1)

            assert result["isValid"] is False
            assert "This is a comment or blank line" in result["warnings"]
            assert any("line 2" in s and "x = 5" in s for s in result["suggestions"])
        finally:
            Path(temp_path).unlink()

    @pytest.mark.asyncio
    async def test_validate_blank_line(self):
        """Test that blank lines are flagged."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("\n")
            f.write("print('hello')\n")
            temp_path = f.name

        try:
            result = await mcp_server.dap_validate_breakpoint_line(temp_path, 1)

            assert result["isValid"] is False
            assert "This is a comment or blank line" in result["warnings"]
        finally:
            Path(temp_path).unlink()

    @pytest.mark.asyncio
    async def test_validate_import_statement(self):
        """Test that import statements are flagged."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("import os\n")
            f.write("from pathlib import Path\n")
            temp_path = f.name

        try:
            # Test regular import
            result = await mcp_server.dap_validate_breakpoint_line(temp_path, 1)
            assert result["isValid"] is False
            assert "This is an import statement" in result["warnings"]

            # Test from import
            result = await mcp_server.dap_validate_breakpoint_line(temp_path, 2)
            assert result["isValid"] is False
            assert "This is an import statement" in result["warnings"]
        finally:
            Path(temp_path).unlink()

    @pytest.mark.asyncio
    async def test_validate_executable_line(self):
        """Test that valid executable lines pass validation."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def my_function():\n")
            f.write("    x = 42\n")
            f.write("    return x\n")
            temp_path = f.name

        try:
            # Line 2 should be valid
            result = await mcp_server.dap_validate_breakpoint_line(temp_path, 2)
            assert result["isValid"] is True
            assert len(result["warnings"]) == 0
            assert result["content"] == "x = 42"

            # Line 3 should also be valid
            result = await mcp_server.dap_validate_breakpoint_line(temp_path, 3)
            assert result["isValid"] is True
            assert len(result["warnings"]) == 0
        finally:
            Path(temp_path).unlink()

    @pytest.mark.asyncio
    async def test_validate_nonexistent_file(self):
        """Test validation of a file that doesn't exist."""
        result = await mcp_server.dap_validate_breakpoint_line(
            "/nonexistent/file.py", 1
        )

        assert "error" in result
        assert "File not found" in result["error"]

    @pytest.mark.asyncio
    async def test_validate_line_out_of_range(self):
        """Test validation with line number out of range."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("x = 1\n")
            temp_path = f.name

        try:
            result = await mcp_server.dap_validate_breakpoint_line(temp_path, 100)

            assert "error" in result
            assert "Line number out of range" in result["error"]
            assert result["line"] == 100
            assert result["total_lines"] == 1
        finally:
            Path(temp_path).unlink()


class TestImprovedErrorMessages:
    """Test suite for improved error messages in DAP client."""

    @pytest.mark.asyncio
    async def test_error_message_for_closed_connection(self):
        """Test that closed connection errors include helpful context."""
        client = StdioDAPClient()

        # Simulate a closed connection by setting the exception
        client._closed_exception = EOFError("Connection closed")

        with pytest.raises(RuntimeError) as exc_info:
            await client.request("threads")

        error_message = str(exc_info.value)
        assert "Debug adapter connection closed unexpectedly" in error_message
        assert "Common causes:" in error_message
        assert "Program finished executing" in error_message
        assert "Breakpoint set on non-executable line" in error_message
        assert "Suggestions:" in error_message
        assert "stop_on_entry=True" in error_message

    @pytest.mark.asyncio
    async def test_error_message_for_successful_exit(self, monkeypatch):
        """Test error message when program exits successfully."""
        client = StdioDAPClient()

        # Mock the process with a successful exit code
        class MockProcess:
            returncode = 0

        client.proc = MockProcess()

        with pytest.raises(RuntimeError) as exc_info:
            await client.request("threads")

        error_message = str(exc_info.value)
        assert "exited successfully (code 0)" in error_message
        assert "finished executing before the debugger" in error_message
        assert "stop_on_entry=True" in error_message
        assert "Verify breakpoints are on executable lines" in error_message

    @pytest.mark.asyncio
    async def test_error_message_for_program_crash(self, monkeypatch):
        """Test error message when program crashes."""
        client = StdioDAPClient()

        # Mock the process with a crash exit code
        class MockProcess:
            returncode = 1

        client.proc = MockProcess()

        with pytest.raises(RuntimeError) as exc_info:
            await client.request("threads")

        error_message = str(exc_info.value)
        assert "crashed (exit code 1)" in error_message
        assert "terminated with an error" in error_message
        assert "Check the program output and stderr" in error_message

    @pytest.mark.asyncio
    async def test_recv_error_includes_exit_code(self, monkeypatch):
        """Test that _recv() includes exit code in error messages."""
        client = StdioDAPClient()

        # Mock a reader that returns empty (EOF)
        class MockReader:
            async def readline(self):
                return b""

        class MockProcess:
            returncode = 0

        client._reader = MockReader()
        client.proc = MockProcess()
        monkeypatch.setattr(client, "_format_stderr_tail", lambda: None)

        with pytest.raises(EOFError) as exc_info:
            await client._recv()

        error_message = str(exc_info.value)
        assert "program exited successfully with code 0" in error_message
        assert "stop_on_entry=True" in error_message
        assert "verify breakpoints are on executable lines" in error_message

    @pytest.mark.asyncio
    async def test_recv_error_with_crash_exit_code(self, monkeypatch):
        """Test that _recv() detects crash exit codes."""
        client = StdioDAPClient()

        class MockReader:
            async def readline(self):
                return b""

        class MockProcess:
            returncode = 137  # Killed by signal

        client._reader = MockReader()
        client.proc = MockProcess()
        monkeypatch.setattr(client, "_format_stderr_tail", lambda: None)

        with pytest.raises(EOFError) as exc_info:
            await client._recv()

        error_message = str(exc_info.value)
        assert "program crashed with exit code 137" in error_message


class TestDocstringImprovements:
    """Test that improved docstrings are present."""

    def test_dap_launch_has_pitfalls_section(self):
        """Test that dap_launch docstring includes Common Pitfalls section."""
        docstring = mcp_server.dap_launch.__doc__

        assert docstring is not None
        assert "Common Pitfalls to Avoid:" in docstring
        assert "Don't set breakpoints on function definitions" in docstring
        assert "Use stop_on_entry for full control" in docstring
        assert "Prefer function call locations" in docstring

    def test_dap_launch_has_recommended_pattern(self):
        """Test that dap_launch docstring includes Recommended Debugging Pattern."""
        docstring = mcp_server.dap_launch.__doc__

        assert docstring is not None
        assert "Recommended Debugging Pattern:" in docstring
        assert "Good: Break where function is called" in docstring
        assert "Also good: Break on first executable line" in docstring
        assert "Avoid: Breaking on function definition" in docstring

    def test_dap_validate_breakpoint_line_has_docstring(self):
        """Test that new validation tool has proper docstring."""
        docstring = mcp_server.dap_validate_breakpoint_line.__doc__

        assert docstring is not None
        assert "Validate if a line number is a good breakpoint location" in docstring
        assert "function/class definitions" in docstring
        assert "comments or blank lines" in docstring
        assert "import statements" in docstring
