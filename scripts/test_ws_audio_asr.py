# ============================================================
# /ws/audio 的端到端測試（4.2）：把合成的「兩句話 + 中間停頓」串流
# 用 320ms chunk 餵進 WebSocket，檢查後端有沒有回 transcript。
#
# 需要先啟動後端：
#   venv\Scripts\python -m uvicorn server:app --port 8000
# 然後：
#   venv\Scripts\python scripts\test_ws_audio_asr.py
# ============================================================

import asyncio
import json
import struct
import sys
import wave
from pathlib import Path

import websockets

try:  # Windows 主控台預設 cp950，印中文會爆
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from voice_asr import BYTES_PER_MS, SAMPLE_RATE  # noqa: E402

WS_URL = "ws://localhost:8000/ws/audio"
CHUNK_MS = 320
CHUNK_BYTES = CHUNK_MS * BYTES_PER_MS
WAVS = ["samples/tts/01_HsiaoChen_p0.wav", "samples/tts/02_YunJhe_p0.wav"]


def read_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (SAMPLE_RATE, 1, 2)
        return w.readframes(w.getnframes())


def silence(ms: int) -> bytes:
    n = ms * SAMPLE_RATE // 1000
    return struct.pack(f"<{n}h", *([0] * n))


async def main() -> None:
    paths = [ROOT / p for p in WAVS]
    if any(not p.exists() for p in paths):
        sys.exit("缺 samples/tts/*.wav；先跑 scripts\\gen_tts_samples.py")

    stream = silence(600)
    for i, p in enumerate(paths):
        stream += read_pcm(p) + silence(900 if i == len(paths) - 1 else 1000)

    acks = 0
    transcripts = []
    async with websockets.connect(WS_URL, max_size=None) as ws:
        async def sender():
            for off in range(0, len(stream), CHUNK_BYTES):
                await ws.send(stream[off:off + CHUNK_BYTES])
                await asyncio.sleep(0.05)  # 不用真 320ms，快轉

        send_task = asyncio.create_task(sender())
        try:
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                t = msg.get("type")
                if t == "ack":
                    acks += 1
                elif t == "transcript":
                    transcripts.append(msg)
                    print(f"  transcript: {msg['text']!r} "
                          f"(audio {msg.get('audio_ms')}ms, ASR {msg.get('asr_latency_ms')}ms)")
                elif t == "error":
                    print(f"  error: {msg}")
                if send_task.done() and len(transcripts) >= len(paths):
                    break
        except asyncio.TimeoutError:
            print("  (等 transcript 逾時)")

    print(f"\nacks={acks}, transcripts={len(transcripts)} (預期 {len(paths)})")
    print("PASS" if len(transcripts) == len(paths) else "FAIL")
    sys.exit(0 if len(transcripts) == len(paths) else 1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (ConnectionRefusedError, OSError) as e:
        sys.exit(f"連不上 {WS_URL}，先啟動後端。({e})")
