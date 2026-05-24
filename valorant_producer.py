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
INTRO_DUR = 3.0
OUTRO_DUR = 4.0

def process_single_video(video_source, logo_path, intro_dur, outro_dur, srt_path=None, dubbing_path=None, enable_upload=True):
    """
    处理单个视频：下载(如果是URL) -> 加Logo/字幕/配音 -> 加片头片尾 -> 自动发布
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
    print("[*] 步骤 1/4: 正在进行视频基础合成 (Logo + 字幕 + 配音)...")
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
    print("[*] 步骤 2/4: 正在合成片头片尾...")
    final_output = os.path.join(project_dir, f"{base_name}_valorant_final.mp4")
    try:
        custom_text = {
            "intro_main": "欢迎来到我的频道",
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
            print("[*] 步骤 3/4: 正在生成吸引人的封面图...")
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

            # 5. 自动发布
            if enable_upload:
                print("[*] 步骤 4/4: 正在触发后台自动上传 (B站 + 抖音)...")
                try:
                    # 去掉 valorant_ 前缀作为发布标题
                    upload_title = base_name
                    auto_upload(result_video, upload_title, best_cover)
                    print("[+] 后台上传任务已排队。")
                except Exception as e:
                    print(f"[!] 警告: 触发自动上传失败: {e}")
                
            return True
        else:
            print("[-] 片头片尾合成失败")
            return False
    except Exception as e:
        print(f"[-] 流程出错: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Valorant 视频自动化处理脚本")
    parser.add_argument("inputs", nargs="+", help="输入视频路径 or URL (支持多个)")
    parser.add_argument("--logo", default=DEFAULT_LOGO, help=f"Logo 文件路径 (默认 {DEFAULT_LOGO})")
    parser.add_argument("--intro", type=float, default=INTRO_DUR, help=f"片头时长 (默认 {INTRO_DUR}s)")
    parser.add_argument("--outro", type=float, default=OUTRO_DUR, help=f"片尾时长 (默认 {OUTRO_DUR}s)")
    parser.add_argument("--no-upload", action="store_false", dest="upload", default=True, help="制作完成后不自动发布到社交平台")

    args = parser.parse_args()

    if not os.path.exists(args.logo):
        print(f"[!] 警告: 找不到 Logo 文件 {args.logo}，将不添加 Logo。")
        logo_to_use = None
    else:
        logo_to_use = args.logo

    success_count = 0
    total_count = len(args.inputs)

    for i, video_source in enumerate(args.inputs):
        print(f"\n>>> 进度: {i+1}/{total_count}")
        if process_single_video(video_source, logo_to_use, args.intro, args.outro, enable_upload=args.upload):
            success_count += 1
        
    print(f"\n{'#'*60}")
    print(f"# 全部任务完成!")
    print(f"# 成功: {success_count} / 总计: {total_count}")
    print(f"{'#'*60}")

if __name__ == "__main__":
    main()
