# ============================================================
# tts_service.py —— CosyVoice 中文語音合成服務（獨立 process）
#
# 這個檔案**不**跑在 imood-backend 主 venv（Python 3.14）裡，因為 CosyVoice
# 需要 PyTorch + pynini（Windows 上只能透過 conda 裝），跟主 venv 的
# llama-cpp-python 環境不相容。詳細環境建置步驟見 docs/tts-prototype-notes.md。
#
# 啟動方式（用 cosyvoice conda env 的 python，在本檔案所在目錄執行）：
#   C:\imood-backend\miniconda3\envs\cosyvoice\python.exe -m uvicorn tts_service:app --host 0.0.0.0 --port 8001
#
# server.py 透過 tts_client.py 呼叫這裡的 /synthesize，兩個 process 用
# HTTP 通訊，互相獨立——這個服務掛掉不影響 /ws/audio 的文字回覆流程。
# ============================================================

import io
import os
import sys
from typing import Iterator

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# CosyVoice 是外部 checkout，不進這個 repo（跟 models/*.gguf 一樣太大不適合
# 進版控）。路徑可用環境變數覆蓋，預設對齊這次 session 實際 clone 的位置。
COSYVOICE_REPO = os.environ.get("COSYVOICE_REPO", r"C:\imood-backend\CosyVoice")
sys.path.insert(0, COSYVOICE_REPO)
sys.path.insert(0, os.path.join(COSYVOICE_REPO, "third_party", "Matcha-TTS"))

MODEL_DIR = os.path.join(COSYVOICE_REPO, "pretrained_models", "CosyVoice-300M-SFT")
SPEAKER = "中文女"

# GPU：CosyVoice 的 torch 模型 (llm/flow/hift) 只要 torch.cuda 可用就會自動
# 上 GPU（不用設任何東西）。實測（Windows + torch 2.3.1，無 flash-attn）：
#   - 預設 fp32 無 jit：RTF ~1.5×，首塊 ~4s
#   - load_jit / fp16 反而更慢（2.5–18×），因為 diffusion decoder 的 attention
#     走 math SDPA kernel，JIT trace 幫不上忙 → 一律不要開
#   - 要真的快只有 load_trt=True（TensorRT，需另裝 tensorrt + 一次性 build
#     flow.decoder.estimator engine）。設 TTS_USE_TRT=1 啟用。
_use_trt = os.environ.get("TTS_USE_TRT", "0") == "1"

TARGET_SAMPLE_RATE = 16000
CHUNK_MS = 320  # 對齊 JoyGen diffusion decoder 8-frame batch @25fps
CHUNK_BYTES = int(TARGET_SAMPLE_RATE * (CHUNK_MS / 1000) * 2)  # 16-bit = 2 bytes/sample

app = FastAPI(title="imood-backend TTS service (CosyVoice)")

cosyvoice = None  # startup 時載入一次，避免每個請求都要重載模型
_t2s = None  # 繁體轉簡體，見下方 load_model() 的說明


@app.on_event("startup")
def load_model():
    global cosyvoice, _t2s
    from cosyvoice.cli.cosyvoice import AutoModel
    from opencc import OpenCC

    import torch
    trt = _use_trt and torch.cuda.is_available()
    print(f"[tts] CUDA available={torch.cuda.is_available()}  load_trt={trt}", flush=True)
    cosyvoice = AutoModel(model_dir=MODEL_DIR, load_trt=trt, fp16=trt)
    # imood 的 LLM 系統提示詞要求一律回覆繁體中文，但 CosyVoice-300M-SFT
    # 的文字前處理主要是針對簡體中文訓練的，餵繁體字進去時，字典裡沒有的
    # 字會念出明顯不像中文的音。這裡只轉換「要合成的文字」，前端顯示的
    # 文字不受影響，使用者看到的還是繁體。
    _t2s = OpenCC("t2s")


class SynthesizeRequest(BaseModel):
    text: str


def _pcm16_bytes(speech_tensor, resampler) -> bytes:
    """CosyVoice tensor（22050Hz float, shape [1, N]）-> 16kHz PCM16 bytes。"""
    import numpy as np

    resampled = resampler(speech_tensor)  # [1, M] @ TARGET_SAMPLE_RATE
    samples = resampled.squeeze(0).clamp(-1.0, 1.0).numpy()
    pcm16 = (samples * 32767.0).astype(np.int16)
    return pcm16.tobytes()


def _synthesize_chunks(text: str) -> Iterator[bytes]:
    """
    逐段呼叫 CosyVoice stream=True，把每段輸出 resample 成 16kHz，
    再切成固定 320ms 的 PCM16 區塊依序 yield 出去。CosyVoice 原生一段
    是 ~1.7-2 秒（見 docs/tts-prototype-notes.md 的實測數字），比 JoyGen
    要的 320ms 粗很多，所以切塊這一步是必要的，不能直接轉發原生分段。
    """
    import torchaudio

    resampler = torchaudio.transforms.Resample(
        orig_freq=cosyvoice.sample_rate, new_freq=TARGET_SAMPLE_RATE
    )

    text = _t2s.convert(text)
    carry = b""  # 上一個 model chunk 切剩、不足 320ms 的尾巴
    for out in cosyvoice.inference_sft(text, SPEAKER, stream=True):
        pcm = carry + _pcm16_bytes(out["tts_speech"], resampler)
        n_full = len(pcm) // CHUNK_BYTES
        for i in range(n_full):
            yield pcm[i * CHUNK_BYTES:(i + 1) * CHUNK_BYTES]
        carry = pcm[n_full * CHUNK_BYTES:]

    if carry:
        yield carry


@app.post("/synthesize")
def synthesize(req: SynthesizeRequest):
    text = req.text.strip()
    if not text or cosyvoice is None:
        return StreamingResponse(iter(()), media_type="application/octet-stream")
    return StreamingResponse(
        _synthesize_chunks(text), media_type="application/octet-stream"
    )


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": cosyvoice is not None}
