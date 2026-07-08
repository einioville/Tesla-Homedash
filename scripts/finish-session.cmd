@echo off
rem Wrapper so the PowerShell finish script runs from cmd.exe. Forwards all args.
powershell -ExecutionPolicy Bypass -File "%~dp0finish-session.ps1" %*
