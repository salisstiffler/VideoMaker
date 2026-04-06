import os
import subprocess
import argparse

def has_nvenc():
    """检查系统是否支持 NVIDIA 硬件加速"""
    try:
        res = subprocess.run(["ffmpeg", "-encoders"], capture_output=True, text=True)
        return "h264_nvenc" in res.stdout
    except:
        return False

def add_logo(video_path, logo_path, output_path=None):
    if not os.path.exists(video_path):
        print(f"[-] 找不到视频文件: {video_path}")
        return
    if not os.path.exists(logo_path):
        print(f"[-] 找不到 Logo 文件: {logo_path}")
        return

    if not output_path:
        base, ext = os.path.splitext(video_path)
        output_path = f"{base}_with_logo{ext}"

    # 检测 GPU 支持
    use_gpu = has_nvenc()
    if use_gpu:
        print("[+] 检测到 GPU 硬件加速 (NVENC)，将使用 GPU 运行。")
        vcodec = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23"]
    else:
        print("[*] 未检测到 GPU 加速，使用 CPU (libx264) 运行。")
        vcodec = ["-c:v", "libx264", "-preset", "fast", "-crf", "23"]

    print(f"[*] 正在为视频添加 Logo...")
    print(f"[*] 输入视频: {video_path}")
    print(f"[*] Logo 文件: {logo_path}")
    print(f"[*] 输出视频: {output_path}")

    # 这里的 filter 逻辑参考了 editor.py 中的圆形 Logo 叠加逻辑
    filter_str = (
        f"[1:v]crop='min(iw,ih)':'min(iw,ih)',scale='ih/8':'ih/8',format=rgba,"
        f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lte(pow(X-W/2,2)+pow(Y-H/2,2),pow(W/2,2)),255,0)'[lready];"
        f"[0:v][lready]overlay=W-w-20:20[v_final]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", logo_path,
        "-filter_complex", filter_str,
        "-map", "[v_final]",
        "-map", "0:a",
    ] + vcodec + [
        "-c:a", "copy",
        output_path
    ]

    try:
        subprocess.run(cmd, check=True)
        print(f"\n[+] 处理完成！")
        print(f"[+] 最终视频: {os.path.abspath(output_path)}")
    except subprocess.CalledProcessError as e:
        print(f"[-] FFmpeg 执行失败: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="快速为现有视频添加圆形 Logo")
    parser.add_argument("video", help="视频文件路径")
    parser.add_argument("--logo", default="avrtar.jpg", help="Logo 文件路径 (默认 avrtar.jpg)")
    parser.add_argument("--output", help="输出文件路径 (可选)")

    args = parser.parse_args()
    add_logo(args.video, args.logo, args.output)
