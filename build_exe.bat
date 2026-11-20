@echo off
rem Builds AutoClicker.exe (see build_exe.ps1). Double-click this file.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_exe.ps1" %*
