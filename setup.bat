@echo off
REM Setup script for mcp-debugpy (Windows)

echo ========================================
echo Setting up mcp-debugpy development environment
echo ========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.8 or higher.
    exit /b 1
)

REM Create virtual environment
echo Creating virtual environment...
python -m venv .venv
if errorlevel 1 (
    echo ERROR: Failed to create virtual environment
    exit /b 1
)
echo.

REM Activate virtual environment
echo Activating virtual environment...
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment
    exit /b 1
)
echo.

REM Upgrade pip
echo Upgrading pip...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo WARNING: Failed to upgrade pip, continuing anyway...
)
echo.

REM Install runtime dependencies
echo Installing runtime dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install runtime dependencies
    exit /b 1
)
echo.

REM Install development dependencies
echo Installing development dependencies...
pip install -r requirements-dev.txt
if errorlevel 1 (
    echo ERROR: Failed to install development dependencies
    exit /b 1
)
echo.

REM Run smoke tests
echo ========================================
echo Smoke-testing MCP tooling and examples
echo ========================================
python -m pytest tests\test_mcp_server.py examples\math_bug\tests examples\async_worker\tests examples\gui_counter\tests examples\web_flask\tests
REM Continue even if tests fail (|| true equivalent)
echo.

REM Display next steps
echo ========================================
echo Setup complete!
echo ========================================
echo.
echo Next steps:
echo   .venv\Scripts\activate
echo   python scripts\configure_mcp_clients.py  # register VS Code / Claude MCP entries
echo   # ...or follow docs\mcp_usage.md for manual configuration details
echo   python src\dap_stdio_direct.py           # optional direct adapter walkthrough
echo   # After configuration, use your MCP chat to call run_tests_json, dap_launch, etc.
echo.
echo Each example README (examples\*\README.md) shows how to launch via dap_launch.
echo.
pause
