import os
import subprocess
import json
import shutil
import tempfile
import time
import hashlib

# 默认文字配置
DEFAULT_TEXT = {
    # 片头
    "intro_main": "欢迎来到Berlin的频道",
    "intro_hint": "WELCOME TO MY CHANNEL",
    "intro_sub":  "精彩内容 · 即刻开启",
    # 片尾
    "outro_main": "感谢您的观看",
    "outro_sub":  "点赞、关注、收藏就是最大的支持",
    "outro_like": "点赞",
    "outro_star": "投币",
    "outro_bell": "收藏",
    "outro_bye":  "期待与您下次相遇",
}

SEP = "─" * 60

def get_video_info(video_path: str) -> dict:
    """获取视频的详尽规格信息以判断是否需要重编码。"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_streams",
        "-of", "json", video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    info = json.loads(result.stdout)
    
    v_stream = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a_stream = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    
    if not v_stream:
        raise RuntimeError(f"无法获取视频流信息: {video_path}")

    res = {
        "width": int(v_stream["width"]),
        "height": int(v_stream["height"]),
        "pix_fmt": v_stream.get("pix_fmt", ""),
        "codec_name": v_stream.get("codec_name", ""),
    }
    
    # 解析帧率
    fr_parts = v_stream["avg_frame_rate"].split("/")
    if len(fr_parts) == 2 and int(fr_parts[1]) != 0:
        res["fps"] = int(fr_parts[0]) / int(fr_parts[1])
    else:
        res["fps"] = 0.0
    
    # 音频信息
    if a_stream:
        res["sample_rate"] = int(a_stream.get("sample_rate", 0))
        res["channels"] = int(a_stream.get("channels", 0))
        res["audio_codec"] = a_stream.get("codec_name", "")
    else:
        res.update({"sample_rate": 0, "channels": 0, "audio_codec": ""})
        
    return res


def _safe_tmp_dir():
    return tempfile.mkdtemp(prefix="vl_stitch_")


def _vcodec_args():
    """
    智能选择硬件加速编码器。
    优先级: NVIDIA (nvenc) > AMD (amf) > Intel (qsv) > Windows MF > CPU (libx264)
    """
    try:
        # 1. NVIDIA
        res = subprocess.run(["ffmpeg", "-h", "encoder=h264_nvenc"], capture_output=True, text=True)
        if "h264_nvenc" in res.stdout:
            # 与 editor.py 保持一致使用 cq 23
            return ["-c:v", "h264_nvenc", "-preset", "p4", "-tune", "hq", "-cq", "23", "-threads", "0"]
        
        # 2. AMD
        res = subprocess.run(["ffmpeg", "-h", "encoder=h264_amf"], capture_output=True, text=True)
        if "h264_amf" in res.stdout:
            return ["-c:v", "h264_amf", "-quality", "quality", "-rc", "cqp", "-qp_i", "23", "-qp_p", "23"]

        # 3. Intel QuickSync
        res = subprocess.run(["ffmpeg", "-h", "encoder=h264_qsv"], capture_output=True, text=True)
        if "h264_qsv" in res.stdout:
            return ["-c:v", "h264_qsv", "-preset", "balanced", "-global_quality", "23"]

        # 4. Windows Media Foundation (通用 GPU 方案)
        res = subprocess.run(["ffmpeg", "-h", "encoder=h264_mf"], capture_output=True, text=True)
        if "h264_mf" in res.stdout:
            return ["-c:v", "h264_mf", "-quality", "7"]

    except:
        pass
    
    # 5. CPU Fallback
    return ["-c:v", "libx264", "-preset", "fast", "-crf", "23", "-threads", "0"]


def configure_intro_outro(custom_text: dict = None):
    """
    允许用户交互式或通过字典配置文字。
    如果 custom_text 为 None，则打印当前默认值。
    """
    cfg = DEFAULT_TEXT.copy()
    if custom_text:
        cfg.update(custom_text)
        return cfg
    
    print(f"\n{SEP}\n[⚙️] 当前片头片尾文字配置:")
    mapping = {
        "intro_main": "片头主标题",
        "intro_hint": "片头装饰语",
        "intro_sub":  "片头副标题",
        "outro_main": "片尾感谢语",
        "outro_sub":  "片尾副标题",
        "outro_like": "片尾点赞文字",
        "outro_star": "片尾收藏文字",
        "outro_bell": "片尾订阅文字",
        "outro_bye":  "片尾落款",
    }
    for k, label in mapping.items():
        print(f"  [{label:16s}] {cfg[k]}")
    print(SEP)
    return cfg


def _get_params_hash(width, height, fps, duration, font_path, text_dict, prefix=""):
    """为参数生成唯一的哈希值，用于缓存判断。"""
    # 确保 text_dict 是稳定的
    text_json = json.dumps(text_dict, sort_keys=True)
    # 组合所有影响视觉的参数
    data = f"{prefix}_{width}_{height}_{fps}_{duration}_{font_path}_{text_json}"
    return hashlib.md5(data.encode("utf-8")).hexdigest()


def _ffmpeg_font_arg(f):
    if not f:
        return ""
    # 对 Windows 路径进行转义（反斜杠转为斜杠，并处理 : 为 \:）
    p = f.replace("\\", "/").replace(":/", "\\:/")
    return f":fontfile='{p}'"


def _find_avatar() -> str | None:
    """查找默认头像。"""
    if os.path.exists("avrtar.jpg"):
        return os.path.abspath("avrtar.jpg")
    return None


def generate_intro(output_path: str, width: int = 1920, height: int = 1080,
                   fps: float = 30.0, duration: float = 4.0,
                   font_path: str = None, text: dict = None,
                   logo_path: str = None) -> str:
    """
    生成高度个性化、动态流动的片头视频。
    """
    import copy
    cfg = copy.deepcopy(DEFAULT_TEXT)
    if text:
        cfg.update(text)

    welcome_text = cfg["intro_main"]
    channel_hint = cfg["intro_hint"]
    sub_hint     = cfg["intro_sub"]

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # 字体
    font = font_path or _find_chinese_font()
    font_arg = _ffmpeg_font_arg(font)

    # ── 背景：平滑的深色径向渐变 (优化兼容性) ──────────────────────────────
    bg = (
        f"color=c=0x050810:s={width}x{height}:r={fps}:d={duration},format=rgb24[base];"
        f"[base]geq="
        f"r='10+80*exp(-((X-W/2)*(X-W/2)+(Y-H/2)*(Y-H/2))/(W*W/10))':"
        f"g='15+110*exp(-((X-W/2)*(X-W/2)+(Y-H/2)*(Y-H/2))/(W*W/10))':"
        f"b='35+180*exp(-((X-W/2)*(X-W/2)+(Y-H/2)*(Y-H/2))/(W*W/10))'[glow]"
    )

    # ── 滤镜链 ──────────────────────────────────────────────────────────────
    # 文字布局 (简约居中风格)
    hint_y = f"h/2-{height//6}"
    main_y = f"h/2-text_h/2"
    sub_y  = f"h/2+{height//6}"
    
    shadow = ":shadowcolor=black@0.8:shadowx=5:shadowy=5"

    txt_filters = (
        # 装饰性水平线 (上下对称)
        f"[glow]drawbox=x=0:y={height//2-height//10}:w={width}:h=1:"
        f"color=white@0.2:t=fill:enable='gte(t,0.5)'[hline1];"
        f"[hline1]drawbox=x=0:y={height//2+height//10}:w={width}:h=1:"
        f"color=white@0.2:t=fill:enable='gte(t,0.5)'[hline2];"

        # 频道装饰语 (Hint)
        f"[hline2]drawtext=text='{channel_hint}'{font_arg}{shadow}:"
        f"fontsize={height//22}:fontcolor=0x62AEDB@0.8:"
        f"x=(w-text_w)/2:y={hint_y}:"
        f"alpha='if(lt(t,0.3),0,min(1,(t-0.3)/0.6))'[subt];"
        
        # 主标题 (Main)
        f"[subt]drawtext=text='{welcome_text}'{font_arg}{shadow}:"
        f"fontsize={height//10}:fontcolor=white@1:"
        f"x=(w-text_w)/2:y={main_y}:"
        f"alpha='if(lt(t,1.0),0,min(1,(t-1.0)/0.7))'[main_txt];"
        
        # 底部标语 (Sub)
        f"[main_txt]drawtext=text='{sub_hint}'{font_arg}{shadow}:"
        f"fontsize={height//24}:fontcolor=0xFFD700@0.8:"
        f"x=(w-text_w)/2:y={sub_y}:"
        f"alpha='if(lt(t,1.8),0,min(1,(t-1.8)/0.6))'[out_v]"
    )

    filter_complex = f"{bg};{txt_filters};anullsrc=r=48000:cl=stereo[out_a]"

    cmd = (
        ["ffmpeg", "-y",
         "-f", "lavfi",
         "-i", f"color=c=black:s={width}x{height}:r={fps}:d={duration}",
         "-filter_complex", filter_complex,
         "-map", "[out_v]", "-map", "[out_a]",
         "-c:a", "aac", "-b:a", "192k"]
        + _vcodec_args()
        + ["-t", str(duration), "-pix_fmt", "yuv420p", output_path]
    )
    print(f"[片头] 正在生成个性化版本... → {output_path}")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg 片头生成失败:\n{result.stderr[-2000:]}")
    return output_path


def generate_outro(output_path: str, width: int = 1920, height: int = 1080,
                   fps: float = 30.0, duration: float = 5.0,
                   font_path: str = None, text: dict = None,
                   logo_path: str = None) -> str:
    """
    生成个性化、温馨的片尾视频。
    """
    import copy
    cfg = copy.deepcopy(DEFAULT_TEXT)
    if text:
        cfg.update(text)

    outro_text = cfg["outro_main"]
    sub_text1  = cfg["outro_sub"]
    like_txt   = cfg["outro_like"]
    sub_txt    = cfg["outro_star"]
    share_txt  = cfg["outro_bell"]
    bye_txt    = cfg["outro_bye"]

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # 字体与头像
    font = font_path or _find_chinese_font()
    font_arg = _ffmpeg_font_arg(font)
    logo = logo_path or _find_avatar()

    # ── 背景：深紫梦幻渐变 (优化兼容性) ──────────────────────────────────────
    bg = (
        f"color=c=0x100520:s={width}x{height}:r={fps}:d={duration},format=rgb24[base];"
        f"[base]geq="
        f"r='20+120*exp(-((X-W/2)*(X-W/2)+(Y-H/2)*(Y-H/2))/(W*W/8))':"
        f"g='10+60*exp(-((X-W/2)*(X-W/2)+(Y-H/2)*(Y-H/2))/(W*W/8))':"
        f"b='45+170*exp(-((X-W/2)*(X-W/2)+(Y-H/2)*(Y-H/2))/(W*W/8))'[glow]"
    )

    inputs = [
        "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:r={fps}:d={duration}"
    ]
    
    logo_filter = ""
    if logo:
        logo_size = height // 5
        inputs.extend(["-i", logo])
        logo_filter = (
            f"[1:v]scale={logo_size}:{logo_size},format=rgba,"
            f"geq=lum='p(X,Y)':a='if(lt(hypot(X-{logo_size}/2,Y-{logo_size}/2),{logo_size}/2-2),255,0)',"
            f"split=2[lr1][lr2];"
            f"[lr1]pad={logo_size+16}:{logo_size+16}:8:8:0x00000000,"
            f"boxblur=8:1[logo_glow];"
            f"[logo_glow][lr2]overlay=8:8:format=rgb[logo_final];"
        )
        # 将头像叠加到背景 (右上角)
        logo_overlay = (
            f"[logo_final]fade=t=in:st=0.5:d=0.8:alpha=1[logo_faded];"
            f"[glow][logo_faded]overlay=W-w-80:80:format=rgb[bg_with_logo];"
        )
        start_node = "[bg_with_logo]"
    else:
        logo_filter = ""
        logo_overlay = ""
        start_node = "[glow]"

    shadow = ":shadowcolor=black@0.7:shadowx=4:shadowy=4"
    icon_y = height // 2 + height // 8
    icon_spacing = width // 5

    txt_filters = (
        # 感谢主标题 (居中靠上)
        f"{start_node}drawtext=text='{outro_text}'{font_arg}{shadow}:"
        f"fontsize={height//12}:fontcolor=white@1:"
        f"x=(w-text_w)/2:y=(h/2)-{height//4}:"
        f"alpha='if(lt(t,0.3),0,min(1,(t-0.3)/0.7))'[t1];"
        
        # 副标题
        f"[t1]drawtext=text='{sub_text1}'{font_arg}{shadow}:"
        f"fontsize={height//20}:fontcolor=0xFFD700@0.9:"
        f"x=(w-text_w)/2:y=(h/2)-{height//10}:"
        f"alpha='if(lt(t,1.2),0,min(1,(t-1.2)/0.6))'[t2];"
        
        # 互动图标文字布局
        f"[t2]drawtext=text='{like_txt}'{font_arg}{shadow}:"
        f"fontsize={height//18}:fontcolor=0x62AEDB@1:"
        f"x={width//2}-{icon_spacing}-text_w/2:y={icon_y}:"
        f"alpha='if(lt(t,1.8),0,min(1,(t-1.8)/0.5))'[t3];"

        f"[t3]drawtext=text='{sub_txt}'{font_arg}{shadow}:"
        f"fontsize={height//18}:fontcolor=0xF28C38@1:"
        f"x=(w-text_w)/2:y={icon_y}:"
        f"alpha='if(lt(t,2.3),0,min(1,(t-2.3)/0.5))'[t4];"

        f"[t4]drawtext=text='{share_txt}'{font_arg}{shadow}:"
        f"fontsize={height//18}:fontcolor=0xF05050@1:"
        f"x={width//2}+{icon_spacing}-text_w/2:y={icon_y}:"
        f"alpha='if(lt(t,2.8),0,min(1,(t-2.8)/0.5))'[t5];"

        # 底部落款
        f"[t5]drawtext=text='{bye_txt}'{font_arg}{shadow}:"
        f"fontsize={height//24}:fontcolor=white@0.6:"
        f"x=(w-text_w)/2:y=h-{height//10}:"
        f"alpha='if(lt(t,3.8),0,min(1,(t-3.8)/0.6))'[out_v]"
    )

    filter_complex = f"{bg};{logo_filter}{logo_overlay}{txt_filters};anullsrc=r=48000:cl=stereo[out_a]"

    cmd = (
        ["ffmpeg", "-y"]
        + inputs
        + ["-filter_complex", filter_complex,
           "-map", "[out_v]", "-map", "[out_a]",
           "-c:a", "aac", "-b:a", "192k"]
        + _vcodec_args()
        + ["-t", str(duration), "-pix_fmt", "yuv420p", output_path]
    )
    print(f"[片尾] 正在生成... → {output_path}")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg 片尾生成失败:\n{result.stderr[-2000:]}")
    return output_path


def concat_with_intro_outro(main_video: str, output_path: str,
                             intro_duration: float = 4.0,
                             outro_duration: float = 5.0,
                             font_path: str = None,
                             text: dict = None,
                             intro_video: str = None,
                             outro_video: str = None) -> str:
    """
    主入口：在 main_video 首尾自动拼接片头片尾。
    优化：通过参数对齐实现秒级拼接（无需重编码主视频）。
    """
    print(f"\n[🎬] 开始极速添加片头片尾...")

    # 获取主视频规格
    info = get_video_info(main_video)
    w, h, fps = info["width"], info["height"], info["fps"]
    print(f"[*] 主视频规格: {w}x{h} @ {fps:.2f}fps, 编码: {info['codec_name']}")

    # 确定存放目录
    assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "io_videos")
    os.makedirs(assets_dir, exist_ok=True)

    # 1. 处理片头 (生成时强制与主视频参数一致)
    actual_font = font_path or _find_chinese_font()
    cfg = DEFAULT_TEXT.copy()
    if text: cfg.update(text)
    
    if intro_video and os.path.exists(intro_video):
        print(f"[+] 使用指定的片头视频: {intro_video}")
        intro_path = intro_video
    else:
        intro_hash = _get_params_hash(w, h, fps, intro_duration, actual_font, cfg, "intro")
        intro_path = os.path.join(assets_dir, f"intro_{intro_hash}.mp4")
        if not os.path.exists(intro_path):
            generate_intro(intro_path, w, h, fps, intro_duration, font_path, text)
        else:
            print(f"[+] 发现匹配的片头缓存: {intro_path}")

    # 2. 处理片尾
    if outro_video and os.path.exists(outro_video):
        print(f"[+] 使用指定的片尾视频: {outro_video}")
        outro_path = outro_video
    else:
        outro_hash = _get_params_hash(w, h, fps, outro_duration, actual_font, cfg, "outro")
        outro_path = os.path.join(assets_dir, f"outro_{outro_hash}.mp4")
        if not os.path.exists(outro_path):
            generate_outro(outro_path, w, h, fps, outro_duration, font_path, text)
        else:
            print(f"[+] 发现匹配的片尾缓存: {outro_path}")

    tmp_dir = _safe_tmp_dir()
    try:
        # 智能判断：如果主视频已经是 yuv420p 且编码参数匹配，则直接拼接
        # VideoEditor 产出的文件通常符合此标准
        is_compatible = (info["pix_fmt"] == "yuv420p" and 
                         info["audio_codec"] in ["aac", "mp3"])
        
        norm_main = main_video
        if not is_compatible:
            norm_main = os.path.join(tmp_dir, "main_norm.mp4")
            print("[*] 主视频规格不兼容，正在进行必要的一次性转换...")
            _normalize_video(main_video, norm_main, w, h, fps)
        else:
            print("[+] 主视频规格兼容，开启秒级拼接模式 (Skip re-encoding)")

        concat_list = os.path.join(tmp_dir, "concat.txt")
        with open(concat_list, "w", encoding="utf-8") as f:
            for p in [intro_path, norm_main, outro_path]:
                abs_p = os.path.abspath(p).replace("\\", "/")
                f.write(f"file '{abs_p}'\n")

        # 执行秒级拼接
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        print("[*] 正在拼接片头 + 主视频 + 片尾 (Copy Mode)...")
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_list,
            "-c", "copy", # 关键：使用流拷贝实现秒级完成
            output_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        
        # 如果秒级拼接失败，自动降级到重编码拼接
        if res.returncode != 0:
            print("[!] 秒级拼接失败，正在尝试兼容性重编码拼接...")
            cmd_slow = [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", concat_list,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "192k", output_path
            ]
            subprocess.run(cmd_slow, check=True)

        print(f"[✅] 片头片尾添加完成！\n    → {output_path}")
        return output_path

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _normalize_video(src: str, dst: str, width: int, height: int, fps: float):
    """将主视频重新编码到与片头片尾相同规格（统一帧率/分辨率/像素格式）。"""
    vcodec = _vcodec_args()
    # 增加 -filter_threads 0 使用所有 CPU 核心处理滤镜
    cmd = (
        ["ffmpeg", "-y", "-i", src,
         "-vf", f"scale={width}:{height},fps={fps}",
         "-filter_threads", "0",
         "-pix_fmt", "yuv420p"]
        + vcodec
        + ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", dst]
    )
    subprocess.run(cmd, check=True, capture_output=True)


def _find_chinese_font() -> str | None:
    """在 Windows 系统字体中查找支持中文的字体。"""
    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",    # 微软雅黑
        r"C:\Windows\Fonts\msyhbd.ttc",  # 微软雅黑 Bold
        r"C:\Windows\Fonts\simhei.ttf",  # 黑体
        r"C:\Windows\Fonts\simsun.ttc",  # 宋体
        r"C:\Windows\Fonts\STZHONGS.TTF",# 华文中宋
    ]
    for f in candidates:
        if os.path.exists(f):
            return f
    return None


# ── 命令行独立调用 ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="为视频自动添加片头片尾或独立生成")
    parser.add_argument("input",  nargs="?", help="输入视频路径（若指定 --gen_only 则不需要）")
    parser.add_argument("output", help="输出视频路径")
    parser.add_argument("--gen_only", action="store_true", help="仅生成片头/片尾视频文件，不进行拼接")
    parser.add_argument("--type", choices=["intro", "outro"], default="intro", help="gen_only 模式下的类型")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--duration", type=float, default=4.0)
    parser.add_argument("--font",  default=None, help="自定义字体文件路径")
    
    args = parser.parse_args()

    if args.gen_only:
        if args.type == "intro":
            generate_intro(args.output, args.width, args.height, args.fps, args.duration, args.font)
        else:
            generate_outro(args.output, args.width, args.height, args.fps, args.duration, args.font)
        print(f"\n🎉 独立视频已生成: {args.output}")
    else:
        if not args.input:
            parser.error("非 gen_only 模式必须提供 input 参数")
        result = concat_with_intro_outro(
            main_video=args.input,
            output_path=args.output,
            intro_duration=args.duration if args.type == "intro" else 4.0,
            font_path=args.font,
        )
        print(f"\n🎉 完成！最终视频: {result}")
