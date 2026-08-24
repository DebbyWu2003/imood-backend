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

## 麥克風骨架
Sidebar 有個「🎤 啟用麥克風」按鈕，目前只會呼叫 `getUserMedia()` 並畫
音量條，**不會**送出任何 WebRTC track，純粹先驗證瀏覽器權限流程。等跟
JoyGen 那邊對齊輸入格式（voice-only / text2voice、sample rate 等）後，
再把 `enableMic()` 裡拿到的 `micStream` 接進 `RTCPeerConnection.addTrack()`。

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
