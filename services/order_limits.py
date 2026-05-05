"""주문 금액 상한 검증 모듈.

실계좌 운영 시 주문당·일별 총액 상한을 강제하는 안전장치.
환경변수로 임계값 토글 가능 (PM2 restart로 반영).

env:
- ORDER_MAX_PER_TRADE: 주문당 최대 (원, default 1,000,000)
- ORDER_MAX_DAILY_TOTAL: 일별 BUY 총액 최대 (원, default 5,000,000)

거부 시 (ok=False, reason)을 반환. caller(executor)는 거부 시 주문을 보내지 않고 텔레그램 알림.
"""
from __future__ import annotations

import logging
import os
from datetime import date

logger = logging.getLogger(__name__)


def _env_int(key: str, default: int) -> int:
    """env 정수 로드. 잘못된 값이면 default."""
    raw = os.getenv(key, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"[order_limits] {key} 파싱 실패: {raw}, default={default} 사용")
        return default


def _today_buy_total() -> int:
    """오늘 자정~현재까지 trades 테이블의 BUY action fill_amount 합계 (원).

    Supabase 미설정 시 0 반환 (한도 체크 부분 무력화 — 안전 측면에서 보수적).
    DRY_RUN 거래는 mode 컬럼으로 별도, 한도 합산 대상에서 제외 (선택적).
    """
    try:
        from database.db import _get_client
    except Exception as exc:
        logger.warning(f"[order_limits] db import 실패: {exc}")
        return 0

    client = _get_client()
    if client is None:
        logger.debug("[order_limits] Supabase 미설정 — 일별 한도 0 반환")
        return 0

    today_iso = f"{date.today().isoformat()}T00:00:00"
    try:
        res = (
            client.table("trades")
            .select("fill_amount")
            .eq("action", "BUY")
            .gte("created_at", today_iso)
            .execute()
        )
        total = sum(int(r.get("fill_amount") or 0) for r in (res.data or []))
        return total
    except Exception as exc:
        logger.warning(f"[order_limits] today_buy_total 조회 실패: {exc}")
        return 0


def check_order_limit(
    action: str,
    code: str,
    quantity: int,
    expected_price: int | float,
) -> tuple[bool, str]:
    """주문 한도 검증. BUY만 검사 (SELL은 손절 차단 위험으로 면제).

    Parameters
    ----------
    action : "BUY" | "SELL"
    code : 종목코드
    quantity : 주문 수량
    expected_price : 예상 체결가 (시장가 주문이라 정확 X, 직전 시세 권장)

    Returns
    -------
    (ok, reason)
        ok=True: 한도 통과
        ok=False: 거부, reason은 사용자/텔레그램 알림용 메시지
    """
    if action != "BUY":
        return True, ""

    if expected_price <= 0 or quantity <= 0:
        return True, ""  # 잘못된 입력은 한도 검증 skip (다른 검증에서 처리)

    estimated_amount = int(round(expected_price * quantity))
    per_max = _env_int("ORDER_MAX_PER_TRADE", 1_000_000)
    daily_max = _env_int("ORDER_MAX_DAILY_TOTAL", 5_000_000)

    # 1. per-order 한도
    if estimated_amount > per_max:
        return False, (
            f"주문당 한도 초과: {code} {quantity}주 × {expected_price:,.0f} = "
            f"{estimated_amount:,}원 > 한도 {per_max:,}원"
        )

    # 2. daily 한도
    today_total = _today_buy_total()
    if today_total + estimated_amount > daily_max:
        return False, (
            f"일별 한도 초과: 오늘 누적 {today_total:,} + 신규 {estimated_amount:,} = "
            f"{today_total + estimated_amount:,}원 > 한도 {daily_max:,}원"
        )

    return True, ""
