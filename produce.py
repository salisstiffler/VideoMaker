import os
import sys
import argparse
import time
import shutil
from downloader import VideoDownloader
from editor import VideoEditor
from translator_timing import batch_translate_with_context

def produce_final_video(url_or_path, ref_voice=None, logo_path="avrtar.jpg", output_root="output"):
    """
    一键化生产流程：下载/读取 -> 分离 -> 对齐 -> 翻译 -> 配音 -> 合成
    """
    start_total = time.time()
    
    # 1. 确定视频来源
    video_path = None
    title = "output_video"
    
    if os.path.exists(url_or_path):
        video_path = os.path.abspath(url_or_path)
        title = os.path.splitext(os.path.basename(video_path))[0]
        print(f"[📍] 使用本地视频: {video_path}")
    else:
        print(f"[🌐] 正在下载视频: {url_or_path}")
        dl = VideoDownloader()
        video_path, title, _ = dl.download_video(url_or_path)
        if not video_path:
            print("[-] 错误: 下载视频失败。")
            return

    # 2. 准备工作目录
    base_name = title.replace(" ", "_")
    work_dir = os.path.join(os.path.abspath(output_root), base_name)
    os.makedirs(work_dir, exist_ok=True)
    
    # 3. 初始化组件
    editor = VideoEditor(model_size="base")
    
    # 4. 声音检测
    if not ref_voice or not os.path.exists(ref_voice):
        if os.path.exists("default_voice.wav"):
            ref_voice = os.path.abspath("default_voice.wav")
        else:
            from native_main import find_default_voice
            ref_voice = find_default_voice()

    print(f"\n[🚀] 生产任务启动: {title}")
    print(f"[🎤] 默认音色: {ref_voice}")
    print(f"[🖼️] 默认 Logo: {logo_path}")

    # 5. UVR 深度消音
    print("\n[🎙️] 步骤 1: UVR HQ 级消音 (彻底消除原英文)...")
    inst_path, _ = editor.separate_audio(video_path, output_dir=output_root)
    
    # 6. WhisperX 转录与精准对齐
    print("\n[📝] 步骤 2: WhisperX 单词级精准卡点...")
    srt_path, segments, _ = editor.generate_subtitles(video_path, output_dir=output_root)
    if not segments:
        print("[-] 错误: 提取字幕片段失败。")
        return

    # 7. 上下文联想翻译
    print(f"\n[㊙️] 步骤 3: 正在进行 3.8字/秒 上下文智能翻译...")
    bilingual_srt_refined = os.path.join(work_dir, f"{base_name}_bilingual_refined.srt")
    if os.path.exists(bilingual_srt_refined):
        print("[+] 加载缓存翻译结果...")
        translated_texts = []
        with open(bilingual_srt_refined, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for i in range(len(lines)):
                if "-->" in lines[i] and i + 1 < len(lines):
                    translated_texts.append(lines[i+1].strip())
    else:
        translated_texts = batch_translate_with_context(segments, chars_per_sec=3.8)
        with open(bilingual_srt_refined, "w", encoding="utf-8") as f:
            for i, ((sts, ets, original), translated) in enumerate(zip(segments, translated_texts), start=1):
                f.write(f"{i}\n{editor.format_time(sts)} --> {editor.format_time(ets)}\n")
                f.write(f"{translated}\n{original}\n\n")

    # 8. F5-TTS 分组连贯配音
    print("\n[🎧] 步骤 4: F5-TTS 生产级分组配音生成...")
    dub_path = editor.generate_dubbing(segments, translated_texts, ref_voice, video_path, output_dir=output_root)
    if not dub_path:
        print("[-] 错误: 配音轨道生成失败。")
        return

    # 9. 最终合成 (含 Logo 和 侧链混音)
    print("\n[🎬] 步骤 5: FFmpeg 全功能专业合成...")
    final_output = editor.burn_subtitles(
        video_path=video_path,
        srt_path=bilingual_srt_refined,
        logo_path=logo_path,
        dubbing_path=dub_path,
        inst_path=inst_path,
        output_dir=output_root
    )

    duration_total = time.time() - start_total
    print(f"\n[✅] 全片生产完成！")
    print(f"[⏱️] 总执行时长: {duration_total/60:.1f} 分钟")
    
    final_dir = os.path.abspath("final_outputs")
    os.makedirs(final_dir, exist_ok=True)
    final_dest = os.path.join(final_dir, f"{base_name}_final_produced.mp4")
    shutil.copy(final_output, final_dest)
    print(f"[🎥] 最终大片已归档至: {final_dest}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--voice", default=None)
    parser.add_argument("--logo", default="avrtar.jpg")
    args = parser.parse_args()
    produce_final_video(args.source, args.voice, args.logo)
