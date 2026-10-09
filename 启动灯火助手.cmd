@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if exist "%~dp0灯火程序\灯火.exe" (
    start "" "%~dp0灯火程序\灯火.exe" %*
    exit /b 0
)
if exist "%~dp0灯火.exe" (
    start "" "%~dp0灯火.exe" %*
    exit /b 0
)
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0launch.pyw" %*
    exit /b 0
)
if exist "%~dp0.venv\Scripts\python.exe" goto source_console
if exist "%LocalAppData%\Programs\Denghuo\灯火.exe" (
    start "" "%LocalAppData%\Programs\Denghuo\灯火.exe" %*
    exit /b 0
)
where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw -3 "%~dp0launch.pyw" %*
    exit /b 0
)
where py >nul 2>nul
if not errorlevel 1 goto use_py
python "%~dp0launch.pyw" %*
set "DENGHUO_EXIT_CODE=%errorlevel%"
if not "%DENGHUO_EXIT_CODE%"=="0" pause
exit /b %DENGHUO_EXIT_CODE%
:source_console
"%~dp0.venv\Scripts\python.exe" "%~dp0launch.pyw" %*
exit /b %errorlevel%
:use_py
py -3 "%~dp0launch.pyw" %*
exit /b %errorlevel%
