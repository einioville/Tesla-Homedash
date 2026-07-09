@echo off
rem Wrapper so the PowerShell build script runs from cmd.exe. Forwards all args.
powershell -ExecutionPolicy Bypass -File "%~dp0build-frontend.ps1" %*
