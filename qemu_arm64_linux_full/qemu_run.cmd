@echo off
call "%~dp0..\virt\qemu_run\arm64\qemu_run.cmd" %*
exit /b %errorlevel%
