import os
from editor import VideoEditor
from intro_outro import concat_with_intro_outro

# 配置路径（根据你出错的日志自动填充）
base_name = "Paper Rex vs Nongshim RedForce - HIGHLIGHTS _ VCT 2026_ Pacific Stage 1"
video_path = rf"D:\videoCapter\uploads\{base_name}.mp4"
output_dir = "output"
work_dir = os.path.join(output_dir, base_name)

srt_path = os.path.join(work_dir, f"{base_name}_burn.srt")
dubbing_path = os.path.join(work_dir, f"{base_name}_full_dub.wav")
inst_path = os.path.join(work_dir, f"{base_name}_instrumental.wav")
logo_path = "avrtar.jpg"

print(f"🚀 正在使用已有的中间文件恢复合成: {base_name}")
editor = VideoEditor()

try:
    final_video = editor.burn_subtitles(
        video_path=video_path,
        srt_path=srt_path if os.path.exists(srt_path) else None,
        margin_v=20,
        logo_path=logo_path if os.path.exists(logo_path) else None,
        logo_pos="top-right",
        logo_margin=(20, 20),
        dubbing_path=dubbing_path if os.path.exists(dubbing_path) else None,
        inst_path=inst_path if os.path.exists(inst_path) else None,
        output_dir=output_dir
    )
    print(f"✅ 合成成功: {final_video}")
    
    # 片头片尾拼接
    final_out_with_io = os.path.join(work_dir, f"{base_name}_full_production.mp4")
    concat_with_intro_outro(
        main_video=final_video,
        output_path=final_out_with_io,
        intro_duration=4.0,
        outro_duration=5.0,
        font_path=None,
        text=None
    )
    print(f"✅ 片头片尾拼接成功: {final_out_with_io}")

except Exception as e:
    print(f"[-] 恢复合成失败: {e}")
