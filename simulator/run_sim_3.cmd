@echo off
cd /d "%~dp0"
"C:\Users\ELF LABS\AppData\Local\Programs\Python\Python312\python.exe" -u run_simulation.py 3
exit /b %ERRORLEVEL%
