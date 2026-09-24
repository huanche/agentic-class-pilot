@echo off
REM One-click start. Double-click this file to run a lesson.
cd /d "%~dp0"

set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" apps\start.py %*
if errorlevel 1 pause
