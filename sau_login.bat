@echo off
title SAU 登录助手
set "SAU_DIR=D:\social-auto-upload"
set "SAU_PY=%SAU_DIR%\.venv\Scripts\python.exe"
set "SAU_CLI=%SAU_DIR%\sau_cli.py"

:menu
cls
echo ==========================================
echo       social-auto-upload 登录工具
echo ==========================================
echo 1. 登录 抖音 (账号: berlin)
echo 2. 登录 Bilibili (账号: berlin2017)
echo 3. 退出
echo ==========================================
set /p choice=请输入选项 [1-3]: 

if "%choice%"=="1" goto douyin
if "%choice%"=="2" goto bilibili
if "%choice%"=="3" goto end
goto menu

:douyin
echo.
echo [*] 正在启动抖音登录流程...
echo [!] 请在弹出的浏览器中完成登录，完成后关闭浏览器即可。
echo.
"%SAU_PY%" "%SAU_CLI%" douyin login --account berlin
echo.
echo [*] 抖音登录操作完成。
pause
goto menu

:bilibili
echo.
echo [*] 正在启动 Bilibili 登录流程...
echo [!] 请扫描控制台中显示的二维码，或查看目录下的 qrcode.png。
echo.
"%SAU_PY%" "%SAU_CLI%" bilibili login --account berlin2017
echo.
echo [*] Bilibili 登录操作完成。
pause
goto menu

:end
echo 退出中...
exit
