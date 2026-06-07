"""
quant/backtest_xs.py 單元測試（合成資料、無網路）。

驗證誠實版回測的四件事：
  1. quintile 五分層在「因子真的有預測力」時報酬單調遞增；
  2. 交易成本確實扣抵（net < gross）、換手率算得出來；
  3. 淨值曲線長度 = 期數+1、起點 1.0、各年化指標型別正確；
  4. 無前視：把未來報酬「打亂」後，IC 應趨近 0（factor 不該偷看未來）。
"""
import numpy as np
import pandas as pd

from quant.backtest_xs import run_backtest, rank_ic_all_factors, _round_trip_cost


def _make_panel(n_stocks=50, n_days=650, seed=0, predictive=True):
    """造一個合成 panel：每檔有固定 quality q，價格漂移 ∝ q。
    predictive=True → 過去動能(mom) 與未來報酬同向（quintile 應單調、IC>0）。"""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-06-01", periods=n_days)
    panel = {}
    for k in range(n_stocks):
        q = (k + 0.5) / n_stocks                      # 0~1 的品質分
        drift = (q - 0.5) * 0.005 if predictive else 0.0
        noise = rng.normal(0, 0.008, n_days)
        rets = drift + noise
        close = 100 * np.cumprod(1 + rets)
        vol = np.full(n_days, 5_000_000.0)            # 高量，過流動性濾網
        # 法人淨買、營收 YoY 都與 q 同向（讓 inst/revyoy 也有訊號、且非 NaN）
        foreign = np.full(n_days, (q - 0.5) * 2_000_000)
        trust = np.full(n_days, (q - 0.5) * 500_000)
        df = pd.DataFrame({
            "Close": close, "Volume": vol,
            "Foreign": foreign, "Trust": trust, "Dealer": 0.0,
            "rev_yoy": np.full(n_days, (q - 0.5) * 40.0),
        }, index=dates)
        panel[f"S{k:02d}"] = df
    return panel


def test_quintile_monotonic_and_costs():
    panel = _make_panel(predictive=True)
    r = run_backtest(panel, step=20, horizon=20, n_quantiles=5, factor="mom",
                     min_liquidity=0, min_names=15, warmup=260)
    assert "error" not in r, r
    qs = r["quintile_mean_ret_pct"]
    assert len(qs) == 5
    # 有預測力 → 單調遞增（Spearman 接近 +1）
    assert r["monotonic_spearman"] is not None and r["monotonic_spearman"] >= 0.8, r
    # 成本確實扣：net < gross，且換手率 > 0
    assert r["ls_net_per_period_pct"] < r["ls_gross_per_period_pct"], r
    assert r["avg_turnover"] > 0, r
    assert r["avg_cost_per_period_pct"] > 0, r
    # round-trip 成本率 = 買 fee + (賣 fee + 稅)
    assert abs(r["cost_params"]["round_trip_cost"] - (2 * 0.001425 + 0.003)) < 1e-9


def test_equity_curve_shape():
    panel = _make_panel(predictive=True)
    r = run_backtest(panel, step=20, horizon=20, factor="composite",
                     min_liquidity=0, min_names=15, warmup=260)
    assert "error" not in r, r
    eq = r["ls_net_equity_curve"]
    assert len(eq) == r["rebalances"] + 1
    assert abs(eq[0] - 1.0) < 1e-9
    for key in ("ann_return_pct", "ann_vol_pct", "sharpe", "max_drawdown_pct"):
        assert key in r["ls_net_annual"]
    assert r["ls_net_annual"]["max_drawdown_pct"] <= 0  # 回撤為負或 0


def test_no_lookahead_shuffled_returns_kills_ic():
    """無前視健全性：因子只用 <=t、報酬用 t->t+h。
    若我們把『未來報酬』與『因子分』的關係破壞（用隨機 panel），IC 應接近 0。"""
    panel = _make_panel(predictive=False, seed=7)
    r = run_backtest(panel, step=20, horizon=20, factor="mom",
                     min_liquidity=0, min_names=15, warmup=260)
    assert "error" not in r, r
    assert abs(r["ic_mean"]) < 0.15, r          # 無真訊號 → IC 近 0
    assert abs(r["ic_t"]) < 2.5, r              # 不顯著


def test_rank_ic_all_factors_runs():
    panel = _make_panel(predictive=True)
    out = rank_ic_all_factors(panel, step=20, horizon=20, min_liquidity=0,
                              min_names=15, warmup=260)
    for fac in ("mom", "revyoy", "inst", "lowvol", "composite"):
        assert fac in out
        assert "ic_mean" in out[fac], out[fac]


if __name__ == "__main__":
    test_quintile_monotonic_and_costs()
    test_equity_curve_shape()
    test_no_lookahead_shuffled_returns_kills_ic()
    test_rank_ic_all_factors_runs()
    print("ALL PASS; round_trip_cost =", _round_trip_cost())
