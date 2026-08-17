# ============================================================
# imood.ai 後端 — 用 llama.cpp 跑 Qwen2.5-1.5B-Instruct
#
# 用法:
#   1. pip install -r requirements.txt
#   2. 到 Hugging Face 下載 GGUF 量化版模型:
#        搜尋 "Qwen2.5-1.5B-Instruct-GGUF"，抓 q4_k_m 這個等級
#        放到 ./models/qwen2.5-1.5b-instruct-q4_k_m.gguf
#      (若想先用最輕量版本驗證串接，也可以先抓 0.5B 版本，
#       改下面 MODEL_PATH 即可，介面完全不用動)
#   3. uvicorn server:app --host 0.0.0.0 --port 8000 --reload
#
# 之後拿到 RTX 4090，若想換更大的模型(如 MiniCPM-2B、ChatGLM3-6B)，
# 只要換 MODEL_PATH，或改用 transformers 版本的載入方式即可，
# /api/chat 這個介面不需要變。
# ============================================================

from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from llama_cpp import Llama
import time

MODEL_PATH = "./models/qwen2.5-1.5b-instruct-q4_k_m.gguf"
N_CTX = 2048
N_THREADS = 8  # 依機器 CPU 核心數調整

SYSTEM_PROMPT = (
    "你是 imood，一個溫暖、有同理心的陪伴型虛擬人。"
    "請一律使用繁體中文回覆，語氣自然、簡短，避免長篇說教。"
)

app = FastAPI(title="imood.ai chat backend")

# 開發階段先全開，正式上線後應該改成白名單網域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

llm: Optional[Llama] = None


@app.on_event("startup")
def load_model():
    global llm
    llm = Llama(
        model_path=MODEL_PATH,
        n_ctx=N_CTX,
        n_threads=N_THREADS,
        verbose=False,
    )


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    latency_ms: int


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if llm is None:
        raise HTTPException(status_code=503, detail="模型尚未載入完成")

    text = req.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="訊息不可為空")

    start = time.time()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    result = llm.create_chat_completion(
        messages=messages,
        max_tokens=200,
        temperature=0.7,
    )
    reply = result["choices"][0]["message"]["content"].strip()
    latency_ms = int((time.time() - start) * 1000)

    return ChatResponse(reply=reply, latency_ms=latency_ms)


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": llm is not None}
