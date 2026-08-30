@echo off
rem Thin wrapper for: test_toolkit.py status
cd /d "%~dp0.."
".venv\Scripts\python.exe" scripts\test_toolkit.py status %*
pause
