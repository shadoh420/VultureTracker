@echo off
rem Sets up audio transcription on a Windows PC with nothing installed: Python (through uv), VultureTracker's few
rem packages and the transcription environments (PyTorch for an NVIDIA card, demucs, basic-pitch, ADTOF, YourMT3+),
rem in %LOCALAPPDATA%\VultureTracker\transcribe-env. Run it once: about 6 GB to download.
rem "transcribe_setup.cmd cpu" sets up without an NVIDIA card (everything then runs on the processor, slowly).
setlocal
set "ENV=%LOCALAPPDATA%\VultureTracker\transcribe-env"
set "UV=%~dp0bin\uv.exe"
if exist "%UV%" goto :uv
set "UV=uv"
where uv >nul 2>&1
if errorlevel 1 goto :nouv
:uv
set "CUDA=--cuda"
if /i "%~1"=="cpu" set "CUDA="
if not defined CUDA goto :go
where nvidia-smi >nul 2>&1
if errorlevel 1 goto :nodriver
echo The NVIDIA card and driver:
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader
:go
echo Installing Python 3.14 and 3.11 (uv keeps them to itself)...
"%UV%" python install 3.14 3.11 || goto :fail
"%UV%" venv -q --allow-existing -p 3.14 "%ENV%\vt" || goto :fail
"%UV%" pip install -q -p "%ENV%\vt\Scripts\python.exe" pyyaml numpy mido imageio-ffmpeg || goto :fail
set "PATH=%~dp0bin;%PATH%"
"%ENV%\vt\Scripts\python.exe" "%~dp0transcribe_audio.py" --setup %CUDA% --yourmt3 --env "%ENV%" || goto :fail
echo.
echo Done. Drag a recording onto transcribe.cmd, or run: transcribe.cmd "path\to\song.mp3"
pause
exit /b 0
:nouv
echo uv.exe is missing: put it in %~dp0bin (https://docs.astral.sh/uv/)
goto :fail
:nodriver
echo No NVIDIA driver found: nvidia-smi is missing.
echo Install the GeForce driver for the card, version 551.61 or later, from https://www.nvidia.com/en-us/drivers/
echo and run this again. To set up for the processor instead: transcribe_setup.cmd cpu
start "" https://www.nvidia.com/en-us/drivers/
pause
exit /b 1
:fail
echo.
echo Setup failed: see the messages above.
pause
exit /b 1
