# TTS 輸出串流規格

imood 語音模組（CosyVoice TTS）目前 output streaming 的音訊格式，供 JoyGen audio2motion 對接前確認。

- **Author**：映潔（語音模組）
- **For**：品靜（JoyGen）
- **Date**：2026-09-11
- **Status**：Prototype，CosyVoice2-0.5B + vLLM

---

## 一眼看完

| 項目 | 值 |
|---|---|
| Sample rate | 16000 Hz |
| Channels | 1（mono） |
| Sample format | PCM16 signed, little-endian |
| Container | 無 — 純 raw samples，沒有 WAV header |
| Chunk size | 10,240 bytes = 5,120 samples = 320 ms |
| Last chunk | 可能 < 10,240 bytes（餘數尾巴，未補零） |
| Pacing | 非 real-time — 跟著模型合成速度到達，不是固定節奏 |

---

## chunk 大小為什麼是 320 ms

切成 320 ms 不是隨便挑的數字——它是刻意對齊 JoyGen diffusion decoder 的 **8-frame batch（25fps）** 算出來的，兩邊一個 chunk / 一個 batch 剛好同步：

```
TTS 音訊 chunk  ├──────────────────────────────────────────┤
                        320 ms · 5,120 samples · 10,240 bytes（int16 LE）

JoyGen 視訊 batch (25fps)
                ├───┬───┬───┬───┬───┬───┬───┬───┤
                 F1  F2  F3  F4  F5  F6  F7  F8
                        8 frames × 40 ms = 320 ms
```

一個 TTS 音訊 chunk 的時長，剛好等於一個 diffusion decoder batch 的時長。

---

## 第 1 層：TTS service HTTP — `POST /synthesize`

獨立的 FastAPI 服務（`tts_service.py`），跟 `server.py` 是兩個 process。**建議 JoyGen 從這一層接**——如果 audio2motion 是 server 端程式，直接拿 raw PCM，不用多一層 base64/JSON。

| 項目 | 值 |
|---|---|
| Request | `POST http://<host>:8001/synthesize`，body `{"text": "..."}` |
| Response | `Content-Type: application/octet-stream`，HTTP chunked transfer |
| Response body | raw PCM bytes，逐塊送出（10,240 bytes / 塊，最後一塊可能較短） |
| 失敗 / 空字串 | 回 200，空 stream（0 bytes） |
| 健康檢查 | `GET /health` → `{"status","model_loaded","backend"}` |

> **⏱ chunk 到達節奏跟真實時間無關**，是模型合成多快就送多快，不是每 320ms 準時吐一塊。目前後端 CosyVoice2-0.5B + vLLM（WSL2 GPU）RTF ≈ 0.24×（比即時快），首塊延遲約 1.0s；純 CPU 環境量測過 RTF ≈ 4×（比即時慢）。接收端要留 buffer 吸收這個落差。

---

## 第 2 層：前端 WebSocket — `/ws/audio`

目前 demo 前端在用的路徑（`server.py`）。LLM 回覆**整段**文字生成完（`reply_done`）才觸發合成——還不是逐句 streaming。訊息是 **JSON text frame**，不是 binary frame。

| Field | Type | 說明 |
|---|---|---|
| `type` | string | `"audio_delta"` / `"audio_done"` / `"error"` |
| `audio` | string | base64。解碼後即第 1 層那串 raw PCM，切塊方式相同（10,240 bytes / 塊） |
| `sample_rate` | int | 固定 `16000` |
| `seq` | int | 從 1 開始遞增，每個 `audio_delta` +1 |

Message sequence：

```jsonc
{"type":"audio_delta","audio":"<base64 PCM>","sample_rate":16000,"seq":1}
{"type":"audio_delta","audio":"<base64 PCM>","sample_rate":16000,"seq":2}
...
{"type":"audio_done"}

// 合成失敗時（不影響已送出的文字回覆）：
{"type":"error","error":"語音合成暫時無法使用"}
```

---

## 請品靜幫忙確認

1. **從哪一層接？** 建議走第 1 層（`/synthesize` raw octet-stream）——如果 audio2motion 跑在 server 端。第 2 層是為瀏覽器前端設計的，多了 base64 + JSON 開銷。
2. **最後一塊不足 320 ms 怎麼處理？** 補零、丟棄、還是合併進前一塊？目前 `tts_service.py` 不會補零，原樣送出。
3. **（放未來優化）整句合成 vs 逐句 streaming**：現在是等 LLM 整段回覆生成完才開始合成。如果 JoyGen 需要更早拿到第一塊，語音模組這邊要改成逐句合成，請提出需求時程。
4. **正式部署的 host / port**：TTS service 目前跑在 WSL2（CosyVoice2-0.5B + vLLM），開發環境是 `server.py` 打 `localhost:8001`。JoyGen 端要接的正式位址待確認。
5. **文字繁轉簡**：合成前文字會先經 OpenCC（t2s）轉簡體，只影響發音、不影響音訊格式；如果 JoyGen 有做文字/字幕對齊需要知道這件事。

---

對應程式碼：`tts_service.py`、`tts_client.py`、`server.py`（`_stream_tts_to_ws()`）、`docs/tts-prototype-notes.md`、`docs/streaming-architecture-analysis.md`
