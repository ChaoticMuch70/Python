@echo off
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo 未检测到 Python 启动器 py，请先安装 Python 3.11+
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    py -3.11 -m venv .venv
)
call ".venv\Scripts\activate.bat"

python -m pip install --upgrade pip
pip install -r requirements.txt
python chinaz_mobile_weight_gui.py

pause
