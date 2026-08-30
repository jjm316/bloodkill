@echo off
rem Thin wrapper for: test_toolkit.py build
cd /d "%~dp0.."
".venv\Scripts\python.exe" scripts\test_toolkit.py build %*
pause
