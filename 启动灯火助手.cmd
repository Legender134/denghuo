@echo off
cd /d "%~dp0"
if exist "%LocalAppData%\Programs\Denghuo\灯火.exe" (
    start "" "%LocalAppData%\Programs\Denghuo\灯火.exe"
    exit /b
)
if exist "%~dp0灯火程序\灯火.exe" (
    start "" "%~dp0灯火程序\灯火.exe"
    exit /b
)
if exist "%LocalAppData%\Programs\Python\Python313\pythonw.exe" (
    start "" "%LocalAppData%\Programs\Python\Python313\pythonw.exe" "%~dp0launch.pyw"
    exit /b
)
where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw -3 "%~dp0launch.pyw"
    exit /b
)
python -m companion
if errorlevel 1 pause
