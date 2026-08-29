# imood.ai demo — 串接輕量對話模型

## 選型結論
先用 **Qwen2.5-1.5B-Instruct**（GGUF q4_k_m 量化版）：CPU 可跑、中文語意品質
在 demo 展示情境下明顯優於 0.5B，延遲也還在可接受範圍。等拿到 RTX 4090
之後，再換 MiniCPM-2B 或 ChatGLM3-6B 比較品質，只要改 `server.py` 裡的
`MODEL_PATH`，前端完全不用動。

## 啟動步驟

```bash
cd imood-backend
python -m venv venv
venv\Scripts\python -m pip install -r requirements.txt
#  Windows 上 llama-cpp-python 的 source build 會因路徑過長失敗，改用預編 wheel：
#  venv\Scripts\python -m pip install llama-cpp-python \
#      --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu

# 下載模型放到 models/qwen2.5-1.5b-instruct-q4_k_m.gguf
#   python -c "from huggingface_hub import hf_hub_download; import shutil; \
#     shutil.copy(hf_hub_download('Qwen/Qwen2.5-1.5B-Instruct-GGUF','qwen2.5-1.5b-instruct-q4_k_m.gguf'), \
#     'models/qwen2.5-1.5b-instruct-q4_k_m.gguf')"

venv\Scripts\python -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

`server.py` 啟動時會載入 Qwen（llama.cpp）**與** faster-whisper `small`
（voice-only ASR 用，第一次跑會自動下載 ~480MB 模型到 HF 快取）。

啟動後，直接用瀏覽器打開 `demo-imood-dashboard.html` 即可（它會呼叫
`http://localhost:8000/api/chat/stream` 做逐字 streaming 顯示，連不上時
自動退回 `http://localhost:8000/api/chat` 非 streaming 版本）。若你的
後端跑在別台機器或別的 port，記得把 HTML 裡的 `CHAT_STREAM_URL` /
`CHAT_API_URL` 改掉。

## 麥克風／voice-only 語音輸入
（2026-08-29 決定先做 voice-only，text2voice 暫緩。ASR→LLM 端到端已跑通，
細節見 `docs/asr-41-results.md`、`docs/asr-42-vad-plan.md`）

Sidebar 的「🎤 啟用語音輸入（voice-only）」按鈕會：
1. `getUserMedia()` 取得麥克風權限，畫音量條。
2. 用 `AudioWorklet`（`pcm16-downsampler`）即時把麥克風原生取樣率
   downsample 成 **16kHz / mono / 16-bit PCM**，每 **320ms** packing 成一個
   chunk，透過 WebSocket 送到後端 `/ws/audio`。

後端 `/ws/audio`（`server.py` + `voice_asr.py`）：

```
chunk → Endpointer 累積 + VAD 斷句（webrtcvad + 能量門檻，句尾靜音 900ms）
      → faster-whisper small 辨識 → transcript
      → 續句合併（等 1s 靜音看有沒有續句，有就併起來）
      → llm_stream()（跟 /api/chat/stream 共用）→ reply_delta… → reply_done
```

回傳的 JSON 訊息都有 `type`：`ack` / `asr_start` / `asr_empty` / `transcript` /
`reply_delta` / `reply_done` / `error`（前端 `handleVoiceMessage()` 處理，
transcript → user 訊息、reply_delta → avatar 逐字回覆，跟打字模式共用
`appendMessage` / `setEmotion`）。

**JoyGen 對接**：品靜 8/29 確認 JoyGen audio2motion 吃的是 **LLM 回覆的 TTS
音訊**（讓 avatar 講出回覆），不是使用者輸入的麥克風 PCM。所以 `/ws/audio`
的 PCM 純 ASR 用，JoyGen 對接點在未來 text2voice 那條路。人臉影片輸出
（UDP/MPEG-TS）等品靜那邊做完，`avatar-frame` 的 `attachRemoteStream()`
介面先保留。

**待補**：真人**對話**語音的斷句準度 + VAD 參數定案（見 `docs/asr-todo.md` 4.5）。

## JoyGen video track 對接點
`avatar-frame` 裡已經放了一個預設 `display:none` 的 `<video id="avatar-video">`，
等 WebRTC 談好、`pc.ontrack` 拿到 remote stream 後呼叫
`attachRemoteStream(stream)`（定義在 HTML 的 `<script>` 裡）即可自動切換
成播放 JoyGen 的畫面，蓋掉目前的 SVG 假臉。

## 之後要接情緒分類（BERT）時
`detectEmotion(text)` 目前還是關鍵字假規則，等君榮那邊的 BERT 模型好了，
建議比照 `callDialogueModel` 的做法，改成呼叫 `/api/emotion` 這種新
endpoint，回傳 `joy` / `anger` / `sorrow` / `calm` 其中一個字串即可，
前端的 `setEmotion()` 不用改。
