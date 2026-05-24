import os
import subprocess
import argparse
import re
import time
import tempfile
from intro_outro import _find_chinese_font, _ffmpeg_font_arg, _find_avatar

def generate_covers(video_path: str, title: str, output_dir: str) -> dict:
    """
    根据标题和视频内容生成两张吸引人的封面 (4:3 和 3:4)。
    针对 Valorant 风格进行了视觉强化。
    """
    video_path = os.path.abspath(video_path)

    # 增加文件就绪检查
    print(f"[*] 正在检查视频文件状态: {os.path.basename(video_path)}")
    for _ in range(10):
        if os.path.exists(video_path) and os.path.getsize(video_path) > 1024 * 100:
            break
        time.sleep(1)

    if not os.path.exists(video_path):
        print(f"[-] 错误: 找不到视频文件 {video_path}")
        return {}

    os.makedirs(output_dir, exist_ok=True)
    
    # 准备字体
    font = r"C:\Windows\Fonts\msyhbd.ttc" if os.path.exists(r"C:\Windows\Fonts\msyhbd.ttc") else _find_chinese_font()
    font_arg = _ffmpeg_font_arg(font)
    logo = _find_avatar()
    
    # 获取视频时长
    duration = 10.0
    try:
        probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_path]
        res = subprocess.run(probe_cmd, capture_output=True, text=True)
        duration = float(res.stdout.strip())
    except: pass
    ss_time = duration * 0.15 # 选在 15% 处，通常是精彩镜头开始

    # 处理标题拆分
    # 规则：如果有 HIGHLIGHTS 或 vs，尝试拆分为主标题和副标题
    split_pattern = re.compile(r"(.*?)(HIGHLIGHTS|VS|[\-\|]).*", re.IGNORECASE)
    match = split_pattern.match(title)
    if match:
        main_t = match.group(1).strip()
        sub_t = title[len(main_t):].strip().strip("-| ")
    else:
        main_t = title
        sub_t = ""

    # 为了安全处理中文字符，我们将文字写入临时文件
    def create_text_file(content):
        fd, path = tempfile.mkstemp(suffix=".txt")
        # FFmpeg drawtext textfile needs to be UTF-8
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    main_txt_file = create_text_file(main_t)
    sub_txt_file = create_text_file(sub_t) if sub_t else None

    def get_filter(w_ratio, h_ratio):
        v_h = 1080
        v_w = int(v_h * w_ratio / h_ratio)

        # 字体大小策略
        # 目标：主标题占据宽度的 85% 左右，但不超过一定高度
        char_count = len(main_t)
        if char_count == 0: char_count = 1
        
        # 基础大小：根据宽度动态计算，确保不溢出
        # 假设每个字符平均占据 fs * 0.8 的宽度 (对于中文和英文大写的平均值)
        main_fs = int((v_w * 0.85) / char_count)
        
        # 限制最大高度 (防止单字符太大)
        max_h = v_h // 6
        if main_fs > max_h:
            main_fs = max_h
            
        # 限制最小大小
        if main_fs < 60:
            main_fs = 60
        
        sub_fs = int(main_fs * 0.5)

        # 转义路径
        def ffmpeg_path_esc(p):
            return p.replace("\\", "/").replace(":", "\\:")

        main_file_esc = ffmpeg_path_esc(main_txt_file)
        sub_file_esc = ffmpeg_path_esc(sub_txt_file) if sub_txt_file else None

        # 核心滤镜组
        # 1. 基础增强：提高对比度、锐度和色彩鲜艳度
        base_color = "unsharp=5:5:1.0:5:5:0.0,eq=contrast=1.2:saturation=1.6:brightness=0.02"
        
        # 2. 构图与裁剪
        crop_v = f"crop=ih*{w_ratio}/{h_ratio}:ih"
        
        # 3. 视觉装饰
        box_h = int(main_fs * 1.8)
        if sub_t: box_h += int(sub_fs * 1.2)
        box_y = (v_h - box_h) // 2
        
        # 装饰性滤镜：更强烈的半透明黑底 + 霓虹边框
        decor = (
            f"drawbox=y={box_y}:h={box_h}:w=iw:color=black@0.7:t=fill,"   # 更深的底座
            f"drawbox=y={box_y}:h=6:w=iw:color=yellow@0.9:t=fill,"        # 顶部明黄边框
            f"drawbox=y={box_y+box_h-6}:h=6:w=iw:color=yellow@0.9:t=fill"  # 底部明黄边框
        )

        # 4. 文字绘制 (醒目配色：明黄 + 黑边)
        # 主标题：明黄 (#FFFF00) + 粗黑边 + 强阴影
        main_draw = (
            f"drawtext=textfile='{main_file_esc}':{font_arg.lstrip(':')}:"
            f"fontsize={main_fs}:fontcolor=0xFFFF00:x=(w-text_w)/2:y={box_y}+({box_h}-text_h)/2-({sub_fs/2 if sub_t else 0}):"
            f"borderw=4:bordercolor=black:shadowcolor=black@0.8:shadowx=8:shadowy=8"
        )
        
        sub_draw = ""
        if sub_file_esc:
            sub_draw = (
                f",drawtext=textfile='{sub_file_esc}':{font_arg.lstrip(':')}:"
                f"fontsize={sub_fs}:fontcolor=white:x=(w-text_w)/2:y={box_y}+{box_h}-text_h-20:"
                f"borderw=2:bordercolor=black@0.8"
            )

        final_vf = f"{base_color},{crop_v},{decor},{main_draw}{sub_draw},vignette=angle=0.2"
        
        if logo:
            logo_size = v_h // 10
            logo_f = (
                f"[1:v]scale={logo_size}:{logo_size},format=rgba,"
                f"geq=lum='p(X,Y)':a='if(lte(hypot(X-{logo_size}/2,Y-{logo_size}/2),{logo_size}/2),255,0)'[logo_circ];"
                f"[v_res][logo_circ]overlay=W-w-50:50"
            )
            return f"[0:v]{final_vf}[v_res];{logo_f}"
        return final_vf

    # 执行生成
    results = {}
    configs = [("4:3", 4, 3, os.path.join(output_dir, "cover_4_3.jpg")), 
               ("3:4", 3, 4, os.path.join(output_dir, "cover_3_4.jpg"))]

    print(f"\n{'='*40}")
    print(f"[*] 正在生成强化版封面: {title}")

    for label, w, h, out in configs:
        filter_str = get_filter(w, h)
        cmd = ["ffmpeg", "-y", "-ss", str(ss_time), "-i", video_path]
        if logo: cmd += ["-i", logo]
        
        if logo:
            cmd += ["-filter_complex", filter_str]
        else:
            cmd += ["-vf", filter_str]
            
        cmd += ["-frames:v", "1", "-q:v", "2", out]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
        if res.returncode == 0:
            results[label] = out
            print(f"[+] 成功: {label} -> {out}")
        else:
            print(f"[-] 失败 ({label}): {res.stderr[-500:]}")

    # 清理临时文件
    for f in [main_txt_file, sub_txt_file]:
        if f and os.path.exists(f):
            try: os.remove(f)
            except: pass

    print(f"{'='*40}\n")
    return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="强化版封面生成脚本")
    parser.add_argument("video", help="输入视频路径")
    parser.add_argument("title", nargs="?", help="标题")
    parser.add_argument("--out", help="输出目录")

    args = parser.parse_args()
    filename = os.path.splitext(os.path.basename(args.video))[0]
    final_title = args.title or filename
    final_out = args.out or os.path.join("output", f"cover_{int(time.time())}")
    
    generate_covers(args.video, final_title, final_out)
