@echo off
title ALEX
cd /d "%~dp0"
set PY=python
where python >nul 2>nul || set PY=py
start "" "http://127.0.0.1:5000/app/"
%PY% app.py
pause
