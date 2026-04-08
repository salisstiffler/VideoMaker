"""
editor.py  —  VideoCapter 音视频处理模块 (最终生产版)
=========================================
"""

import os
import subprocess
import time
import torch
import numpy as np
from scipy.io import wavfile
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from pydub import AudioSegment
from pydub.effects import speedup, normalize

# ── 核心依赖检测 ──────────────────────────────────────────────────────
try:
    import whisperx
    HAS_WHISPERX = True
except: HAS_WHISPERX = False

try:
    from audio_separator.separator import Separator
    HAS_SEPARATOR = True
except: HAS_SEPARATOR = False

try:
    from f5_tts.api import F5TTS
    HAS_F5TTS = True
except: HAS_F5TTS = False

@contextmanager
def suppress_output():
    with open(os.devnull, 'w') as fnull:
        with redirect_stdout(fnull), redirect_stderr(fnull):
            yield

class VideoEditor:
    def __init__(self, model_size: str = "base", beam_size: int = 2):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.compute_type = "float16" if self.device == "cuda" else "int8"
        self.separator = None
        self.tts = None
        self.stt_model = None
        self._model_size = model_size
        print(f"[VideoEditor] 初始化 (device={self.device})")

    def format_time(self, seconds: float) -> str:
        msec = int(seconds * 1000)
        h, m = divmod(msec // 1000, 3600)
        m, s = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d},{msec % 1000:03d}"

    def _has_nvenc(self) -> bool:
        try:
            res = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True)
            return "h264_nvenc" in res.stdout
        except: return False

    def generate_subtitles(self, video_path: str, output_dir: str = "output") -> tuple:
        import json
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        video_output_dir = os.path.abspath(os.path.join(output_dir, base_name))
        os.makedirs(video_output_dir, exist_ok=True)
        
        srt_path = os.path.join(video_output_dir, f"{base_name}_bilingual.srt")
        segments_cache = os.path.join(video_output_dir, f"{base_name}_segments.json")
        
        if os.path.exists(segments_cache):
            print(f"[+] 发现 WhisperX 缓存片段，跳过转录: {segments_cache}")
            with open(segments_cache, "r", encoding="utf-8") as f:
                raw_segments = json.load(f)
            return srt_path, raw_segments, []

        print(f"[*] [WhisperX] 正在处理: {os.path.basename(video_path)}")
        model = whisperx.load_model(self._model_size, self.device, compute_type=self.compute_type)
        audio = whisperx.load_audio(video_path)
        result = model.transcribe(audio, batch_size=16)
        model_a, metadata = whisperx.load_align_model(language_code=result["language"], device=self.device)
        result = whisperx.align(result["segments"], model_a, metadata, audio, self.device, return_char_alignments=False)
        raw_segments = []
        for seg in result["segments"]:
            if "start" in seg and "end" in seg:
                raw_segments.append((seg["start"], seg["end"], seg["text"].strip()))
        
        # 缓存片段
        with open(segments_cache, "w", encoding="utf-8") as f:
            json.dump(raw_segments, f, ensure_ascii=False, indent=2)
            
        return srt_path, raw_segments, []

    def separate_audio(self, video_path: str, output_dir: str = "output") -> tuple:
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        video_output_dir = os.path.abspath(os.path.join(output_dir, base_name))
        os.makedirs(video_output_dir, exist_ok=True)
        inst_out = os.path.join(video_output_dir, f"{base_name}_instrumental.wav")
        if os.path.exists(inst_out): return inst_out, ""
        print(f"[*] [UVR] 正在分离背景音...")
        if self.separator is None:
            self.separator = Separator()
            self.separator.load_model("UVR-MDX-NET-Inst_HQ_3.onnx")
        files = self.separator.separate(video_path)
        inst_path = ""
        for f in files:
            if "Instrumental" in f:
                import shutil
                shutil.move(f, inst_out)
                inst_path = inst_out
            else:
                if os.path.exists(f): os.remove(f)
        return inst_path, ""

    def generate_dubbing(self, segments: list, translated_texts: list,
                         ref_audio: str, video_path: str, output_dir: str = "output") -> str:
        if not HAS_F5TTS: return None
        import torchaudio
        from f5_tts.infer.utils_infer import infer_batch_process
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        video_output_dir = os.path.abspath(os.path.join(output_dir, base_name))
        dub_path = os.path.join(video_output_dir, f"{base_name}_full_dub.wav")
        voice_seg_dir = os.path.join(video_output_dir, "temp_voice")
        os.makedirs(voice_seg_dir, exist_ok=True)
        if os.path.exists(dub_path): return dub_path
        if self.tts is None:
            print(f"[*] 正在加载 F5-TTS 生产级模型...")
            self.tts = F5TTS(device=self.device)
        ref_aseg = AudioSegment.from_file(ref_audio).set_frame_rate(24000).set_channels(1)
        ref_wav_24k = os.path.join(video_output_dir, "ref_temp_24k.wav")
        ref_aseg.export(ref_wav_24k, format="wav")
        if not self.stt_model:
            from faster_whisper import WhisperModel
            self.stt_model = WhisperModel("base", device=self.device, compute_type=self.compute_type)
        ref_res, _ = self.stt_model.transcribe(ref_wav_24k)
        ref_text = " ".join([s.text for s in ref_res]).strip()
        ref_audio_tensor, ref_sr = torchaudio.load(ref_wav_24k)
        groups = []
        cur_group = {"texts": [], "meta": []}
        for i, (seg, trans) in enumerate(zip(segments, translated_texts)):
            if not trans.strip(): continue
            if cur_group["meta"] and (seg[0] - cur_group["meta"][-1][1] > 0.5):
                groups.append(cur_group); cur_group = {"texts": [], "meta": []}
            cur_group["texts"].append(trans); cur_group["meta"].append(seg)
        if cur_group["texts"]: groups.append(cur_group)
        total_ms = int(segments[-1][1] * 1000) + 1000
        full_dub = AudioSegment.silent(duration=total_ms)
        print(f"[*] [F5-TTS] 正在合成 {len(groups)} 个连贯语段...")
        for g_idx, group in enumerate(groups):
            full_text = "。".join(group["texts"])
            temp_g_wav = os.path.join(voice_seg_dir, f"group_{g_idx}.wav")
            with suppress_output():
                gen = infer_batch_process((ref_audio_tensor, ref_sr), ref_text, [full_text], 
                                          self.tts.ema_model, self.tts.vocoder, self.tts.mel_spec_type, device=self.device)
                wav, sr, _ = next(gen)
            wav_np = wav.cpu().numpy().flatten() if isinstance(wav, torch.Tensor) else wav.flatten()
            wavfile.write(temp_g_wav, sr, wav_np)
            group_audio = AudioSegment.from_wav(temp_g_wav)
            g_start_ms = int(group["meta"][0][0] * 1000)
            g_end_ms = int(group["meta"][-1][1] * 1000)
            target_dur = g_end_ms - g_start_ms
            if len(group_audio) > target_dur:
                ratio = len(group_audio) / target_dur
                if ratio > 1.4: ratio = 1.4
                group_audio = speedup(group_audio, playback_speed=ratio, chunk_size=150, crossfade=25)
            group_audio = normalize(group_audio).apply_gain(3)
            full_dub = full_dub.overlay(group_audio[:target_dur], position=g_start_ms)
        full_dub.export(dub_path, format="wav")
        return dub_path

    def burn_subtitles(self, video_path: str, srt_path: str,
                       margin_v: int = 35, logo_path: str = None,
                       logo_pos: str = "top-right", logo_margin: tuple = (20, 20),
                       dubbing_path: str = None, inst_path: str = None,
                       output_dir: str = "output",
                       sub_style: dict = None) -> str:
        import shutil
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        video_output_dir = os.path.abspath(os.path.join(output_dir, base_name))
        os.makedirs(video_output_dir, exist_ok=True)
        out_path = os.path.join(video_output_dir, f"{base_name}_final.mp4")
        
        if os.path.exists(out_path):
            print(f"[+] 发现已合成的视频，跳过渲染: {out_path}")
            return out_path
        
        # 1. 资源就位 (全部拷贝到根目录以防路径问题)
        tmp_files = []
        target_srt = "r_sub.srt" if srt_path and os.path.exists(srt_path) else None
        if target_srt: shutil.copy(srt_path, target_srt); tmp_files.append(target_srt)

        target_logo = f"r_logo{os.path.splitext(logo_path)[1]}" if logo_path and os.path.exists(logo_path) else None
        if target_logo: shutil.copy(logo_path, target_logo); tmp_files.append(target_logo)

        target_dub = "r_dub.wav" if dubbing_path and os.path.exists(dubbing_path) else None
        if target_dub: shutil.copy(dubbing_path, target_dub); tmp_files.append(target_dub)
            
        target_inst = "r_inst.wav" if inst_path and os.path.exists(inst_path) else None
        if target_inst: shutil.copy(inst_path, target_inst); tmp_files.append(target_inst)

        # 2. 构造样式参数 (更严谨的引号包裹)
        style_dict = {"FontSize": 24, "BackColour": "&H80000000", "BorderStyle": 4, "Outline": 0}
        if sub_style: style_dict.update(sub_style)
        s = style_dict
        # 核心：将所有样式放在单引号内
        style_str = f"FontSize={s['FontSize']},BorderStyle={s['BorderStyle']},BackColour={s['BackColour']},Outline={s['Outline']},MarginV={margin_v},Alignment=2"

        # 3. 构造滤镜
        filter_parts = []
        cur_v = "[0:v]"
        
        # 字幕：注意 filename 的路径在脚本文件中不需要额外转义冒号
        if target_srt:
            filter_parts.append(f"{cur_v}subtitles=filename='{target_srt}':force_style='{style_str}'[v_sub]")
            cur_v = "[v_sub]"

        # Logo：圆形裁剪 + 白色边框 (工业级稳健方案)
        if target_logo:
            mx, my = logo_margin
            pos_map = {
                "top-left": f"{mx}:{my}",
                "top-right": f"W-w-{mx}:{my}",
                "bottom-left": f"{mx}:H-h-{my}",
                "bottom-right": f"W-w-{mx}:H-h-{my}"
            }
            overlay_coord = pos_map.get(logo_pos, f"W-w-{mx}:{my}")
            
            # 滤镜链：
            # 1. 裁剪为正方形 -> 2. 缩放 -> 3. 创建圆形遮罩 -> 4. 应用遮罩 -> 5. 加上白色圆形外框
            # 我们通过覆盖两层来实现边框：底层是稍微大一点的白色圆，顶层是 Logo 圆
            logo_size = "ih/8"
            filter_parts.append(
                f"[1:v]crop='min(iw,ih)':'min(iw,ih)',scale={logo_size}:{logo_size},format=rgba,"
                f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lte(pow(X-W/2,2)+pow(Y-H/2,2),pow(W/2,2)),255,0)'[logo_circ]"
            )
            # 创建一个纯白色的圆形背景（比 Logo 大 4 像素作为边框）
            filter_parts.append(
                f"color=c=white:s=100x100,scale={logo_size}+4:{logo_size}+4,format=rgba,"
                f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lte(pow(X-W/2,2)+pow(Y-H/2,2),pow(W/2,2)),255,0)'[white_bg]"
            )
            # 叠加：先贴白圆，再贴 Logo
            filter_parts.append(f"{cur_v}[white_bg]overlay={overlay_coord}-2:2[v_with_bg]")
            filter_parts.append(f"[v_with_bg][logo_circ]overlay={overlay_coord}[v_final]")
            cur_v = "[v_final]"

        # 音频
        cur_a = "[0:a]"
        if target_dub:
            dub_idx = 2 if target_logo else 1
            if target_inst:
                inst_idx = 3 if target_logo else 2
                filter_parts.append(f"[{inst_idx}:a][{dub_idx}:a]sidechaincompress=threshold=0.1:ratio=5:release=500[bg_d]")
                filter_parts.append(f"[bg_d][{dub_idx}:a]amix=inputs=2:duration=first:dropout_transition=2[a_final]")
            else:
                filter_parts.append(f"[{dub_idx}:a]copy[a_final]")
            cur_a = "[a_final]"

        # 4. 写入脚本
        script_file = "r_filter.txt"
        with open(script_file, "w", encoding="utf-8") as f:
            f.write(";\n".join(filter_parts))
        tmp_files.append(script_file)

        # 5. 命令组装
        inputs = ["-i", video_path]
        if target_logo: inputs += ["-i", target_logo]
        if target_dub:  inputs += ["-i", target_dub]
        if target_inst: inputs += ["-i", target_inst]

        # 解决 EINVAL: 检测并只映射滤镜图内部实际存在的输出流标签，不要映射初始占位符 [0:v] / [0:a]
        map_v = cur_v if cur_v != "[0:v]" else "0:v"
        map_a = cur_a if cur_a != "[0:a]" else "0:a"

        # 显卡加速配置
        vcodec = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23"] if self._has_nvenc() else ["-c:v", "libx264", "-preset", "fast", "-crf", "23"]
        
        cmd = ["ffmpeg", "-y", "-hide_banner"] + inputs
        
        if filter_parts:
            cmd += ["-filter_complex_script", script_file]
            
        cmd += [
            "-map", map_v, "-map", map_a,
            "-pix_fmt", "yuv420p" # 强制输出标准像素格式
        ] + vcodec + ["-c:a", "aac", "-b:a", "192k", out_path]

        print(f"[*] 执行最终命令:\n{' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
        
        # 6. 异常处理与降级
        if result.returncode != 0:
            print(f"[-] FFmpeg 严重错误日志:\n{result.stderr}")
            with open("FFMPEG_CRASH_REPORT.log", "w", encoding="utf-8") as f_err:
                f_err.write(f"COMMAND:\n{' '.join(cmd)}\n\nERROR:\n{result.stderr}")
            
            if "nvenc" in result.stderr.lower():
                print("[!] 硬件编码失败，尝试 CPU 重新合成...")
                cmd_cpu = [c.replace("h264_nvenc", "libx264").replace("p4", "medium").replace("-cq", "-crf") for c in cmd]
                result = subprocess.run(cmd_cpu, capture_output=True, text=True, encoding="utf-8", errors="ignore")
                if result.returncode == 0: 
                    self._cleanup(tmp_files)
                    return out_path

            self._cleanup(tmp_files)
            raise Exception(f"FFmpeg 合成失败 (Exit {result.returncode})，错误报告已生成至 FFMPEG_CRASH_REPORT.log")

        self._cleanup(tmp_files)
        return out_path

    def _cleanup(self, files):
        for f in files:
            if os.path.exists(f): 
                try: os.remove(f)
                except: pass

    def generate_covers(self, image_path: str, output_dir: str) -> dict:
        return {}
