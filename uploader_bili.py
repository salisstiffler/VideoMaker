import asyncio
import os
from bilibili_api import video_uploader, Credential

class BilibiliUploader:
    def __init__(self, sessdata: str, bili_jct: str, buvid3: str):
        """
        Initializes the Bilibili API with user credentials (Cookies).
        """
        self.cred = Credential(sessdata=sessdata, bili_jct=bili_jct, buvid3=buvid3)

    async def upload(self, video_path: str, title: str, description: str = "", tid: int = 171, tags: list = []):
        """
        Uploads a video to Bilibili.
        tid=171 is usually Electronic Games/Video Games. Update depending on your niche!
        """
        if not os.path.exists(video_path):
            print(f"[-] Video not found: {video_path}")
            return False

        print(f"[*] Starting Bilibili upload for: {title}")
        page = video_uploader.VideoUploaderPage(path=video_path, title=title, description=description)

        try:
            # The uploader expects an event loop, we use it to upload
            result = await video_uploader.upload(
                pages=[page],
                title=title,
                tid=tid,
                tag=",".join(tags) if tags else "二次创作",
                desc=description,
                source="自制",
                credential=self.cred
            )
            print(f"[+] Upload successful! Response: {result}")
            return True
        except Exception as e:
            print(f"[-] Upload failed: {e}")
            return False

if __name__ == "__main__":
    # Test snippet (replace with actual SESSDATA, BILI_JCT, BUVID3 from browser cookies)
    # import dotenv
    # dotenv.load_dotenv()
    # sessdata = os.getenv("BILI_SESSDATA")
    # bili_jct = os.getenv("BILI_JCT")
    # buvid3 = os.getenv("BILI_BUVID3")
    # uploader = BilibiliUploader(sessdata, bili_jct, buvid3)
    # asyncio.run(uploader.upload("output/test.mp4", "My Test Video", "Enjoy!"))
    pass
