@echo off
rem Thin wrapper for: test_toolkit.py serve
cd /d "%~dp0.."
".venv\Scripts\python.exe" scripts\test_toolkit.py serve %*
pause
