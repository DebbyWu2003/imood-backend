# imood.ai — 前端 Streaming 架構整合分析

負責人：映潔（語音模組 / 前端 portal）
日期：2026-08-25（更新：已收到品靜對 JoyGen input/output side 的回覆）
目的：盤點現有前端架構，並根據品靜（JoyGen）2026-08-25 的回覆，確認 input side
streaming 格式與 output side 現況，規劃可平行推進的工作。

---

## 0. 本次更新摘要（品靜回覆重點）

> 完整問答見文末「附錄：品靜回覆原文」。

1. **JoyGen/audio2motion 本身沒有原生文字輸入路徑，只吃音訊**
   （16kHz、mono、16-bit PCM）。也就是說原本問的「voice-only 還是
   text2voice」不是平行的兩個選項，而是：
   - **無論最終走哪條路，進 JoyGen 的都一定是 PCM 音訊。**
   - 差別只在於「這段音訊從哪裡來」——使用者真的講話（voice-only），
     還是文字先經過一層 **streaming TTS** 轉成音訊（text2voice）。
2. 若走 text2voice：TTS 需要**支援中文**，且**最好能 streaming 逐塊吐 PCM**
   （而不是整句合成完才給）。TTS 這層可以放在前端，也可能放在 Moshi 那邊
   （品靜原話：「需要在前端或 Moshi 那邊先過一層 streaming TTS」）。
3. 若走 voice-only：前端麥克風收音後，需 encode 成 **16kHz / 單聲道 /
   16-bit PCM** 再送出。
4. **輸出端目前仍是離線模式**：跑完整段語音才產生一支 MP4，**尚未**接上
   WebRTC 即時輸出。品靜表示「輸出端改成即時串流」技術上已確認可行，
   但仍在實作中，還沒有時程。
5. 品靜附上參考文件 `joygen-deployment-notes/docs/buffering_reserach_20260819.md`
   （在 JoyGen repo 內，非本 repo）——建議之後跟品靜要一份，確認 buffering
   策略是否會影響前端要不要做本地 jitter buffer。

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
  `/api/chat`（非 streaming，保留作備援）與 `/api/chat/stream`（SSE streaming）。
- 輸出面目前是 SVG path 動畫，**還不是**影片/音訊 track。`avatar-frame` 內已
  預留 `<video id="avatar-video">`，並提供 `attachRemoteStream(stream)` /
  `detachRemoteStream()` 兩個函式作為 JoyGen WebRTC track 接入點（**目前尚無
  對接目標**，見下方第 3 節）。
- 麥克風骨架已完成：`getUserMedia()` + 音量條，僅驗證瀏覽器權限流程，**尚未**
  送出任何 WebRTC track，也**尚未**做 48kHz→16kHz resample。

## 2. 修正後的 Input 架構：不是二選一，是「共同終點 + 不同前段」

品靜的回覆讓原本並列的 A/B 兩案合併成一條 pipeline，差異只在音訊怎麼來：

```
                        ┌─ 使用者打字 → LLM 產生回覆文字 → streaming TTS ──┐
                        │   （TTS 在前端 or 在 Moshi？待定，見第 6 節 #1）  │
                        │                                                  ▼
                        │                                    音訊 chunk (16kHz/mono/16-bit PCM)
                        │                                                  │
使用者說話 → getUserMedia() → resample/encode(16kHz/mono/16-bit PCM) ──────┤
                                                                            ▼
                                                        JoyGen audio2motion（吃 PCM）
                                                                            │
                                                              嘴型/表情驅動
                                                                            │
                                                離線：跑完整段 → 產出 MP4（目前）
                                                即時：WebRTC video/audio track（研究中，未實作）
                                                                            │
                                                              前端 avatar-frame 顯示
```

對前端的具體影響：

- **音訊格式已經確定**：16kHz、單聲道、16-bit PCM，不是 Opus。麥克風那條路
  一定要做 resample（瀏覽器 `getUserMedia` 預設多半是 48kHz），建議用
  `AudioWorklet` 做 downsample + PCM16 encode，`MediaRecorder` 內建的
  Opus/WebM 編碼不能直接用。
- **文字輸入這條路，多了一個新的必要元件：streaming TTS**。這件事本次任務
  單上寫的是「找尋 lightly 的文字對話模型」（已完成，Qwen2.5-1.5B），但現在
  多了一個「找 streaming 中文 TTS」的子任務，且需求明確：
  1. 支援中文
  2. 能 chunk streaming 吐 PCM（不能整句才吐，否則沒有「即時感」）
  3. 最好夠 lightweight，能跟 LLM 一起塞進同一台機器
- **TTS 放哪裡（前端 / Moshi）還沒定案**，這會決定 `server.py` 的角色：
  - 若 TTS 放前端：前端要新增「文字→TTS→PCM chunk→送給 JoyGen」的邏輯，
    `server.py` 維持現有 LLM streaming 角色不變。
  - 若 TTS 併入 Moshi（或未來取代 Moshi 的中文語音模型）：`server.py` 的
    LLM streaming 輸出，改成轉送給 Moshi 側的 TTS endpoint，前端只需要拿到
    最終音訊/影片 track，不用自己處理 TTS。
  - 這點需要主動再跟品靜或學長確認一次（見第 6 節 #1），因為會決定接下來
    程式碼寫在哪一個 repo。

## 3. 輸出端現況：離線 MP4，WebRTC 尚未可用 → 本週 demo 必須有 fallback

這是這次同步最關鍵的新資訊：**JoyGen 現在還是「整段跑完才吐 MP4」**，
`avatar-frame` 裡預留的 `attachRemoteStream(stream)` **暫時沒有東西可以接**。

對「本週先做一個簡單版 demo 給廠商看」這個目標的直接影響：

- 如果照原計畫等 JoyGen 的 WebRTC track，demo 時程會被卡住（品靜說仍在
  實作中、無時程）。
- 建議這週 demo **維持目前的 SVG 假表情**當作 fallback（`detectEmotion()`
  + SVG path 動畫），這部分已經完成且不依賴 JoyGen 進度，可以先給廠商看
  「文字對話 + 表情反應」的整體體驗，不用等真人臉影片。
- `attachRemoteStream()` / `<video id="avatar-video">` 的殼保留著，等 JoyGen
  真的有 WebRTC track（或至少能吐出一段一段的 MP4/PNG 序列做假 streaming）
  時直接插上去，前端這邊不用重寫。
- 可以順便問品靜：在真正的 WebRTC track 做出來之前，**有沒有「跑完一小段
  就吐一個短 MP4」的中間形態**可以先接，即使不是嚴格意義的即時，也比
  等到完全體 WebRTC 更早能串起整條 pipeline 做端對端驗證。（新增到第 6 節）

## 4. WebRTC 整合抽象化（三層）—— 現況：全部待 JoyGen 側就緒

1. **Signaling 層**：SDP offer/answer 怎麼交換——WebSocket signaling、REST
   交換 SDP，還是 JoyGen 用現成的 SFU（如 aiortc / mediasoup / LiveKit）。
   品靜的回覆沒有提到這塊，代表 JoyGen 側連 WebRTC 輸出都還沒做，signaling
   方案更是完全未知。**這件事目前只能靠我方自己研究 + 寫 mock 驗證**，暫時
   問不出答案（見第 6 節）。
2. **Track 層**：
   - Outbound（前端→JoyGen）：若走 voice-only，`pc.addTrack(micStream.getAudioTracks()[0])`；
     若走 text2voice + TTS 在前端，則是把 TTS 產生的 PCM chunk 包成
     `MediaStreamTrack` 再 addTrack（比純麥克風複雜一點，需要研究
     `AudioWorkletNode` → `MediaStreamAudioDestinationNode` 的組合方式）。
   - Inbound（JoyGen→前端）：`pc.ontrack = e => attachRemoteStream(e.streams[0])`
     （已定義好介面，但如第 3 節所述，目前無實際 track 可對接）。
3. **同步層**：video/audio 兩條 track 若分開傳送，需確認 JoyGen 端 A/V sync
   做法。**JoyGen 輸出端連即時輸出都還沒做，這件事優先度更低**，先不用花
   時間研究。

## 5. Buffering 相關設計

- LLM 端已改為 streaming token 輸出，前端逐字 append，這條路已經跟 JoyGen
  無關、可以獨立展示。
- 品靜提供的參考文件 `joygen-deployment-notes/docs/buffering_reserach_20260819.md`
  在 JoyGen repo 內，我方 repo 目前沒有這份檔案。**建議跟品靜要一份 copy
  或連結**，確認：
  - JoyGen 端音訊 buffering 的 chunk size / latency 預期值，反推前端 TTS
    （若 TTS 放前端）要用多大的 chunk 送出比較合拍。
  - 這份研究是否已經涵蓋「output 端要怎麼 buffer 才能做到即時 WebRTC」，
    如果有，代表輸出端的技術路線已定，只是還沒寫完；如果只涵蓋 input 端，
    代表輸出端 buffering 策略可能還要再等。

## 6. 已完成 / 可獨立推進（不需再等品靜回覆）

- [x] `/api/chat` 改為 streaming（`/api/chat/stream`，SSE），前端逐字顯示，
      並保留非 streaming `/api/chat` 作為連線失敗時的備援。
- [x] `avatar-frame` 加入 `<video>` 殼與 `attachRemoteStream()` / `detachRemoteStream()`
      對接點。
- [x] 麥克風權限骨架（`getUserMedia` + 音量條 UI）。
- [x] 確認音訊格式規格：16kHz / mono / 16-bit PCM（不是 Opus）。
- [ ] **麥克風 resample 到 16kHz/mono/16-bit PCM**：現在可以直接動工，用
      `AudioWorklet` 做 downsample，不用再等任何人回覆。
- [ ] **調查中文 streaming TTS 選項**：這是本次同步後新增的必要子任務，
      候選方向可先評估 Edge-TTS（免費但非本地、非嚴格 streaming）、
      PaddleSpeech TTS streaming、CosyVoice、GPT-SoVITS 等，篩選標準是
      「支援中文 + 能 chunk 輸出 PCM」。獨立於品靜的回覆即可先動工研究。
- [ ] Signaling 方案研究（`aiortc` / 原生 `RTCPeerConnection`）：JoyGen 側
      目前無實際 endpoint 可對，只能先寫 mock track（例如本地一支測試影片
      模擬 remote stream）驗證前端 `pc.ontrack → attachRemoteStream()` 這條
      路徑邏輯是否正確，等 JoyGen 真的推出即時輸出時，只要換掉 mock 來源。

## 7. 需再跟品靜 / 學長確認的項目（更新版）

1. **TTS 放前端還是併入 Moshi（或取代 Moshi 的中文語音模型）？**
   → 決定 `server.py` 未來要不要保留、以及 TTS 相關程式碼要寫在哪個 repo。
   （這是本次回覆後最需要優先釐清的架構分工問題。）
2. **能否先要一份 `joygen-deployment-notes/docs/buffering_reserach_20260819.md`？**
   → 確認 chunk size / latency 預期，設計前端 TTS 送出節奏。
3. **在完整 WebRTC 即時輸出做好之前，有沒有「短片段 MP4/PNG 序列」的中間
   形態可以先接？** → 決定本週 demo 是否能提早做一次端對端串接驗證（哪怕
   不是嚴格即時），而不是完全等到 JoyGen WebRTC 完工。
4. **JoyGen 側對 signaling／SFU 的規劃（aiortc/mediasoup/LiveKit 或自建）？**
   → 品靜回覆未提及，可能代表尚未決定；若尚未決定，可以主動提議由我方
   先評估方案，減少 JoyGen 端負擔。
5. **中文 streaming TTS 有沒有指定/偏好的引擎？** → 避免我方研究和 Moshi
   那邊（若 TTS 放在那）重工。

## 8. 下一步

1. 立即動工（不用等回覆）：麥克風 resample 邏輯 + 中文 streaming TTS 選型調查。
2. 主動追問品靜 / 學長：TTS 分工位置（前端 vs Moshi）、buffering 研究文件、
   是否有中間輸出形態可先串。
3. 本週 demo 先以「文字輸入 + LLM streaming 回覆 + SVG 假表情」為主
   （已完成、不依賴 JoyGen），JoyGen 真人臉部分等有可用輸出（即使是短片段）
   時再插上去，不讓 demo 時程被 JoyGen 輸出端進度卡住。

---

## 附錄：品靜回覆原文（2026-08-25）

> Q1 ～ Q3 — Input 是 voice-only 還是 text2voice？
> 目前 JoyGen/audio2motion 本身只接受音訊輸入（16kHz、mono、16-bit PCM），
> 沒有原生的文字輸入路徑。如果要走 text2voice，需要在前端或 Moshi 那邊先過
> 一層 streaming TTS，再把 PCM 音訊餵進來。
> • 如果走 text2voice：需要支援中文、且最好能 streaming 逐塊吐 PCM。
> • 如果走 voice-only：前端需要加麥克風，音訊格式要求是 16kHz、單聲道、
>   16-bit PCM。
>
> Q4 — JoyGen 輸出目前進度
> 仍是「跑完整段才產生 MP4」的離線模式，尚未接上 WebRTC 即時輸出。
> 研究已確認輸出端改成即時串流技術上可行（仍在實作中）
>
> 參考文件：joygen-deployment-notes/docs/buffering_reserach_20260819.md
</content>
</invoke>
