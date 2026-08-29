# ============================================================
# 用 edge-tts（微軟 neural voice，比 Windows 內建 SAPI 自然很多）產生一批
# 中文測試語音 + ground-truth manifest，給 scripts/asr_eval.py 算辨識率。
#
# 遠端連線、沒辦法真人錄音時的替代測試法。仍是合成語音（沒有真實環境噪音、
# 咬字比真人清楚），數據會偏樂觀，但多了「不同語者 / 語速 / 句型」的變化。
#
# 用法：
#   venv\Scripts\python scripts\gen_tts_samples.py --out-dir samples\tts
#   → 產生 samples\tts\*.wav（16kHz/mono）與 samples\tts\manifest.jsonl
#   然後：
#   venv\Scripts\python scripts\asr_eval.py samples\tts\manifest.jsonl --model small
#
# 需要 edge-tts（pip install edge-tts）＋ ffmpeg（PATH 內），產生時需連網。
# ============================================================

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

try:  # Windows 主控台預設 cp950，印中文會爆
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# (語者, 語速) 組合；語速 +N% 模擬講快一點
VOICE_PROFILES = [
    ("zh-TW-HsiaoChenNeural", "+0%"),
    ("zh-TW-YunJheNeural", "+0%"),
    ("zh-TW-HsiaoChenNeural", "+25%"),
    ("zh-CN-XiaoxiaoNeural", "+0%"),
]

# 陪伴型 app 情境的口語句子：情緒宣洩、提問、發語詞、長句、含數字
SENTENCES = [
    "欸我今天上班超累的，客戶一直改需求，改到我都快崩潰了。",
    "你可以陪我聊一下嗎，我現在心情有點差。",
    "就是那種，明明已經很努力了，可是還是覺得不夠好的感覺。",
    "我昨天晚上大概只睡了四個小時，今天整個人都沒精神。",
    "嗯……其實我也不知道該怎麼說，可能就是有點迷惘吧。",
    "謝謝你願意聽我講這些，我覺得好多了。",
]


async def synth(voice: str, rate: str, text: str, mp3_path: Path) -> None:
    import edge_tts

    comm = edge_tts.Communicate(text, voice, rate=rate)
    await comm.save(str(mp3_path))


def to_wav16k(mp3_path: Path, wav_path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3_path),
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav_path)],
        check=True,
    )


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=Path("samples/tts"))
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    manifest = args.out_dir / "manifest.jsonl"
    rows = []
    idx = 0
    for s_i, text in enumerate(SENTENCES):
        voice, rate = VOICE_PROFILES[s_i % len(VOICE_PROFILES)]
        idx += 1
        stem = f"{idx:02d}_{voice.split('-')[-1].replace('Neural','')}_{rate.replace('%','').replace('+','p')}"
        mp3_path = args.out_dir / f"{stem}.mp3"
        wav_path = args.out_dir / f"{stem}.wav"
        print(f"[{idx}] {voice} {rate}  {text}")
        await synth(voice, rate, text, mp3_path)
        to_wav16k(mp3_path, wav_path)
        mp3_path.unlink()
        rows.append({"audio": wav_path.name, "text": text, "voice": voice, "rate": rate})

    manifest.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    print(f"\n✔ {len(rows)} 筆 → {manifest}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ImportError:
        sys.exit("需要 edge-tts：venv\\Scripts\\python -m pip install edge-tts")
