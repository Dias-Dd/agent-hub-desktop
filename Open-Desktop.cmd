@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0..\AgentMessageHubDesktop.exe" (
 start "" "%~dp0..\AgentMessageHubDesktop.exe"
) else (
 start "" pythonw desktop\launch_desktop.py
)
