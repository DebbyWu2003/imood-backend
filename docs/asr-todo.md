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

## 1. 現況（已完成，不用重做）

- **2026-08-29 團隊決議**：先做 **voice-only**（text2voice / streaming TTS
  選型暫緩）；JoyGen 輸出端維持 **UDP/MPEG-TS**。
- 前端 `demo-imood-dashboard.html`：`enableMic()` 已用 `AudioWorklet`
  即時把麥克風 downsample 成 **16kHz / mono / 16-bit PCM**，每 **320ms**
  （對齊 JoyGen diffusion decoder 的 8-frame batch @25fps）送一個 chunk，
  透過 WebSocket 送到後端 `/ws/audio`。
- 後端 `server.py`：`/ws/audio` 會驗證 chunk 格式、回
  `{ack, chunk_ms, total_bytes}`，但**目前只是回 ack，不會做任何辨識或
  轉送**，程式碼裡有 `# TODO forward to JoyGen` 的掛勾點。
- 回歸測試腳本：`scripts/test_ws_audio.py`（驗證 `/ws/audio` 的格式檢查
  邏輯沒壞掉，不需要真麥克風）。

**現在的行為**：對著麥克風講話，後端只會印 ack，**不會有任何回應**——這是
目前的已知缺口，也是這份待辦要補的部分。

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

## 3. 環境搬遷 checklist（換機器第一步）

- [ ] clone / 複製整個 repo（含 `models/` 目錄，`qwen2.5-1.5b-instruct-q4_k_m.gguf`
      約 1GB，注意不要漏掉）。
- [ ] 桌機建立新的 venv：`python3 -m venv venv && source venv/bin/activate`
- [ ] `pip install -r requirements.txt --break-system-packages`（跟現在一樣）
- [ ] `uvicorn server:app --host 0.0.0.0 --port 8000` 跑起來，確認
      `curl localhost:8000/health` 回 `{"status":"ok","model_loaded":true}`
- [ ] 瀏覽器開 `demo-imood-dashboard.html`，確認文字輸入模式、麥克風
      voice-only pipeline（連線 `/ws/audio`、看得到 ack）都跟筆電上一樣正常，
      再開始加 ASR，避免把環境問題跟新功能的 bug 混在一起 debug。
- [ ] 跑 `python3 scripts/test_ws_audio.py` 確認基礎回歸測試先過。
- [ ] 確認桌機 CPU 核心數／記憶體（`sysctl -n hw.ncpu` / `hw.memsize`，或
      Linux 用 `nproc` / `free -h`），ASR 模型大小選型會依這個調整。

## 4. ASR 實作步驟（依順序做）

### 4.1 選型與環境驗證（約 0.5 天）
- [ ] 安裝 **faster-whisper**（CTranslate2 後端，CPU int8 量化跑起來快，
      跟現有 llama.cpp 本地優先的路線一致）：
      `pip install faster-whisper`
- [ ] 下載 `small` 模型（中文優先驗證），寫一支獨立小腳本（不用進
      `server.py`），錄一段自己講話的 wav（16kHz/mono），跑一次辨識，
      確認：
      - 中文辨識品質可接受
      - 單次辨識延遲（幾秒的語音大概要算多久）
- [ ] 如果 `small` 品質不夠，再試 `base` 或 `medium`，記錄各自的延遲/
      品質權衡，決定要用哪個。

### 4.2 VAD 斷句邏輯（約 0.5–1 天）— 已完成 2026-08-29，見 docs/asr-42-vad-plan.md
- [x] 在 `/ws/audio` 裡把收到的 PCM chunk 累積進一個 buffer。
- [x] 靜音偵測：`webrtcvad`（aggressiveness 2）+ 自適應能量門檻，連續靜音
      700ms（起始值，待真人語音現場調）判定「這句話講完了」。
- [x] 觸發後把累積 buffer 丟去 faster-whisper 辨識（`voice_asr.Transcriber`）。
- [x] 清空 buffer、準備收下一句；太短的語句丟棄。
- [x] 離線 + 端到端 + 舊回歸測試都過（`scripts/test_endpointer.py`、
      `scripts/test_ws_audio_asr.py`、`scripts/test_ws_audio.py`）。
- [ ] 待補：真人語音下的斷句準度與 VAD 參數微調。

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

### 4.4 前端串接（約 0.5 天）— 已完成 2026-08-29
- [x] `demo-imood-dashboard.html` 的 WS `onmessage` → `handleVoiceMessage()`，
      處理 ack / asr_start / asr_empty / transcript / reply_delta / reply_done / error。
- [x] transcript 進來 → `appendMessage('user', text)` + `setEmotion(detectEmotion(text))`。
- [x] reply_delta → 逐段 append 進新的 avatar message（`voiceReplyBodyEl`），
      reply_done 時 `setEmotion(detectEmotion(整段回覆))`。跟打字模式共用
      `appendMessage` / `setEmotion`。
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
      900ms 仍沒完全消除（FLEURS 長句還有 >900ms 停頓）。
- [ ] **待做**：真人**對話**語音（自然停頓 / 口語 / 語助詞 / 噪音）測斷句準度，
      FLEURS 朗讀代替不了。依此現場調 VAD 參數並定案（或加「等待續句」機制）。

**總工作量估計：約 2.5–3.5 天**（跟筆電上討論時給的估計一致，只是換到
桌機上算力更充裕，實際跑起來應該更快）。

## 5. 刻意不做的事（先不要展開）

- **真 streaming ASR**（逐字即時字幕）：需要專門的 streaming ASR 模型
  （如 FunASR 的 Paraformer-streaming），複雜度高很多，這階段先不碰。
- **text2voice / streaming TTS**：這次會議已決定暫緩，等 voice-only
  端到端跑通再撿回來。
- **JoyGen 對接（人臉影片）**：品靜那邊還在實作 streaming endpoint，
  `/ws/audio` 裡的 `# TODO forward to JoyGen` 掛勾點先留著，不用主動去等。

## 6. 還沒拍板、要主動找學長確認的風險

1. **音訊 buffer 的分工**：加了 ASR 之後，`/ws/audio` 收到的 PCM 會被拿去
   做語音辨識；但將來 JoyGen 側也需要吃同一份音訊來驅動嘴型（audio2motion）。
   兩邊要不要共用同一份 buffer？要不要分流成兩條 pipeline？這個沒問清楚
   會影響 4.2 的實作方式，**建議動工前先確認**。
2. **VAD 靜音閾值**：抓多長算「講完一句話」，這會影響使用者體驗（太短切斷
   語句、太長等太久），沒有標準答案，需要現場試講調整，記錄下最後選定的
   數值跟理由。
3. **ASR 模型大小 vs 延遲**：桌機算力比筆電好，但還是要實測 small/base/
   medium 在真實中文語句上的延遲跟準確度，才能決定要不要換更大的模型。

## 7. 完成後要更新的文件

- [ ] `docs/streaming-architecture-analysis.md` 第 6 節：把這次的 ASR
      工作項目從「待辦」搬到「已完成」，補上實測的延遲數據。
- [ ] `README.md`：補上 ASR 啟動方式（要不要額外下載模型、環境變數等）。
- [ ] 這份文件（`docs/asr-todo.md`）：完成後可以整份標記為 done 或直接
      刪除，內容併回 `streaming-architecture-analysis.md`。
