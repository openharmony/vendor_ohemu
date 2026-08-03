@echo off
call "%~dp0..\virt\qemu_run\arm\qemu_run.cmd" %*
exit /b %errorlevel%
