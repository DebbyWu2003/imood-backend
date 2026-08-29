# ============================================================
# 測 /ws/audio 的「續句合併」（VOICE_COALESCE_MS）。
#
#   A. 一句話從中間切開、塞 ~1.2s 靜音（模擬念頭中間停頓，會被 VAD 切成兩段）：
#      → 應收到 2 個 transcript，但只有 1 次 reply_done（兩段併起來回一次）
#   B. 兩段之間塞 ~3s 靜音（> end_silence + coalesce）：
#      → 2 個 transcript + 2 次 reply_done（各自回）
#
# 用「切開同一個 wav」而不是接兩個檔，避免檔案本身頭尾靜音影響間隔長度。
#
# 需要先啟動後端（要有 Qwen 模型）：
#   venv\Scripts\python -m uvicorn server:app --port 8000
#   venv\Scripts\python scripts\test_coalesce.py
# ============================================================

import asyncio
import json
import struct
import sys
import wave
from pathlib import Path

import websockets

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from voice_asr import BYTES_PER_MS, SAMPLE_RATE  # noqa: E402

WS_URL = "ws://localhost:8000/ws/audio"
CHUNK_BYTES = 320 * BYTES_PER_MS
CLIP = ROOT / "samples/tts/03_HsiaoChen_p25.wav"  # 「就是那種，明明已經很努力了…」較長，好切兩半


def pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (SAMPLE_RATE, 1, 2)
        return w.readframes(w.getnframes())


def sil(ms: int) -> bytes:
    n = ms * SAMPLE_RATE // 1000
    return struct.pack(f"<{n}h", *([0] * n))


def split_with_gap(clip: bytes, gap_ms: int) -> bytes:
    """把一段語音從中間切開、塞 gap_ms 靜音，尾巴補 3s 靜音。"""
    half = (len(clip) // 2) & ~1  # 對齊 2 bytes
    return sil(600) + clip[:half] + sil(gap_ms) + clip[half:] + sil(3000)


async def send_stream(stream: bytes) -> dict:
    counts = {"transcript": 0, "reply_done": 0, "asr_empty": 0}
    async with websockets.connect(WS_URL, max_size=None) as ws:
        async def sender():
            for off in range(0, len(stream), CHUNK_BYTES):
                await ws.send(stream[off:off + CHUNK_BYTES])
                await asyncio.sleep(0.32)  # 真實時間速率，續句合併靠 audio-time 靜音

        task = asyncio.create_task(sender())
        try:
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
                t = msg.get("type")
                if t in counts:
                    counts[t] += 1
                    if t == "transcript":
                        print(f"    transcript: {msg['text'][:30]!r}")
                if task.done() and counts["transcript"] >= 2 and \
                        counts["reply_done"] + counts["asr_empty"] >= 1:
                    # 再等一下看有沒有第二個 reply_done
                    await asyncio.sleep(6)
                    while True:
                        try:
                            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=0.5))
                        except asyncio.TimeoutError:
                            break
                        if msg.get("type") in counts:
                            counts[msg["type"]] += 1
                    break
        except asyncio.TimeoutError:
            pass
    return counts


async def main() -> None:
    if not CLIP.exists():
        sys.exit("缺 samples/tts/*.wav；先跑 scripts\\gen_tts_samples.py")
    clip = pcm(CLIP)

    print("A. 中間停頓 ~1.2s（預期 2 transcript / 1 reply_done — 併起來回一次）")
    a = await send_stream(split_with_gap(clip, 1200))
    print(f"   → {a}")
    a_ok = a["transcript"] >= 2 and a["reply_done"] == 1

    print("\nB. 中間停頓 ~3s（預期 2 transcript / 2 reply_done — 各自回）")
    b = await send_stream(split_with_gap(clip, 3000))
    print(f"   → {b}")
    b_ok = b["transcript"] >= 2 and b["reply_done"] == 2

    print("\n" + ("PASS" if a_ok and b_ok else "FAIL"))
    sys.exit(0 if a_ok and b_ok else 1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (ConnectionRefusedError, OSError) as e:
        sys.exit(f"連不上 {WS_URL}，先啟動後端。({e})")
