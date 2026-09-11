# imood.ai demo — 串接輕量對話模型

## 選型結論
先用 **Qwen2.5-1.5B-Instruct**（GGUF q4_k_m 量化版）：CPU 可跑、中文語意品質
在 demo 展示情境下明顯優於 0.5B，延遲也還在可接受範圍。等拿到 RTX 4090
之後，再換 MiniCPM-2B 或 ChatGLM3-6B 比較品質，只要改 `server.py` 裡的
`MODEL_PATH`，前端完全不用動。

## 啟動步驟

```bash
cd imood-voice
python -m venv venv            # Python 3.12 實測 OK（3.14 也行，但預編 wheel 常落後）

#  llama-cpp-python 的 source build 在 Windows 會因路徑過長失敗，要靠預編 CPU
#  wheel。加 --prefer-binary + extra-index-url 就能一次裝完 requirements.txt：
venv\Scripts\python -m pip install -r requirements.txt --prefer-binary \
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
#  → 若之後 import 時報 "Could not find module llama.dll (or one of its dependencies)"，
#    是缺 MSVC runtime：winget install Microsoft.VCRedist.2015+.x64
#  （若 wheel 那步還是失敗，就先 pip install 其他套件、最後單獨用上面同一個
#   --extra-index-url 裝 llama-cpp-python）

# 下載模型放到 models/qwen2.5-1.5b-instruct-q4_k_m.gguf
#   python -c "from huggingface_hub import hf_hub_download; import shutil; \
#     shutil.copy(hf_hub_download('Qwen/Qwen2.5-1.5B-Instruct-GGUF','qwen2.5-1.5b-instruct-q4_k_m.gguf'), \
#     'models/qwen2.5-1.5b-instruct-q4_k_m.gguf')"

venv\Scripts\python -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

`server.py` 啟動時會載入 Qwen（llama.cpp）**與** faster-whisper `small`
（voice-only ASR 用，第一次跑會自動下載 ~480MB 模型到 HF 快取）。

### GPU 加速（選用，有 NVIDIA 顯卡才裝）

```bash
venv\Scripts\python -m pip install -r requirements-gpu.txt   # nvidia-cudnn / cublas
```

裝好後 `server.py` 的 ASR 會自動偵測 CUDA（`device="auto"`）並改用
`cuda + float16`：small 模型 6s 音檔辨識 ~1.8s → ~0.3s。`ASR_DEVICE=cpu`
可強制關掉。實測數字與各元件細節見 `docs/gpu-notes.md`。

- **LLM**：Windows 沒有 llama-cpp-python 的 GPU 預編 wheel（abetlen 只出到
  0.2.68），要 GPU 得自己 source build。Qwen 1.5B 純 CPU 本來就 ~1s，除非
  換大模型否則不值得。
- **TTS**：正式跑 **CosyVoice2-0.5B + vLLM**，在 **WSL2** 起 `tts_service.py`
  （vLLM 沒有 Windows CUDA 版），`server.py` 在 Windows 跨邊界打 `localhost:8001`。
  首塊 ~1.0s、RTF ~0.24×。啟動指令與 WSL 環境見「語音回覆（TTS）」一節與
  `docs/gpu-notes.md`。舊的 CosyVoice-300M-SFT（Windows `cosyvoice` conda env）
  仍可用作後備——`tts_service.py` 靠 `COSYVOICE_MODEL_DIR` 自動判後端。

啟動後，直接用瀏覽器打開 `demo-imood-dashboard.html` 即可（它會呼叫
`http://localhost:8000/api/chat/stream` 做逐字 streaming 顯示，連不上時
自動退回 `http://localhost:8000/api/chat` 非 streaming 版本）。若你的
後端跑在別台機器或別的 port，記得把 HTML 裡的 `CHAT_STREAM_URL` /
`CHAT_API_URL` 改掉。

## 語音回覆（TTS，CosyVoice，選用）

回覆文字轉語音是另一個獨立 process（`tts_service.py`），透過 HTTP 被
`server.py` 呼叫（見 `tts_client.py`）。原因、完整環境建置步驟、已知限制
記在 `docs/tts-prototype-notes.md`（原型）與 `docs/gpu-notes.md`（CosyVoice2
遷移），這裡只列啟動指令。

**正式：CosyVoice2-0.5B + vLLM（WSL2）** —— 首塊 ~1.0s、RTF ~0.24×。
WSL env `cosyvoice_vllm` 的建置見 `docs/gpu-notes.md`。

```bash
# 在 wsl -d Ubuntu-24.04 -u root 裡
cd /mnt/c/imood_project/imood-voice
COSYVOICE_REPO=/root/CosyVoice \
COSYVOICE_MODEL_DIR=/root/CosyVoice/pretrained_models/CosyVoice2-0.5B \
MODELSCOPE_OFFLINE=1 \
/root/miniconda3/envs/cosyvoice_vllm/bin/python -m uvicorn tts_service:app --host 0.0.0.0 --port 8001
```

**後備：CosyVoice-300M-SFT（Windows）** —— 首塊 ~4s、RTF ~1.5×。

```bash
C:\imood_project\imood-voice\miniconda3\envs\cosyvoice\python.exe -m uvicorn tts_service:app --host 0.0.0.0 --port 8001
```

`tts_service` 沒啟動或連不上也沒關係——`/ws/audio` 的文字回覆流程不受
影響，只是沒有語音。**第一次建置**（新機器、新 clone）請照
`docs/tts-prototype-notes.md` 的步驟裝 Miniconda + CosyVoice，不能只靠
`git clone` 這個 repo，因為 CosyVoice、miniconda3、預訓練模型加起來十幾
GB，故意排除在版控外（見下一節）。

## 換一台機器跑起來（全新環境建置 checklist）

這個 repo 只有程式碼進版控；CosyVoice、miniconda3、LLM/ASR 模型檔都刻意
排除在外（單靠 `git clone` 拉不到，見 `.gitignore`），每台新機器都要照
下面順序重新建置一次：

1. **Clone repo**：`git clone https://github.com/DebbyWu2003/imood-voice C:\imood_project\imood-voice`
   （建議路徑保持 `C:\imood_project\imood-voice`，`tts_service.py` 裡 `COSYVOICE_REPO`
   的預設值是寫死這個路徑；要放別的路徑也可以，改用環境變數
   `COSYVOICE_REPO` 覆蓋即可，不用動程式碼）
2. **主服務 venv + LLM 模型**：照上面「啟動步驟」，分兩步裝依賴
   （llama-cpp-python 走預編 CPU wheel；import 報缺 `llama.dll` 就
   `winget install Microsoft.VCRedist.2015+.x64`）、下載 Qwen GGUF 模型到 `models/`
3. **TTS 環境**：照 `docs/tts-prototype-notes.md` 完整走一次——裝
   Miniconda 到 `C:\imood_project\imood-voice\miniconda3`（**帳號名稱含中文/非 ASCII
   字元的機器，NSIS 安裝程式會直接裝失敗**，要選純英數路徑；`winget install
   Anaconda.Miniconda3` 會裝到家目錄不是這個路徑，要用官方 installer 加
   `/D=C:\imood_project\imood-voice\miniconda3` 靜默安裝）、建 `cosyvoice` conda env
   （新版 conda 對預設頻道會擋 ToS，全程加 `-c conda-forge --override-channels`
   繞過）、clone CosyVoice + submodule、裝依賴（含 `openai-whisper` build
   繞過法、`opencc-python-reimplemented`）、下載 CosyVoice-300M-SFT 預訓練
   模型（~5GB，視網速可能要 30-50 分鐘）
4. **兩個服務都起來**：一個 terminal 跑 tts_service（cosyvoice env，
   port 8001），另一個跑 `server.py`（主 venv，port 8000）
5. 瀏覽器打開 `demo-imood-dashboard.html`

之後要在新機器上**繼續編輯**，就是正常的 git clone/pull/push；只有上面
第 3 步（CosyVoice 環境）不會跟著 git 走，每台機器要各自建一次。

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
