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

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from llama_cpp import Llama
import json
import time

MODEL_PATH = "./models/qwen2.5-1.5b-instruct-q4_k_m.gguf"
N_CTX = 2048
N_THREADS = 8  # 依機器 CPU 核心數調整

# voice-only 輸入路徑：JoyGen/audio2motion 只吃 16kHz / 單聲道 / 16-bit PCM
# （8/25 品靜回覆，見 docs/streaming-architecture-analysis.md 第 2 節）
PCM_SAMPLE_RATE = 16000
PCM_SAMPLE_WIDTH_BYTES = 2  # 16-bit

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


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest):
    """
    SSE streaming 版本的 /api/chat。前端不能用 EventSource（那個只能發 GET），
    改用 fetch + ReadableStream 自己解析 "data: {...}\n\n" 這種格式。

    之後接 JoyGen text2voice 時，可以比照這支的做法：把這裡的
    `yield` 换成「把每個 delta 轉送給 JoyGen 的 streaming TTS endpoint」，
    介面（逐字 SSE chunk）不用變。
    """
    if llm is None:
        raise HTTPException(status_code=503, detail="模型尚未載入完成")

    text = req.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="訊息不可為空")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]

    def event_generator():
        start = time.time()
        stream = llm.create_chat_completion(
            messages=messages,
            max_tokens=200,
            temperature=0.7,
            stream=True,
        )
        for chunk in stream:
            delta = chunk["choices"][0].get("delta", {})
            piece = delta.get("content")
            if piece:
                yield f"data: {json.dumps({'delta': piece}, ensure_ascii=False)}\n\n"
        latency_ms = int((time.time() - start) * 1000)
        yield f"data: {json.dumps({'done': True, 'latency_ms': latency_ms}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.websocket("/ws/audio")
async def audio_stream(websocket: WebSocket):
    """
    Voice-only 輸入路徑的接收端。

    前端麥克風經 AudioWorklet 即時 resample 成 16kHz / mono / 16-bit PCM，
    每個 chunk（預設 320ms，對齊 JoyGen diffusion decoder 的 8-frame batch
    @25fps）以 binary frame 送過來。

    JoyGen audio2motion 目前還沒有可對接的 streaming endpoint（品靜那邊還
    在實作，見 docs/streaming-architecture-analysis.md 第 3、6 節），所以
    這裡先只做格式驗證＋log，把「JoyGen 人臉影片」那塊留白。等對方 endpoint
    就緒後，把下面 `# TODO forward to JoyGen` 那行換成實際轉送邏輯即可，
    前端這條路徑完全不用改。
    """
    await websocket.accept()
    chunk_count = 0
    byte_count = 0
    start = time.time()
    try:
        while True:
            data = await websocket.receive_bytes()
            if len(data) % PCM_SAMPLE_WIDTH_BYTES != 0:
                await websocket.send_json({
                    "error": f"chunk 長度 {len(data)} bytes 不是 16-bit PCM 的整數倍",
                })
                continue

            chunk_count += 1
            byte_count += len(data)
            n_samples = len(data) // PCM_SAMPLE_WIDTH_BYTES
            chunk_ms = n_samples / PCM_SAMPLE_RATE * 1000

            # TODO forward to JoyGen: 品靜的 audio2motion streaming endpoint
            # 就緒後，把這個 chunk 的 raw PCM16 bytes（`data`）轉送過去。

            await websocket.send_json({
                "ack": chunk_count,
                "chunk_ms": round(chunk_ms, 1),
                "total_bytes": byte_count,
            })
    except WebSocketDisconnect:
        elapsed = time.time() - start
        print(
            f"[voice] client disconnected: {chunk_count} chunks, "
            f"{byte_count} bytes, {elapsed:.1f}s"
        )


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": llm is not None}
