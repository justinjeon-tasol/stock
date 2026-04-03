"""
시장 국면 분류기 (6단계)
히스토리 데이터를 분석하여 각 날짜를 6개 장으로 분류한다.

6개 장:
  대상승장  - KOSPI 20일 수익률 +10% 이상 (강한 상승 추세)
  상승장    - KOSPI 20일 수익률 +3% ~ +10%
  일반장    - 낮은 변동성, -3% ~ +3%
  변동폭큰  - 높은 변동성, VIX 20~35 (방향 불명확)
  하락장    - KOSPI 20일 수익률 -3% ~ -10%
  대폭락장  - KOSPI 20일 수익률 -10% 이하 또는 VIX 35 이상

사용법:
  python data/history/phase_classifier.py
"""

from pathlib import Path
import pandas as pd
import numpy as np

HIST_DIR = Path(__file__).resolve().parent
KR_DIR   = HIST_DIR / "kr_market"
US_DIR   = HIST_DIR / "us_market"

# ─── 국면 상수 ───────────────────────────────
PHASE_MAJOR_BULL  = "대상승장"
PHASE_BULL        = "상승장"
PHASE_NORMAL      = "일반장"
PHASE_VOLATILE    = "변동폭큰"
PHASE_BEAR        = "하락장"
PHASE_MAJOR_CRASH = "대폭락장"

PHASE_ORDER = [PHASE_MAJOR_BULL, PHASE_BULL, PHASE_NORMAL,
               PHASE_VOLATILE, PHASE_BEAR, PHASE_MAJOR_CRASH]

# ─── 분류 파라미터 (조정 가능) ────────────────
PARAMS = {
    "roll_days":       20,    # 추세 계산 기간 (거래일)
    "vol_days":        10,    # 변동성 계산 기간
    "major_bull_thr":  10.0,  # 20일 수익률 기준 (%)
    "bull_thr":         3.0,
    "bear_thr":        -3.0,
    "major_crash_thr": -10.0,
    "vol_high_thr":     1.2,  # 10일 일간변동성 기준 (%)
    "vix_crash_thr":   35.0,
    "vix_vol_thr":     20.0,
}


def load_data() -> pd.DataFrame:
    """KOSPI + VIX 로드 후 병합."""
    kospi = pd.read_csv(KR_DIR / "index_KOSPI.csv", index_col=0, parse_dates=True)
    vix   = pd.read_csv(US_DIR / "vix.csv",         index_col=0, parse_dates=True)

    # 컬럼 정리
    kospi_close = kospi["Close"] if "Close" in kospi.columns else kospi.iloc[:, 3]
    vix_close   = vix["Close"]   if "Close" in vix.columns   else vix.iloc[:, 3]

    df = pd.DataFrame({"kospi": kospi_close, "vix": vix_close})

    # 미국 지수도 추가 (패턴 분석용)
    for name, fname in [
        ("nasdaq", "nasdaq.csv"), ("sox", "sox.csv"),
        ("nvda", "nvidia.csv"),   ("amd", "amd.csv"),
        ("usd_krw", "usd_krw.csv"), ("gold", "gold.csv"),
    ]:
        try:
            s = pd.read_csv(US_DIR / fname, index_col=0, parse_dates=True)
            col = "Close" if "Close" in s.columns else s.columns[3]
            df[name] = s[col]
        except Exception:
            pass

    # SK하이닉스
    try:
        sk = pd.read_csv(KR_DIR / "stock_sk_hynix.csv", index_col=0, parse_dates=True)
        col = "종가" if "종가" in sk.columns else ("Close" if "Close" in sk.columns else sk.columns[3])
        df["sk_hynix"] = sk[col]
    except Exception:
        pass

    return df.sort_index()


def classify_phases(df: pd.DataFrame, params: dict = None) -> pd.DataFrame:
    """
    각 날짜를 6개 장으로 분류.

    추가 컬럼:
      kospi_ret1   : 당일 등락률 (%)
      kospi_ret20  : 20일 누적 수익률 (%)
      kospi_vol10  : 10일 실현 변동성 (일간 %)
      phase        : 장 분류 문자열
    """
    p = params or PARAMS
    df = df.copy()

    # 등락률
    df["kospi_ret1"]  = df["kospi"].pct_change() * 100
    df["kospi_ret20"] = df["kospi"].pct_change(p["roll_days"]) * 100
    df["kospi_vol10"] = df["kospi_ret1"].rolling(p["vol_days"]).std()

    # 미국 지표 전일 등락률 (선행 신호용)
    for col in ["nasdaq", "sox", "nvda", "amd", "usd_krw", "gold"]:
        if col in df.columns:
            df[f"{col}_ret1"] = df[col].pct_change() * 100

    def _classify_row(row):
        ret20 = row.get("kospi_ret20", 0) or 0
        vol10 = row.get("kospi_vol10", 0) or 0
        vix   = row.get("vix", 15) or 15

        # 우선순위 순서로 판단
        if ret20 <= p["major_crash_thr"] or vix >= p["vix_crash_thr"]:
            return PHASE_MAJOR_CRASH
        if ret20 >= p["major_bull_thr"]:
            return PHASE_MAJOR_BULL
        if ret20 >= p["bull_thr"]:
            return PHASE_BULL
        if ret20 <= p["bear_thr"]:
            return PHASE_BEAR
        # -3% ~ +3% 사이: 변동성으로 구분
        if vol10 >= p["vol_high_thr"] or vix >= p["vix_vol_thr"]:
            return PHASE_VOLATILE
        return PHASE_NORMAL

    df["phase"] = df.apply(_classify_row, axis=1)
    return df.dropna(subset=["phase"])


def phase_stats(df: pd.DataFrame) -> pd.DataFrame:
    """국면별 기간 분포 및 기본 통계."""
    stats = df.groupby("phase").agg(
        일수         = ("kospi_ret1", "count"),
        평균등락률    = ("kospi_ret1", "mean"),
        변동성        = ("kospi_ret1", "std"),
        평균VIX       = ("vix", "mean"),
        최대낙폭일    = ("kospi_ret1", "min"),
        최대상승일    = ("kospi_ret1", "max"),
    ).round(3)

    # 비율 추가
    stats["비율(%)"] = (stats["일수"] / stats["일수"].sum() * 100).round(1)

    # 정렬
    ordered = [p for p in PHASE_ORDER if p in stats.index]
    return stats.loc[ordered]


def save_classified(df: pd.DataFrame) -> None:
    """분류 결과를 CSV로 저장."""
    out_path = HIST_DIR / "phase_classified.csv"
    cols = ["kospi", "vix", "kospi_ret1", "kospi_ret20", "kospi_vol10", "phase"]
    extra = [c for c in df.columns if c.endswith("_ret1") and c != "kospi_ret1"]
    df[cols + extra].to_csv(out_path)
    print(f"  저장: {out_path.name} ({len(df)}행)")


if __name__ == "__main__":
    print("=== 시장 국면 분류 ===\n")
    df_raw = load_data()
    df     = classify_phases(df_raw)

    print("[국면별 통계]")
    stats = phase_stats(df)
    print(stats.to_string())
    print()

    save_classified(df)

    # 최근 20일 국면 확인
    print("\n[최근 20거래일 국면]")
    recent = df[["kospi", "vix", "kospi_ret1", "kospi_ret20", "phase"]].tail(20)
    print(recent.to_string())
