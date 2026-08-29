# ============================================================
# voice_asr.Endpointer 的離線測試（不用 server、不用真麥克風）。
#
# 做法：把幾個測試 wav 用靜音串起來，模擬「講一句、停一下、再講一句」，
# 切成 320ms chunk 餵給 Endpointer，檢查：
#   - 斷句數量對不對（幾句話就該吐幾個 Utterance）
#   - 每句的長度 / 有聲長度合理
#   - 接 Transcriber 辨識，內容有沒有掉
#
# 用法：
#   venv\Scripts\python scripts\test_endpointer.py
#   venv\Scripts\python scripts\test_endpointer.py samples\tts\01_HsiaoChen_p0.wav samples\tts\02_YunJhe_p0.wav
# ============================================================

import struct
import sys
import wave
from pathlib import Path

try:  # Windows 主控台預設 cp950，印中文會爆
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from voice_asr import BYTES_PER_MS, SAMPLE_RATE, Endpointer, Transcriber  # noqa: E402

CHUNK_MS = 320
CHUNK_BYTES = CHUNK_MS * BYTES_PER_MS
DEFAULT_WAVS = ["samples/tts/01_HsiaoChen_p0.wav", "samples/tts/02_YunJhe_p0.wav"]
GAP_MS = 1400       # 句子之間的靜音（要 > end_silence_ms 900 + chunk 粒度）
TAIL_MS = 1400      # 最後一句後面的靜音
LEAD_MS = 600       # 開頭墊一點靜音給校正用


def read_wav_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == SAMPLE_RATE, f"{path} 不是 16kHz"
        assert w.getnchannels() == 1, f"{path} 不是 mono"
        assert w.getsampwidth() == 2, f"{path} 不是 16-bit"
        return w.readframes(w.getnframes())


def silence(ms: int) -> bytes:
    return struct.pack("<%dh" % (ms * SAMPLE_RATE // 1000), *([0] * (ms * SAMPLE_RATE // 1000)))


def main() -> None:
    wav_paths = [Path(p) for p in (sys.argv[1:] or DEFAULT_WAVS)]
    missing = [p for p in wav_paths if not p.exists()]
    if missing:
        sys.exit(f"找不到 {missing}；先跑 scripts\\gen_tts_samples.py 產生測試語音")

    clips = [read_wav_pcm(p) for p in wav_paths]
    stream = silence(LEAD_MS)
    for i, c in enumerate(clips):
        stream += c
        stream += silence(TAIL_MS if i == len(clips) - 1 else GAP_MS)

    print(f"合成測試串流：{len(clips)} 句，總長 {len(stream) / BYTES_PER_MS / 1000:.1f}s")

    ep = Endpointer()
    utterances = []
    for off in range(0, len(stream), CHUNK_BYTES):
        chunk = stream[off:off + CHUNK_BYTES]
        if len(chunk) < BYTES_PER_MS:
            break
        u = ep.feed(chunk)
        if u is not None:
            utterances.append(u)
            print(f"  → 斷句 #{len(utterances)}: {u.duration_ms:.0f}ms "
                  f"(有聲 {u.voiced_ms:.0f}ms, 尾靜音 {u.trailing_silence_ms:.0f}ms)")

    print(f"\n共斷出 {len(utterances)} 句（預期 {len(clips)}）")
    ok = len(utterances) == len(clips)

    print("\n接 faster-whisper 辨識：")
    tr = Transcriber(model_size="small")
    tr.load()
    for i, u in enumerate(utterances):
        r = tr.transcribe(u.pcm)
        print(f"  #{i + 1} [{r.latency_ms}ms, RTF {r.latency_ms / r.audio_ms:.2f}x] {r.text}")

    print("\nPASS" if ok else "\nFAIL：斷句數量不符")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
