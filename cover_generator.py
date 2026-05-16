import os
import subprocess
import argparse
import re
from intro_outro import _find_chinese_font, _ffmpeg_font_arg, _find_avatar
def generate_covers(video_path: str, title: str, output_dir: str) -> dict:
    """
    根据标题和视频内容生成两张吸引人的封面 (4:3 和 3:4)。
    """
    video_path = os.path.abspath(video_path)

    # 增加文件就绪检查 (最多等待 10s)
    print(f"[*] 正在检查视频文件状态: {os.path.basename(video_path)}")
    for _ in range(10):
        if os.path.exists(video_path) and os.path.getsize(video_path) > 1024 * 100: # 至少 100KB
            break
        time.sleep(1)

    if not os.path.exists(video_path):
        print(f"[-] 错误: 找不到视频文件 {video_path}")
        return {}


    os.makedirs(output_dir, exist_ok=True)
    
    # 过滤掉 Windows 文件名不允许的字符
    safe_filename = "".join([c for c in title if c.isalnum() or c in (" ", "-", "_")]).strip()
    cover_4_3 = os.path.join(output_dir, f"{safe_filename}_cover_4_3.jpg")
    cover_3_4 = os.path.join(output_dir, f"{safe_filename}_cover_3_4.jpg")
    
    # 1. 准备字体 (优先使用粗体)
    font = r"C:\Windows\Fonts\msyhbd.ttc" if os.path.exists(r"C:\Windows\Fonts\msyhbd.ttc") else _find_chinese_font()
    font_arg = _ffmpeg_font_arg(font)
    logo = _find_avatar()
    
    # 2. 获取视频时长以确定抽帧时间点 (10% 处)
    duration = 10.0
    try:
        probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_path]
        res = subprocess.run(probe_cmd, capture_output=True, text=True)
        duration = float(res.stdout.strip())
    except: pass
    ss_time = duration * 0.1

    # 3. 构造 FFmpeg 滤镜
    def get_filter(w_ratio, h_ratio, title_text):
        split_pattern = re.compile(r"(.*)(HIGHLIGHTS.*)", re.IGNORECASE)
        match = split_pattern.match(title_text)
        main_t, sub_t = (match.group(1).strip().strip(" -_"), match.group(2).strip()) if match else (title_text, "")

        v_h = 1080
        v_w = v_h * w_ratio / h_ratio

        # 动态缩放计算
        main_fs = max(min((1.6 * v_w) / max(len(main_t), 1), v_h / 8.5), v_h / 25)
        sub_fs = max(min((1.6 * v_w) / max(len(sub_t), 1), main_fs * 0.7), v_h / 35)

        def ffmpeg_escape(t):
            return t.replace("'", "'\\\\''").replace(":", "\\:")

        safe_main = ffmpeg_escape(main_t)
        safe_sub = ffmpeg_escape(sub_t)
        
        # 基础画面处理
        filter_base = (
            f"eq=contrast=1.15:saturation=1.5,"
            f"crop=ih*{w_ratio}/{h_ratio}:ih,"
            f"vignette=angle=0.5"
        )
        
        # 装饰背景逻辑 (修复变量名：overlay 使用 H，crop/drawbox 使用 ih)
        # 我们使用相对比例变量以适应不同滤镜
        box_y_rel = "ih/2-ih/6"    # 用于 drawbox
        box_y_crop = "ih/2-ih/6"   # 用于 crop
        box_y_ovl = "H/2-H/6"      # 用于 overlay
        box_h = "ih/3"             # 用于 drawbox
        box_h_crop = "ih/3"        # 用于 crop
        
        mask_layers = (
            f"split[v_orig][v_blur];"
            f"[v_blur]boxblur=20:5,crop=iw:{box_h_crop}:0:{box_y_crop}[v_blur_strip];"
            f"[v_orig][v_blur_strip]overlay=0:{box_y_ovl}[v_bg_blur];"
            f"[v_bg_blur]drawbox=y={box_y_rel}:h={box_h}:w=iw:color=black@0.7:t=fill[v_box];"
            f"[v_box]drawbox=y={box_y_rel}:h=4:w=iw:color=0xFF4655@0.9:t=fill[v_line1];"
            f"[v_line1]drawbox=y={box_y_rel}+{box_h}-4:h=4:w=iw:color=0x00F5FF@0.9:t=fill"
        )
        
        # 文字绘制
        main_draw = (
            f",drawtext=text='{safe_main}':{font_arg.lstrip(':')}:"
            f"fontsize={int(main_fs)}:fontcolor=0xFFD700:x=(w-text_w)/2:y=h/2-h/12:"
            f"borderw=3:bordercolor=black@0.8:shadowcolor=black@0.9:shadowx=6:shadowy=6"
        )
        sub_draw = ""
        if safe_sub:
            sub_draw = (
                f",drawtext=text='{safe_sub}':{font_arg.lstrip(':')}:"
                f"fontsize={int(sub_fs)}:fontcolor=white:x=(w-text_w)/2:y=h/2+h/15:"
                f"borderw=2:bordercolor=black@0.8:shadowcolor=black@0.9:shadowx=4:shadowy=4"
            )
            
        final_vf = f"{filter_base},{mask_layers}{main_draw}{sub_draw}"
        
        if logo:
            logo_size = v_h // 12
            logo_f = (
                f"[1:v]scale={logo_size}:{logo_size},format=rgba,"
                f"geq=lum='p(X,Y)':a='if(lte(hypot(X-{logo_size}/2,Y-{logo_size}/2),{logo_size}/2),255,0)'[logo_circ];"
                f"[v_res][logo_circ]overlay=50:50"
            )
            return f"[0:v]{final_vf}[v_res];{logo_f}"
        return final_vf

    # 4. 执行生成
    results = {}
    configs = [("4:3", 4, 3, cover_4_3), ("3:4", 3, 4, cover_3_4)]

    print(f"\n{'='*40}")
    print(f"[*] 正在为视频生成封面: {os.path.basename(video_path)}")
    print(f"[*] 标题: {title}")

    for label, w, h, out in configs:
        print(f"[*] 正在生成 {label} 封面...")
        filter_str = get_filter(w, h, title)
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
            print(f"[+] 成功: {out}")
        else:
            print(f"[-] 失败 ({label}): {res.stderr}")

    print(f"{'='*40}\n")
    return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="独立封面生成脚本 (风格 A)")
    parser.add_argument("video", help="输入视频路径")
    parser.add_argument("title", nargs="?", help="封面显示的标题文字 (可选，默认使用文件名)")
    parser.add_argument("--out", help="封面保存目录 (可选，默认输出到项目 output 目录)")

    args = parser.parse_args()
    
    filename = os.path.splitext(os.path.basename(args.video))[0]
    final_title = args.title or filename
    
    if args.out:
        final_out = args.out
    else:
        final_out = os.path.abspath(os.path.join("output", f"valorant_{filename}"))
    
    print(f"[*] 目标输出目录: {final_out}")
    generate_covers(args.video, final_title, final_out)
