import os
import time
import subprocess
import sys
import glob
import datetime

# Configuration
OUTPUT_DIR = "output"
WATCH_INTERVAL = 60 # seconds
UPLOAD_SCRIPT_DOUYIN = "uploader_douyin.py"
UPLOAD_SCRIPT_BILI = "uploader_bili.py"
LOG_FILE = "logs/bg_service.log"

def log(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"[{timestamp}] {message}"
    print(msg)
    os.makedirs("logs", exist_ok=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except:
        pass

def start_upload_process(platform, video_path, title, cover_path):
    """
    启动上传进程但不等待其结束（返回 Popen 对象）
    """
    if platform == "douyin":
        cmd = [sys.executable, UPLOAD_SCRIPT_DOUYIN, "--video", video_path, "--title", title]
        if cover_path:
            cmd.extend(["--cover", cover_path])
    elif platform == "bili":
        cmd = [sys.executable, UPLOAD_SCRIPT_BILI, "--video", video_path, "--title", title]
        if cover_path:
            cmd.extend(["--cover", cover_path])
        cmd.extend(["--tid", "171"])
    else:
        return None

    try:
        log(f"[*] [{platform}] Starting asynchronous upload: {title}")
        # 使用 subprocess.Popen 实现非阻塞启动
        # 重定向输出到各自的日志文件
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)
        out_f = open(os.path.join(log_dir, f"upload_{platform}.log"), "a", encoding="utf-8")
        
        process = subprocess.Popen(
            cmd, 
            stdout=out_f, 
            stderr=out_f, 
            text=True, 
            encoding="utf-8", 
            errors="ignore",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        return process, out_f
    except Exception as e:
        log(f"[!] [{platform}] Failed to start process: {e}")
        return None

def check_and_upload(since_ts=None):
    if not os.path.exists(OUTPUT_DIR):
        return

    if since_ts is None:
        since_ts = time.time() - (24 * 3600) 

    projects = [d for d in os.listdir(OUTPUT_DIR) if os.path.isdir(os.path.join(OUTPUT_DIR, d))]
    
    for project in projects:
        project_path = os.path.join(OUTPUT_DIR, project)
        if os.path.getmtime(project_path) < since_ts:
            continue

        patterns = ["**/*_full_production.mp4", "**/*_final.mp4", "**/*_valorant_final.mp4"]
        video_files = []
        for p in patterns:
            video_files.extend(glob.glob(os.path.join(project_path, p), recursive=True))
            
        if not video_files:
            continue
        
        pref_video = next((v for v in video_files if "_full_production.mp4" in v), video_files[0])
        video_path = os.path.abspath(pref_video)
        if os.path.getmtime(video_path) < since_ts:
            continue

        video_dir = os.path.dirname(video_path)
        video_filename = os.path.basename(video_path)
        douyin_flag = os.path.join(video_dir, f"{video_filename}_douyin.flag")
        bili_flag = os.path.join(video_dir, f"{video_filename}_bili.flag")
        
        title = project.replace("valorant_", "")
        cover_4_3 = glob.glob(os.path.join(video_dir, "*_cover_4_3.jpg")) or glob.glob(os.path.join(project_path, "*_cover_4_3.jpg"))
        cover_3_4 = glob.glob(os.path.join(video_dir, "*_cover_3_4.jpg")) or glob.glob(os.path.join(project_path, "*_cover_3_4.jpg"))
        best_cover_douyin = cover_3_4[0] if cover_3_4 else (cover_4_3[0] if cover_4_3 else None)
        best_cover_bili = cover_4_3[0] if cover_4_3 else (cover_3_4[0] if cover_3_4 else None)

        pending_uploads = []
        
        # 准备任务
        if not os.path.exists(douyin_flag):
            pending_uploads.append(("douyin", best_cover_douyin, douyin_flag))
        if not os.path.exists(bili_flag):
            pending_uploads.append(("bili", best_cover_bili, bili_flag))

        if not pending_uploads:
            continue

        # 并行启动任务
        active_processes = []
        for platform, cover, flag in pending_uploads:
            res = start_upload_process(platform, video_path, title, cover)
            if res:
                process, log_file = res
                active_processes.append({
                    "platform": platform,
                    "process": process,
                    "flag": flag,
                    "log_file": log_file
                })

        # 等待当前项目的所有任务完成
        if active_processes:
            log(f"[*] Waiting for {len(active_processes)} concurrent upload(s) to finish...")
            for item in active_processes:
                p = item["process"]
                p.wait()
                item["log_file"].close()
                
                if p.returncode == 0:
                    log(f"[+] [{item['platform']}] Upload successful for {title}")
                    with open(item["flag"], "w") as f:
                        f.write(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                else:
                    log(f"[-] [{item['platform']}] Upload failed (Exit code: {p.returncode}). Check logs/upload_{item['platform']}.log")

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", type=float, help="Only process videos modified after this timestamp")
    args = parser.parse_args()

    log("=== Background Uploader Service Started ===")
    if args.since:
        log(f"[*] Filtering videos modified after: {datetime.datetime.fromtimestamp(args.since)}")
    else:
        log("[*] Mode: New tasks only (last 24 hours)")

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    try:
        while True:
            check_and_upload(since_ts=args.since)
            log(f"[*] Sleeping for {WATCH_INTERVAL} seconds...")
            time.sleep(WATCH_INTERVAL)
    except KeyboardInterrupt:
        log("=== Background Uploader Service Stopped ===")
    except Exception as e:
        log(f"[!] Fatal Exception in service: {e}")

if __name__ == "__main__":
    main()
