@echo off
echo [*] Starting Playwright to refresh Douyin login...
echo [*] Please log in to your Douyin account in the opened browser window.
echo [*] After logging in, close the browser to save the authentication state.
python -m playwright codegen --save-storage=douyin_auth.json https://creator.douyin.com/
echo [!] Authentication state saved to douyin_auth.json.
pause
