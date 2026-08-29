# ============================================================
# 抓 google/fleurs (cmn_hans_cn, 普通話真人朗讀) 的前 N 句，
# 存成 wav + manifest.jsonl 給 scripts/asr_eval.py 算「真人語音」CER。
#
# 為什麼不用 `datasets` 直接 load：新版 datasets 解 audio 欄位要 torchcodec
# (連帶一包 torch)，太重。這裡改成直接串流 tar.gz、讀到 N 個檔就停，
# 因為 gzip 是循序讀取，實際只會下載前面幾 MB，不會整包 217MB 抓下來。
#
# 用法：
#   venv\Scripts\python scripts\fetch_fleurs_zh.py --n 15 --out-dir samples\fleurs
#   venv\Scripts\python scripts\asr_eval.py samples\fleurs\manifest.jsonl --model small
#
# 需要 requests（datasets 已帶）。FLEURS 音檔本身就是 16kHz/mono wav。
# ============================================================

import argparse
import csv
import io
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

try:  # Windows 主控台預設 cp950，印中文會爆
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = "https://huggingface.co/datasets/google/fleurs/resolve/main/data/cmn_hans_cn"
SPLIT = "dev"  # dev.tar.gz 217MB < test.tar.gz 525MB，串流只讀前面所以無所謂


def load_transcripts() -> dict:
    # tsv 欄位：id \t filename \t raw_transcription \t transcription \t ...
    url = f"{BASE}/{SPLIT}.tsv"
    with urllib.request.urlopen(url, timeout=30) as r:
        text = r.read().decode("utf-8")
    out = {}
    for row in csv.reader(io.StringIO(text), delimiter="\t"):
        if len(row) >= 4:
            out[row[1]] = row[3]  # filename -> normalized transcription
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=15)
    ap.add_argument("--out-dir", type=Path, default=Path("samples/fleurs"))
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    print("下載 transcripts tsv ...")
    trans = load_transcripts()

    url = f"{BASE}/audio/{SPLIT}.tar.gz"
    print(f"串流 {url}（讀到 {args.n} 個檔就停）...")
    rows = []
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        with tarfile.open(fileobj=resp, mode="r|gz") as tar:
            for member in tar:
                if not member.name.endswith(".wav"):
                    continue
                fname = Path(member.name).name
                if fname not in trans:
                    continue
                data = tar.extractfile(member).read()
                wav = args.out_dir / fname
                wav.write_bytes(data)
                rows.append({"audio": fname, "text": trans[fname],
                             "voice": "fleurs-cmn(真人朗讀)", "rate": ""})
                print(f"  [{len(rows)}] {fname}  {trans[fname][:36]}")
                if len(rows) >= args.n:
                    break

    (args.out_dir / "manifest.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    print(f"\n✔ {len(rows)} 筆 → {args.out_dir / 'manifest.jsonl'}")


if __name__ == "__main__":
    main()
