import os
import sys
import argparse
import time
from editor import VideoEditor
from translator_timing import batch_translate_with_context
from cover_generator import generate_covers

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
    yield "⚙️ 正在初始化 AI 引擎 (Faster-Whisper / Fun-CosyVoice3)..."
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
    _, original_segments, _ = editor.generate_subtitles(video_path, output_dir=output_dir)
    if not original_segments:
        yield f"[-] 错误: 未能在视频中检测到有效对白"
        return
        
    # 直接使用原始转录片段进行翻译，确保语义连贯性
    segments = original_segments
    yield f"✅ 成功提取对白时间轴 (共 {len(segments)} 句)"

    # 4. 翻译 (只有明确需要译文时才调用大模型)
    import json
    translated_cache_path = os.path.join(work_dir, f"{base_name}_translated_texts.json")
    translated_texts = []
    
    must_translate = sub_mode in ["双语", "仅译文"]
    
    if must_translate or use_dubbing:
        if os.path.exists(translated_cache_path):
            yield "♻️ 发现已翻译的缓存记录，正在加载..."
            with open(translated_cache_path, "r", encoding="utf-8") as f:
                translated_texts = json.load(f)
            if len(translated_texts) != len(segments):
                yield "⚠️ 缓存与当前片段不匹配，重新开始翻译..."
                translated_texts = []
        
        if not translated_texts:
            if must_translate:
                # 用户确实需要翻译字幕或意译配音
                yield f"㊙️ 步骤 3/5: 正在进行大模型意译/润色 ({sub_mode})..."
                translated_texts = batch_translate_with_context(segments, chars_per_sec=3.3)
                with open(translated_cache_path, "w", encoding="utf-8") as f:
                    json.dump(translated_texts, f, ensure_ascii=False, indent=2)
                yield "✅ 翻译完成并存入缓存"
            elif use_dubbing:
                # 仅开启配音但字幕选了“无”或“仅原文”：直接用原话，跳过大模型
                yield "⏭️ 字幕模式设为“仅原文/无”，配音将直接使用原始识别文本 (跳过大模型翻译)"
                translated_texts = [seg[2] for seg in segments]
        else:
            yield "✅ 内容已从缓存恢复"
    else:
        yield "⏭️ 跳过翻译/改写步骤"

    # 5. 生成 SRT (带长句拆分优化)
    final_srt_path = None
    if sub_mode != "无":
        yield "📄 正在生成字幕文件 (进行长句自动拆分)..."
        final_srt_path = os.path.join(work_dir, f"{base_name}_burn.srt")
        with open(final_srt_path, "w", encoding="utf-8") as f:
            srt_idx = 1
            for seg, trans in zip(segments, translated_texts if translated_texts else [None]*len(segments)):
                start, end, original = seg
                duration = end - start
                
                # 获取拆分后的行列表 (把长句切得更细碎，单行中文控制在18字左右，原文如果也是中文则30字左右)
                trans_lines = editor.split_text_to_lines(trans, 18) if trans else []
                orig_lines = editor.split_text_to_lines(original, 30)
                
                # 按照“最多1行翻译，最多2行原文”的要求分配时间，完全阻断被超长原文长段霸屏的情况
                num_trans_chunks = len(trans_lines)
                num_orig_chunks = (len(orig_lines) + 1) // 2
                num_parts = max(1, num_trans_chunks, num_orig_chunks)
                
                if num_parts <= 1:
                    # 单个片段：直接写入
                    f.write(f"{srt_idx}\n{editor.format_time(start)} --> {editor.format_time(end)}\n")
                    w_trans = trans_lines[0] if trans_lines else ""
                    w_orig = "\\N".join(orig_lines) if orig_lines else ""
                    if sub_mode == "双语": f.write(f"{w_trans}\n{w_orig}\n\n")
                    elif sub_mode == "仅译文": f.write(f"{w_trans}\n\n")
                    elif sub_mode == "仅原文": f.write(f"{w_orig}\n\n")
                    srt_idx += 1
                else:
                    # 多个片段：均分时间，使得每一块时间只显示指定数量的文本
                    part_dur = duration / num_parts
                    for p in range(num_parts):
                        p_start = start + p * part_dur
                        p_end = start + (p + 1) * part_dur
                        
                        # 翻译行（按比例停留）：
                        t_start_idx = int(len(trans_lines) * (p / num_parts))
                        t_end_idx = int(len(trans_lines) * ((p + 1) / num_parts))
                        p_trans = "\\N".join(trans_lines[t_start_idx : max(t_start_idx + 1, t_end_idx)]) if trans_lines else ""
                        
                        # 原文行（按比例停留）：
                        o_start_idx = int(len(orig_lines) * (p / num_parts))
                        o_end_idx = int(len(orig_lines) * ((p + 1) / num_parts))
                        p_orig = "\\N".join(orig_lines[o_start_idx : max(o_start_idx + 1, o_end_idx)]) if orig_lines else ""
                        
                        f.write(f"{srt_idx}\n{editor.format_time(p_start)} --> {editor.format_time(p_end)}\n")
                        if sub_mode == "双语": f.write(f"{p_trans}\n{p_orig}\n\n")
                        elif sub_mode == "仅译文": f.write(f"{p_trans}\n\n")
                        elif sub_mode == "仅原文": f.write(f"{p_orig}\n\n")
                        srt_idx += 1

    # 6. Fun-CosyVoice3 配音
    dub_path = None
    if use_dubbing:
        yield "🎧 步骤 4/5: 正在进行 Fun-CosyVoice3 (0.5B) 高保真零样本音色克隆配音..."
        dub_path = editor.generate_dubbing(segments, translated_texts, os.path.abspath(ref_voice), video_path, output_dir=output_dir)
        yield f"✅ 配音合成完成"
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

    # 9. 生成封面
    best_cover = None
    try:
        yield "🖼️ 步骤 7/7: 正在生成封面图..."
        cover_dir = os.path.dirname(final_video)
        covers = generate_covers(final_video, base_name, cover_dir)
        best_cover = covers.get("3:4") or covers.get("4:3")
        yield "✅ 封面生成完成"
    except Exception as e:
        yield f"[!] 警告: 封面生成失败: {e}"

    total_dur = time.time() - start_time
    # 最终确保 yield 消息在所有操作之后
    yield f"SUCCESS: {final_video} | {best_cover if best_cover else ''} | 耗时: {total_dur/60:.1f} 分钟"

if __name__ == "__main__":
    # CLI 模式依然兼容打印
    def cli_run():
        parser = argparse.ArgumentParser()
        parser.add_argument("video")
        parser.add_argument("--no-upload", action="store_false", dest="upload", default=True, help="制作完成后不自动上传")
        args = parser.parse_args()
        
        final_video = None
        best_cover = None
        
        for msg in run_native_pipeline(args.video):
            print(msg)
            if msg.startswith("SUCCESS: "):
                parts = msg.replace("SUCCESS: ", "").split(" | ")
                final_video = parts[0]
                best_cover = parts[1] if parts[1] else None
        
        if args.upload and final_video:
            from upload_utils import auto_upload
            title = os.path.splitext(os.path.basename(final_video))[0].replace("_full_production", "")
            print(f"[*] 正在触发后台自动上传: {title}")
            auto_upload(final_video, title, best_cover)
    cli_run()
