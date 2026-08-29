# ============================================================
# 4.5 延遲量測 —— 用 FLEURS 真人語料先跑一次
#
# 對每個 wav 組成「靜音 + 語句 + 靜音尾巴」，以「真實時間速率」（每 320ms
# 一個 chunk）串進 /ws/audio，用回傳訊息的時間戳拆解各段延遲：
#
#   speech_end ──(VAD 句尾判定)──▶ asr_start ──(ASR)──▶ transcript
#              ──(LLM 首字)──▶ 第一個 reply_delta ──(LLM 生成)──▶ reply_done
#
# 照 buffering_reserach_20260819.md 的規範：每個處理單位記 ms，最後取平均。
#
# 需要先啟動後端（要有 Qwen 模型）：
#   venv\Scripts\python -m uvicorn server:app --port 8000
# 然後：
#   venv\Scripts\python scripts\measure_e2e.py samples\fleurs\manifest.jsonl
#   venv\Scripts\python scripts\measure_e2e.py samples\fleurs\manifest.jsonl --limit 8 --fast
# ============================================================

import argparse
import asyncio
import json
import statistics
import struct
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import websockets

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from voice_asr import BYTES_PER_MS, SAMPLE_RATE  # noqa: E402

WS_URL = "ws://localhost:8000/ws/audio"
CHUNK_MS = 320
CHUNK_BYTES = CHUNK_MS * BYTES_PER_MS
LEAD_MS = 600
TAIL_MS = 1300  # > end_silence_ms(700) + 一個 chunk 的餘裕


def read_pcm(path: Path) -> bytes:
    # 用 soundfile 讀（FLEURS 的 wav 是 32-bit float，Python wave 讀不了）。
    # 注意 soundfile 對 float 檔請求 dtype='int16' 不會自動 scale，會直接截成 0，
    # 所以一律讀 float 再自己轉。
    data, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data[:, 0]
    if sr != SAMPLE_RATE:
        raise SystemExit(f"{path} 取樣率 {sr} != {SAMPLE_RATE}")
    # 修掉檔案頭尾的靜音，讓「speech_end」有明確位置（FLEURS 每檔尾巴長度不一）
    win = SAMPLE_RATE // 100  # 10ms
    energy = np.sqrt(np.convolve(data ** 2, np.ones(win) / win, mode="same"))
    voiced = np.where(energy > 0.01)[0]
    if len(voiced):
        data = data[max(0, voiced[0] - win): voiced[-1] + win]
    return (data * 32767.0).clip(-32768, 32767).astype("<i2").tobytes()


def silence(ms: int) -> bytes:
    n = ms * SAMPLE_RATE // 1000
    return struct.pack(f"<{n}h", *([0] * n))


def ms(a, b):
    return None if a is None or b is None else round((b - a) * 1000)


async def run_one(ws, pcm: bytes, realtime: bool) -> list:
    """
    送一句（靜音 + 語句 + 靜音尾巴），收集這句產生的所有 utterance。

    FLEURS 是朗讀，句中會有換氣停頓，一個 clip 可能被 VAD 切成 >1 個
    utterance。每個 utterance 都量 ASR / LLM；只有「最後一個」（asr_start
    發生在我送完語句之後）能對到 speech_end，量 VAD 句尾判定延遲 + 總延遲。
    """
    stream = silence(LEAD_MS) + pcm + silence(TAIL_MS)
    speech_end_byte = LEAD_MS * BYTES_PER_MS + len(pcm)

    events: list = []  # (wall, type, msg)
    stop = asyncio.Event()

    async def reader():
        try:
            async for raw in ws:
                msg = json.loads(raw)
                events.append((time.perf_counter(), msg.get("type"), msg))
        except asyncio.CancelledError:
            pass

    reader_task = asyncio.create_task(reader())

    speech_end_wall = None
    sent = 0
    for off in range(0, len(stream), CHUNK_BYTES):
        await ws.send(stream[off:off + CHUNK_BYTES])
        sent += CHUNK_BYTES
        if speech_end_wall is None and sent >= speech_end_byte:
            speech_end_wall = time.perf_counter()
        await asyncio.sleep(CHUNK_MS / 1000 if realtime else 0.01)

    # 等到「reply_done 數 == asr_start 數」且連續 3s 沒新訊息，或硬 timeout
    deadline = time.perf_counter() + 90
    while time.perf_counter() < deadline:
        await asyncio.sleep(0.5)
        starts = sum(1 for _, t, _ in events if t == "asr_start")
        dones = sum(1 for _, t, _ in events if t in ("reply_done", "asr_empty"))
        last = events[-1][0] if events else 0
        if starts >= 1 and dones >= starts and time.perf_counter() - last > 3:
            break
    reader_task.cancel()

    # 把 events 依 asr_start 切成一個個 utterance
    utts: list = []
    cur = None
    for wall, t, msg in events:
        if t == "asr_start":
            if cur:
                utts.append(cur)
            cur = {"asr_start": wall}
        elif cur is None:
            continue
        elif t == "transcript":
            cur["transcript"] = wall
            cur["text"] = msg.get("text", "")
            cur["audio_ms"] = msg.get("audio_ms")
            cur["asr_report_ms"] = msg.get("asr_latency_ms")
        elif t == "reply_delta" and "first_delta" not in cur:
            cur["first_delta"] = wall
        elif t == "reply_done":
            cur["reply_done"] = wall
            cur["llm_report_ms"] = msg.get("latency_ms")
        elif t == "asr_empty":
            cur["empty"] = True
    if cur:
        utts.append(cur)

    out = []
    for k, u in enumerate(utts):
        is_final = speech_end_wall is not None and u["asr_start"] > speech_end_wall
        out.append({
            "final": is_final,
            "empty": u.get("empty", False),
            "text": u.get("text", ""),
            "audio_ms": u.get("audio_ms"),
            "vad": ms(speech_end_wall, u["asr_start"]) if is_final else None,
            "asr": ms(u.get("asr_start"), u.get("transcript")),
            "ttft": ms(u.get("transcript"), u.get("first_delta")),
            "llm": ms(u.get("transcript"), u.get("reply_done")),
            "total": ms(speech_end_wall, u.get("reply_done")) if is_final else None,
        })
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--limit", type=int, default=0, help="只測前 N 句（0 = 全部）")
    ap.add_argument("--fast", action="store_true", help="不照真實時間送 chunk（VAD 判定延遲會失真，只看 ASR/LLM 時用）")
    args = ap.parse_args()

    rows = [json.loads(l) for l in args.manifest.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.limit:
        rows = rows[:args.limit]
    base = args.manifest.parent
    realtime = not args.fast

    print(f"送 {len(rows)} 句到 {WS_URL}（{'真實時間速率' if realtime else 'fast'}）\n")
    utts = []
    async with websockets.connect(WS_URL, max_size=None) as ws:
        for i, r in enumerate(rows):
            pcm = read_pcm(base / r["audio"])
            got = await run_one(ws, pcm, realtime)
            n = len([u for u in got if not u["empty"]])
            for u in got:
                if u["empty"]:
                    print(f"[{i+1:2}] · asr_empty")
                    continue
                utts.append(u)
                tag = "末句" if u["final"] else "句中"
                vad = f"{u['vad']:>4}" if u["vad"] is not None else "  - "
                total = f"{u['total']:>5}" if u["total"] is not None else "   - "
                print(f"[{i+1:2}] {tag} VAD {vad}  ASR {u['asr']:>5}  首字 {u['ttft']:>4}  "
                      f"LLM {u['llm']:>5}  | 講完→回覆完 {total} ms  «{u['text'][:20]}»")
            if n > 1:
                print(f"      （這句被 VAD 切成 {n} 段）")

    ok = [u for u in utts if u["asr"] is not None]
    if not ok:
        print("\n沒有成功的量測")
        sys.exit(1)

    def summarize(key, label, subset):
        vals = [x[key] for x in subset if x[key] is not None]
        if not vals:
            return
        print(f"  {label:<16} 平均 {statistics.mean(vals):6.0f}  中位 {statistics.median(vals):6.0f}  "
              f"最小 {min(vals):5.0f}  最大 {max(vals):5.0f}  (n={len(vals)})")

    finals = [u for u in ok if u["final"]]
    print(f"\n=== 彙總（ms）　utterance 共 {len(ok)} 個，其中末句 {len(finals)} 個 ===")
    summarize("vad", "VAD 句尾判定", finals)
    summarize("asr", "ASR 辨識", ok)
    summarize("ttft", "LLM 首字", ok)
    summarize("llm", "LLM 全程", ok)
    summarize("total", "講完→回覆完", finals)
    audio = statistics.mean([x["audio_ms"] for x in ok if x["audio_ms"]])
    asr = statistics.mean([x["asr"] for x in ok])
    print(f"\n  ASR RTF ≈ {asr / audio:.2f}x（平均切段音長 {audio:.0f}ms）")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (ConnectionRefusedError, OSError) as e:
        sys.exit(f"連不上 {WS_URL}，先啟動後端。({e})")
