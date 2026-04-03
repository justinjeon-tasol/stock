"""
국면별 패턴 분석기.
phase_classified.csv를 읽어, 각 장에서
'전일 미국 신호 → 당일 KOSPI 수익률' 패턴을 분석한다.

분석 항목:
  1. 국면별 기초 통계
  2. 전일 미국 지표별 정보계수 (IC, 예측력)
  3. 조건부 분포 — "전일 SOX +2% 이상일 때 당일 KOSPI는?"
  4. 최적 진입 신호 도출 (승률 + 기대수익 기준)
  5. 국면별 전략 카드 자동 생성

사용법:
  python data/history/pattern_analyzer.py
"""

from pathlib import Path
import json
from datetime import date

import pandas as pd
import numpy as np

HIST_DIR = Path(__file__).resolve().parent
OUT_DIR  = HIST_DIR / "analysis"
OUT_DIR.mkdir(exist_ok=True)

PHASE_ORDER = ["대상승장", "상승장", "일반장", "변동폭큰", "하락장", "대폭락장"]


# ──────────────────────────────────────────────
# 데이터 로드
# ──────────────────────────────────────────────

def load_classified() -> pd.DataFrame:
    path = HIST_DIR / "phase_classified.csv"
    if not path.exists():
        raise FileNotFoundError("phase_classified.csv 없음. phase_classifier.py 먼저 실행하세요.")
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    return df.sort_index()


# ──────────────────────────────────────────────
# 1. 국면별 기초 통계
# ──────────────────────────────────────────────

def phase_basic_stats(df: pd.DataFrame) -> pd.DataFrame:
    """국면별 KOSPI 일간 수익률 분포."""
    grp = df.groupby("phase")["kospi_ret1"]
    stats = pd.DataFrame({
        "일수":   grp.count(),
        "평균":   grp.mean().round(3),
        "중앙값": grp.median().round(3),
        "표준편차": grp.std().round(3),
        "승률(%)": (grp.apply(lambda x: (x > 0).mean()) * 100).round(1),
        "최솟값":  grp.min().round(2),
        "최댓값":  grp.max().round(2),
    })
    return stats.loc[[p for p in PHASE_ORDER if p in stats.index]]


# ──────────────────────────────────────────────
# 2. 전일 미국 지표 → 당일 KOSPI 예측력 (IC)
# ──────────────────────────────────────────────

US_SIGNALS = ["nasdaq_ret1", "sox_ret1", "nvda_ret1", "amd_ret1", "usd_krw_ret1", "gold_ret1"]


def calc_ic_by_phase(df: pd.DataFrame) -> pd.DataFrame:
    """
    각 국면에서 전일 미국 신호와 당일 KOSPI 수익률의 스피어만 상관계수.
    IC 절대값이 클수록 예측력이 높음.
    양수 = 같은 방향, 음수 = 반대 방향.
    """
    rows = []
    for phase, group in df.groupby("phase"):
        target = group["kospi_ret1"]
        row = {"phase": phase}
        for sig in US_SIGNALS:
            if sig not in group.columns:
                row[sig] = np.nan
                continue
            # 전일 신호: shift(1) → 이미 분류 파일에 당일 미국 신호가 있으므로
            # 전일 미국 ret1 → 당일 KOSPI ret1 상관관계
            prev_sig = group[sig].shift(1)
            valid    = pd.concat([prev_sig, target], axis=1).dropna()
            if len(valid) < 10:
                row[sig] = np.nan
            else:
                row[sig] = round(valid.iloc[:, 0].corr(valid.iloc[:, 1], method="spearman"), 3)
        rows.append(row)

    ic_df = pd.DataFrame(rows).set_index("phase")
    return ic_df.loc[[p for p in PHASE_ORDER if p in ic_df.index]]


# ──────────────────────────────────────────────
# 3. 조건부 승률 분석
# ──────────────────────────────────────────────

SIGNAL_THRESHOLDS = {
    "nasdaq_ret1": [1.0, 1.5, 2.0, -1.0, -1.5, -2.0],
    "sox_ret1":    [1.0, 2.0, 3.0, -1.5, -2.5],
    "nvda_ret1":   [2.0, 3.0, 5.0, -3.0],
    "usd_krw_ret1":[-0.3, -0.5, 0.5, 1.0],
}


def conditional_win_rates(df: pd.DataFrame) -> pd.DataFrame:
    """
    각 국면 × 신호 조건에서 '익일 KOSPI 상승 승률'과 '평균 수익률' 계산.
    신호는 전일 값 기준.
    """
    rows = []
    for phase, group in df.groupby("phase"):
        target = group["kospi_ret1"]   # 당일 KOSPI

        for sig, thresholds in SIGNAL_THRESHOLDS.items():
            if sig not in group.columns:
                continue
            prev_sig = group[sig].shift(1)

            for thr in thresholds:
                direction = "상승" if thr > 0 else "하락"
                cond      = prev_sig >= thr if thr > 0 else prev_sig <= thr
                sub_target= target[cond]

                if len(sub_target) < 5:
                    continue

                win_rate   = (sub_target > 0).mean()
                avg_ret    = sub_target.mean()
                rows.append({
                    "phase":     phase,
                    "signal":    sig.replace("_ret1", ""),
                    "threshold": thr,
                    "direction": direction,
                    "n":         len(sub_target),
                    "win_rate":  round(win_rate, 3),
                    "avg_ret":   round(avg_ret, 3),
                    "edge":      round(win_rate - 0.5, 3),  # 50% 대비 우위
                })

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values(["phase", "edge"], ascending=[True, False])


# ──────────────────────────────────────────────
# 4. 국면별 최적 진입 신호
# ──────────────────────────────────────────────

def best_signals_per_phase(cond_df: pd.DataFrame, top_n: int = 3) -> dict:
    """국면별 상위 N개 진입 신호 (edge 기준)."""
    result = {}
    for phase in PHASE_ORDER:
        sub = cond_df[cond_df["phase"] == phase]
        if sub.empty:
            continue
        # 상승 신호 (매수 우위)
        buy_signals = sub[sub["direction"] == "상승"].nlargest(top_n, "edge")
        # 하락 신호 (현금/방어 우위)
        sell_signals = sub[sub["direction"] == "하락"].nlargest(top_n, "edge")
        result[phase] = {
            "매수신호": buy_signals[["signal", "threshold", "n", "win_rate", "avg_ret", "edge"]].to_dict("records"),
            "방어신호": sell_signals[["signal", "threshold", "n", "win_rate", "avg_ret", "edge"]].to_dict("records"),
        }
    return result


# ──────────────────────────────────────────────
# 5. 국면별 전략 카드 자동 생성
# ──────────────────────────────────────────────

_PHASE_TO_FOLDER = {
    "대상승장": "대상승구간",
    "상승장":   "상승구간",
    "일반장":   "일반구간",
    "변동폭큰": "변동큰구간",
    "하락장":   "하락구간",
    "대폭락장": "대폭락구간",
}

_NEW_STR_IDS = {
    "대상승장": "STR_B1",
    "상승장":   "STR_B2",
    "일반장":   "STR_B3",
    "변동폭큰": "STR_B4",
    "하락장":   "STR_B5",
    "대폭락장": "STR_B6",
}


def generate_strategy_cards(
    basic_stats: pd.DataFrame,
    best_sigs: dict,
    df: pd.DataFrame,
) -> list:
    """
    분석 결과로 전략 카드 JSON을 자동 생성한다.
    기존 STR_001~007과 구별하기 위해 STR_B1~B6 (B=Backtest-derived) 사용.
    """
    cards = []
    today = date.today().isoformat()

    for phase in PHASE_ORDER:
        if phase not in best_sigs:
            continue

        sigs      = best_sigs[phase]
        buy_sigs  = sigs.get("매수신호", [])
        sell_sigs = sigs.get("방어신호", [])
        stats_row = basic_stats.loc[phase] if phase in basic_stats.index else {}

        # 진입 조건 텍스트 생성
        entry_parts = []
        for s in buy_sigs[:2]:
            sig_name = s["signal"].upper()
            thr      = s["threshold"]
            win_pct  = s["win_rate"] * 100
            entry_parts.append(
                f"전일 {sig_name} {thr:+.1f}% 이상 (해당 시 익일 승률 {win_pct:.0f}%)"
            )
        entry_cond = " AND ".join(entry_parts) if entry_parts else "조건 없음"

        # 제외 조건 텍스트
        excl_parts = []
        for s in sell_sigs[:1]:
            sig_name = s["signal"].upper()
            thr      = s["threshold"]
            excl_parts.append(f"전일 {sig_name} {thr:+.1f}% 이하 시 진입 보류")
        excl_cond = excl_parts[0] if excl_parts else ""

        # 국면 특성
        avg_daily = float(stats_row.get("평균", 0) or 0)
        win_rate_phase = float(stats_row.get("승률(%)", 50) or 50) / 100
        std_daily = float(stats_row.get("표준편차", 1) or 1)

        # 익절/손절 설정 (변동성 기반)
        take_profit = round(max(2.0, std_daily * 2.0), 1)
        stop_loss   = round(min(-2.0, -std_daily * 1.5), 1)

        card = {
            "id":          _NEW_STR_IDS.get(phase, f"STR_{phase}"),
            "group":       "데이터기반",
            "phase":       phase,
            "description": _make_description(phase, buy_sigs, avg_daily, win_rate_phase),
            "conditions": {
                "진입": entry_cond,
                "청산": f"익절 +{take_profit}% 또는 손절 {stop_loss}%",
                "제외": excl_cond,
            },
            "performance": {
                "backtest_win_rate":    0.0,   # 실제 백테스팅 후 채워짐
                "backtest_return_pct":  0.0,
                "real_win_rate":        0.0,
                "real_return_pct":      0.0,
                "mdd":                  0.0,
                "status":               "백테스팅중",
                "phase_daily_win_rate": round(win_rate_phase, 3),
                "phase_avg_daily_ret":  round(avg_daily, 3),
            },
            "analysis": {
                "top_buy_signals":  buy_sigs[:3],
                "top_sell_signals": sell_sigs[:2],
                "phase_days":       int(stats_row.get("일수", 0) or 0),
                "phase_ratio_pct":  0.0,
            },
            "compatible":   [],
            "incompatible": [],
            "created_at":   today,
            "updated_at":   today,
        }
        cards.append(card)

    return cards


def _make_description(phase: str, buy_sigs: list, avg_daily: float, win_rate: float) -> str:
    sig_names = [s["signal"].upper() for s in buy_sigs[:2]] if buy_sigs else []
    sig_str   = "/".join(sig_names) if sig_names else "없음"
    return (
        f"{phase} 데이터기반 전략. "
        f"주요 선행신호: {sig_str}. "
        f"국면 평균 일간수익 {avg_daily:+.2f}%, 자연 승률 {win_rate:.0%}."
    )


def save_strategy_cards(cards: list, base_dir: Path) -> None:
    """전략 카드를 strategy_library 하위 폴더에 저장."""
    lib_dir = base_dir / "data" / "strategy_library"
    for card in cards:
        phase  = card["phase"]
        folder = _PHASE_TO_FOLDER.get(phase, phase)
        out_folder = lib_dir / folder
        out_folder.mkdir(exist_ok=True)
        fname = f"{card['id']}_{phase}.json"
        with open(out_folder / fname, "w", encoding="utf-8") as f:
            json.dump(card, f, ensure_ascii=False, indent=2)
        print(f"  저장: {folder}/{fname}")


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────

if __name__ == "__main__":
    BASE_DIR = HIST_DIR.parent.parent   # P/ 루트

    print("=== 국면별 패턴 분석 ===\n")
    df = load_classified()

    # 1. 기초 통계
    basic = phase_basic_stats(df)
    print("[1] 국면별 기초 통계")
    print(basic.to_string())
    basic.to_csv(OUT_DIR / "phase_basic_stats.csv")

    # 2. IC
    print("\n[2] 전일 미국 신호 → 당일 KOSPI 정보계수 (스피어만 상관)")
    ic = calc_ic_by_phase(df)
    print(ic.to_string())
    ic.to_csv(OUT_DIR / "ic_by_phase.csv")

    # 3. 조건부 승률
    print("\n[3] 조건부 승률 계산...")
    cond = conditional_win_rates(df)
    cond.to_csv(OUT_DIR / "conditional_win_rates.csv", index=False)
    print(f"  {len(cond)}개 조건-국면 조합 분석 완료")

    # 4. 최적 신호
    best = best_signals_per_phase(cond)
    print("\n[4] 국면별 최적 진입 신호")
    for phase, sigs in best.items():
        print(f"\n  [{phase}]")
        print(f"  매수신호:")
        for s in sigs["매수신호"][:3]:
            print(f"    {s['signal']:12s} >= {s['threshold']:+.1f}%  |  "
                  f"n={s['n']:3d}  승률={s['win_rate']:.0%}  edge={s['edge']:+.3f}  avgRet={s['avg_ret']:+.3f}%")
        print(f"  방어신호:")
        for s in sigs["방어신호"][:2]:
            print(f"    {s['signal']:12s} <= {s['threshold']:+.1f}%  |  "
                  f"n={s['n']:3d}  승률={s['win_rate']:.0%}  edge={s['edge']:+.3f}  avgRet={s['avg_ret']:+.3f}%")

    # 5. 전략 카드 생성
    print("\n[5] 전략 카드 자동 생성...")
    cards = generate_strategy_cards(basic, best, df)
    save_strategy_cards(cards, BASE_DIR)
    print(f"  {len(cards)}개 전략 카드 생성 완료")

    # 분석 결과 JSON 저장
    with open(OUT_DIR / "best_signals.json", "w", encoding="utf-8") as f:
        json.dump(best, f, ensure_ascii=False, indent=2)
    print(f"\n분석 결과 저장: {OUT_DIR}")
