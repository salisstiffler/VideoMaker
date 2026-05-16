@echo off
echo ==================================================
echo [*] VideoCapter Background Uploader Service
echo ==================================================
echo [*] Scanning 'output' folder every 60 seconds...
echo [*] Platforms: Douyin, Bilibili
echo [*] Log: logs\bg_service.log
echo --------------------------------------------------
python background_uploader_service.py %*
pause
