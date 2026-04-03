"""
30년치 확장 히스토리 데이터 수집.
기존 5년 데이터를 30년으로 확장하고, 선물/옵션/채권/매크로 등 추가 데이터 수집.

사용법:
  python data/history/fetch_extended_history.py          # 전체 수집
  python data/history/fetch_extended_history.py --category us   # US만

수집 카테고리:
  1. US 시장지수 (30년): NASDAQ, S&P500, DOW, SOX, Russell 2000
  2. US 개별종목 (20년+): NVDA, AMD, TSLA, AAPL, MSFT, GOOG, AMZN, META, QCOM 등
  3. 한국 시장 (20년): KOSPI, KOSDAQ, 주요 종목
  4. 원자재 (30년): WTI, 금, 은, 구리, 천연가스, 리튬
  5. 채권/금리 (30년): US 2Y/5Y/10Y/30Y, KR 국채
  6. 선물지수 (20년): VIX 선물, NASDAQ 선물, S&P500 선물
  7. 환율 (30년): USD/KRW, USD/JPY, DXY(달러인덱스), EUR/USD
  8. 신용/리스크 (20년): HY Spread, IG Spread, TED Spread 프록시
  9. 섹터 ETF (15년): 반도체(SOXX), 에너지(XLE), 금융(XLF), 기술(XLK), 헬스케어(XLV)
  10. 글로벌 지수 (20년): 닛케이225, 항셍, 독일DAX, 영국FTSE
"""

import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent
EXTENDED_DIR = ROOT / "extended"

# ═══════════════════════════════════════════════
# 수집 대상 정의
# ═══════════════════════════════════════════════

DATASETS = {
    "us_index": {
        "dir": "us_index",
        "period": "max",
        "tickers": {
            "nasdaq":     "^IXIC",
            "sp500":      "^GSPC",
            "dow":        "^DJI",
            "sox":        "^SOX",
            "russell2000": "^RUT",
            "nasdaq100":  "^NDX",
            "vix":        "^VIX",
        },
    },
    "us_stocks": {
        "dir": "us_stocks",
        "period": "max",
        "tickers": {
            "nvidia":   "NVDA",
            "amd":      "AMD",
            "tesla":    "TSLA",
            "apple":    "AAPL",
            "microsoft": "MSFT",
            "google":   "GOOGL",
            "amazon":   "AMZN",
            "meta":     "META",
            "qualcomm": "QCOM",
            "broadcom": "AVGO",
            "asml":     "ASML",
            "tsmc":     "TSM",
            "intel":    "INTC",
            "micron":   "MU",
            "lam_research": "LRCX",
            "applied_materials": "AMAT",
            "klac":     "KLAC",
        },
    },
    "kr_index": {
        "dir": "kr_index",
        "period": "max",
        "tickers": {
            "kospi":   "^KS11",
            "kosdaq":  "^KQ11",
            "ks200":   "^KS200",
        },
    },
    "kr_stocks": {
        "dir": "kr_stocks",
        "period": "max",
        "tickers": {
            "samsung":     "005930.KS",
            "sk_hynix":    "000660.KS",
            "lg_energy":   "373220.KS",
            "samsung_sdi": "006400.KS",
            "hanmi_semi":  "042700.KS",
            "sk_inno":     "096770.KS",
            "s_oil":       "010950.KS",
            "hyundai":     "005380.KS",
            "kia":         "000270.KS",
            "posco":       "005490.KS",
            "naver":       "035420.KS",
            "kakao":       "035720.KS",
            "celltrion":   "068270.KS",
            "samsung_bio": "207940.KS",
            "hanhwa_aero": "012450.KS",
            "lig_nex1":    "079550.KS",
            "doosan_enerbility": "034020.KS",
            "kepco_e_c":   "052690.KS",
        },
    },
    "commodities": {
        "dir": "commodities",
        "period": "max",
        "tickers": {
            "wti":          "CL=F",
            "brent":        "BZ=F",
            "gold":         "GC=F",
            "silver":       "SI=F",
            "copper":       "HG=F",
            "natural_gas":  "NG=F",
            "wheat":        "ZW=F",
            "corn":         "ZC=F",
            "soybean":      "ZS=F",
            "platinum":     "PL=F",
            "palladium":    "PA=F",
        },
    },
    "bonds": {
        "dir": "bonds",
        "period": "max",
        "tickers": {
            "us_2y":    "^IRX",     # 13-week T-bill (proxy for short-term)
            "us_5y":    "^FVX",     # 5-year Treasury
            "us_10y":   "^TNX",     # 10-year Treasury
            "us_30y":   "^TYX",     # 30-year Treasury
            "tlt":      "TLT",     # 20+ Year Treasury ETF
            "shy":      "SHY",     # 1-3 Year Treasury ETF
            "ief":      "IEF",     # 7-10 Year Treasury ETF
            "tip":      "TIP",     # TIPS (inflation-protected)
        },
    },
    "futures": {
        "dir": "futures",
        "period": "max",
        "tickers": {
            "sp500_fut":   "ES=F",
            "nasdaq_fut":  "NQ=F",
            "dow_fut":     "YM=F",
            "vix_fut":     "VX=F",
            "kospi200_fut": "^KS200",  # proxy
            "us_dollar":   "DX=F",     # Dollar Index Future
        },
    },
    "forex": {
        "dir": "forex",
        "period": "max",
        "tickers": {
            "usd_krw":  "KRW=X",
            "usd_jpy":  "JPY=X",
            "eur_usd":  "EURUSD=X",
            "gbp_usd":  "GBPUSD=X",
            "usd_cny":  "CNY=X",
            "dxy":      "DX-Y.NYB",   # Dollar Index
        },
    },
    "credit_risk": {
        "dir": "credit_risk",
        "period": "max",
        "tickers": {
            "hy_bond":     "HYG",    # High Yield Corporate Bond ETF
            "ig_bond":     "LQD",    # Investment Grade Bond ETF
            "junk_spread": "JNK",    # SPDR Junk Bond ETF
            "em_bond":     "EMB",    # Emerging Market Bond ETF
        },
    },
    "sector_etf": {
        "dir": "sector_etf",
        "period": "max",
        "tickers": {
            "semi_soxx":   "SOXX",   # Semiconductor ETF
            "energy_xle":  "XLE",    # Energy ETF
            "finance_xlf": "XLF",    # Financial ETF
            "tech_xlk":    "XLK",    # Technology ETF
            "health_xlv":  "XLV",    # Healthcare ETF
            "consumer_xly": "XLY",   # Consumer Discretionary
            "utility_xlu": "XLU",    # Utilities
            "materials_xlb": "XLB",  # Materials
            "industrial_xli": "XLI", # Industrials
            "real_estate": "VNQ",    # Real Estate
            "defense":     "ITA",    # Defense/Aerospace ETF
            "clean_energy": "ICLN",  # Clean Energy ETF
            "robotics":    "ROBO",   # Robotics/AI ETF
            "battery":     "LIT",    # Lithium/Battery ETF
        },
    },
    "global_index": {
        "dir": "global_index",
        "period": "max",
        "tickers": {
            "nikkei225":   "^N225",
            "hang_seng":   "^HSI",
            "shanghai":    "000001.SS",
            "dax":         "^GDAXI",
            "ftse100":     "^FTSE",
            "cac40":       "^FCHI",
            "bovespa":     "^BVSP",
            "sensex":      "^BSESN",
            "asx200":      "^AXJO",
            "taiwan":      "^TWII",
        },
    },
}


def fetch_category(category: str, dataset: dict) -> dict:
    """카테고리별 데이터 수집."""
    out_dir = EXTENDED_DIR / dataset["dir"]
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    tickers = dataset["tickers"]
    total = len(tickers)

    print(f"\n=== [{category}] {total}개 수집 시작 ===")

    for i, (name, ticker) in enumerate(tickers.items(), 1):
        csv_path = out_dir / f"{name}.csv"
        print(f"  [{i}/{total}] {name} ({ticker})...", end=" ", flush=True)

        try:
            data = yf.download(ticker, period=dataset["period"], progress=False, timeout=15)
            if data.empty:
                print("데이터 없음")
                results[name] = {"status": "empty", "rows": 0}
                continue

            # MultiIndex columns 처리
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)

            # 표준 OHLCV 컬럼만 저장
            cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
            data = data[cols].dropna(how="all")
            data.to_csv(csv_path)

            years = (data.index[-1] - data.index[0]).days / 365.25 if len(data) > 1 else 0
            print(f"{len(data)}행 ({years:.1f}년)")
            results[name] = {"status": "ok", "rows": len(data), "years": round(years, 1)}

        except Exception as e:
            print(f"실패: {e}")
            results[name] = {"status": "error", "error": str(e)}

        time.sleep(0.3)  # API 부하 방지

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", type=str, default=None,
                        help="특정 카테고리만 수집 (예: us_index, kr_stocks)")
    args = parser.parse_args()

    EXTENDED_DIR.mkdir(parents=True, exist_ok=True)

    all_results = {}

    if args.category:
        if args.category not in DATASETS:
            print(f"알 수 없는 카테고리: {args.category}")
            print(f"사용 가능: {', '.join(DATASETS.keys())}")
            return
        categories = {args.category: DATASETS[args.category]}
    else:
        categories = DATASETS

    for cat_name, dataset in categories.items():
        results = fetch_category(cat_name, dataset)
        all_results[cat_name] = results

    # 요약 출력
    print("\n" + "=" * 60)
    print("수집 완료 요약")
    print("=" * 60)
    total_files = 0
    total_rows = 0
    for cat, results in all_results.items():
        ok = sum(1 for r in results.values() if r.get("status") == "ok")
        rows = sum(r.get("rows", 0) for r in results.values())
        total_files += ok
        total_rows += rows
        print(f"  {cat:20s}: {ok}/{len(results)}개 성공, {rows:,}행")
    print(f"\n  총계: {total_files}개 파일, {total_rows:,}행")

    # 결과 JSON 저장
    import json
    summary_path = EXTENDED_DIR / "collection_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n요약 저장: {summary_path}")


if __name__ == "__main__":
    main()
