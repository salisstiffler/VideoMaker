from faster_whisper import WhisperModel
import os
import subprocess
import time
import torch
import numpy as np
from scipy.io import wavfile
import translators as ts
from contextlib import contextmanager, redirect_stdout, redirect_stderr
import torchaudio
from pydub import AudioSegment
from concurrent.futures import ThreadPoolExecutor, as_completed

def monkey_patch_torchaudio():
    """Monkey-patch torchaudio.load to use pydub as a fallback to avoid libtorchcodec error."""
    original_load = torchaudio.load
    def patched_load(filepath, *args, **kwargs):
        try:
            audio = AudioSegment.from_file(filepath)
            
            # F5-TTS expects 24000Hz mono. Force it here.
            audio = audio.set_frame_rate(24000).set_channels(1)
            
            samples = np.array(audio.get_array_of_samples()).astype(np.float32)
            # Normalize to [-1, 1]
            if audio.sample_width == 2:
                samples /= 32768.0
            elif audio.sample_width == 4:
                samples /= 2147483648.0
            
            # Reshape to [1, samples] (since we forced mono)
            samples = samples.reshape((1, -1))
            
            return torch.from_numpy(samples), 24000
        except Exception as e:
            # If pydub fails or file doesn't exist, fallback but log briefly if debug
            return original_load(filepath, *args, **kwargs)
    
    torchaudio.load = patched_load

monkey_patch_torchaudio()

@contextmanager
def suppress_output():
    """Context manager to suppress stdout and stderr."""
    with open(os.devnull, 'w') as fnull:
        with redirect_stdout(fnull), redirect_stderr(fnull):
            yield

try:
    from pydub import AudioSegment
    HAS_PYDUB = True
except ImportError:
    HAS_PYDUB = False

try:
    from audio_separator.separator import Separator
    HAS_SEPARATOR = True
except ImportError:
    HAS_SEPARATOR = False

try:
    from f5_tts.api import F5TTS
    from f5_tts.infer.utils_infer import infer_process
    HAS_F5TTS = True
except (ImportError, OSError):
    HAS_F5TTS = False


class VideoEditor:
    HAS_PYDUB = HAS_PYDUB
    HAS_SEPARATOR = HAS_SEPARATOR
    HAS_F5TTS = HAS_F5TTS

    def __init__(self, model_size: str = "base", beam_size: int = 2, max_workers: int = 8):
        """
        Args:
            model_size: Whisper model size ('tiny','base','small','medium','large-v3')
            beam_size:  Lower = faster (1~2), Higher = more accurate (5). Default 2.
            max_workers: Thread pool size for concurrent translation.
        """
        self.beam_size = beam_size
        self.max_workers = max_workers
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.compute_type = "float16" if self.device == "cuda" else "int8"

        print(f"[*] Initializing Faster-Whisper ({model_size}) on {self.device.upper()} "
              f"[beam={beam_size}, workers={max_workers}]...")
        try:
            self.model = WhisperModel(model_size, device=self.device, compute_type=self.compute_type)
            print(f"[+] Model loaded.")
        except Exception as e:
            print(f"[!] CUDA load failed: {e}. Falling back to CPU...")
            self.device = "cpu"
            self.compute_type = "int8"
            self.model = WhisperModel(model_size, device="cpu", compute_type="int8")

        # Initialize TTS and Separator as None (lazy load to save VRAM)
        self.tts = None
        self.separator = None

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def format_time(self, seconds: float) -> str:
        msec = int(seconds * 1000)
        h, m = divmod(msec // 1000, 3600)
        m, s = divmod(m, 60)
        ms = msec % 1000
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def _parse_srt_time(self, time_str: str) -> float:
        """Helper to parse '00:00:00,000' to seconds."""
        h, m, s_ms = time_str.split(":")
        s, ms = s_ms.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

    def _translate_one(self, text: str, target_lang: str,
                       engines=('google', 'bing', 'alibaba')) -> str:
        """Translate a single segment. Called from thread pool."""
        if not text.strip():
            return ""
        for engine in engines:
            try:
                result = ts.translate_text(text, translator=engine, to_language=target_lang)
                if result:
                    return result
            except Exception:
                time.sleep(0.3)
        return text  # fallback: return original

    def _translate_batch(self, texts: list[str], target_lang: str) -> list[str]:
        """
        Translate all texts concurrently using a thread pool.
        Returns results in the same order as 'texts'.
        """
        results = [""] * len(texts)
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_to_idx = {
                pool.submit(self._translate_one, text, target_lang): i
                for i, text in enumerate(texts)
            }
            done = 0
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception:
                    results[idx] = texts[idx]
                done += 1
                if done % 10 == 0 or done == len(texts):
                    print(f"    [翻译] {done}/{len(texts)} 完成")
        return results

    # ------------------------------------------------------------------ #
    # Subtitle generation: stream transcription → batch translate
    # ------------------------------------------------------------------ #

    def generate_subtitles(self, video_path: str, output_dir: str = "output") -> str:
        # Create a video-specific subdirectory
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        video_output_dir = os.path.abspath(os.path.join(output_dir, base_name))
        os.makedirs(video_output_dir, exist_ok=True)
        
        srt_path = os.path.join(video_output_dir, f"{base_name}_bilingual.srt")

        # --- Step 0: Check for existing SRT (Cache) ---
        if os.path.exists(srt_path):
            print(f"[+] 发现现有字幕文件，正在加载: {srt_path}")
            try:
                raw_segments = []
                translated_texts = []
                with open(srt_path, "r", encoding="utf-8") as f:
                    content = f.read().strip().split("\n\n")
                    for block in content:
                        lines = block.split("\n")
                        if len(lines) >= 4:
                            # 1
                            # 00:00:01,000 --> 00:00:03,000
                            # [Translated]
                            # [Original]
                            times = lines[1].split(" --> ")
                            start = self._parse_srt_time(times[0])
                            end = self._parse_srt_time(times[1])
                            translated = lines[2].strip()
                            original = lines[3].strip()
                            raw_segments.append((start, end, original))
                            translated_texts.append(translated)
                
                if raw_segments:
                    return srt_path, raw_segments, translated_texts
            except Exception as e:
                print(f"[!] 加载现有字幕失败 ({e})，将重新生成...")

        # --- Step 1: Stream transcription (do NOT list() eagerly) ---
        print(f"[*] 转录中: {video_path}")
        t0 = time.time()
        try:
            segments_gen, info = self.model.transcribe(
                video_path,
                beam_size=self.beam_size,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
            )
        except Exception as e:
            print(f"[-] 转录失败: {e}")
            return None

        target_lang = 'zh-CN' if info.language != 'zh' else 'en'
        print(f"[*] 语言: {info.language} → 翻译目标: {target_lang}")

        # Consume the generator ONCE, collecting raw segment data
        raw_segments = []
        for seg in segments_gen:
            raw_segments.append((seg.start, seg.end, seg.text.strip()))

        print(f"[*] 转录完成 ({len(raw_segments)} 段, 耗时 {time.time()-t0:.1f}s)")

        if not raw_segments:
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write("1\n00:00:00,000 --> 00:00:05,000\n(No Dialogue)\n(无对白)\n\n")
            return srt_path

        # --- Step 2: Batch concurrent translation ---
        print(f"[*] 并发翻译 {len(raw_segments)} 个字幕段 (workers={self.max_workers})...")
        t1 = time.time()
        original_texts = [s[2] for s in raw_segments]
        translated_texts = self._translate_batch(original_texts, target_lang)
        print(f"[*] 翻译完成 (耗时 {time.time()-t1:.1f}s)")

        # --- Step 3: Write SRT ---
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, ((start, end, original), translated) in enumerate(
                    zip(raw_segments, translated_texts), start=1):
                f.write(f"{i}\n{self.format_time(start)} --> {self.format_time(end)}\n")
                if target_lang == 'zh-CN':
                    f.write(f"{translated}\n{original}\n\n")
                else:
                    f.write(f"{original}\n{translated}\n\n")

        print(f"[+] 字幕文件: {srt_path}")
        return srt_path, raw_segments, translated_texts

    # ------------------------------------------------------------------ #
    # Audio Processing: UVR Separation & F5-TTS Dubbing
    # ------------------------------------------------------------------ #

    def separate_audio(self, video_path: str, output_dir: str = "output") -> tuple[str, str]:
        """
        Separates vocals from background music using UVR (via audio-separator).
        Returns paths to (instrumental_path, vocals_path).
        """
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        video_output_dir = os.path.abspath(os.path.join(output_dir, base_name))
        os.makedirs(video_output_dir, exist_ok=True)
        
        print(f"[*] 正在进行人声分离 (UVR): {video_path}")
        
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        # audio-separator typically names files with specific suffixes
        # SEARCH in video_output_dir instead of root
        found_inst = ""
        found_voc = ""
        for f in os.listdir(video_output_dir):
            if f.startswith(base_name) and "Instrumental" in f:
                found_inst = os.path.join(video_output_dir, f)
            if f.startswith(base_name) and "Vocals" in f:
                found_voc = os.path.join(video_output_dir, f)

        if found_inst and found_voc:
            print(f"[+] 发现现有分离音频，正在加载: {os.path.basename(found_inst)}")
            return found_inst, found_voc

        if self.separator is None:
            # audio-separator handles device auto-detection or through model loading
            self.separator = Separator()
            # Try a very standard model name
            try:
                self.separator.load_model("UVR-MDX-NET-Voc_FT.onnx")
            except Exception:
                print("[!] 默认模型加载失败，尝试备选模型 UVR-MDX-NET-Inst_HQ_3.onnx...")
                self.separator.load_model("UVR-MDX-NET-Inst_HQ_3.onnx")

        # Perform separation (defaulting to current directory)
        print(f"[*] Separating audio segments...")
        output_files = self.separator.separate(video_path)
        
        # 🚀 Manually move files to ensure they go to the right video-specific folder
        inst_path = ""
        voc_path = ""
        import shutil
        for f in output_files:
            source_path = os.path.join(os.getcwd(), f)
            dest_path = os.path.join(video_output_dir, f)
            try:
                # Move if distinct, or just update full_path
                if os.path.abspath(source_path) != os.path.abspath(dest_path):
                    shutil.move(source_path, dest_path)
                
                if "Instrumental" in f:
                    inst_path = dest_path
                elif "Vocals" in f:
                    voc_path = dest_path
            except Exception as e:
                print(f"[!] Error moving separated file {f}: {e}")
                # Fallback to current path if move fails
                if "Instrumental" in f: inst_path = source_path
                if "Vocals" in f: voc_path = source_path

        print(f"[+] 分离完成: 背景音->{os.path.basename(inst_path)}, 人声->{os.path.basename(voc_path)}")
        return inst_path, voc_path

    def generate_dubbing(self, segments: list, translated_texts: list, 
                         ref_audio: str, video_path: str, output_dir: str = "output") -> str:
        """
        Generates a full dubbed track using F5-TTS based on translated segments.
        """
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        video_output_dir = os.path.abspath(os.path.join(output_dir, base_name))
        os.makedirs(video_output_dir, exist_ok=True)
        
        dub_path = os.path.join(video_output_dir, f"{base_name}_full_dub.wav")
        # Cache check
        if os.path.exists(dub_path):
            print(f"[+] 发现现有配音轨道，正在加载: {dub_path}")
            return dub_path

        print(f"[*] 正在生成 AI 配音 (F5-TTS) 使用参考音: {ref_audio}")
        
        # Temp voice segments folder inside video output dir
        voice_seg_dir = os.path.join(video_output_dir, "temp_voice")
        os.makedirs(voice_seg_dir, exist_ok=True)
        
        # 🚀 统一路径：不再使用根目录下的 full_dub.wav
        if self.tts is None:
            print(f"[*] Loading F5TTS on {self.device}...")
            try:
                self.tts = F5TTS(device=self.device)
            except Exception as e:
                # Fallback for model corruption
                if "Consistency check failed" in str(e):
                    print("[!] 检测到模型文件损坏，正在尝试强制重新下载 (force_download=True)...")
                    self.tts = F5TTS(device=self.device, force_download=True)
                else:
                    raise e
        
        # We'll create a silent base track first (or just use pydub to overlay)
        # To keep it simple, we generate each segment and then overlay it on a silent track of original length.
        # Actually, overlaying on a track that matches the video duration is better for sync.
        # But we need the total duration. We can get it from the last segment.
        total_duration_ms = int(segments[-1][1] * 1000) + 1000
        full_dub = AudioSegment.silent(duration=total_duration_ms)

        # Use global AudioSegment to pre-process reference audio to strictly 24kHz mono
        try:
            ref_aseg = AudioSegment.from_file(ref_audio).set_frame_rate(24000).set_channels(1)
            # Use a slightly different name for the pre-processed version to avoid overwriting original if same
            ref_audio_fixed = ref_audio.replace(".wav", "_fixed.wav")
            if ref_audio_fixed == ref_audio: ref_audio_fixed = "ref_temp_24k.wav"
            ref_aseg.export(ref_audio_fixed, format="wav")
            ref_audio = ref_audio_fixed
        except Exception as e:
            print(f"[!] Warning: Failed to pre-process ref audio: {e}")

        # Transcribe reference audio once
        print(f"[*] Transcribing reference audio for F5-TTS...")
        ref_res, _ = self.model.transcribe(ref_audio)
        ref_text = " ".join([seg.text for seg in ref_res]).strip()
        print(f"[+] Reference text: {ref_text!r}")

        for i, ((start, end, _), text) in enumerate(zip(segments, translated_texts)):
            # Filter out empty or extremely short segments that might cause tensor issues
            if not text.strip() or (end - start) < 0.3: 
                continue
            
            temp_wav = os.path.join(voice_seg_dir, f"seg_{i}.wav")
            # F5-TTS infer: Bypass infer_process and call infer_batch_process directly to avoid chunking issues
            with suppress_output():
                from f5_tts.infer.utils_infer import infer_batch_process
                # Load the fixed ref audio once for this call
                ref_audio_tensor, ref_sr = torchaudio.load(ref_audio)
                
                # We wrap the text in a list as expected by infer_batch_process
                gen_text_batches = [text] 
                
                # Getting the generator from infer_batch_process and taking the first result
                result_gen = infer_batch_process(
                    (ref_audio_tensor, ref_sr),
                    ref_text,
                    gen_text_batches,
                    self.tts.ema_model,
                    self.tts.vocoder,
                    mel_spec_type=self.tts.mel_spec_type,
                    device=self.device
                )
                wav, sr, _ = next(result_gen)
            
            # Save manually using scipy.io.wavfile (standard wav saving)
            if isinstance(wav, torch.Tensor):
                wav_np = wav.cpu().numpy()
            else:
                wav_np = wav # It's already a numpy array from infer_batch_process
            
            # Ensure correct shape and type for wavfile
            if wav_np.ndim > 1:
                wav_np = wav_np.flatten()
            
            # Convert to int16 if necessary, but F5-TTS float is usually fine for pydub
            wavfile.write(temp_wav, sr, wav_np)
            
            seg_audio = AudioSegment.from_wav(temp_wav)
            
            # --- Sync & Duration Matching ---
            orig_duration_ms = int((end - start) * 1000)
            gen_duration_ms = len(seg_audio)
            
            # If AI is too slow, speed it up to fit (without changing pitch)
            if gen_duration_ms > orig_duration_ms:
                # Use pydub speedup if the difference is significant
                speed_ratio = gen_duration_ms / orig_duration_ms
                print(f"    [*] Sync: Segment too long ({gen_duration_ms}ms vs {orig_duration_ms}ms). Speeding up x{speed_ratio:.2f}")
                # pydub.effects.speedup is a simple way, or we can just truncate if it's tiny
                if speed_ratio > 1.05:
                    from pydub.effects import speedup
                    seg_audio = speedup(seg_audio, playback_speed=speed_ratio)
                
                # Double check length after processing and truncate if still slightly over
                if len(seg_audio) > orig_duration_ms:
                    seg_audio = seg_audio[:orig_duration_ms]
            
            # If AI is too fast, we simply let it be (it will just have a silence before the next one)
            # This prevents overlap because we overlay at the exact start time.
            full_dub = full_dub.overlay(seg_audio, position=int(start * 1000))

        full_dub.export(dub_path, format="wav")
        print(f"[+] 配音合成完成: {dub_path}")
        return dub_path

    # ------------------------------------------------------------------ #
    # FFmpeg: GPU-first encoding with CPU fallback
    # ------------------------------------------------------------------ #

    def _has_nvenc(self) -> bool:
        """Quick check: does ffmpeg support h264_nvenc?"""
        try:
            result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=10
            )
            return "h264_nvenc" in result.stdout
        except Exception:
            return False

    def burn_subtitles(self, video_path: str, srt_path: str,
                       margin_v: int = 20, logo_path: str = None,
                       dubbing_path: str = None, inst_path: str = None,
                       output_dir: str = "output") -> str:
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        video_output_dir = os.path.abspath(os.path.join(output_dir, base_name))
        os.makedirs(video_output_dir, exist_ok=True)
        
        out_path = os.path.join(video_output_dir, f"{base_name}_final.mp4")

        rel_srt = os.path.relpath(srt_path).replace("\\", "/")
        style = (f"FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
                 f"BorderStyle=1,Outline=1,Shadow=1,MarginV={margin_v}")

        # Choose encoder: NVENC (GPU, ~5-10x faster) or libx264 (CPU)
        use_nvenc = self._has_nvenc()
        if use_nvenc:
            print("[*] FFmpeg: 使用 GPU 硬件编码 (h264_nvenc)")
            video_codec_args = ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "23"]
        else:
            print("[*] FFmpeg: 使用 CPU 编码 (libx264)")
            video_codec_args = ["-c:v", "libx264", "-preset", "fast", "-crf", "23"]

        print(f"[*] FFmpeg 处理中...")
        t0 = time.time()

        if dubbing_path and os.path.exists(dubbing_path):
            print(f"[*] FFmpeg: 正在合入新配音与背景音...")
            # Inputs: 0:video, 1:inst/dub/logo...
            inputs = ["-i", video_path]
            
            # Map indices
            v_idx = 0
            logo_idx = -1
            inst_idx = -1
            dub_idx = -1
            
            next_idx = 1
            if logo_path and os.path.exists(logo_path):
                inputs += ["-i", logo_path]
                logo_idx = next_idx
                next_idx += 1
            
            if inst_path and os.path.exists(inst_path):
                inputs += ["-i", inst_path]
                inst_idx = next_idx
                next_idx += 1
            
            inputs += ["-i", dubbing_path]
            dub_idx = next_idx
            next_idx += 1

            # Build Filter Complex
            filters = []
            # Video part
            if logo_idx != -1:
                filters.append(f"[{logo_idx}:v]crop='min(iw,ih)':'min(iw,ih)'[sq]")
                # 修复: 'md5' -> '1' (因为 logo 已经过 crop 变成正方形，宽高比为 1)
                filters.append(f"[sq][0:v]scale2ref=w='oh':h='ih/10'[logo_raw][main]")
                filters.append(f"[logo_raw]format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lte(pow(X-W/2,2)+pow(Y-H/2,2),pow(W/2,2)),255,0)'[circle]")
                filters.append(f"[main]subtitles='{rel_srt}':force_style='{style}'[v_sub]")
                filters.append(f"[v_sub][circle]overlay=W-w-15:15[vout]")
            else:
                filters.append(f"[0:v]subtitles='{rel_srt}':force_style='{style}'[vout]")
            
            # Audio part
            if inst_idx != -1:
                filters.append(f"[{inst_idx}:a][{dub_idx}:a]amix=inputs=2:duration=first[aout]")
            else:
                filters.append(f"[{dub_idx}:a]copy[aout]")
            
            filter_str = ";".join(filters)
            cmd = (["ffmpeg", "-y"] + inputs + 
                   ["-filter_complex", filter_str, "-map", "[vout]", "-map", "[aout]"] + 
                   video_codec_args + ["-c:a", "aac", "-b:a", "192k", out_path])
        
        elif logo_path and os.path.exists(logo_path):
            rel_logo = os.path.relpath(logo_path).replace("\\", "/")
            filter_complex = (
                "[1:v]crop='min(iw,ih)':'min(iw,ih)'[sq];"
                "[sq][0:v]scale2ref=w='iw/14':h='iw/14'[logo_raw][main];"
                "[logo_raw]format=rgba,"
                "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                "a='if(lte(pow(X-W/2,2)+pow(Y-H/2,2),pow(W/2,2)),255,0)'[circle];"
                f"[main]subtitles='{rel_srt}':force_style='{style}'[v_sub];"
                "[v_sub][circle]overlay=W-w-15:15"
            )
            cmd = (["ffmpeg", "-y",
                    "-i", video_path,
                    "-i", rel_logo,
                    "-filter_complex", filter_complex]
                   + video_codec_args
                   + ["-c:a", "aac", "-b:a", "192k", out_path])
        else:
            cmd = (["ffmpeg", "-y",
                    "-i", video_path,
                    "-vf", f"subtitles='{rel_srt}':force_style='{style}'"]
                   + video_codec_args
                   + ["-c:a", "aac", "-b:a", "192k", out_path])

        try:
            subprocess.run(cmd, check=True, capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
            print(f"[+] 编码完成 (耗时 {time.time()-t0:.1f}s): {out_path}")
            return out_path
        except subprocess.CalledProcessError as e:
            print(f"[-] FFmpeg 错误:\n{e.stderr[-500:]}")
            return None

    # ------------------------------------------------------------------ #
    # Cover Generation: Horizontal & Vertical
    # ------------------------------------------------------------------ #

    def generate_covers(self, image_path: str, output_dir: str) -> dict:
        """
        Generates horizontal (16:9) and vertical (9:16) covers from a thumbnail.
        Vertical cover uses a blurred version of the image as the background.
        """
        if not image_path or not os.path.exists(image_path):
            print("[!] No thumbnail to generate covers from.")
            return {}

        results = {}
        h_path = os.path.join(output_dir, "cover_horizontal.jpg")
        v_path = os.path.join(output_dir, "cover_vertical.jpg")

        print(f"[*] Generating Horizontal Cover (16:9)...")
        # Horizontal: Fit into 1920x1080 with black padding if necessary
        cmd_h = [
            "ffmpeg", "-y", "-i", image_path,
            "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
            h_path
        ]
        
        print(f"[*] Generating Vertical Cover (9:16) with Blur BG...")
        # Vertical: Blur Background (scaled to fill 1080x1920) + Centered Original (scaled to fit width)
        cmd_v = [
            "ffmpeg", "-y", "-i", image_path,
            "-vf", (
                "split[bg_raw][fg_raw];"
                "[bg_raw]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:20[bg];"
                "[fg_raw]scale=1080:-1[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2"
            ),
            v_path
        ]

        try:
            subprocess.run(cmd_h, check=True, capture_output=True)
            results['horizontal'] = h_path
            print(f"[+] Horizontal Cover: {h_path}")
            
            subprocess.run(cmd_v, check=True, capture_output=True)
            results['vertical'] = v_path
            print(f"[+] Vertical Cover: {v_path}")
        except subprocess.CalledProcessError as e:
            print(f"[-] FFmpeg Cover Error: {e.stderr.decode(errors='replace')}")

        return results
