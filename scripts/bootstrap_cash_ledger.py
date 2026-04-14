"""
현금 원장(cash_ledger) 부트스트랩 스크립트.

현재 KIS 계좌 잔액을 기준으로 원장을 초기화한다.
(과거 trades 데이터에 초기 테스트/버그 데이터가 섞여있어 단순 재생 불가)

사용법:
    python scripts/bootstrap_cash_ledger.py [--dry-run]
"""

import os
import sys
import uuid
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)

from supabase import create_client


def get_client():
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "")
    if not url or not key:
        print("ERROR: SUPABASE_URL 또는 SUPABASE_KEY 미설정")
        sys.exit(1)
    return create_client(url, key)


def bootstrap_ledger(client, dry_run: bool = False):
    """현재 KIS 잔액 기준으로 cash_ledger를 초기화한다."""

    # 1. 원장 테이블 존재 확인
    try:
        existing = client.table("cash_ledger").select("id").limit(1).execute()
        if existing.data:
            print(f"WARNING: cash_ledger에 이미 항목이 있습니다.")
            answer = input("기존 데이터를 삭제하고 다시 초기화하시겠습니까? (y/N): ")
            if answer.lower() != "y":
                print("취소됨.")
                return
            if not dry_run:
                client.table("cash_ledger").delete().neq(
                    "id", "00000000-0000-0000-0000-000000000000"
                ).execute()
                print("기존 cash_ledger 데이터 삭제 완료.")
    except Exception as e:
        print(f"ERROR: cash_ledger 테이블 접근 실패: {e}")
        print("먼저 database/migrations/008_cash_ledger.sql을 Supabase SQL Editor에서 실행하세요.")
        sys.exit(1)

    # 2. 최신 account_summary에서 현재 KIS 현금 가져오기
    latest_acct = (
        client.table("account_summary")
        .select("cash_amt, stock_evlu_amt, tot_evlu_amt, created_at")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not latest_acct.data:
        print("ERROR: account_summary에 데이터가 없습니다.")
        print("파이프라인을 최소 1회 실행하세요.")
        sys.exit(1)

    acct = latest_acct.data[0]
    kis_cash = int(acct.get("cash_amt", 0))
    kis_stock = int(acct.get("stock_evlu_amt", 0))
    kis_total = int(acct.get("tot_evlu_amt", 0))
    acct_time = acct.get("created_at", "")

    print(f"=== 현재 KIS 계좌 현황 (기준: {acct_time}) ===")
    print(f"  예수금:       {kis_cash:>15,}원")
    print(f"  주식 평가:    {kis_stock:>15,}원")
    print(f"  총 평가:      {kis_total:>15,}원")

    # 3. 현재 보유 포지션 확인
    open_positions = (
        client.table("positions")
        .select("code, name, quantity, avg_price")
        .neq("status", "CLOSED")
        .execute()
    )
    positions = open_positions.data or []
    total_position_cost = sum(
        float(p.get("avg_price", 0)) * int(p.get("quantity", 0))
        for p in positions
    )

    print(f"\n=== 보유 포지션 ({len(positions)}개) ===")
    for p in positions:
        qty = int(p.get("quantity", 0))
        avg = float(p.get("avg_price", 0))
        print(f"  {p.get('name',''):12} {p.get('code',''):8} {qty:4}주 × {avg:>10,.0f} = {avg*qty:>12,.0f}")
    print(f"  {'매입금 합계':12} {'':8} {'':4}   {'':>10} = {total_position_cost:>12,.0f}")

    # 4. 원장 초기화 — INITIAL 항목으로 현재 현금 잔액을 기록
    initial_balance = kis_cash
    print(f"\n=== 원장 초기화 ===")
    print(f"  원장 초기 잔액: {initial_balance:>15,}원 (현재 KIS 예수금 기준)")

    if dry_run:
        print("\n[DRY RUN] 실제 DB 저장은 수행하지 않습니다.")
        return

    # INITIAL 항목 삽입
    initial_entry = {
        "id": str(uuid.uuid4()),
        "entry_type": "INITIAL",
        "amount": initial_balance,
        "balance_after": initial_balance,
        "note": f"원장 초기화 (KIS 예수금 기준, {acct_time[:10]})",
        "mode": "MOCK",
    }
    client.table("cash_ledger").insert(initial_entry).execute()
    print(f"  INITIAL 항목 저장 완료: {initial_balance:,}원")

    # 5. 최근 SELL trades에 realized_pnl_amt 백필 (오늘 기준)
    print(f"\n=== 최근 SELL trades realized_pnl_amt 백필 ===")
    sells = (
        client.table("trades")
        .select("id, code, price, quantity, result_pct, realized_pnl_amt")
        .eq("action", "SELL")
        .is_("realized_pnl_amt", "null")
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )
    sell_trades = sells.data or []
    backfilled = 0

    if sell_trades:
        # 포지션에서 avg_price 가져오기
        all_positions = (
            client.table("positions")
            .select("code, avg_price")
            .execute()
        )
        code_avg = {}
        for p in (all_positions.data or []):
            code = p.get("code", "")
            avg = float(p.get("avg_price", 0))
            if code and avg > 0:
                code_avg[code] = avg

        for s in sell_trades:
            code = s.get("code", "")
            sell_price = int(s.get("price", 0))
            qty = int(s.get("quantity", 1))
            avg_price = code_avg.get(code, 0)

            if avg_price > 0 and sell_price > 0:
                pnl = int((sell_price - avg_price) * qty)
                fill_amt = sell_price * qty
                try:
                    client.table("trades").update({
                        "realized_pnl_amt": pnl,
                        "fill_amount": fill_amt,
                    }).eq("id", s["id"]).execute()
                    backfilled += 1
                except Exception as e:
                    print(f"  백필 실패 ({s['id'][:8]}): {e}")

    print(f"  {backfilled}/{len(sell_trades)}건 백필 완료.")
    print(f"\n부트스트랩 완료!")
    print(f"이후 모든 BUY/SELL 거래는 자동으로 원장에 기록됩니다.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="현금 원장 부트스트랩")
    parser.add_argument("--dry-run", action="store_true", help="실제 저장 없이 결과만 확인")
    args = parser.parse_args()

    client = get_client()
    bootstrap_ledger(client, dry_run=args.dry_run)
