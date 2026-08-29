# 4.2 VAD 斷句 + 音訊 buffer — 實作計畫

負責人：映潔　日期：2026-08-29
對應：`docs/asr-todo.md` 第 4.2 節、第 6 節風險 1（buffer 分工）與 2（靜音閾值）
前置：`docs/asr-41-results.md`（選型已定 = faster-whisper `small`，CPU/int8）

這份文件把 todo 第 6 節兩個「還沒拍板」的風險點收斂成可以直接動工的參數與
設計，數值都標成「起始值」，要照下方調整流程現場調。

---

## 1. 決議摘要

- **音訊 buffer：共用一份**（2026-08-29 團隊 + 映潔判斷）。`/ws/audio` 收到的
  PCM 進同一個 accumulator，ASR 與（未來的）JoyGen 轉送都從它取，但消費模式
  不同 —— JoyGen 那條做成 tee，不等 VAD。細節見第 3 節。
- **VAD 靜音閾值：起始 700ms**，往長的那端偏（陪伴型 app，切斷正在傾訴的人
  比晚 1 秒回應更糟）。完整參數見第 2 節。
- **待跟品靜確認**：架構文件第 2 節的圖是「使用者 PCM → JoyGen audio2motion」，
  代表 JoyGen 吃的是**使用者輸入音訊**。若 JoyGen 其實是要讓 avatar 講 **LLM
  回覆**（該吃 TTS 音訊），就沒有共用 buffer 的問題。動工前問一句。

---

## 2. VAD 斷句參數

### 2.1 前置限制

- 前端 chunk 固定 **320ms**（5120 sample @ 16kHz / mono / 16-bit PCM），對齊
  JoyGen diffusion decoder 的 8-frame batch @25fps，**不要改**。
- 所以靜音偵測的時間解析度就是 320ms：700ms 的門檻實際會在連續 2–3 個「靜音
  chunk」（640–960ms）才判定。可接受。要更細只能改前端 chunk 大小，代價是
  跟 JoyGen 對齊失效，不划算。

### 2.2 起始參數表

| 參數 | 起始值 | 說明 |
|---|---|---|
| VAD 引擎 | `webrtcvad`，aggressiveness **2** | 0–3；室內安靜環境的平衡點。吵 → 3；會切掉小聲的人 → 1 |
| 子 frame 切法 | **20ms**（320 sample），每 chunk 16 個 | webrtcvad 只吃 10/20/30ms frame；320ms 不能被 30 整除 |
| chunk 判為「有聲」 | ≥ **30%** 子 frame 有聲（≥ 5/16） | 寬鬆，寧可多留語音 |
| **句尾靜音（最關鍵）** | **700ms** 連續靜音 | 中文句間停頓 ~300–500ms、思考停頓可到 ~1s |
| 最短語句 | **400ms** 有聲音訊才觸發 ASR | 濾掉咳嗽、鍵盤聲、「喂?」誤觸；不足則丟棄 buffer |
| 最長語句（強制 flush） | **15s** | VAD 卡在噪音上時不讓 buffer 無限長 |
| 前置 padding | 保留第一個有聲 frame 前 **300ms** | 不切掉字頭（attack）；反正本來就在 buffer 裡，別急著 trim |
| faster-whisper `vad_filter` | **關掉** | 已自己斷句、餵進去的是貼好的整段語句，Silero 只是多一次載入 + 延遲 |

### 2.3 自適應能量門檻（建議一起做）

麥克風增益每台機器差很多，固定 RMS 閾值不可靠。

1. WebSocket 連上後，取前 ~500ms 當環境底噪，算 RMS floor。
2. 某個 chunk 的 RMS < **3× floor** → 無條件當靜音，不管 webrtcvad 說什麼。
3. 防止熱麥克風 / 風扇聲 / 冷氣聲一直被判成「講話」而永遠不斷句。

### 2.4 調整流程

每句記 log（照 `buffering_reserach_20260819.md` 開頭的量測規範，單位 ms）：
`buffer 總長 / flush 時尾端靜音長度 / ASR 延遲 / 人工標記(被切掉? 等太久?)`。

| 症狀 | 調整 |
|---|---|
| 講到一半停頓思考就被切斷 | 句尾靜音 → 900–1100ms |
| 明明講完了還等很久 | 句尾靜音 → 500–600ms |
| 電視 / 音樂 / 背景人聲會誤觸 | aggressiveness → 3、有聲門檻 → 50%、最短語句 → 600ms |
| 第一個字被吃掉 | 加大前置 padding、aggressiveness 降一級 |

測試情境：短回應「好啊」／長情緒宣洩含中間停頓／講話慢的人／背景開電視。

拍板後把最終選定的數值 + 理由寫回本節，並更新
`docs/streaming-architecture-analysis.md` 第 6 節。

---

## 3. 共用 buffer 的設計

### 3.1 為什麼要注意

ASR 與 JoyGen 對同一份 PCM 的消費模式相反：

| 消費者 | 需要的節奏 |
|---|---|
| JoyGen audio2motion | 每個 320ms chunk **立刻轉送**，低延遲連續流，對齊 25fps |
| ASR（輪流式） | **累積**到句尾靜音，再整段送去辨識 |

如果只做「累積、等 VAD 再處理」，JoyGen 會被 VAD 的斷句延遲卡住 → 嘴型延遲
好幾百 ms。反過來如果只做「立刻轉送、不留」，ASR 沒東西可辨識。

### 3.2 做法：一份 accumulator + tee

```
        receive_bytes() 收到一個 320ms chunk
                     │
        ┌────────────┴────────────┐
        ▼                         ▼
 (a) append 進 ASR 語句 buffer   (b) 立刻轉送 JoyGen
     ＋跑 VAD 更新靜音計數           （目前是 no-op stub，
        │                            對應 server.py 的
        ▼                            # TODO forward to JoyGen）
  靜音 ≥ 700ms 或 buffer ≥ 15s？
        │ 是
        ▼
  切走累積的 buffer → faster-whisper 辨識 → 清空
  （不影響 (b) 的轉送）
```

要點：

- **JoyGen 那條（b）永遠不等 VAD 判定**。VAD 只決定 (a) 何時把累積的語句丟去
  ASR，跟 (b) 無關。
- 4.2 這階段 JoyGen 沒有 endpoint 可對，(b) 先是空的（維持現有 `{ack}` 回應）。
  「共用 buffer」在這階段的實際意義只是：**之後接 JoyGen 時不要再另外開第二個
  buffer**，直接在這個 tee 點加轉送邏輯。
- buffer 用 `bytearray` 或固定上限的 ring buffer；清空 = 重置長度，別每次
  重新配置。

### 3.3 邊界情況

- **語句被 15s 強制 flush 後使用者還在講**：下一段從 flush 點接續累積，前置
  padding 這次略過（沒有靜音起點）。ASR 結果可能在切點附近斷字，可接受。
- **VAD 從沒偵測到語音**（純噪音 / 使用者沒講話）：buffer 到 15s 也不觸發
  ASR（因為「最短語句 400ms 有聲」不滿足），直接丟棄清空。
- **WebSocket 斷線時 buffer 還有半句**：丟棄，不做辨識（半句辨識品質差、
  且使用者已經離開）。

---

## 4. 這一節不做的事

- 真 streaming / 逐字字幕（沿用 `docs/asr-todo.md` 第 5 節）。
- Barge-in / 雙講（使用者在 avatar 回話時插話打斷）：第一版不處理，
  之後再說。
- 多語言自動偵測：先鎖 `language="zh"`。

---

## 5. 完成後更新

- 本文件第 2.4 節：填入最終選定的 VAD 數值 + 理由。
- `docs/streaming-architecture-analysis.md` 第 6 節：ASR 工作項目搬到「已完成」，
  補實測延遲。
- `docs/asr-todo.md`：4.2 打勾，往 4.3（接 LLM streaming）。
