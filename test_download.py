import os
import sys
from downloader import VideoDownloader

def test():
    # Make sure we have a cookies file
    if not os.path.exists("cookies.txt") and not os.path.exists("youtube_cookies.txt"):
        print("[!] Warning: Neither cookies.txt nor youtube_cookies.txt found. Trying anyway.")

    dl = VideoDownloader("test_downloads")
    
    # Test YouTube with the new Python API logic
    test_url = "https://www.youtube.com/watch?v=aqz-KE-bpKQ" 
    print(f"Testing URL: {test_url}")
    
    path, title = dl.download_video(test_url)
    if path and os.path.exists(path):
        print(f"SUCCESS: Downloaded '{title}' to {path}")
    else:
        print("FAILURE: Could not download video. Ensure proxy and cookies are correct.")

if __name__ == "__main__":
    test()
