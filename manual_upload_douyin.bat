@echo off
title 抖音单独上传工具 (SAU版)
set "SAU_DIR=D:\social-auto-upload"
set "SAU_PY=%SAU_DIR%\.venv\Scripts\python.exe"
set "SAU_CLI=%SAU_DIR%\sau_cli.py"
set "ACCOUNT=berlin"

echo =================================================
echo        抖音单独上传工具 - 账号: %ACCOUNT%
echo =================================================

set "VIDEO_PATH=%~1"
if "%VIDEO_PATH%"=="" (
    set /p VIDEO_PATH=请拖入或输入视频文件路径: 
)
set VIDEO_PATH=%VIDEO_PATH:"=%

if not exist "%VIDEO_PATH%" (
    echo [!] 错误: 找不到视频文件 "%VIDEO_PATH%"
    pause
    exit /b
)

echo [+] 已选中视频: %VIDEO_PATH%

set /p TITLE=请输入视频标题 (直接回车则使用文件名): 
if "%TITLE%"=="" (
    for %%i in ("%VIDEO_PATH%") do set "TITLE=%%~ni"
)

set /p COVER_PATH=请拖入或输入封面图路径 (直接回车跳过): 
set COVER_PATH=%COVER_PATH:"=%

echo.
echo 选择上传模式:
echo [1] 有界面模式 (Headed) - 最稳定，能看到进度和弹窗 [推荐]
echo [2] 静默模式 (Headless) - 后台运行，可能被抖音弹窗卡住
set /p MODE_CHOICE=请输入选项 [1 或 2, 默认 1]: 
if "%MODE_CHOICE%"=="" set MODE_CHOICE=1

set "MODE_ARG=--headed"
if "%MODE_CHOICE%"=="2" set "MODE_ARG=--headless"

echo.
echo [*] 准备上传...
echo     标题: %TITLE%
echo     模式: %MODE_ARG%
echo.

set CMD_ARGS=douyin upload-video --account %ACCOUNT% --file "%VIDEO_PATH%" --title "%TITLE%" %MODE_ARG%

if not "%COVER_PATH%"=="" (
    if exist "%COVER_PATH%" (
        set CMD_ARGS=%CMD_ARGS% --thumbnail "%COVER_PATH%"
    )
)

echo 执行命令: "%SAU_PY%" "%SAU_CLI%" %CMD_ARGS%
echo.

"%SAU_PY%" "%SAU_CLI%" %CMD_ARGS%

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [✅] 抖音上传任务提交成功！
) else (
    echo.
    echo [❌] 上传失败。
)

pause
