# ============================================================
# 批次跑 faster-whisper 辨識一組音檔，跟 ground-truth 比對算 CER，
# 給 4.1 選型用（比 asr_demo.py 的單檔目測更有數據）。
#
# manifest 格式：每行一個 JSON，至少要有 audio / text 兩個欄位：
#   {"audio": "01.wav", "text": "參考文字"}
# audio 是相對於 manifest 所在資料夾的路徑。
#
# 用法：
#   venv\Scripts\python scripts\asr_eval.py samples\tts\manifest.jsonl --model small
#   venv\Scripts\python scripts\asr_eval.py samples\tts\manifest.jsonl --model medium
#
# CER = 字元錯誤率（編輯距離 / 參考字數），比對前會去掉標點與空白。
# ============================================================

import argparse
import json
import re
import sys
import time
from pathlib import Path

# 比對前只留下「字」（CJK / 英數），標點、空白、省略號等全部去掉
NON_WORD = re.compile(r"[^\w]", re.UNICODE)

# Whisper 對中文會隨機輸出繁體或簡體，這不算辨識錯誤 —— 比對前統一轉簡體。
try:
    import opencc

    _T2S = opencc.OpenCC("t2s")
    _to_simp = _T2S.convert
except Exception:  # 沒裝 opencc 就跳過（繁簡差異會被算進 CER，記得 --prompt "")
    _to_simp = lambda s: s


def normalize(s: str) -> str:
    return _to_simp(NON_WORD.sub("", s.strip()).lower())


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--model", default="small")
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--compute", default="int8")
    ap.add_argument("--beam", type=int, default=5)
    ap.add_argument("--no-vad", action="store_true")
    ap.add_argument("--prompt", default="以下是台灣人的日常對話，請以繁體中文輸出。")
    args = ap.parse_args()

    rows = [json.loads(l) for l in args.manifest.read_text(encoding="utf-8").splitlines() if l.strip()]
    base = args.manifest.parent

    from faster_whisper import WhisperModel

    t0 = time.perf_counter()
    model = WhisperModel(args.model, device="cpu", compute_type=args.compute)
    print(f"[load] {args.model}/{args.compute}  {time.perf_counter() - t0:.1f}s\n")

    tot_err = tot_ref = tot_audio = tot_infer = 0.0
    for r in rows:
        wav = base / r["audio"]
        t1 = time.perf_counter()
        segs, info = model.transcribe(
            str(wav), language=args.lang, beam_size=args.beam,
            vad_filter=not args.no_vad, initial_prompt=args.prompt or None,
        )
        hyp = "".join(s.text for s in segs)
        infer = time.perf_counter() - t1

        ref_n, hyp_n = normalize(r["text"]), normalize(hyp)
        err = edit_distance(ref_n, hyp_n)
        cer = err / max(len(ref_n), 1)
        tot_err += err
        tot_ref += len(ref_n)
        tot_audio += info.duration or 0
        tot_infer += infer

        tag = r.get("voice", "")
        print(f"— {r['audio']}  {tag} {r.get('rate','')}  CER={cer:6.1%}  ({err}/{len(ref_n)})  RTF={infer/(info.duration or 1):.2f}x")
        print(f"    ref: {r['text']}")
        print(f"    hyp: {hyp.strip()}")

    print("\n========================================")
    print(f"  clips      : {len(rows)}")
    print(f"  總 CER     : {tot_err / max(tot_ref,1):.1%}  ({int(tot_err)}/{int(tot_ref)} 字)")
    print(f"  平均 RTF   : {tot_infer / max(tot_audio,1e-9):.2f}x  (音訊 {tot_audio:.1f}s / 辨識 {tot_infer:.1f}s)")
    print("========================================")


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as e:
        sys.exit(f"找不到檔案: {e}")
