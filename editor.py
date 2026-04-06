"""
editor.py  —  VideoCapter 音视频处理模块 (最终生产版)
=========================================
核心逻辑：
  - 借鉴 VideoLingo：引入“分组生成”技术，解决 F5-TTS 吞字和不自然问题。
  - WhisperX 精准对齐。
  - 侧链压缩自动避让背景音。
  - 支持专业级圆形 Logo 叠加。
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
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        video_output_dir = os.path.abspath(os.path.join(output_dir, base_name))
        os.makedirs(video_output_dir, exist_ok=True)
        srt_path = os.path.join(video_output_dir, f"{base_name}_bilingual.srt")
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
                       dubbing_path: str = None, inst_path: str = None,
                       output_dir: str = "output") -> str:
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        video_output_dir = os.path.abspath(os.path.join(output_dir, base_name))
        out_path = os.path.join(video_output_dir, f"{base_name}_final.mp4")
        style = f"FontSize=20,BorderStyle=3,Outline=1,OutlineColour=&H80000000,MarginV={margin_v},Alignment=2"
        vcodec = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23"] if self._has_nvenc() else ["-c:v", "libx264", "-preset", "fast", "-crf", "23"]

        # 构建输入列表并记录各路流的索引
        inputs = ["-i", video_path]
        vid_idx = 0
        aud_idx = 0
        
        logo_idx = -1
        if logo_path and os.path.exists(logo_path):
            logo_idx = len(inputs) // 2
            inputs += ["-i", logo_path]
            
        dub_idx = -1
        if dubbing_path and os.path.exists(dubbing_path):
            dub_idx = len(inputs) // 2
            inputs += ["-i", dubbing_path]
            
        inst_idx = -1
        if inst_path and os.path.exists(inst_path):
            inst_idx = len(inputs) // 2
            inputs += ["-i", inst_path]

        filter_parts = []
        cur_v = f"[{vid_idx}:v]"
        cur_a = f"[{vid_idx}:a]"

        # 1. 字幕
        if srt_path:
            rel_srt = os.path.relpath(srt_path).replace("\\", "/")
            filter_parts.append(f"{cur_v}subtitles='{rel_srt}':force_style='{style}'[v_sub]")
            cur_v = "[v_sub]"

        # 2. Logo
        if logo_idx != -1:
            filter_parts.append(f"[{logo_idx}:v]crop='min(iw,ih)':'min(iw,ih)',scale='ih/8':'ih/8',format=rgba,"
                               f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lte(pow(X-W/2,2)+pow(Y-H/2,2),pow(W/2,2)),255,0)'[lready];"
                               f"{cur_v}[lready]overlay=W-w-20:20[v_final]")
            cur_v = "[v_final]"

        # 3. 音频
        if dub_idx != -1:
            if inst_idx != -1:
                # 侧链混音: 背景音在配音出现时降低
                filter_parts.append(f"[{inst_idx}:a][{dub_idx}:a]sidechaincompress=threshold=0.1:ratio=5:release=500[bg_d]")
                filter_parts.append(f"[bg_d][{dub_idx}:a]amix=inputs=2:duration=first:dropout_transition=2[a_final]")
            else:
                filter_parts.append(f"[{dub_idx}:a]copy[a_final]")
            cur_a = "[a_final]"

        cmd = ["ffmpeg", "-y"] + inputs
        if filter_parts:
            cmd += ["-filter_complex", ";".join(filter_parts), "-map", cur_v, "-map", cur_a]
        else:
            cmd += ["-map", "0:v", "-map", "0:a", "-c:v", "copy", "-c:a", "copy"]
            
        cmd += vcodec + ["-c:a", "aac", "-b:a", "192k", out_path]
        subprocess.run(cmd, check=True, capture_output=True)
        return out_path

    def generate_covers(self, image_path: str, output_dir: str) -> dict:
        return {}
