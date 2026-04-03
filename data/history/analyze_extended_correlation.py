"""
확장 데이터 상관관계 분석.
764,739행의 데이터에서 한국 주식과의 선행/동행/후행 상관관계를 분석한다.

분석 내용:
  1. KOSPI vs 모든 글로벌 지표 상관관계 (lag 0~5일)
  2. 한국 주요 종목 vs US 섹터/개별종목 상관관계
  3. 매크로 지표(금리, 환율, 원자재) vs KOSPI 상관관계
  4. VIX 구간별 KOSPI 수익률 분포
  5. 새로운 선행 시그널 발굴

사용법: python data/history/analyze_extended_correlation.py
출력: data/history/extended/analysis/ 폴더에 CSV/JSON 저장
"""

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent / "extended"
ANALYSIS_DIR = ROOT / "analysis"
ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)


def load_close(category: str, name: str) -> pd.Series:
    """카테고리/이름으로 종가 시리즈 로드."""
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


def calc_returns(series: pd.Series) -> pd.Series:
    """일간 수익률."""
    return series.pct_change().dropna()


def lead_lag_correlation(leader: pd.Series, follower: pd.Series, max_lag: int = 5) -> dict:
    """
    leader가 follower를 선행하는 상관관계 분석.
    lag=1: leader[T] vs follower[T+1] (leader가 1일 선행)
    """
    leader_ret = calc_returns(leader)
    follower_ret = calc_returns(follower)

    # 날짜 교집합
    common = leader_ret.index.intersection(follower_ret.index)
    if len(common) < 100:
        return {}

    lr = leader_ret.reindex(common).dropna()
    fr = follower_ret.reindex(common).dropna()
    common2 = lr.index.intersection(fr.index)
    lr = lr.reindex(common2)
    fr = fr.reindex(common2)

    results = {}
    for lag in range(0, max_lag + 1):
        if lag == 0:
            corr = lr.corr(fr)
        else:
            corr = lr.iloc[:-lag].reset_index(drop=True).corr(
                fr.iloc[lag:].reset_index(drop=True)
            )
        results[f"lag_{lag}"] = round(corr, 4) if not np.isnan(corr) else 0.0

    results["n_obs"] = len(common2)
    results["best_lag"] = max(
        [(k, abs(v)) for k, v in results.items() if k.startswith("lag_")],
        key=lambda x: x[1], default=("lag_0", 0)
    )[0]
    results["best_corr"] = results.get(results["best_lag"], 0)

    return results


def analyze_all_vs_kospi():
    """모든 글로벌 지표 vs KOSPI 상관관계."""
    print("=== 1. 모든 지표 vs KOSPI 상관관계 ===")

    kospi = load_close("kr_index", "kospi")
    if kospi.empty:
        # 기존 데이터에서 시도
        alt = Path(__file__).resolve().parent / "kr_market" / "index_KOSPI.csv"
        if alt.exists():
            df = pd.read_csv(alt, index_col=0, parse_dates=True)
            kospi = df["Close"].dropna() if "Close" in df.columns else df.iloc[:, 3].dropna()

    if kospi.empty:
        print("  KOSPI 데이터 없음, 건너뜀")
        return pd.DataFrame()

    categories = [
        ("us_index", ["nasdaq", "sp500", "dow", "sox", "russell2000", "nasdaq100", "vix"]),
        ("us_stocks", ["nvidia", "amd", "tesla", "apple", "microsoft", "google",
                       "amazon", "meta", "qualcomm", "broadcom", "asml", "tsmc",
                       "intel", "micron", "lam_research", "applied_materials", "klac"]),
        ("commodities", ["wti", "brent", "gold", "silver", "copper", "natural_gas",
                         "wheat", "corn", "soybean", "platinum"]),
        ("bonds", ["us_2y", "us_5y", "us_10y", "us_30y", "tlt", "shy", "ief", "tip"]),
        ("futures", ["sp500_fut", "nasdaq_fut", "dow_fut"]),
        ("forex", ["usd_krw", "usd_jpy", "eur_usd", "gbp_usd", "usd_cny", "dxy"]),
        ("credit_risk", ["hy_bond", "ig_bond", "junk_spread", "em_bond"]),
        ("sector_etf", ["semi_soxx", "energy_xle", "finance_xlf", "tech_xlk",
                        "health_xlv", "consumer_xly", "utility_xlu", "materials_xlb",
                        "industrial_xli", "real_estate", "defense", "clean_energy",
                        "robotics", "battery"]),
        ("global_index", ["nikkei225", "hang_seng", "shanghai", "dax", "ftse100",
                          "cac40", "bovespa", "sensex", "asx200", "taiwan"]),
    ]

    rows = []
    for cat, names in categories:
        for name in names:
            series = load_close(cat, name)
            if series.empty:
                continue
            corr = lead_lag_correlation(series, kospi, max_lag=5)
            if not corr:
                continue
            rows.append({
                "category": cat,
                "indicator": name,
                "lag_0": corr.get("lag_0", 0),
                "lag_1": corr.get("lag_1", 0),
                "lag_2": corr.get("lag_2", 0),
                "lag_3": corr.get("lag_3", 0),
                "best_lag": corr.get("best_lag", ""),
                "best_corr": corr.get("best_corr", 0),
                "n_obs": corr.get("n_obs", 0),
            })
            print(f"  {cat}/{name}: lag1={corr.get('lag_1', 0):+.3f} best={corr.get('best_lag', '')}={corr.get('best_corr', 0):+.3f} (n={corr.get('n_obs', 0)})")

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("best_corr", key=abs, ascending=False)
        df.to_csv(ANALYSIS_DIR / "all_vs_kospi_correlation.csv", index=False)
        print(f"\n  저장: {len(df)}개 지표 분석 완료")

    return df


def analyze_kr_stock_correlations():
    """한국 주요 종목 vs US 지표 상관관계."""
    print("\n=== 2. 한국 종목 vs US 지표 상관관계 ===")

    kr_stocks = {
        "samsung": "kr_stocks",
        "sk_hynix": "kr_stocks",
        "lg_energy": "kr_stocks",
        "samsung_sdi": "kr_stocks",
        "hanmi_semi": "kr_stocks",
        "sk_inno": "kr_stocks",
        "s_oil": "kr_stocks",
        "hyundai": "kr_stocks",
        "naver": "kr_stocks",
        "posco": "kr_stocks",
        "celltrion": "kr_stocks",
        "hanhwa_aero": "kr_stocks",
    }

    us_indicators = [
        ("us_index", "nasdaq"), ("us_index", "sox"), ("us_index", "vix"),
        ("us_stocks", "nvidia"), ("us_stocks", "amd"), ("us_stocks", "tesla"),
        ("us_stocks", "apple"), ("us_stocks", "microsoft"),
        ("commodities", "wti"), ("commodities", "gold"), ("commodities", "copper"),
        ("forex", "usd_krw"),
        ("bonds", "us_10y"),
        ("sector_etf", "semi_soxx"), ("sector_etf", "energy_xle"),
        ("sector_etf", "battery"), ("sector_etf", "defense"),
    ]

    rows = []
    for kr_name, kr_cat in kr_stocks.items():
        kr_series = load_close(kr_cat, kr_name)
        if kr_series.empty:
            continue

        for us_cat, us_name in us_indicators:
            us_series = load_close(us_cat, us_name)
            if us_series.empty:
                continue
            corr = lead_lag_correlation(us_series, kr_series, max_lag=3)
            if not corr or corr.get("n_obs", 0) < 100:
                continue
            rows.append({
                "kr_stock": kr_name,
                "us_indicator": us_name,
                "us_category": us_cat,
                "lag_0": corr.get("lag_0", 0),
                "lag_1": corr.get("lag_1", 0),
                "lag_2": corr.get("lag_2", 0),
                "best_lag": corr.get("best_lag", ""),
                "best_corr": corr.get("best_corr", 0),
                "n_obs": corr.get("n_obs", 0),
            })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("best_corr", key=abs, ascending=False)
        df.to_csv(ANALYSIS_DIR / "kr_stock_vs_us_correlation.csv", index=False)
        # 종목별 최고 상관 지표 출력
        for kr in kr_stocks:
            sub = df[df["kr_stock"] == kr].head(3)
            if sub.empty:
                continue
            top = sub.iloc[0]
            print(f"  {kr}: 최고상관={top['us_indicator']} lag1={top['lag_1']:+.3f} (n={top['n_obs']})")
        print(f"\n  저장: {len(df)}행")

    return df


def analyze_vix_regime():
    """VIX 구간별 KOSPI 수익률 분포."""
    print("\n=== 3. VIX 구간별 KOSPI 수익률 ===")

    vix = load_close("us_index", "vix")
    kospi = load_close("kr_index", "kospi")
    if vix.empty or kospi.empty:
        print("  데이터 부족")
        return

    kospi_ret = calc_returns(kospi)
    common = vix.index.intersection(kospi_ret.index)
    vix_c = vix.reindex(common).dropna()
    kr_c = kospi_ret.reindex(common).dropna()
    common2 = vix_c.index.intersection(kr_c.index)
    vix_c = vix_c.reindex(common2)
    kr_c = kr_c.reindex(common2)

    bins = [(0, 15, "VIX<15 안정"), (15, 20, "VIX 15-20 보통"), (20, 25, "VIX 20-25 경계"),
            (25, 30, "VIX 25-30 불안"), (30, 40, "VIX 30-40 공포"), (40, 100, "VIX>40 패닉")]

    rows = []
    for low, high, label in bins:
        mask = (vix_c >= low) & (vix_c < high)
        subset = kr_c[mask]
        if len(subset) < 10:
            continue
        rows.append({
            "vix_range": label,
            "days": len(subset),
            "mean_ret": round(subset.mean() * 100, 3),
            "median_ret": round(subset.median() * 100, 3),
            "std_ret": round(subset.std() * 100, 3),
            "win_rate": round((subset > 0).mean() * 100, 1),
            "max_gain": round(subset.max() * 100, 2),
            "max_loss": round(subset.min() * 100, 2),
        })
        print(f"  {label}: {len(subset)}일, 평균={subset.mean()*100:+.3f}%, 승률={((subset>0).mean()*100):.1f}%")

    df = pd.DataFrame(rows)
    df.to_csv(ANALYSIS_DIR / "vix_regime_kospi.csv", index=False)


def discover_new_signals():
    """새로운 선행 시그널 발굴: |lag_1| > 0.15인 지표."""
    print("\n=== 4. 새로운 선행 시그널 발굴 ===")

    csv_path = ANALYSIS_DIR / "all_vs_kospi_correlation.csv"
    if not csv_path.exists():
        print("  상관관계 데이터 없음")
        return

    df = pd.read_csv(csv_path)
    # lag_1 > 0.15: 선행 상관이 의미 있는 지표
    signals = df[df["lag_1"].abs() > 0.15].sort_values("lag_1", key=abs, ascending=False)

    if signals.empty:
        print("  유의미한 선행 시그널 없음")
        return

    print(f"\n  선행 상관 |lag_1| > 0.15인 지표 {len(signals)}개:")
    print(f"  {'지표':25s} {'카테고리':15s} {'lag_1':>8s} {'lag_0':>8s} {'관측수':>6s}")
    print("  " + "-" * 65)

    new_signals = []
    for _, row in signals.iterrows():
        direction = "BUY" if row["lag_1"] > 0 else "AVOID"
        print(f"  {row['indicator']:25s} {row['category']:15s} {row['lag_1']:+8.3f} {row['lag_0']:+8.3f} {row['n_obs']:6.0f}")
        new_signals.append({
            "indicator": row["indicator"],
            "category": row["category"],
            "lag_1_corr": row["lag_1"],
            "direction": direction,
            "strength": abs(row["lag_1"]),
            "n_obs": int(row["n_obs"]),
        })

    with open(ANALYSIS_DIR / "new_leading_signals.json", "w", encoding="utf-8") as f:
        json.dump(new_signals, f, ensure_ascii=False, indent=2)
    print(f"\n  저장: new_leading_signals.json ({len(new_signals)}개)")


def analyze_bond_stock_relation():
    """채권-주식 상관관계 (금리 역상관)."""
    print("\n=== 5. 채권/금리 vs KOSPI 관계 ===")

    kospi = load_close("kr_index", "kospi")
    kospi_ret = calc_returns(kospi)

    bond_names = ["us_2y", "us_5y", "us_10y", "us_30y", "tlt", "shy", "ief", "tip"]
    rows = []
    for name in bond_names:
        series = load_close("bonds", name)
        if series.empty:
            continue
        corr = lead_lag_correlation(series, kospi, max_lag=5)
        if not corr:
            continue
        rows.append({"bond": name, **corr})
        print(f"  {name}: lag0={corr.get('lag_0', 0):+.3f} lag1={corr.get('lag_1', 0):+.3f} best={corr.get('best_lag', '')}={corr.get('best_corr', 0):+.3f}")

    if rows:
        pd.DataFrame(rows).to_csv(ANALYSIS_DIR / "bond_vs_kospi.csv", index=False)


def main():
    print("확장 데이터 상관관계 분석 시작")
    print("=" * 60)

    analyze_all_vs_kospi()
    analyze_kr_stock_correlations()
    analyze_vix_regime()
    analyze_bond_stock_relation()
    discover_new_signals()

    print("\n" + "=" * 60)
    print("분석 완료. 결과: data/history/extended/analysis/")
    print("  - all_vs_kospi_correlation.csv")
    print("  - kr_stock_vs_us_correlation.csv")
    print("  - vix_regime_kospi.csv")
    print("  - bond_vs_kospi.csv")
    print("  - new_leading_signals.json")


if __name__ == "__main__":
    main()
