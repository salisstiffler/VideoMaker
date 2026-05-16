import asyncio
import os
from bilibili_api import video_uploader, Credential

class BilibiliUploader:
    def __init__(self, sessdata: str, bili_jct: str, buvid3: str):
        """
        Initializes the Bilibili API with user credentials (Cookies).
        """
        self.cred = Credential(sessdata=sessdata, bili_jct=bili_jct, buvid3=buvid3)

    async def upload(self, video_path: str, title: str, description: str = "", tid: int = 171, tags: list = [], cover_path: str = None):
        """
        Uploads a video to Bilibili.
        """
        if not os.path.exists(video_path):
            print(f"[-] Video not found: {video_path}")
            return False

        print(f"[*] Starting Bilibili upload for: {title}")
        
        # Current version uses VideoUploaderPage and VideoUploader class
        page = video_uploader.VideoUploaderPage(
            path=video_path,
            title=title,
            description=description
        )

        meta = {
            "title": title,
            "tid": tid,
            "tag": ",".join(tags) if tags else "二次创作",
            "desc": description,
            "source": "自制",
            "copyright": 1
        }

        try:
            uploader = video_uploader.VideoUploader(
                pages=[page],
                meta=meta,
                credential=self.cred,
                cover=cover_path if cover_path else ""
            )
            # await uploader.start() returns the result
            result = await uploader.start()
            print(f"[+] Upload successful! Response: {result}")
            return True
        except Exception as e:
            print(f"[-] Upload failed: {e}")
            return False

if __name__ == "__main__":
    import argparse
    import os
    from dotenv import load_dotenv
    
    parser = argparse.ArgumentParser(description="Bilibili Video Uploader CLI")
    parser.add_argument("--video", required=True, help="Path to video file")
    parser.add_argument("--title", required=True, help="Video title")
    parser.add_argument("--cover", help="Path to cover image")
    parser.add_argument("--tid", type=int, default=171, help="Category ID (default: 171)")
    parser.add_argument("--tags", help="Comma-separated tags")
    
    args = parser.parse_args()
    
    load_dotenv()
    sessdata = os.getenv("BILI_SESSDATA")
    bili_jct = os.getenv("BILI_JCT")
    buvid3 = os.getenv("BILI_BUVID3")
    
    if not all([sessdata, bili_jct, buvid3]):
        print("[-] Error: Bilibili credentials missing in .env")
        sys.exit(1)
        
    uploader = BilibiliUploader(sessdata, bili_jct, buvid3)
    
    tags_list = args.tags.split(",") if args.tags else ["二次创作"]
    
    success = asyncio.run(uploader.upload(
        video_path=args.video,
        title=args.title,
        cover_path=args.cover,
        tid=args.tid,
        tags=tags_list
    ))
    
    if success:
        sys.exit(0)
    else:
        sys.exit(1)
