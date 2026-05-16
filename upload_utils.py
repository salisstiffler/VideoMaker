import os
import subprocess
import sys
import datetime
import glob
from dotenv import load_dotenv

def auto_upload(video_path, title, cover_path=None):
    """
    立即在后台启动当前视频的抖音和 Bilibili 上传任务
    """
    load_dotenv()
    video_path = os.path.abspath(video_path)
    video_dir = os.path.dirname(video_path)
    video_filename = os.path.basename(video_path)
    
    # 封面自动适配逻辑
    cover_4_3 = glob.glob(os.path.join(video_dir, "*_cover_4_3.jpg"))
    cover_3_4 = glob.glob(os.path.join(video_dir, "*_cover_3_4.jpg"))
    
    # 抖音优先 3:4 (竖屏)，B站优先 4:3 (横屏)
    best_cover_douyin = cover_path
    if not best_cover_douyin or "_cover_4_3" in best_cover_douyin:
        if cover_3_4: best_cover_douyin = cover_3_4[0]
        
    best_cover_bili = cover_path
    if not best_cover_bili or "_cover_3_4" in best_cover_bili:
        if cover_4_3: best_cover_bili = cover_4_3[0]

    # 1. 抖音上传指令
    cmd_douyin = [sys.executable, "uploader_douyin.py", "--video", video_path, "--title", title]
    if best_cover_douyin: cmd_douyin.extend(["--cover", best_cover_douyin])

    # 2. Bilibili 上传指令 (直接使用 CLI)
    cmd_bili = [sys.executable, "uploader_bili.py", "--video", video_path, "--title", title]
    if best_cover_bili: cmd_bili.extend(["--cover", best_cover_bili])

    # Windows 静默启动标志
    CREATE_NO_WINDOW = 0x08000000

    def run_in_bg(cmd, platform_name):
        try:
            os.makedirs("logs", exist_ok=True)
            log_file = open(f"logs/upload_{platform_name}.log", "a", encoding="utf-8")
            
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_file.write(f"\n[{now}] [Direct-Trigger] Starting {platform_name} upload for {video_filename}...\n")
            log_file.flush()

            subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=log_file,
                creationflags=CREATE_NO_WINDOW,
                start_new_session=True
            )
            print(f"[+] {platform_name} 后台上传任务已启动: {video_filename}")
        except Exception as e:
            print(f"[-] 启动 {platform_name} 上传失败: {e}")

    # 并发启动两个平台的上传
    run_in_bg(cmd_douyin, "douyin")
    run_in_bg(cmd_bili, "bilibili")
