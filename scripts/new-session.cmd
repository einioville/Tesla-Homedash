@echo off
rem Wrapper so the PowerShell session script runs from cmd.exe. Forwards all args.
powershell -ExecutionPolicy Bypass -File "%~dp0new-session.ps1" %*
