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

1. ~~**WSL2 / Linux 跑 tts_service**~~ —— **實測無效，見下節**。
2. 換非 autoregressive 的中文 TTS 引擎（F5-TTS / MeloTTS / Kokoro，GPU RTF <0.1×，但音色/韻律不同）。
3. **CosyVoice2-0.5B + vLLM**（`load_vllm=True`）——把 LLM 換成 Qwen2 backbone，vLLM 才吃得到。要下載 CosyVoice2 模型、裝 vllm、改 `tts_service.py`（CosyVoice2 用 `inference_zero_shot`/`inference_instruct2`，要 prompt wav 當語者，沒有內建「中文女」SFT 語者），音色會變。這是真正有機會的路，但是一個獨立的中型任務。
4. ~~`server.py` 的 `_stream_tts_to_ws` 改逐句合成~~ —— **實測反而更慢，見下節**。
5. 調低 CosyVoice flow decoder 的 ODE 步數（快一點、品質略降）。

## WSL2 遷移實測（2026-09-08）→ ❌ 沒有加速

把 `tts_service.py` + CosyVoice-300M-SFT 整包搬進 WSL2（Ubuntu 24.04、GPU passthrough、
torch 2.3.1+cu121、同一顆 RTX 4090）跑，直接量 `inference_sft` streaming 的 RTF：

| 環境 | TTS RTF（多次平均） | 備註 |
|---|---|---|
| Windows（`docs` 上表） | ~1.55× | |
| WSL2 Linux | **~1.7×**（1.42–2.4× 抖動） | 等於或略差，在雜訊範圍內 |

- `tts_service.py` 在 WSL 可正常啟動 + `/synthesize` 出音（env 建置流程可用，留著）。
- **為什麼沒用**：CosyVoice-300M-SFT 是 **v1**，LLM 是自家 wenet 風格 transformer 的
  `forward_chunk` 逐 token decode，**不是 HF Qwen2**。所以：
  - flash-attn / SDPA-flash 插不進去（程式沒走 `scaled_dot_product_attention`），裝了也沒差。
  - vLLM 只能加速 CosyVoice**2** 的 Qwen2 backbone，對 v1 無效。
- `deepspeed`（Linux requirements 才有）會在 import 時試著 JIT 編 CUDA op → 沒 `CUDA_HOME` 會炸；
  直接 `pip uninstall deepspeed`（跟 Windows 一致，tts_service 用不到）。
- 結論：要真的快只剩「換模型」——CosyVoice2+vLLM 或非 AR 引擎（見上方第 2、3 點）。

WSL 環境路徑（若之後要試 CosyVoice2）：`wsl -d Ubuntu-24.04 -u root`，
env `/root/miniconda3/envs/cosyvoice`（Py3.10），repo+模型 `/root/CosyVoice`，
啟動 `COSYVOICE_REPO=/root/CosyVoice MODELSCOPE_OFFLINE=1 /root/miniconda3/envs/cosyvoice/bin/python -m uvicorn tts_service:app --host 0.0.0.0 --port 8001`（在 `/mnt/c/imood-backend` 下）。

## 逐句 TTS 實測（2026-09-08）→ ❌ 反而更慢

在 `_stream_reply_to_ws` 邊收 LLM delta 邊把講完的整句丟 `stream_tts`，`_tts_worker`
逐句合成、前端逐句播（有實作出來、bench3.py 跑過，之後 revert 了）。端到端 4 次平均：

| 指標（使用者講完話後） | 原本（整段合成） | 逐句合成 |
|---|---|---|
| 聽到語音第一聲 | ~6.1 s | ~6.6 s（沒改善） |
| 整段語音備妥 | ~8.6 s | **~12.6 s（更慢 ~4s）** |

- **為什麼更慢**：imood 的回覆很短（LLM ~1s 就串完、通常 1–2 句），根本沒有「後面句子
  還在生成、前面句子先合成」的重疊空間。而拆成 2 段 = 付 2 次 CosyVoice 的首塊開銷
  （每次 `stream_tts` 的第一塊 RTF ~3×，是最貴的一段），淨結果比 1 次呼叫慢。
- 這條路只有在「回覆很長（4+ 句）且 LLM 夠慢」時才會贏；imood 不是這種 workload。
- 真正的瓶頸是 `reply_done → audio_first` 的 ~4s，就是 CosyVoice-300M 生第一塊的時間，
  逐句切不動它。要壓這個只能換模型（第 2、3 點）或砍 ODE 步數（第 5 點）。
