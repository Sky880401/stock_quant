#!/usr/bin/env python3
"""N檔邏輯一致性檢核(資料層,不經 LLM)。用法: python logic_test_n.py 2330 2317 ..."""
import sys, time, traceback

STOCKS = sys.argv[1:]
P20, P10 = -0.076, -0.132

from main import analyze_single_target

def check(sid):
    data = analyze_single_target(sid)
    if "error" in data:
        return {"sid": sid, "error": data["error"]}
    dec = data["final_decision"]
    ps = data.get("profit_space") or {}
    alert = data.get("inst_avoid_alert") or {}
    close = data["price_data"]["latest_close"]
    action = str(dec.get("action", ""))
    stop = dec.get("stop_loss_price")
    pos = str(dec.get("position_size", ""))
    v = []

    insuff = bool(ps.get("insufficient")) or not ps.get("samples")
    prob = ps.get("prob_up"); exp = ps.get("expected_return"); dn = abs(ps.get("downside") or 0)

    # R1 BUY 閘門
    if "BUY" in action and not insuff:
        if (prob is not None and prob < 50) or (exp is not None and exp <= 0) or \
           (dn > 0 and exp is not None and exp < 0.4 * dn):
            v.append(f"R1 BUY但風報比爛(prob={prob},exp={exp},dn={dn})閘門失效")
    # R2 避雷門檻
    lv = alert.get("level"); ratio = alert.get("inst_20d_ratio")
    if lv not in (None, "no_data") and ratio is not None:
        expect = "extreme" if ratio <= P10 else ("heavy" if ratio <= P20 else "none")
        if lv != expect:
            v.append(f"R2 避雷等級錯(ratio={ratio} 應為{expect} 實為{lv})")
    # R3 停損方向
    if stop:
        if ("BUY" in action or "HOLD" in action) and stop >= close:
            v.append(f"R3 停損{stop}高於現價{close}")
        if ("SELL" in action or "REDUCE" in action or "EXIT" in action) and stop <= close:
            v.append(f"R3 反轉點{stop}低於現價{close}")
    # R4 動作↔倉位
    if ("SELL" in action or "REDUCE" in action or "EXIT" in action) and not pos.startswith("0%"):
        v.append(f"R4 減碼動作但倉位={pos}")
    if "BUY" in action and pos.startswith("0%"):
        v.append(f"R4 BUY但倉位={pos}")
    # R5 降級一致
    if dec.get("risk_reward_downgrade") and "HOLD" not in action:
        v.append(f"R5 有降級說明但action={action}")
    # R6 倉位退化區間
    if "-" in pos:
        try:
            a, b = pos.split("%")[0].split("-")
            if int(a) >= int(b):
                v.append(f"R6 倉位退化區間 {pos}")
        except Exception:
            pass
    # R7 分歧註記:減碼+強烈偏多時必須有 note
    if ("REDUCE" in action or "SELL" in action or "EXIT" in action) and not insuff:
        if prob is not None and exp is not None and prob >= 60 and exp >= 0.4 * dn:
            if not dec.get("stat_conflict_note"):
                v.append(f"R7 減碼但分佈偏多(prob={prob},exp={exp})缺分歧註記")

    # R8 避雷壓倉:heavy/extreme + BUY/HOLD 時倉位上限須 ≤2%/≤1%
    import re as _re
    pm = _re.match(r"(?:(\d+)-)?(\d+)%", pos)
    if pm and ("BUY" in action or "HOLD" in action) and lv in ("heavy", "extreme"):
        hi = int(pm.group(2))
        limit = 2 if lv == "heavy" else 1
        if hi > limit:
            v.append(f"R8 避雷{lv}但倉位上限{hi}%超過{limit}%")
    # R9 優勢偏薄:BUY 且 0.4dn≤exp<0.7dn 須有壓低註記
    if pm and "BUY" in action and not insuff:
        if exp is not None and dn > 0 and 0.4 * dn <= exp < 0.7 * dn:
            if not dec.get("position_cap_note"):
                v.append(f"R9 BUY優勢偏薄(exp={exp},dn={dn})缺倉位壓低註記")
    # R10 HOLD統計看壞:exp<0且prob<40 時倉位上限須≤1%
    # (原本就≤1%者無需壓、也就無註記;壓過的會走 R10b 檢查)
    if pm and "HOLD" in action and not insuff:
        if exp is not None and prob is not None and exp < 0 and prob < 40:
            hi = int(pm.group(2))
            if hi > 1:
                v.append(f"R10 HOLD統計看壞(prob={prob},exp={exp})但倉位上限{hi}%未壓至1%")
    # R10b 通用一致性:倉位標示「上限壓低」就必須有書面理由欄位
    if "上限壓低" in pos and not dec.get("position_cap_note"):
        v.append("R10b 倉位標示上限壓低但缺 position_cap_note")

    return {"sid": sid, "name": data["meta"]["name"], "action": action, "pos": pos,
            "prob": prob, "exp": exp, "dn": ps.get("downside"),
            "alert": lv, "ratio": ratio,
            "downgraded": bool(dec.get("risk_reward_downgrade")),
            "conflict": bool(dec.get("stat_conflict_note")),
            "capped": bool(dec.get("position_cap_note")),
            "violations": v}

results = []
for i, sid in enumerate(STOCKS, 1):
    print(f"[{i}/{len(STOCKS)}] {sid} ...", flush=True)
    try:
        results.append(check(sid))
    except Exception as e:
        results.append({"sid": sid, "error": f"{type(e).__name__}: {e}"})
    time.sleep(1)

print("\n" + "=" * 110)
total_v, fails, downs, confs, alerts = 0, 0, 0, 0, []
actions = {}
for r in results:
    if "error" in r:
        print(f"❌ {r['sid']}: 分析失敗 {r['error']}")
        fails += 1
        continue
    flag = "⚠️ " if r["violations"] else "✅"
    marks = ("[降級]" if r["downgraded"] else "") + ("[分歧]" if r["conflict"] else "") + \
            ("[壓倉]" if r.get("capped") else "") + \
            (f"[避雷:{r['alert']}]" if r["alert"] in ("heavy", "extreme") else "")
    print(f"{flag} {r['sid']} {r['name']}: {r['action']} 倉位{r['pos']} | "
          f"prob={r['prob']}% exp={r['exp']}% dn={r['dn']}% | ratio={r['ratio']} {marks}")
    for vio in r["violations"]:
        print(f"     └─ {vio}")
        total_v += 1
    a = r["action"].split(" ")[0].split("(")[0]
    actions[a] = actions.get(a, 0) + 1
    downs += r["downgraded"]; confs += r["conflict"]
    if r["alert"] in ("heavy", "extreme"):
        alerts.append(f"{r['sid']}({r['alert']})")
print("=" * 110)
print(f"總計 {len(results)} 檔 | 違規 {total_v} 項 | 分析失敗 {fails} 檔")
print(f"動作分佈: {actions}")
print(f"風報比降級: {downs} 檔 | 分歧註記: {confs} 檔 | 避雷觸發: {alerts}")
