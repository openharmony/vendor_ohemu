@echo off
call "%~dp0..\virt\qemu_run\x86_64\qemu_run.cmd" %*
exit /b %errorlevel%
