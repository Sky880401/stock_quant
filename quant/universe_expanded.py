"""
回測強化①初版：擴充股票池到上市中小型股（去有低效率的地方挖選股 edge）。

現況：大型股(~92)已證明無產業內選股 alpha；中小型股無效率大、被忽略 → 較可能有 edge。
做法：取全部上市普通股(4位數、排除 ETF/特別股)。法人 T86 涵蓋全上市(per-day已快取)，
      故擴股池主要成本＝逐檔股價+月營收(FinMind,有註冊層級限制)。上櫃(.TWO)待補TPEx法人源。

get_universe_expanded(cap=None) → 上市普通股代號清單(可選上限)。
"""
import os, json, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIST_CACHE = os.path.join(ROOT, "data", "quant_cache", "twse_common_list.json")


def get_universe_expanded(cap=None):
    if os.path.exists(LIST_CACHE):
        d = json.load(open(LIST_CACHE))
    else:
        envp = os.path.join(ROOT, ".env")
        if os.path.exists(envp):
            for line in open(envp):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
        from FinMind.data import DataLoader
        dl = DataLoader()
        tok = os.environ.get("FINMIND_TOKEN")
        if tok:
            dl.login_by_token(api_token=tok)
        info = dl.taiwan_stock_info()
        tw = info[info.type == "twse"]
        tw = tw[tw.stock_id.str.match(r"^[1-9][0-9]{3}$")]   # 4位、非00(排ETF)
        ind = {}
        for _, r in tw.drop_duplicates("stock_id").iterrows():
            ind[str(r.stock_id)] = str(r.industry_category)
        d = {"ids": sorted(ind.keys()), "industry": ind}
        os.makedirs(os.path.dirname(LIST_CACHE), exist_ok=True)
        json.dump(d, open(LIST_CACHE, "w"), ensure_ascii=False)
    ids = d["ids"]
    return ids[:cap] if cap else ids


if __name__ == "__main__":
    ids = get_universe_expanded()
    print("上市普通股總數：", len(ids))
