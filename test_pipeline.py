import os
import sys
from downloader import VideoDownloader
from editor import VideoEditor

def test_full_pipeline():
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    print(f"\n[TEST] Testing URL: {url}")
    
    # 1. Test Downloader
    dl = VideoDownloader()
    video_path, title = dl.download_video(url)
    
    if not video_path or not os.path.exists(video_path):
        print("[-] FAILED: Download stage failed.")
        return False
    print(f"[+] PASSED: Downloaded to {video_path}")
    print(f"[+] PASSED: Cleaned title: {title}")

    # 2. Test Editor (GPU + Faster-Whisper)
    # Using 'tiny' model for faster testing, but 'base' is what main.py uses
    editor = VideoEditor(model_size="base") 
    srt_path = editor.generate_subtitles(video_path)
    
    if not srt_path or not os.path.exists(srt_path):
        print("[-] FAILED: Transcription stage failed.")
        return False
    print(f"[+] PASSED: Subtitles generated at {srt_path}")

    # 3. Test FFmpeg Burn
    final_path = editor.burn_subtitles(video_path, srt_path, margin_v=20)
    if not final_path or not os.path.exists(final_path):
        print("[-] FAILED: FFmpeg burn stage failed.")
        return False
    print(f"[+] PASSED: Final video created at {final_path}")
    
    print("\n[!!!] ALL SYSTEMS GO: Pipeline is fully functional.")
    return True

if __name__ == "__main__":
    test_full_pipeline()
