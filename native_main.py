import os
import sys
import argparse
import time
from editor import VideoEditor
from translator_timing import batch_translate_with_context

DEFAULT_LOGO = "avrtar.jpg"
DEFAULT_MARGIN = 20

def find_default_voice():
    """尝试寻找项目根目录下的 default_voice.wav"""
    p = "default_voice.wav"
    if os.path.exists(p):
        return p
    return None

def run_native_pipeline(video_path, ref_voice=None, output_dir="output"):
    """
    全链路原生翻译配音生产流程
    """
    if not ref_voice or not os.path.exists(ref_voice):
        ref_voice = find_default_voice()
        print(f"[*] 未指定声音或路径无效，使用默认音色: {ref_voice}")
    start_time = time.time()
    video_path = os.path.abspath(video_path)
    if not os.path.exists(video_path):
        print(f"[-] 找不到视频文件: {video_path}")
        return

    base_name = os.path.splitext(os.path.basename(video_path))[0]
    work_dir = os.path.join(os.path.abspath(output_dir), base_name)
    os.makedirs(work_dir, exist_ok=True)

    print(f"\n[🚀] 开始处理: {base_name}")
    print(f"[📍] 工作目录: {work_dir}")

    # 1. 初始化
    editor = VideoEditor(model_size="base")

    # 2. UVR 人声背景音分离
    print("\n[🎙️] 步骤 1: UVR 氛围音分离...")
    inst_path, _ = editor.separate_audio(video_path, output_dir=output_dir)
    if not inst_path:
        print("[!] 警告: 未能分离出背景音，将使用原音合成。")

    # 3. 语音转录 (Faster-Whisper)
    print("\n[📝] 步骤 2: 提取英文字幕...")
    srt_path, segments, _ = editor.generate_subtitles(video_path, output_dir=output_dir)
    if not segments:
        print("[-] 错误: 未能在视频中检测到对白。")
        return

    # 4. 上下文适配翻译
    print(f"\n[㊙️] 步骤 3: 正在进行等时长上下文翻译 (共 {len(segments)} 句)...")
    # 检查是否已有翻译好的双语字幕，避免重复消耗 API
    bilingual_srt_path = os.path.join(work_dir, f"{base_name}_bilingual_refined.srt")
    
    if os.path.exists(bilingual_srt_path):
        print("[+] 发现已存在的优化字幕，正在加载...")
        translated_texts = []
        with open(bilingual_srt_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            # 简单解析已有的双语字幕获取中文行
            for i in range(len(lines)):
                if "-->" in lines[i] and i + 1 < len(lines):
                    translated_texts.append(lines[i+1].strip())
    else:
        translated_texts = batch_translate_with_context(segments, chars_per_sec=3.8)
        # 写入优化后的双语 SRT
        with open(bilingual_srt_path, "w", encoding="utf-8") as f:
            for i, ((start, end, original), translated) in enumerate(zip(segments, translated_texts), start=1):
                f.write(f"{i}\n{editor.format_time(start)} --> {editor.format_time(end)}\n")
                f.write(f"{translated}\n{original}\n\n")
        print(f"[+] 优化版双语字幕已保存: {bilingual_srt_path}")

    # 5. F5-TTS 配音生成
    print("\n[🎧] 步骤 4: F5-TTS 极速音色克隆配音...")
    ref_voice_path = os.path.abspath(ref_voice)
    dub_path = editor.generate_dubbing(segments, translated_texts, ref_voice_path, video_path, output_dir=output_dir)
    if not dub_path:
        print("[-] 错误: 配音生成失败。")
        return

    # 6. 最终合成
    print("\n[🎬] 步骤 5: FFmpeg 侧链闪避混音合成...")
    logo_path = DEFAULT_LOGO if os.path.exists(DEFAULT_LOGO) else None
    final_video = editor.burn_subtitles(
        video_path=video_path,
        srt_path=bilingual_srt_path,
        margin_v=DEFAULT_MARGIN,
        logo_path=logo_path,
        dubbing_path=dub_path,
        inst_path=inst_path,
        output_dir=output_dir
    )

    total_dur = time.time() - start_time
    print(f"\n[✅] 恭喜！全链路处理完成。")
    print(f"[⏱️] 总耗时: {total_dur/60:.1f} 分钟")
    print(f"[🎥] 最终大片: {final_video}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VideoCapter 原生全链路翻译配音工具")
    parser.add_argument("video", help="待处理的视频文件路径")
    parser.add_argument("--voice", default=None, help="参考音色 (wav格式)，不指定则使用系统默认男声")
    parser.add_argument("--output", default="output", help="输出根目录")
    
    args = parser.parse_args()
    
    run_native_pipeline(args.video, args.voice, args.output)
