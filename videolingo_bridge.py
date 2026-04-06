"""
videolingo_bridge.py
====================
将 VideoLingo 的完整流程（WhisperX转录 + AI翻译 + 高质量TTS）
封装为 VideoCapter 可直接调用的接口。

集成方式：
  通过 VideoLingo 的虚拟环境 subprocess 调用，完全隔离，
  无需在 VideoCapter 环境中安装 VL 的全部依赖。

调用方式:
  from videolingo_bridge import VideoLingoBridge
  bridge = VideoLingoBridge(tts_method='edge_tts', whisper_language='en')
  result = bridge.process_video('path/to/video.mp4', dubbing=True)
  # result['srt_path']   -> 字幕 SRT 文件路径
  # result['dub_path']   -> 配音结果路径（mp4/wav）
  # result['vl_out_dir'] -> VL output 目录
  # result['success']    -> bool
"""

import os
import sys
import shutil
import subprocess
import time
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────
# 路径常量
# ──────────────────────────────────────────────────────────────────────
VL_DIR      = Path(r"d:\VideoLingo")
VL_VENV_PY  = VL_DIR / ".venv" / "Scripts" / "python.exe"
VL_CONFIG   = VL_DIR / "config.yaml"
VL_OUTPUT   = VL_DIR / "output"
VC_DIR      = Path(r"d:\videoCapter")
VC_CFG_TPL  = VC_DIR / "vl_config_template.yaml"

# VL 内部管道运行脚本（动态生成）
_VL_RUNNER  = VL_DIR / "_vc_runner.py"


class VideoLingoBridge:
    """
    通过 VideoLingo 虚拟环境运行字幕生成 + 翻译 + TTS 配音。
    以 subprocess 方式调用，避免依赖冲突。
    """

    def __init__(
        self,
        tts_method: str = "edge_tts",
        whisper_language: str = "en",
        target_language: str = "简体中文",
        llm_api_key: str = "",
        llm_base_url: str = "https://api.deepseek.com",
        llm_model: str = "deepseek-chat",
        extra_config: dict = None,
    ):
        self.tts_method       = tts_method
        self.whisper_language = whisper_language
        self.target_language  = target_language
        self.llm_api_key      = llm_api_key
        self.llm_base_url     = llm_base_url
        self.llm_model        = llm_model
        self.extra_config     = extra_config or {}

        self._check_vl()
        print(f"[VL Bridge] 就绪 | TTS={tts_method} | "
              f"语言={whisper_language}→{target_language}")

    # ──────────────────────────────────────────────────────────────────
    # 前置检查
    # ──────────────────────────────────────────────────────────────────

    def _check_vl(self):
        if not VL_DIR.exists():
            raise RuntimeError(
                f"VideoLingo 目录不存在: {VL_DIR}\n"
                f"请运行: install_videolingo.bat"
            )
        if not VL_VENV_PY.exists():
            raise RuntimeError(
                f"VL Python 环境未找到: {VL_VENV_PY}\n"
                f"请运行: install_videolingo.bat"
            )

    # ──────────────────────────────────────────────────────────────────
    # 主接口
    # ──────────────────────────────────────────────────────────────────

    def process_video(
        self,
        video_path: str,
        output_dir: str = "output",
        dubbing: bool = True,
    ) -> dict:
        """
        使用 VideoLingo 处理视频（字幕+翻译+TTS配音）。

        Args:
            video_path: 已下载的本地视频路径
            output_dir: VideoCapter output 目录
            dubbing: True=生成配音, False=仅生成字幕

        Returns:
            dict {
              'success': bool,
              'srt_path': str,    # 翻译后字幕
              'dub_path': str,    # 配音视频/音频（dubbing=True 时）
              'vl_out_dir': str,  # VL output 目录
              'error': str        # 失败时的错误信息
            }
        """
        video_path = os.path.abspath(video_path)
        base_name  = Path(video_path).stem
        print(f"\n[VL Bridge] ═══ 开始处理: {base_name} ═══")

        try:
            # 1. 写入 config.yaml
            self._write_config()

            # 2. 清理并准备 VL output 目录
            if VL_OUTPUT.exists():
                shutil.rmtree(VL_OUTPUT)
            VL_OUTPUT.mkdir(parents=True)

            # 3. 把视频复制到 VL output（VL 从这里读取待处理视频）
            vl_video = VL_OUTPUT / Path(video_path).name
            shutil.copy2(video_path, vl_video)
            print(f"[VL Bridge] 视频已就位: {vl_video.name}")

            # 4. 生成 VL 运行脚本
            self._write_runner(str(vl_video), dubbing)

            # 5. 通过 VL 虚拟环境执行
            success, err = self._exec_runner()

            if not success:
                print(f"[VL Bridge] ✗ VL 流程失败: {err}")
                return {"success": False, "error": err,
                        "vl_out_dir": str(VL_OUTPUT)}

            # 6. 收集输出文件 → VC output
            result = self._collect(base_name, output_dir, dubbing)
            result["success"] = True
            print(f"[VL Bridge] ✓ 完成")
            return result

        except Exception as e:
            import traceback; traceback.print_exc()
            return {"success": False, "error": str(e),
                    "vl_out_dir": str(VL_OUTPUT)}

    # ──────────────────────────────────────────────────────────────────
    # 写入 VL config.yaml
    # ──────────────────────────────────────────────────────────────────

    def _write_config(self):
        """把用户参数合并进 VL config.yaml"""
        import yaml

        # 读现有模板（如果有）
        if VC_CFG_TPL.exists():
            with open(VC_CFG_TPL, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        else:
            cfg = {}

        # 必要覆盖项
        cfg["tts_method"]    = self.tts_method
        cfg["target_language"] = self.target_language
        cfg["burn_subtitles"]  = False   # 我们自己烧录

        cfg.setdefault("whisper", {})
        cfg["whisper"]["language"] = self.whisper_language
        cfg["whisper"]["detected_language"] = self.whisper_language

        cfg.setdefault("api", {})
        if self.llm_api_key:
            cfg["api"]["key"]      = self.llm_api_key
        if self.llm_base_url:
            cfg["api"]["base_url"] = self.llm_base_url
        if self.llm_model:
            cfg["api"]["model"]    = self.llm_model

        for k, v in self.extra_config.items():
            cfg[k] = v

        with open(VL_CONFIG, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)

        print(f"[VL Bridge] config.yaml 更新完成 (TTS={self.tts_method})")

    # ──────────────────────────────────────────────────────────────────
    # 生成 VL 内部运行脚本
    # ──────────────────────────────────────────────────────────────────

    def _write_runner(self, video_path: str, dubbing: bool):
        """
        生成在 VL 虚拟环境中运行的脚本，
        直接调用 VL 核心步骤（跳过依赖 streamlit 的 batch 层）。
        """
        dub_flag  = "True" if dubbing else "False"
        video_bn  = Path(video_path).name

        code = f'''
# ── Auto-generated by VideoLingoBridge ──
import sys, os, shutil, traceback
sys.path.insert(0, r"{VL_DIR}")
os.chdir(r"{VL_DIR}")

VIDEO_FILE   = r"{video_bn}"
OUTPUT_DIR   = r"{VL_OUTPUT}"
ENABLE_DUB   = {dub_flag}

def run_step(name, fn):
    print(f"[VL] >>> {{name}}")
    for attempt in range(3):
        try:
            result = fn()
            if isinstance(result, dict):
                globals().update(result)
            print(f"[VL] <<< {{name}} OK")
            return True
        except Exception as e:
            if attempt == 2:
                print(f"[VL] XXX {{name}} FAILED: {{e}}")
                traceback.print_exc()
                return False
            print(f"[VL] !!! {{name}} 重试 ({{attempt+1}}/3)...")
    return False

# ── 步骤函数 ──────────────────────────────────────────
def step_prepare():
    """确保视频文件在 output 目录"""
    src = os.path.join(OUTPUT_DIR, VIDEO_FILE)
    if not os.path.exists(src):
        raise FileNotFoundError(f"视频不存在: {{src}}")
    return {{"video_file": src}}

def step_transcribe():
    from core import _2_asr
    _2_asr.transcribe()

def step_split():
    from core import _3_1_split_nlp, _3_2_split_meaning
    _3_1_split_nlp.split_by_spacy()
    _3_2_split_meaning.split_sentences_by_meaning()

def step_translate():
    from core import _4_1_summarize, _4_2_translate
    _4_1_summarize.get_summary()
    _4_2_translate.translate_all()

def step_align_sub():
    from core import _5_split_sub, _6_gen_sub
    _5_split_sub.split_for_sub_main()
    _6_gen_sub.align_timestamp_main()

def step_sub_to_video():
    from core import _7_sub_into_vid
    _7_sub_into_vid.merge_subtitles_to_video()

def step_audio_tasks():
    from core import _8_1_audio_task, _8_2_dub_chunks
    _8_1_audio_task.gen_audio_task_main()
    _8_2_dub_chunks.gen_dub_chunks()

def step_ref_audio():
    from core import _9_refer_audio
    _9_refer_audio.extract_refer_audio_main()

def step_gen_audio():
    from core import _10_gen_audio
    _10_gen_audio.gen_audio()

def step_merge_audio():
    from core import _11_merge_audio
    _11_merge_audio.merge_full_audio()

def step_dub_to_vid():
    from core import _12_dub_to_vid
    _12_dub_to_vid.merge_video_audio()

# ── 执行流程 ──────────────────────────────────────────
steps = [
    ("准备视频文件",   step_prepare),
    ("WhisperX 转录", step_transcribe),
    ("NLP 分句",      step_split),
    ("AI 翻译",       step_translate),
    ("字幕对齐",      step_align_sub),
    ("字幕嵌入视频",  step_sub_to_video),
]

if ENABLE_DUB:
    steps += [
        ("生成音频任务", step_audio_tasks),
        ("提取参考音频", step_ref_audio),
        ("TTS 生成音频", step_gen_audio),
        ("合并音频",     step_merge_audio),
        ("配音合入视频", step_dub_to_vid),
    ]

failed = False
for name, fn in steps:
    if not run_step(name, fn):
        failed = True
        break

if failed:
    print("VL_RESULT:FAILED")
    sys.exit(1)
else:
    print("VL_RESULT:SUCCESS")
    sys.exit(0)
'''

        _VL_RUNNER.write_text(code, encoding="utf-8")
        print(f"[VL Bridge] 运行脚本已生成: {_VL_RUNNER.name}")

    # ──────────────────────────────────────────────────────────────────
    # 执行 VL 运行脚本
    # ──────────────────────────────────────────────────────────────────

    def _exec_runner(self) -> tuple:
        """
        在 VL 虚拟环境中运行 _vc_runner.py，
        实时将 VL 输出打印到控制台，超时 3 小时。
        返回 (success: bool, error_msg: str)
        """
        print(f"[VL Bridge] 启动 VL 处理（可能需要几分钟）...")
        try:
            proc = subprocess.Popen(
                [str(VL_VENV_PY), str(_VL_RUNNER)],
                cwd=str(VL_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            last_line = ""
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    print(f"  [VL] {line}")
                    last_line = line

            proc.wait(timeout=10800)  # 3 小时

            _VL_RUNNER.unlink(missing_ok=True)

            if proc.returncode == 0 and "VL_RESULT:SUCCESS" in last_line:
                return True, ""
            else:
                return False, f"返回码 {proc.returncode}, 最后输出: {last_line}"

        except subprocess.TimeoutExpired:
            proc.kill()
            return False, "处理超时（>3小时）"
        except Exception as e:
            return False, str(e)

    # ──────────────────────────────────────────────────────────────────
    # 收集 VL 输出文件
    # ──────────────────────────────────────────────────────────────────

    def _collect(self, base_name: str, output_dir: str, dubbing: bool) -> dict:
        """
        从 VL output 目录收集字幕和配音文件，
        复制到 VideoCapter 的 output/{base_name}/ 目录。
        """
        vc_out = Path(output_dir) / base_name
        vc_out.mkdir(parents=True, exist_ok=True)

        result = {
            "srt_path":   None,
            "dub_path":   None,
            "vl_out_dir": str(VL_OUTPUT),
        }

        if not VL_OUTPUT.exists():
            return result

        # 收集字幕 SRT
        srt_priority = ["translated", "zh", "bilingual", ""]
        srt_candidates = list(VL_OUTPUT.rglob("*.srt"))

        for keyword in srt_priority:
            for f in srt_candidates:
                if keyword in f.name.lower() or keyword == "":
                    dest = vc_out / f.name
                    shutil.copy2(f, dest)
                    result["srt_path"] = str(dest)
                    print(f"[VL Bridge] 字幕: {f.name}")
                    break
            if result["srt_path"]:
                break

        # 收集配音结果
        if dubbing:
            # 优先找 VL 合成的最终视频
            for pattern in ["*dub*.mp4", "*audio*.mp4", "*.mp4"]:
                mp4s = [f for f in VL_OUTPUT.rglob(pattern)
                        if f.name != Path(result.get("srt_path", "x")).name]
                if mp4s:
                    # 取最新的
                    mp4s.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                    dest = vc_out / mp4s[0].name
                    shutil.copy2(mp4s[0], dest)
                    result["dub_path"] = str(dest)
                    print(f"[VL Bridge] 配音视频: {mp4s[0].name}")
                    break

            # 如未找到 mp4，找 wav
            if not result["dub_path"]:
                for f in VL_OUTPUT.rglob("*.wav"):
                    if any(k in f.name.lower() for k in ("merge", "final", "dub", "full")):
                        dest = vc_out / f.name
                        shutil.copy2(f, dest)
                        result["dub_path"] = str(dest)
                        print(f"[VL Bridge] 配音音频: {f.name}")
                        break

        # 归档 VL 所有中间文件
        archive = vc_out / "vl_output_archive"
        try:
            if archive.exists():
                shutil.rmtree(archive)
            shutil.copytree(VL_OUTPUT, archive)
        except Exception:
            pass

        return result


# ──────────────────────────────────────────────────────────────────────
# SRT 解析工具（供 main.py 在需要时解析字幕段落）
# ──────────────────────────────────────────────────────────────────────

def parse_srt(srt_path: str) -> tuple:
    """
    解析 SRT 文件。
    Returns:
        segments: list of (start_sec, end_sec, text)
        texts:    list of str
    """
    segments, texts = [], []
    try:
        with open(srt_path, "r", encoding="utf-8") as f:
            blocks = f.read().strip().split("\n\n")
        for block in blocks:
            lines = [l.strip() for l in block.split("\n") if l.strip()]
            if len(lines) < 3 or "-->" not in lines[1]:
                continue
            t1, t2 = lines[1].split("-->")
            start = _srt_sec(t1.strip())
            end   = _srt_sec(t2.strip())
            text  = " ".join(lines[2:])
            segments.append((start, end, text))
            texts.append(text)
    except Exception as e:
        print(f"[VL Bridge] SRT 解析错误: {e}")
    return segments, texts


def _srt_sec(t: str) -> float:
    t = t.replace(",", ".")
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


# ──────────────────────────────────────────────────────────────────────
# CLI 测试接口
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="VideoLingo Bridge 测试")
    p.add_argument("video", help="视频路径")
    p.add_argument("--tts",    default="edge_tts", help="TTS 方法（默认 edge_tts）")
    p.add_argument("--lang",   default="en",       help="源语言（默认 en）")
    p.add_argument("--no-dub", action="store_true", help="仅字幕，不配音")
    p.add_argument("--key",    default="",         help="LLM API Key")
    args = p.parse_args()

    bridge = VideoLingoBridge(
        tts_method=args.tts,
        whisper_language=args.lang,
        llm_api_key=args.key,
    )
    result = bridge.process_video(args.video, dubbing=not args.no_dub)
    print("\n── 结果 ──")
    for k, v in result.items():
        print(f"  {k}: {v}")
