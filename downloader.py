import os
import subprocess
import re
import time
import shutil
import tempfile
from typing import Optional, Tuple


class VideoDownloader:
    def __init__(self, base_dir: str = "downloads"):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

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

    def _run_cmd(self, cmd: list, label: str) -> tuple[bool, str]:
        """Run a subprocess command; return (success, stderr_snippet)."""
        print(f"[*] {label}")
        print(f"    CMD: {' '.join(cmd)}")
        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
            )
            return True, ""
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "")[-600:]
            print(f"[!] {label} — exit code {e.returncode}")
            if stderr:
                print(f"    STDERR: {stderr[-300:]}")
            return False, stderr
        except subprocess.TimeoutExpired:
            print(f"[!] {label} — timed out after 300s")
            return False, "timeout"
        except FileNotFoundError:
            print("[!] yt-dlp not found. Install: pip install -U yt-dlp")
            return False, "not_found"
        except Exception as e:
            print(f"[!] {label} — unexpected: {e}")
            return False, str(e)

    def get_channel_videos_last_week(self, channel_url: str) -> list[str]:
        """
        Scrapes a channel URL and returns a list of video URLs uploaded in the last week.
        """
        print(f"[*] Searching for recent videos in channel: {channel_url}")
        
        # Use yt-dlp to get URLs of videos from the last 7 days
        # --dateafter now-7days : filter by date
        # --get-id or --get-url : just get the metadata
        # --flat-playlist : don't extract individual video info (faster)
        cmd = [
            "yt-dlp",
            "--no-check-certificate",
            "--flat-playlist",
            "--get-id",
            "--dateafter", "now-7days",
            channel_url
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60
            )
            if result.returncode == 0:
                video_ids = result.stdout.strip().split('\n')
                urls = [f"https://www.youtube.com/watch?v={vid.strip()}" for vid in video_ids if vid.strip()]
                print(f"[+] Found {len(urls)} videos from the last 7 days.")
                return urls
            else:
                print(f"[!] Failed to scrape channel: {result.stderr}")
        except Exception as e:
            print(f"[!] Error scraping channel: {e}")
            
        return []

    def get_channel_video_ids(self, channel_url: str, limit: int = 5) -> list[str]:
        """
        Quickly gets the last 'limit' video IDs from a channel.
        """
        print(f"[*] Checking channel for latest {limit} videos: {channel_url}")
        cmd = [
            "yt-dlp",
            "--no-check-certificate",
            "--flat-playlist",
            "--get-id",
            "--playlist-end", str(limit),
            channel_url
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            if result.returncode == 0:
                return [vid.strip() for vid in result.stdout.strip().split('\n') if vid.strip()]
        except Exception as e:
            print(f"[!] Error checking channel IDs: {e}")
        return []

    def download_video(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        # 1. URL Cleanup — strip tracking parameters
        url = url.split('&')[0]
        print(f"\n[*] Downloading: {url}")

        video_id = str(int(time.time()))
        video_dir = os.path.abspath(os.path.join(self.base_dir, video_id))
        os.makedirs(video_dir, exist_ok=True)

        out_template = os.path.join(video_dir, "%(title)s.%(ext)s")

        # ------------------------------------------------------------------ #
        # Base options shared across all strategies
        # --no-check-certificate : skip SSL verification
        # --merge-output-format mp4 : always produce .mp4
        # --format : prefer h264 (most compatible) then best
        # --extractor-args : use ios client — most reliable in 2024-2025
        # --no-playlist : never accidentally grab a whole playlist
        # ------------------------------------------------------------------ #
        base_opts = [
            "yt-dlp",
            "--no-check-certificate",
            "--no-warnings",
            "--no-playlist",
            "--merge-output-format", "mp4",
            # General fallback: Prefer 1080p, but allow 720p or lower if needed.
            # Don't strictly force avc1 in the selector, just sort it higher.
            "--format", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
            "--format-sort", "res:1080,vcodec:avc1,fps,size",
            "--socket-timeout", "30",
            # Download video in 8 parallel fragments — much faster on fast connections
            "--concurrent-fragments", "8",
            "-o", out_template,
        ]

        # ------------------------------------------------------------------ #
        # STRATEGY 1 — Manual cookie file (most reliable when present)
        # Export cookies with "Get cookies.txt LOCALLY" Chrome extension,
        # save as youtube_cookies.txt next to this script.
        # ------------------------------------------------------------------ #
        if os.path.exists(cookie_file):
            # Strategy 1 with cookies: Allow more formats (avc1 preferred but not strictly required)
            cookie_cmd = [
                "yt-dlp",
                "--no-check-certificate", "--no-warnings", "--no-playlist",
                "--merge-output-format", "mp4",
                # Best video+audio, prefer 1080p, fallback to 720p or any.
                "--format", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
                "--format-sort", "res:1080,vcodec:avc1,fps,size",
                "--concurrent-fragments", "8",
                "--socket-timeout", "30",
                "--cookies", cookie_file,
                "-o", out_template,
                url,
            ]
            ok, _ = self._run_cmd(cookie_cmd, "Strategy 1: manual cookies file")
            if ok:
                mp4 = self._find_mp4(video_dir)
                if mp4:
                    title = self.clean_filename(os.path.splitext(os.path.basename(mp4))[0])
                    return mp4, title

        # ------------------------------------------------------------------ #
        # STRATEGY 2 — Live browser session (Chrome → Edge → Firefox)
        # Works while the browser is running and user is logged in.
        # ------------------------------------------------------------------ #
        # Fast-fail keywords: if we see these errors, browser cookies won't work —
        # skip remaining browser strategies immediately
        BROWSER_FATAL_ERRORS = ("could not copy", "dpapi", "locked", "could not find")

        for browser in ["chrome", "edge", "firefox"]:
            cmd = base_opts + ["--cookies-from-browser", browser, url]
            ok, stderr = self._run_cmd(cmd, f"Strategy 2: live {browser} session")
            if ok:
                mp4 = self._find_mp4(video_dir)
                if mp4:
                    title = self.clean_filename(os.path.splitext(os.path.basename(mp4))[0])
                    return mp4, title
            # If it's a known-bad cookie error, don't bother with other browsers
            if any(kw in stderr.lower() for kw in BROWSER_FATAL_ERRORS):
                print(f"    [!] Browser cookie extraction not available — skipping remaining browser strategies")
                break

        # ------------------------------------------------------------------ #
        # STRATEGY 3 — No cookies, fallback player clients
        # Try tv_embedded and mweb clients as last resort.
        # ------------------------------------------------------------------ #
        for client in ["android_vr", "tv_embedded", "mweb"]:
            cmd = [
                "yt-dlp",
                "--no-check-certificate",
                "--no-playlist",
                "--merge-output-format", "mp4",
                # android_vr only exposes combined streams (360p/720p)
                # Use bestvideo+bestaudio to get the highest available for this client
                "--format", "bestvideo+bestaudio/best",
                "--format-sort", "res,fps",
                "--concurrent-fragments", "8",
                "--extractor-args", f"youtube:player_client={client}",
                "--socket-timeout", "30",
                "-o", out_template,
                url,
            ]
            ok, _ = self._run_cmd(cmd, f"Strategy 3: no-cookie fallback (client={client})")
            if ok:
                mp4 = self._find_mp4(video_dir)
                if mp4:
                    title = self.clean_filename(os.path.splitext(os.path.basename(mp4))[0])
                    return mp4, title

        print("\n[-] All download strategies failed for this URL.")
        print("    Tips:")
        print("    1. Update yt-dlp:  pip install -U yt-dlp")
        print("    2. Export cookies from your browser and save as youtube_cookies.txt")
        print("    3. Make sure Chrome/Edge is open and logged in for Strategy 2")
        return None, None
