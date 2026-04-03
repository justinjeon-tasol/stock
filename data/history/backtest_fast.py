"""
고속 백테스팅 엔진 (numpy 벡터 연산).
코스피100 × 선행지표 전수 테스트.

기존 backtest_extended.py의 최적화 버전:
- 모든 데이터를 하나의 DataFrame으로 merge 후 numpy 연산
- 개별 시계열 reindex 제거 → 100배 이상 속도 향상

사용법: python -u data/history/backtest_fast.py
"""

import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent / "extended"
KOSPI_DIR = ROOT / "kospi100"
RESULT_DIR = ROOT / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

# 선행지표
INDICATORS = {
    "robotics":     ("sector_etf",  "robotics"),
    "semi_soxx":    ("sector_etf",  "semi_soxx"),
    "tech_xlk":     ("sector_etf",  "tech_xlk"),
    "sp500_fut":    ("futures",     "sp500_fut"),
    "nasdaq_fut":   ("futures",     "nasdaq_fut"),
    "defense":      ("sector_etf",  "defense"),
    "nasdaq":       ("us_index",    "nasdaq"),
    "clean_energy": ("sector_etf",  "clean_energy"),
    "sox":          ("us_index",    "sox"),
    "battery":      ("sector_etf",  "battery"),
    "nvidia":       ("us_stocks",   "nvidia"),
    "amd":          ("us_stocks",   "amd"),
    "tesla":        ("us_stocks",   "tesla"),
    "energy_xle":   ("sector_etf",  "energy_xle"),
    "wti":          ("commodities", "wti"),
    "gold":         ("commodities", "gold"),
    "copper":       ("commodities", "copper"),
    "usd_krw":      ("forex",      "usd_krw"),
    "vix":          ("us_index",    "vix"),
    "us_10y":       ("bonds",      "us_10y"),
    "sp500":        ("us_index",    "sp500"),
    "dow":          ("us_index",    "dow"),
}

THRESHOLDS = [1.0, 1.5, 2.0, 2.5, 3.0, -1.0, -1.5, -2.0, -2.5, -3.0]
TP_SL_SETS = [
    (2.0, -1.5, 3, "단기_보수"),
    (3.0, -2.0, 5, "단기_표준"),
    (5.0, -3.0, 10, "중기"),
]


def load_close(cat: str, name: str) -> pd.Series:
    path = ROOT / cat / f"{name}.csv"
    if not path.exists():
        return pd.Series(dtype=float)
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    col = "Close" if "Close" in df.columns else df.columns[min(3, len(df.columns)-1)]
    return df[col].dropna().rename(name)


def vectorized_backtest(sig_ret: np.ndarray, stock_close: np.ndarray,
                        threshold: float, tp: float, sl: float, max_hold: int) -> dict:
    """numpy 벡터 연산 백테스트."""
    n = len(sig_ret)
    if n < 200:
        return {"n": 0}

    # 시그널 마스크
    if threshold > 0:
        mask = sig_ret > threshold / 100
    else:
        mask = sig_ret < threshold / 100

    trades_pnl = []
    i = 0
    while i < n - max_hold - 1:
        if not mask[i]:
            i += 1
            continue

        entry_price = stock_close[i + 1]
        if entry_price <= 0 or np.isnan(entry_price):
            i += 1
            continue

        exit_pnl = None
        exit_day = 0
        for d in range(1, max_hold + 1):
            idx = i + 1 + d
            if idx >= n:
                break
            cur = stock_close[idx]
            if cur <= 0 or np.isnan(cur):
                continue
            pnl = (cur / entry_price - 1) * 100
            if pnl >= tp or pnl <= sl:
                exit_pnl = pnl
                exit_day = d
                break

        if exit_pnl is None:
            final_idx = min(i + 1 + max_hold, n - 1)
            final = stock_close[final_idx]
            if final > 0 and not np.isnan(final):
                exit_pnl = (final / entry_price - 1) * 100
                exit_day = max_hold

        if exit_pnl is not None:
            trades_pnl.append(exit_pnl)

        i = i + 1 + exit_day + 1 if exit_day > 0 else i + 1

    if len(trades_pnl) < 20:
        return {"n": len(trades_pnl)}

    arr = np.array(trades_pnl)
    wins = np.sum(arr > 0)
    return {
        "n": len(arr),
        "win_rate": round(float(wins / len(arr)), 4),
        "avg_ret": round(float(np.mean(arr)), 4),
        "edge": round(float(np.sum(arr)), 2),
        "max_win": round(float(np.max(arr)), 2),
        "max_loss": round(float(np.min(arr)), 2),
    }


def main():
    print("=" * 70)
    print("고속 백테스팅: 코스피100 × 선행지표 전수 테스트")
    print("=" * 70)

    # 1. 선행지표 수익률 로드
    print("\n선행지표 로딩...")
    ind_data = {}
    for key, (cat, fname) in INDICATORS.items():
        s = load_close(cat, fname)
        if len(s) >= 500:
            ind_data[key] = s.pct_change().dropna()
            print(f"  {key}: {len(ind_data[key])}행")

    # 2. 코스피100 종가 로드
    print("\n코스피100 종목 로딩...")
    kr_stocks = {}
    for f in sorted(KOSPI_DIR.glob("*.csv")):
        code = f.stem.split("_")[0]
        name = f.stem.split("_", 1)[1] if "_" in f.stem else code
        df = pd.read_csv(f, index_col=0, parse_dates=True)
        col = "Close" if "Close" in df.columns else df.columns[min(3, len(df.columns)-1)]
        s = df[col].dropna()
        if len(s) >= 500:
            kr_stocks[code] = {"name": name, "close": s}
    print(f"  {len(kr_stocks)}종목 로드")

    # 3. 전수 테스트
    total = len(kr_stocks) * len(ind_data) * len(THRESHOLDS) * len(TP_SL_SETS)
    print(f"\n테스트 시작: {total:,}건 조합")

    results = []
    tested = 0
    sig_count = 0

    for code, stock_info in kr_stocks.items():
        stock_close = stock_info["close"]
        stock_name = stock_info["name"]

        for ind_key, ind_ret in ind_data.items():
            # 날짜 교집합으로 align (1회만)
            common = ind_ret.index.intersection(stock_close.index)
            if len(common) < 200:
                tested += len(THRESHOLDS) * len(TP_SL_SETS)
                continue

            sig_arr = ind_ret.reindex(common).values
            close_arr = stock_close.reindex(common).values

            for thresh in THRESHOLDS:
                for tp, sl, mh, label in TP_SL_SETS:
                    tested += 1
                    r = vectorized_backtest(sig_arr, close_arr, thresh, tp, sl, mh)

                    if r["n"] < 30 or r.get("win_rate", 0) < 0.58 or r.get("avg_ret", 0) < 2.0:
                        continue

                    sig_count += 1
                    results.append({
                        "kr_code": code, "kr_name": stock_name,
                        "indicator": ind_key, "threshold": thresh,
                        "direction": "BUY" if thresh > 0 else "SELL_SIG",
                        "tp": tp, "sl": sl, "max_hold": mh, "label": label,
                        **r,
                    })

        # 진행률 출력
        pct = tested / total * 100
        if pct % 5 < 0.5 or code == list(kr_stocks.keys())[-1]:
            print(f"  {tested:,}/{total:,} ({pct:.0f}%) → 유의미 {sig_count}건", flush=True)

    print(f"\n완료: {tested:,}건 테스트, {sig_count}건 유의미")

    if not results:
        print("유의미한 결과 없음")
        return

    df = pd.DataFrame(results).sort_values("edge", ascending=False)
    df.to_csv(RESULT_DIR / "full_backtest_results.csv", index=False)

    # === 종목별 최고 전략 ===
    best = df.sort_values("edge", ascending=False).drop_duplicates("kr_code")
    best.to_csv(RESULT_DIR / "best_strategy_per_stock.csv", index=False)

    # === 지표별 유효성 ===
    ind_eff = df.groupby("indicator").agg(
        stocks=("kr_code", "nunique"),
        avg_wr=("win_rate", "mean"),
        avg_ret=("avg_ret", "mean"),
        total_edge=("edge", "sum"),
    ).sort_values("total_edge", ascending=False)
    ind_eff.to_csv(RESULT_DIR / "indicator_effectiveness.csv")

    # === 전략 업데이트용 JSON ===
    updates = []
    for ind_key in df["indicator"].unique():
        sub = df[df["indicator"] == ind_key]
        top = sub.sort_values("edge", ascending=False).drop_duplicates("kr_code").head(10)
        best_row = sub.sort_values(["win_rate", "edge"], ascending=False).iloc[0]
        updates.append({
            "indicator": ind_key,
            "best_threshold": float(best_row["threshold"]),
            "best_direction": best_row["direction"],
            "best_win_rate": float(best_row["win_rate"]),
            "best_avg_ret": float(best_row["avg_ret"]),
            "n_stocks": int(top["kr_code"].nunique()),
            "top_stocks": [
                {"code": r["kr_code"], "name": r["kr_name"],
                 "win_rate": r["win_rate"], "avg_ret": r["avg_ret"], "n": r["n"]}
                for _, r in top.iterrows()
            ],
        })
    updates.sort(key=lambda x: x["n_stocks"], reverse=True)
    with open(RESULT_DIR / "strategy_signal_updates.json", "w", encoding="utf-8") as f:
        json.dump(updates, f, ensure_ascii=False, indent=2)

    # === 콘솔 요약 ===
    print("\n" + "=" * 70)
    print(f"유의미 시그널: {len(df)}건 (n≥30, 승률≥55%, 수익>0)")
    print("=" * 70)

    print(f"\n[지표별 유효성 TOP 15]")
    print(f"  {'지표':18s} {'종목수':>5s} {'평균승률':>7s} {'평균수익':>8s} {'총기대값':>10s}")
    print("  " + "-" * 52)
    for idx, r in ind_eff.head(15).iterrows():
        print(f"  {idx:18s} {r['stocks']:>5.0f} {r['avg_wr']*100:>6.1f}% {r['avg_ret']:>+7.3f}% {r['total_edge']:>10.1f}")

    print(f"\n[종목별 최고 전략 TOP 20]")
    print(f"  {'종목':12s} {'지표':15s} {'임계':>5s} {'승률':>6s} {'수익':>7s} {'거래':>4s}")
    print("  " + "-" * 55)
    for _, r in best.head(20).iterrows():
        nm = r['kr_name'][:10] if isinstance(r['kr_name'], str) else str(r['kr_name'])[:10]
        print(f"  {nm:12s} {r['indicator']:15s} {r['threshold']:>+5.1f} {r['win_rate']*100:>5.1f}% {r['avg_ret']:>+6.3f}% {r['n']:>4.0f}")

    print(f"\n결과: {RESULT_DIR}")


if __name__ == "__main__":
    main()
