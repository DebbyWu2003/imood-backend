# imood.ai demo — 串接輕量對話模型

## 選型結論
先用 **Qwen2.5-1.5B-Instruct**（GGUF q4_k_m 量化版）：CPU 可跑、中文語意品質
在 demo 展示情境下明顯優於 0.5B，延遲也還在可接受範圍。等拿到 RTX 4090
之後，再換 MiniCPM-2B 或 ChatGLM3-6B 比較品質，只要改 `server.py` 裡的
`MODEL_PATH`，前端完全不用動。

## 啟動步驟

```bash
cd imood-backend
pip install -r requirements.txt --break-system-packages

# 下載模型（Hugging Face 搜尋 "Qwen2.5-1.5B-Instruct-GGUF"，抓 q4_k_m）
mkdir -p models
# 把下載好的 .gguf 檔放到 models/qwen2.5-1.5b-instruct-q4_k_m.gguf

uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

啟動後，直接用瀏覽器打開 `demo-imood-dashboard.html` 即可（它會呼叫
`http://localhost:8000/api/chat/stream` 做逐字 streaming 顯示，連不上時
自動退回 `http://localhost:8000/api/chat` 非 streaming 版本）。若你的
後端跑在別台機器或別的 port，記得把 HTML 裡的 `CHAT_STREAM_URL` /
`CHAT_API_URL` 改掉。

## 麥克風／voice-only 語音輸入
（2026-08-29 更新：已與學長及組員開會決定先做 voice-only，text2voice 暫緩）

Sidebar 的「🎤 啟用語音輸入（voice-only）」按鈕會：
1. `getUserMedia()` 取得麥克風權限，畫音量條。
2. 用 `AudioWorklet`（`pcm16-downsampler`）即時把麥克風原生取樣率
   downsample 成 **16kHz / mono / 16-bit PCM**（JoyGen/audio2motion 要求
   的格式），每 **320ms**（對齊 JoyGen diffusion decoder 的 8-frame batch
   @25fps）packing 成一個 chunk。
3. 透過 WebSocket 把每個 chunk 送到後端 `/ws/audio`（見 `server.py`）。

後端目前只會驗證格式、回 ack，**還沒有真的轉送給 JoyGen**——JoyGen 側的
audio2motion streaming endpoint 還在品靜那邊實作中，`server.py` 裡的
`/ws/audio` 已經留了 `# TODO forward to JoyGen` 的掛勾點，之後串接時只要
補上轉送邏輯，前端這條路徑不用改。JoyGen 人臉影片輸出（UDP/MPEG-TS）也是
等品靜那邊實作完成才能對接，`avatar-frame` 的 `attachRemoteStream()` 介面
先保留、暫不動工。

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
