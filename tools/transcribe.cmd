@echo off
rem Transcribes a recording into VultureTracker songs: drag a sound file onto this, or run
rem   transcribe.cmd "path\to\song.mp3" [options]
rem (the options: tools\transcribe_audio.py --help). By default the notes come from both basic-pitch and YourMT3+, each
rem making its own song, MP3 to compare by ear and diff picture in <recording>-transcription beside the recording.
setlocal
set "ENV=%LOCALAPPDATA%\VultureTracker\transcribe-env"
if not exist "%ENV%\vt\Scripts\python.exe" goto :nosetup
if "%~1"=="" goto :usage
set "PATH=%~dp0bin;%PATH%"
"%ENV%\vt\Scripts\python.exe" "%~dp0transcribe_audio.py" --env "%ENV%" --notes basic-pitch yourmt3 %*
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
