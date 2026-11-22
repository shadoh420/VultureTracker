@echo off
rem Transcribes a recording into VultureTracker songs: drag a sound file onto this, or run
rem   transcribe.cmd "path\to\song.mp3" [options]
rem Dettato reads the full mix by default. See transcribe_audio.py --help for alternate takes and older methods.
setlocal
set "ENV=%LOCALAPPDATA%\VultureTracker\transcribe-env"
set "VT=%ENV%\vt\Scripts\python.exe"
if exist "%VT%" goto :ready
set "ENV=%~dp0transcribe-env"
if not exist "%ENV%\torch\Scripts\python.exe" goto :nosetup
set "VT=python"
:ready
if "%~1"=="" goto :usage
set "PATH=%~dp0bin;%PATH%"
"%VT%" "%~dp0transcribe_audio.py" --env "%ENV%" %*
pause
exit /b
:nosetup
echo Run transcribe_setup.cmd first.
pause
exit /b 1
:usage
echo Drag a recording onto transcribe.cmd, or run: transcribe.cmd "path\to\song.mp3"
pause
exit /b 1
