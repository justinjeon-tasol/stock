"""
히스토리 데이터 로더
에이전트들이 저장된 과거 데이터를 빠르게 조회할 수 있는 유틸리티.

사용 예:
    from data.history.history_loader import HistoryLoader

    hl = HistoryLoader()
    kospi_z  = hl.z_score("KOSPI", -2.5)          # 현재 등락률의 역사적 Z-score
    vix_pct  = hl.percentile("vix", 32.5)          # VIX 32.5가 몇 번째 백분위인지
    corr     = hl.get_lead_lag_corr("QQQ(나스닥)", "KOSPI", lag=1)  # 1일 후행 상관관계
"""

import os
from functools import lru_cache
from pathlib import Path

from typing import Optional

import numpy as np
import pandas as pd

HIST_DIR = Path(__file__).parent
US_DIR   = HIST_DIR / "us_market"
KR_DIR   = HIST_DIR / "kr_market"
COM_DIR  = HIST_DIR / "commodity"
COR_DIR  = HIST_DIR / "correlation"

# extended/ 폴백 경로 (GCP 등 us_market/kr_market 폴더가 없는 환경)
_EXT_DIR       = HIST_DIR / "extended"
_EXT_US_IDX    = _EXT_DIR / "us_index"
_EXT_US_STK    = _EXT_DIR / "us_stocks"
_EXT_KR_IDX    = _EXT_DIR / "kr_index"
_EXT_KR_STK    = _EXT_DIR / "kr_stocks"
_EXT_COM       = _EXT_DIR / "commodities"
_EXT_FOREX     = _EXT_DIR / "forex"
_EXT_BONDS     = _EXT_DIR / "bonds"

# 에이전트에서 사용할 심볼 → 파일명 매핑 (기본 경로)
_SYMBOL_MAP = {
    # 미국 지수
    "nasdaq":  US_DIR / "nasdaq.csv",
    "sox":     US_DIR / "sox.csv",
    "sp500":   US_DIR / "sp500.csv",
    "vix":     US_DIR / "vix.csv",
    "nvidia":  US_DIR / "nvidia.csv",
    "amd":     US_DIR / "amd.csv",
    "tsmc":    US_DIR / "tsmc.csv",
    "tesla":   US_DIR / "tesla.csv",
    "usd_krw": US_DIR / "usd_krw.csv",
    "us10y":   US_DIR / "us10y.csv",
    # 원자재
    "wti":     COM_DIR / "wti.csv",
    "gold":    COM_DIR / "gold.csv",
    "silver":  COM_DIR / "silver.csv",
    "copper":  COM_DIR / "copper.csv",
    "lithium": COM_DIR / "lithium.csv",
    "natgas":  COM_DIR / "natgas.csv",
    # 한국 지수 (yfinance 기준)
    "KOSPI":   KR_DIR / "index_KOSPI.csv",
    "KOSDAQ":  KR_DIR / "index_KOSDAQ.csv",
    "KS200":   KR_DIR / "index_KS200.csv",
    # 한국 종목
    "samsung":     KR_DIR / "stock_samsung.csv",
    "sk_hynix":    KR_DIR / "stock_sk_hynix.csv",
    "lg_energy":   KR_DIR / "stock_lg_energy.csv",
    "samsung_sdi": KR_DIR / "stock_samsung_sdi.csv",
    "hanmi_semi":  KR_DIR / "stock_hanmi_semi.csv",
    "sk_inno":     KR_DIR / "stock_sk_inno.csv",
    "posco":       KR_DIR / "stock_posco.csv",
    "kakao":       KR_DIR / "stock_kakao.csv",
    "naver":       KR_DIR / "stock_naver.csv",
    "hyundai":     KR_DIR / "stock_hyundai.csv",
}

# extended/ 폴백 매핑 (기본 경로 파일이 없을 때 사용)
_SYMBOL_MAP_FALLBACK = {
    # 미국 지수/종목
    "nasdaq":  _EXT_US_IDX / "nasdaq.csv",
    "sox":     _EXT_US_IDX / "sox.csv",
    "sp500":   _EXT_US_IDX / "sp500.csv",
    "vix":     _EXT_US_IDX / "vix.csv",
    "nvidia":  _EXT_US_STK / "nvidia.csv",
    "amd":     _EXT_US_STK / "amd.csv",
    "tsmc":    _EXT_US_STK / "tsmc.csv",
    "tesla":   _EXT_US_STK / "tesla.csv",
    "usd_krw": _EXT_FOREX  / "usd_krw.csv",
    "us10y":   _EXT_BONDS  / "us_10y.csv",
    # 원자재
    "wti":     _EXT_COM / "wti.csv",
    "gold":    _EXT_COM / "gold.csv",
    "silver":  _EXT_COM / "silver.csv",
    "copper":  _EXT_COM / "copper.csv",
    "natgas":  _EXT_COM / "natural_gas.csv",
    # 한국 지수
    "KOSPI":   _EXT_KR_IDX / "kospi.csv",
    "KOSDAQ":  _EXT_KR_IDX / "kosdaq.csv",
    "KS200":   _EXT_KR_IDX / "ks200.csv",
    # 한국 종목
    "samsung":     _EXT_KR_STK / "samsung.csv",
    "sk_hynix":    _EXT_KR_STK / "sk_hynix.csv",
    "lg_energy":   _EXT_KR_STK / "lg_energy.csv",
    "samsung_sdi": _EXT_KR_STK / "samsung_sdi.csv",
    "hanmi_semi":  _EXT_KR_STK / "hanmi_semi.csv",
    "sk_inno":     _EXT_KR_STK / "sk_inno.csv",
    "posco":       _EXT_KR_STK / "posco.csv",
    "kakao":       _EXT_KR_STK / "kakao.csv",
    "naver":       _EXT_KR_STK / "naver.csv",
    "hyundai":     _EXT_KR_STK / "hyundai.csv",
}


class HistoryLoader:
    """과거 가격 데이터 조회 유틸리티."""

    def __init__(self):
        self._cache: dict = {}

    def _load_close(self, symbol: str) -> Optional[pd.Series]:
        """종가 시리즈 로드 (캐시 사용)."""
        if symbol in self._cache:
            return self._cache[symbol]

        path = _SYMBOL_MAP.get(symbol)
        if path is None or not path.exists():
            path = _SYMBOL_MAP_FALLBACK.get(symbol)
        if path is None or not path.exists():
            return None

        try:
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            # 종가 컬럼 자동 탐지
            for col in ["Close", "종가"]:
                if col in df.columns:
                    series = df[col].dropna()
                    self._cache[symbol] = series
                    return series
            # 컬럼 없으면 4번째 컬럼 (OHLCV 순서)
            series = df.iloc[:, 3].dropna()
            self._cache[symbol] = series
            return series
        except Exception:
            return None

    def returns(self, symbol: str, period: int = 252) -> Optional[pd.Series]:
        """최근 period일 일간 수익률."""
        close = self._load_close(symbol)
        if close is None:
            return None
        return close.pct_change().dropna().tail(period)

    def z_score(self, symbol: str, current_return_pct: float, window: int = 252) -> Optional[float]:
        """
        현재 등락률이 과거 window일 분포에서 몇 sigma인지 반환.
        current_return_pct: 소수 (예: -2.5% → -0.025)
        """
        ret = self.returns(symbol, window)
        if ret is None or len(ret) < 20:
            return None
        mu  = ret.mean()
        std = ret.std()
        if std == 0:
            return 0.0
        return round((current_return_pct / 100 - mu) / std, 2)

    def percentile(self, symbol: str, current_value: float, window: int = 252) -> Optional[float]:
        """
        현재 가격 수준이 과거 window일 중 몇 번째 백분위인지 반환 (0~100).
        VIX, 환율 등 가격 수준 자체를 비교할 때 사용.
        """
        close = self._load_close(symbol)
        if close is None or len(close) < 20:
            return None
        recent = close.tail(window)
        pct = (recent < current_value).mean() * 100
        return round(float(pct), 1)

    def historical_range(self, symbol: str, window: int = 252) -> Optional[dict]:
        """최근 window일 가격 범위 통계."""
        close = self._load_close(symbol)
        if close is None or len(close) < 20:
            return None
        recent = close.tail(window)
        return {
            "min":    round(float(recent.min()),  2),
            "max":    round(float(recent.max()),  2),
            "mean":   round(float(recent.mean()), 2),
            "std":    round(float(recent.std()),  2),
            "latest": round(float(recent.iloc[-1]), 2),
        }

    def get_lead_lag_corr(self, us_symbol: str, kr_symbol: str, lag: int = 1) -> Optional[float]:
        """
        미국 지수(us_symbol) → 한국 지수(kr_symbol) lag일 후행 상관관계.
        lag=1: 미국 당일 수익률 vs 한국 익일 수익률
        """
        us_ret = self.returns(us_symbol)
        kr_ret = self.returns(kr_symbol)
        if us_ret is None or kr_ret is None:
            return None

        # 인덱스 맞추기
        combined = pd.DataFrame({"us": us_ret, "kr": kr_ret}).dropna()
        if len(combined) < 20:
            return None

        kr_shifted = combined["kr"].shift(-lag)
        corr = combined["us"].corr(kr_shifted.dropna())
        return round(float(corr), 4) if not np.isnan(corr) else None

    def is_extreme(self, symbol: str, current_value: float, threshold_pct: float = 90.0) -> bool:
        """현재 값이 역사적 상위 threshold_pct% 이상이면 True."""
        pct = self.percentile(symbol, current_value)
        if pct is None:
            return False
        return pct >= threshold_pct

    def summary(self) -> dict:
        """로드 가능한 심볼 목록 및 데이터 현황."""
        result = {}
        for symbol, path in _SYMBOL_MAP.items():
            if path.exists():
                try:
                    df = pd.read_csv(path, index_col=0, parse_dates=True)
                    result[symbol] = {
                        "rows":  len(df),
                        "start": str(df.index.min().date()),
                        "end":   str(df.index.max().date()),
                    }
                except Exception:
                    result[symbol] = {"rows": 0, "start": None, "end": None}
            else:
                result[symbol] = None
        return result


# ──────────────────────────────────────────────
# 싱글턴 (에이전트에서 import 후 바로 사용)
# ──────────────────────────────────────────────

_loader: Optional["HistoryLoader"] = None


def get_loader() -> HistoryLoader:
    global _loader
    if _loader is None:
        _loader = HistoryLoader()
    return _loader


# ──────────────────────────────────────────────
# 빠른 확인용
# ──────────────────────────────────────────────

if __name__ == "__main__":
    hl = HistoryLoader()

    print("=== 로드 가능 심볼 현황 ===")
    for sym, info in hl.summary().items():
        if info:
            print(f"  {sym:15s}: {info['rows']}행  {info['start']} ~ {info['end']}")
        else:
            print(f"  {sym:15s}: [파일 없음]")

    print("\n=== VIX 현황 ===")
    vix_range = hl.historical_range("vix")
    if vix_range:
        print(f"  최근 1년 VIX: min={vix_range['min']} / mean={vix_range['mean']} / max={vix_range['max']}")
    pct = hl.percentile("vix", 25.0)
    print(f"  VIX 25.0 = 과거 1년 대비 {pct}번째 백분위")

    print("\n=== 미-한 후행 상관관계 ===")
    for lag in [0, 1]:
        corr = hl.get_lead_lag_corr("nasdaq", "KOSPI", lag=lag)
        print(f"  QQQ vs KOSPI (lag={lag}일): {corr}")
