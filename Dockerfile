FROM nvidia/cuda:12.1.0-base-ubuntu22.04

# 设置环境变量
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3-pip \
    ffmpeg \
    git \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 升级 pip
RUN python3 -m pip install --no-cache-dir --upgrade pip

# 复制依赖文件
COPY requirements.txt .

# 安装基础 Python 依赖
RUN pip3 install --no-cache-dir -r requirements.txt --index-url https://download.pytorch.org/whl/cu121

# 安装 F5-TTS 和 WhisperX (由于它们通常需要从 git 安装或有特殊依赖)
RUN pip3 install git+https://github.com/m-bain/whisperX.git
RUN pip3 install f5-tts

# 复制项目代码
COPY . .

# 暴露 Streamlit 端口
EXPOSE 8501

# 启动命令
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.maxUploadSize=2000"]
