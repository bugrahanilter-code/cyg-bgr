@echo off
REM ---------------------------------------------------------------------------
REM  Kontrol panelini baslatir (Docker'siz).
REM  Once arka ucu baslatin, sonra bu dosyaya cift tiklayin.
REM
REM  Node PATH'te olmayabilir - Windows kurulumlari sik sik oraya eklemez - bu
REM  yuzden once bilinen konumlara bakilir. Aksi halde bu betik, Node kurulu
REM  oldugu halde "kurulu degil" derdi.
REM ---------------------------------------------------------------------------
setlocal enabledelayedexpansion
cd /d "%~dp0\..\frontend"

set "NPM_CMD="
where npm >nul 2>&1 && set "NPM_CMD=npm"

if not defined NPM_CMD (
    for %%D in (
        "%ProgramFiles%\nodejs"
        "%ProgramFiles(x86)%\nodejs"
        "%LOCALAPPDATA%\Programs\nodejs"
    ) do (
        if exist "%%~D\npm.cmd" (
            set "PATH=%%~D;!PATH!"
            set "NPM_CMD=npm"
        )
    )
)

if not defined NPM_CMD (
    echo.
    echo Node.js bulunamadi.
    echo   1. https://nodejs.org adresinden LTS surumunu kurun
    echo   2. Bu pencereyi kapatip yeniden acin
    echo.
    pause
    exit /b 1
)

for /f "delims=" %%V in ('node --version') do echo Node %%V bulundu.

if not exist "node_modules" (
    echo Panel paketleri ilk kez kuruluyor, bu birkac dakika surebilir...
    call npm install
    if errorlevel 1 (
        echo.
        echo Paket kurulumu basarisiz oldu.
        pause
        exit /b 1
    )
)

echo.
echo Panel baslatiliyor: http://localhost:3000
echo Durdurmak icin Ctrl+C.
echo.
call npm run dev
pause
