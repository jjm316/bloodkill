@echo off
rem Thin wrapper for: test_toolkit.py up --players 7 (extra args pass through via %*)
cd /d "%~dp0.."
".venv\Scripts\python.exe" scripts\test_toolkit.py up --players 7 %*
pause
