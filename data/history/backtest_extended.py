"""
확장 백테스팅 엔진.
코스피 100종목 × 글로벌 선행지표 조합을 전수 테스트하여
유의미한 시그널을 발굴하고 전략 설정에 반영한다.

로직:
  1. US 지표 일간 변동률이 threshold 이상인 날을 시그널로 간주
  2. 시그널 발생 익일 한국 종목 매수 (종가)
  3. 최대 5일 보유, TP/SL 도달 시 청산
  4. 승률, 평균수익, 기대값 계산
  5. 유의미 기준: n≥30, 승률≥55%, 기대값>0

사용법: python data/history/backtest_extended.py
출력: data/history/extended/backtest_results/
"""

import json
import os
from pathlib import Path
from itertools import product

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent / "extended"
KOSPI_DIR = ROOT / "kospi100"
RESULT_DIR = ROOT / "backtest_results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

# TP/SL 세트
TP_SL_SETS = [
    {"tp": 2.0, "sl": -1.5, "max_hold": 3, "label": "단기_보수"},
    {"tp": 3.0, "sl": -2.0, "max_hold": 5, "label": "단기_표준"},
    {"tp": 5.0, "sl": -3.0, "max_hold": 10, "label": "중기"},
]

# 선행지표 목록 (상관분석에서 발견된 상위 지표)
LEADING_INDICATORS = {
    # (카테고리, 파일명, 표시명)
    "robotics":      ("sector_etf",  "robotics",      "ROBO ETF"),
    "semi_soxx":     ("sector_etf",  "semi_soxx",     "SOXX ETF"),
    "tech_xlk":      ("sector_etf",  "tech_xlk",      "XLK ETF"),
    "sp500_fut":     ("futures",     "sp500_fut",     "S&P500선물"),
    "nasdaq_fut":    ("futures",     "nasdaq_fut",    "NASDAQ선물"),
    "defense":       ("sector_etf",  "defense",       "ITA 방산ETF"),
    "nasdaq":        ("us_index",    "nasdaq",        "NASDAQ"),
    "clean_energy":  ("sector_etf",  "clean_energy",  "ICLN ETF"),
    "sox":           ("us_index",    "sox",           "SOX"),
    "battery":       ("sector_etf",  "battery",       "LIT 배터리ETF"),
    "nvidia":        ("us_stocks",   "nvidia",        "NVIDIA"),
    "amd":           ("us_stocks",   "amd",           "AMD"),
    "tesla":         ("us_stocks",   "tesla",         "Tesla"),
    "energy_xle":    ("sector_etf",  "energy_xle",    "XLE 에너지ETF"),
    "wti":           ("commodities", "wti",           "WTI유"),
    "gold":          ("commodities", "gold",          "금"),
    "copper":        ("commodities", "copper",        "구리"),
    "usd_krw":       ("forex",      "usd_krw",       "달러/원"),
    "vix":           ("us_index",    "vix",           "VIX"),
    "us_10y":        ("bonds",      "us_10y",        "미국10Y금리"),
    "sp500":         ("us_index",    "sp500",         "S&P500"),
    "dow":           ("us_index",    "dow",           "다우"),
    "materials_xlb": ("sector_etf",  "materials_xlb", "XLB 소재ETF"),
    "industrial_xli":("sector_etf",  "industrial_xli","XLI 산업ETF"),
}

# 시그널 임계값
THRESHOLDS = [1.0, 1.5, 2.0, 2.5, 3.0]
# 역방향(하락) 임계값
NEG_THRESHOLDS = [-1.0, -1.5, -2.0, -2.5, -3.0]


def load_close(category: str, name: str) -> pd.Series:
    path = ROOT / category / f"{name}.csv"
    if not path.exists():
        return pd.Series(dtype=float)
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    for col in ["Close", "종가"]:
        if col in df.columns:
            return df[col].dropna()
    if len(df.columns) >= 4:
        return df.iloc[:, 3].dropna()
    return pd.Series(dtype=float)


def load_kospi_stock(code: str) -> pd.Series:
    """코스피100 폴더에서 종목 로드."""
    for f in KOSPI_DIR.glob(f"{code}_*.csv"):
        df = pd.read_csv(f, index_col=0, parse_dates=True)
        for col in ["Close", "종가"]:
            if col in df.columns:
                return df[col].dropna()
        if len(df.columns) >= 4:
            return df.iloc[:, 3].dropna()
    return pd.Series(dtype=float)


def run_backtest(
    signal_returns: pd.Series,
    stock_close: pd.Series,
    threshold: float,
    tp_pct: float,
    sl_pct: float,
    max_hold: int,
) -> dict:
    """
    시그널 발생일 익일 매수 → TP/SL/최대보유일 청산.

    signal_returns: US 지표 일간 수익률
    stock_close: 한국 종목 종가
    threshold: > threshold면 BUY 시그널 (음수면 하락 시그널)
    """
    stock_ret = stock_close.pct_change()

    # 날짜 교집합
    common = signal_returns.index.intersection(stock_close.index)
    if len(common) < 200:
        return {"n": 0}

    sig = signal_returns.reindex(common)
    close = stock_close.reindex(common)

    trades = []
    i = 0
    dates = common.tolist()

    while i < len(dates) - max_hold - 1:
        sig_val = sig.iloc[i]

        # 시그널 체크
        if threshold > 0 and sig_val < threshold / 100:
            i += 1
            continue
        elif threshold < 0 and sig_val > threshold / 100:
            i += 1
            continue
        elif threshold == 0:
            i += 1
            continue

        # 익일 매수 (T+1)
        entry_idx = i + 1
        if entry_idx >= len(dates):
            break
        entry_price = close.iloc[entry_idx]
        if entry_price <= 0 or np.isnan(entry_price):
            i += 1
            continue

        # 보유 기간 동안 TP/SL 체크
        exit_pnl = None
        exit_day = 0
        for d in range(1, max_hold + 1):
            check_idx = entry_idx + d
            if check_idx >= len(dates):
                break
            cur_price = close.iloc[check_idx]
            if cur_price <= 0 or np.isnan(cur_price):
                continue
            pnl = (cur_price / entry_price - 1) * 100

            if pnl >= tp_pct:
                exit_pnl = pnl
                exit_day = d
                break
            elif pnl <= sl_pct:
                exit_pnl = pnl
                exit_day = d
                break

        if exit_pnl is None:
            # 최대 보유일 도달 → 종가 청산
            final_idx = min(entry_idx + max_hold, len(dates) - 1)
            final_price = close.iloc[final_idx]
            if final_price > 0 and not np.isnan(final_price):
                exit_pnl = (final_price / entry_price - 1) * 100
                exit_day = max_hold

        if exit_pnl is not None:
            trades.append({"pnl": exit_pnl, "days": exit_day})

        # 다음 시그널은 청산 후부터
        i = entry_idx + exit_day + 1 if exit_day > 0 else i + 1

    if not trades:
        return {"n": 0}

    pnls = [t["pnl"] for t in trades]
    wins = sum(1 for p in pnls if p > 0)

    return {
        "n": len(trades),
        "win_rate": round(wins / len(trades), 4),
        "avg_ret": round(np.mean(pnls), 4),
        "med_ret": round(np.median(pnls), 4),
        "edge": round(np.mean(pnls) * len(trades), 2),  # 누적 기대값
        "max_win": round(max(pnls), 2),
        "max_loss": round(min(pnls), 2),
        "avg_days": round(np.mean([t["days"] for t in trades]), 1),
    }


def main():
    print("=" * 70)
    print("확장 백테스팅: 코스피100 × 선행지표 전수 테스트")
    print("=" * 70)

    # 코스피100 종목 로드
    kr_stocks = {}
    for f in sorted(KOSPI_DIR.glob("*.csv")):
        code = f.stem.split("_")[0]
        name = f.stem.split("_", 1)[1] if "_" in f.stem else code
        series = load_kospi_stock(code)
        if len(series) >= 500:
            kr_stocks[code] = {"name": name, "close": series}

    print(f"한국 종목: {len(kr_stocks)}개 로드 (500일 이상)")

    # 선행지표 로드
    indicators = {}
    for key, (cat, fname, label) in LEADING_INDICATORS.items():
        series = load_close(cat, fname)
        if series.empty:
            continue
        ret = series.pct_change().dropna()
        if len(ret) >= 500:
            indicators[key] = {"label": label, "returns": ret}

    print(f"선행지표: {len(indicators)}개 로드")

    # 전수 테스트
    all_results = []
    total_combos = len(kr_stocks) * len(indicators) * (len(THRESHOLDS) + len(NEG_THRESHOLDS)) * len(TP_SL_SETS)
    print(f"테스트 조합: {total_combos:,}개")
    print()

    tested = 0
    significant = 0

    for code, stock_info in kr_stocks.items():
        stock_close = stock_info["close"]
        stock_name = stock_info["name"]

        for ind_key, ind_info in indicators.items():
            ind_ret = ind_info["returns"]
            ind_label = ind_info["label"]

            for thresholds in [THRESHOLDS, NEG_THRESHOLDS]:
                for thresh in thresholds:
                    for tpsl in TP_SL_SETS:
                        tested += 1

                        result = run_backtest(
                            signal_returns=ind_ret,
                            stock_close=stock_close,
                            threshold=thresh,
                            tp_pct=tpsl["tp"],
                            sl_pct=tpsl["sl"],
                            max_hold=tpsl["max_hold"],
                        )

                        if result["n"] < 30:
                            continue
                        if result["win_rate"] < 0.55:
                            continue
                        if result["avg_ret"] <= 0:
                            continue

                        significant += 1
                        row = {
                            "kr_code": code,
                            "kr_name": stock_name,
                            "indicator": ind_key,
                            "indicator_label": ind_label,
                            "threshold": thresh,
                            "direction": "BUY" if thresh > 0 else "SELL_SIGNAL",
                            "tp_pct": tpsl["tp"],
                            "sl_pct": tpsl["sl"],
                            "max_hold": tpsl["max_hold"],
                            "tpsl_label": tpsl["label"],
                            **result,
                        }
                        all_results.append(row)

        if tested % 5000 == 0:
            print(f"  진행: {tested:,}/{total_combos:,} ({tested/total_combos*100:.0f}%) → 유의미 {significant}건")

    print(f"\n완료: {tested:,}건 테스트, {significant}건 유의미")

    if not all_results:
        print("유의미한 결과 없음")
        return

    df = pd.DataFrame(all_results)
    df = df.sort_values("edge", ascending=False)

    # 전체 결과 저장
    df.to_csv(RESULT_DIR / "full_backtest_results.csv", index=False)

    # === 핵심 분석: 종목별 최고 전략 ===
    best_per_stock = df.groupby("kr_code").first().reset_index()
    best_per_stock.to_csv(RESULT_DIR / "best_strategy_per_stock.csv", index=False)

    # === 지표별 유효 종목 수 ===
    indicator_coverage = df.groupby("indicator").agg(
        n_stocks=("kr_code", "nunique"),
        avg_win_rate=("win_rate", "mean"),
        avg_ret=("avg_ret", "mean"),
        total_edge=("edge", "sum"),
    ).sort_values("total_edge", ascending=False)
    indicator_coverage.to_csv(RESULT_DIR / "indicator_effectiveness.csv")

    # === 전략 설정 업데이트용 JSON 생성 ===
    strategy_updates = []

    # 지표별 상위 종목 매핑
    for ind_key in df["indicator"].unique():
        sub = df[df["indicator"] == ind_key]
        # 최고 승률+기대값 조합
        best = sub.sort_values(["win_rate", "edge"], ascending=False).head(1)
        if best.empty:
            continue
        b = best.iloc[0]

        top_stocks = (
            sub.sort_values("edge", ascending=False)
            .drop_duplicates("kr_code")
            .head(10)
        )

        strategy_updates.append({
            "indicator": ind_key,
            "indicator_label": LEADING_INDICATORS.get(ind_key, ("", "", ind_key))[2] if ind_key in LEADING_INDICATORS else ind_key,
            "best_threshold": b["threshold"],
            "best_direction": b["direction"],
            "best_tp": b["tp_pct"],
            "best_sl": b["sl_pct"],
            "best_win_rate": b["win_rate"],
            "best_avg_ret": b["avg_ret"],
            "n_effective_stocks": len(top_stocks),
            "top_stocks": [
                {"code": r["kr_code"], "name": r["kr_name"],
                 "win_rate": r["win_rate"], "avg_ret": r["avg_ret"], "n": r["n"]}
                for _, r in top_stocks.iterrows()
            ],
        })

    strategy_updates.sort(key=lambda x: x["n_effective_stocks"], reverse=True)

    with open(RESULT_DIR / "strategy_signal_updates.json", "w", encoding="utf-8") as f:
        json.dump(strategy_updates, f, ensure_ascii=False, indent=2)

    # === 콘솔 요약 ===
    print("\n" + "=" * 70)
    print("유의미한 시그널 요약 (n≥30, 승률≥55%, 수익>0)")
    print("=" * 70)

    print(f"\n총 {len(df)}건 유의미 조합 발견")
    print(f"\n[지표별 유효성]")
    print(f"{'지표':20s} {'유효종목':>6s} {'평균승률':>8s} {'평균수익':>8s} {'누적기대값':>10s}")
    print("-" * 56)
    for _, r in indicator_coverage.head(15).iterrows():
        print(f"{r.name:20s} {r['n_stocks']:>6.0f} {r['avg_win_rate']*100:>7.1f}% {r['avg_ret']:>+7.3f}% {r['total_edge']:>10.1f}")

    print(f"\n[종목별 최고 전략 TOP 20]")
    print(f"{'종목':15s} {'지표':15s} {'임계':>5s} {'승률':>6s} {'수익':>7s} {'거래':>4s} {'기대값':>7s}")
    print("-" * 65)
    for _, r in best_per_stock.head(20).iterrows():
        print(f"{r['kr_name'][:12]:15s} {r['indicator']:15s} {r['threshold']:>+5.1f} {r['win_rate']*100:>5.1f}% {r['avg_ret']:>+6.3f}% {r['n']:>4.0f} {r['edge']:>7.1f}")

    print(f"\n결과 저장: {RESULT_DIR}")


if __name__ == "__main__":
    main()
