import os
import sys
import argparse
import time
from editor import VideoEditor
from translator_timing import batch_translate_with_context

# ── 片头片尾配置 ──────────────────────────────────────────────────────────────
INTRO_OUTRO_CONFIG = {
    "enable": True,           
    "intro_duration": 4.0,   
    "outro_duration": 5.0,   
    "font_path": None,        
    "text": None,             
}
# ──────────────────────────────────────────────────────────────

DEFAULT_LOGO = "avrtar.jpg"
DEFAULT_MARGIN = 20

def find_default_voice():
    p = "default_voice.wav"
    if os.path.exists(p):
        return p
    return None

def run_native_pipeline(video_path, ref_voice=None, output_dir="output", logo_path=None, margin_v=20, sub_mode="双语", use_dubbing=True, logo_pos="top-right", logo_margin=(20, 20), sub_style=None, use_io=True, io_text=None, intro_dur=4.0, outro_dur=5.0):
    """
    全链路原生翻译配音生产流程 (进度汇报版)
    使用 yield 返回进度消息
    """
    if use_dubbing and (not ref_voice or not os.path.exists(ref_voice)):
        ref_voice = find_default_voice()
        yield f"[*] 使用默认音色: {ref_voice}"
    
    start_time = time.time()
    video_path = os.path.abspath(video_path)
    if not os.path.exists(video_path):
        yield f"[-] 错误: 找不到视频文件: {video_path}"
        return

    base_name = os.path.splitext(os.path.basename(video_path))[0]
    work_dir = os.path.join(os.path.abspath(output_dir), base_name)
    os.makedirs(work_dir, exist_ok=True)

    yield f"🚀 开始处理项目: {base_name}"

    # 1. 初始化
    yield "⚙️ 正在初始化 AI 引擎 (Faster-Whisper / F5-TTS)..."
    editor = VideoEditor(model_size="base")

    # 2. UVR 背景音分离
    inst_path = None
    if use_dubbing:
        yield "🎙️ 步骤 1/5: 正在进行 UVR 人声与背景音乐分离 (MDX-Net)..."
        inst_path, _ = editor.separate_audio(video_path, output_dir=output_dir)
        yield "✅ 背景音分离完成"
    else:
        yield "⏭️ 跳过背景音分离 (保留原声模式)"

    # 3. 语音转录
    yield "📝 步骤 2/5: 正在提取视频语音并生成时间戳 (WhisperX)..."
    _, segments, _ = editor.generate_subtitles(video_path, output_dir=output_dir)
    if not segments:
        yield "[-] 错误: 未能在视频中检测到有效对白"
        return
    yield f"✅ 成功提取 {len(segments)} 句对白"

    # 4. 翻译
    translated_texts = []
    if sub_mode in ["双语", "仅译文"] or use_dubbing:
        yield f"㊙️ 步骤 3/5: 正在进行上下文关联翻译 ({sub_mode})..."
        translated_texts = batch_translate_with_context(segments, chars_per_sec=3.8)
        yield "✅ 翻译完成"
    else:
        yield "⏭️ 跳过翻译步骤 (仅需原文)"

    # 5. 生成 SRT
    final_srt_path = None
    if sub_mode != "无":
        yield "📄 正在生成字幕文件..."
        final_srt_path = os.path.join(work_dir, f"{base_name}_burn.srt")
        with open(final_srt_path, "w", encoding="utf-8") as f:
            for i, (seg, trans) in enumerate(zip(segments, translated_texts if translated_texts else [None]*len(segments)), start=1):
                start, end, original = seg
                f.write(f"{i}\n{editor.format_time(start)} --> {editor.format_time(end)}\n")
                if sub_mode == "双语":
                    f.write(f"{trans}\n{original}\n\n")
                elif sub_mode == "仅译文":
                    f.write(f"{trans}\n\n")
                elif sub_mode == "仅原文":
                    f.write(f"{original}\n\n")

    # 6. F5-TTS 配音
    dub_path = None
    if use_dubbing:
        yield "🎧 步骤 4/5: 正在进行 F5-TTS 极速音色克隆配音 (分组流水线模式)..."
        dub_path = editor.generate_dubbing(segments, translated_texts, os.path.abspath(ref_voice), video_path, output_dir=output_dir)
        yield "✅ 配音合成完成"
    else:
        yield "⏭️ 跳过 AI 配音"

    # 7. 合成主视频
    yield "🎬 步骤 5/5: 正在进行 FFmpeg 侧链压制与混音合成..."
    final_video = editor.burn_subtitles(
        video_path=video_path,
        srt_path=final_srt_path,
        margin_v=margin_v,
        logo_path=logo_path,
        logo_pos=logo_pos,
        logo_margin=logo_margin,
        dubbing_path=dub_path,
        inst_path=inst_path,
        output_dir=output_dir,
        sub_style=sub_style
    )

    # 8. 片头片尾拼接
    if final_video and os.path.exists(final_video) and use_io:
        yield "📽️ 步骤 6/6: 正在合成自定义片头与片尾 (预计需要 1-2 分钟)..."
        try:
            from intro_outro import concat_with_intro_outro
            final_out_with_io = os.path.join(work_dir, f"{base_name}_full_production.mp4")
            
            # 关键：捕获返回的新路径
            result_video = concat_with_intro_outro(
                main_video=final_video,
                output_path=final_out_with_io,
                intro_duration=intro_dur,
                outro_duration=outro_dur,
                font_path=INTRO_OUTRO_CONFIG["font_path"],
                text=io_text if io_text else INTRO_OUTRO_CONFIG["text"],
            )
            
            if result_video and os.path.exists(result_video):
                final_video = result_video
                yield "✅ 片头片尾拼接成功"
            else:
                yield "[!] 警告: 片头片尾生成的文件不存在，使用原合成视频"
        except Exception as e:
            yield f"[!] 警告: 片头片尾拼接出错: {e}"

    total_dur = time.time() - start_time
    # 最终确保 yield 消息在所有操作之后
    yield f"SUCCESS: {final_video} | 耗时: {total_dur/60:.1f} 分钟"

if __name__ == "__main__":
    # CLI 模式依然兼容打印
    def cli_run():
        parser = argparse.ArgumentParser()
        parser.add_argument("video")
        args = parser.parse_args()
        for msg in run_native_pipeline(args.video):
            print(msg)
    cli_run()
