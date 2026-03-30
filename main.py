import os
os.environ["translators_default_region"] = "CN"
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

DEFAULT_LOGO = "avrtar.jpg"
DEFAULT_MARGIN = 20
PROCESSED_LOG = "processed_videos.txt"

def load_processed_ids():
    if os.path.exists(PROCESSED_LOG):
        with open(PROCESSED_LOG, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_processed_id(video_id):
    with open(PROCESSED_LOG, "a", encoding="utf-8") as f:
        f.write(f"{video_id}\n")

def check_env():
    """Verify core dependencies are present."""
    print("[*] Verifying local environment...")
    required = ["torch", "faster_whisper", "translators", "yt_dlp"]
    for pkg in required:
        try:
            __import__(pkg.replace("-", "_"))
        except ImportError:
            print(f"[!] Warning: {pkg} not found. Please run 'pip install {pkg}'")
    
    import torch
    if torch.cuda.is_available():
        print(f"[+] GPU Hardware Accelerated: {torch.cuda.get_device_name(0)}")
    else:
        print("[!] Running on CPU Mode.")

def find_existing_video(url, dl, base_dir="downloads"):
    try:
        info = dl.ydl.extract_info(url, download=False)
        title = info.get('title', 'Video')
        for root, _, files in os.walk(base_dir):
            for f in files:
                if f.endswith(".mp4") and title in f:
                    return os.path.join(root, f), title
    except Exception:
        pass
    return None, None

def process_video_task(url, dl, editor):
    """The full autonomous pipeline for a single URL."""
    # Extract video ID for logging
    video_id = url.split("v=")[-1] if "v=" in url else url
    print(f"\n{'='*20} STARTING: {url} {'='*20}")
    
    try:
        video_path, title = find_existing_video(url, dl)
        if video_path:
            print(f"[+] Found existing video: {video_path}")
        else:
            print(f"[*] Downloading: {url}")
            video_path, title = dl.download_video(url)

        if not video_path or not os.path.exists(video_path):
            print(f"[-] Failed to obtain video for {url}")
            return

        result = editor.generate_subtitles(video_path)
        if not result: return
        srt_path, segments, translated_texts = result

        dub_path = None
        inst_path = None
        ref_audio = "my_voice.wav"
        if not os.path.exists(ref_audio):
            if os.path.exists("my_voice.m4a"):
                from pydub import AudioSegment
                AudioSegment.from_file("my_voice.m4a").export("my_voice.wav", format="wav")
            else:
                ref_audio = None

        if ref_audio and os.path.exists(ref_audio):
            inst_path, _ = editor.separate_audio(video_path)
            dub_path = editor.generate_dubbing(segments, translated_texts, ref_audio, video_path)

        logo_path = DEFAULT_LOGO if os.path.exists(DEFAULT_LOGO) else None
        final_path = editor.burn_subtitles(
            video_path, srt_path, DEFAULT_MARGIN, logo_path, 
            dubbing_path=dub_path, inst_path=inst_path
        )

        if final_path:
            out_dir = "final_outputs"
            os.makedirs(out_dir, exist_ok=True)
            safe_title = "".join([c for c in title if c.isalnum() or c in (' ', '_', '-')]).strip()
            dest = os.path.join(out_dir, f"{safe_title}_final.mp4")
            shutil.copy2(final_path, dest)
            print(f"[SUCCESS] {url} -> {os.path.abspath(dest)}")
            # Mark as processed after successful export
            save_processed_id(video_id)
        else:
            print(f"[-] Final assembly failed for {url}")

    except Exception as e:
        print(f"[ERROR] Task failed for {url}: {e}")
    finally:
        print(f"{'='*20} FINISHED: {url} {'='*20}")

def monitor_channel(channel_url, dl, editor, executor, interval=1800):
    """Periodically checks a channel for new videos."""
    print(f"[*] Started Monitor for {channel_url} (Interval: {interval}s)")
    processed_ids = load_processed_ids()
    
    while True:
        try:
            # Check latest 5 videos
            latest_ids = dl.get_channel_video_ids(channel_url, limit=5)
            new_tasks = []
            
            for vid in latest_ids:
                if vid not in processed_ids:
                    print(f"[NEW] Found new video in channel: {vid}")
                    url = f"https://www.youtube.com/watch?v={vid}"
                    new_tasks.append(url)
                    processed_ids.add(vid)
            
            # Submit new tasks to the sequential executor
            for url in new_tasks:
                executor.submit(process_video_task, url, dl, editor)
                
        except Exception as e:
            print(f"[!] Monitor Error: {e}")
            
        time.sleep(interval)

def main():
    print("="*60)
    print("   VideoCapter Pro - autonomous Content Factory   ")
    print("="*60)
    
    check_env()
    
    from downloader import VideoDownloader
    from editor import VideoEditor

    dl = VideoDownloader()
    editor = VideoEditor(model_size="base")
    
    # Sequential processing to save VRAM
    executor = ThreadPoolExecutor(max_workers=1)

    while True:
        print("\n[MENU]")
        print("1. Process Video URL(s) - Batch")
        print("2. Listen to Channel - Monitor New Uploads")
        print("Q. Exit")
        choice = input("Select [1/2/Q]: ").strip().upper()

        if choice == '1':
            raw_input = input("\n[INPUT] Enter Video/Channel URL(s) (space/comma separated): ").strip()
            if not raw_input: continue
            
            inputs = [u.strip() for u in raw_input.replace(',', ' ').split() if u.strip()]
            urls = []
            for item in inputs:
                if any(k in item for k in ['/@', '/channel/', '/user/', '/c/']):
                    channel_urls = dl.get_channel_videos_last_week(item)
                    if channel_urls: urls.extend(channel_urls)
                else:
                    urls.append(item)
            
            if urls:
                print(f"[*] Queuing {len(urls)} videos...")
                for url in urls:
                    executor.submit(process_video_task, url, dl, editor)
        
        elif choice == '2':
            channel_url = input("\n[INPUT] Enter Channel URL to monitor: ").strip()
            if not channel_url: continue
            interval = input("Check interval in minutes [default 30]: ").strip()
            sec = int(interval) * 60 if interval.isdigit() else 1800
            
            # Run monitor in a background thread so user can still use menu
            monitor_thread = threading.Thread(
                target=monitor_channel, 
                args=(channel_url, dl, editor, executor, sec),
                daemon=True
            )
            monitor_thread.start()
            print(f"[+] Monitor started. You can still add other tasks or exit to stop.")

        elif choice in ('Q', 'QUIT', 'EXIT'):
            print("[*] Shutting down...")
            executor.shutdown(wait=False)
            break

if __name__ == "__main__":
    main()
