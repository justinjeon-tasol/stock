"""
히스토리 데이터 수집 스크립트
yfinance와 pykrx를 사용하여 미국/한국/원자재 과거 데이터를 로컬에 저장.

사용법:
    python data/history/fetch_history.py              # 전체 수집 (5년)
    python data/history/fetch_history.py --update     # 최근 30일만 업데이트
    python data/history/fetch_history.py --section us # 미국 데이터만
    python data/history/fetch_history.py --section kr # 한국 데이터만
    python data/history/fetch_history.py --section commodity # 원자재만
    python data/history/fetch_history.py --section correlation # 상관관계 계산만
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

# 경로 설정
HIST_DIR = Path(__file__).parent
US_DIR   = HIST_DIR / "us_market"
KR_DIR   = HIST_DIR / "kr_market"
COM_DIR  = HIST_DIR / "commodity"
COR_DIR  = HIST_DIR / "correlation"

# 디렉터리 자동 생성 (없으면 fetch 중 에러나던 것 방지)
for _d in (US_DIR, KR_DIR, COM_DIR, COR_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────
# 1. 미국 시장 히스토리 (yfinance)
# ──────────────────────────────────────────────

US_TICKERS = {
    # 지수 ETF / 선물 (지수 대용)
    "nasdaq":  "QQQ",     # 나스닥100 ETF
    "sp500":   "SPY",     # S&P500 ETF
    "sox":     "SOXX",    # 필라델피아 반도체 ETF
    "vix":     "^VIX",    # VIX 지수
    # 개별 종목 (한국 시장 선행)
    "nvidia":  "NVDA",
    "amd":     "AMD",
    "tsmc":    "TSM",     # TSMC ADR
    "tesla":   "TSLA",
    "apple":   "AAPL",
    # 매크로
    "usd_krw": "KRW=X",   # 원/달러 환율
    "gold":    "GC=F",    # 금 선물
    "oil_wti": "CL=F",    # WTI 원유 선물
    "copper":  "HG=F",    # 구리 선물
    "us10y":   "^TNX",    # 미국 10년물 금리
}


def fetch_us_history(start: str, end: str, update_only: bool = False) -> dict[str, pd.DataFrame]:
    """미국 시장 데이터를 yfinance로 수집하여 CSV 저장."""
    results = {}
    for name, ticker in US_TICKERS.items():
        csv_path = US_DIR / f"{name}.csv"

        # 업데이트 모드: 기존 파일의 마지막 날짜 이후만 수집
        if update_only and csv_path.exists():
            existing = pd.read_csv(csv_path, index_col=0, parse_dates=True)
            last_date = existing.index.max()
            start = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
            if start >= end:
                print(f"  [{name}] 이미 최신 ({last_date.date()})")
                results[name] = existing
                continue

        try:
            df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
            if df.empty:
                print(f"  [{name}] 데이터 없음 (ticker={ticker})")
                continue

            # 컬럼 단순화
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            # 업데이트 모드: 기존 데이터에 붙이기
            if update_only and csv_path.exists():
                existing = pd.read_csv(csv_path, index_col=0, parse_dates=True)
                df = pd.concat([existing, df])
                df = df[~df.index.duplicated(keep="last")]
                df.sort_index(inplace=True)

            df.to_csv(csv_path)
            print(f"  [{name}] {len(df)}행 저장 → {csv_path.name}")
            results[name] = df

        except Exception as e:
            print(f"  [{name}] 오류: {e}")

    return results


# ──────────────────────────────────────────────
# 2. 원자재 히스토리 (yfinance)
# ──────────────────────────────────────────────

COMMODITY_TICKERS = {
    "wti":     "CL=F",     # WTI 원유
    "gold":    "GC=F",     # 금
    "silver":  "SI=F",     # 은
    "copper":  "HG=F",     # 구리
    "lithium": "LIT",      # 리튬 ETF (Global X Lithium & Battery Tech)
    "natgas":  "NG=F",     # 천연가스
    "wheat":   "ZW=F",     # 소맥 (지정학 지표)
}


def fetch_commodity_history(start: str, end: str, update_only: bool = False) -> dict[str, pd.DataFrame]:
    """원자재 데이터 수집 및 저장."""
    results = {}
    for name, ticker in COMMODITY_TICKERS.items():
        csv_path = COM_DIR / f"{name}.csv"

        if update_only and csv_path.exists():
            existing = pd.read_csv(csv_path, index_col=0, parse_dates=True)
            last_date = existing.index.max()
            start_adj = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
            if start_adj >= end:
                print(f"  [{name}] 이미 최신 ({last_date.date()})")
                results[name] = existing
                continue
        else:
            start_adj = start

        try:
            df = yf.download(ticker, start=start_adj, end=end, progress=False, auto_adjust=True)
            if df.empty:
                print(f"  [{name}] 데이터 없음 (ticker={ticker})")
                continue

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            if update_only and csv_path.exists():
                existing = pd.read_csv(csv_path, index_col=0, parse_dates=True)
                df = pd.concat([existing, df])
                df = df[~df.index.duplicated(keep="last")]
                df.sort_index(inplace=True)

            df.to_csv(csv_path)
            print(f"  [{name}] {len(df)}행 저장 → {csv_path.name}")
            results[name] = df

        except Exception as e:
            print(f"  [{name}] 오류: {e}")

    return results


# ──────────────────────────────────────────────
# 3. 한국 시장 히스토리 (pykrx)
# ──────────────────────────────────────────────

KR_INDICES_YF = {
    "KOSPI":  "^KS11",    # KOSPI 종합
    "KOSDAQ": "^KQ11",    # KOSDAQ 종합
    "KS200":  "^KS200",   # KOSPI200
}

# 기존 전략(STR_001~007)이 참조하는 10개 — backtest_engine.py SYMBOL_MAP과 호환 유지
_KR_STOCKS_NAMED = {
    "samsung":  "005930",   # 삼성전자
    "sk_hynix": "000660",   # SK하이닉스
    "lg_energy":"373220",   # LG에너지솔루션
    "samsung_sdi":"006400", # 삼성SDI
    "hanmi_semi": "042700", # 한미반도체
    "sk_inno":  "096770",   # SK이노베이션
    "posco":    "005490",   # POSCO
    "kakao":    "035720",   # 카카오
    "naver":    "035420",   # 네이버
    "hyundai":  "005380",   # 현대차
}


def _load_kospi200_universe() -> dict[str, str]:
    """
    tradingview-1 seed JSON에서 KOSPI200 구성종목 로드.
    반환: {파일명_slug: 종목코드} — 코드 기반(stock_005930.csv 형식).
    기존 _KR_STOCKS_NAMED에 있는 코드는 중복 제외 (named 파일이 우선).
    """
    import json
    seed_path = Path(__file__).resolve().parent.parent.parent / "data" / "seed" / "kospi200.json"
    if not seed_path.exists():
        return {}
    try:
        with open(seed_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"  [KR] kospi200.json 로드 실패: {e}")
        return {}

    existing_codes = set(_KR_STOCKS_NAMED.values())
    result: dict[str, str] = {}
    for s in data.get("stocks", []):
        code = s.get("code")
        if not code or code in existing_codes:
            continue
        # 파일명 slug는 코드 그대로 (stock_005930.csv)
        result[code] = code
    return result


# 최종 KR_STOCKS = named 10개 + kospi200 증분 (총 ~200)
KR_STOCKS = {**_KR_STOCKS_NAMED, **_load_kospi200_universe()}


def fetch_kr_history(start: str, end: str, update_only: bool = False) -> dict[str, pd.DataFrame]:
    """yfinance(지수) + pykrx(개별종목)로 한국 데이터 수집."""
    try:
        from pykrx import stock as pykrx_stock
        _has_pykrx = True
    except ImportError:
        print("  [KR] pykrx 미설치 - 개별종목 수집 불가")
        _has_pykrx = False

    results = {}

    # 지수 데이터 - yfinance 사용 (pykrx 지수 API는 인코딩 버그로 오류 발생)
    for name, ticker in KR_INDICES_YF.items():
        csv_path = KR_DIR / f"index_{name}.csv"

        if update_only and csv_path.exists():
            existing = pd.read_csv(csv_path, index_col=0, parse_dates=True)
            last_date = existing.index.max()
            start_adj = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
            if start_adj >= end:
                print(f"  [{name}] 이미 최신 ({last_date.date()})")
                results[f"index_{name}"] = existing
                continue
        else:
            start_adj = start

        try:
            df = yf.download(ticker, start=start_adj, end=end, progress=False, auto_adjust=True)
            if df.empty:
                print(f"  [{name}] 데이터 없음 (ticker={ticker})")
                continue

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            if update_only and csv_path.exists():
                existing = pd.read_csv(csv_path, index_col=0, parse_dates=True)
                df = pd.concat([existing, df])
                df = df[~df.index.duplicated(keep="last")]
                df.sort_index(inplace=True)

            df.to_csv(csv_path)
            print(f"  [{name}] {len(df)}행 저장 -> {csv_path.name}")
            results[f"index_{name}"] = df

        except Exception as e:
            print(f"  [{name}] 오류: {e}")

    if not _has_pykrx:
        return results

    # 날짜 형식 변환 (pykrx는 YYYYMMDD)
    start_pykrx = start.replace("-", "")
    end_pykrx   = end.replace("-", "")

    # 개별 종목 데이터
    for name, code in KR_STOCKS.items():
        csv_path = KR_DIR / f"stock_{name}.csv"

        if update_only and csv_path.exists():
            existing = pd.read_csv(csv_path, index_col=0, parse_dates=True)
            last_date = existing.index.max()
            start_adj = (last_date + timedelta(days=1)).strftime("%Y%m%d")
            if start_adj >= end_pykrx:
                print(f"  [{name}] 이미 최신 ({last_date.date()})")
                results[f"stock_{name}"] = existing
                continue
        else:
            start_adj = start_pykrx

        try:
            df = pykrx_stock.get_market_ohlcv_by_date(start_adj, end_pykrx, code)
            if df is None or df.empty:
                print(f"  [{name}] 데이터 없음")
                continue

            if update_only and csv_path.exists():
                existing = pd.read_csv(csv_path, index_col=0, parse_dates=True)
                df = pd.concat([existing, df])
                df = df[~df.index.duplicated(keep="last")]
                df.sort_index(inplace=True)

            df.to_csv(csv_path)
            print(f"  [{name}] {len(df)}행 저장 → {csv_path.name}")
            results[f"stock_{name}"] = df

        except Exception as e:
            print(f"  [{name}] 오류: {e}")

    return results


# ──────────────────────────────────────────────
# 4. 미-한 상관관계 분석
# ──────────────────────────────────────────────

def compute_correlation() -> None:
    """저장된 CSV에서 미-한 상관관계 계산 후 저장."""
    # 미국 지수 종가
    us_files = {
        "QQQ(나스닥)":  US_DIR / "nasdaq.csv",
        "SOXX(SOX)":   US_DIR / "sox.csv",
        "SPY(S&P500)": US_DIR / "sp500.csv",
        "NVDA":        US_DIR / "nvidia.csv",
        "AMD":         US_DIR / "amd.csv",
    }
    # 한국 지수/종목 종가
    kr_files = {
        "KOSPI":        KR_DIR / "index_KOSPI.csv",
        "KOSDAQ":       KR_DIR / "index_KOSDAQ.csv",
        "삼성전자":     KR_DIR / "stock_samsung.csv",
        "SK하이닉스":   KR_DIR / "stock_sk_hynix.csv",
    }

    closes = {}

    # 미국 - 'Close' 컬럼
    for label, path in us_files.items():
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            col = "Close" if "Close" in df.columns else df.columns[3]  # OHLCV에서 종가
            closes[label] = df[col]
        except Exception as e:
            print(f"  [corr] {label} 로드 오류: {e}")

    # 한국 - pykrx 컬럼명이 다름 ('종가')
    for label, path in kr_files.items():
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            col = "종가" if "종가" in df.columns else ("Close" if "Close" in df.columns else df.columns[3])
            closes[label] = df[col]
        except Exception as e:
            print(f"  [corr] {label} 로드 오류: {e}")

    if len(closes) < 2:
        print("  [corr] 데이터 부족 - 먼저 us/kr 히스토리를 수집하세요")
        return

    # 일간 수익률로 변환
    price_df = pd.DataFrame(closes).dropna(how="all")
    returns_df = price_df.pct_change().dropna(how="all")

    # 전체 기간 상관관계
    full_corr = returns_df.corr()
    full_corr.to_csv(COR_DIR / "full_period_correlation.csv")
    print(f"  [corr] 전체 기간 상관관계 저장 ({len(returns_df)}거래일)")

    # 연도별 상관관계 (rolling 252일)
    rolling_corr_list = []
    for year in returns_df.index.year.unique():
        year_df = returns_df[returns_df.index.year == year]
        if len(year_df) < 20:
            continue
        corr = year_df.corr()
        corr.index   = pd.MultiIndex.from_tuples([(year, r) for r in corr.index])
        corr.columns = pd.MultiIndex.from_tuples([(year, c) for c in corr.columns])
        rolling_corr_list.append(corr)

    if rolling_corr_list:
        # 간단히 각 연도 KOSPI vs 미국 지수 상관관계 요약
        summary_rows = []
        for corr in rolling_corr_list:
            year = corr.index[0][0]
            for us_label in [l for l in ["QQQ(나스닥)", "SOXX(SOX)", "SPY(S&P500)"] if l in returns_df.columns]:
                for kr_label in [l for l in ["KOSPI", "KOSDAQ"] if l in returns_df.columns]:
                    try:
                        val = corr.loc[(year, kr_label), (year, us_label)]
                        summary_rows.append({"year": year, "us": us_label, "kr": kr_label, "correlation": round(val, 4)})
                    except KeyError:
                        pass

        if summary_rows:
            summary_df = pd.DataFrame(summary_rows)
            summary_df.to_csv(COR_DIR / "yearly_correlation_summary.csv", index=False)
            print(f"  [corr] 연도별 상관관계 요약 저장 ({len(summary_df)}행)")

    # 리드-래그 분석 (미국 t-0 vs 한국 t+1)
    if "QQQ(나스닥)" in returns_df.columns and "KOSPI" in returns_df.columns:
        lag_results = []
        for lag in range(0, 4):  # 0~3일 후행
            shifted_kr = returns_df["KOSPI"].shift(-lag)
            corr_val = returns_df["QQQ(나스닥)"].corr(shifted_kr)
            lag_results.append({"lag_days": lag, "us_index": "QQQ(나스닥)", "kr_index": "KOSPI", "correlation": round(corr_val, 4)})

        lag_df = pd.DataFrame(lag_results)
        lag_df.to_csv(COR_DIR / "lead_lag_analysis.csv", index=False)
        print(f"  [corr] 리드-래그 분석 저장")


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="히스토리 데이터 수집")
    parser.add_argument("--update",  action="store_true", help="최근 30일만 업데이트")
    parser.add_argument("--section", choices=["us", "kr", "commodity", "correlation", "all"],
                        default="all", help="수집할 섹션")
    parser.add_argument("--years",   type=int, default=5, help="수집 연수 (기본 5년)")
    args = parser.parse_args()

    today     = datetime.now()
    end_date  = today.strftime("%Y-%m-%d")
    if args.update:
        start_date = (today - timedelta(days=30)).strftime("%Y-%m-%d")
        print(f"=== 업데이트 모드: 최근 30일 ({start_date} ~ {end_date}) ===")
    else:
        start_date = (today - timedelta(days=365 * args.years)).strftime("%Y-%m-%d")
        print(f"=== 전체 수집: {args.years}년 ({start_date} ~ {end_date}) ===")

    if args.section in ("us", "all"):
        print("\n[1] 미국 시장 히스토리 수집...")
        fetch_us_history(start_date, end_date, update_only=args.update)

    if args.section in ("commodity", "all"):
        print("\n[2] 원자재 히스토리 수집...")
        fetch_commodity_history(start_date, end_date, update_only=args.update)

    if args.section in ("kr", "all"):
        print("\n[3] 한국 시장 히스토리 수집...")
        fetch_kr_history(start_date, end_date, update_only=args.update)

    if args.section in ("correlation", "all"):
        print("\n[4] 미-한 상관관계 계산...")
        compute_correlation()

    print("\n완료!")


if __name__ == "__main__":
    main()
