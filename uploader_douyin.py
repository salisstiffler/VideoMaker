from playwright.sync_api import sync_playwright
import time
import os

class DouyinUploader:
    def __init__(self, auth_state_path: str = "douyin_auth.json"):
        """
        Douyin Uploader using Playwright. 
        Requires you to first log in and save the authentication state to `douyin_auth.json`.
        """
        self.auth_state_path = auth_state_path

    def upload(self, video_path: str, title: str):
        if not os.path.exists(video_path):
            print(f"[-] Video not found: {video_path}")
            return False

        if not os.path.exists(self.auth_state_path):
            print(f"[-] Auth state not found: {self.auth_state_path}")
            print(f"[-] Please run `playwright codegen --save-storage={self.auth_state_path} https://creator.douyin.com/` to login first.")
            return False

        print(f"[*] Starting Douyin upload for: {title}")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False) # Headless=False usually helps bypass bot detection
                context = browser.new_context(storage_state=self.auth_state_path)
                page = context.new_page()

                # Go to Douyin Creator Studio upload page
                page.goto("https://creator.douyin.com/creator-micro/content/upload")
                page.wait_for_load_state("networkidle")

                # The exact selectors depend on the current Douyin layout, these might need updating over time
                # Look for the input[type=file]
                file_input = page.locator("input[type='file']")
                file_input.set_input_files(video_path)
                
                print("[*] Uploading video file...")
                # Wait for the title input box to be visible after upload completes
                page.wait_for_selector(".zone-title", timeout=60000) 
                
                print("[*] Setting title...")
                # Clear and set the title
                title_input = page.locator(".zone-title")
                title_input.fill("")
                title_input.type(title, delay=100)

                print("[*] Publishing...")
                # Click the publish button
                publish_btn = page.locator("button:has-text('发布')")
                publish_btn.click()
                
                # Wait for success message
                page.wait_for_selector(".toast-success", timeout=30000)
                print(f"[+] Douyin upload successful!")
                
                context.close()
                browser.close()
            return True
        except Exception as e:
            print(f"[-] Douyin upload failed: {e}")
            return False

if __name__ == "__main__":
    pass
