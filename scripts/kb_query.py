"""
scripts/kb_query.py — 給開發 Claude / 人工查內化知識庫的 CLI。
用法: python scripts/kb_query.py <collection> "<問題>" [k]
例:   python scripts/kb_query.py stock "量價背離怎麼判斷出場？"
會自動載入 repo 根的 .env 取 NVIDIA_API_KEY。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 載入 .env（取 NVIDIA_API_KEY）
envp = os.path.join(ROOT, ".env")
if os.path.exists(envp):
    for line in open(envp):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            kk, vv = line.split("=", 1)
            os.environ.setdefault(kk.strip(), vv.strip())

from knowledge.query import query


def main():
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(2)
    coll, q = sys.argv[1], sys.argv[2]
    k = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    hits = query(coll, q, k)
    print("問：%s\n%s" % (q, "=" * 56))
    for i, h in enumerate(hits, 1):
        print("【%d】相似度 %.3f | 出處 %s p.%s %s" % (i, h["score"], h["source"], h["page"], h["img_note"]))
        print("    " + h["text"].replace("\n", "\n    ") + "\n")


if __name__ == "__main__":
    main()
