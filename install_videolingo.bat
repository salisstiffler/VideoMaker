@echo off
chcp 65001 >nul
echo ============================================================
echo  VideoCapter x VideoLingo 环境安装脚本
echo  运行前请确保已联网，安装过程约 10-20 分钟
echo ============================================================
echo.

:: ── 检查 FFmpeg ───────────────────────────────────────────────
echo [1/5] 检查 FFmpeg...
ffmpeg -version >nul 2>&1
if %errorlevel% NEQ 0 (
    echo [!] FFmpeg 未找到，请先安装:
    echo     方法1: choco install ffmpeg  (需要 Chocolatey)
    echo     方法2: 从 https://ffmpeg.org/download.html 下载并加入 PATH
    echo.
    pause
)

:: ── 检查 Git ──────────────────────────────────────────────────
echo [2/5] 检查 Git...
git --version >nul 2>&1
if %errorlevel% NEQ 0 (
    echo [!] Git 未找到，请先安装: https://git-scm.com/download/win
    pause
)

:: ── Clone VideoLingo（如未克隆）──────────────────────────────
echo [3/5] 检查 VideoLingo 目录...
if not exist "d:\VideoLingo\" (
    echo [*] 正在克隆 VideoLingo...
    git clone https://github.com/Huanshere/VideoLingo.git d:\VideoLingo
    if %errorlevel% NEQ 0 (
        echo [-] 克隆失败，请检查网络连接
        pause
        exit /b 1
    )
    echo [+] VideoLingo 克隆完成
) else (
    echo [+] VideoLingo 已存在，跳过克隆
)

:: ── 安装 VideoLingo Python 环境 (uv) ─────────────────────────
echo [4/5] 安装 VideoLingo 依赖...
cd /d d:\VideoLingo

if not exist ".venv\Scripts\python.exe" (
    echo [*] 初始化 VL 虚拟环境（首次安装，约 5-10 分钟）...
    python setup_env.py
    if %errorlevel% NEQ 0 (
        echo [-] setup_env.py 失败，尝试手动安装...
        pip install uv
        uv venv .venv --python 3.10
    )
)

echo [*] 安装 VL Python 依赖（约 5-15 分钟，需下载大型包）...
.venv\Scripts\pip install -r requirements.txt

echo [*] 安装 edge-tts（免费 TTS）...
.venv\Scripts\pip install edge-tts

echo [*] 安装 spacy 中文模型...
.venv\Scripts\python -m spacy download zh_core_web_md
.venv\Scripts\python -m spacy download en_core_web_md

:: ── 安装 VideoCapter 自身依赖 ─────────────────────────────────
echo [5/5] 安装 VideoCapter 依赖...
cd /d d:\videoCapter
pip install faster-whisper yt-dlp pydub translators scipy torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

:: audio-separator (UVR)
pip install audio-separator[gpu]

:: yaml（桥接器需要）
pip install pyyaml

:: 将 VL 配置模板复制到 VL 目录
copy /Y "d:\videoCapter\vl_config_template.yaml" "d:\VideoLingo\config.yaml"
echo [+] VL config.yaml 已初始化

:: ── 验证核心模块 ──────────────────────────────────────────────
echo.
echo [验证] 检查关键模块...
cd /d d:\VideoLingo
.venv\Scripts\python -c "
import sys
sys.path.insert(0, '.')
results = []
modules = {
    'pyyaml': 'yaml',
    'edge_tts': 'edge_tts',
    'core.utils': 'core.utils.config_utils',
    'json_repair': 'json_repair',
    'pandas': 'pandas',
    'spacy': 'spacy',
}
for name, mod in modules.items():
    try:
        __import__(mod)
        results.append(f'  [+] {name}')
    except ImportError as e:
        results.append(f'  [-] {name}: {e}')
print('\n'.join(results))
"

echo.
echo ============================================================
echo  安装完成！
echo  下一步：
echo  1. 编辑 d:\videoCapter\vl_config_template.yaml
echo     - 填写 LLM API Key（翻译用）
echo     - 选择 TTS 引擎（默认 edge_tts 免费）
echo  2. 运行 d:\videoCapter\main.py
echo ============================================================
pause
