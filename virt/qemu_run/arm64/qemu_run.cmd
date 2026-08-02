@echo off
setlocal
set "PYTHONDONTWRITEBYTECODE=1"
set "SCRIPT_DIR=%~dp0"
set "PROFILE=%SCRIPT_DIR%qemu_profile.json"
set "PORTABLE_IMAGES="
if exist "%SCRIPT_DIR%qemu_launcher.py" if exist "%SCRIPT_DIR%qemu_launcher_lib\launcher.py" (
    set "LAUNCHER=%SCRIPT_DIR%qemu_launcher.py"
    set "PORTABLE_IMAGES=1"
) else (
    set "LAUNCHER=%SCRIPT_DIR%..\..\..\common\qemu_launcher.py"
)
where py >nul 2>nul
if not errorlevel 1 goto use_py
where python >nul 2>nul
if not errorlevel 1 goto use_python
echo Error: Python 3.8 or newer is required. 1>&2
exit /b 127
:use_py
if defined PORTABLE_IMAGES (
    py -3 "%LAUNCHER%" --profile "%PROFILE%" --images "%SCRIPT_DIR%." %*
) else (
    py -3 "%LAUNCHER%" --profile "%PROFILE%" %*
)
exit /b %errorlevel%
:use_python
if defined PORTABLE_IMAGES (
    python "%LAUNCHER%" --profile "%PROFILE%" --images "%SCRIPT_DIR%." %*
) else (
    python "%LAUNCHER%" --profile "%PROFILE%" %*
)
exit /b %errorlevel%
