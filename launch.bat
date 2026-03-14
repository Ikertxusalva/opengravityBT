@echo off
title OpenGravity Launcher

:: Kill any orphaned processes from previous sessions
taskkill /F /IM electron.exe >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8888" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

:: Launch app
cd /d "%~dp0opengravity-app"
npm run dev
pause
