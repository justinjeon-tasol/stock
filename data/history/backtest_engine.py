"""
전략 백테스팅 엔진.
히스토리 CSV를 사용해 각 전략의 진입/청산 조건을 시뮬레이션한다.

핵심 로직:
  Day T  : 미국 시장 진입 조건 확인 (전일 신호)
  Day T+1: 한국 시장 매수 (익일 가격으로 진입)
  Day T+N: 익절/손절 조건 충족 시 청산 (최대 보유 10일)

사용법:
  python data/history/backtest_engine.py
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

# 경로 설정
ROOT     = Path(__file__).resolve().parent.parent.parent
HIST_DIR = Path(__file__).resolve().parent
US_DIR   = HIST_DIR / "us_market"
KR_DIR   = HIST_DIR / "kr_market"
COM_DIR  = HIST_DIR / "commodity"
STR_DIR  = ROOT / "data" / "strategy_library"

MAX_HOLD_DAYS = 10   # 최대 보유일


# ──────────────────────────────────────────────
# 데이터 로딩
# ──────────────────────────────────────────────

def _load_close(path: Path, col_hint: str = "Close") -> Optional[pd.Series]:
    """CSV에서 종가 시리즈 로드."""
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        for col in [col_hint, "Close", "종가"]:
            if col in df.columns:
                return df[col].dropna()
        return df.iloc[:, 3].dropna()   # OHLCV 순서에서 종가
    except Exception:
        return None


def _daily_ret(series: pd.Series) -> pd.Series:
    """일간 등락률(%) 계산."""
    return series.pct_change() * 100


def _load_all() -> dict:
    """백테스팅에 필요한 전체 데이터 로드."""
    data = {}
    mapping = {
        "nasdaq":  US_DIR / "nasdaq.csv",
        "sox":     US_DIR / "sox.csv",
        "nvda":    US_DIR / "nvidia.csv",
        "amd":     US_DIR / "amd.csv",
        "vix":     US_DIR / "vix.csv",
        "usd_krw": US_DIR / "usd_krw.csv",
        "kospi":   KR_DIR / "index_KOSPI.csv",
        "sk_hynix":KR_DIR / "stock_sk_hynix.csv",
        "samsung": KR_DIR / "stock_samsung.csv",
    }
    for name, path in mapping.items():
        series = _load_close(path)
        if series is not None:
            data[name] = series
    return data


# ──────────────────────────────────────────────
# 전략별 진입 신호 생성기
# ──────────────────────────────────────────────

def _signals_str001(data: dict) -> pd.Series:
    """
    STR_001 (안정화, 미국지수):
    전일 나스닥 +1.5% 이상 & VIX < 20 & KOSPI 선물(나스닥으로 대용) +0.3% 이상
    → 익일 KOSPI 매수
    """
    nasdaq_ret = _daily_ret(data["nasdaq"])
    vix        = data["vix"]
    signal = (nasdaq_ret >= 1.5) & (vix < 20)
    return signal.shift(1).fillna(False)   # 전일 신호 → 당일 진입


def _signals_str002(data: dict) -> pd.Series:
    """
    STR_002 (안정화, 환율매크로):
    전일 SOX +1.0% 이상 & USD/KRW -0.3% 이하(달러 약세) & VIX < 20
    → 익일 SK하이닉스 매수
    """
    sox_ret    = _daily_ret(data["sox"])
    usdkrw_ret = _daily_ret(data["usd_krw"])
    vix        = data["vix"]
    signal = (sox_ret >= 1.0) & (usdkrw_ret <= -0.3) & (vix < 20)
    return signal.shift(1).fillna(False)


def _signals_str003(data: dict) -> pd.Series:
    """
    STR_003 (급등장, 섹터연계):
    전일 SOX +2.0% 이상 & 나스닥 +1.5% 이상 & VIX < 20
    → 익일 SK하이닉스 매수
    (거래량 150% 조건은 데이터 없으므로 SOX 강도로 대용)
    """
    sox_ret    = _daily_ret(data["sox"])
    nasdaq_ret = _daily_ret(data["nasdaq"])
    vix        = data["vix"]
    signal = (sox_ret >= 2.0) & (nasdaq_ret >= 1.5) & (vix < 20)
    return signal.shift(1).fillna(False)


def _signals_str004(data: dict) -> pd.Series:
    """
    STR_004 (급등장, 타이밍):
    전일 NVDA 또는 AMD +3.0% 이상 & SOX +1.5% 이상
    (외국인 순매수 조건은 데이터 없으므로 생략)
    → 익일 SK하이닉스 매수
    """
    nvda_ret = _daily_ret(data["nvda"])
    amd_ret  = _daily_ret(data["amd"])
    sox_ret  = _daily_ret(data["sox"])
    signal = ((nvda_ret >= 3.0) | (amd_ret >= 3.0)) & (sox_ret >= 1.5)
    return signal.shift(1).fillna(False)


def _signals_str005(data: dict) -> pd.Series:
    """
    STR_005 (급락장, 시장국면):
    VIX >= 25 & KOSPI -1.5% 이하 당일 → 역발상 매수 신호
    (급락장 저점 매수 전략 — 패닉 시 단기 반등 포착)
    """
    kospi_ret = _daily_ret(data["kospi"])
    vix       = data["vix"]
    # 당일 급락 감지 → 다음날 저점 매수
    signal = (kospi_ret <= -1.5) & (vix >= 25)
    return signal.shift(1).fillna(False)


def _signals_str006(data: dict) -> pd.Series:
    """
    STR_006 (급락장, 시장국면):
    KOSPI -2.0% 이하 & VIX >= 30 → 익일 저점 매수 (극단적 패닉 후 반등)
    """
    kospi_ret = _daily_ret(data["kospi"])
    vix       = data["vix"]
    signal = (kospi_ret <= -2.0) & (vix >= 30)
    return signal.shift(1).fillna(False)


def _signals_str007(data: dict) -> pd.Series:
    """
    STR_007 (변동폭큰, 시장국면):
    미국 선물 약세 — 나스닥 -1.5% 이하 & VIX 25~35 → 당일 현금 전환 후
    KOSPI 반등 포착 (이튿날 소량 재진입)
    """
    nasdaq_ret = _daily_ret(data["nasdaq"])
    vix        = data["vix"]
    signal = (nasdaq_ret <= -1.5) & (vix >= 25) & (vix <= 35)
    return signal.shift(1).fillna(False)


_SIGNAL_FUNCS = {
    "STR_001": (_signals_str001, "kospi",    3.0, -2.0),   # (신호함수, 대상, TP%, SL%)
    "STR_002": (_signals_str002, "sk_hynix", 4.0, -2.5),
    "STR_003": (_signals_str003, "sk_hynix", 5.0, -3.0),
    "STR_004": (_signals_str004, "sk_hynix", 6.0, -3.0),
    "STR_005": (_signals_str005, "kospi",    3.0, -2.0),
    "STR_006": (_signals_str006, "kospi",    4.0, -2.5),
    "STR_007": (_signals_str007, "kospi",    3.0, -2.0),
}


# ──────────────────────────────────────────────
# STR_B 시리즈: 국면 필터링 + 데이터기반 신호
# ──────────────────────────────────────────────

def _load_phase_series() -> Optional[pd.Series]:
    """phase_classified.csv에서 국면 시리즈 로드."""
    path = HIST_DIR / "phase_classified.csv"
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        return df["phase"].sort_index()
    except Exception:
        return None


def _phase_mask(phase_series: Optional[pd.Series], phase_name: str, index: pd.Index) -> pd.Series:
    """특정 국면인 날짜에만 True인 마스크. phase_series 없으면 전체 True."""
    if phase_series is None:
        return pd.Series(True, index=index)
    aligned = phase_series.reindex(index)
    return aligned == phase_name


def _signals_strB1(data: dict, phase_series: Optional[pd.Series]) -> pd.Series:
    """
    STR_B1 (대상승장 데이터기반):
    국면=대상승장 AND 전일 SOX >= +1.0%
    → 다음날 KOSPI 매수. 승률 89%, edge=+0.39
    """
    sox_ret = _daily_ret(data["sox"])
    mask    = _phase_mask(phase_series, "대상승장", sox_ret.index)
    signal  = (sox_ret >= 1.0) & mask
    return signal.shift(1).fillna(False)


def _signals_strB2(data: dict, phase_series: Optional[pd.Series]) -> pd.Series:
    """
    STR_B2 (상승장 데이터기반):
    국면=상승장 AND 전일 NASDAQ >= +1.5%
    → 다음날 KOSPI 매수. 승률 87%, edge=+0.37
    """
    nasdaq_ret = _daily_ret(data["nasdaq"])
    mask       = _phase_mask(phase_series, "상승장", nasdaq_ret.index)
    signal     = (nasdaq_ret >= 1.5) & mask
    return signal.shift(1).fillna(False)


def _signals_strB3(data: dict, phase_series: Optional[pd.Series]) -> pd.Series:
    """
    STR_B3 (일반장 데이터기반):
    국면=일반장 AND 전일 NASDAQ >= +1.5%
    → 다음날 KOSPI 매수. 승률 66%, edge=+0.16
    """
    nasdaq_ret = _daily_ret(data["nasdaq"])
    mask       = _phase_mask(phase_series, "일반장", nasdaq_ret.index)
    signal     = (nasdaq_ret >= 1.5) & mask
    return signal.shift(1).fillna(False)


def _signals_strB4(data: dict, phase_series: Optional[pd.Series]) -> pd.Series:
    """
    STR_B4 (변동폭큰 데이터기반):
    국면=변동폭큰 AND 전일 SOX >= +3.0%
    → 다음날 KOSPI 매수. 승률 67%, edge=+0.17
    """
    sox_ret = _daily_ret(data["sox"])
    mask    = _phase_mask(phase_series, "변동폭큰", sox_ret.index)
    signal  = (sox_ret >= 3.0) & mask
    return signal.shift(1).fillna(False)


def _signals_strB5(data: dict, phase_series: Optional[pd.Series]) -> pd.Series:
    """
    STR_B5 (하락장 데이터기반):
    국면=하락장 AND 전일 NVDA >= +5.0%
    → 다음날 KOSPI 매수. 승률 67%, edge=+0.17
    """
    nvda_ret = _daily_ret(data["nvda"])
    mask     = _phase_mask(phase_series, "하락장", nvda_ret.index)
    signal   = (nvda_ret >= 5.0) & mask
    return signal.shift(1).fillna(False)


def _signals_strB6(data: dict, phase_series: Optional[pd.Series]) -> pd.Series:
    """
    STR_B6 (대폭락장 데이터기반):
    대폭락장에서는 모든 매수신호 edge 음수 → 현금 전략.
    신호 없음 (0 거래).
    """
    kospi_ret = _daily_ret(data["kospi"])
    return pd.Series(False, index=kospi_ret.index)


_SIGNAL_FUNCS_B = {
    "STR_B1": (_signals_strB1, "kospi", 3.8, -2.8),
    "STR_B2": (_signals_strB2, "kospi", 2.5, -2.0),
    "STR_B3": (_signals_strB3, "kospi", 2.0, -2.0),
    "STR_B4": (_signals_strB4, "kospi", 2.3, -2.0),
    "STR_B5": (_signals_strB5, "kospi", 2.9, -2.1),
    "STR_B6": (_signals_strB6, "kospi", 5.3, -4.0),
}


# ──────────────────────────────────────────────
# 단일 전략 백테스팅
# ──────────────────────────────────────────────

def backtest_strategy(
    strategy_id: str,
    data: dict,
    take_profit_pct: float,
    stop_loss_pct: float,
    signal_series: pd.Series,
    target_series: pd.Series,
    max_hold: int = MAX_HOLD_DAYS,
) -> dict:
    """
    신호 발생일 다음날 진입 → TP/SL 조건으로 청산하는 시뮬레이션.

    Returns:
        {
            "trade_count": int,
            "win_count": int,
            "win_rate": float,
            "avg_return_pct": float,
            "mdd": float,
            "trades": [{"entry_date", "exit_date", "return_pct", "win"}],
        }
    """
    # 공통 인덱스 정렬
    combined = pd.DataFrame({
        "signal": signal_series,
        "price":  target_series,
    }).dropna()
    combined = combined.sort_index()

    prices  = combined["price"]
    signals = combined["signal"]

    trades = []
    i = 0
    while i < len(prices) - 1:
        if not signals.iloc[i]:
            i += 1
            continue

        # 진입: 신호 다음날 종가
        entry_idx   = i + 1
        entry_price = prices.iloc[entry_idx]
        entry_date  = prices.index[entry_idx]

        tp_price = entry_price * (1 + take_profit_pct / 100)
        sl_price = entry_price * (1 + stop_loss_pct / 100)

        # 청산: 이후 최대 max_hold일 동안 TP/SL 확인
        exit_price = None
        exit_date  = None
        for j in range(entry_idx + 1, min(entry_idx + max_hold + 1, len(prices))):
            price = prices.iloc[j]
            if price >= tp_price:
                exit_price = tp_price   # TP 도달
                exit_date  = prices.index[j]
                break
            if price <= sl_price:
                exit_price = sl_price   # SL 도달
                exit_date  = prices.index[j]
                break
        else:
            # 최대 보유일 도달 → 당시 종가로 청산
            last_j = min(entry_idx + max_hold, len(prices) - 1)
            exit_price = prices.iloc[last_j]
            exit_date  = prices.index[last_j]

        ret_pct = (exit_price - entry_price) / entry_price * 100
        trades.append({
            "entry_date": str(entry_date.date()),
            "exit_date":  str(exit_date.date()),
            "return_pct": round(ret_pct, 3),
            "win":        ret_pct > 0,
        })

        # 다음 진입은 청산 이후부터 (중복 방지)
        prices_list = list(prices.index)
        i = prices_list.index(exit_date) + 1

    if not trades:
        return {
            "trade_count": 0, "win_count": 0, "win_rate": 0.0,
            "avg_return_pct": 0.0, "mdd": 0.0, "trades": [],
        }

    win_count   = sum(1 for t in trades if t["win"])
    returns     = [t["return_pct"] for t in trades]
    win_rate    = round(win_count / len(trades), 4)
    avg_return  = round(sum(returns) / len(returns), 4)
    mdd         = _calc_mdd(returns)

    return {
        "trade_count":    len(trades),
        "win_count":      win_count,
        "win_rate":       win_rate,
        "avg_return_pct": avg_return,
        "mdd":            mdd,
        "trades":         trades,
    }


def _calc_mdd(return_series: list) -> float:
    """누적 수익 곡선에서 MDD(%) 계산."""
    if not return_series:
        return 0.0
    cum, peak, mdd = 1.0, 1.0, 0.0
    for r in return_series:
        cum *= (1 + r / 100)
        if cum > peak:
            peak = cum
        dd = (cum - peak) / peak * 100
        if dd < mdd:
            mdd = dd
    return round(mdd, 2)


# ──────────────────────────────────────────────
# 메인 실행
# ──────────────────────────────────────────────

def run_all_backtests(save_to_json: bool = True) -> dict:
    """7 + 6개 전략 전체 백테스팅 실행 (STR_001~007 + STR_B1~B6)."""
    print("히스토리 데이터 로딩...")
    data = _load_all()
    missing = [k for k, v in data.items() if v is None]
    if missing:
        print(f"  경고: 없는 데이터 {missing}")

    # STR_B용 국면 데이터 로드
    phase_series = _load_phase_series()
    if phase_series is not None:
        print(f"  국면 데이터 로드 완료 ({len(phase_series)}일)")
    else:
        print("  경고: phase_classified.csv 없음 — STR_B 국면 필터 미적용")

    results = {}

    # STR_001~007
    print("\n=== STR_001~007 백테스팅 ===")
    for strategy_id, (sig_func, target_key, tp, sl) in _SIGNAL_FUNCS.items():
        if target_key not in data:
            print(f"  [{strategy_id}] {target_key} 데이터 없음 - 건너뜀")
            continue

        print(f"\n[{strategy_id}] 백테스팅 중...")
        signal = sig_func(data)
        result = backtest_strategy(
            strategy_id     = strategy_id,
            data            = data,
            take_profit_pct = tp,
            stop_loss_pct   = sl,
            signal_series   = signal,
            target_series   = data[target_key],
        )
        results[strategy_id] = result

        trade_cnt = result["trade_count"]
        win_rate  = result["win_rate"]
        avg_ret   = result["avg_return_pct"]
        mdd       = result["mdd"]
        print(f"  거래 {trade_cnt}건 | 승률 {win_rate:.1%} | 평균수익 {avg_ret:+.2f}% | MDD {mdd:.1f}%")

        if save_to_json:
            _update_strategy_card(strategy_id, result)

    # STR_B1~B6 (국면 필터링 포함)
    print("\n=== STR_B1~B6 백테스팅 (국면 필터 적용) ===")
    for strategy_id, (sig_func, target_key, tp, sl) in _SIGNAL_FUNCS_B.items():
        if target_key not in data:
            print(f"  [{strategy_id}] {target_key} 데이터 없음 - 건너뜀")
            continue

        print(f"\n[{strategy_id}] 백테스팅 중...")
        signal = sig_func(data, phase_series)
        result = backtest_strategy(
            strategy_id     = strategy_id,
            data            = data,
            take_profit_pct = tp,
            stop_loss_pct   = sl,
            signal_series   = signal,
            target_series   = data[target_key],
        )
        results[strategy_id] = result

        trade_cnt = result["trade_count"]
        win_rate  = result["win_rate"]
        avg_ret   = result["avg_return_pct"]
        mdd       = result["mdd"]
        print(f"  거래 {trade_cnt}건 | 승률 {win_rate:.1%} | 평균수익 {avg_ret:+.2f}% | MDD {mdd:.1f}%")

        if save_to_json:
            _update_strategy_card(strategy_id, result)

    return results


def _update_strategy_card(strategy_id: str, result: dict) -> None:
    """백테스팅 결과를 전략 카드 JSON에 저장."""
    # 파일 찾기 (STR_001_xxx.json 형식)
    files = list(STR_DIR.glob(f"**/{strategy_id}_*.json")) + list(STR_DIR.glob(f"**/{strategy_id}.json"))
    if not files:
        print(f"  [{strategy_id}] 전략 파일 없음")
        return

    filepath = files[0]
    with open(filepath, encoding="utf-8") as f:
        card = json.load(f)

    # 성과 업데이트
    perf = card.setdefault("performance", {})
    perf["backtest_win_rate"]   = result["win_rate"]
    perf["backtest_return_pct"] = result["avg_return_pct"]
    perf["mdd"]                 = result["mdd"]
    perf["backtest_trade_count"]= result["trade_count"]

    # 채택 기준 충족 여부
    passed = (
        result["trade_count"] >= 10 and
        result["win_rate"]    >= 0.50 and
        result["mdd"]         >= -10.0
    )
    perf["status"] = "검증완료" if passed else "백테스팅중"

    card["updated_at"] = datetime.now().strftime("%Y-%m-%d")

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(card, f, ensure_ascii=False, indent=2)

    print(f"  [{strategy_id}] 저장 완료 → status={perf['status']}")


def _print_summary(results: dict) -> None:
    """결과 요약 출력."""
    print("\n" + "=" * 60)
    print("전략 백테스팅 결과 요약")
    print("=" * 60)
    print(f"{'전략ID':10s} {'거래수':>6s} {'승률':>8s} {'평균수익':>10s} {'MDD':>8s} {'상태':>8s}")
    print("-" * 60)
    for sid, r in sorted(results.items()):
        passed = r["win_rate"] >= 0.50 and r["mdd"] >= -10.0 and r["trade_count"] >= 10
        status = "검증완료" if passed else "백테스팅중"
        print(
            f"{sid:10s} {r['trade_count']:>6d} {r['win_rate']:>8.1%} "
            f"{r['avg_return_pct']:>+10.2f}% {r['mdd']:>8.1f}% {status:>8s}"
        )
    print("=" * 60)


if __name__ == "__main__":
    results = run_all_backtests(save_to_json=True)
    _print_summary(results)
