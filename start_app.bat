@echo off
chcp 65001 >nul
echo ============================================================
echo  VideoCapter Web 界面启动器
echo ============================================================
echo.

:: 检查 streamlit 是否安装
python -c "import streamlit" >nul 2>&1
if %errorlevel% NEQ 0 (
    echo [*] 正在安装界面组件 Streamlit...
    pip install streamlit
)

echo [*] 正在启动服务 (本地浏览器访问: http://localhost:8501)
streamlit run app.py --server.maxUploadSize=2000

pause
