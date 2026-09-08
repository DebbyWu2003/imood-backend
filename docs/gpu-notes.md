# GPU 加速紀錄（2026-09-08）

測試機：Intel i7-8700 (6C/12T) + RTX 4090 24GB + 64GB RAM，Windows 11。
輸入：`demo-assets/sample-zh.wav`（6.05s），以真實麥克風速率餵 `/ws/audio`，每階段 3 次平均。

## 使用者「講完話」後的等待時間

| 事件 | 全 CPU/預設 | + ASR GPU | + TTS TensorRT |
|---|---|---|---|
| 看到自己的話（transcript） | 1.83 s | **0.35 s** | 0.35 s |
| 回覆文字全部出完 | 2.86 s | 2.07 s | **1.85 s** |
| 整段語音備妥 | ~11.8 s | ~9.9 s | ~8.5 s |
| ASR 辨識延遲 | ~1830 ms | **~330 ms** | ~360 ms |
| TTS RTF | ~1.65× | ~1.55× | ~1.54× |

## ASR（faster-whisper）→ GPU ✅

- `voice_asr.py` `Transcriber` 預設 `device="auto"` → 有 CUDA 用 `cuda+float16`，否則 `cpu+int8`。`ASR_DEVICE=cpu` 強制關。
- 需要 `nvidia-cudnn-cu12`（9.x）+ `nvidia-cublas-cu12`（`requirements-gpu.txt`）。
- **Windows 雷**：CTranslate2 4.8 找得到這些 pip 包，但推論時載 `cublas64_12.dll` 會失敗，要把 `site-packages/nvidia/*/bin` 加進 `os.add_dll_directory()` **和** `PATH`——`voice_asr._register_nvidia_dll_dirs()` 已處理。
- GPU 第一次推論卡 ~30s 編 cuDNN kernel → `load()` 用一段靜音先 warmup。
- 效果：1830ms → 330ms。

## TTS（CosyVoice-300M-SFT）→ GPU ⚠️ 有限

- torch 模型（llm/flow/hift）**本來就自動上 GPU**（`model.py` 裡 `torch.cuda.is_available()` 就選 cuda）。原始 benchmark 已是 GPU 數字。
- `load_jit` / `fp16`：實測**更慢**（RTF 2.5–18×）→ `tts_service.py` 不開，改用 `AutoModel(..., load_trt=..., fp16=...)` 只在 TRT 時開。
- **TensorRT**：`pip install tensorrt-cu12==10.13.3.9`，`TTS_USE_TRT=1` 啟動會 build `flow.decoder.estimator` 的 fp16 engine（一次性 ~160s，快取成 `flow.decoder.estimator.fp16.mygpu.plan`）。**RTF 幾乎沒變（1.55→1.54×）。**
- 原因：瓶頸是 CosyVoice-300M 的 **autoregressive 語音 token decoder**（逐 token 生成），Windows torch 無 flash-attn、CosyVoice-1 無 vLLM。TRT 只加速後段 diffusion decoder。
- 預設 `TTS_USE_TRT=0`。engine 已建好，要開隨時開。

## LLM（Qwen / llama.cpp）→ GPU ⏭️ 跳過

- abetlen 的 Windows CUDA wheel 只到 0.2.68（2024），0.3.x 只有 Linux wheel。
- 要 GPU 得 `CMAKE_ARGS="-DGGML_CUDA=on"` source build（Windows 上會遇路徑過長）。
- Qwen 1.5B q4 純 CPU ~1s，省 <1s，不值得。換 7B+ 大模型時才做。

## 要再壓 TTS 延遲

1. **WSL2 / Linux 跑 tts_service**（`tts_client.py` 是 HTTP，跨機器/WSL 都行）——Linux torch 有 flash-attn，可用 CosyVoice2 + vLLM，RTF 可望 <0.5×。
2. 換非 autoregressive 的中文 TTS 引擎。
3. `server.py` 的 `_stream_tts_to_ws` 改逐句合成（首塊延遲少 ~2–3s，總時間不變）。
4. 調低 CosyVoice flow decoder 的 ODE 步數（快一點、品質略降）。
