# ASR 待辦事項 — 讓「講完話 → 有回應」跑起來

負責人：映潔（語音模組 / 前端 portal）
建立日期：2026-08-29
用途：把專案搬到桌機後，接續完成 voice-only 語音輸入的 ASR 那段。這份文件
是給「換一台機器繼續做」用的交接清單，寫清楚現況、要做什麼、順序、以及
還沒拍板的風險點。

---

## 0. 先讀這些，建立背景

1. `docs/streaming-architecture-analysis.md`（尤其第 2、6 節）——這次任務的
   完整架構背景、跟品靜（JoyGen）之間的分工。
2. `docs/buffering_reserach_20260819.md` ——JoyGen 側的 buffering 可行性
   研究，音訊格式（16kHz/mono/16-bit PCM）跟切塊對齊 25fps 的限制都是從
   這份文件來的。
3. `README.md` 的「麥克風／voice-only 語音輸入」章節——目前已完成的部分。

## 1. 現況

> **2026-08-29 更新**：這份待辦的 4.1–4.4 已完成、4.5 首輪已跑，voice-only
> 的「講完話 → 有回應」整條端到端在本機跑通了。下面第 4 節每個小節有勾選
> 狀態與實作對照；細節見 `docs/asr-41-results.md`（選型）與
> `docs/asr-42-vad-plan.md`（VAD / 續句合併 / 延遲量測）。**只剩 4.5 的真人
> 對話語音測試**。以下保留原始交接內容當歷程。

- **2026-08-29 團隊決議**：先做 **voice-only**（text2voice / streaming TTS
  選型暫緩）；JoyGen 輸出端維持 **UDP/MPEG-TS**。
- 前端 `demo-imood-dashboard.html`：`enableMic()` 已用 `AudioWorklet`
  即時把麥克風 downsample 成 **16kHz / mono / 16-bit PCM**，每 **320ms**
  （對齊 JoyGen diffusion decoder 的 8-frame batch @25fps）送一個 chunk，
  透過 WebSocket 送到後端 `/ws/audio`。
- 後端 `server.py`：`/ws/audio` ~~只回 ack~~ **（已完成）** 現在會累積 chunk
  → VAD 斷句 → faster-whisper 辨識 → 續句合併 → Qwen 回覆 streaming，透過
  WebSocket 訊息送回前端。原本的 `# TODO forward to JoyGen` 掛勾點已移除
  （品靜 8/29 確認 JoyGen 吃的是 LLM 回覆的 TTS 音訊，不是使用者輸入 PCM）。
- 回歸測試腳本：`scripts/test_ws_audio.py`（驗證 `/ws/audio` 的格式檢查
  邏輯沒壞掉，不需要真麥克風）。

## 2. 目標

讓「使用者講話 → 系統真的有回應」跑起來，先做**輪流式**（講完一句話、停頓
一下才觸發回應），不是逐字即時字幕的真 streaming ASR。理由跟權衡見第 5 節
「不做的事」。

```
麥克風 PCM chunk（已完成）
        ↓
[新增] /ws/audio 累積 buffer + 靜音偵測（VAD）判斷「這句話講完了」
        ↓
[新增] ASR：整段語音 → 文字
        ↓
[複用] 現有 /api/chat 的 LLM 邏輯：文字 → Qwen2.5 回覆（streaming）
        ↓
[新增] 把 transcript + LLM 回覆用 WebSocket 訊息送回前端
        ↓
[複用] 前端 appendMessage() / setEmotion()，跟現在打字模式共用同一套顯示邏輯
```

## 3. 環境搬遷 checklist（換機器第一步）— 已完成（桌機是 Windows，指令有出入）

- [x] repo + `models/qwen2.5-1.5b-instruct-q4_k_m.gguf`（1.1GB，用
      `huggingface_hub.hf_hub_download('Qwen/Qwen2.5-1.5B-Instruct-GGUF', ...)` 抓）。
- [x] venv：`python -m venv venv`（Windows，`venv\Scripts\python`；不用 activate）。
- [x] `venv\Scripts\python -m pip install -r requirements.txt`
      （`llama-cpp-python` 用 `--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu`
      的預編 wheel，Windows source build 會因路徑過長失敗）。
      評估/測試用的額外依賴：`pip install -r requirements-asr.txt`。
- [x] `uvicorn server:app --port 8000` 起得來，`/health` 回
      `{"status":"ok","model_loaded":true}`。
- [x] 瀏覽器開 `demo-imood-dashboard.html`，文字模式 + voice-only pipeline 正常。
- [x] `scripts/test_ws_audio.py` 過。
- [x] 桌機規格：12 cores / 64 GB / ffmpeg 7.1.1 在 PATH（見 asr-41-results.md）。

## 4. ASR 實作步驟（依順序做）

### 4.1 選型與環境驗證（約 0.5 天）— 已完成 2026-08-29，見 docs/asr-41-results.md
- [x] 裝 **faster-whisper** 1.2.1（ctranslate2 4.8.1，CPU int8）。
- [x] `scripts/asr_demo.py`（單檔）+ `scripts/asr_eval.py`（批次算 CER）。
      遠端連線無法錄音，改用 `scripts/gen_tts_samples.py`（edge-tts 合成）+
      `scripts/fetch_fleurs_zh.py`（FLEURS 真人朗讀）當測試語料。
- [x] small/base/medium 都跑過：**選 `small`**。口語 CER 1.6%、FLEURS 真人
      朗讀 CER 6.2%；一句辨識 RTF ~0.2–0.5x。`base` 明顯差；`medium` 難詞域
      較好但慢 ~2.5x，留作 fallback。
- [ ] 待補：真人**對話**語音（非朗讀）再驗一次品質。

### 4.2 VAD 斷句邏輯（約 0.5–1 天）— 已完成 2026-08-29，見 docs/asr-42-vad-plan.md
- [x] `/ws/audio` 裡把 PCM chunk 累積進 buffer（`voice_asr.Endpointer`，
      buffer 純 ASR 用，不跟 JoyGen 共用）。
- [x] 靜音偵測：`webrtcvad`（aggressiveness 2）+ 自適應能量門檻，連續靜音
      **900ms**（起始 700，量測後調到 900，見 asr-42-vad-plan 第 7 節）判定句尾。
- [x] 觸發後把累積 buffer 丟 faster-whisper（`voice_asr.Transcriber`）；
      清空 buffer；太短的語句丟棄（回 `asr_empty`）。
- [x] 續句合併：句尾判定後不馬上丟 LLM，先等 1s 靜音看有沒有續句（見 4.5）。
- [x] 離線 + 端到端 + 舊回歸測試都過（`scripts/test_endpointer.py`、
      `scripts/test_coalesce.py`、`scripts/test_ws_audio_asr.py`、
      `scripts/test_ws_audio.py`）。

### 4.3 接上既有 LLM streaming 邏輯（約 0.5–1 天）— 已完成 2026-08-29
- [x] ASR 出來的文字丟給 `llm_stream()`（跟 `/api/chat/stream` 同一個 helper）。
- [x] `/ws/audio` 送回 `transcript` → 一串 `reply_delta` → `reply_done`，
      所有 JSON 訊息都有 `type` 欄位（協定見下 + `server.py` docstring）。
- [x] 抽 `_build_messages()` / `llm_complete()` / `llm_stream()` 共用 helper，
      `/api/chat`、`/api/chat/stream`、`/ws/audio` 三處共用；SSE wire 格式沒變。
- [x] 同步 generator → async 的橋接（thread pool + queue），`_llm_lock` 序列化。
- [x] 端到端測試 `scripts/test_ws_audio_asr.py`：2 句 → 2 transcript → 2 回覆。

**`/ws/audio` 回傳訊息協定：**

| type | 欄位 | 時機 |
|---|---|---|
| `ack` | `ack`, `chunk_ms`, `total_bytes` | 每個 chunk |
| `asr_start` | `audio_ms` | 偵測到句尾靜音、開始辨識 |
| `asr_empty` | — | 有聲音但辨識不出內容 |
| `transcript` | `text`, `audio_ms`, `asr_latency_ms` | 一句話辨識完 |
| `reply_delta` | `delta` | LLM 回覆逐段（比照 SSE 的 `delta`） |
| `reply_done` | `latency_ms` | LLM 回覆結束 |
| `error` | `error` | 任一步出錯 |

> `transcript` 送出後不會馬上有 `reply_delta`——後端會先等續句合併窗
> （`VOICE_COALESCE_MS`，見 4.5 + asr-42-vad-plan 第 8 節），可能再來一個
> `transcript`，最後才一次 `reply_delta`…`reply_done`。

### 4.4 前端串接（約 0.5 天）— 已完成 2026-08-29
- [x] `demo-imood-dashboard.html` 的 WS `onmessage` → `handleVoiceMessage()`，
      處理 ack / asr_start / asr_empty / transcript / reply_delta / reply_done / error。
- [x] transcript 進來 → `appendMessage('user', text)` + `setEmotion(detectEmotion(text))`
      （表情依使用者的話，跟打字模式一致——不在 reply_done 用中性回覆內容蓋回 calm）；
      **不建 avatar 泡泡**（可能還有續句）。
- [x] 第一個 reply_delta 才建 avatar 泡泡（`voiceReplyBodyEl`），之後逐段 append。
      多段 transcript → 一個回覆泡泡。跟打字模式共用 `appendMessage` / `setEmotion`。
- [x] 頂端狀態膠囊 `setStatus()`：聆聽中 / 辨識中… / 回覆中…（`state-busy`
      橘色脈動）。`enableMic` / `disableMic` 也連動。
- [x] 瀏覽器實測：真的連 `/ws/audio` 串 TTS 語音 → 出現 user 訊息 + 逐字回覆
      + 表情切換；JS 過 `node --check`。

### 4.5 真人測試 + 量測延遲（約 0.5 天）— 首輪已跑（FLEURS 朗讀），見 asr-42-vad-plan 第 7 節
- [x] `scripts/measure_e2e.py`：把語料以真實時間速率串進 `/ws/audio`，用回傳
      訊息時間戳拆 VAD / ASR / LLM 各段延遲。
- [x] 首輪數據（FLEURS 15 句真人朗讀，`end_silence_ms` 900ms）：VAD ~1000ms、
      ASR ~2050ms (RTF 0.34–0.40x)、LLM 首字 ~155ms / 全程 ~1900ms、
      **講完→回覆完 中位 5.0s**（~5–6s 切段；casual 短句估 ~3–3.5s）。
- [x] 瓶頸：ASR 與 LLM 全程各佔一半，VAD 最小。槓桿見文件第 7 節。
- [x] 斷句：700ms → 900ms，切段從 8/15 降到 5/15，端到端沒變差；已改預設。
- [x] **續句合併**（asr-42-vad-plan 第 8 節）：被 VAD 切成兩段時，等
      `VOICE_COALESCE_MS`(1000ms) 靜音看有沒有續句，有就把 transcript 併起來
      只丟一次 LLM。`scripts/test_coalesce.py` 驗過（1.2s 停頓→1 回覆、3s→2 回覆）。
- [ ] **待做**：真人**對話**語音（自然停頓 / 口語 / 語助詞 / 噪音）測斷句準度 +
      續句合併的 900/1000 這組數字合不合適。可考慮把 end_silence 調回短一點
      （transcript 更快出現）、加「結尾標點 → 跳過等待」啟發式。

**總工作量估計：約 2.5–3.5 天**（跟筆電上討論時給的估計一致，只是換到
桌機上算力更充裕，實際跑起來應該更快）。

## 5. 刻意不做的事（先不要展開）

- **真 streaming ASR**（逐字即時字幕）：需要專門的 streaming ASR 模型
  （如 FunASR 的 Paraformer-streaming），複雜度高很多，這階段先不碰。
- **text2voice / streaming TTS**：這次會議已決定暫緩，等 voice-only
  端到端跑通再撿回來。
- **JoyGen 對接（人臉影片）**：品靜那邊還在實作 streaming endpoint。JoyGen
  吃的是 **LLM 回覆的 TTS 音訊**（8/29 確認），所以對接點在未來的 TTS 那條路，
  不在 `/ws/audio`（原本放在這裡的 `# TODO forward to JoyGen` 已移除）。
- **barge-in / 雙講**：使用者在 avatar 回話時插話打斷，第一版不處理。

## 6. 風險點狀態

1. ~~**音訊 buffer 的分工**~~ **已解決**：品靜 8/29 確認 JoyGen audio2motion
   吃的是 LLM 回覆的 TTS 音訊，不是使用者輸入 PCM → `/ws/audio` 的 buffer
   純 ASR 用，沒有共用問題。
2. **VAD 靜音閾值** — 進行中：起始 700 → 量測後 900ms + 續句合併（1000ms）。
   還要用**真人對話語音**現場調、定案（見 4.5 待做）。
3. ~~**ASR 模型大小 vs 延遲**~~ **已解決**：small/base/medium 都實測過，選
   `small`（見 4.1 / asr-41-results.md）。medium 留作 fallback。

## 7. 完成後要更新的文件

- [x] `docs/streaming-architecture-analysis.md` 第 6 節：ASR 工作項目已搬到
      「已完成」（commit 270c513）。端到端實測延遲見 asr-42-vad-plan 第 7 節。
- [x] `README.md`：voice-only 章節已更新成「ASR → LLM 端到端」，補了 ASR
      啟動方式（額外依賴、模型下載）。
- [ ] 這份文件：4.5 真人對話語音測試做完後，可整份標記 done 或併回
      `streaming-architecture-analysis.md`。
