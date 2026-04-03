"""
계좌 히스토리 빌드 스크립트.
trades + account_summary 를 기반으로 account_history 테이블을 구성한다.

사용법:
  python scripts/build_account_history.py          # 전체 재구성
  python scripts/build_account_history.py --days 3 # 최근 N일
"""

import sys, os, argparse, uuid
from datetime import datetime, timedelta, timezone, date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from database.db import _get_client

INITIAL_CAPITAL = 50_000_000

def build_history(days: int = 30):
    client = _get_client()
    if client is None:
        print("Supabase 미설정")
        return

    # 기간 설정
    end_dt   = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=days)

    # trades 조회
    trades_resp = (
        client.table("trades")
        .select("*")
        .gte("created_at", start_dt.isoformat())
        .order("created_at")
        .execute()
    )
    trades = trades_resp.data or []
    print(f"trades: {len(trades)}건")

    # account_summary 조회 (일자별 마지막 스냅샷)
    summary_resp = (
        client.table("account_summary")
        .select("*")
        .gte("created_at", start_dt.isoformat())
        .order("created_at")
        .execute()
    )
    summaries = summary_resp.data or []
    print(f"account_summary: {len(summaries)}건")

    # 날짜별 trades 그룹핑
    from collections import defaultdict
    trades_by_date = defaultdict(list)
    for t in trades:
        d = t["created_at"][:10]  # YYYY-MM-DD
        trades_by_date[d].append(t)

    # 날짜별 account_summary 마지막 스냅샷
    summary_by_date = {}
    for s in summaries:
        d = s["created_at"][:10]
        summary_by_date[d] = s  # 마지막 값 덮어쓰기

    # 현재 positions (OPEN) 현재 상태
    positions_resp = client.table("positions").select("*").eq("status", "OPEN").execute()
    open_positions = positions_resp.data or []

    # 날짜 범위 생성
    all_dates = set(list(trades_by_date.keys()) + list(summary_by_date.keys()))
    # 오늘도 포함
    today_str = datetime.now().strftime("%Y-%m-%d")
    all_dates.add(today_str)

    # 누적 실현손익
    cumulative_pnl = 0.0

    rows = []
    for d in sorted(all_dates):
        day_trades = trades_by_date.get(d, [])
        snap = summary_by_date.get(d)

        # 당일 매수/매도 금액
        daily_buy_amt  = sum(
            float(t.get("price", 0)) * int(t.get("quantity", 0))
            for t in day_trades if t.get("action") == "BUY"
        )
        daily_sell_amt = sum(
            float(t.get("price", 0)) * int(t.get("quantity", 0))
            for t in day_trades if t.get("action") == "SELL"
        )

        # 당일 실현 손익 (SELL result_pct 기반)
        daily_realized = 0.0
        for t in day_trades:
            if t.get("action") == "SELL" and t.get("result_pct"):
                rp = float(t["result_pct"])
                price = float(t.get("price", 0))
                qty   = int(t.get("quantity", 0))
                buy_val = price * qty / (1 + rp / 100) if (1 + rp / 100) != 0 else 0
                daily_realized += buy_val * rp / 100

        cumulative_pnl += daily_realized

        # 자산 스냅샷
        if snap:
            cash_amt       = float(snap.get("cash_amt", 0))
            stock_evlu_amt = float(snap.get("stock_evlu_amt", 0))
            tot_evlu_amt   = float(snap.get("tot_evlu_amt", 0))
            pchs_amt       = float(snap.get("pchs_amt", 0))
            evlu_pfls_amt  = float(snap.get("evlu_pfls_amt", 0))
            erng_rt        = float(snap.get("erng_rt", 0))
        elif d == today_str:
            # 오늘 스냅샷 없으면 positions 기반 추정
            pchs_amt       = sum(float(p.get("avg_price", 0)) * int(p.get("quantity", 0)) for p in open_positions)
            stock_evlu_amt = pchs_amt  # 현재가 없으면 원가 사용
            cash_amt       = max(0, INITIAL_CAPITAL - pchs_amt)
            tot_evlu_amt   = cash_amt + stock_evlu_amt
            evlu_pfls_amt  = stock_evlu_amt - pchs_amt
            erng_rt        = evlu_pfls_amt / pchs_amt if pchs_amt > 0 else 0.0
        else:
            continue  # 스냅샷도 없고 오늘도 아니면 skip

        rows.append({
            "id":                  str(uuid.uuid4()),
            "recorded_date":       d,
            "initial_capital":     INITIAL_CAPITAL,
            "cash_amt":            cash_amt,
            "stock_evlu_amt":      stock_evlu_amt,
            "tot_evlu_amt":        tot_evlu_amt,
            "pchs_amt":            pchs_amt,
            "evlu_pfls_amt":       evlu_pfls_amt,
            "erng_rt":             erng_rt,
            "daily_buy_amt":       daily_buy_amt,
            "daily_sell_amt":      daily_sell_amt,
            "daily_realized_pnl":  daily_realized,
            "daily_trade_count":   len(day_trades),
            "total_realized_pnl":  cumulative_pnl,
            "mode":                "MOCK",
        })

    if not rows:
        print("저장할 데이터 없음")
        return

    # 기존 데이터 삭제 후 재삽입 (recorded_date 기준)
    dates_to_upsert = [r["recorded_date"] for r in rows]
    client.table("account_history").delete().in_("recorded_date", dates_to_upsert).execute()
    client.table("account_history").insert(rows).execute()
    print(f"account_history {len(rows)}건 저장 완료")
    for r in rows:
        print(f"  {r['recorded_date']} | 총:{r['tot_evlu_amt']:>12,.0f}원 | 현금:{r['cash_amt']:>12,.0f}원 | 주식:{r['stock_evlu_amt']:>12,.0f}원 | 실현손익:{r['daily_realized_pnl']:>+10,.0f}원 | 거래:{r['daily_trade_count']}건")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    build_history(args.days)
