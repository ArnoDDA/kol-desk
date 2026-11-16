@echo off
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 launch.py
) else (
  python launch.py
)
if errorlevel 1 pause
