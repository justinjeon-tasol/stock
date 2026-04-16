"""
포지션 관리 서비스 모듈.
현재 보유 포지션 CRUD, 매도 조건 판단, KIS 잔고 동기화를 담당한다.
BaseAgent를 상속하지 않는 순수 서비스 클래스.
Executor와 WeightAdjuster에서 의존성 주입으로 사용한다.
"""

import asyncio
import logging
import os
import time
from typing import Optional

import requests
from dotenv import load_dotenv

from agents.horizon_manager import HorizonManager
from database.db import (
    save_position,
    get_open_positions,
    get_position_by_code,
    close_position,
    update_position_peak,
    update_position_result_pct,
)

logger = logging.getLogger(__name__)

# KIS 모의투자 베이스 URL
_KIS_BASE_URL = "https://openapivts.koreainvestment.com:29443"
# KIS 실전 서버 (시세 조회는 실전 서버만 지원, 모의투자 키로도 가능)
_KIS_REAL_URL = "https://openapi.koreainvestment.com:9443"

# 손절/익절 기본 임계값 (holding_period 없는 포지션 fallback)
_STOP_LOSS_PCT   = -5.0
_TAKE_PROFIT_PCT = +8.0

# 전량 매도 발동 국면 (6단계 기준)
_DEFENSIVE_PHASES = {"하락장", "대폭락장", "변동폭큰"}


class PositionManager:
    """
    포지션 CRUD, 매도 판단, KIS 잔고 동기화 서비스.
    Executor와 WeightAdjuster에서 공유하는 서비스 레이어.
    """

    def __init__(self) -> None:
        load_dotenv()
        self._app_key    = os.getenv("KIS_APP_KEY")
        self._app_secret = os.getenv("KIS_APP_SECRET")
        account_no       = os.getenv("KIS_ACCOUNT_NO", "")
        self._cano         = account_no[:8]
        self._horizon    = HorizonManager()
        self._acnt_prdt_cd = account_no[8:] if len(account_no) > 8 else "01"

    # ------------------------------------------------------------------
    # 동기 메서드
    # ------------------------------------------------------------------

    def get_open_positions(self) -> list:
        """OPEN 상태 포지션 전체 반환. 실패 시 빈 리스트."""
        return get_open_positions()

    def is_already_held(self, code: str) -> bool:
        """해당 종목을 현재 보유 중이면 True."""
        return get_position_by_code(code) is not None

    def get_position_by_code(self, code: str) -> Optional[dict]:
        """종목코드로 OPEN 포지션 조회."""
        return get_position_by_code(code)

    def open_position(
        self,
        code: str,
        name: str,
        avg_price: float,
        buy_order_id: str,
        quantity: int = 1,
        buy_trade_id: Optional[str] = None,
        phase: Optional[str] = None,
        mode: str = "MOCK",
        holding_period: Optional[str] = None,
        signal_source: Optional[str] = None,
        signal_confidence: Optional[str] = None,
        signal_trigger: Optional[str] = None,
    ) -> Optional[str]:
        """
        신규 포지션 오픈.
        holding_period가 지정되면 max_exit_date를 자동 계산해 저장한다.
        반환: position UUID 또는 None (중복/실패).
        """
        from datetime import datetime, timezone
        entry_dt   = datetime.now(timezone.utc)
        entry_time = entry_dt.isoformat()
        max_exit_date = None

        if holding_period:
            max_dt = self._horizon.calc_max_exit_date(holding_period, entry_dt)
            if max_dt:
                max_exit_date = max_dt.isoformat()

        position_id = save_position(
            code=code,
            name=name,
            quantity=quantity,
            avg_price=avg_price,
            buy_order_id=buy_order_id,
            buy_trade_id=buy_trade_id,
            phase=phase,
            mode=mode,
            holding_period=holding_period,
            entry_time=entry_time,
            max_exit_date=max_exit_date,
            signal_source=signal_source,
            signal_confidence=signal_confidence,
            signal_trigger=signal_trigger,
        )
        if position_id:
            period_str = f" [{holding_period}]" if holding_period else ""
            logger.info(
                f"[포지션] 오픈: {name}({code}) {quantity}주 avg_price={avg_price:.0f}"
                f"{period_str} max_exit={max_exit_date or '없음'}"
            )
        return position_id

    def close_position_by_id(
        self,
        position_id: str,
        close_reason: str,
        result_pct: float,
    ) -> bool:
        """포지션 종료 및 수익률 기록."""
        success = close_position(position_id, close_reason, result_pct)
        if success:
            logger.info(
                f"[포지션] 종료: {position_id} "
                f"reason={close_reason} pct={result_pct:+.2f}%"
            )
        return success

    def calculate_result_pct(self, avg_price: float, sell_price: float) -> float:
        """수익률 계산. avg_price가 0이면 0.0 반환."""
        if avg_price <= 0:
            return 0.0
        return round((sell_price - avg_price) / avg_price * 100, 4)

    def check_exit_condition(
        self,
        position: dict,
        current_price: float,
        current_phase: str = "",
        override_sl_price: float = None,
    ) -> Optional[str]:
        """
        HorizonManager에 위임하여 청산 조건 종합 판단.

        override_sl_price: exit_plan의 동적 SL 가격. 있으면 고정 SL 대신 사용.

        Returns
        -------
        청산 사유 문자열 또는 None
        """
        # exit_plan 동적 SL 우선 체크
        if override_sl_price and current_price <= override_sl_price:
            return "DYNAMIC_STOP_LOSS"

        if position.get("holding_period"):
            return self._horizon.check_exit(position, current_price, current_phase)

        # fallback: 구형 포지션
        avg_price = float(position.get("avg_price", 0))
        if avg_price <= 0:
            return None
        pnl_pct = (current_price - avg_price) / avg_price * 100
        if pnl_pct <= _STOP_LOSS_PCT:
            return "STOP_LOSS"
        if pnl_pct >= _TAKE_PROFIT_PCT:
            return "TAKE_PROFIT"
        return None

    def update_peak_price(self, position: dict, current_price: float) -> None:
        """
        트레일링 스탑을 위해 peak_price를 갱신한다.
        단기/중기/장기 포지션에 적용 (트레일링 활성화된 기간).
        """
        hp = position.get("holding_period", "")
        params = self._horizon.get_horizon_params(hp)
        if not params.get("trailing_stop", False):
            return
        new_peak = self._horizon.update_peak_price(position, current_price)
        old_peak  = float(position.get("peak_price") or 0)
        if new_peak > old_peak:
            pos_id = position.get("id", "")
            if pos_id:
                update_position_peak(pos_id, new_peak)
                position["peak_price"] = new_peak   # 메모리 갱신

    def get_sell_targets_from_positions(
        self,
        signal_buy_codes: set,
        current_phase: str,
    ) -> list:
        """
        현재 포지션에서 매도 대상 결정.

        매도 사유:
        - PHASE_CHANGE: 급락장/변동폭큰 국면 전환
        - SIGNAL_EXIT:  새 BUY 타겟에 없는 종목

        Returns
        -------
        list[dict]
            [{"code", "name", "position_id", "avg_price", "sell_reason"}, ...]
        """
        open_positions = get_open_positions(portfolio_type="short")
        sell_list: list = []

        for pos in open_positions:
            reason: Optional[str] = None
            hp = pos.get("holding_period", "단기")

            # 1. 국면 전환 청산: 방어 국면 진입 시 전략의 exit_on_phase_change 확인
            if current_phase in _DEFENSIVE_PHASES:
                exit_phases = self._horizon.get_horizon_params(hp).get("exit_on_phase_change", [])
                if current_phase in exit_phases or not exit_phases:
                    reason = "PHASE_CHANGE"

            # 2. 시그널 청산: 초단기만 적용 (단기/중기/장기는 TP/SL로 관리)
            if reason is None and hp == "초단기":
                if pos["code"] not in signal_buy_codes:
                    reason = "SIGNAL_EXIT"

            if reason:
                sell_list.append({
                    "code":           pos["code"],
                    "name":           pos["name"],
                    "position_id":    pos["id"],
                    "avg_price":      float(pos.get("avg_price", 0)),
                    "quantity":       int(pos.get("quantity", 0)),
                    "sell_reason":    reason,
                    "holding_period": hp,
                })

        logger.info(
            f"[포지션] 매도 대상 {len(sell_list)}종목 "
            f"(보유 {len(open_positions)}종목 / 국면={current_phase})"
        )
        return sell_list

    def review_positions_for_horizon_change(
        self,
        current_phase: str,
        current_prices: dict = None,
    ) -> list:
        """
        모든 OPEN 포지션의 holding_period를 현재 국면에 맞게 재평가한다.
        조건 충족 시 DB를 업데이트하고 변경 내역 리스트를 반환한다.

        Parameters
        ----------
        current_phase  : 현재 시장 국면
        current_prices : {종목코드: 현재가} 딕셔너리 (없으면 avg_price 기준 0% 가정)

        Returns
        -------
        list[dict]  변경된 포지션 내역
          [{"code", "name", "old_horizon", "new_horizon", "pnl_pct", "reason"}, ...]
        """
        from datetime import datetime
        from database.db import update_position_horizon

        open_positions = get_open_positions()
        if not open_positions:
            return []

        current_prices = current_prices or {}
        changes = []

        for pos in open_positions:
            try:
                code      = pos.get("code", "")
                avg_price = float(pos.get("avg_price", 0))
                if avg_price <= 0:
                    continue

                # 현재가 조회: kr_market → pykrx(KRX) → yfinance (±20% 가드)
                cur_price = current_prices.get(code)
                if cur_price:
                    cur_price = float(cur_price)
                if not cur_price or cur_price <= 0:
                    cur_price = self._fetch_price_pykrx(code)
                if not cur_price or cur_price <= 0:
                    yf_price = self._fetch_price_yfinance(code)
                    if yf_price and yf_price > 0:
                        deviation = abs(yf_price - avg_price) / avg_price if avg_price > 0 else 0
                        if deviation > 0.20:
                            name = pos.get("name", code)
                            logger.warning(
                                f"[포지션] {name}({code}) yfinance 가격 불신: "
                                f"{yf_price:,.0f}원 vs 매입 {avg_price:,.0f}원 "
                                f"(차이 {deviation*100:.1f}%) → 이번 사이클 스킵")
                            continue
                        cur_price = yf_price
                    else:
                        cur_price = avg_price  # 전부 실패 시 fallback (0%로 표시)

                pnl_pct   = (cur_price - avg_price) / avg_price * 100

                # result_pct 실시간 갱신 (OPEN 포지션 대시보드 표시용)
                pos_id = pos.get("id", "")
                if pos_id and cur_price != avg_price:
                    update_position_result_pct(pos_id, pnl_pct)

                # peak_price 갱신
                self.update_peak_price(pos, cur_price)

                # 기간 변경 제안
                new_hp = self._horizon.suggest_horizon_change(pos, current_phase, pnl_pct)
                if new_hp is None:
                    continue

                old_hp = pos.get("holding_period", "단기")

                # 새 만기일 계산
                entry_str = pos.get("entry_time")
                try:
                    entry_dt = datetime.fromisoformat(entry_str) if entry_str else datetime.now()
                except ValueError:
                    entry_dt = datetime.now()
                new_max_dt = self._horizon.calc_max_exit_date(new_hp, entry_dt)
                new_max_str = new_max_dt.isoformat() if new_max_dt else None

                # DB 업데이트
                pos_id = pos.get("id", "")
                if pos_id and update_position_horizon(pos_id, new_hp, new_max_str):
                    direction = "↑" if self._HORIZON_ORDER.index(new_hp) > self._HORIZON_ORDER.index(old_hp) else "↓"
                    logger.info(
                        f"[포지션] 기간변경 {direction}: {pos['name']}({code}) "
                        f"{old_hp} → {new_hp} (pnl={pnl_pct:+.1f}%, 국면={current_phase})"
                    )
                    changes.append({
                        "code":        code,
                        "name":        pos.get("name", ""),
                        "old_horizon": old_hp,
                        "new_horizon": new_hp,
                        "pnl_pct":     round(pnl_pct, 2),
                        "reason":      f"국면={current_phase}",
                    })
            except Exception as exc:
                logger.warning(f"[포지션] 기간 재평가 실패 {pos.get('code', '')}: {exc}")

        return changes

    # holding_period 순서 (suggest_horizon_change에서 참조)
    _HORIZON_ORDER = ["초단기", "단기", "중기", "장기"]

    def get_horizon_suitable_stocks(self, target_horizon: str, all_stocks: dict) -> dict:
        """
        stock_classification.json의 horizon_suitability 기준으로
        target_horizon에 적합한 종목만 필터링한다.

        Parameters
        ----------
        target_horizon : "장기" | "중기" | "단기" | "초단기"
        all_stocks     : {섹터: [{"code": ..., "name": ...}]} 형태의 전체 종목 유니버스

        Returns
        -------
        같은 형태지만 target_horizon에 적합한 종목만 포함
        """
        from agents.classification_loader import ClassificationLoader
        import os
        _CLASSIFICATION_PATH = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "stock_classification.json",
        )
        loader = ClassificationLoader(_CLASSIFICATION_PATH)

        result = {}
        for sector, stocks in all_stocks.items():
            suitable = []
            for s in stocks:
                code = s.get("code", "")
                info = loader.get_stock_info(code)
                if info is None:
                    suitable.append(s)   # 정보 없으면 통과
                    continue
                suitability = info.get("horizon_suitability", [])
                if not suitability or target_horizon in suitability:
                    suitable.append(s)
            if suitable:
                result[sector] = suitable
        return result

    # ------------------------------------------------------------------
    # 비동기 메서드 (KIS API 호출)
    # ------------------------------------------------------------------

    # KIS 시세 조회 캐시: {code: (price, timestamp)}
    _price_cache: dict = {}
    _PRICE_CACHE_TTL = 10  # 10초 캐시 (API 부하 방지)

    async def fetch_current_price(
        self, token: str, code: str, avg_price: float = 0.0,
    ) -> Optional[float]:
        """
        현재가 조회. KIS 실시간 시세 API 우선, 실패 시 yfinance fallback.

        KIS 실전 서버(openapi.koreainvestment.com)는 모의투자 앱키로도
        시세 조회가 가능하다. TR ID: FHKST01010100 (주식현재가 시세)

        Parameters
        ----------
        avg_price : 매입 평균가 (선택). 제공 시 yfinance 가격이 매입가 대비
                    ±20% 이상 벗어나면 신뢰할 수 없으므로 None 반환.
        """
        # 캐시 확인
        cached = self._price_cache.get(code)
        if cached:
            price, ts = cached
            if time.time() - ts < self._PRICE_CACHE_TTL:
                return price

        # 1순위: KIS 실시간 시세
        kis_price = await self._fetch_price_kis(token, code)
        if kis_price and kis_price > 0:
            self._price_cache[code] = (kis_price, time.time())
            return kis_price

        # 2순위: pykrx (KRX 공식 데이터) — KIS보다 느리지만 정확
        krx_price = self._fetch_price_pykrx(code)
        if krx_price and krx_price > 0:
            logger.info(f"[시세] {code} KIS 실패 → pykrx(KRX) fallback: {krx_price:,.0f}원")
            self._price_cache[code] = (krx_price, time.time())
            return krx_price

        # 3순위: yfinance (최후 fallback, 부정확할 수 있음)
        yf_price = self._fetch_price_yfinance(code)
        if yf_price and yf_price > 0:
            # 매입가 대비 ±20% 이상 차이나면 yfinance 가격이 부정확한 것으로 판단
            if avg_price > 0:
                deviation = abs(yf_price - avg_price) / avg_price
                if deviation > 0.20:
                    logger.warning(
                        f"[시세] {code} yfinance 가격 불신: "
                        f"{yf_price:,.0f}원 vs 매입 {avg_price:,.0f}원 "
                        f"(차이 {deviation*100:.1f}%) → 사용 안 함")
                    return None
            logger.info(f"[시세] {code} KIS+pykrx 실패 → yfinance fallback: {yf_price:,.0f}원")
            self._price_cache[code] = (yf_price, time.time())
            return yf_price

        return None

    async def _fetch_price_kis(self, token: str, code: str) -> Optional[float]:
        """
        KIS 실전 서버 주식현재가 시세 API (FHKST01010100).
        모의투자 앱키로도 시세 조회 가능.
        """
        if not all([self._app_key, self._app_secret, token]):
            return None

        url = f"{_KIS_REAL_URL}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = {
            "authorization": f"Bearer {token}",
            "appkey":        self._app_key,
            "appsecret":     self._app_secret,
            "tr_id":         "FHKST01010100",
            "custtype":      "P",
        }
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",  # 주식
            "FID_INPUT_ISCD":         code,
        }

        loop = asyncio.get_event_loop()

        def _request() -> requests.Response:
            return requests.get(url, headers=headers, params=params, timeout=5)

        try:
            resp = await loop.run_in_executor(None, _request)
            data = resp.json()
            if data.get("rt_cd") != "0":
                return None
            output = data.get("output", {})
            price = int(output.get("stck_prpr", 0) or 0)
            return float(price) if price > 0 else None
        except Exception as exc:
            logger.debug(f"[시세] KIS 시세 조회 실패 {code}: {exc}")
            return None

    def _fetch_price_pykrx(self, code: str) -> Optional[float]:
        """pykrx(KRX 공식 데이터)로 한국 주식 현재가 조회. KIS 다음 2순위 fallback."""
        try:
            from pykrx import stock
            from datetime import datetime, timedelta
            today = datetime.now().strftime("%Y%m%d")
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
            df = stock.get_market_ohlcv(yesterday, today, code)
            if not df.empty:
                price = int(df.iloc[-1].iloc[3])  # 종가
                if price > 0:
                    return float(price)
        except Exception as exc:
            logger.debug(f"[시세] pykrx 시세 조회 실패 {code}: {exc}")
        return None

    def _fetch_price_yfinance(self, code: str) -> Optional[float]:
        """yfinance로 한국 주식 현재가 조회 (최후 fallback). KRX 종목은 code.KS 접미사 사용."""
        try:
            import yfinance as yf
            ticker = yf.Ticker(f"{code}.KS")
            price = ticker.fast_info.last_price
            if price and float(price) > 0:
                return float(price)
        except Exception:
            pass
        return None

    async def sync_with_kis_balance(self, token: str) -> dict:
        """
        KIS 잔고와 DB 포지션 비교 및 불일치 보고.
        불일치 발견 시 로그만 기록, 자동 수정 없음 (안전 우선).

        Returns
        -------
        dict
            {
              "kis_holdings":  list,  # KIS 보유 목록
              "db_positions":  list,  # DB OPEN 포지션
              "in_db_not_kis": list,  # DB에는 있으나 KIS에 없음
              "in_kis_not_db": list,  # KIS에는 있으나 DB에 없음
            }
        실패 시 빈 dict 반환.
        """
        if not all([self._app_key, self._app_secret, self._cano]):
            return {}

        url = f"{_KIS_BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance"
        headers = {
            "authorization": f"Bearer {token}",
            "appkey":        self._app_key,
            "appsecret":     self._app_secret,
            "tr_id":         "VTTC8434R",
            "custtype":      "P",
        }
        params = {
            "CANO":                  self._cano,
            "ACNT_PRDT_CD":          self._acnt_prdt_cd,
            "AFHR_FLPR_YN":          "N",
            "OFL_YN":                "",
            "INQR_DVSN":             "02",
            "UNPR_DVSN":             "01",
            "FUND_STTL_ICLD_YN":     "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN":             "00",
            "CTX_AREA_FK100":        "",
            "CTX_AREA_NK100":        "",
        }

        loop = asyncio.get_event_loop()

        def _request() -> requests.Response:
            return requests.get(url, headers=headers, params=params, timeout=10)

        try:
            resp = await loop.run_in_executor(None, _request)
            data = resp.json()

            kis_output = data.get("output1", [])
            kis_holdings = [
                {
                    "code":      item.get("pdno", ""),
                    "name":      item.get("prdt_name", ""),
                    "quantity":  int(item.get("hldg_qty", 0)),
                    "avg_price": float(item.get("pchs_avg_pric", 0)),
                }
                for item in kis_output
                if int(item.get("hldg_qty", 0)) > 0
            ]

            db_positions = get_open_positions()
            kis_codes = {h["code"] for h in kis_holdings}
            db_codes  = {p["code"] for p in db_positions}

            in_db_not_kis = [p for p in db_positions if p["code"] not in kis_codes]
            in_kis_not_db = [h for h in kis_holdings if h["code"] not in db_codes]

            if in_db_not_kis:
                logger.warning(
                    f"[포지션] DB에 있으나 KIS에 없음: "
                    f"{[p['code'] for p in in_db_not_kis]}"
                )
            if in_kis_not_db:
                logger.warning(
                    f"[포지션] KIS에 있으나 DB에 없음: "
                    f"{[h['code'] for h in in_kis_not_db]}"
                )

            return {
                "kis_holdings":  kis_holdings,
                "db_positions":  db_positions,
                "in_db_not_kis": in_db_not_kis,
                "in_kis_not_db": in_kis_not_db,
            }

        except Exception as exc:
            logger.warning(f"[포지션] KIS 잔고 동기화 실패: {exc}")
            return {}
