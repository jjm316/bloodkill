@echo off
rem Thin wrapper for: test_toolkit.py close
cd /d "%~dp0.."
".venv\Scripts\python.exe" scripts\test_toolkit.py close %*
pause
