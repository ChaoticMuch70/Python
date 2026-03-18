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

rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
if exist "站长之家移动权重批量查询.spec" del /f /q "站长之家移动权重批量查询.spec"

pyinstaller --noconfirm --clean --windowed --onefile ^
  --name "站长之家移动权重批量查询" ^
  chinaz_mobile_weight_gui.py

echo.
echo 打包完成。
echo EXE 路径：dist\站长之家移动权重批量查询.exe
pause
