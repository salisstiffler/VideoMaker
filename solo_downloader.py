import os
import subprocess

def main():
    url = "https://www.youtube.com/watch?v=TJZlEyFLXbM"
    output_path = "test_download_result.mp4"
    
    print("\n[*] ATTEMPTING THE LAST STAND: MWEB Client (PO-Token Bypass attempt)")
    
    # The 'mweb' client often avoids the strict PO-Token check required by iOS/Android apps
    cmd = [
        "yt-dlp",
        "--no-check-certificate",
        "--extractor-args", "youtube:player_client=mweb",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--cookies", "youtube_cookies.txt",
        "-o", output_path,
        url
    ]
    
    try:
        subprocess.run(cmd, check=True)
        print("\n[!!!] IT WORKED! MWEB IS THE KEY.")
    except:
        print("\n[X] MWEB also failed. YouTube's PO-Token wall is complete.")
        print("[!] SUGGESTION: Download the video manually via browser extension and place it in the project folder.")

if __name__ == "__main__":
    main()
