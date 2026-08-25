@echo off
REM ---------------------------------------------------------------------------
REM  Arka ucu baslatir (Docker'siz).
REM  Bu dosyaya cift tiklayin ve pencereyi acik birakin.
REM ---------------------------------------------------------------------------
setlocal enabledelayedexpansion
cd /d "%~dp0\..\backend"

REM Sanal ortam yoksa kur. "python" PATH'te olmayabilir; Windows'un "py"
REM baslaticisi genelde vardir, o yuzden ikisi de denenir.
if not exist ".venv\Scripts\python.exe" (
    echo Python ortami ilk kez kuruluyor...
    set "PY_CMD="
    where py >nul 2>&1 && set "PY_CMD=py"
    if not defined PY_CMD (
        where python >nul 2>&1 && set "PY_CMD=python"
    )
    if not defined PY_CMD (
        echo.
        echo Python bulunamadi. python.org adresinden 3.11 veya uzerini kurun
        echo ve kurulumda "Add python.exe to PATH" secenegini isaretleyin.
        pause
        exit /b 1
    )
    !PY_CMD! -m venv .venv
    if errorlevel 1 (
        echo Sanal ortam olusturulamadi.
        pause
        exit /b 1
    )
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Paket kurulumu basarisiz oldu.
        pause
        exit /b 1
    )
)

REM .env yoksa ornekten uret ve calisir bir SECRET_KEY yaz. Bos bir SECRET_KEY
REM ile uygulama acilmaz, ve yeni bir makinede bunu elle fark etmek zordur.
if not exist "..\.env" (
    echo .env bulunamadi, ornekten olusturuluyor...
    copy /y "..\.env.example" "..\.env" >nul
    for /f "delims=" %%K in ('.venv\Scripts\python.exe -c "import secrets;print(secrets.token_urlsafe(48))"') do (
        powershell -NoProfile -Command "(Get-Content '..\.env') -replace '^SECRET_KEY=$', 'SECRET_KEY=%%K' | Set-Content '..\.env'"
    )
    echo .env olusturuldu. Binance anahtarlari bos - panelden girebilirsiniz.
)

echo.
echo Arka uc baslatiliyor: http://localhost:8000
echo API dokumantasyonu:   http://localhost:8000/docs
echo Durdurmak icin Ctrl+C.
echo.
REM Yalnizca 127.0.0.1 dinler: bu uygulamada kimlik dogrulama yok ve acil
REM durdurma dahil her kontrol acik, o yuzden yerel agdan erisilebilir
REM olmamali. Panel /api isteklerini kendi sunucusundan vekillendirdigi
REM icin tarayicinin arka uca dogrudan baglanmasi gerekmiyor.
REM API dokumantasyonu icin http://127.0.0.1:8000/docs kullanin.
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
