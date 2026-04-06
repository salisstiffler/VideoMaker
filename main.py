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

# ── VideoLingo 桥接配置（在这里修改 TTS 和语言设置）──────────────────
VL_CONFIG = {
    "tts_method": "edge_tts",          # 免费: edge_tts | 付费: azure_tts | sf_fish_tts | openai_tts
    "whisper_language": "en",          # 源视频语言: en, zh, ja, ru, fr, de...
    "target_language": "简体中文",      # 翻译目标语言
    "llm_api_key": "lm-studio",        # 本地 LM Studio 随便填
    "llm_base_url": "http://localhost:1234/v1", # LM Studio 的默认本地 API 地址
    "llm_model": "local-model",        # LM Studio 模型名称打底
    "enable_dubbing": True,            # True=字幕+配音，False=仅字幕
}
# ─────────────────────────────────────────────────────────────────────────


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
    required = ["torch", "yt_dlp"]
    for pkg in required:
        try:
            __import__(pkg.replace("-", "_"))
        except ImportError:
            print(f"[!] Warning: {pkg} not found.")
    
    import torch
    if torch.cuda.is_available():
        print(f"[+] GPU Hardware Accelerated: {torch.cuda.get_device_name(0)}")
    else:
        print("[!] Running on CPU Mode.")
    
    # 检查 VideoLingo
    vl_dir = r"d:\VideoLingo"
    if os.path.exists(vl_dir):
        print(f"[+] VideoLingo found at: {vl_dir}")
    else:
        print(f"[!] VideoLingo NOT FOUND at {vl_dir}")
        print(f"    请运行: git clone https://github.com/Huanshere/VideoLingo.git d:\\VideoLingo")
        print(f"    然后运行: cd d:\\VideoLingo && python setup_env.py")

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

def process_video_task(url_or_path, dl, editor, bridge):
    """The full autonomous pipeline for a single URL or local path."""
    is_local = os.path.isfile(url_or_path)
    
    if is_local:
        video_path = os.path.abspath(url_or_path)
        title = os.path.splitext(os.path.basename(video_path))[0]
        video_id = title
        print(f"\n{'='*20} STARTING LOCAL FILE: {video_path} {'='*20}")
    else:
        url = url_or_path
        video_id = url.split("v=")[-1] if "v=" in url else url
        print(f"\n{'='*20} STARTING URL: {url} {'='*20}")
    
    try:
        # ── 步骤 0: 获取视频文件 ──────────────────────────────────────────
        if is_local:
            # For local, try to find thumbnail in same dir (same name) or directory
            thb_path = None
            for ext in ['.jpg', '.png', '.jpeg', '.webp']:
                pot = os.path.splitext(video_path)[0] + ext
                if os.path.exists(pot):
                    thb_path = pot
                    break
            if not thb_path:
                thb_path = dl._find_thumbnail(os.path.dirname(video_path))
        else:
            url = url_or_path
            video_path, title = find_existing_video(url, dl)
            if video_path:
                print(f"[+] Found existing video: {video_path}")
            if not video_path or not os.path.exists(video_path):
                print(f"[*] Downloading: {url}")
                video_path, title, thb_path = dl.download_video(url)
            else:
                thb_path = dl._find_thumbnail(os.path.dirname(video_path))

        if not video_path or not os.path.exists(video_path):
            print(f"[-] Failed to obtain video for {url_or_path}")
            return

        base_name = os.path.splitext(os.path.basename(video_path))[0]
        video_out_dir = os.path.join("output", base_name)
        os.makedirs(video_out_dir, exist_ok=True)

        # ── 步骤 1: VideoLingo 处理（字幕 + 翻译 + 配音）────────────────
        print(f"\n[*] 启动 VideoLingo 流程（字幕生成 + 翻译 + AI 配音）...")
        vl_result = bridge.process_video(
            video_path,
            output_dir="output",
            dubbing=VL_CONFIG["enable_dubbing"],
        )

        if not vl_result.get("success"):
            print(f"[-] VideoLingo 处理失败: {vl_result.get('error')}")
            print(f"[!] 将降级为旧版 Whisper+F5TTS 流程...")
            _fallback_process(url_or_path, dl, editor, video_path, thb_path, title, video_out_dir, video_id)
            return

        # 获取 VL 输出的字幕路径
        srt_path = vl_result.get("srt_zh_path") or vl_result.get("srt_bi_path")
        dub_path = vl_result.get("dub_path")  # 可能是 mp4 或 wav

        if not srt_path:
            print("[!] 未找到字幕文件，将跳过字幕烧录")

        # ── 步骤 2: 封面生成 ─────────────────────────────────────────────
        if thb_path:
            editor.generate_covers(thb_path, video_out_dir)

        # ── 步骤 3: UVR 人声分离（仅在需要混合背景音时）─────────────────
        inst_path = None
        # 如果 VL 已经输出了完整的配音视频（带混合音轨），直接用它
        # 如果 VL 只输出了配音音轨，需要我们再做背景音混合
        if dub_path and dub_path.endswith(".wav"):
            print(f"[*] VL 输出配音音轨，进行背景音分离...")
            try:
                inst_path, _ = editor.separate_audio(video_path)
            except Exception as e:
                print(f"[!] UVR 分离失败（跳过背景音混合）: {e}")

        # ── 步骤 4: FFmpeg 最终合成 ──────────────────────────────────────
        logo_path = DEFAULT_LOGO if os.path.exists(DEFAULT_LOGO) else None
        
        # 判断 dub_path 是 mp4 还是 wav
        if dub_path and dub_path.endswith(".mp4"):
            # VL 已经完成了完整的配音+字幕合成，直接用
            final_path = dub_path
            print(f"[+] VideoLingo 已完成完整合成: {final_path}")
        else:
            # 用我们自己的 FFmpeg 合成（字幕烧录 + 音轨混合）
            final_path = editor.burn_subtitles(
                video_path=video_path,
                srt_path=srt_path,
                margin_v=DEFAULT_MARGIN,
                logo_path=logo_path,
                dubbing_path=dub_path,     # WAV 配音（可能为 None）
                inst_path=inst_path,        # 背景音（可能为 None）
                output_dir="output",
            )

        # ── 步骤 5: 复制到最终输出目录 ───────────────────────────────────
        if final_path and os.path.exists(final_path):
            out_dir = "final_outputs"
            os.makedirs(out_dir, exist_ok=True)
            safe_title = "".join([c for c in title if c.isalnum() or c in (' ', '_', '-')]).strip()
            dest = os.path.join(out_dir, f"{safe_title}_final.mp4")
            shutil.copy2(final_path, dest)
            print(f"[SUCCESS] {url_or_path} -> {os.path.abspath(dest)}")
            save_processed_id(video_id)
        else:
            print(f"[-] Final assembly failed for {url_or_path}")

    except Exception as e:
        print(f"[ERROR] Task failed for {url_or_path}: {e}")
    finally:
        print(f"{'='*20} FINISHED: {url_or_path} {'='*20}")


def _fallback_process(url_or_path, dl, editor, video_path, thb_path, title, video_out_dir, video_id):
    """原始 Whisper+F5TTS 降级处理（备用，VL 失败时使用）"""
    print("[*] [降级模式] 使用旧版 Whisper + 翻译 + F5TTS 流程...")
    try:
        result = editor.generate_subtitles(video_path)
        if not result:
            return
        srt_path, segments, translated_texts = result

        if thb_path:
            editor.generate_covers(thb_path, video_out_dir)

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
            dest = os.path.join(out_dir, f"{title}_final_fallback.mp4")
            shutil.copy2(final_path, dest)
            print(f"[SUCCESS][降级] -> {os.path.abspath(dest)}")
            save_processed_id(video_id)
    except Exception as e:
        print(f"[ERROR][降级] {e}")


def monitor_channel(channel_url, dl, editor, bridge, executor, interval=1800):
    """Periodically checks a channel for new videos."""
    print(f"[*] Started Monitor for {channel_url} (Interval: {interval}s)")
    processed_ids = load_processed_ids()
    
    while True:
        try:
            latest_ids = dl.get_channel_video_ids(channel_url, limit=5)
            new_tasks = []
            
            for vid in latest_ids:
                if vid not in processed_ids:
                    print(f"[NEW] Found new video in channel: {vid}")
                    url = f"https://www.youtube.com/watch?v={vid}"
                    new_tasks.append(url)
                    processed_ids.add(vid)
            
            for url in new_tasks:
                executor.submit(process_video_task, url, dl, editor, bridge)
                
        except Exception as e:
            print(f"[!] Monitor Error: {e}")
            
        time.sleep(interval)


def main():
    print("="*60)
    print("   VideoCapter Pro - VideoLingo Edition   ")
    print("="*60)
    
    check_env()
    
    from downloader import VideoDownloader
    from editor import VideoEditor
    from videolingo_bridge import VideoLingoBridge

    dl = VideoDownloader()
    editor = VideoEditor(model_size="base")  # Whisper 保留用于降级模式

    # 初始化 VideoLingo 桥接器
    bridge = VideoLingoBridge(
        tts_method=VL_CONFIG["tts_method"],
        whisper_language=VL_CONFIG["whisper_language"],
        target_language=VL_CONFIG["target_language"],
        llm_api_key=VL_CONFIG["llm_api_key"],
        llm_base_url=VL_CONFIG["llm_base_url"],
        llm_model=VL_CONFIG["llm_model"],
    )
    
    # 顺序处理节省 VRAM
    executor = ThreadPoolExecutor(max_workers=1)

    while True:
        print("\n[MENU]")
        print("1. Process Video URL(s) - Batch")
        print("2. Listen to Channel - Monitor New Uploads")
        print("3. Configure VideoLingo Settings")
        print("Q. Exit")
        choice = input("Select [1/2/3/Q]: ").strip().upper()

        if choice == '1':
            raw_input = input("\n[INPUT] Enter Video/Channel URL(s) or Local Path(s) (space/comma/quote separated): ").strip()
            if not raw_input:
                continue
            
            import shlex
            try:
                # Replace commas with spaces to allow comma-separation, but keep quoted parts intact
                # shlex doesn't like some characters if not quoted, but for URLs it's usually fine.
                cleaned_input = raw_input.replace(',', ' ')
                inputs = shlex.split(cleaned_input)
            except Exception:
                inputs = [u.strip() for u in raw_input.replace(',', ' ').split() if u.strip()]

            urls_or_paths = []
            for item in inputs:
                if os.path.isfile(item):
                    urls_or_paths.append(item)
                elif any(k in item for k in ['/@', '/channel/', '/user/', '/c/']):
                    channel_urls = dl.get_channel_videos_last_week(item)
                    if channel_urls:
                        urls_or_paths.extend(channel_urls)
                else:
                    urls_or_paths.append(item)
            
            if urls_or_paths:
                print(f"[*] Queuing {len(urls_or_paths)} tasks...")
                for up in urls_or_paths:
                    executor.submit(process_video_task, up, dl, editor, bridge)

        elif choice == '2':
            channel_url = input("\n[INPUT] Enter Channel URL to monitor: ").strip()
            if not channel_url:
                continue
            interval = input("Check interval in minutes [default 30]: ").strip()
            sec = int(interval) * 60 if interval.isdigit() else 1800
            
            monitor_thread = threading.Thread(
                target=monitor_channel,
                args=(channel_url, dl, editor, bridge, executor, sec),
                daemon=True
            )
            monitor_thread.start()
            print(f"[+] Monitor started.")
        
        elif choice == '3':
            _configure_vl()

        elif choice in ('Q', 'QUIT', 'EXIT'):
            print("[*] Shutting down...")
            executor.shutdown(wait=False)
            break


def _configure_vl():
    """交互式配置 VideoLingo 设置"""
    print("\n[VL CONFIG] 当前配置:")
    for k, v in VL_CONFIG.items():
        print(f"  {k}: {v}")
    
    print("\nTTS 选项:")
    print("  edge_tts      - 免费，无需 API Key，音质良好")
    print("  azure_tts     - 需要 302.ai API Key，音质优秀")
    print("  sf_fish_tts   - 需要 SiliconFlow API Key，音质优秀")
    print("  openai_tts    - 需要 302.ai API Key，音质良好")
    print("  gpt_sovits    - 本地运行，需要额外安装 GPT-SoVITS")
    
    new_tts = input(f"\nTTS 方法 [{VL_CONFIG['tts_method']}]: ").strip()
    if new_tts:
        VL_CONFIG["tts_method"] = new_tts
    
    new_lang = input(f"源语言 [{VL_CONFIG['whisper_language']}]: ").strip()
    if new_lang:
        VL_CONFIG["whisper_language"] = new_lang
    
    new_key = input(f"LLM API Key [{VL_CONFIG['llm_api_key'] or '(空)'}]: ").strip()
    if new_key:
        VL_CONFIG["llm_api_key"] = new_key
    
    print(f"[+] 配置已更新: TTS={VL_CONFIG['tts_method']}, 语言={VL_CONFIG['whisper_language']}")


if __name__ == "__main__":
    main()
