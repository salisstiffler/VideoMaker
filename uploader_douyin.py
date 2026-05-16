from playwright.sync_api import sync_playwright
import time
import os
import re
import sys
import argparse
import datetime

def log_message(message, log_file="douyin_upload.log"):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_msg = f"[{timestamp}] {message}"
    print(formatted_msg)
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(formatted_msg + "\n")
    except:
        pass

class DouyinUploader:
    def __init__(self, auth_state_path: str = "douyin_auth.json"):
        """
        Douyin Uploader using Playwright. 
        Requires you to first log in and save the authentication state to `douyin_auth.json`.
        """
        self.auth_state_path = auth_state_path

    def upload(self, video_path: str, title: str, cover_path: str = None):
        if not os.path.exists(video_path):
            log_message(f"[-] Video not found: {video_path}")
            return False

        if not os.path.exists(self.auth_state_path):
            log_message(f"[-] Auth state not found: {self.auth_state_path}")
            log_message(f"[-] Please run `playwright codegen --save-storage={self.auth_state_path} https://creator.douyin.com/` to login first.")
            return False

        log_message(f"[*] Starting Douyin upload for: {title}")
        try:
            with sync_playwright() as p:
                # Using headless=False because Douyin frequently blocks headless uploads or changes UI
                browser = p.chromium.launch(headless=False) 
                context = browser.new_context(storage_state=self.auth_state_path)
                page = context.new_page()

                # Go to Douyin Creator Studio upload page
                log_message("[*] Navigating to Douyin upload page...")
                page.goto("https://creator.douyin.com/creator-micro/content/upload")
                
                # Check login
                if "login" in page.url:
                    log_message("[-] Error: Douyin authentication expired.")
                    return False

                page.wait_for_load_state("networkidle")

                # Try to click the "Upload" box first to ensure it's ready
                log_message("[*] Locating and triggering upload...")
                try:
                    upload_area = page.locator("text=发布视频, text=点击上传, .upload-btn").first
                    upload_area.click(timeout=5000)
                    page.wait_for_timeout(1000)
                except:
                    pass

                # Set the file
                file_input = page.locator("input[type='file']").first
                file_input.set_input_files(video_path)
                
                log_message("[*] Video file selected. Starting data entry immediately...")
                
                # 3. 选定文件后，不再等待 100%，立即填写资料
                log_message("[*] Setting title and cover immediately...")
                
                # 等待标题输入框出现（通常文件一选定就会出现）
                title_input = None
                title_selectors = ["div[contenteditable='true']", "[placeholder*='添加作品描述']", ".zone-title"]
                for selector in title_selectors:
                    try:
                        title_input = page.wait_for_selector(selector, timeout=20000)
                        if title_input: break
                    except: continue

                if not title_input:
                    log_message("[-] Error: Video editor UI did not appear. Upload likely failed or was rejected.")
                    return False

                # 设置标题
                title_input.click()
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                page.keyboard.type(title, delay=50)
                log_message("[+] Title set.")

                # 4. 设置封面
                if cover_path and os.path.exists(cover_path):
                    try:
                        log_message("[*] Attempting to set cover...")
                        cover_btn = None
                        cover_selectors = [
                            "text=编辑封面", "text=设置封面", 
                            ".cover-edit-btn", ".cover-container",
                            "//div[contains(text(), '封面')]",
                            "//button[contains(., '封面')]"
                        ]
                        
                        for sel in cover_selectors:
                            try:
                                btn = page.locator(sel).first
                                if btn.is_visible(timeout=5000):
                                    cover_btn = btn
                                    break
                            except: continue
                        
                        if not cover_btn:
                            cover_btn = page.get_by_text(re.compile(r"(编辑|设置)封面")).first
                        
                        if cover_btn:
                            cover_btn.click(timeout=10000, force=True)
                            page.wait_for_selector("text=上传封面", timeout=10000)
                            page.click("text=上传封面")
                            cover_input = page.locator("input[type='file']").last
                            cover_input.set_input_files(cover_path)
                            page.wait_for_timeout(4000)
                            
                            for sel in ["text=确定", "text=完成", "text=保存", ".save-btn"]:
                                try:
                                    btn = page.locator(sel).last
                                    if btn.is_visible(timeout=2000):
                                        btn.click()
                                        break
                                except: continue
                            log_message("[+] Cover set.")
                    except Exception as e:
                        log_message(f"[!] Warning: Could not set cover: {e}")

                # 5. 尝试提前点击发布
                log_message("[*] Attempting to click publish (will retry until enabled)...")
                publish_btn = page.get_by_role("button", name="发布", exact=True)
                
                # 循环尝试点击，给一定的重试时间（比如 5 分钟）
                published = False
                for i in range(100): 
                    # 处理可能出现的遮挡弹窗
                    try:
                        temp_btn = page.locator("text=确定, text=我知道了").first
                        if temp_btn.is_visible(timeout=500):
                            temp_btn.click()
                    except: pass

                    if publish_btn.is_enabled():
                        publish_btn.click()
                        log_message("[+] Publish button clicked!")
                        published = True
                        break
                    
                    if i % 10 == 0:
                        log_message(f"[*] Waiting for publish button to be enabled ({i*3}s elapsed)...")
                    page.wait_for_timeout(3000)
                
                # 6. 不主动关闭浏览器，保持页面在后台运行
                log_message("[✅] Task submitted to browser. Leaving it OPEN to complete background upload...")
                
                # 创建 flag 表示任务已提交
                try:
                    flag_file = os.path.join(os.path.dirname(os.path.abspath(video_path)), f"{os.path.basename(video_path)}_douyin.flag")
                    with open(flag_file, "w") as f:
                        f.write(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                except: pass

                # 此时我们进入无限等待，直到进程被外部杀死
                # 这样浏览器窗口会一直保持打开状态
                while True:
                    page.wait_for_timeout(60000)
                
            return True
        except Exception as e:
            log_message(f"[-] Douyin upload failed: {e}")
            return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Douyin Video Uploader")
    parser.add_argument("--video", required=True, help="Path to video file")
    parser.add_argument("--title", required=True, help="Video title")
    parser.add_argument("--cover", help="Path to cover image")
    parser.add_argument("--auth", default="douyin_auth.json", help="Path to auth state JSON")
    
    args = parser.parse_args()
    
    uploader = DouyinUploader(auth_state_path=args.auth)
    success = uploader.upload(video_path=args.video, title=args.title, cover_path=args.cover)
    
    if success:
        sys.exit(0)
    else:
        sys.exit(1)
