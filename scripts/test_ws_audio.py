# ============================================================
# /ws/audio 回歸測試腳本
#
# 不需要真麥克風，純粹驗證後端的格式檢查邏輯有沒有壞掉：
#   1. 送一個合法的 320ms / 16kHz / mono / 16-bit PCM chunk
#      （5120 個 int16 樣本 = 10240 bytes），預期收到
#      {"ack": 1, "chunk_ms": 320.0, "total_bytes": 10240}
#   2. 送一個長度不是偶數（非 16-bit 整數倍）的異常 chunk，
#      預期收到 {"error": "..."}
#
# 用法：
#   source venv/bin/activate
#   uvicorn server:app --host 0.0.0.0 --port 8000 &
#   python3 scripts/test_ws_audio.py
# ============================================================

import asyncio
import json
import struct
import sys

import websockets

WS_URL = "ws://localhost:8000/ws/audio"
PCM_SAMPLE_RATE = 16000
CHUNK_MS = 320
CHUNK_SAMPLES = PCM_SAMPLE_RATE * CHUNK_MS // 1000  # 5120


async def main():
    async with websockets.connect(WS_URL) as ws:
        # 1. 合法 chunk：320ms 靜音
        chunk = struct.pack(f"<{CHUNK_SAMPLES}h", *([0] * CHUNK_SAMPLES))
        await ws.send(chunk)
        resp = json.loads(await ws.recv())
        print("valid chunk ack:", resp)
        assert resp.get("ack") == 1, "預期第一包 ack 應該是 1"
        assert resp.get("chunk_ms") == 320.0, "預期 chunk_ms 應該是 320.0"
        assert resp.get("total_bytes") == len(chunk), "total_bytes 應該等於這包的 bytes 數"

        # 2. 異常 chunk：長度非 16-bit 整數倍
        bad_chunk = b"\x00\x01\x02"
        await ws.send(bad_chunk)
        resp2 = json.loads(await ws.recv())
        print("bad chunk resp:", resp2)
        assert "error" in resp2, "非法長度應該回傳 error"

    print("PASS")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (ConnectionRefusedError, OSError) as e:
        print(f"連不上 {WS_URL}，請先啟動後端：uvicorn server:app --port 8000")
        print(f"({e})")
        sys.exit(1)
