# ============================================================
# 錄一段自己講話的 wav，給 scripts/asr_demo.py 測中文辨識用。
#
# 直接錄成 asr / JoyGen 要的格式：16kHz / mono / 16-bit PCM。
#
# 用法：
#   venv\Scripts\python scripts\record_wav.py rec.wav            # 錄 6 秒
#   venv\Scripts\python scripts\record_wav.py rec.wav --sec 10
#   venv\Scripts\python scripts\record_wav.py --list             # 列出輸入裝置
#   venv\Scripts\python scripts\record_wav.py rec.wav --device 3 # 指定裝置編號
#
# 需要 sounddevice + soundfile（已裝在 venv 裡）。
# ============================================================

import argparse
import sys
import time
from pathlib import Path

SAMPLE_RATE = 16000


def main() -> None:
    ap = argparse.ArgumentParser(description="錄 16kHz/mono/16-bit PCM wav")
    ap.add_argument("out", type=Path, nargs="?", help="輸出 wav 檔名")
    ap.add_argument("--sec", type=float, default=6.0, help="錄音秒數 (預設 6)")
    ap.add_argument("--device", type=int, default=None, help="輸入裝置編號 (見 --list)")
    ap.add_argument("--list", action="store_true", help="列出所有輸入裝置後結束")
    args = ap.parse_args()

    import sounddevice as sd
    import soundfile as sf

    if args.list:
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                print(f"  [{i}] {d['name']}  ({d['max_input_channels']}ch @ {int(d['default_samplerate'])}Hz)")
        return

    if args.out is None:
        sys.exit("要指定輸出檔名，例如：python scripts/record_wav.py rec.wav")

    for n in (3, 2, 1):
        print(f"  {n}...", flush=True)
        time.sleep(1)
    print(f"  ● 開始錄音 {args.sec:.0f} 秒，請講話...", flush=True)

    audio = sd.rec(
        int(args.sec * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        device=args.device,
    )
    sd.wait()
    sf.write(str(args.out), audio, SAMPLE_RATE, subtype="PCM_16")
    print(f"  ✔ 已存 {args.out}  ({args.sec:.0f}s / {SAMPLE_RATE}Hz / mono / 16-bit)")
    print(f"  下一步：venv\\Scripts\\python scripts\\asr_demo.py {args.out}")


if __name__ == "__main__":
    main()
