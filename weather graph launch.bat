@echo off
cd /d "%~dp0"
setlocal enabledelayedexpansion
title WeatherSnake Launcher

:: ---------------------------------------------------------------
:: Launch WeatherSnake — auto-installs Python, fetches source,
:: sets up venv, installs deps, and launches the app.
:: ---------------------------------------------------------------

set "APP_DIR=%~dp0"
set "GIT_REPO=https://github.com/deanable/WeatherSnake.git"
set "PYTHON="

:: ── 1. Check / fetch application source ─────────────────────────
if not exist "!APP_DIR!ui_app.pyw" (
    echo [INFO] Application source not found. Downloading from GitHub...
    where git >nul 2>&1
    if !errorlevel! equ 0 (
        git clone "!GIT_REPO!" "!APP_DIR!"
        if !errorlevel! neq 0 (
            echo [ERROR] Git clone failed. Check your connection.
            pause
            exit /b 1
        )
        cd /d "!APP_DIR!"
    ) else (
        echo [WARN] Git not found. Downloading via PowerShell...
        powershell -Command "
            $tmp = [System.IO.Path]::GetTempPath();
            $zip = $tmp + 'WeatherSnake.zip';
            $out = '!APP_DIR!';
            Write-Host 'Downloading repository ZIP...';
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;
            Invoke-WebRequest -Uri 'https://github.com/deanable/WeatherSnake/archive/refs/heads/main.zip' -OutFile $zip;
            Write-Host 'Extracting...';
            Expand-Archive -LiteralPath $zip -DestinationPath $tmp -Force;
            $src = $tmp + 'WeatherSnake-main\*';
            Move-Item -Path $src -Destination $out -Force;
            Remove-Item -LiteralPath $zip;
            Write-Host 'Done.';
        "
        if !errorlevel! neq 0 (
            echo [ERROR] Failed to download source.
            pause
            exit /b 1
        )
        cd /d "!APP_DIR!"
    )
)

:: ── 2. Locate Python ───────────────────────────────────────────
for %%p in (python python3 py) do (
    where %%p >nul 2>&1 && (
        for /f "delims=" %%v in ('%%p --version 2^>nul') do set "PYTHON=%%p"
        goto :found_py
    )
)

:: ── 3. Python not found — install ──────────────────────────────
echo [INFO] Python not found. Attempting installation via winget...
winget install --id Python.Python.3.13 --silent --accept-package-agreements >nul 2>&1
if errorlevel 1 (
    echo [WARN] winget install failed. Falling back to direct download...
    powershell -Command "
        $url = 'https://www.python.org/ftp/python/3.13.3/python-3.13.3-amd64.exe';
        $out = [System.IO.Path]::GetTempPath() + 'python-installer.exe';
        Write-Host 'Downloading Python 3.13...';
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;
        Invoke-WebRequest -Uri $url -OutFile $out;
        Start-Process $out -ArgumentList '/quiet InstallAllUsers=1 PrependPath=1' -Wait;
    "
)
echo [INFO] Refreshing PATH from registry...
for /f "skip=2 tokens=2*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "PATH=%%b;%PATH%"
for /f "skip=2 tokens=2*" %%a in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "PATH=%%b;%PATH%"

:: Try to find Python again after install
for %%p in (python python3 py) do (
    where %%p >nul 2>&1 && (
        for /f "delims=" %%v in ('%%p --version 2^>nul') do set "PYTHON=%%p"
        goto :found_py
    )
)
:: Check common install locations as a last resort
for %%d in (
    "C:\Program Files\Python313\python.exe"
    "C:\Program Files\Python313\python3.exe"
    "%LocalAppData%\Programs\Python\Python313\python.exe"
) do (
    if exist %%d (
        set "PYTHON=%%~d"
        goto :found_py
    )
)

:found_py
if "!PYTHON!"=="" (
    echo [ERROR] Could not locate Python. Install it from https://python.org, then re-run.
    pause
    exit /b 1
)

echo [INFO] Using !PYTHON!:
"!PYTHON!" --version

:: ── 4. Virtual environment ─────────────────────────────────────
if not exist ".venv\Scripts\activate.bat" (
    echo [INFO] Creating virtual environment...
    "!PYTHON!" -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

:: ── 5. Install dependencies ────────────────────────────────────
if exist "requirements.txt" (
    echo [INFO] Installing dependencies...
    .venv\Scripts\python.exe -m pip install --upgrade pip -q
    .venv\Scripts\python.exe -m pip install -r requirements.txt -q
)

:: ── 6. Launch ──────────────────────────────────────────────────
echo [INFO] Starting WeatherSnake...
start "" .venv\Scripts\pythonw.exe "!APP_DIR!ui_app.pyw"
exit /b 0
