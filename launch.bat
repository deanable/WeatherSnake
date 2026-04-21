@echo off
cd /d "%~dp0"
.venv\Scripts\activate.bat && python ui_app.py
