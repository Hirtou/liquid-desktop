@echo off
cd /d "%~dp0"
py -c "import PySide6, psutil, numpy, tzdata, winrt.windows.media, winrt.windows.media.control" 2>nul || py -m pip install -r requirements.txt
start "" pyw main.py
