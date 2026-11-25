@echo off
title ALEX (phone mode)
cd /d "%~dp0"
set PY=python
where python >nul 2>nul || set PY=py
%PY% -m pip install cryptography --quiet
set ALEX_HOST=0.0.0.0
set ALEX_HTTPS=1
echo Phone link will be printed below. Same WiFi needed.
start "" "https://127.0.0.1:5000/app/"
%PY% app.py
pause
