# imood.ai — 前端 Streaming 架構整合分析

負責人：映潔（語音模組 / 前端 portal）
日期：2026-08-24
目的：與品靜（JoyGen）sync input side streaming 格式前，先盤點現有前端架構、
規劃可平行推進的工作，並列出需要 JoyGen 側確認才能定案的項目。

---

## 1. 現況架構

```
[文字輸入框] → fetch POST /api/chat/stream (SSE)
            → llama.cpp (Qwen2.5-1.5B-Instruct)
            → 逐字 stream 回傳
            → 前端逐字 append 到對話紀錄
            → 關鍵字假規則 detectEmotion() → SVG 假表情
```

- 純 HTML/CSS/JS，無框架（符合任務要求）。
- 對話模型：本地跑 `Qwen2.5-1.5B-Instruct`（GGUF q4_k_m），透過 FastAPI 包成
  `/api/chat`（非 streaming，保留作備援）與 `/api/chat/stream`（SSE streaming，
  已於 2026-08-24 完成）。
- 輸出面目前是 SVG path 動畫，**還不是**影片/音訊 track。`avatar-frame` 內已
  預留 `<video id="avatar-video">`，並提供 `attachRemoteStream(stream)` /
  `detachRemoteStream()` 兩個函式作為 JoyGen WebRTC track 接入點。
- 麥克風骨架已完成：`getUserMedia()` + 音量條，僅驗證瀏覽器權限流程，**尚未**
  送出任何 WebRTC track。

## 2. 兩種候選 Input 架構對前端的影響

### A. Text2Voice（JoyGen 內建 TTS）

```
前端(text) → JoyGen text input endpoint
    → (LLM 產生回覆文字，位置待確認：留在我方 server.py 還是併入 JoyGen)
    → TTS(文字→語音)
    → 驅動嘴型/表情
    → video+audio frame
→ WebRTC track 回傳前端
```

- 前端不需要麥克風，現有文字 composer 可直接沿用。
- 需要確認**分工邊界**：`/api/chat/stream` 產生的回覆文字，是繼續留在我方
  FastAPI 後端，再把文字轉送給 JoyGen 的 TTS endpoint；還是 JoyGen 端整套接手
  （文字進、影片出，我方 LLM 停用）。這會決定 `server.py` 未來要不要保留。
- 需要確認 TTS 是整句吐還是逐 chunk streaming（決定 JoyGen video track 能不能
  邊生成邊播，還是要等整句合成完才開始）。

### B. Voice-only（JoyGen 只吃音訊）

```
前端麥克風 → getUserMedia() → encode(PCM/Opus)
    → WebRTC addTrack(audioTrack)
    → JoyGen server（可能含 ASR）
    → 驅動嘴型/表情
    → video+audio track 回傳前端
```

- 前端必須加麥克風輸入（骨架已就緒，見上）。
- 音訊格式（sample rate / 聲道 / PCM or Opus）決定要不要在前端做 resample：
  若 JoyGen 要求特定 raw PCM sample rate，瀏覽器預設抓到的通常是 48kHz，需要
  AudioWorklet 轉換；若走 Opus，WebRTC codec 協商通常會自動處理。
- 若廠商 demo 仍要支援文字輸入，但 JoyGen 只吃語音，前端需要「文字→本地
  TTS→合成音訊→送進同一條 audio track」的轉接層，讓 JoyGen 端始終只收到統一
  格式的音訊。這點需要在 sync 時明確問清楚。

## 3. WebRTC 整合抽象化（三層）

1. **Signaling 層**：SDP offer/answer 怎麼交換——WebSocket signaling、REST
   交換 SDP，還是 JoyGen 用現成的 SFU（如 aiortc / mediasoup / LiveKit）。目前
   完全未知，決定前端 signaling 邏輯的複雜度。
2. **Track 層**：
   - Outbound（前端→JoyGen）：`pc.addTrack(micStream.getAudioTracks()[0])`，
     僅 voice-only 情境需要。
   - Inbound（JoyGen→前端）：`pc.ontrack = e => attachRemoteStream(e.streams[0])`
     （已在前端定義好介面，等 JoyGen 端可用即可接上）。
3. **同步層**：video/audio 兩條 track 若分開傳送，需確認 JoyGen 端是否已處理
   A/V sync（timestamp 對齊），避免嘴型與聲音不同步。優先度較低，非本次 sync
   必問項目。

## 4. Buffering 相關設計

- LLM 端已改為 streaming token 輸出（`llm.create_chat_completion(..., stream=True)`），
  避免「LLM 跑完整段才送出」的全序列延遲，為未來與 JoyGen pipeline overlap
  留好介面。
- 前端顯示已改為逐字 append（`callDialogueModelStream` 的 `onDelta` callback），
  之後如果 JoyGen 走 text2voice，文字端可以維持現在的 streaming 節奏，音訊/影片
  端則視 JoyGen TTS 是否支援 chunk streaming 決定顯示同步方式。

## 5. 已完成 / 可獨立推進（不需等品靜回覆）

- [x] `/api/chat` 改為 streaming（`/api/chat/stream`，SSE），前端逐字顯示，
      並保留非 streaming `/api/chat` 作為連線失敗時的備援。
- [x] `avatar-frame` 加入 `<video>` 殼與 `attachRemoteStream()` / `detachRemoteStream()`
      對接點，尚未接真實 stream 前顯示原本的 SVG 假臉。
- [x] 麥克風權限骨架（`getUserMedia` + 音量條 UI），驗證瀏覽器權限流程，尚未
      送出 WebRTC track。
- [ ] Signaling 方案研究（`aiortc` / 原生 `RTCPeerConnection` / 是否需要
      STUN/TURN——區網 demo 應該不需要）：屬於「研究 WebRTC 如何與 JoyGen
      串接」任務本身該做的功課，不依賴品靜的回覆內容，只是最終要接的
      endpoint 需要她確認。

## 6. 需等 JoyGen 側（品靜）確認才能定案的項目

1. Input 是 voice-only 還是 text2voice？→ 決定要不要在前端 UI 上開放麥克風
   按鈕給使用者實際使用（骨架已備妥，只差開關）。
2. 若 text2voice：TTS 引擎是哪個、是否支援中文、整句吐或 streaming 吐？→
   決定 `server.py` 的 LLM 角色要不要保留，以及前端顯示同步策略。
3. 若 voice-only：音訊格式要求（sample rate / 聲道 / PCM or Opus）？→ 決定
   前端要不要加 resample 邏輯。
4. JoyGen 現在輸出進度到哪（PNG 序列 or 已可 WebRTC 即時輸出 video/audio
   track）？→ 決定本週能不能開始寫真的 `RTCPeerConnection` 對接程式碼，還是
   只能先用 mock track 驗證前端邏輯。
5.（新增）LLM 產生回覆文字這件事，最終留在我方 `server.py`，還是併入
   JoyGen 那邊整套接手？→ 決定 `server.py` 的存廢與後續維護方向。

## 7. 下一步

品靜回覆後，依照答案打開對應分支：

- 若確認 voice-only + 音訊格式 → 把 `enableMic()` 拿到的 `micStream` 接進
  `RTCPeerConnection.addTrack()`。
- 若確認 text2voice → 決定 `/api/chat/stream` 的文字要不要轉送給 JoyGen 的
  TTS endpoint，或直接改造成呼叫 JoyGen 的對話+TTS 一條龍 API。
- 若 JoyGen 已有可用的 WebRTC track → 直接串 `pc.ontrack` 到現成的
  `attachRemoteStream()`，驗證真實畫面能不能顯示在 `avatar-frame` 裡。
