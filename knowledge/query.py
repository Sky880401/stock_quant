"""
knowledge/query.py — 部門知識庫『查詢』端（RAG 檢索）。純 stdlib，無 fitz 依賴。

答題時用：把問題向量化(NVIDIA bge-m3)→ 對已內化的知識塊算 cosine → 回最相關 top-k + 出處。
建庫(ingest)在有 PDF/掛載的機器(#107)另做；本模組只負責讀 data/knowledge/<collection>.kb.json 查詢。
需環境變數 NVIDIA_API_KEY（查詢時 embed 用）。
"""
import os
import json
import math
import urllib.request

API = "https://integrate.api.nvidia.com/v1/embeddings"
MODEL = "baai/bge-m3"

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KB_DIR = os.path.join(_ROOT, "data", "knowledge")


def _key():
    k = os.environ.get("NVIDIA_API_KEY") or os.environ.get("NVKEY", "")
    if not k:
        raise RuntimeError("缺 NVIDIA_API_KEY（查詢知識庫要 embed 用）；請設於 .env")
    return k


def embed(texts, input_type="query"):
    body = {"model": MODEL, "input": texts, "input_type": input_type, "truncate": "END"}
    req = urllib.request.Request(API, data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + _key(),
                                          "Content-Type": "application/json"})
    d = json.load(urllib.request.urlopen(req, timeout=60))
    return [x["embedding"] for x in sorted(d["data"], key=lambda x: x["index"])]


def _cosine(a, b):
    s = na = nb = 0.0
    for x, y in zip(a, b):
        s += x * y; na += x * x; nb += y * y
    return s / (math.sqrt(na) * math.sqrt(nb) + 1e-12)


def query(collection, question, k=4):
    """回 list[{score, text, source, page, img_note}]，相似度由高到低。"""
    path = os.path.join(KB_DIR, collection + ".kb.json")
    if not os.path.exists(path):
        raise FileNotFoundError("找不到知識庫 %s（請先在 #107 ingest 並把 json commit 進 repo）" % path)
    kb = json.load(open(path))
    qv = embed([question], "query")[0]
    units = sorted(kb["units"], key=lambda u: _cosine(qv, u["vec"]), reverse=True)
    out = []
    for u in units[:k]:
        out.append({"score": round(_cosine(qv, u["vec"]), 3), "text": u["text"],
                    "source": u.get("source"), "page": u.get("page"),
                    "img_note": u.get("img_note", "")})
    return out
