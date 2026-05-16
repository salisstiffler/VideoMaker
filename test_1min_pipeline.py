import os
import subprocess
import shutil
from valorant_producer import process_single_video
from editor import VideoEditor
from cover_generator import generate_covers

def run_1min_test(input_video, logo_path="avrtar.jpg"):
    print("\n" + "="*60)
    print("[🚀] 开始 1 分钟全流程压力测试...")
    print("="*60)

    if not os.path.exists(input_video):
        print(f"[-] 错误: 找不到输入视频 {input_video}")
        return

    # 1. 准备临时文件和 1 分钟片段
    base_name = os.path.splitext(os.path.basename(input_video))[0]
    test_dir = os.path.abspath(f"output/test_1min_{base_name}")
    os.makedirs(test_dir, exist_ok=True)
    
    short_video = os.path.join(test_dir, "short_source.mp4")
    
    print("[*] 正在截取前 60 秒视频...")
    trim_cmd = [
        "ffmpeg", "-y", "-i", input_video,
        "-ss", "0", "-t", "60",
        "-c", "copy", short_video
    ]
    subprocess.run(trim_cmd, check=True, capture_output=True)

    # 2. 模拟配音流程
    editor = VideoEditor()
    print("[*] 正在进行 STT 转录与 TTS 配音测试...")
    
    # 修复：CosyVoice 要求参考音频必须小于 30 秒
    # 我们从 short_video 中截取 15 秒作为参考音
    ref_audio_temp = os.path.join(test_dir, "ref_15s.wav")
    print("[*] 正在提取 15s 参考音频 (用于声音克隆)...")
    ref_cmd = [
        "ffmpeg", "-y", "-i", short_video,
        "-ss", "10", "-t", "15", # 从第 10s 开始截取 15s，通常这部分人声比较清晰
        "-vn", "-ac", "1", "-ar", "16000", ref_audio_temp
    ]
    subprocess.run(ref_cmd, check=True, capture_output=True)

    # 获取字幕和转录片段
    srt_path_out, segments, _ = editor.generate_subtitles(short_video, output_dir=test_dir)
    
    # 3. 翻译并生成中文字幕文件 (SRT)
    # 这里模拟针对 Valorant 的中文翻译
    translated_texts = []
    test_srt = os.path.join(test_dir, "test_chinese.srt")
    with open(test_srt, "w", encoding="utf-8") as f:
        for i, (start, end, text) in enumerate(segments):
            # 简单模拟翻译逻辑：英文转中文
            chn_text = f"这是瓦罗兰特精彩时刻的第 {i+1} 段解说。"
            if "kill" in text.lower(): chn_text = "漂亮！完成了一次精彩的击杀！"
            if "win" in text.lower(): chn_text = "恭喜！他们赢下了这一局！"
            
            translated_texts.append(chn_text)
            
            # 写入 SRT 格式
            f.write(f"{i+1}\n")
            f.write(f"{editor.format_time(start)} --> {editor.format_time(end)}\n")
            f.write(f"{chn_text}\n\n")

    # 4. 执行 TTS (使用 15s 的短参考音)
    dubbing_path = editor.generate_dubbing(
        segments=segments,
        translated_texts=translated_texts,
        ref_audio=ref_audio_temp, 
        video_path=short_video,
        output_dir=test_dir
    )
    
    if dubbing_path:
        print(f"[✅] TTS 合成成功: {dubbing_path}")
    else:
        print("[-] TTS 合成失败")

    # 5. 运行封面生成测试
    print("[*] 正在生成美化版封面...")
    covers = generate_covers(short_video, base_name, test_dir)
    if covers:
        print(f"[✅] 封面生成成功: {list(covers.keys())}")

    # 6. 运行 Logo 和片头片尾合成 (现在包含了字幕和配音)
    print("[*] 正在合成最终成品 (Logo + 中文解说 + 中文字幕 + 片头片尾)...")
    process_single_video(
        video_source=short_video, 
        logo_path=logo_path, 
        intro_dur=4.0, 
        outro_dur=5.0,
        srt_path=test_srt,      # 传入中文字幕
        dubbing_path=dubbing_path # 传入中分配音
    )

    print("\n" + "="*60)
    print(f"[🎉] 测试完成！请检查目录: {test_dir}")
    print("="*60)

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python test_1min_pipeline.py <视频路径>")
    else:
        run_1min_test(sys.argv[1])
