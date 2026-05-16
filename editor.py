"""
editor.py  —  VideoCapter 音视频处理模块 (最终生产版)
=========================================
"""

import os
import subprocess
import time
import torch
import numpy as np
import logging
from scipy.io import wavfile
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from pydub import AudioSegment
from pydub.effects import speedup, normalize

# ── 禁用遥测与压制日志 ──────────────────────────────────────────────────
os.environ["PYANNOTE_TELEMETRY"] = "0"
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
# ──────────────────────────────────────────────────────────────────────

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

    def split_text_to_lines(self, text: str, max_width: int = 30) -> list:
        if not text: return []
        if len(text) <= max_width: return [text]
        lines = []
        while len(text) > max_width:
            cut = max_width
            while cut < len(text) and text[cut] not in ' ,.，。!！?？、':
                cut += 1
                if cut > max_width + 10:
                    cut = max_width; break
            if cut < len(text) and text[cut] in ' ,.，。!！?？、':
                cut += 1
            lines.append(text[:cut].strip())
            text = text[cut:].strip()
        if text: lines.append(text)
        return lines

    def split_text(self, text: str, max_width: int = 30) -> str:
        lines = self.split_text_to_lines(text, max_width)
        return "\\N".join(lines)

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
            print(f"[+] 发现 WhisperX 缓存片段: {segments_cache}")
            with open(segments_cache, "r", encoding="utf-8") as f:
                raw_segments = json.load(f)
            return srt_path, raw_segments, []
        print(f"[*] [WhisperX] 正在处理: {os.path.basename(video_path)}")
        model = whisperx.load_model(self._model_size, self.device, compute_type=self.compute_type)
        audio = whisperx.load_audio(video_path)
        result = model.transcribe(audio, batch_size=16)
        try:
            model_a, metadata = whisperx.load_align_model(language_code=result["language"], device=self.device)
            result = whisperx.align(result["segments"], model_a, metadata, audio, self.device, return_char_alignments=False)
        except: pass
        raw_segments = []
        for seg in result["segments"]:
            if "start" in seg and "end" in seg:
                raw_segments.append((seg["start"], seg["end"], seg["text"].strip()))
        with open(segments_cache, "w", encoding="utf-8") as f:
            json.dump(raw_segments, f, ensure_ascii=False, indent=2)
        return srt_path, raw_segments, []

    def separate_audio(self, video_path: str, output_dir: str = "output") -> tuple:
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        video_output_dir = os.path.abspath(os.path.join(output_dir, base_name))
        os.makedirs(video_output_dir, exist_ok=True)
        inst_out = os.path.join(video_output_dir, f"{base_name}_instrumental.wav")
        if os.path.exists(inst_out): return inst_out, ""
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
            elif os.path.exists(f): os.remove(f)
        return inst_path, ""

    def generate_dubbing(self, segments: list, translated_texts: list,
                         ref_audio: str, video_path: str, output_dir: str = "output") -> str:
        import sys
        import torchaudio
        if r"D:\CosyVoice" not in sys.path: sys.path.insert(0, r"D:\CosyVoice")
        if r"D:\CosyVoice\third_party\Matcha-TTS" not in sys.path: sys.path.insert(0, r"D:\CosyVoice\third_party\Matcha-TTS")
        try:
            from cosyvoice.cli.cosyvoice import CosyVoice3
            from cosyvoice.utils.file_utils import load_wav
        except:
            print("[-] CosyVoice3 导入失败")
            return None
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        video_output_dir = os.path.abspath(os.path.join(output_dir, base_name))
        dub_path = os.path.join(video_output_dir, f"{base_name}_full_dub.wav")
        if os.path.exists(dub_path): return dub_path
        voice_seg_dir = os.path.join(video_output_dir, "temp_voice")
        os.makedirs(voice_seg_dir, exist_ok=True)
        if getattr(self, 'tts', None) is None:
            # fp16=True: 启用 GPU 半精度推理，速度提升 ~1.5-2x
            _use_fp16 = self.device == 'cuda'
            self.tts = CosyVoice3(
                r'D:\CosyVoice\pretrained_models\Fun-CosyVoice3-0.5B',
                fp16=_use_fp16
            )
            print(f"[TTS] CosyVoice3 加载完成 (fp16={_use_fp16}, device={self.device})")
        ref_aseg = AudioSegment.from_file(ref_audio).set_frame_rate(16000).set_channels(1)
        ref_wav_16k = os.path.join(video_output_dir, "ref_temp_16k.wav")
        ref_aseg.export(ref_wav_16k, format="wav")
        if not self.stt_model:
            from faster_whisper import WhisperModel
            self.stt_model = WhisperModel("base", device=self.device, compute_type=self.compute_type)
        # 缓存 ref_text，避免对同一参考音频重复转录
        ref_cache_key = ref_wav_16k
        if not hasattr(self, '_ref_text_cache'):
            self._ref_text_cache = {}
        if ref_cache_key not in self._ref_text_cache:
            ref_res, _ = self.stt_model.transcribe(ref_wav_16k)
            self._ref_text_cache[ref_cache_key] = " ".join([s.text for s in ref_res]).strip()
            print(f"[TTS] 参考音频转录: {self._ref_text_cache[ref_cache_key][:60]}")
        ref_text = self._ref_text_cache[ref_cache_key]
        
        import re
        def clean_tts_text(t): return re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9，。！？、 ]', '', t)

        # 极简/极短文本合并策略：彻底杜绝 HiFiGAN 崩溃，同时保证“不漏字”
        seg_list = []
        buff_text = ""
        buff_meta = []
        
        MIN_CHARS = 12 # 至少 12 个字才允许发送合成，绝对安全且语音顺畅
        
        for seg, trans in zip(segments, translated_texts):
            cleaned = clean_tts_text(trans).strip()
            if not cleaned: continue
            
            # 只有当已有内容且间隔 > 1.5秒时才尝试结算，否则尽量往后并
            if buff_text and (seg[0] - buff_meta[-1][1] > 1.5) and len(buff_text) >= MIN_CHARS:
                seg_list.append(((buff_meta[0][0], buff_meta[-1][1]), buff_text.strip('，')))
                buff_text = ""
                buff_meta = []
            
            buff_text += cleaned + "，"
            buff_meta.append(seg)
            
            # 攒够 15 个字或者已经跨越 4 秒，结算
            if len(buff_text.strip('，')) >= 15 or (buff_meta[-1][1] - buff_meta[0][0]) > 4.0:
                seg_list.append(((buff_meta[0][0], buff_meta[-1][1]), buff_text.strip('，')))
                buff_text = ""
                buff_meta = []
                
        # 强制处理剩余尾巴
        if buff_text.strip('，'):
            final_t = buff_text.strip('，')
            if seg_list and len(final_t) < MIN_CHARS:
                # 最后的尾巴如果太短，必须硬塞给上一句，确保不漏字
                pm, pt = seg_list[-1]
                seg_list[-1] = ((pm[0], buff_meta[-1][1]), pt + "，" + final_t)
            elif len(final_t) < MIN_CHARS:
                # 整个视频就这一小句，由于没前任，只能补齐
                seg_list.append(((buff_meta[0][0], buff_meta[-1][1]), final_t + "。这是一段简短的视频配音。"))
            else:
                seg_list.append(((buff_meta[0][0], buff_meta[-1][1]), final_t))

        total_ms = int(segments[-1][1] * 1000) + 1000
        full_dub = AudioSegment.silent(duration=total_ms)
        NATIVE_SR = self.tts.sample_rate

        for s_idx, (seg, text) in enumerate(seg_list):
            temp_wav = os.path.join(voice_seg_dir, f"seg_{s_idx}.wav")
            start_ms  = int(seg[0] * 1000)
            target_dur = max(int((seg[1] - seg[0]) * 1000), 100)
            
            if os.path.exists(temp_wav):
                seg_audio = AudioSegment.from_file(temp_wav)
            else:
                import time as _time
                t0 = _time.time()
                # 自动重试逻辑：如果合成失败，自动添加补丁重试，确保不漏字
                current_try_text = text
                try:
                    for _attempt in range(2): # 两次机会
                        try:
                            with suppress_output():
                                gen = self.tts.inference_zero_shot(current_try_text, ref_text or "参考语音", ref_wav_16k, stream=False)
                                wav_chunks = []
                                for chunk in gen:
                                    wav_chunks.append(chunk['tts_speech'])
                            if not wav_chunks: raise ValueError("Empty Audio")
                            wav = torch.cat(wav_chunks, dim=-1)
                            torchaudio.save(temp_wav, wav.cpu(), NATIVE_SR)
                            seg_audio = AudioSegment.from_file(temp_wav)
                            break # 成功则退出重试
                        except RuntimeError as re:
                            if "Kernel size" in str(re) and _attempt == 0:
                                # 触发长度崩溃，打补丁重试
                                current_try_text = text + "。这是一段简短的补齐语音。"
                                continue
                            raise re
                    
                    elapsed = _time.time() - t0
                    print(f"[TTS] [{s_idx+1}/{len(seg_list)}] 成功: '{text[:20]}...'")
                except Exception as e:
                    print(f"[!] [TTS] 极端错误: '{text}' 跳过 (原因: {str(e)[:40]})")
                    seg_audio = AudioSegment.silent(duration=target_dur)
            # 时长对齐（加速不超过 1.6x）
            g_start_ms  = start_ms
            group_audio = seg_audio
            if len(group_audio) > target_dur and target_dur > 0:
                # Bug Fix 2: 加速上限从 1.3x 提升至 1.6x，优先使用 pyrubberband 高质量拉伸
                ratio = min(len(group_audio) / target_dur, 1.6)
                try:
                    import pyrubberband as pyrb
                    import numpy as np
                    raw = np.array(group_audio.get_array_of_samples()).astype(np.float32) / 32768.0
                    stretched = pyrb.time_stretch(raw, group_audio.frame_rate, 1.0 / ratio)
                    stretched_int = (stretched * 32768).clip(-32768, 32767).astype(np.int16)
                    group_audio = AudioSegment(
                        stretched_int.tobytes(),
                        frame_rate=group_audio.frame_rate,
                        sample_width=2,
                        channels=group_audio.channels
                    )
                except ImportError:
                    # pyrubberband 未安装，fallback 至 pydub speedup
                    group_audio = group_audio.speedup(playback_speed=ratio, chunk_size=150, crossfade=25)
            full_dub = full_dub.overlay(normalize(group_audio).apply_gain(2)[:target_dur], position=g_start_ms)
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
        if os.path.exists(out_path): return out_path
        
        v_height = 1080
        try:
            probe_cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=height", "-of", "csv=p=0", video_path]
            res = subprocess.run(probe_cmd, capture_output=True, text=True)
            v_height = int(res.stdout.strip())
        except: pass

        tmp_files = []
        target_srt = "r_sub.srt" if srt_path and os.path.exists(srt_path) else None
        if target_srt: shutil.copy(srt_path, target_srt); tmp_files.append(target_srt)
        target_logo = f"r_logo{os.path.splitext(logo_path)[1]}" if logo_path and os.path.exists(logo_path) else None
        if target_logo: shutil.copy(logo_path, target_logo); tmp_files.append(target_logo)
        target_dub = "r_dub.wav" if dubbing_path and os.path.exists(dubbing_path) else None
        if target_dub: shutil.copy(dubbing_path, target_dub); tmp_files.append(target_dub)
        target_inst = "r_inst.wav" if inst_path and os.path.exists(inst_path) else None
        if target_inst: shutil.copy(inst_path, target_inst); tmp_files.append(target_inst)

        style_dict = {"FontSize": 14, "BackColour": "&H80000000", "BorderStyle": 4, "Outline": 0}
        if sub_style: style_dict.update(sub_style)
        s = style_dict
        style_str = f"FontSize={s['FontSize']},BorderStyle={s['BorderStyle']},BackColour={s['BackColour']},Outline={s['Outline']},MarginV={margin_v},Alignment=2"

        filter_parts = []
        cur_v = "0:v"
        if target_srt:
            filter_parts.append(f"[{cur_v}]subtitles=filename='{target_srt}':force_style='{style_str}'[v_sub]")
            cur_v = "v_sub"
        if target_logo:
            mx, my = logo_margin
            pos_map = {"top-left": f"x={mx}:y={my}", "top-right": f"x=W-w-{mx}:y={my}", "bottom-left": f"x={mx}:y=H-h-{my}", "bottom-right": f"x=W-w-{mx}:y=H-h-{my}"}
            overlay_coord = pos_map.get(logo_pos, f"x=W-w-{mx}:y={my}")
            l_sz = v_height // 20
            bw = max(2, l_sz // 15)
            # Logo chain
            filter_parts.append(f"[1:0]format=rgba,crop='min(iw,ih)':'min(iw,ih)',scale={l_sz}:{l_sz},pad=w={l_sz+bw*2}:h={l_sz+bw*2}:x={bw}:y={bw}:color=white@0,geq=r='if(lte(hypot(X-W/2,Y-H/2),W/2-{bw}),r(X,Y),255)':g='if(lte(hypot(X-W/2,Y-H/2),W/2-{bw}),g(X,Y),255)':b='if(lte(hypot(X-W/2,Y-H/2),W/2-{bw}),b(X,Y),255)':a='max(0,min(255,255*(W/2-hypot(X-W/2,Y-H/2))))'[logo_circ]")
            filter_parts.append(f"[{cur_v}][logo_circ]overlay={overlay_coord}[v_final]")
            cur_v = "v_final"

        cur_a = "0:a"
        if target_dub:
            d_idx = 2 if target_logo else 1
            if target_inst:
                i_idx = 3 if target_logo else 2
                filter_parts.append(f"[{i_idx}:0][{d_idx}:0]sidechaincompress=threshold=0.1:ratio=5:release=500[bg_d]")
                filter_parts.append(f"[bg_d][{d_idx}:0]amix=inputs=2:duration=first:dropout_transition=2[a_final]")
            else:
                filter_parts.append(f"[{d_idx}:0]anull[a_final]")
            cur_a = "a_final"

        script_file = "r_filter.txt"
        with open(script_file, "w", encoding="utf-8") as f: f.write(";\n".join(filter_parts))
        tmp_files.append(script_file)

        cmd = ["ffmpeg", "-y", "-hide_banner", "-analyzeduration", "50M", "-probesize", "50M", "-i", video_path]
        if target_logo: cmd += ["-i", target_logo]
        if target_dub:  cmd += ["-i", target_dub]
        if target_inst: cmd += ["-i", target_inst]
        
        if filter_parts:
            cmd += ["-filter_complex_script", script_file]
            # 只有当标识符不以 "0:" 开头时，才认为是滤镜产生的标签，需要加 []
            map_v = f"[{cur_v}]" if not cur_v.startswith("0:") else cur_v
            map_a = f"[{cur_a}]" if not cur_a.startswith("0:") else cur_a
        else:
            map_v = "0:v"
            map_a = "0:a"
            
        vcodec = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23"] if self._has_nvenc() else ["-c:v", "libx264", "-preset", "fast", "-crf", "23"]
        cmd += ["-map", map_v, "-map", map_a, "-pix_fmt", "yuv420p"] + vcodec + ["-c:a", "aac", "-b:a", "192k", out_path]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
        self._cleanup(tmp_files)
        if result.returncode != 0:
            with open("FFMPEG_CRASH_REPORT.log", "w", encoding="utf-8") as f: f.write(f"CMD: {' '.join(cmd)}\nERR: {result.stderr}")
            raise Exception(f"FFmpeg 合成失败 ({result.returncode})")
        return out_path

    def _cleanup(self, files):
        for f in files:
            if os.path.exists(f): 
                try: os.remove(f)
                except: pass
