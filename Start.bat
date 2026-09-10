@echo off
cd /d "%~dp0"
start "" pythonw "%~dp0run.py"
if errorlevel 1 pause
