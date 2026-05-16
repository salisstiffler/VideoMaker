import os
import sys
import time
import argparse
import subprocess
from downloader import VideoDownloader
from editor import VideoEditor
from intro_outro import concat_with_intro_outro
from cover_generator import generate_covers
from upload_utils import auto_upload

# 默认配置
DEFAULT_LOGO = "avrtar.jpg"
OUTPUT_ROOT = "output"
INTRO_DUR = 4.0
OUTRO_DUR = 5.0

def ensure_background_service():
    """
    自动启动后台上传服务窗口，并限制只上传从现在开始的任务
    """
    try:
        if os.path.exists("start_bg_uploader.bat"):
            # 记录当前时间，告诉后台服务只处理 10 分钟前到未来的视频（给当前正在生成的视频留点余量）
            start_ts = time.time() - 600 
            print(f"[*] 正在自动启动后台上传服务 (过滤历史任务)...")
            # 传递 --since 参数给 bat
            subprocess.Popen(["cmd", "/c", "start", "start_bg_uploader.bat", "--since", str(start_ts)], shell=True)
            time.sleep(2)
    except Exception as e:
        print(f"[!] 自动启动后台服务失败: {e}")

def process_single_video(video_source, logo_path, intro_dur, outro_dur, srt_path=None, dubbing_path=None, upload=True):
    """
    处理单个视频：下载(如果是URL) -> 加Logo/字幕/配音 -> 加片头片尾
    """
    print(f"\n{'='*60}")
    print(f"[*] 正在处理: {video_source}")
    print(f"{'='*60}\n")

    # 1. 准备视频文件
    video_path = None
    if video_source.startswith("http"):
        print("[*] 检测到 URL，正在下载...")
        downloader = VideoDownloader()
        video_path, title, _ = downloader.download_video(video_source)
        if not video_path or not os.path.exists(video_path):
            print(f"[-] 下载失败: {video_source}")
            return False
        print(f"[+] 下载完成: {video_path}")
    else:
        video_path = os.path.abspath(video_source)
        if not os.path.exists(video_path):
            print(f"[-] 找不到本地文件: {video_path}")
            return False

    base_name = os.path.splitext(os.path.basename(video_path))[0]
    project_dir = os.path.abspath(os.path.join(OUTPUT_ROOT, f"valorant_{base_name}"))
    os.makedirs(project_dir, exist_ok=True)

    # 2. 初始化编辑器并合成 (包含 Logo, 字幕, 配音)
    print("[*] 步骤 1/3: 正在进行视频基础合成 (Logo + 字幕 + 配音)...")
    editor = VideoEditor()
    try:
        logo_video = editor.burn_subtitles(
            video_path=video_path,
            srt_path=srt_path, 
            logo_path=logo_path,
            logo_pos="top-right",
            logo_margin=(20, 20),
            dubbing_path=dubbing_path,
            inst_path=None,
            output_dir=project_dir
        )
    except Exception as e:
        print(f"[-] 基础合成失败: {e}")
        return False

    if not logo_video or not os.path.exists(logo_video):
        print("[-] 基础合成产物丢失")
        return False

    # 3. 添加片头片尾
    print("[*] 步骤 2/3: 正在合成片头片尾...")
    final_output = os.path.join(project_dir, f"{base_name}_valorant_final.mp4")
    try:
        custom_text = {
            "intro_main": "欢迎来到Berlin的频道",
            "intro_sub": base_name,
            "intro_hint": "精彩内容 · 即刻开启",
            "outro_main": "感谢您的观看",
            "outro_sub": "欢迎点赞、关注、收藏"
        }
        result_video = concat_with_intro_outro(
            main_video=logo_video,
            output_path=final_output,
            intro_duration=intro_dur,
            outro_duration=outro_dur,
            text=custom_text
        )
        
        if result_video and os.path.exists(result_video):
            print(f"\n[✅] 最终视频生成成功: {result_video}")
            
            # 4. 生成封面图 (基于成品视频，效果更好)
            print("[*] 步骤 3/3: 正在生成吸引人的封面图...")
            best_cover = None
            try:
                # 标题使用原文件名
                cover_title = base_name 
                covers = generate_covers(
                    video_path=result_video,
                    title=cover_title,
                    output_dir=project_dir
                )
                # 优先使用 3:4 封面用于短视频平台
                best_cover = covers.get("3:4") or covers.get("4:3")
            except Exception as e:
                print(f"[!] 警告: 封面生成出错: {e}")
            
            # 5. 自动上传 (改为由后台服务接管，更稳定，不会丢任务)
            if upload:
                # 提示用户确保后台服务已启动
                print("[*] 任务已交由后台服务接管。请确保运行了 start_bg_uploader.bat")
                # 我们不再直接调用 auto_upload，而是让 background_uploader_service.py 扫描到这个成品后自动上传
                # 这样即使 valorant_producer.py 这里的循环很快结束，也不会影响后台进程的稳定性。
                # 如果用户非常急，可以在这里保留一个触发，但为了防止丢任务，后台轮询是最稳的。
                # 为了兼容性，我们依然可以调用一次，但现在的 auto_upload 已经改写为使用本地 uploader，
                # 并且 background_service 会通过 .flag 文件防止重复。
                try:
                    auto_upload(result_video, base_name, best_cover)
                except Exception as e:
                    print(f"[!] 自动上传触发提示失败 (不影响后台服务轮询): {e}")
                
            return True
        else:
            print("[-] 片头片尾合成失败")
            return False
    except Exception as e:
        print(f"[-] 流程出错: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Valorant 视频自动化处理脚本 (Logo + 字幕 + 配音 + 片头片尾 + 自动上传)")
    parser.add_argument("inputs", nargs="+", help="输入视频路径 or URL (支持多个)")
    parser.add_argument("--logo", default=DEFAULT_LOGO, help=f"Logo 文件路径 (默认 {DEFAULT_LOGO})")
    parser.add_argument("--intro", type=float, default=INTRO_DUR, help=f"片头时长 (默认 {INTRO_DUR}s)")
    parser.add_argument("--outro", type=float, default=OUTRO_DUR, help=f"片尾时长 (默认 {OUTRO_DUR}s)")
    parser.add_argument("--no-upload", action="store_false", dest="upload", default=True, help="合成完成后不自动上传")

    args = parser.parse_args()

    # 自动启动后台上传服务
    if args.upload:
        ensure_background_service()

    if not os.path.exists(args.logo):
        print(f"[!] 警告: 找不到 Logo 文件 {args.logo}，将不添加 Logo。")
        logo_to_use = None
    else:
        logo_to_use = args.logo

    success_count = 0
    total_count = len(args.inputs)

    for i, video_source in enumerate(args.inputs):
        print(f"\n>>> 进度: {i+1}/{total_count}")
        if process_single_video(video_source, logo_to_use, args.intro, args.outro, upload=args.upload):
            success_count += 1
        
    print(f"\n{'#'*60}")
    print(f"# 全部任务完成!")
    print(f"# 成功: {success_count} / 总计: {total_count}")
    print(f"{'#'*60}")

if __name__ == "__main__":
    main()
