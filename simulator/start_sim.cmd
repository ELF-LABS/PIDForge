@echo off
setlocal
cd /d C:\temp\flightforge\simulator
echo [SIM] Installing deps (websockets, numpy)...
"C:\Users\ELF LABS\AppData\Local\Programs\Python\Python312\python.exe" -m pip install -q websockets numpy
echo [SIM] Starting Mock FC on :5051 ...
start "FlightForge-MockFC" cmd /k C:\temp\flightforge\simulator\run_mock_fc.cmd
timeout /t 3 /nobreak >nul
echo [SIM] Starting FlightForge Web on :5050 ...
start "FlightForge-Web" cmd /k C:\temp\flightforge\simulator\run_web.cmd
echo.
echo Mock FC:    ws://127.0.0.1:5051   (use host IP from phone on LAN)
echo FlightForge: http://127.0.0.1:5050
echo Open UI -^> enable SIM MODE -^> Connect FC
endlocal
