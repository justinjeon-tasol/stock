"""
매매 데이터 종합 분석 스크립트
GCP VM에서 실행: python scripts/analyze_trades.py
.env의 Supabase 크레덴셜을 사용합니다.
"""

import os
import sys
import json
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# 프로젝트 루트에서 실행되도록 경로 설정
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)

from supabase import create_client

KST = timezone(timedelta(hours=9))

url = os.getenv("SUPABASE_URL", "")
key = os.getenv("SUPABASE_KEY", "")
client = create_client(url, key)


def section(title):
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def query(table, filters=None, order=None, limit=200):
    """Supabase 테이블 조회 헬퍼"""
    q = client.table(table).select("*")
    if filters:
        for col, op, val in filters:
            q = getattr(q, op)(col, val)
    if order:
        col, desc = order
        q = q.order(col, desc=desc)
    q = q.limit(limit)
    result = q.execute()
    return result.data if result.data else []


def analyze_open_positions():
    section("1. OPEN 포지션 현황")
    positions = query("positions",
                      filters=[("status", "eq", "OPEN")],
                      order=("created_at", True))
    if not positions:
        print("  OPEN 포지션 없음")
        return

    print(f"  총 {len(positions)}개 OPEN 포지션\n")
    total_invested = 0
    for p in positions:
        code = p.get("code", "?")
        name = p.get("name", "?")
        avg = float(p.get("avg_price", 0))
        qty = int(p.get("quantity", 0))
        peak = float(p.get("peak_price", 0))
        horizon = p.get("holding_period", "?")
        sector = p.get("sector", "?")
        created = p.get("created_at", "?")[:16]
        invested = avg * qty
        total_invested += invested

        # 보유 기간 계산
        try:
            entry_dt = datetime.fromisoformat(p["created_at"].replace("Z", "+00:00"))
            hold_hours = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600
            hold_str = f"{hold_hours:.1f}h"
        except:
            hold_str = "?"

        print(f"  [{horizon}] {name}({code}) | {sector}")
        print(f"    평균가={avg:,.0f} x {qty}주 = {invested:,.0f}원 | 최고가={peak:,.0f} | 보유={hold_str}")
        print(f"    진입: {created}")
        print()

    print(f"  총 투자금(매입가 기준): {total_invested:,.0f}원")


def analyze_closed_positions():
    section("2. CLOSED 포지션 분석 (최근 50건)")
    positions = query("positions",
                      filters=[("status", "eq", "CLOSED")],
                      order=("closed_at", True),
                      limit=50)
    if not positions:
        print("  CLOSED 포지션 없음")
        return

    print(f"  총 {len(positions)}건 조회\n")

    results = []
    reason_stats = defaultdict(lambda: {"count": 0, "pnl_sum": 0.0})
    horizon_stats = defaultdict(lambda: {"count": 0, "wins": 0, "pnl_sum": 0.0})

    for p in positions:
        avg = float(p.get("avg_price", 0))
        close_price = float(p.get("close_price", 0)) if p.get("close_price") else 0
        qty = int(p.get("quantity", 0))
        reason = p.get("close_reason", "UNKNOWN")
        horizon = p.get("holding_period", "?")
        name = p.get("name", "?")
        code = p.get("code", "?")

        if avg > 0 and close_price > 0:
            pnl = (close_price - avg) / avg * 100
        else:
            pnl = 0

        results.append(pnl)
        reason_stats[reason]["count"] += 1
        reason_stats[reason]["pnl_sum"] += pnl
        horizon_stats[horizon]["count"] += 1
        horizon_stats[horizon]["pnl_sum"] += pnl
        if pnl > 0:
            horizon_stats[horizon]["wins"] += 1

        created = p.get("created_at", "?")[:10]
        closed = (p.get("closed_at") or "?")[:10]
        print(f"  {created}→{closed} | [{horizon}] {name}({code}) | {avg:,.0f}→{close_price:,.0f} | {pnl:+.2f}% | {reason}")

    # 요약
    if results:
        wins = [r for r in results if r > 0]
        losses = [r for r in results if r <= 0]
        print(f"\n  --- 요약 ---")
        print(f"  총 {len(results)}건 | 승률 {len(wins)/len(results)*100:.1f}% ({len(wins)}승/{len(losses)}패)")
        if wins:
            print(f"  평균 이익: {sum(wins)/len(wins):+.2f}%")
        if losses:
            print(f"  평균 손실: {sum(losses)/len(losses):+.2f}%")
        print(f"  전체 평균: {sum(results)/len(results):+.2f}%")

        print(f"\n  --- 청산 사유별 ---")
        for reason, stats in sorted(reason_stats.items(), key=lambda x: x[1]["count"], reverse=True):
            avg_pnl = stats["pnl_sum"] / stats["count"]
            print(f"    {reason}: {stats['count']}건, 평균 {avg_pnl:+.2f}%")

        print(f"\n  --- 보유기간별 ---")
        for horizon, stats in horizon_stats.items():
            wr = stats["wins"] / stats["count"] * 100 if stats["count"] > 0 else 0
            avg_pnl = stats["pnl_sum"] / stats["count"]
            print(f"    {horizon}: {stats['count']}건, 승률 {wr:.0f}%, 평균 {avg_pnl:+.2f}%")


def analyze_trades():
    section("3. 매매 내역 분석 (최근 100건)")
    trades = query("trades", order=("created_at", True), limit=100)
    if not trades:
        print("  매매 내역 없음")
        return

    buy_count = sum(1 for t in trades if t.get("action") == "BUY")
    sell_count = sum(1 for t in trades if t.get("action") == "SELL")
    print(f"  최근 100건: 매수 {buy_count}건, 매도 {sell_count}건\n")

    # 매도 손익 분석
    sell_results = []
    daily_trades = defaultdict(lambda: {"buys": 0, "sells": 0, "pnl_sum": 0.0})

    for t in trades:
        action = t.get("action", "?")
        dt = t.get("created_at", "")[:10]
        daily_trades[dt][f"{action.lower()}s"] = daily_trades[dt].get(f"{action.lower()}s", 0) + 1

        if action == "SELL" and t.get("result_pct") is not None:
            rp = float(t["result_pct"])
            sell_results.append(rp)
            daily_trades[dt]["pnl_sum"] += rp

    # 최근 30건 상세
    print("  최근 30건 상세:")
    for t in trades[:30]:
        action = t.get("action", "?")
        name = t.get("name", "?")
        code = t.get("code", "?")
        qty = int(t.get("quantity", 0))
        price = float(t.get("price", 0))
        result_pct = t.get("result_pct")
        reason = t.get("reason", t.get("strategy_id", "?"))
        created = t.get("created_at", "?")[:16]
        result_str = f" → {float(result_pct):+.2f}%" if result_pct is not None else ""
        print(f"    {created} | {action:4s} | {name}({code}) | {qty}주 x {price:,.0f}원{result_str} | {reason}")

    # 매도 통계
    if sell_results:
        wins = [r for r in sell_results if r > 0]
        losses = [r for r in sell_results if r <= 0]
        print(f"\n  --- 매도 손익 통계 ---")
        print(f"  총 {len(sell_results)}건 | 승률 {len(wins)/len(sell_results)*100:.1f}%")
        if wins:
            print(f"  평균 이익: {sum(wins)/len(wins):+.2f}%, 최대: {max(wins):+.2f}%")
        if losses:
            print(f"  평균 손실: {sum(losses)/len(losses):+.2f}%, 최대: {min(losses):+.2f}%")
        print(f"  Profit Factor: {abs(sum(wins))/abs(sum(losses)):.2f}" if losses and sum(losses) != 0 else "")

    # 일별 거래 빈도
    print(f"\n  --- 일별 거래 빈도 (최근 10일) ---")
    for dt in sorted(daily_trades.keys(), reverse=True)[:10]:
        d = daily_trades[dt]
        pnl_str = f", 실현 {d['pnl_sum']:+.2f}%" if d['pnl_sum'] != 0 else ""
        print(f"    {dt}: 매수 {d.get('buys', 0)}건, 매도 {d.get('sells', 0)}건{pnl_str}")


def analyze_dsl_breakdown():
    section("4. DSL -22.32% 원인 분석")
    print("  OPEN 포지션의 미실현 손익을 가중 평균으로 계산합니다.\n")

    positions = query("positions",
                      filters=[("status", "eq", "OPEN")],
                      order=("created_at", True))

    if not positions:
        print("  OPEN 포지션 없음 - DSL 계산 불가")
        return

    print(f"  ※ 현재가 정보 없이 매입가/최고가 기반으로 추정\n")
    total_value = 0
    weighted_pnl = 0

    for p in positions:
        avg = float(p.get("avg_price", 0))
        qty = int(p.get("quantity", 0))
        peak = float(p.get("peak_price", 0))
        name = p.get("name", "?")
        code = p.get("code", "?")

        if avg <= 0 or qty <= 0:
            continue

        position_value = avg * qty
        total_value += position_value

        # 최고가 대비 현재 상태 추정 (peak_price가 있으면)
        if peak > 0:
            peak_pnl = (peak - avg) / avg * 100
            print(f"  {name}({code}): 매입가={avg:,.0f} x {qty}주 = {position_value:,.0f}원")
            print(f"    최고가={peak:,.0f} (최고가 기준 {peak_pnl:+.2f}%)")

    # 오늘 실현 손익
    section("4-1. 오늘 실현 손익 (trades에서 SELL)")
    today = datetime.now(KST).strftime("%Y-%m-%d")
    today_sells = query("trades",
                        filters=[("action", "eq", "SELL")],
                        order=("created_at", True),
                        limit=200)

    today_realized = 0
    today_count = 0
    for t in today_sells:
        dt = t.get("created_at", "")[:10]
        if dt == today and t.get("result_pct") is not None:
            rp = float(t["result_pct"])
            today_realized += rp
            today_count += 1
            print(f"  {t.get('name','?')}({t.get('code','?')}) → {rp:+.2f}%")

    print(f"\n  오늘 실현 손익: {today_count}건, 합계 {today_realized:+.2f}%")
    print(f"  ※ DSL = 실현손익({today_realized:+.2f}%) + 미실현손익(가중평균) = 합계")
    print(f"  ※ -22.32%가 나오려면 미실현손익이 매우 큰 음수이거나,")
    print(f"     이전 버그(FIX-3 전)로 단순합산된 값이 누적되었을 가능성")


def analyze_account_history():
    section("5. 계좌 자산 추이")
    accounts = query("account_summary", order=("created_at", True), limit=30)
    if not accounts:
        print("  계좌 요약 데이터 없음")
        return

    for a in accounts:
        cash = float(a.get("cash", 0))
        stock = float(a.get("stock_value", 0))
        total = float(a.get("total_assets", 0))
        pnl = a.get("daily_pnl_pct")
        created = a.get("created_at", "?")[:16]
        pnl_str = f" | 일간={float(pnl):+.2f}%" if pnl is not None else ""
        print(f"  {created} | 현금={cash:,.0f} | 주식={stock:,.0f} | 총={total:,.0f}{pnl_str}")


def analyze_market_phases():
    section("6. 국면 변화 이력")
    phases = query("market_phases", order=("created_at", True), limit=20)
    if not phases:
        print("  국면 이력 없음")
        return

    for p in phases:
        phase = p.get("phase", "?")
        conf = p.get("confidence", "?")
        created = p.get("created_at", "?")[:16]
        details = p.get("details", "")
        detail_str = f" | {details[:80]}" if details else ""
        print(f"  {created} | {phase} (신뢰도: {conf}){detail_str}")


def analyze_trading_frequency():
    section("7. 매매 빈도 분석 (과매매 진단)")
    trades = query("trades", order=("created_at", True), limit=200)
    if not trades:
        print("  매매 내역 없음")
        return

    # 동일 종목 매수→매도 사이클 분석
    code_trades = defaultdict(list)
    for t in trades:
        code_trades[t.get("code", "")].append(t)

    print(f"  총 {len(trades)}건 중 거래 종목 수: {len(code_trades)}개\n")

    short_holds = 0  # 1시간 이내 청산
    same_day_round_trips = 0

    for code, code_list in code_trades.items():
        buys = [t for t in code_list if t.get("action") == "BUY"]
        sells = [t for t in code_list if t.get("action") == "SELL"]

        if buys and sells:
            name = buys[0].get("name", code)
            print(f"  {name}({code}): 매수 {len(buys)}회, 매도 {len(sells)}회")

            # 매수-매도 간격 분석
            for b in buys:
                for s in sells:
                    try:
                        buy_dt = datetime.fromisoformat(b["created_at"].replace("Z", "+00:00"))
                        sell_dt = datetime.fromisoformat(s["created_at"].replace("Z", "+00:00"))
                        if sell_dt > buy_dt:
                            delta_hours = (sell_dt - buy_dt).total_seconds() / 3600
                            if delta_hours < 1:
                                short_holds += 1
                            if buy_dt.date() == sell_dt.date():
                                same_day_round_trips += 1
                            break
                    except:
                        pass

    print(f"\n  --- 과매매 지표 ---")
    print(f"  1시간 이내 청산: {short_holds}건")
    print(f"  당일 왕복 매매: {same_day_round_trips}건")
    total_days = len(set(t.get("created_at", "")[:10] for t in trades))
    if total_days > 0:
        print(f"  거래일 수: {total_days}일")
        print(f"  일평균 거래: {len(trades)/total_days:.1f}건")


def analyze_pending_dca():
    section("8. DCA 대기 주문")
    dca = query("pending_dca", order=("created_at", True), limit=20)
    if not dca:
        print("  DCA 대기 주문 없음")
        return
    for d in dca:
        print(f"  {json.dumps(d, ensure_ascii=False, indent=2)[:200]}")


def main():
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║          주식 자동매매 시스템 - 종합 데이터 분석 리포트              ║")
    print(f"║          실행시각: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST'):>43s}   ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")

    try:
        analyze_open_positions()
        analyze_closed_positions()
        analyze_trades()
        analyze_dsl_breakdown()
        analyze_account_history()
        analyze_market_phases()
        analyze_trading_frequency()
        analyze_pending_dca()
    except Exception as e:
        print(f"\n  ❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()

    print(f"\n{'=' * 70}")
    print("  분석 완료")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
