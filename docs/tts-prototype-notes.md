# CosyVoice TTS 原型 —— 環境建置紀錄與已知限制

負責人：映潔（語音模組）
日期：2026-09-02 ～ 09-03

目的：把這次 session 實際做過、踩過雷的 CosyVoice 環境建置步驟記下來，
之後要在別台機器重現、或跟品靜/學長同步這個原型驗證結果時不用重踩一次。
背景與架構決策見 `docs/streaming-architecture-analysis.md`（TTS 選型原本
因為優先做 voice-only 而暫緩，這次是先自己動手做原型驗證）。

## 為什麼是獨立環境，不是塞進 imood-backend 主 venv

`server.py` 跑在專案原本的 Python 3.14（`llama-cpp-python`、`faster-whisper`
那一套）。CosyVoice 需要 PyTorch + `pynini`（Windows 上 `pynini` 只能透過
conda 裝，pip 裝不起來），版本也只支援到 Python 3.10。兩邊裝在同一個環境
機率很高會互相打架，所以做法是完全分開：`tts_service.py` 用另一個 conda
環境跑成獨立 process，`server.py` 透過 HTTP 呼叫它（見 `tts_client.py`）。

## 環境建置步驟（實際跑過、成功的版本）

1. **Miniconda**：裝到 `C:\pianoplayer\miniconda3`（**不要**裝在使用者
   家目錄底下，這台機器的使用者名稱含中文字元，Miniconda 的 NSIS 安裝程式
   對非 ASCII 路徑會直接安裝失敗，退而求其次選一個全英數字路徑）。
2. 建立 conda 環境：
   ```
   conda create -n cosyvoice python=3.10 -y
   conda install -n cosyvoice -c conda-forge pynini==2.1.5 -y
   ```
3. Clone CosyVoice（放在 repo 外面，`C:\pianoplayer\CosyVoice`，不要 vendor
   進 imood-backend，模型檔案加起來好幾 GB）：
   ```
   git clone --depth 1 https://github.com/FunAudioLLM/CosyVoice.git C:\pianoplayer\CosyVoice
   cd C:\pianoplayer\CosyVoice
   git submodule update --init --recursive   # 補 third_party/Matcha-TTS
   ```
4. 裝 `requirements.txt`（`cosyvoice` conda env 的 python）：
   ```
   <miniconda>\envs\cosyvoice\python.exe -m pip install -r requirements.txt
   ```
   **已知會卡的地方**：`openai-whisper==20231117` 的 `setup.py` 直接
   `import pkg_resources`，但 pip 幫它建的 build-isolation 環境會抓最新版
   `setuptools`（已經拿掉 `pkg_resources`），導致 build 失敗。繞過方式：
   ```
   <miniconda>\envs\cosyvoice\python.exe -m pip install "setuptools<81"
   <miniconda>\envs\cosyvoice\python.exe -m pip install --no-build-isolation "openai-whisper==20231117"
   <miniconda>\envs\cosyvoice\python.exe -m pip install -r requirements.txt   # 再跑一次，這次會跳過已裝好的 whisper
   ```
5. 下載預訓練模型（`iic/CosyVoice-300M-SFT`，內建中文女/男聲，不用額外
   參考音檔）：
   ```python
   from modelscope import snapshot_download
   snapshot_download('iic/CosyVoice-300M-SFT', local_dir='pretrained_models/CosyVoice-300M-SFT')
   ```
   實測總大小約 **5GB**（fp16/fp32 好幾種精度版本都會抓），下載時間視網路
   而定，這次 session 抓了快 50 分鐘。

## 已知限制 / 之後可以再優化的地方

- **純 CPU 首段延遲偏高**：這台測試機沒有獨立顯卡，`inference_sft(...,
  stream=True)` 第一個 chunk 要等 ~6 秒才吐出來，一句 ~35 字的完整合成要
  13 秒左右。有 GPU 的機器上應該會明顯改善，但這次原型驗證沒有測到。
- **CosyVoice 原生 chunk 粒度是 1.7~2 秒**，遠比 JoyGen 要的 320ms 粗，
  `tts_service.py` 自己在服務層把每個 model chunk 切成固定 320ms 區塊
  轉發，這是必要的後處理、不是 CosyVoice 原生支援。
- **輸出取樣率是 22050Hz**，不是 JoyGen 要的 16kHz，`tts_service.py` 用
  `torchaudio.transforms.Resample` 轉。
- **模型載入時有執行期網路依賴**：CosyVoice 的中文/英文文字正規化前端
  （`wetext`）會在載入時額外連到 modelscope.cn 抓資源，其中一個日文相關
  檔案在這次測試中連線重試了將近 5 分鐘才 403 放棄（不影響最終能不能用，
  但代表 `tts_service` 冷啟動時間不完全可預期，可能因為网路狀況再拉長）。
  之後如果要提高穩定性，可以研究能不能跳過用不到的語言資源下載。
- **PaddleSpeech 這條路已經放棄**：一開始想先試 PaddleSpeech（比較輕量），
  但公開 PyPI 上的依賴鏈目前是壞的——`paddlenlp==3.0.0b4` 需要的
  `aistudio_sdk.hub.download` 在最新版 `aistudio_sdk` 裡不存在，降版本到
  `paddlenlp==2.8.1` 又依賴一個根本不存在於公開 PyPI 的 `tool-helpers`。
  不是 Windows 特有問題，是上游套件生態目前失修，不建議再花時間修。

## 實測後修過的兩個 bug（接進 /ws/audio 之後才發現）

- **播放斷斷續續**：CosyVoice 在純 CPU 環境的合成速度遠慢於即時播放
  （RTF 實測約 4 倍），一開始「邊合成、邊把收到的 chunk 排程播放」，播放
  速度追過合成速度時就會沒有下一塊可接，聽起來斷斷續續。**修法**：前端
  （`demo-imood-dashboard.html`）改成收滿整段 `audio_delta`、等
  `audio_done` 才一次排程播放（見 `pendingAudioChunks`），犧牲一點「即時
  感」換取播放連貫。這台機器上合成本來就跟不上即時播放，這個犧牲幾乎
  沒有額外代價。
- **繁體中文發音跑掉、聽起來不像中文**：imood 的 LLM 系統提示詞要求一律
  用繁體中文回覆，但 CosyVoice-300M-SFT 的文字前處理主要是針對簡體中文
  訓練的，字典裡沒有對應注音資料的繁體字會念出明顯不像中文的音。**修
  法**：`tts_service.py` 在合成前用 `opencc`（`OpenCC('t2s')`）把文字轉
  成簡體再送進 CosyVoice，前端顯示的文字不受影響（只有語音合成那一步
  用簡體）。實測確認發音恢復正常。`opencc-python-reimplemented` 已加進
  `cosyvoice` conda env（不在 `requirements.txt`，因為 `tts_service.py`
  不跑在主 venv）。
- **另一個純前端 bug（跟 CosyVoice 無關）**：「播放範例語音」按鈕的舊程式
  碼在收到 `reply_done` 就關閉 WebSocket，但 TTS 是接在 `reply_done`
  **之後**才送 `audio_delta`/`audio_done`，導致語音還沒送到連線就被切斷。
  已改成等 `audio_done`/`error` 才關閉，並加 20 秒保險 timeout（避免
  `TTS_ENABLED=False` 時卡住不結束）。

## 對應的程式碼

- `tts_service.py`（imood-backend repo 根目錄，但用 `cosyvoice` conda env
  執行）：FastAPI app，`POST /synthesize` 逐塊吐 16kHz/mono/16-bit PCM。
- `tts_client.py`：`server.py` 用來呼叫 `tts_service` 的 async client。
- `server.py` 的 `_stream_tts_to_ws()`：`/ws/audio` 裡接 TTS 的地方，
  等整句回覆文字生成完（`reply_done`）才觸發合成（先求簡單，之後要更
  即時可以改成逐句合成）。

## 啟動方式

```
# 1. TTS 服務（cosyvoice conda env，在 imood-backend 目錄下執行）
C:\pianoplayer\miniconda3\envs\cosyvoice\python.exe -m uvicorn tts_service:app --host 0.0.0.0 --port 8001

# 2. 主服務（imood-backend 主 venv，照原本方式）
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

`tts_service` 沒啟動或連不上時，`/ws/audio` 的文字回覆流程不受影響，只是
沒有語音（`server.py` 會送一個 `{"type":"error","error":"語音合成暫時無法使用"}`，
不會中斷對話）。
