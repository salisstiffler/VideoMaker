import os
import subprocess
import time
from editor import VideoEditor
from translator_timing import translate_with_timing

def test_1min_pipeline():
    # 1. 准备路径
    source_video = r"D:\videoCapter\downloads\1774960416\They Rented a Famous Serial Killer House Not Knowing The Killer is Hiding as Prop.mp4"
    ref_voice = r"D:\videoCapter\my_voice.wav"
    output_dir = r"D:\videoCapter\output"
    
    video_1min = os.path.join(output_dir, "test_1min.mp4")
    
    # 确保存储目录和测试视频
    os.makedirs(output_dir, exist_ok=True)
    
    if not os.path.exists(source_video):
        print(f"[-] 源视频不存在: {source_video}")
        return
        
    print(f"\n[1] 正在截取前 60 秒的视频用于测试...")
    cmd_trim = ["ffmpeg", "-y", "-i", source_video, "-t", "60", "-c", "copy", video_1min]
    subprocess.run(cmd_trim, capture_output=True)
    
    if not os.path.exists(video_1min):
        print("[-] 截取失败")
        return
        
    print("[+] 视频截取成功。")

    # 2. 初始化 Editor
    editor = VideoEditor(model_size="base")
    
    # 3. UVR 背景音分离 (如果环境有问题则跳过)
    print("\n[2] 开始分离人声与背景音 (UVR)...")
    try:
        inst_path, voc_path = editor.separate_audio(video_1min, output_dir=output_dir)
        print(f"[+] 背景音路径: {inst_path}")
    except Exception as e:
        print(f"[-] 分离人声失败 (跳过): {e}")
        inst_path = ""
    
    # 4. 转录
    print("\n[3] 提取英文字幕 (Faster-Whisper)...")
    srt_path, segments, _ = editor.generate_subtitles(video_1min, output_dir=output_dir)
    if not segments:
        print("[-] 提取字幕失败或无对白")
        return
        
    # 5. 等时长翻译
    print(f"\n[4] 开始等时长限制翻译 (共 {len(segments)} 句)...")
    translated_texts = []
    for i, (sts, ets, text) in enumerate(segments):
        dur = ets - sts
        if dur < 0.3 or not text.strip():
            translated_texts.append("")
            continue
        print(f"  [{i+1}/{len(segments)}] {dur:.1f}s | {text}")
        zh_text = translate_with_timing(text, dur)
        print(f"  -> 翻译({len(zh_text)}字): {zh_text}")
        translated_texts.append(zh_text)
        
    # 生成新的双语 SRT
    bilingual_srt_path = srt_path.replace(".srt", "_zh.srt")
    with open(bilingual_srt_path, "w", encoding="utf-8") as f:
        for i, ((start, end, original), translated) in enumerate(zip(segments, translated_texts), start=1):
            f.write(f"{i}\n{editor.format_time(start)} --> {editor.format_time(end)}\n")
            f.write(f"{translated}\n{original}\n\n")

    # 6. 配音
    print("\n[5] F5-TTS 生成时间适配配音...")
    dub_path = editor.generate_dubbing(segments, translated_texts, ref_voice, video_1min, output_dir=output_dir)
    if not dub_path:
        print("[-] 配音失败")
        return

    # 7. 合并
    print("\n[6] FFmpeg 最终合并 (背景音 + 配音 + 字幕)...")
    final_video = editor.burn_subtitles(
        video_path=video_1min,
        srt_path=bilingual_srt_path,
        dubbing_path=dub_path,
        inst_path=inst_path,
        output_dir=output_dir
    )
    
    print(f"\n[SUCCESS] 测试完成！\n最终产物: {final_video}")

if __name__ == "__main__":
    test_1min_pipeline()
