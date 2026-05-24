import streamlit as st
import os
import time
import base64
from native_main import run_native_pipeline

st.set_page_config(page_title="VideoCapter Pro", layout="wide", page_icon="🎬")

# 确保必要的目录存在
UPLOAD_DIR = "uploads"
OUTPUT_DIR = "output"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

def get_image_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def main():
    st.markdown("""
        <style>
        .main {
            background-color: #f8f9fa;
        }
        .stButton>button {
            border-radius: 10px;
            font-weight: 600;
            transition: all 0.3s ease;
        }
        .stButton>button:hover {
            transform: scale(1.02);
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }
        .sidebar .sidebar-content {
            background-color: #ffffff;
        }
        div[data-testid="stExpander"] {
            border: none;
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);
            border-radius: 10px;
            margin-bottom: 1rem;
        }
        </style>
    """, unsafe_allow_html=True)

    st.title("🎬 VideoCapter Pro")
    st.caption("🚀 下一代 AI 视频翻译与配音工作流")
    
    # 初始化预览参数
    if 'logo_preview_url' not in st.session_state:
        st.session_state.logo_preview_url = None

    with st.sidebar:
        st.header("🎨 项目定制")
        
        # 1. 配音设置
        with st.expander("🎧 语音克隆引擎", expanded=True):
            use_dubbing = st.toggle("启用 AI 语音合成", value=True)
            ref_voice_path = None
            if use_dubbing:
                voice_mode = st.radio("选择参考音色", ["内置男声 (默认)", "上传自定义 WAV"], index=0)
                if voice_mode == "上传自定义 WAV":
                    uploaded_voice = st.file_uploader("上传 5-15秒音频", type=["wav"])
                    if uploaded_voice:
                        ref_voice_path = os.path.join(UPLOAD_DIR, "user_ref_voice.wav")
                        with open(ref_voice_path, "wb") as f:
                            f.write(uploaded_voice.getbuffer())
        
        # 2. 字幕样式设置
        with st.expander("📝 字幕视觉样式", expanded=True):
            sub_mode = st.selectbox("显示模式", ["双语对比", "仅显示译文", "仅显示原文", "无字幕"], index=0)
            mode_map = {"双语对比": "双语", "仅显示译文": "仅译文", "仅显示原文": "仅原文", "无字幕": "无"}
            final_sub_mode = mode_map[sub_mode]
            
            font_size = st.number_input("字体大小", value=24, min_value=10, max_value=100)
            margin_v = st.slider("底部垂直间距", min_value=0, max_value=200, value=50)
            bg_color = st.color_picker("背景衬底颜色", "#000000")
            bg_alpha = st.slider("衬底不透明度", 0, 255, 128)
            
            # 颜色计算
            alpha_hex = format(255 - bg_alpha, '02X')
            r_int, g_int, b_int = int(bg_color[1:3], 16), int(bg_color[3:5], 16), int(bg_color[5:7], 16)
            ass_bg_color = f"&H{alpha_hex}{format(b_int, '02X')}{format(g_int, '02X')}{format(r_int, '02X')}"
            
            sub_style = {
                "FontSize": font_size,
                "BackColour": ass_bg_color,
                "BorderStyle": 4 if bg_alpha > 0 else 3,
                "Outline": 0 if bg_alpha > 50 else 1
            }

        # 3. Logo 设置
        with st.expander("🛡️ 品牌水印 (Logo)", expanded=False):
            use_logo = st.checkbox("添加图片水印", value=True)
            logo_path = None
            logo_pos = "top-right"
            logo_margin = (20, 20)
            
            if use_logo:
                logo_option = st.radio("来源", ["默认头像", "上传本地图片"])
                if logo_option == "默认头像":
                    if os.path.exists("avrtar.jpg"):
                        logo_path = os.path.abspath("avrtar.jpg")
                        st.session_state.logo_preview_url = f"data:image/jpeg;base64,{get_image_base64(logo_path)}"
                else:
                    uploaded_logo = st.file_uploader("上传图片", type=["jpg", "png", "jpeg"])
                    if uploaded_logo:
                        l_path = os.path.join(UPLOAD_DIR, f"custom_logo{os.path.splitext(uploaded_logo.name)[1]}")
                        with open(l_path, "wb") as f:
                            f.write(uploaded_logo.getbuffer())
                        logo_path = os.path.abspath(l_path)
                        st.session_state.logo_preview_url = f"data:image/png;base64,{get_image_base64(logo_path)}"
                
                logo_pos = st.selectbox("位置", ["top-right", "top-left", "bottom-right", "bottom-left"], index=0)
                col_m1, col_m2 = st.columns(2)
                with col_m1: mx = st.number_input("横向距离", value=20)
                with col_m2: my = st.number_input("纵向距离", value=20)
                logo_margin = (mx, my)
            else:
                st.session_state.logo_preview_url = None

        # 4. 片头片尾设置
        with st.expander("📽️ 片头片尾 (Snappy)", expanded=False):
            use_io = st.checkbox("开启自动合成", value=True)
            io_text = None
            intro_dur = 3.0
            outro_dur = 4.0
            if use_io:
                io_text = st.text_input("个性化欢迎语", placeholder="欢迎来到我的频道")
                col_dur1, col_dur2 = st.columns(2)
                with col_dur1: intro_dur = st.number_input("片头秒数", value=3.0, step=0.5)
                with col_dur2: outro_dur = st.number_input("片尾秒数", value=4.0, step=0.5)

        # 5. 发布设置
        with st.expander("🚀 一键发布设置", expanded=True):
            enable_upload = st.toggle("制作完成后自动上传", value=True)
            upload_platforms = []
            if enable_upload:
                col_up1, col_up2 = st.columns(2)
                with col_up1: 
                    if st.checkbox("Bilibili", value=True): upload_platforms.append("bilibili")
                with col_up2: 
                    if st.checkbox("抖音 (Douyin)", value=True): upload_platforms.append("douyin")
                
                if not upload_platforms:
                    st.warning("⚠️ 请至少选择一个发布平台")

        st.divider()
        st.info("💡 提示：所有参数调整均可在右侧进行实时模拟预览。")

    # 主界面
    uploaded_file = st.file_uploader("📤 选择待处理的视频文件", type=["mp4", "mkv", "mov", "avi"])

    if uploaded_file:
        video_path = os.path.join(UPLOAD_DIR, uploaded_file.name)
        with open(video_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        
        col1, col2 = st.columns([1.6, 1])
        with col1:
            st.subheader("📺 实时效果预览")
            st.video(video_path)

            # 实时预览叠加层
            pos_css = ""
            if logo_pos == "top-right": pos_css = f"top: {logo_margin[1]}px; right: {logo_margin[0]}px;"
            elif logo_pos == "top-left": pos_css = f"top: {logo_margin[1]}px; left: {logo_margin[0]}px;"
            elif logo_pos == "bottom-right": pos_css = f"bottom: {logo_margin[1]}px; right: {logo_margin[0]}px;"
            elif logo_pos == "bottom-left": pos_css = f"bottom: {logo_margin[1]}px; left: {logo_margin[0]}px;"

            logo_html = ""
            if use_logo and st.session_state.logo_preview_url:
                logo_html = f'<img src="{st.session_state.logo_preview_url}" style="position: absolute; {pos_css} width: 54px; height: 54px; border-radius: 50%; object-fit: cover; z-index: 100; border: 1.5px solid white; box-shadow: 0 0 8px rgba(0,0,0,0.5);">'

            sub_text = ""
            if final_sub_mode == "双语": sub_text = "这是中文翻译示例内容<br><span style='font-size: 0.8em; opacity: 0.8;'>Original content example.</span>"
            elif final_sub_mode == "仅译文": sub_text = "这是中文翻译示例内容"
            elif final_sub_mode == "仅原文": sub_text = "Original content example."

            sub_html = ""
            if final_sub_mode != "无":
                rgba_bg = f"rgba({r_int}, {g_int}, {b_int}, {bg_alpha/255})"
                sub_html = (
                    f'<div style="position: absolute; bottom: {margin_v}px; left: 50%; transform: translateX(-50%); '
                    f'width: 80%; text-align: center; z-index: 101;">'
                    f'<span style="background-color: {rgba_bg}; color: white; padding: 4px 10px; '
                    f'font-size: {font_size}px; line-height: 1.2; border-radius: 4px; '
                    f'font-family: sans-serif; text-shadow: 1px 1px 2px black; display: inline-block;">'
                    f'{sub_text}</span></div>'
                )

            preview_overlay = (
                f'<div style="position: relative; width: 100%; height: 0; margin-top: -57%; pointer-events: none; z-index: 99;">'
                f'<div style="position: relative; width: 100%; padding-bottom: 56.25%; overflow: hidden;">'
                f'{logo_html}{sub_html}'
                f'</div></div><div style="height: 60px;"></div>'
            )
            st.markdown(preview_overlay, unsafe_allow_html=True)

        with col2:
            st.subheader("🚀 生产执行")
            st.write("点击下方按钮开始全自动流水线处理。")
            
            if st.button("🎬 开始自动化生产", type="primary", use_container_width=True):
                progress_log = st.empty()
                log_content = []
                
                with st.status("💎 正在全速执行 AI 任务流水线...", expanded=True) as status:
                    final_video_path = None
                    final_cover_path = None
                    for msg in run_native_pipeline(
                        video_path=video_path,
                        ref_voice=ref_voice_path,
                        output_dir=OUTPUT_DIR,
                        logo_path=logo_path,
                        margin_v=margin_v,
                        sub_mode=final_sub_mode,
                        use_dubbing=use_dubbing,
                        logo_pos=logo_pos,
                        logo_margin=logo_margin,
                        sub_style=sub_style,
                        use_io=use_io,
                        io_text=io_text,
                        intro_dur=intro_dur,
                        outro_dur=outro_dur
                    ):
                        if msg.startswith("SUCCESS: "):
                            parts = msg.replace("SUCCESS: ", "").split(" | ")
                            final_video_path = parts[0]
                            final_cover_path = parts[1] if parts[1] else None
                            status.update(label=f"✅ 生产成功！{parts[2]}", state="complete")
                        elif msg.startswith("[-] 错误: "):
                            st.error(msg)
                            status.update(label="❌ 处理失败", state="error")
                            break
                        else:
                            log_content.append(msg)
                            progress_log.markdown("\n".join([f"- {l}" for l in log_content]))
                    
                    if final_video_path and os.path.exists(final_video_path):
                        st.balloons()
                        st.success("✨ 处理完成！您可以立即预览并下载。")
                        st.video(final_video_path)
                        
                        # 触发后台上传
                        if enable_upload and upload_platforms:
                            try:
                                from upload_utils import auto_upload
                                title = os.path.splitext(os.path.basename(final_video_path))[0].replace("_full_production", "")
                                auto_upload(final_video_path, title, final_cover_path, platforms=upload_platforms)
                                st.info(f"🚀 已在后台启动上传任务至: {', '.join(upload_platforms)}")
                                st.caption("您可以在 logs/ 目录下查看上传进度日志。")
                            except Exception as e:
                                st.warning(f"⚠️ 启动自动上传失败: {e}")

                        with open(final_video_path, "rb") as f:
                            st.download_button("📥 立即下载成品视频", f, file_name=f"capter_{uploaded_file.name}", use_container_width=True)

if __name__ == "__main__":
    main()
