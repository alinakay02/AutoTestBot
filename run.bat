@echo off
cd /d "%~dp0"

if not exist "venv" (
    echo Creating venv...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo Installing dependencies...
pip install -q -r requirements.txt

echo.
echo Starting eb.cert.roskazna.ru robot...
python eb_robot.py %*

pause
