@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo === LensLingo ===

REM Sanal ortam yoksa olustur
if not exist ".venv\Scripts\python.exe" (
    echo [*] Sanal ortam olusturuluyor...
    py -3.14 -m venv .venv
)

set "PY=.venv\Scripts\python.exe"

REM Bagimliliklari kur (ilk calistirmada torch/easyocr indirilir - biraz surer)
echo [*] Bagimliliklar kontrol ediliyor...
"%PY%" -m pip install --upgrade pip >nul
"%PY%" -m pip install -r requirements.txt

echo [*] Uygulama baslatiliyor...
"%PY%" lenslingo.py

endlocal
pause
