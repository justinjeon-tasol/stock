"""
전략 성과 리포트 생성.
백테스팅 결과 + 실매매 결과 + 시그널 분석을 종합한 리포트를 생성하고
DB(strategy_reports 테이블) + JSON 파일로 저장한다.

사용법:
  python scripts/generate_strategy_report.py           # 전체 리포트
  python scripts/generate_strategy_report.py --days 7  # 최근 7일 실매매 포함

orchestrator AFTER_HOURS에서 자동 호출.
"""

import argparse
import json
import sys
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPORT_DIR = Path(__file__).resolve().parent.parent / "data" / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

BACKTEST_DIR = Path(__file__).resolve().parent.parent / "data" / "history" / "extended" / "backtest_results"
ANALYSIS_DIR = Path(__file__).resolve().parent.parent / "data" / "history" / "extended" / "analysis"


def load_backtest_results() -> dict:
    """백테스팅 결과 로드."""
    results = {}

    # 전체 결과
    full_path = BACKTEST_DIR / "full_backtest_results.csv"
    if full_path.exists():
        df = pd.read_csv(full_path)
        results["total_signals"] = len(df)
        results["unique_stocks"] = df["kr_code"].nunique()
        results["unique_indicators"] = df["indicator"].nunique()
        results["avg_win_rate"] = round(df["win_rate"].mean() * 100, 1)
        results["avg_return"] = round(df["avg_ret"].mean(), 3)

        # 지표별 요약
        ind_summary = df.groupby("indicator").agg(
            stocks=("kr_code", "nunique"),
            avg_wr=("win_rate", "mean"),
            avg_ret=("avg_ret", "mean"),
            total_edge=("edge", "sum"),
            total_trades=("n", "sum"),
        ).sort_values("total_edge", ascending=False)

        results["indicator_ranking"] = [
            {
                "indicator": idx,
                "stocks": int(r["stocks"]),
                "avg_win_rate": round(r["avg_wr"] * 100, 1),
                "avg_return": round(r["avg_ret"], 3),
                "total_edge": round(r["total_edge"], 1),
                "total_trades": int(r["total_trades"]),
            }
            for idx, r in ind_summary.iterrows()
        ]

    # 종목별 최고 전략
    best_path = BACKTEST_DIR / "best_strategy_per_stock.csv"
    if best_path.exists():
        best_df = pd.read_csv(best_path)
        results["top_strategies"] = [
            {
                "code": r["kr_code"],
                "name": r["kr_name"],
                "indicator": r["indicator"],
                "threshold": r["threshold"],
                "direction": r["direction"],
                "win_rate": round(r["win_rate"] * 100, 1),
                "avg_return": round(r["avg_ret"], 3),
                "trades": int(r["n"]),
                "edge": round(r["edge"], 1),
            }
            for _, r in best_df.head(30).iterrows()
        ]

    return results


def load_correlation_analysis() -> dict:
    """상관관계 분석 결과 로드."""
    results = {}

    # KOSPI vs 전지표
    corr_path = ANALYSIS_DIR / "all_vs_kospi_correlation.csv"
    if corr_path.exists():
        df = pd.read_csv(corr_path)
        top_lead = df.sort_values("lag_1", key=abs, ascending=False).head(15)
        results["top_leading_indicators"] = [
            {
                "indicator": r["indicator"],
                "category": r["category"],
                "lag_0": round(r["lag_0"], 3),
                "lag_1": round(r["lag_1"], 3),
                "observations": int(r["n_obs"]),
            }
            for _, r in top_lead.iterrows()
        ]

    # VIX 구간별
    vix_path = ANALYSIS_DIR / "vix_regime_kospi.csv"
    if vix_path.exists():
        vdf = pd.read_csv(vix_path)
        results["vix_regime"] = vdf.to_dict("records")

    # 종목별 US 상관
    kr_corr_path = ANALYSIS_DIR / "kr_stock_vs_us_correlation.csv"
    if kr_corr_path.exists():
        kdf = pd.read_csv(kr_corr_path)
        # 종목별 최고 상관
        best_corr = kdf.sort_values("lag_1", key=abs, ascending=False).drop_duplicates("kr_stock").head(15)
        results["stock_us_correlation"] = [
            {
                "kr_stock": r["kr_stock"],
                "us_indicator": r["us_indicator"],
                "lag_1": round(r["lag_1"], 3),
                "observations": int(r["n_obs"]),
            }
            for _, r in best_corr.iterrows()
        ]

    return results


def load_live_performance(days: int = 30) -> dict:
    """실매매 성과 로드."""
    try:
        from database.db import _get_client
        client = _get_client()
        if client is None:
            return {}

        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        # 최근 거래
        trades_resp = client.table("trades").select("*").gte("created_at", since).order("created_at").execute()
        trades = trades_resp.data or []

        if not trades:
            return {"trade_count": 0, "period_days": days}

        buy_count = sum(1 for t in trades if t.get("action") == "BUY")
        sell_count = sum(1 for t in trades if t.get("action") == "SELL")
        sell_trades = [t for t in trades if t.get("action") == "SELL" and t.get("result_pct")]
        wins = sum(1 for t in sell_trades if float(t.get("result_pct", 0)) > 0)
        total_pnl = sum(float(t.get("result_pct", 0)) for t in sell_trades)

        # 전략별 성과
        strategy_perf = {}
        for t in sell_trades:
            sid = t.get("strategy_id") or "미지정"
            if sid not in strategy_perf:
                strategy_perf[sid] = {"trades": 0, "wins": 0, "total_pnl": 0}
            strategy_perf[sid]["trades"] += 1
            pnl = float(t.get("result_pct", 0))
            strategy_perf[sid]["total_pnl"] += pnl
            if pnl > 0:
                strategy_perf[sid]["wins"] += 1

        strategy_list = [
            {
                "strategy_id": sid,
                "trades": v["trades"],
                "win_rate": round(v["wins"] / v["trades"] * 100, 1) if v["trades"] > 0 else 0,
                "total_pnl": round(v["total_pnl"], 2),
            }
            for sid, v in strategy_perf.items()
        ]

        return {
            "period_days": days,
            "trade_count": len(trades),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "win_rate": round(wins / len(sell_trades) * 100, 1) if sell_trades else 0,
            "total_pnl_pct": round(total_pnl, 2),
            "avg_pnl_pct": round(total_pnl / len(sell_trades), 3) if sell_trades else 0,
            "strategy_performance": strategy_list,
        }

    except Exception as e:
        return {"error": str(e)}


def load_active_strategies() -> list:
    """현재 활성 전략 목록."""
    strategy_dir = Path(__file__).resolve().parent.parent / "data" / "strategy_library"
    strategies = []
    for f in strategy_dir.rglob("*.json"):
        try:
            card = json.loads(f.read_text(encoding="utf-8"))
            perf = card.get("performance", {})
            strategies.append({
                "id": card.get("id", ""),
                "phase": card.get("phase", ""),
                "group": card.get("group", ""),
                "status": perf.get("status", ""),
                "win_rate": round(perf.get("backtest_win_rate", 0) * 100, 1),
                "return_pct": round(perf.get("backtest_return_pct", 0), 3),
                "mdd": round(perf.get("mdd", 0), 1),
                "trade_count": perf.get("backtest_trade_count", 0),
                "holding_period": card.get("holding_period", ""),
            })
        except Exception:
            pass
    return sorted(strategies, key=lambda x: x["win_rate"], reverse=True)


def load_exit_plans() -> list:
    """현재 활성 exit_plan (상세 포함)."""
    try:
        from database.db import get_all_active_exit_plans
        plans = get_all_active_exit_plans()
        result = []
        for p in plans:
            stages = p.get("exit_stages", [])
            fc = p.get("forecast_components", {})
            dsl = p.get("dynamic_sl", {})
            avg = p.get("avg_price", 0) or 0
            cur = p.get("current_price", 0) or 0
            pnl_pct = (cur / avg - 1) * 100 if avg > 0 else 0

            stage_details = []
            for s in (stages if isinstance(stages, list) else []):
                tp = s.get("trigger_price", 0)
                stage_details.append({
                    "stage": s.get("stage", 0),
                    "type": s.get("type", ""),
                    "trigger_price": tp,
                    "trigger_vs_avg": round((tp / avg - 1) * 100, 1) if avg > 0 and tp > 0 else 0,
                    "sell_ratio": s.get("sell_ratio", 0),
                    "status": s.get("status", ""),
                    "rationale": s.get("rationale", ""),
                })

            result.append({
                "code": p.get("code", ""),
                "name": p.get("name", ""),
                "trend": p.get("forecast_trend", ""),
                "target_1w": p.get("forecast_target_1w"),
                "target_1m": p.get("forecast_target_1m"),
                "confidence": p.get("forecast_confidence"),
                "avg_price": avg,
                "current_price": cur,
                "pnl_pct": round(pnl_pct, 1),
                "quantity": p.get("quantity", 0),
                "holding_period": p.get("holding_period", ""),
                "stages": stage_details,
                "stage_count": len(stage_details),
                "sl_price": dsl.get("current_sl_price"),
                "sl_pct": dsl.get("initial_sl_pct"),
                "upside_p75": fc.get("upside_p75") if isinstance(fc, dict) else None,
                "upside_p90": fc.get("upside_p90") if isinstance(fc, dict) else None,
            })
        return result
    except Exception:
        return []


def generate_report(days: int = 30) -> dict:
    """전체 리포트 생성."""
    print("전략 리포트 생성 중...")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report_version": "2.0",

        # 1. 백테스팅 결과 (30년 데이터 기반)
        "backtest": load_backtest_results(),

        # 2. 상관관계 분석
        "correlation": load_correlation_analysis(),

        # 3. 실매매 성과
        "live_performance": load_live_performance(days),

        # 4. 활성 전략 목록
        "active_strategies": load_active_strategies(),

        # 5. 현재 exit_plans
        "exit_plans": load_exit_plans(),
    }

    # JSON 저장
    report_path = REPORT_DIR / "strategy_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 날짜별 아카이브
    today = datetime.now().strftime("%Y%m%d")
    archive_path = REPORT_DIR / f"strategy_report_{today}.json"
    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"리포트 저장: {report_path}")
    print(f"아카이브: {archive_path}")

    # 요약 출력
    bt = report["backtest"]
    live = report["live_performance"]
    strategies = report["active_strategies"]
    plans = report["exit_plans"]

    print(f"\n{'='*60}")
    print(f"전략 성과 리포트 ({report['generated_at'][:10]})")
    print(f"{'='*60}")

    print(f"\n[백테스팅 (30년 데이터)]")
    print(f"  유의미 시그널: {bt.get('total_signals', 0):,}건")
    print(f"  유효 종목: {bt.get('unique_stocks', 0)}개")
    print(f"  평균 승률: {bt.get('avg_win_rate', 0):.1f}%")
    print(f"  평균 수익: {bt.get('avg_return', 0):+.3f}%")

    if bt.get("indicator_ranking"):
        print(f"\n  [지표 순위 TOP 5]")
        for r in bt["indicator_ranking"][:5]:
            print(f"    {r['indicator']:18s} 종목={r['stocks']:>2} 승률={r['avg_win_rate']:>5.1f}% 기대값={r['total_edge']:>8.1f}")

    print(f"\n[실매매 ({live.get('period_days', 0)}일)]")
    print(f"  거래: {live.get('trade_count', 0)}건 (매수={live.get('buy_count', 0)}, 매도={live.get('sell_count', 0)})")
    print(f"  승률: {live.get('win_rate', 0):.1f}%")
    print(f"  총 손익: {live.get('total_pnl_pct', 0):+.2f}%")

    active = [s for s in strategies if s["status"] not in ("비활성", "")]
    inactive = [s for s in strategies if s["status"] == "비활성"]
    print(f"\n[전략 현황]")
    print(f"  활성: {len(active)}개 / 비활성: {len(inactive)}개")
    for s in active[:5]:
        print(f"    {s['id']:10s} [{s['phase']}] 승률={s['win_rate']:>5.1f}% MDD={s['mdd']:>+5.1f}% ({s['status']})")

    if plans:
        print(f"\n[보유종목 매도 계획]")
        for p in plans:
            print(f"    {p['name']:12s} 추세={p['trend']:8s} 1주목표={p.get('target_1w', 0):>10,.0f} 단계={p['stages']}개")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    generate_report(args.days)
