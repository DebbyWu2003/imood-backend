# imood.ai — 前端 Streaming 架構整合分析

負責人：映潔（語音模組 / 前端 portal）
日期：2026-08-26（更新：已取得品靜 `buffering_reserach_20260819.md` 全文，補上
JoyGen 輸出端／輸入端的具體 buffering 方案與可行性結論）
目的：盤點現有前端架構，並根據品靜（JoyGen）2026-08-25 的回覆與
2026-08-19 的 buffering 研究文件，確認 input side streaming 格式與 output
side 現況，規劃可平行推進的工作。

---

## 0. 本次更新摘要

> 8/25 品靜回覆問答見文末「附錄一：品靜回覆原文」。8/19 buffering 研究文件
> 全文已補進 `docs/buffering_reserach_20260819.md`，重點結論見下。

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
   WebRTC 即時輸出。**buffering 研究文件證實這是可行的、風險最低的一塊**：
   現有程式碼已經有逐 batch（8 frame）的 frame generator，理論上不用動模型，
   只要把結尾「寫完全部 PNG 才一次性 ffmpeg 轉檔」換成常駐 ffmpeg pipe
   即可做到邊算邊送（細節見第 3 節）。
5. **buffering 研究文件的核心結論（品靜 2026-08-19，已讀原始碼 `inference_audio2motion.py` / `inference_joygen.py`，逐行確認）**：
   - 輸出端：**可行，風險最低**，不需動模型，只需重寫收尾邏輯。
   - 輸入端（語音）：**有條件可行**，能否 sliding window 切塊餵給
     audio2motion，取決於 VAE 模型是否依賴長距離上下文，**尚未驗證**，
     需要本地實測才能拍板。
   - 輸入端（文字）：**不建議直接支援**，需先過 streaming TTS 轉音訊
     （跟品靜 8/25 的回覆一致）。
   - 三段管線（audio2motion → edit-expression → joygen diffusion decoder）
     目前靠寫檔＋CLI 參數交接，串接方式要重新設計，優先度排在最後。

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

## 3. 輸出端現況：離線 MP4，但已有明確的 streaming 改法 → 本週 demo 仍先用 fallback

品靜 8/25 回覆時，輸出端**還是「整段跑完才吐 MP4」**，`avatar-frame` 裡預留的
`attachRemoteStream(stream)` **暫時沒有東西可以接**。但 8/19 buffering
研究文件已經把改法寫清楚，且判定「風險最低、可以先做」，跟前端規劃直接相關：

- **現有程式碼已經是逐 batch（8 frame）yield 的 generator**
  （`inference_joygen.py` 的 `data_generator()`），UNet decode 完馬上就有畫面，
  卡住即時性的唯一地方是**結尾**：等全部 frame 都貼完、寫成 PNG，才一次性
  呼叫 blocking 的 `ffmpeg image2 ...` 轉 MP4，事後還會把 PNG 全刪掉。
- 品靜規劃的解法是**不改原檔**、另外複製一份 `joygen_stream.py`，把「decode →
  貼回原圖」搬進迴圈裡即時做，並用**常駐 ffmpeg subprocess**（`-f rawvideo`
  → `-c:v libx264 -tune zerolatency` → `-f mpegts udp://...` 或 fragmented
  MP4）取代結尾的一次性轉檔，frame 一產生就寫進 pipe。
- **這件事對本週 demo 的意義**：品靜這邊的規劃是先做這塊（風險低、能立刻
  拿到延遲數據），不依賴輸入端是否已經 streaming 化。但**目前仍在實作中，
  還沒有可以對接的 endpoint**，所以本週 demo 時程上還是不能指望這塊。
- **音畫同步是新增的工作**，ffmpeg 不會自動處理：畫面（frame_index/fps）跟
  音訊（sample_count/sample_rate）要換算成統一的 PTS 才能對齊，且因為畫面是
  整批（8 張）產生、節奏不穩定，可能需要前端／中介層做一個小型 jitter
  buffer 吸收落差——這點呼應第 5 節的 buffering 設計。
- 建議這週 demo **維持目前的 SVG 假表情**當作 fallback（`detectEmotion()`
  + SVG path 動畫），這部分已經完成且不依賴 JoyGen 進度，可以先給廠商看
  「文字對話 + 表情反應」的整體體驗，不用等真人臉影片。
- `attachRemoteStream()` / `<video id="avatar-video">` 的殼保留著，等 JoyGen
  真的有 WebRTC track（或至少能吐出一段一段的 MP4/PNG 序列做假 streaming）
  時直接插上去，前端這邊不用重寫。
- **中間形態已有答案**：buffering 文件裡提到本地測試階段會先用
  `ffplay udp://<ip>:<port>` 監聽 UDP/MPEG-TS 驗證管線，這代表在正式 WebRTC
  track 做出來之前，**JoyGen 端可能會先有一個 UDP/MPEG-TS 的中間輸出**，
  而不是直接跳到 WebRTC。前端如果想提早驗證，可以先確認能不能接這個
  UDP/MPEG-TS 來源，而不是死等 WebRTC track（已更新到第 6、7 節）。

## 4. WebRTC 整合抽象化（三層）—— 現況：全部待 JoyGen 側就緒

1. **Signaling 層**：SDP offer/answer 怎麼交換——WebSocket signaling、REST
   交換 SDP，還是 JoyGen 用現成的 SFU（如 aiortc / mediasoup / LiveKit）。
   品靜的回覆沒有提到這塊，buffering 文件裡目前規劃的輸出也是
   **UDP/MPEG-TS（或 fragmented MP4），不是直接的 WebRTC track**，代表
   JoyGen 側連 WebRTC 輸出都還沒做，signaling 方案更是完全未知。**這件事
   目前只能靠我方自己研究 + 寫 mock 驗證**，暫時問不出答案（見第 6 節）。
   另外要注意：buffering 文件明講「UDP/MPEG-TS bytes → 瀏覽器可播放格式」
   中間還要接什麼元件（WebRTC gateway？MSE + websocket relay？）**屬於
   Media Server 範疇，不在 JoyGen 端修改範圍內**——這代表就算 JoyGen 端把
   frame-based streaming 做完，前端也不會直接拿到 WebRTC track，中間很可能
   還需要我方或第三方架一個轉發/封裝層，這是本次更新後新增的架構風險
   （已加進第 7 節待確認）。
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

## 5. Buffering 相關設計（已取得品靜研究文件，更新為具體結論）

- LLM 端已改為 streaming token 輸出，前端逐字 append，這條路已經跟 JoyGen
  無關、可以獨立展示。
- 品靜的參考文件 `buffering_reserach_20260819.md` 已補進 `docs/` 資料夾，
  以下是跟前端規劃直接相關的結論：

  | 管線位置 | 建議 buffering 單位 | 可行性 | 對前端的意義 |
  |---|---|---|---|
  | Audio-to-Latent Mapper（audio2motion） | bytes，固定長度 sliding window（暫定 1–2 秒 window，200–320ms 一個 chunk） | 有條件可行，待本地驗證邊界失真 | 若 TTS 放前端，送出的 PCM chunk 大小最好對齊 200–320ms、且是 25fps 的整數倍，才跟 JoyGen 端的 window 合拍 |
  | Edit-Expression（3D 渲染） | frame（逐張） | **未讀原始碼，無法確認**，是目前最大的資訊缺口 | 這段若不能逐 frame 輸出，會卡住整條輸出端 streaming，即使 diffusion decoder 那段做完也沒用 |
  | Diffusion Decoder（joygen 主體） | frame（batch=8） | **已確認可行**，程式碼裡已有 generator | 對應第 3 節，是目前唯一可以立刻動工的一段 |
  | 最終輸出 | bytes（H.264/MP4 fragment 或 raw frame，走 UDP/MPEG-TS） | 目前不存在，需新建 | 前端不會直接拿到 WebRTC track，中間可能要架轉發層（見第 4 節） |

- **Chunk size 對齊**：品靜文件確認 TTS/麥克風送出的音訊切塊大小要**對齊
  視訊 fps**，這件事原本只知道格式是 16kHz/mono/16-bit PCM，現在多了一個
  具體的節奏限制（200–320ms 一塊，對齊 25fps），前端做 `AudioWorklet`
  downsample 時可以直接照這個粒度設計 buffer。
- **Sliding window 是否可行，取決於 VAE 模型是否依賴長距離上下文**——品靜
  文件明講這件事**沒有被驗證過**，不能假設可行也不能假設不可行，要本地
  實測（用同一段音訊比較「整段 forward」vs「切段 forward」的 expression
  係數差異）。這代表輸入端 streaming 的時程目前無法承諾，前端這邊不用等，
  先照第 6 節清單獨立推進即可。
- **輸出端才是目前技術路線已定的部分**：品靜文件回答了「這份研究是否已經
  涵蓋 output 端 buffering」——**有涵蓋，而且判定風險最低、可以先做**（見
  第 3 節）。所以原本擔心「輸出端策略可能還要再等」的疑慮可以放下，唯一
  不確定的是實作時程，不是技術路線本身。
- **三段管線目前靠寫檔＋CLI 參數交接**，即使個別段落都改成 streaming，
  串接方式仍要重新設計（走記憶體物件或 local socket），品靜文件把這件事
  排在最後優先順序，等輸入/輸出端各自的可行性確認後才會動工——這代表
  前後端真正端到端串接（不是 mock）的時程，比輸出端本身完工還要更晚。

## 6. 已完成 / 可獨立推進（不需再等品靜回覆）

> **2026-08-29 更新**：跟學長及組員開會後決定，先實作 **voice-only** 這條路
> （text2voice / streaming TTS 選型暫緩，等 voice-only 這條路走通再說）；
> JoyGen 輸出端維持 **UDP/MPEG-TS**。以下已把可獨立完成（不依賴品靜側
> JoyGen 人臉影片實作）的部分做掉。

- [x] `/api/chat` 改為 streaming（`/api/chat/stream`，SSE），前端逐字顯示，
      並保留非 streaming `/api/chat` 作為連線失敗時的備援。
- [x] `avatar-frame` 加入 `<video>` 殼與 `attachRemoteStream()` / `detachRemoteStream()`
      對接點。
- [x] 麥克風權限骨架（`getUserMedia` + 音量條 UI）。
- [x] 確認音訊格式規格：16kHz / mono / 16-bit PCM（不是 Opus），且切塊大小
      要對齊視訊 fps（200–320ms、25fps 整數倍）。
- [x] 取得 JoyGen buffering 研究文件全文，確認輸出端技術路線已定
      （見第 3、5 節）。
- [x] **麥克風 resample 到 16kHz/mono/16-bit PCM**：`demo-imood-dashboard.html`
      的 `enableMic()` 已改成用 `AudioWorklet`（`pcm16-downsampler`，內嵌
      Blob URL，不用額外檔案）即時把麥克風原生取樣率線性插值 downsample
      成 16kHz PCM16，chunk 大小取 **320ms**（= JoyGen diffusion decoder
      的 8-frame batch @25fps，對齊第 5 節表格），透過 WebSocket 送到後端
      `/ws/audio`。
- [x] **後端接收端**：`server.py` 新增 `/ws/audio`（WebSocket），驗證 chunk
      是否為 16-bit PCM 整數倍、回傳 `{ack, chunk_ms, total_bytes}`，並在
      程式碼裡標了明確的 `# TODO forward to JoyGen` 掛勾點——等品靜那邊
      audio2motion 的 streaming endpoint 就緒，只要在這裡把 `data`
      （raw PCM16 bytes）轉送過去即可，前端這條路徑不用改。已用本地
      WebSocket client 測試過 320ms 合法 chunk（10240 bytes → ack 正確）
      與長度非偶數的異常 chunk（正確回傳 error）。
- [~] **調查中文 streaming TTS 選項**：因為決定先走 voice-only，這個子
      任務暫緩，等 voice-only 端到端跑通、且確定要做 text2voice 時再撿回來
      （候選方向仍是 Edge-TTS / PaddleSpeech TTS streaming / CosyVoice /
      GPT-SoVITS，篩選標準不變：支援中文＋能 chunk 輸出 PCM＋對齊 25fps）。
- [ ] Signaling 方案研究（`aiortc` / 原生 `RTCPeerConnection`）：JoyGen 側
      目前無實際 endpoint 可對，只能先寫 mock track（例如本地一支測試影片
      模擬 remote stream）驗證前端 `pc.ontrack → attachRemoteStream()` 這條
      路徑邏輯是否正確，等 JoyGen 真的推出即時輸出時，只要換掉 mock 來源。
      **仍待做**：目前 `/ws/audio` 是先用 WebSocket 收 PCM，不是走
      `RTCPeerConnection.addTrack()`，這塊 signaling 研究決定的是之後要不要
      換成真正的 WebRTC track。
- [ ] **研究 UDP/MPEG-TS → 瀏覽器可播放格式的轉發層**：buffering 文件明講
      這塊「不在 JoyGen 端修改範圍內」，代表是我方（或需要另外協調的第三方）
      要處理的缺口。可以先研究 `ffplay` 本機驗證管線的方式能不能延伸成
      「MSE + websocket relay」這類前端可用的形態，這件事也不依賴 JoyGen
      輸入端進度，可以獨立先做技術驗證。**這塊仍在等品靜側 JoyGen 人臉
      影片輸出端實作完成才能真正對接**，本次先不動工，avatar-frame 的
      `<video>` 殼與 `attachRemoteStream()` 介面維持不變、隨時可插上。

## 7. 需再跟品靜 / 學長確認的項目（更新版）

1. **TTS 放前端還是併入 Moshi（或取代 Moshi 的中文語音模型）？**
   → 決定 `server.py` 未來要不要保留、以及 TTS 相關程式碼要寫在哪個 repo。
   （這是目前最需要優先釐清的架構分工問題，buffering 文件沒有回答這個。）
2. ~~能否先要一份 `buffering_reserach_20260819.md`？~~ **已取得，本次更新已
   整合進第 3、5 節。**
3. **在完整 WebRTC 即時輸出做好之前，有沒有「短片段 MP4/PNG 序列」的中間
   形態可以先接？** → buffering 文件顯示品靜本地測試會先用 UDP/MPEG-TS
   （`ffplay` 監聽），這代表「中間形態」很可能就是 UDP/MPEG-TS，需要跟品靜
   確認：這個 UDP/MPEG-TS 輸出何時能有一個測試用的 endpoint 給前端接，
   以及前端能不能先拿一段錄好的 UDP/MPEG-TS 樣本做轉發層驗證。
4. **JoyGen 側對 signaling／SFU 的規劃（aiortc/mediasoup/LiveKit 或自建）？**
   → buffering 文件確認「UDP/MPEG-TS → 瀏覽器可播放格式」這段**不在
   JoyGen 端範圍**，等於明確了這是我方或另一個角色的工作，需要主動確認
   由誰負責，而不是等 JoyGen 端生出方案。
5. **中文 streaming TTS 有沒有指定/偏好的引擎？** → 避免我方研究和 Moshi
   那邊（若 TTS 放在那）重工。
6. **`inference_edit_expression.py`（Edit-Expression／3D 渲染段）能不能逐
   frame 輸出？** → buffering 文件標注「未讀原始碼，無法確認」，是目前
   最大的資訊缺口，這段若卡住，輸出端 streaming 即使 diffusion decoder
   做完也接不起來，建議請品靜這邊優先排讀這段原始碼。
7. **VAEModel sliding window 本地實測結果／時程？** → 決定輸入端語音
   streaming 到底能不能做，以及前端 TTS/麥克風 chunk 送出節奏要不要因此
   調整。

## 8. 下一步

1. 立即動工（不用等回覆）：麥克風 resample 邏輯（照 200–320ms chunk 設計）、
   中文 streaming TTS 選型調查、UDP/MPEG-TS 轉發層技術驗證。
2. 主動追問品靜 / 學長：TTS 分工位置（前端 vs Moshi）、UDP/MPEG-TS 中間
   輸出何時能給測試 endpoint、`edit_expression` 段是否能逐 frame 輸出、
   sliding window 實測時程。
3. 本週 demo 先以「文字輸入 + LLM streaming 回覆 + SVG 假表情」為主
   （已完成、不依賴 JoyGen），JoyGen 真人臉部分等有可用輸出（即使是短片段）
   時再插上去，不讓 demo 時程被 JoyGen 輸出端進度卡住。

---

## 附錄一：品靜回覆原文（2026-08-25）

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

## 附錄二：buffering 研究文件重點摘要（品靜，2026-08-19）

> 全文見 `docs/buffering_reserach_20260819.md`。基於直接讀
> `inference_audio2motion.py`、`inference_joygen.py` 原始碼得到的結論
> （逐行讀過）；`inference_edit_expression.py` 尚未逐行讀，標記為未確認。

- **輸出端（video streaming）**：可行，風險最低。現有程式碼已有逐 batch
  的 frame generator，只需接上即時編碼/傳輸，不需動模型本身。
- **輸入端（語音）**：有條件可行。能否用 sliding window 分塊餵給
  audio2motion，取決於 VAE 模型是否依賴長距離上下文，目前沒有被驗證過，
  需要本地實測才能拍板。
- **輸入端（文字）**：不直接支援。JoyGen 只吃音訊特徵，文字需先經
  streaming TTS 轉成音訊，格式須是 16kHz、單聲道、16-bit PCM，且切塊對齊
  視訊 fps。
- **建議執行順序**：先做風險低、能立刻拿到數據的輸出端（frame-based
  streaming + 時間量測），再做風險較高的輸入端（audio2motion chunked
  inference 實測）；`inference_edit_expression.py` 能否逐 frame 輸出待讀
  原始碼確認；frame／audio 的 timestamp 同步機制待設計；UDP/MPEG-TS →
  瀏覽器可播放格式的轉發元件待對齊（不在 JoyGen 端範圍）；三段管線的
  串接方式最後再重新設計，避免白工。
