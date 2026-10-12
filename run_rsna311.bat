@echo off
REM ============================================================
REM  使用 conda 环境 rsna311 启动「医疗数据科学结构化工作流系统」
REM  rsna311 = D:\python\envs\rsna311  (Python 3.12.9 + PyQt5 + torch cu124)
REM
REM  用法:
REM    run_rsna311.bat                启动 GUI
REM    run_rsna311.bat --check        先跑自检再启动
REM ============================================================
setlocal EnableDelayedExpansion

set "CONDA_ROOT=D:\python"
set "PY=%CONDA_ROOT%\envs\rsna311\python.exe"
set "PYW=%CONDA_ROOT%\envs\rsna311\pythonw.exe"

cd /d "%~dp0"

if not exist "%PY%" (
    echo [ERROR] 未找到 rsna311 环境: %PY%
    echo         请确认 conda 根目录，或修改本脚本里的 CONDA_ROOT。
    exit /b 1
)

echo [INFO] 解释器: %PY%
for /f "delims=" %%v in ('"%PY%" --version 2^>^&1') do echo [INFO] 版本: %%v

if /i "%~1"=="--check" (
    echo [INFO] 运行 opencode 内嵌自检...
    "%PY%" scripts\test_kernel_embed.py --offline
    if errorlevel 1 (
        echo [WARN] 静态自检未全通过，继续启动 GUI...
    )
    "%PY%" scripts\test_gui_kernel_link.py
    echo.
)

echo [INFO] 启动主程序...
"%PYW%" main.py %*
if errorlevel 1 (
    echo [ERROR] pythonw 启动失败，回退到 python.exe 以显示错误输出
    "%PY%" main.py %*
)

endlocal
