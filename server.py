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
import asyncio
import json
import time

from voice_asr import Endpointer, Transcriber

MODEL_PATH = "./models/qwen2.5-1.5b-instruct-q4_k_m.gguf"
N_CTX = 2048
N_THREADS = 8  # 依機器 CPU 核心數調整

# voice-only 輸入路徑：麥克風送 16kHz / 單聲道 / 16-bit PCM 進來，後端做 VAD
# 斷句 + ASR（見 docs/asr-42-vad-plan.md）。
# 註：JoyGen/audio2motion 吃的是「LLM 回覆的 TTS 音訊」不是這條使用者輸入
# （品靜 2026-08-29 確認），所以這條 PCM 只給 ASR 用。
PCM_SAMPLE_RATE = 16000
PCM_SAMPLE_WIDTH_BYTES = 2  # 16-bit

ASR_MODEL_SIZE = "small"  # 選型見 docs/asr-41-results.md

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
transcriber: Optional[Transcriber] = None
# faster-whisper / ctranslate2 與 llama.cpp 對同一個 model 併發呼叫都不保證
# 安全，各用一把 lock 序列化（主要是保護 /ws/audio 這條路）
_asr_lock = asyncio.Lock()
_llm_lock = asyncio.Lock()


@app.on_event("startup")
def load_model():
    global llm, transcriber
    llm = Llama(
        model_path=MODEL_PATH,
        n_ctx=N_CTX,
        n_threads=N_THREADS,
        verbose=False,
    )
    transcriber = Transcriber(model_size=ASR_MODEL_SIZE)
    transcriber.load()


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    latency_ms: int


# ------------------------------------------------------------
# LLM helper —— /api/chat、/api/chat/stream、/ws/audio 共用同一套
# prompt 組裝與生成參數，避免三個地方各寫一份。
# ------------------------------------------------------------

LLM_MAX_TOKENS = 200
LLM_TEMPERATURE = 0.7


def _build_messages(user_text: str) -> list:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]


def llm_complete(user_text: str) -> str:
    """非 streaming：回完整回覆文字。"""
    result = llm.create_chat_completion(
        messages=_build_messages(user_text),
        max_tokens=LLM_MAX_TOKENS,
        temperature=LLM_TEMPERATURE,
    )
    return result["choices"][0]["message"]["content"].strip()


def llm_stream(user_text: str):
    """streaming：逐段 yield 回覆文字 delta（同步 generator）。"""
    stream = llm.create_chat_completion(
        messages=_build_messages(user_text),
        max_tokens=LLM_MAX_TOKENS,
        temperature=LLM_TEMPERATURE,
        stream=True,
    )
    for chunk in stream:
        piece = chunk["choices"][0].get("delta", {}).get("content")
        if piece:
            yield piece


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if llm is None:
        raise HTTPException(status_code=503, detail="模型尚未載入完成")

    text = req.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="訊息不可為空")

    start = time.time()
    reply = llm_complete(text)
    latency_ms = int((time.time() - start) * 1000)
    return ChatResponse(reply=reply, latency_ms=latency_ms)


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest):
    """
    SSE streaming 版本的 /api/chat。前端不能用 EventSource（那個只能發 GET），
    改用 fetch + ReadableStream 自己解析 "data: {...}\n\n" 這種格式。

    wire 格式（跟 4.3 前就一樣，前端不用改）：
      data: {"delta": "..."}          逐字
      data: {"done": true, "latency_ms": N}
    """
    if llm is None:
        raise HTTPException(status_code=503, detail="模型尚未載入完成")

    text = req.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="訊息不可為空")

    def event_generator():
        start = time.time()
        for piece in llm_stream(text):
            yield f"data: {json.dumps({'delta': piece}, ensure_ascii=False)}\n\n"
        latency_ms = int((time.time() - start) * 1000)
        yield f"data: {json.dumps({'done': True, 'latency_ms': latency_ms}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


async def _stream_reply_to_ws(websocket: WebSocket, loop, user_text: str) -> None:
    """
    把同步的 llm_stream() generator 橋接成 async，逐段送 reply_delta，
    最後送 reply_done。生成在 thread pool 跑，透過 queue 把 delta 丟回
    event loop。
    """
    queue: asyncio.Queue = asyncio.Queue()
    DONE = object()

    def produce():
        try:
            for piece in llm_stream(user_text):
                loop.call_soon_threadsafe(queue.put_nowait, piece)
        except Exception as exc:  # noqa: BLE001 — 丟回主 coroutine 統一處理
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, DONE)

    start = time.time()
    fut = loop.run_in_executor(None, produce)
    try:
        while True:
            item = await queue.get()
            if item is DONE:
                break
            if isinstance(item, Exception):
                await websocket.send_json({"type": "error", "error": f"LLM 生成失敗: {item}"})
                break
            await websocket.send_json({"type": "reply_delta", "delta": item})
    finally:
        await fut
    await websocket.send_json({
        "type": "reply_done",
        "latency_ms": int((time.time() - start) * 1000),
    })


@app.websocket("/ws/audio")
async def audio_stream(websocket: WebSocket):
    """
    Voice-only 輸入路徑的接收端（見 docs/asr-42-vad-plan.md）。

    前端麥克風經 AudioWorklet 即時 resample 成 16kHz / mono / 16-bit PCM，
    每個 chunk（預設 320ms）以 binary frame 送過來。後端回傳的 JSON 訊息
    都有 "type" 欄位：

      {"type":"ack",       "ack":N, "chunk_ms":.., "total_bytes":..}   每個 chunk
      {"type":"asr_start", "audio_ms":..}                              偵測到句尾、開始辨識
      {"type":"asr_empty"}                                             有聲音但辨識不出內容
      {"type":"transcript","text":.., "audio_ms":.., "asr_latency_ms":..} 一句話辨識完
      {"type":"reply_delta","delta":".."}                              LLM 回覆逐段
      {"type":"reply_done", "latency_ms":N}                            LLM 回覆結束
      {"type":"error",     "error":".."}

    流程：chunk → Endpointer 累積 → 句尾靜音 → faster-whisper 辨識 → transcript
    → llm_stream() → 逐段 reply_delta → reply_done。辨識 / 生成期間主迴圈不讀
    socket，使用者這時通常在聽不會講話，累積的（靜音）chunk 之後補收即可。
    """
    await websocket.accept()

    endpointer = Endpointer()
    loop = asyncio.get_running_loop()
    chunk_count = 0
    byte_count = 0
    start = time.time()
    try:
        while True:
            data = await websocket.receive_bytes()
            if len(data) % PCM_SAMPLE_WIDTH_BYTES != 0:
                await websocket.send_json({
                    "type": "error",
                    "error": f"chunk 長度 {len(data)} bytes 不是 16-bit PCM 的整數倍",
                })
                continue

            chunk_count += 1
            byte_count += len(data)
            n_samples = len(data) // PCM_SAMPLE_WIDTH_BYTES
            chunk_ms = n_samples / PCM_SAMPLE_RATE * 1000

            await websocket.send_json({
                "type": "ack",
                "ack": chunk_count,
                "chunk_ms": round(chunk_ms, 1),
                "total_bytes": byte_count,
            })

            utterance = endpointer.feed(data)
            if utterance is None:
                continue

            if transcriber is None or not transcriber.ready:
                await websocket.send_json({"type": "error", "error": "ASR 模型尚未載入完成"})
                continue

            # 讓前端知道「已偵測到句尾靜音、開始辨識」，避免使用者以為沒反應
            await websocket.send_json({"type": "asr_start", "audio_ms": round(utterance.duration_ms)})

            async with _asr_lock:
                result = await loop.run_in_executor(
                    None, transcriber.transcribe, utterance.pcm
                )
            print(
                f"[voice] utterance {utterance.duration_ms:.0f}ms "
                f"(voiced {utterance.voiced_ms:.0f}ms) -> ASR {result.latency_ms}ms "
                f"RTF {result.latency_ms / max(result.audio_ms, 1):.2f}x: {result.text!r}",
                flush=True,
            )
            if not result.text:
                await websocket.send_json({"type": "asr_empty"})
                continue

            await websocket.send_json({
                "type": "transcript",
                "text": result.text,
                "audio_ms": round(utterance.duration_ms),
                "asr_latency_ms": result.latency_ms,
            })

            if llm is None:
                await websocket.send_json({"type": "error", "error": "LLM 模型尚未載入完成"})
                continue
            async with _llm_lock:
                await _stream_reply_to_ws(websocket, loop, result.text)
    except WebSocketDisconnect:
        elapsed = time.time() - start
        print(
            f"[voice] client disconnected: {chunk_count} chunks, "
            f"{byte_count} bytes, {elapsed:.1f}s",
            flush=True,
        )


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": llm is not None}
