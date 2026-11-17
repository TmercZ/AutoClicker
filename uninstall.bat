@echo off
rem Removes the installed app and its shortcuts.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -Uninstall %*
