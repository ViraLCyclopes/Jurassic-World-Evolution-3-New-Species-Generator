@echo off
REM Standalone PPUIPKG inspector - open ANY .ppuipkg, no mod project needed.
REM Optionally drag a .ppuipkg onto this file to open it directly.
cd /d "%~dp0"
python ppuipkg_tool.py %1
if errorlevel 1 pause
