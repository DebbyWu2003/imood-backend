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
`http://localhost:8000/api/chat`）。若你的後端跑在別台機器或別的
port，記得把 HTML 裡的 `CHAT_API_URL` 改掉。

## 之後要接情緒分類（BERT）時
`detectEmotion(text)` 目前還是關鍵字假規則，等君榮那邊的 BERT 模型好了，
建議比照 `callDialogueModel` 的做法，改成呼叫 `/api/emotion` 這種新
endpoint，回傳 `joy` / `anger` / `sorrow` / `calm` 其中一個字串即可，
前端的 `setEmotion()` 不用改。
