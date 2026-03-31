import os
import shutil
import subprocess
from downloader import VideoDownloader

def test_with_copied_cookies():
    # Attempt to copy Chrome's cookie database to bypass the lock
    # Path for Chrome 'chenb' user:
    chrome_cookies = os.path.expandvars(r'%LocalAppData%\Google\Chrome\User Data\Default\Network\Cookies')
    temp_cookies = "temp_cookies_v3.sqlite"
    
    print(f"[*] Attempting to shadow-copy cookies from: {chrome_cookies}")
    try:
        shutil.copy2(chrome_cookies, temp_cookies)
        print("[+] Copy successful. Running downloader test.")
    except Exception as e:
        print(f"[!] Copy failed: {e}")
        return

    dl = VideoDownloader("test_downloads")
    # Test with a harmless short video
    test_url = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"
    
    # We'll temporarily rename temp_cookies to youtube_cookies.txt for the strategy to pick it up?
    # No, yt-dlp might not like SQLite format as a --cookies file.
    # But let's try it anyway.
    if os.path.exists("youtube_cookies.txt"):
        os.rename("youtube_cookies.txt", "youtube_cookies.txt.bak")
    
    shutil.copy2(temp_cookies, "youtube_cookies.txt")
    
    try:
        path, title = dl.download_video(test_url)
        if path:
            print(f"[SUCCESS] Downloaded: {title}")
        else:
            print("[FAILURE] Download failed even with fresh cookie copy.")
    finally:
        if os.path.exists("youtube_cookies.txt.bak"):
            os.remove("youtube_cookies.txt")
            os.rename("youtube_cookies.txt.bak", "youtube_cookies.txt")

if __name__ == "__main__":
    test_with_copied_cookies()
