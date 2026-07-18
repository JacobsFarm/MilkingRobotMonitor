@echo off
REM Build the uploader as a standalone .exe.
REM The config/ folder (settings.json + epassport.json) is copied NEXT TO the
REM .exe so it stays editable without rebuilding.
REM The dashboard is a SvelteKit web app: see dashboard/README.md for how to
REM run it on a server (Raspberry Pi) or package it as a desktop app later.
cd /d "%~dp0"

pip install pyinstaller

REM Create the real settings from the template on first use.
if not exist uploader\config\settings.json copy uploader\config\settings.example.json uploader\config\settings.json

echo.
echo === Building uploader.exe ===
pyinstaller --onefile --name uploader --paths uploader --paths . ^
    --distpath dist\uploader --workpath build\uploader --specpath build ^
    uploader\run.py
xcopy /e /i /y uploader\config dist\uploader\config

echo.
echo Done.
echo   Uploader: dist\uploader\uploader.exe
