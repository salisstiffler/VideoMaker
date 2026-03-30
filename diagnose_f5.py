import torch
import torchaudio
import numpy as np
import os
import sys
from contextlib import contextmanager, redirect_stdout, redirect_stderr

@contextmanager
def suppress_output():
    with open(os.devnull, 'w') as fnull:
        with redirect_stdout(fnull), redirect_stderr(fnull):
            yield

# Monkey patch BEFORE imports that might use torchaudio
import torchaudio
from pydub import AudioSegment

original_load = torchaudio.load
def patched_load(filepath, *args, **kwargs):
    audio = AudioSegment.from_file(filepath).set_frame_rate(24000).set_channels(1)
    samples = np.array(audio.get_array_of_samples()).astype(np.float32)
    if audio.sample_width == 2: samples /= 32768.0
    return torch.from_numpy(samples.reshape((1, -1))), 24000

torchaudio.load = patched_load

from f5_tts.api import F5TTS
from f5_tts.infer.utils_infer import infer_process, convert_char_to_pinyin, hop_length

def diagnose():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using Device: {device}")
    
    ref_audio = "my_voice.wav"
    # The exact text from the user's error log
    ref_text = "視頻原生克隆與人生菲林共農說明 我們已經集成了F5-TTS聲音克隆和UVR人生菲林技術 現在你可以將任何視頻的語音接望著 為你自己的音色同時保留視頻的背景音樂"
    gen_text = "测试生成文本"
    
    if not os.path.exists(ref_audio):
        # Create a dummy 1s silence if missing for testing
        AudioSegment.silent(duration=1000).export(ref_audio, format="wav")

    print(f"Ref text len: {len(ref_text)}")
    
    tts = F5TTS(device=device)
    
    print("\n--- Internal Shape Analysis ---")
    # 1. Manually check pinyin expansion
    text_list = [ref_text + gen_text]
    final_text_list = convert_char_to_pinyin(text_list)
    print(f"Pinyin tokens: {len(final_text_list[0])}")
    
    # 2. Check audio mel length
    audio, _ = torchaudio.load(ref_audio)
    ref_audio_len = audio.shape[-1] // hop_length
    print(f"Audio mel frames: {ref_audio_len}")
    
    # 3. Predict duration as F5-TTS does
    ref_text_len = len(ref_text.encode("utf-8"))
    gen_text_len = len(gen_text.encode("utf-8"))
    duration = ref_audio_len + int(ref_audio_len / ref_text_len * gen_text_len)
    print(f"Predicted total duration (frames): {duration}")

    # 4. Final attempt
    print("\nRunning infer_process...")
    try:
        with suppress_output():
            wav, sr, _ = infer_process(
                ref_audio,
                ref_text,
                gen_text,
                tts.ema_model,
                tts.vocoder,
                tts.mel_spec_type,
                device=device
            )
        print("Success!")
    except Exception as e:
        print(f"\nCaught Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    diagnose()
