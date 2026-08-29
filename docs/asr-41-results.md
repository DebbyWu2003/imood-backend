# 4.1 ASR 選型與環境驗證 —— 實測結果

負責人：映潔　日期：2026-08-29　機器：桌機（換機後第一步）
對應：`docs/asr-todo.md` 第 4.1 節

## 結論（TL;DR）

- **faster-whisper 在這台桌機 CPU / int8 跑得起來，沒有卡住。**
- **`small` 是選型**：
  - 口語對話（edge-tts 合成）：總 CER **1.6%**，平均 RTF 0.45x。
  - 真人朗讀新聞/百科（FLEURS，難詞多、非目標情境）：總 CER **6.2%**，
    平均 RTF 0.21x。
  - 錯的大多是句首發語詞（欸→給）或冷僻專有名詞（科隆→客棟、眾議院→縱醫院），
    對「講完話→給回應」的流程影響有限。
- `base` 明顯變差。`medium` 在難詞域較好（FLEURS 6.2%→2.3%），但目標情境的
  口語兩者都已 ~1%，差距吃不到；`medium` CPU RTF ~0.5–0.7x（正常長度句），
  留作 `small` 撐不住時的 fallback。
- 目標情境（陪伴型 app 的口語傾訴）比 FLEURS 簡單，真實 CER 應落在 1.6%～6.2%
  之間、偏低端。仍建議有機會補一次真人語音訊息驗證（見下方替代測試法第 4 點）。

## 環境

| 項目 | 值 |
|---|---|
| OS | Windows 11 Pro (26200) |
| Python | 3.13.5（system，`C:\Python313`） |
| venv | `D:\imood-backend\venv`（gitignore 已含 `venv/`） |
| CPU / RAM | 12 cores / 64 GB |
| ffmpeg | 7.1.1（PATH 內，faster-whisper 解碼用得到） |
| faster-whisper | 1.2.1（ctranslate2 4.8.1、onnxruntime 1.29、av 18.1） |
| 模型快取 | `C:\Users\cgmhaha\.cache\huggingface\hub`（symlink warning 無害） |

安裝：
```
python -m venv venv
venv\Scripts\python -m pip install -r requirements.txt      # faster-whisper 等
venv\Scripts\python -m pip install -r requirements-asr.txt  # 評估/測試用的額外依賴
```
> 本文件寫於 4.1 當時，ASR 依賴曾獨立放 `requirements-asr.txt`。4.2/4.3 把
> faster-whisper + webrtcvad-wheels 接進 `server.py` 後，這兩個已移到正式
> `requirements.txt`（釘版本）；`requirements-asr.txt` 現在只剩評估/測試工具
> （sounddevice / soundfile / edge-tts / opencc）。

## 新增檔案（都沒動 server.py）

- `scripts/asr_demo.py` —— 單檔辨識 demo，印載入時間 / 音長 / 辨識耗時 / RTF /
  分段 transcript。
- `scripts/asr_eval.py` —— 批次跑一組音檔 + ground-truth，算 CER / 平均 RTF
  （比對前用 opencc 統一繁簡、去標點）。
- `scripts/gen_tts_samples.py` —— 用 edge-tts 產生一批中文測試語音 + manifest。
- `scripts/fetch_fleurs_zh.py` —— 抓 FLEURS 普通話真人朗讀前 N 句 + manifest
  （串流 tar.gz，只下載前面幾 MB）。
- `scripts/record_wav.py` —— 用麥克風錄 16kHz/mono/16-bit PCM wav 當測試輸入。
- `requirements-asr.txt` —— ASR 階段的額外依賴。

## Benchmark

### A. 單句目測（Windows SAPI「Hanhan」zh-TW，10.43s）

原句：`欸我今天上班超累的，客戶一直改需求，改到我都快崩潰了。你可以陪我聊一下嗎？`

| model | 載入(快取後) | 辨識 | RTF | 品質 |
|---|---|---|---|---|
| base  | ~2 s | 1.0 s | 0.10x | ✗ 超累→超**類**、標點壞成「０」 |
| small | ~2 s | 2.8 s | 0.27x | ✓ 僅「欸→被」 |
| medium | ~5–10 s | 7.2 s | 0.69x | ✓ 全對 |

### B. 口語對話 CER（edge-tts neural voice，6 句、3 位語者、含 +25% 語速，共 29s）

`scripts\asr_eval.py samples\tts\manifest.jsonl --model <M>`

| model | 總 CER | 平均 RTF | 錯的地方 |
|---|---|---|---|
| small | **1.6%** (2/125 字) | **0.45x** | 欸→給、嗯→恩 |
| medium | 0.8% (1/125 字) | 1.27x | 嗯→恩 |

### C. 真人朗讀 CER（FLEURS cmn_hans_cn，15 句新聞/百科朗讀，共 184s）

`scripts\fetch_fleurs_zh.py --n 15` → `scripts\asr_eval.py samples\fleurs\manifest.jsonl --model <M> --prompt ""`

| model | 總 CER | 平均 RTF | 備註 |
|---|---|---|---|
| small | 6.2% (27/438 字) | **0.21x** | 錯在冷僻詞：科隆→客棟、間隔年→建革年、眾議院→縱醫院、跋涉→發射… |
| medium | **2.3%** (10/438 字) | 0.56x | 剩下的錯：跋涉→發射、迦南→家南、游獵→游略 |

- FLEURS 是**朗讀新聞/維基**，難詞、專有名詞、外國人名很多，比陪伴型 app 的
  口語傾訴難得多 → 這裡的 CER 是**悲觀上界**，不是目標情境的預期值。
- `medium` 在這種難詞域確實明顯較好（6.2% → 2.3%），但目標情境的口語（見 B）
  兩者都已 ~1%，差距吃不到。
- 繁簡差異已用 opencc 統一後才算 CER（Whisper 對中文會隨機吐繁或簡，未統一前
  這 15 句 CER 會被灌水到 20%）。跑 FLEURS 要加 `--prompt ""` 關掉繁體提示。
- 數字 / 英文單字辨識正常（21比20、1767年、6英里、wifi）。

### 其他觀察

- `medium` 的 RTF 跟句長有關：~12s 的正常長度句 RTF ~0.5–0.7x（可接受）；
  ~5s 的短句因固定 overhead 佔比高，RTF 會衝到 ~1.3x。`small` 一律 ~0.2–0.45x。
  → `small` 先用；真人實測若 `small` 在人名/口音/噪音上撐不住，再換 `medium`
  （正常長度句的延遲還 OK，不一定要上 GPU）。
- 內建 VAD filter 開關對「無靜音尾巴的乾淨音檔」沒差（`--no-vad` 實測一致）。
  VAD 對延遲/斷句的實際影響要等 4.2 用「有靜音尾巴」的音檔才看得出來。
- 模型下載大小：base ~145MB、small ~480MB、medium ~1.5GB（都已快取）。

## 真人 / 真實語音的替代測試法（遠端連線、無法當場錄音時）

1. **edge-tts 合成批次（已做，見 B）**：`gen_tts_samples.py` + `asr_eval.py`。
   快、可控語者/語速/句型，但仍是乾淨合成音，數據偏樂觀。
2. **公開中文語料 FLEURS（已做，見 C）**：`fetch_fleurs_zh.py`。真人朗讀、
   附逐句 ground-truth，但屬於朗讀（非自然口語）且是新聞/百科難詞域。
   `datasets` 新版解 audio 要 torchcodec（連帶 torch），太重，所以改成自己
   串流 tar.gz。
3. **抓一段中文 podcast / YouTube 片段**（yt-dlp，需另裝）：有真實環境噪音、
   自然語速與口誤，最接近產品情境，但沒有乾淨 ground-truth，只能目測。
4. **請組員丟一段語音訊息**（品靜 / 學長 / 君榮的手機語音），或在自己遠端
   連線的「本機」用手機錄音後把 wav 拖進遠端桌面 —— 這才是最終該做的驗證。

## 待補 / 下一步

1. 有機會就做替代測試法第 3 或第 4 點（真實口語 / 真人語音訊息）最終確認
   `small` 在自然口語 + 噪音下仍可接受；若不行則換 `medium`。
2. 選型可以先當 `small` 拍板 → 進 `docs/asr-todo.md` 第 4.2 節（VAD 斷句 +
   buffer）。動工前先跟學長確認 todo 第 6 節的風險（音訊 buffer 分工、VAD
   靜音閾值）。
