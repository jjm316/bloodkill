@echo off
rem Thin wrapper for: test_toolkit.py down
cd /d "%~dp0.."
".venv\Scripts\python.exe" scripts\test_toolkit.py down %*
pause
