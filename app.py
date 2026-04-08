import streamlit as st
import os
import time
import base64
from native_main import run_native_pipeline

st.set_page_config(page_title="VideoCapter 生产面板", layout="wide", page_icon="🎬")

# 确保必要的目录存在
UPLOAD_DIR = "uploads"
OUTPUT_DIR = "output"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

def get_image_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def main():
    st.title("🎬 VideoCapter - 专业级视频翻译配音")
    
    # 初始化预览参数
    if 'logo_preview_url' not in st.session_state:
        st.session_state.logo_preview_url = None

    with st.sidebar:
        st.header("🎨 样式与设置")
        
        # 1. 配音设置
        st.subheader("🎧 配音设置")
        use_dubbing = st.toggle("启用 AI 音色克隆配音", value=True)
        ref_voice_path = None
        if use_dubbing:
            voice_mode = st.radio("参考音色", ["使用默认男声", "上传自定义 WAV"], index=0)
            if voice_mode == "上传自定义 WAV":
                uploaded_voice = st.file_uploader("上传 5-15秒 WAV 音频", type=["wav"])
                if uploaded_voice:
                    ref_voice_path = os.path.join(UPLOAD_DIR, "user_ref_voice.wav")
                    with open(ref_voice_path, "wb") as f:
                        f.write(uploaded_voice.getbuffer())
        
        st.divider()

        # 2. 字幕样式设置
        st.subheader("📝 字幕设置")
        sub_mode = st.selectbox("字幕模式", ["双语", "仅译文", "仅原文", "无"], index=0)
        
        with st.expander("更多字幕样式自定义", expanded=True):
            font_size = st.number_input("字体大小 (FontSize)", value=24, min_value=10, max_value=100)
            margin_v = st.slider("底部边距 (MarginV)", min_value=0, max_value=200, value=50)
            bg_color = st.color_picker("字幕背景颜色", "#000000")
            bg_alpha = st.slider("背景不透明度", 0, 255, 128)
            
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
        
        st.divider()

        # 3. Logo 设置
        st.subheader("🛡️ 品牌 Logo")
        use_logo = st.checkbox("在视频上添加 Logo", value=True)
        logo_path = None
        logo_pos = "top-right"
        logo_margin = (20, 20)
        
        if use_logo:
            logo_option = st.radio("Logo 来源", ["项目默认 (avrtar.jpg)", "上传自定义图片"])
            if logo_option == "项目默认 (avrtar.jpg)":
                if os.path.exists("avrtar.jpg"):
                    logo_path = os.path.abspath("avrtar.jpg")
                    st.session_state.logo_preview_url = f"data:image/jpeg;base64,{get_image_base64(logo_path)}"
            else:
                uploaded_logo = st.file_uploader("上传图片 (JPG/PNG)", type=["jpg", "png", "jpeg"])
                if uploaded_logo:
                    l_path = os.path.join(UPLOAD_DIR, f"custom_logo{os.path.splitext(uploaded_logo.name)[1]}")
                    with open(l_path, "wb") as f:
                        f.write(uploaded_logo.getbuffer())
                    logo_path = os.path.abspath(l_path)
                    st.session_state.logo_preview_url = f"data:image/png;base64,{get_image_base64(logo_path)}"
            
            logo_pos = st.selectbox("显示位置", ["top-right", "top-left", "bottom-right", "bottom-left"], index=0)
            col_m1, col_m2 = st.columns(2)
            with col_m1:
                mx = st.number_input("横向边距 (X)", value=20)
            with col_m2:
                my = st.number_input("纵向边距 (Y)", value=20)
            logo_margin = (mx, my)
        else:
            st.session_state.logo_preview_url = None

        st.divider()

        # 4. 片头片尾设置
        st.subheader("📽️ 片头片尾")
        use_io = st.checkbox("自动生成片头片尾", value=True)
        io_text = None
        intro_dur = 4.0
        outro_dur = 5.0
        if use_io:
            io_text = st.text_input("片头欢迎语 (留空使用默认)", placeholder="例如：欢迎来到我的频道")
            col_dur1, col_dur2 = st.columns(2)
            with col_dur1:
                intro_dur = st.number_input("片头时长(s)", value=4.0, step=0.5)
            with col_dur2:
                outro_dur = st.number_input("片尾时长(s)", value=5.0, step=0.5)

        st.divider()
        st.info("🚀 提示：处理大型视频建议使用具备 GPU 的服务器。")

    # 主界面
    uploaded_file = st.file_uploader("📤 上传待制作视频", type=["mp4", "mkv", "mov", "avi"])

    if uploaded_file:
        video_path = os.path.join(UPLOAD_DIR, uploaded_file.name)
        with open(video_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        
        col1, col2 = st.columns([2, 1])
        with col1:
            st.subheader("📺 实时效果预览")
            
            # 渲染视频
            st.video(video_path)

            # --- 实时预览黑科技：利用负外边距将 HTML 元素“拉”到视频上方 ---
            pos_css = ""
            if logo_pos == "top-right": pos_css = f"top: {logo_margin[1]}px; right: {logo_margin[0]}px;"
            elif logo_pos == "top-left": pos_css = f"top: {logo_margin[1]}px; left: {logo_margin[0]}px;"
            elif logo_pos == "bottom-right": pos_css = f"bottom: {logo_margin[1]}px; right: {logo_margin[0]}px;"
            elif logo_pos == "bottom-left": pos_css = f"bottom: {logo_margin[1]}px; left: {logo_margin[0]}px;"

            logo_html = ""
            if use_logo and st.session_state.logo_preview_url:
                logo_html = f'<img src="{st.session_state.logo_preview_url}" style="position: absolute; {pos_css} width: 45px; height: 45px; border-radius: 50%; object-fit: cover; z-index: 100; border: 1.5px solid white; box-shadow: 0 0 8px rgba(0,0,0,0.5);">'

            sub_text = ""
            if sub_mode == "双语": sub_text = "这是中文翻译示例内容<br><span style='font-size: 0.8em; opacity: 0.8;'>This is the original English content example.</span>"
            elif sub_mode == "仅译文": sub_text = "这是中文翻译示例内容"
            elif sub_mode == "仅原文": sub_text = "This is the original English content example."

            sub_html = ""
            if sub_mode != "无":
                rgba_bg = f"rgba({r_int}, {g_int}, {b_int}, {bg_alpha/255})"
                sub_html = f"""
                <div style="position: absolute; bottom: {margin_v}px; left: 50%; transform: translateX(-50%); 
                            width: 80%; text-align: center; z-index: 101;">
                    <span style="background-color: {rgba_bg}; color: white; padding: 4px 10px; 
                                 font-size: {font_size}px; line-height: 1.2; border-radius: 4px; 
                                 font-family: sans-serif; text-shadow: 1px 1px 2px black; display: inline-block;">
                        {sub_text}
                    </span>
                </div>
                """

            # 核心预览叠加层
            preview_overlay = f"""
            <div style="position: relative; width: 100%; height: 0; margin-top: -57%; pointer-events: none; z-index: 99;">
                <div style="position: relative; width: 100%; padding-bottom: 56.25%; overflow: hidden;">
                    {logo_html}
                    {sub_html}
                </div>
            </div>
            <div style="height: 60px;"></div>
            """
            st.markdown(preview_overlay, unsafe_allow_html=True)
            st.caption("💡 提示：左侧参数调整后，视频画面将实时更新模拟效果。")

        with col2:
            st.subheader("🚀 生产控制")
            if st.button("开始自动化流水线制作", type="primary", use_container_width=True):
                progress_log = st.empty()
                log_content = []
                
                with st.status("🎬 正在执行全链路流水线...", expanded=True) as status:
                    final_video_path = None
                    # 循环获取生成器返回的进度消息
                    for msg in run_native_pipeline(
                        video_path=video_path,
                        ref_voice=ref_voice_path,
                        output_dir=OUTPUT_DIR,
                        logo_path=logo_path,
                        margin_v=margin_v,
                        sub_mode=sub_mode,
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
                            # 处理成功标志
                            parts = msg.replace("SUCCESS: ", "").split(" | ")
                            final_video_path = parts[0]
                            status_msg = parts[1]
                            status.update(label=f"✅ 制作完成！{status_msg}", state="complete")
                        elif msg.startswith("[-] 错误: "):
                            st.error(msg)
                            status.update(label="❌ 处理失败", state="error")
                            break
                        else:
                            # 普通进度消息
                            log_content.append(msg)
                            progress_log.markdown("\n".join([f"- {l}" for l in log_content]))
                    
                    if final_video_path and os.path.exists(final_video_path):
                        st.success("处理成功！预览与下载：")
                        st.video(final_video_path)
                        with open(final_video_path, "rb") as f:
                            st.download_button("📥 下载制作好的视频", f, file_name=f"final_{uploaded_file.name}")

if __name__ == "__main__":
    main()
