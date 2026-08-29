# ============================================================
# faster-whisper 中文語音辨識 demo —— docs/asr-todo.md 第 4.1 節
#
# 目的：在動 server.py 之前，先獨立驗證
#   1. faster-whisper 在這台桌機 (CPU / int8) 跑不跑得起來
#   2. 中文（繁體優先）辨識品質可不可接受
#   3. 單次辨識的延遲 / RTF（realtime factor）數據
#
# 這支腳本「不」import server.py，也不碰任何正式程式碼。
#
# 用法：
#   venv\Scripts\python scripts\asr_demo.py <audio.wav>
#   venv\Scripts\python scripts\asr_demo.py rec.wav --model base
#   venv\Scripts\python scripts\asr_demo.py rec.wav --model small --compute int8
#
# 常用參數：
#   --model    tiny | base | small | medium  (預設 small，中文優先驗證)
#   --compute  int8 | int8_float32 | float32  (CPU 建議 int8)
#   --lang     預設 zh；設 auto 讓模型自己偵測
#   --no-vad   關掉內建 VAD filter（比較「有無 VAD」對延遲/斷句的影響）
#
# 模型檔第一次跑會自動從 HuggingFace 下載到 ~/.cache/huggingface，
# small 約 480MB、base 約 145MB、medium 約 1.5GB。
# ============================================================

import argparse
import sys
import time
from pathlib import Path

try:  # Windows 主控台預設 cp950，印中文會爆
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 繁體中文輸出的提示語：Whisper 對中文預設偏向輸出簡體，
# 用 initial_prompt 稍微把輸出風格拉回繁體 / 台灣用語。
DEFAULT_ZH_PROMPT = "以下是台灣人的日常對話，請以繁體中文輸出。"


def main() -> None:
    ap = argparse.ArgumentParser(description="faster-whisper 單次中文辨識 demo")
    ap.add_argument("audio", type=Path, help="要辨識的音訊檔 (wav/mp3/m4a 皆可，內部用 ffmpeg 解碼)")
    ap.add_argument("--model", default="small", help="模型大小 (預設 small)")
    ap.add_argument("--lang", default="zh", help="語言代碼，預設 zh；auto = 自動偵測")
    ap.add_argument("--device", default="cpu", help="cpu 或 cuda (預設 cpu)")
    ap.add_argument("--compute", default="int8", help="量化型別 (預設 int8)")
    ap.add_argument("--beam", type=int, default=5, help="beam size (預設 5)")
    ap.add_argument("--no-vad", action="store_true", help="關掉內建 VAD filter")
    ap.add_argument("--prompt", default=DEFAULT_ZH_PROMPT, help="initial_prompt；設空字串可關掉")
    args = ap.parse_args()

    if not args.audio.exists():
        sys.exit(f"找不到音訊檔: {args.audio}")

    from faster_whisper import WhisperModel

    t0 = time.perf_counter()
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute)
    load_s = time.perf_counter() - t0
    print(f"[load]  model={args.model} device={args.device} compute={args.compute}  ->  {load_s:.2f}s")

    language = None if args.lang == "auto" else args.lang

    t1 = time.perf_counter()
    segments, info = model.transcribe(
        str(args.audio),
        language=language,
        beam_size=args.beam,
        vad_filter=not args.no_vad,
        initial_prompt=args.prompt or None,
    )
    segments = list(segments)  # segments 是 generator，這行才真的觸發運算
    infer_s = time.perf_counter() - t1

    dur = info.duration or 0.0
    rtf = infer_s / dur if dur else float("nan")
    print(
        f"[audio] duration={dur:.2f}s  "
        f"detected_lang={info.language} (p={info.language_probability:.2f})"
    )
    print(
        f"[infer] {infer_s:.2f}s  RTF={rtf:.2f}x  "
        f"(beam={args.beam}, VAD={'off' if args.no_vad else 'on'})"
    )
    print("-" * 64)
    parts = []
    for s in segments:
        print(f"[{s.start:6.2f} -> {s.end:6.2f}]  {s.text.strip()}")
        parts.append(s.text.strip())
    print("-" * 64)
    print("全文：" + "".join(parts))


if __name__ == "__main__":
    main()
