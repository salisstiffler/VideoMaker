import os
import re
import time
import shutil
from typing import Optional, Tuple
import yt_dlp

class VideoDownloader:
    def __init__(self, base_dir: str = "downloads"):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)
        # Align with latest desktop script: Use proxy = False
        self.proxy = "http://127.0.0.1:7890"
        self.use_proxy = False
        self.cookies_file = "cookies.txt"
        if not os.path.exists(self.cookies_file):
            if os.path.exists("youtube_cookies.txt"):
                self.cookies_file = "youtube_cookies.txt"

    def clean_filename(self, filename: str) -> str:
        """Windows-safe filename cleaning."""
        name = re.sub(r'[\\/*?:"<>|]', "", filename)
        return name.strip().rstrip('.')

    def _find_mp4(self, directory: str) -> Optional[str]:
        """Find the first mp4 file in a directory."""
        for f in os.listdir(directory):
            if f.lower().endswith(".mp4"):
                return os.path.join(directory, f)
        return None

    def get_channel_videos_last_week(self, channel_url: str) -> list[str]:
        """Scrapes a channel URL and returns a list of video URLs from the last week."""
        print(f"[*] Searching for recent videos in channel (using API): {channel_url}")
        
        opts = {
            'extract_flat': 'in_playlist',
            'playlist_items': '1-20',
            'quiet': True,
        }
        
        # Don't use proxy for channel search if use_proxy is False
        if self.use_proxy and self.proxy:
            opts['proxy'] = self.proxy
        if os.path.exists(self.cookies_file):
            opts['cookiefile'] = self.cookies_file

        urls = []
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                result = ydl.extract_info(channel_url, download=False)
                if 'entries' in result:
                    for entry in result['entries']:
                        url = entry.get('url') or f"https://www.youtube.com/watch?v={entry.get('id')}"
                        urls.append(url)
            print(f"[+] Found {len(urls)} videos in channel.")
        except Exception as e:
            print(f"[!] Error scraping channel: {e}")
            
        return urls

    def get_channel_video_ids(self, channel_url: str, limit: int = 5) -> list[str]:
        """Quickly gets the last 'limit' video IDs from a channel."""
        print(f"[*] Checking channel IDs: {channel_url}")
        opts = {
            'extract_flat': 'in_playlist',
            'playlist_items': f'1-{limit}',
            'quiet': True,
        }
        if self.use_proxy and self.proxy:
            opts['proxy'] = self.proxy
        if os.path.exists(self.cookies_file):
            opts['cookiefile'] = self.cookies_file

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                result = ydl.extract_info(channel_url, download=False)
                if 'entries' in result:
                    return [entry.get('id') for entry in result['entries'] if entry.get('id')]
        except Exception as e:
            print(f"[!] Error checking channel IDs: {e}")
        return []

    def build_ydl_opts(self, video_dir: str, use_proxy: bool = False, client: str = "android") -> dict:
        """Constructs yt-dlp options based on working desktop script."""
        opts = {
            'outtmpl': f'{video_dir}/%(title)s.%(ext)s',
            # 🚀 强制优先 H.264 (高码率/大文件，与 IDM 一致)，次选 VP9，最后才选 AV1
            'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
            'merge_output_format': 'mp4',
            'cookies': self.cookies_file,
            'writethumbnail': True,  # 🚀 新增：获取封面
            'postprocessors': [
                {'key': 'FFmpegExtractAudio', 'preferredcodec': 'm4a', 'preferredquality': '192'},
                {'key': 'FFmpegThumbnailsConvertor', 'format': 'jpg', 'when': 'before_dl'}, # 🚀 将封面转为 jpg
            ],
            'extractor_args': {
                'youtube': {
                    'player_client': [client]
                }
            },
            'retries': 10,
            'fragment_retries': 10,
            'ignoreerrors': True,
            'quiet': False,
            'no_warnings': False,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                'Accept-Language': 'en-US,en;q=0.9',
            },
        }
        
        if use_proxy and self.proxy:
            opts['proxy'] = self.proxy
        else:
            # 强制不使用任何代理 (防止读取系统环境变量中的代理)
            opts['proxy'] = ""
            
        return opts

    def download_video(self, url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Returns (video_path, title, thumbnail_path)"""
        url = url.split('&')[0]
        
        # 🚀 优化：从 URL 中提取唯一 ID，防止重复下载
        video_id = "unknown"
        if "youtube.com" in url or "youtu.be" in url:
            match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11})", url)
            if match: video_id = match.group(1)
        elif "bilibili.com" in url:
            match = re.search(r"(BV[0-9A-Za-z]+)", url)
            if match: video_id = match.group(1)
        
        # 如果无法提取 ID，则降级使用缓存的哈希值
        if video_id == "unknown":
            import hashlib
            video_id = hashlib.md5(url.encode()).hexdigest()[:12]

        print(f"\n[*] New Download Request (Unique ID: {video_id}): {url}")

        video_dir = os.path.abspath(os.path.join(self.base_dir, video_id))
        os.makedirs(video_dir, exist_ok=True)

        # Implementation of the user's successful sequential strategies
        # 策略重调：优先使用 tv_embedded 和 web_safari，目前它们最容易获取 1080p
        strategies = [
            ("tv_embedded", False), # 🚀 尝试 1: TV 客户端 (最容易无 PO Token 获取高分辨率)
            ("web_safari", False),  # 🚀 尝试 2: 网页 Safari (配合 Cookies 成功率高)
            ("android", False),     # 🚀 尝试 3: Android 直连
            ("android", True),      # 🚀 尝试 4: Android + 代理 (最后备份)
        ]

        for i, (client, use_proxy) in enumerate(strategies):
            print(f"\n🚀 Attempt {i+1}: client={client}, use_proxy={use_proxy}")
            try:
                ydl_opts = self.build_ydl_opts(video_dir, use_proxy=use_proxy, client=client)
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    error_code = ydl.download([url])
                    if error_code == 0:
                        mp4 = self._find_mp4(video_dir)
                        thb = self._find_thumbnail(video_dir)
                        if mp4:
                            title = self.clean_filename(os.path.splitext(os.path.basename(mp4))[0])
                            print(f"[+] Download Success: {title} (Strategy: {client})")
                            return mp4, title, thb
            except Exception as e:
                print(f"❌ Attempt {i+1} failed: {e}")

        print("\n[-] All download strategies failed for this URL.")
        return None, None, None
