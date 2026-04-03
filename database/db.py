"""
Supabase 저장 모듈
파이프라인 실행 결과를 Supabase에 저장하는 함수 모음.
에이전트 코드에서 import해서 사용.
"""

import os
import uuid
import logging
from datetime import date
from typing import Optional

from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 클라이언트 초기화 (지연 싱글턴)
# ---------------------------------------------------------------------------

_client = None  # supabase.Client | None


def _get_client():
    """Supabase 클라이언트 반환. URL/KEY 미설정 시 None 반환."""
    global _client
    if _client is None:
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_KEY", "")
        if url and key:
            try:
                from supabase import create_client
                _client = create_client(url, key)
            except Exception as e:
                logger.warning(f"[db] Supabase 클라이언트 초기화 실패: {e}")
    return _client


# ---------------------------------------------------------------------------
# 1. save_trade
# ---------------------------------------------------------------------------

def save_trade(order_result: dict, signal: dict) -> Optional[str]:
    """
    trades 테이블에 주문 결과 저장.

    Parameters
    ----------
    order_result : dict
        실행 에이전트가 반환한 주문 결과.
        필수 키: order_id, action, results (리스트), mode
    signal : dict
        로직적용 에이전트가 생성한 신호.
        필수 키: phase

    Returns
    -------
    str | None
        저장된 첫 번째 레코드의 uuid, 실패 시 None.
    """
    client = _get_client()
    if client is None:
        logger.debug("[db] save_trade: Supabase 미설정, 저장 건너뜀")
        return None

    try:
        order_id = order_result.get("order_id", "")
        action = order_result.get("action", "")
        mode = order_result.get("mode", "MOCK")
        phase = signal.get("phase", "")
        results = order_result.get("results", [])

        # status == "OK"인 항목만 저장
        ok_results = [r for r in results if r.get("status") == "OK"]
        if not ok_results:
            logger.debug("[db] save_trade: 저장할 OK 결과 없음")
            return None

        strategy_id = signal.get("strategy_id", None)
        first_id = None
        for result in ok_results:
            record_id = str(uuid.uuid4())
            row = {
                "id":          record_id,
                "order_id":    order_id,
                "code":        result.get("code", ""),
                "name":        result.get("name", ""),
                "action":      action,
                "quantity":    int(result.get("quantity", 1)),
                "price":       int(result.get("price", 0)),
                "phase":       phase,
                "result_pct":  float(result.get("result_pct", 0.0)),
                "mode":        mode,
                "strategy_id": result.get("strategy_id") or strategy_id,
            }
            client.table("trades").insert(row).execute()
            if first_id is None:
                first_id = record_id

        return first_id

    except Exception as e:
        logger.warning(f"[db] save_trade 실패: {e}")
        return None


# ---------------------------------------------------------------------------
# 2. save_market_phase
# ---------------------------------------------------------------------------

def save_market_phase(signal: dict) -> Optional[str]:
    """
    market_phases 테이블에 국면 저장.
    오늘 날짜에 같은 phase가 이미 있으면 저장 안 함 (중복 방지).

    Parameters
    ----------
    signal : dict
        필수 키: phase, confidence

    Returns
    -------
    str | None
        저장된 레코드의 uuid, 실패(중복 포함) 시 None.
    """
    client = _get_client()
    if client is None:
        logger.debug("[db] save_market_phase: Supabase 미설정, 저장 건너뜀")
        return None

    try:
        phase = signal.get("phase", "")
        confidence = signal.get("confidence", 0.0)
        today = date.today().isoformat()  # "YYYY-MM-DD"

        # 중복 확인: 오늘 날짜에 같은 phase 존재 여부
        existing = (
            client.table("market_phases")
            .select("id")
            .eq("phase", phase)
            .eq("start_date", today)
            .execute()
        )
        if existing.data:
            logger.debug(f"[db] save_market_phase: 오늘({today}) {phase} 이미 존재, 건너뜀")
            return None

        record_id = str(uuid.uuid4())
        row = {
            "id":         record_id,
            "phase":      phase,
            "confidence": confidence,
            "start_date": today,
            "end_date":   None,
        }
        client.table("market_phases").insert(row).execute()
        return record_id

    except Exception as e:
        logger.warning(f"[db] save_market_phase 실패: {e}")
        return None


# ---------------------------------------------------------------------------
# 3. save_agent_log
# ---------------------------------------------------------------------------

def save_agent_log(
    agent: str,
    level: str,
    message: str,
    error_code: str = "",
) -> None:
    """
    agent_logs 테이블에 로그 저장.
    실패해도 예외 전파 안 함 (로깅 실패가 시스템 중단으로 이어지면 안 됨).

    Parameters
    ----------
    agent      : 에이전트명 (예: "data_collector")
    level      : 로그 레벨 (예: "INFO", "ERROR", "CRITICAL")
    message    : 로그 메시지
    error_code : 오류 코드 (선택, 기본값 빈 문자열)
    """
    client = _get_client()
    if client is None:
        return  # Supabase 미설정 → 조용히 무시

    try:
        from datetime import datetime, timezone
        row = {
            "id":         str(uuid.uuid4()),
            "agent":      agent,
            "level":      level,
            "message":    message,
            "error_code": error_code,
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        }
        client.table("agent_logs").insert(row).execute()
    except Exception as e:
        # 로그 저장 실패는 콘솔 경고만 출력, 예외 전파 금지
        logger.warning(f"[db] save_agent_log 실패: {e}")


# ---------------------------------------------------------------------------
# 4. save_position
# ---------------------------------------------------------------------------

def save_position(
    code: str,
    name: str,
    avg_price: float,
    buy_order_id: str,
    quantity: int = 1,
    buy_trade_id: Optional[str] = None,
    phase: Optional[str] = None,
    mode: str = "MOCK",
    strategy_id: Optional[str] = None,
    holding_period: Optional[str] = None,
    entry_time: Optional[str] = None,
    max_exit_date: Optional[str] = None,
) -> Optional[str]:
    """
    positions 테이블에 신규 OPEN 포지션 저장.
    동일 code + OPEN 상태가 이미 있으면 None 반환 (중복 방지).

    Returns
    -------
    str | None
        생성된 position UUID, 중복/실패 시 None.
    """
    client = _get_client()
    if client is None:
        logger.debug("[db] save_position: Supabase 미설정, 저장 건너뜀")
        return None

    try:
        # 중복 체크 (OPEN 상태 동일 종목)
        existing = (
            client.table("positions")
            .select("id")
            .eq("code", code)
            .eq("status", "OPEN")
            .execute()
        )
        if existing.data:
            logger.debug(f"[db] save_position: {code} 이미 OPEN 포지션 존재, 건너뜀")
            return None

        record_id = str(uuid.uuid4())
        row: dict = {
            "id":           record_id,
            "code":         code,
            "name":         name,
            "quantity":     max(1, int(quantity)),
            "avg_price":    avg_price,
            "buy_order_id": buy_order_id,
            "status":       "OPEN",
            "mode":         mode,
        }
        if buy_trade_id:
            row["buy_trade_id"] = buy_trade_id
        if phase:
            row["phase_at_buy"] = phase
        if strategy_id:
            row["strategy_id"] = strategy_id
        if holding_period:
            row["holding_period"] = holding_period
        if entry_time:
            row["entry_time"] = entry_time
        if max_exit_date:
            row["max_exit_date"] = max_exit_date
        # peak_price는 avg_price로 초기화 (트레일링 스탑용)
        row["peak_price"] = avg_price

        client.table("positions").insert(row).execute()
        logger.debug(f"[db] save_position: {name}({code}) 저장 완료")
        return record_id

    except Exception as e:
        logger.warning(f"[db] save_position 실패: {e}")
        return None


# ---------------------------------------------------------------------------
# 5. get_open_positions
# ---------------------------------------------------------------------------

def get_open_positions() -> list:
    """
    status='OPEN'인 모든 포지션 조회.

    Returns
    -------
    list[dict]
        OPEN 포지션 목록. Supabase 미설정 또는 실패 시 빈 리스트.
    """
    client = _get_client()
    if client is None:
        return []

    try:
        result = (
            client.table("positions")
            .select("*")
            .eq("status", "OPEN")
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.warning(f"[db] get_open_positions 실패: {e}")
        return []


# ---------------------------------------------------------------------------
# 6. get_position_by_code
# ---------------------------------------------------------------------------

def get_position_by_code(code: str) -> Optional[dict]:
    """
    특정 종목코드의 OPEN 포지션 단건 조회.

    Returns
    -------
    dict | None
        OPEN 포지션 정보. 없으면 None.
    """
    client = _get_client()
    if client is None:
        return None

    try:
        result = (
            client.table("positions")
            .select("*")
            .eq("code", code)
            .eq("status", "OPEN")
            .execute()
        )
        if result.data:
            return result.data[0]
        return None
    except Exception as e:
        logger.warning(f"[db] get_position_by_code 실패: {e}")
        return None


# ---------------------------------------------------------------------------
# 7. close_position
# ---------------------------------------------------------------------------

def close_position(
    position_id: str,
    close_reason: str,
    result_pct: float,
) -> bool:
    """
    포지션을 CLOSED로 변경하고 결과를 기록한다.
    연결된 trades 레코드의 result_pct도 함께 업데이트.

    Returns
    -------
    bool
        성공 여부.
    """
    client = _get_client()
    if client is None:
        return False

    try:
        from datetime import datetime, timezone
        result = (
            client.table("positions")
            .update({
                "status":       "CLOSED",
                "closed_at":    datetime.now(timezone.utc).isoformat(),
                "close_reason": close_reason,
                "result_pct":   round(result_pct, 4),
            })
            .eq("id", position_id)
            .execute()
        )
        if not result.data:
            return False

        # 연결된 trades 레코드 result_pct 동기화
        buy_trade_id = result.data[0].get("buy_trade_id")
        if buy_trade_id:
            update_trade_result_pct(buy_trade_id, result_pct)

        logger.debug(f"[db] close_position: {position_id} → {close_reason} ({result_pct:+.2f}%)")
        return True

    except Exception as e:
        logger.warning(f"[db] close_position 실패: {e}")
        return False


# ---------------------------------------------------------------------------
# 8. update_trade_result_pct
# ---------------------------------------------------------------------------

def update_trade_result_pct(trade_id: str, result_pct: float) -> bool:
    """
    trades 테이블의 특정 레코드 result_pct 업데이트.

    Returns
    -------
    bool
        성공 여부.
    """
    client = _get_client()
    if client is None:
        return False

    try:
        client.table("trades").update({
            "result_pct": round(result_pct, 4),
        }).eq("id", trade_id).execute()
        return True
    except Exception as e:
        logger.warning(f"[db] update_trade_result_pct 실패: {e}")
        return False


# ---------------------------------------------------------------------------
# 9. update_position_peak
# ---------------------------------------------------------------------------

def update_position_peak(position_id: str, peak_price: float) -> bool:
    """
    포지션의 peak_price 업데이트 (트레일링 스탑용).
    peak_price가 현재값보다 높을 때만 호출한다.
    """
    client = _get_client()
    if client is None:
        return False
    try:
        client.table("positions").update({"peak_price": peak_price}).eq("id", position_id).execute()
        return True
    except Exception as e:
        logger.warning(f"[db] update_position_peak 실패: {e}")
        return False


# ---------------------------------------------------------------------------
# 9-b. update_position_result_pct
# ---------------------------------------------------------------------------

def update_position_result_pct(position_id: str, result_pct: float) -> bool:
    """OPEN 포지션의 실시간 수익률을 갱신한다."""
    client = _get_client()
    if client is None:
        return False
    try:
        client.table("positions").update(
            {"result_pct": round(result_pct, 4)}
        ).eq("id", position_id).execute()
        return True
    except Exception as e:
        logger.warning(f"[db] update_position_result_pct 실패: {e}")
        return False


# ---------------------------------------------------------------------------
# 10-a. update_position_horizon
# ---------------------------------------------------------------------------

def update_position_horizon(
    position_id: str,
    new_horizon: str,
    new_max_exit_date: Optional[str] = None,
) -> bool:
    """
    포지션의 holding_period와 max_exit_date를 업데이트한다.
    국면 변화에 따른 투자 기간 업그레이드/다운그레이드 시 호출.
    """
    client = _get_client()
    if client is None:
        return False
    try:
        update_data: dict = {"holding_period": new_horizon}
        if new_max_exit_date is not None:
            update_data["max_exit_date"] = new_max_exit_date
        client.table("positions").update(update_data).eq("id", position_id).execute()
        return True
    except Exception as e:
        logger.warning(f"[db] update_position_horizon 실패: {e}")
        return False


# ---------------------------------------------------------------------------
# 10. upsert_strategy
# ---------------------------------------------------------------------------

def upsert_strategy(card: dict) -> Optional[str]:
    """
    strategies 테이블에 전략 카드 upsert (id 기준).
    반환: strategy id (str) 또는 None.
    """
    client = _get_client()
    if client is None:
        logger.debug("[db] upsert_strategy: Supabase 미설정, 건너뜀")
        return None
    try:
        perf = card.get("performance", {})
        row = {
            "id":         card["id"],
            "name":       card.get("description", ""),
            "group_name": card.get("group", ""),
            "phase":      card.get("phase", ""),
            "win_rate":   perf.get("backtest_win_rate", 0.0),
            "return_pct": perf.get("backtest_return_pct", 0.0),
            "mdd":        perf.get("mdd", 0.0),
            "conditions": card.get("conditions", {}),
            "status":     perf.get("status", "백테스팅중"),
        }
        client.table("strategies").upsert(row).execute()
        return card["id"]
    except Exception as e:
        logger.warning(f"[db] upsert_strategy 실패: {e}")
        return None


# ---------------------------------------------------------------------------
# 10. get_strategies_by_phase
# ---------------------------------------------------------------------------

def get_strategies_by_phase(phase: str, active_only: bool = True) -> list:
    """
    특정 국면의 전략 목록 조회.
    active_only=True이면 status != '비활성' 필터 적용.
    실패 시 빈 리스트 반환.
    """
    client = _get_client()
    if client is None:
        return []
    try:
        query = client.table("strategies").select("*").eq("phase", phase)
        if active_only:
            query = query.neq("status", "비활성")
        result = query.execute()
        return result.data or []
    except Exception as e:
        logger.warning(f"[db] get_strategies_by_phase 실패: {e}")
        return []


# ---------------------------------------------------------------------------
# 11. save_backtest_result
# ---------------------------------------------------------------------------

def save_backtest_result(
    strategy_id: str,
    phase: str,
    period_start: str,
    period_end: str,
    win_rate: float,
    return_pct: float,
    mdd: float,
) -> Optional[str]:
    """
    backtest_results 테이블에 단일 기간 결과 저장.
    반환: 생성된 UUID 또는 None.
    """
    client = _get_client()
    if client is None:
        logger.debug("[db] save_backtest_result: Supabase 미설정, 건너뜀")
        return None
    try:
        record_id = str(uuid.uuid4())
        row = {
            "id":           record_id,
            "strategy_id":  strategy_id,
            "phase":        phase,
            "period_start": period_start,
            "period_end":   period_end,
            "win_rate":     round(win_rate, 4),
            "return_pct":   round(return_pct, 4),
            "mdd":          round(mdd, 4),
        }
        client.table("backtest_results").insert(row).execute()
        return record_id
    except Exception as e:
        logger.warning(f"[db] save_backtest_result 실패: {e}")
        return None


# ---------------------------------------------------------------------------
# 12. save_market_snapshot
# ---------------------------------------------------------------------------

def save_market_snapshot(
    us_market: dict,
    kr_market: dict,
    commodities: dict,
) -> Optional[str]:
    """
    market_snapshots 테이블에 당일 수집 데이터 저장.
    파이프라인 실행마다 한 번씩 저장하여 대시보드 및 이력 분석에 활용.

    Returns
    -------
    str | None
        생성된 레코드 id, 실패 시 None.
    """
    client = _get_client()
    if client is None:
        logger.debug("[db] save_market_snapshot: Supabase 미설정, 건너뜀")
        return None

    try:
        import json as _json
        row = {
            "us_market":  _json.loads(_json.dumps(us_market)),
            "kr_market":  _json.loads(_json.dumps(kr_market)),
            "commodities": _json.loads(_json.dumps(commodities)),
        }
        result = client.table("market_snapshots").insert(row).execute()
        if result.data:
            return str(result.data[0].get("id", ""))
        return None
    except Exception as e:
        logger.warning(f"[db] save_market_snapshot 실패: {e}")
        return None


# ---------------------------------------------------------------------------
# 13. save_account_summary
# ---------------------------------------------------------------------------

def save_account_summary(
    cash_amt: int,
    stock_evlu_amt: int,
    tot_evlu_amt: int,
    pchs_amt: int,
    evlu_pfls_amt: int,
    erng_rt: float,
    mode: str = "MOCK",
) -> Optional[str]:
    """
    account_summary 테이블에 계좌 잔고 저장.
    매 파이프라인 실행 시 최신 잔고 스냅샷을 저장한다.

    Returns
    -------
    str | None
        생성된 레코드 id, 실패 시 None.
    """
    client = _get_client()
    if client is None:
        logger.debug("[db] save_account_summary: Supabase 미설정, 건너뜀")
        return None

    try:
        row = {
            "cash_amt":      cash_amt,
            "stock_evlu_amt": stock_evlu_amt,
            "tot_evlu_amt":  tot_evlu_amt,
            "pchs_amt":      pchs_amt,
            "evlu_pfls_amt": evlu_pfls_amt,
            "erng_rt":       round(erng_rt, 6),
            "mode":          mode,
        }
        result = client.table("account_summary").insert(row).execute()
        if result.data:
            return str(result.data[0].get("id", ""))
        return None
    except Exception as e:
        logger.warning(f"[db] save_account_summary 실패: {e}")
        return None


# ---------------------------------------------------------------------------
# 13. get_trades_for_backtest
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 14. save_position_analysis
# ---------------------------------------------------------------------------

def save_position_analysis(
    position_id: Optional[str],
    code: str,
    name: str,
    recommendation: str,
    reason: str,
    rsi: Optional[float] = None,
    price_change_5d: Optional[float] = None,
    above_ma20: Optional[bool] = None,
    news_sentiment: Optional[str] = None,
    target_exit_price: Optional[float] = None,
) -> Optional[str]:
    """
    position_analyses 테이블에 AI 분석 결과 저장.

    Parameters
    ----------
    position_id        : positions 테이블 uuid (외래키). None 허용.
    code               : 종목코드
    name               : 종목명
    recommendation     : 'HOLD' | 'CAUTION' | 'SELL'
    reason             : 분석 근거 (2-3문장)
    rsi                : RSI(14) 값. 없으면 None.
    price_change_5d    : 5일 수익률(%). 없으면 None.
    above_ma20         : 현재가가 20일 이동평균 위이면 True. 없으면 None.
    news_sentiment     : 'POSITIVE' | 'NEUTRAL' | 'NEGATIVE' | None
    target_exit_price  : 매도 목표가. 없으면 None.

    Returns
    -------
    str | None
        생성된 레코드 uuid, 실패 시 None.
    """
    client = _get_client()
    if client is None:
        logger.debug("[db] save_position_analysis: Supabase 미설정, 저장 건너뜀")
        return None

    try:
        record_id = str(uuid.uuid4())
        row: dict = {
            "id":             record_id,
            "code":           code,
            "name":           name,
            "recommendation": recommendation,
            "reason":         reason,
        }
        if position_id is not None:
            row["position_id"] = position_id
        if rsi is not None:
            row["rsi"] = round(float(rsi), 2)
        if price_change_5d is not None:
            row["price_change_5d"] = round(float(price_change_5d), 4)
        if above_ma20 is not None:
            row["above_ma20"] = bool(above_ma20)
        if news_sentiment is not None:
            row["news_sentiment"] = news_sentiment
        if target_exit_price is not None:
            row["target_exit_price"] = float(target_exit_price)

        client.table("position_analyses").insert(row).execute()
        logger.debug(f"[db] save_position_analysis: {name}({code}) → {recommendation} 저장 완료")
        return record_id

    except Exception as e:
        logger.warning(f"[db] save_position_analysis 실패: {e}")
        return None


# ---------------------------------------------------------------------------
# 15. get_latest_position_analyses
# ---------------------------------------------------------------------------

def get_latest_position_analyses() -> list:
    """
    OPEN 포지션에 연결된 position_analyses 중 position_id별 최신 1건씩 반환.

    Returns
    -------
    list[dict]
        각 항목에 position_id, code, name, recommendation, reason 등 포함.
        Supabase 미설정 또는 실패 시 빈 리스트.
    """
    client = _get_client()
    if client is None:
        return []

    try:
        # OPEN 포지션 id 목록 조회
        open_pos = (
            client.table("positions")
            .select("id")
            .eq("status", "OPEN")
            .execute()
        )
        if not open_pos.data:
            return []

        open_ids = [row["id"] for row in open_pos.data]

        # position_analyses에서 해당 id들의 레코드 조회 (created_at 내림차순)
        analyses = (
            client.table("position_analyses")
            .select("*")
            .in_("position_id", open_ids)
            .order("created_at", desc=True)
            .execute()
        )
        if not analyses.data:
            return []

        # position_id별 최신 1건만 추출
        seen: set = set()
        result = []
        for row in analyses.data:
            pid = row.get("position_id")
            if pid and pid not in seen:
                seen.add(pid)
                result.append(row)

        return result

    except Exception as e:
        logger.warning(f"[db] get_latest_position_analyses 실패: {e}")
        return []


# ---------------------------------------------------------------------------
# 13. get_trades_for_backtest  (번호 유지)
# ---------------------------------------------------------------------------

def get_trades_for_backtest(
    phase: str,
    strategy_id: Optional[str] = None,
    limit: int = 500,
) -> list:
    """
    백테스팅용 trades 조회.
    - result_pct가 0.0이 아닌 건만 반환 (확정된 거래)
    - phase 필터
    - strategy_id 있으면 추가 필터
    - created_at ASC 정렬
    실패 시 빈 리스트 반환.
    """
    client = _get_client()
    if client is None:
        return []
    try:
        query = (
            client.table("trades")
            .select("id, code, name, action, result_pct, phase, strategy_id, created_at")
            .eq("phase", phase)
            .neq("result_pct", 0.0)
            .order("created_at", desc=False)
            .limit(limit)
        )
        if strategy_id:
            query = query.eq("strategy_id", strategy_id)
        result = query.execute()
        return result.data or []
    except Exception as e:
        logger.warning(f"[db] get_trades_for_backtest 실패: {e}")
        return []


# ---------------------------------------------------------------------------
# 16. get_recent_closed_trades  (리스크 관리: 연속 손실 감지)
# ---------------------------------------------------------------------------

def get_recent_closed_trades(limit: int = 10) -> list:
    """
    최근 청산된 포지션을 limit건 반환한다 (closed_at DESC).
    연속 손실 감지용.

    Returns
    -------
    list[dict]
        각 항목에 result_pct, close_reason, closed_at 등 포함.
        Supabase 미설정 또는 실패 시 빈 리스트.
    """
    client = _get_client()
    if client is None:
        return []
    try:
        result = (
            client.table("positions")
            .select("id, code, name, result_pct, close_reason, closed_at")
            .eq("status", "CLOSED")
            .order("closed_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.warning(f"[db] get_recent_closed_trades 실패: {e}")
        return []


# ---------------------------------------------------------------------------
# 17. get_today_realized_pnl  (리스크 관리: Daily Stop Loss)
# ---------------------------------------------------------------------------

def get_today_realized_pnl() -> float:
    """
    오늘 청산된 모든 포지션의 result_pct 합산을 반환한다.
    Daily Stop Loss 판단용.

    Returns
    -------
    float
        오늘 실현 손익률 합산 (%). Supabase 미설정이면 0.0.
    """
    client = _get_client()
    if client is None:
        return 0.0
    try:
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        result = (
            client.table("positions")
            .select("result_pct, closed_at")
            .eq("status", "CLOSED")
            .gte("closed_at", today)
            .execute()
        )
        if not result.data:
            return 0.0
        return sum(float(r.get("result_pct", 0) or 0) for r in result.data)
    except Exception as e:
        logger.warning(f"[db] get_today_realized_pnl 실패: {e}")
        return 0.0


def get_open_positions_for_mtm() -> list:
    """
    OPEN 포지션의 avg_price, quantity, code를 반환한다.
    Mark-to-Market 미실현 손익 계산용.

    Returns
    -------
    list[dict]
        [{"code": str, "avg_price": float, "quantity": int}, ...]
    """
    client = _get_client()
    if client is None:
        return []
    try:
        result = (
            client.table("positions")
            .select("code, avg_price, quantity")
            .eq("status", "OPEN")
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.warning(f"[db] get_open_positions_for_mtm 실패: {e}")
        return []


def get_week_realized_pnl() -> float:
    """
    이번 주(월~일) 청산된 모든 포지션의 result_pct 합산을 반환한다.
    Weekly Stop Loss 판단용.

    Returns
    -------
    float
        이번 주 실현 손익률 합산 (%).
    """
    client = _get_client()
    if client is None:
        return 0.0
    try:
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        # 이번 주 월요일 00:00
        monday = (now - timedelta(days=now.weekday())).date().isoformat()
        result = (
            client.table("positions")
            .select("result_pct")
            .eq("status", "CLOSED")
            .gte("closed_at", monday)
            .execute()
        )
        if not result.data:
            return 0.0
        return sum(float(r.get("result_pct", 0) or 0) for r in result.data)
    except Exception as e:
        logger.warning(f"[db] get_week_realized_pnl 실패: {e}")
        return 0.0


# ---------------------------------------------------------------------------
# DCA (분할 매수) 관련
# ---------------------------------------------------------------------------

def save_pending_dca(
    position_id: str,
    code: str,
    name: str,
    stage: int,
    target_price: float,
    budget: float,
    quantity: int,
    expires_at: str,
) -> Optional[str]:
    """pending_dca 테이블에 2차 매수 대기 레코드 저장."""
    client = _get_client()
    if client is None:
        return None
    try:
        record_id = str(uuid.uuid4())
        row = {
            "id": record_id,
            "position_id": position_id,
            "code": code,
            "name": name,
            "stage": stage,
            "target_price": target_price,
            "budget": budget,
            "quantity": quantity,
            "status": "PENDING",
            "expires_at": expires_at,
        }
        client.table("pending_dca").insert(row).execute()
        logger.debug(f"[db] save_pending_dca: {name}({code}) stage={stage} 저장 완료")
        return record_id
    except Exception as e:
        logger.warning(f"[db] save_pending_dca 실패: {e}")
        return None


def get_pending_dca_list() -> list:
    """PENDING 상태인 DCA 대기 목록 반환."""
    client = _get_client()
    if client is None:
        return []
    try:
        resp = (
            client.table("pending_dca")
            .select("*")
            .eq("status", "PENDING")
            .execute()
        )
        return resp.data or []
    except Exception as e:
        logger.warning(f"[db] get_pending_dca_list 실패: {e}")
        return []


def update_pending_dca_status(dca_id: str, status: str) -> bool:
    """pending_dca 레코드 상태 업데이트. status: EXECUTED | EXPIRED | CANCELLED"""
    client = _get_client()
    if client is None:
        return False
    try:
        update_data: dict = {"status": status}
        if status == "EXECUTED":
            from datetime import datetime, timezone
            update_data["executed_at"] = datetime.now(timezone.utc).isoformat()
        client.table("pending_dca").update(update_data).eq("id", dca_id).execute()
        return True
    except Exception as e:
        logger.warning(f"[db] update_pending_dca_status 실패: {e}")
        return False


def lock_pending_dca(dca_id: str) -> bool:
    """
    DCA 중복 실행 방지: PENDING → EXECUTING 원자적 상태 전환.
    이미 PENDING이 아닌 경우 (다른 프로세스가 먼저 잡은 경우) False 반환.

    Returns
    -------
    bool
        True: 잠금 성공 (실행 가능), False: 이미 다른 상태로 전환됨
    """
    client = _get_client()
    if client is None:
        return False
    try:
        result = (
            client.table("pending_dca")
            .update({"status": "EXECUTING"})
            .eq("id", dca_id)
            .eq("status", "PENDING")  # PENDING인 경우에만 업데이트
            .execute()
        )
        # 업데이트된 행이 있으면 잠금 성공
        return len(result.data or []) > 0
    except Exception as e:
        logger.warning(f"[db] lock_pending_dca 실패: {e}")
        return False


# ---------------------------------------------------------------------------
# Exit Plans (가격 예측 기반 매도 계획)
# ---------------------------------------------------------------------------

def save_exit_plan(plan: dict) -> Optional[str]:
    """exit_plans 테이블에 upsert (position_id 기준)."""
    client = _get_client()
    if client is None:
        return None
    try:
        position_id = plan.get("position_id")
        if not position_id:
            return None
        from datetime import datetime, timezone
        plan["updated_at"] = datetime.now(timezone.utc).isoformat()
        # upsert: position_id가 같으면 업데이트
        result = client.table("exit_plans").upsert(
            plan, on_conflict="position_id"
        ).execute()
        return result.data[0]["id"] if result.data else None
    except Exception as e:
        logger.warning(f"[db] save_exit_plan 실패: {e}")
        return None


def get_exit_plan(position_id: str) -> Optional[dict]:
    """position_id로 exit_plan 단건 조회."""
    client = _get_client()
    if client is None:
        return None
    try:
        result = (
            client.table("exit_plans")
            .select("*")
            .eq("position_id", position_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.warning(f"[db] get_exit_plan 실패: {e}")
        return None


def get_all_active_exit_plans() -> list:
    """OPEN 포지션의 exit_plan 전체 조회."""
    client = _get_client()
    if client is None:
        return []
    try:
        result = client.table("exit_plans").select("*").execute()
        return result.data or []
    except Exception as e:
        logger.warning(f"[db] get_all_active_exit_plans 실패: {e}")
        return []


def update_exit_plan_stage(position_id: str, stages: list, version: int) -> bool:
    """exit_plan의 exit_stages 업데이트 (단계 상태 변경)."""
    client = _get_client()
    if client is None:
        return False
    try:
        import json
        from datetime import datetime, timezone
        client.table("exit_plans").update({
            "exit_stages": json.dumps(stages) if isinstance(stages, list) else stages,
            "plan_version": version,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("position_id", position_id).execute()
        return True
    except Exception as e:
        logger.warning(f"[db] update_exit_plan_stage 실패: {e}")
        return False


def delete_exit_plan(position_id: str) -> bool:
    """포지션 종료 시 exit_plan 삭제."""
    client = _get_client()
    if client is None:
        return False
    try:
        client.table("exit_plans").delete().eq("position_id", position_id).execute()
        return True
    except Exception as e:
        logger.warning(f"[db] delete_exit_plan 실패: {e}")
        return False


# ---------------------------------------------------------------------------
# 계좌 히스토리
# ---------------------------------------------------------------------------

def get_account_history(days: int = 30) -> list:
    """account_history 테이블에서 최근 N일 조회 (날짜 내림차순)."""
    client = _get_client()
    if client is None:
        return []
    try:
        from datetime import datetime, timedelta, timezone
        start = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
        resp = (
            client.table("account_history")
            .select("*")
            .gte("recorded_date", start)
            .order("recorded_date", desc=True)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        logger.warning(f"[db] get_account_history 실패: {e}")
        return []


def get_account_history_detail(target_date: str) -> dict:
    """특정 날짜의 account_history + 해당 날 trades 조회."""
    client = _get_client()
    if client is None:
        return {}
    try:
        # account_history
        hist = (
            client.table("account_history")
            .select("*")
            .eq("recorded_date", target_date)
            .limit(1)
            .execute()
        )
        history = hist.data[0] if hist.data else {}

        # 해당 날 trades
        start = f"{target_date}T00:00:00+00:00"
        end   = f"{target_date}T23:59:59+00:00"
        trades_resp = (
            client.table("trades")
            .select("*")
            .gte("created_at", start)
            .lte("created_at", end)
            .order("created_at")
            .execute()
        )
        return {"history": history, "trades": trades_resp.data or []}
    except Exception as e:
        logger.warning(f"[db] get_account_history_detail 실패: {e}")
        return {}


# ---------------------------------------------------------------------------
# 재무지표 (financial_indicators)
# ---------------------------------------------------------------------------

def upsert_financial_indicators(data: dict):
    """재무 지표 저장. 같은 symbol+날짜면 업데이트."""
    client = _get_client()
    if client is None:
        return None
    try:
        row = {k: v for k, v in data.items() if v is not None}
        row.setdefault("fetched_date", date.today().isoformat())
        result = client.table("financial_indicators").upsert(
            row, on_conflict="symbol,fetched_date"
        ).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.warning(f"[db] upsert_financial_indicators 실패: {e}")
        return None


def get_financial_indicators(symbol: str):
    """최신 재무 지표 1건 조회."""
    client = _get_client()
    if client is None:
        return None
    try:
        result = (
            client.table("financial_indicators")
            .select("*")
            .eq("symbol", symbol)
            .order("fetched_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.warning(f"[db] get_financial_indicators 실패: {e}")
        return None


def get_financial_indicators_batch(symbols: list) -> dict:
    """여러 종목 최신 재무 지표 일괄 조회."""
    client = _get_client()
    if client is None:
        return {}
    try:
        result = (
            client.table("financial_indicators")
            .select("*")
            .in_("symbol", symbols)
            .order("fetched_at", desc=True)
            .execute()
        )
        out = {}
        for row in (result.data or []):
            sym = row["symbol"]
            if sym not in out:  # 최신 1건만
                out[sym] = row
        return out
    except Exception as e:
        logger.warning(f"[db] get_financial_indicators_batch 실패: {e}")
        return {}


# ---------------------------------------------------------------------------
# 예측 로그 (prediction_log)
# ---------------------------------------------------------------------------

def save_prediction_log(data: dict):
    """예측 결과를 prediction_log에 저장."""
    client = _get_client()
    if client is None:
        return None
    try:
        result = client.table("prediction_log").insert(data).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.warning(f"[db] save_prediction_log 실패: {e}")
        return None
