"""
주문 흐름 통합 테스트
1. 토큰 발급
2. 샘플 종목 BUY 주문 (KODEX 200 ETF / 069500)
3. 미체결 내역 조회로 주문 접수 확인
4. 주문 취소
5. 취소 확인
"""

import asyncio
import os
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import requests
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────
# 설정
# ──────────────────────────────
BASE_URL   = "https://openapivts.koreainvestment.com:29443"
APP_KEY    = os.getenv("KIS_APP_KEY")
APP_SECRET = os.getenv("KIS_APP_SECRET")
ACCOUNT_NO = os.getenv("KIS_ACCOUNT_NO", "")

# 계좌번호 8자리 + 상품코드 2자리
CANO         = ACCOUNT_NO[:8]
ACNT_PRDT_CD = ACCOUNT_NO[8:] if len(ACCOUNT_NO) > 8 else "01"

# 테스트 종목: KODEX 200 ETF (유동성 높고 가격 낮음)
TEST_CODE = "069500"
TEST_NAME = "KODEX 200"


# ──────────────────────────────
# 토큰 발급
# ──────────────────────────────
def get_token() -> str:
    print("\n[1] 토큰 발급 요청...")
    url  = f"{BASE_URL}/oauth2/tokenP"
    body = {
        "grant_type": "client_credentials",
        "appkey":     APP_KEY,
        "appsecret":  APP_SECRET,
    }
    resp = requests.post(url, json=body, timeout=10)
    resp.raise_for_status()
    data  = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"토큰 없음: {data}")
    print(f"    ✓ 토큰 발급 완료 (앞 20자: {token[:20]}...)")
    return token


# ──────────────────────────────
# BUY 주문
# ──────────────────────────────
def place_buy_order(token: str) -> str:
    """시장가 BUY 1주. 주문번호(ODNO) 반환."""
    print(f"\n[2] BUY 주문: {TEST_NAME}({TEST_CODE}) 시장가 1주")
    print(f"    계좌: {CANO} / 상품코드: {ACNT_PRDT_CD}")

    url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/order-cash"
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey":        APP_KEY,
        "appsecret":     APP_SECRET,
        "tr_id":         "VTTC0802U",  # 모의 BUY
        "custtype":      "P",
    }
    body = {
        "CANO":         CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "PDNO":         TEST_CODE,
        "ORD_DVSN":     "01",   # 시장가
        "ORD_QTY":      "1",
        "ORD_UNPR":     "0",
    }

    resp = requests.post(url, json=body, headers=headers, timeout=10)
    data = resp.json()

    print(f"    HTTP {resp.status_code}")
    print(f"    응답: rt_cd={data.get('rt_cd')}  msg1={data.get('msg1')}")

    rt_cd = data.get("rt_cd", "")
    if rt_cd == "0":
        order_no = data.get("output", {}).get("ODNO", "")
        print(f"    ✓ 주문 접수 완료 — 주문번호: {order_no}")
        return order_no
    else:
        print(f"    ✗ 주문 실패")
        print(f"    전체 응답: {data}")
        return ""


# ──────────────────────────────
# 미체결 주문 조회
# ──────────────────────────────
def get_unexecuted_orders(token: str) -> list:
    """당일 미체결 주문 목록 조회."""
    print("\n[3] 미체결 주문 조회...")

    url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl"
    headers = {
        "Content-Type":  "application/json",
        "authorization": f"Bearer {token}",
        "appkey":        APP_KEY,
        "appsecret":     APP_SECRET,
        "tr_id":         "VTTC8036R",  # 모의 미체결 조회
        "custtype":      "P",
    }
    params = {
        "CANO":           CANO,
        "ACNT_PRDT_CD":   ACNT_PRDT_CD,
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
        "INQR_DVSN_1":    "0",  # 전체
        "INQR_DVSN_2":    "0",  # 전체
    }

    resp = requests.get(url, headers=headers, params=params, timeout=10)
    data = resp.json()

    rt_cd  = data.get("rt_cd", "")
    orders = data.get("output", [])

    if rt_cd == "0":
        print(f"    ✓ 미체결 주문 {len(orders)}건")
        for o in orders:
            print(f"      종목: {o.get('pdno')} {o.get('prdt_name')} | "
                  f"수량: {o.get('ord_qty')} | "
                  f"주문번호: {o.get('odno')} | "
                  f"상태: {o.get('ord_tmd')}")
    else:
        print(f"    ✗ 조회 실패: {data.get('msg1')}")
        print(f"    전체 응답: {data}")

    return orders


# ──────────────────────────────
# 주문 취소
# ──────────────────────────────
def cancel_order(token: str, order_no: str) -> bool:
    """주문번호로 취소 요청."""
    if not order_no:
        print("\n[4] 주문번호 없음 → 취소 건너뜀")
        return False

    print(f"\n[4] 주문 취소: 주문번호 {order_no}")

    url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/order-rvsecncl"
    headers = {
        "Content-Type":  "application/json",
        "authorization": f"Bearer {token}",
        "appkey":        APP_KEY,
        "appsecret":     APP_SECRET,
        "tr_id":         "VTTC0803U",  # 모의 취소/정정
        "custtype":      "P",
    }
    body = {
        "CANO":         CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "KRX_FWDG_ORD_ORGNO": "",   # 원주문 HTS ID (공백 허용)
        "ORGN_ODNO":    order_no,    # 원주문번호
        "ORD_DVSN":     "01",        # 시장가
        "RVSE_CNCL_DVSN_CD": "02",  # 02=취소
        "ORD_QTY":      "0",         # 0=전량
        "ORD_UNPR":     "0",
        "QTY_ALL_ORD_YN": "Y",       # 잔량 전부
    }

    resp = requests.post(url, json=body, headers=headers, timeout=10)
    data = resp.json()

    print(f"    HTTP {resp.status_code}")
    print(f"    응답: rt_cd={data.get('rt_cd')}  msg1={data.get('msg1')}")

    if data.get("rt_cd") == "0":
        cancel_no = data.get("output", {}).get("ODNO", "")
        print(f"    ✓ 취소 완료 — 취소 주문번호: {cancel_no}")
        return True
    else:
        print(f"    ✗ 취소 실패")
        print(f"    전체 응답: {data}")
        return False


# ──────────────────────────────
# 메인
# ──────────────────────────────
def main():
    print("=" * 50)
    print(" KIS 모의투자 주문 흐름 테스트")
    print("=" * 50)
    print(f" 계좌: {CANO}-{ACNT_PRDT_CD}")
    print(f" 종목: {TEST_NAME} ({TEST_CODE})")
    print("=" * 50)

    try:
        # 1. 토큰
        token = get_token()

        # 2. 주문
        order_no = place_buy_order(token)

        # 3. 미체결 조회
        get_unexecuted_orders(token)

        # 4. 취소
        if order_no:
            cancel_order(token, order_no)

            # 5. 취소 후 미체결 재확인
            print("\n[5] 취소 후 미체결 재확인...")
            remaining = get_unexecuted_orders(token)
            cancelled = all(o.get("odno") != order_no for o in remaining)
            if cancelled:
                print("    ✓ 주문이 목록에서 사라짐 → 취소 확인")
            else:
                print("    △ 주문이 아직 목록에 있음 (장 마감 후 정리될 수 있음)")

        print("\n" + "=" * 50)
        print(" 테스트 완료")
        print("=" * 50)

    except Exception as e:
        print(f"\n✗ 오류 발생: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
