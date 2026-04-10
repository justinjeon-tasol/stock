"""
실행 에이전트 모듈.
WeightAdjuster의 SIGNAL 메시지를 받아 KIS API로 모의투자 주문을 실행하고
결과를 ORDER 메시지로 오케스트레이터에 전달한다.
텔레그램으로 주문 결과 알림을 전송한다.
"""

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

from agents.base_agent import BaseAgent
from agents.horizon_manager import HorizonManager
from agents.position_manager import PositionManager
from agents.risk_manager import RiskManager
from database.db import save_trade, save_pending_dca, get_pending_dca_list, update_pending_dca_status, lock_pending_dca
from protocol.protocol import StandardMessage, dataclass_to_dict

# 모의투자 KIS API 베이스 URL
_KIS_BASE_URL = "https://openapivts.koreainvestment.com:29443"

# 주문 TR ID
_TR_BUY  = "VTTC0802U"
_TR_SELL = "VTTC0801U"

# 텔레그램 API 베이스 URL
_TELEGRAM_BASE_URL = "https://api.telegram.org"


class Executor(BaseAgent):
    """
    KIS 모의투자 API를 통해 주문을 실행하는 에이전트.
    SIGNAL → ORDER
    """

    def __init__(self) -> None:
        super().__init__("EX", "실행", timeout=30, max_retries=3)

        # KIS API 설정
        self._app_key: Optional[str] = None
        self._app_secret: Optional[str] = None
        self._account_no: Optional[str] = None
        self._is_mock: bool = True

        # 텔레그램 설정
        self._telegram_token: Optional[str] = None
        self._telegram_chat_id: Optional[str] = None

        # 토큰 캐시 (인메모리 + 파일)
        self._token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        self._token_cache_path = Path(__file__).parent.parent / "logs" / ".kis_token_cache.json"

        self._position_manager = PositionManager()
        self._horizon          = HorizonManager()
        self._risk_manager     = RiskManager()
        self._max_stock_weight_pct: float = 0.15  # 단일 종목 최대 비중 (기본 15%)
        self._load_kis_config()
        self._dca_enabled = False
        self._dca_split_ratio = [0.6, 0.4]
        self._dca_pullback_pct = -1.0
        self._dca_max_wait_hours = 4
        self._load_dca_config()
        self._partial_tp_enabled = False
        self._partial_tp_levels: list = []
        self._kalman_signals: dict = {}  # 칼만 MA 신호 (파이프라인에서 갱신)
        self._load_partial_tp_config()

    # ------------------------------------------------------------------
    # 설정 로드
    # ------------------------------------------------------------------

    def _load_kis_config(self) -> None:
        """
        .env 파일에서 KIS API 및 텔레그램 설정을 로드한다.
        값이 없으면 None으로 설정하고 예외는 발생시키지 않는다.
        """
        load_dotenv()

        self._app_key      = os.getenv("KIS_APP_KEY")
        self._app_secret   = os.getenv("KIS_APP_SECRET")
        self._account_no   = os.getenv("KIS_ACCOUNT_NO")
        is_mock_str        = os.getenv("KIS_IS_MOCK", "true")
        self._is_mock      = is_mock_str.lower() not in ("false", "0", "no")

        self._telegram_token   = os.getenv("TELEGRAM_BOT_TOKEN")
        self._telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

        # 리스크 관리 설정 (strategy_config.json)
        try:
            _cfg_path = Path(__file__).parent.parent / "config" / "strategy_config.json"
            _cfg = json.loads(_cfg_path.read_text(encoding="utf-8"))
            self._max_stock_weight_pct = float(
                _cfg.get("risk_management", {}).get("max_stock_weight_pct", 0.15)
            )
        except Exception:
            self._max_stock_weight_pct = 0.15

        # 설정 상태 로깅
        kis_ready = all([self._app_key, self._app_secret, self._account_no])
        tg_ready  = all([self._telegram_token, self._telegram_chat_id])
        self.log(
            "info",
            f"설정 로드 완료 — KIS {'준비됨' if kis_ready else '미설정'}, "
            f"텔레그램 {'준비됨' if tg_ready else '미설정'}, "
            f"모드={'MOCK' if self._is_mock else 'REAL'}",
        )

    def _load_dca_config(self) -> None:
        """risk_config.json에서 DCA 설정을 로드한다."""
        try:
            cfg_path = Path(__file__).parent.parent / "config" / "risk_config.json"
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            dca = cfg.get("dca_config", {})
            self._dca_enabled = bool(dca.get("enabled", False))
            self._dca_split_ratio = dca.get("split_ratio", [0.6, 0.4])
            cond = dca.get("second_entry_condition", {})
            self._dca_pullback_pct = float(cond.get("pullback_pct", -1.0))
            self._dca_max_wait_hours = int(cond.get("max_wait_hours", 4))
            self.log("info", f"DCA 설정: enabled={self._dca_enabled}, ratio={self._dca_split_ratio}, pullback={self._dca_pullback_pct}%")
        except Exception as exc:
            self.log("warning", f"DCA 설정 로드 실패, 비활성 유지: {exc}")

    def _load_partial_tp_config(self) -> None:
        """risk_config.json에서 분할 매도(Partial Take Profit) 설정을 로드한다."""
        try:
            cfg_path = Path(__file__).parent.parent / "config" / "risk_config.json"
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            ptp = cfg.get("partial_take_profit", {})
            self._partial_tp_enabled = bool(ptp.get("enabled", False))
            self._partial_tp_levels = ptp.get("levels", [])
            self.log("info", f"분할매도 설정: enabled={self._partial_tp_enabled}, levels={len(self._partial_tp_levels)}")
        except Exception as exc:
            self.log("warning", f"분할매도 설정 로드 실패: {exc}")

    # ------------------------------------------------------------------
    # KIS 토큰 발급
    # ------------------------------------------------------------------

    async def _get_token(self) -> str:
        """
        유효한 KIS 접근 토큰을 반환한다.
        캐시된 토큰이 유효하면 재사용하고, 만료됐거나 없으면 새로 발급한다.

        Returns:
            access_token 문자열

        Raises:
            RuntimeError: API 키 미설정 또는 토큰 발급 실패 시
        """
        # 인메모리 캐시 확인
        if (
            self._token
            and self._token_expires_at
            and datetime.now(timezone.utc) < self._token_expires_at
        ):
            self.log("debug", "캐시된 토큰 재사용 (메모리)")
            return self._token

        # 파일 캐시 확인
        if self._token_cache_path.exists():
            try:
                cached = json.loads(self._token_cache_path.read_text(encoding="utf-8"))
                expires_at = datetime.fromisoformat(cached["expires_at"])
                if datetime.now(timezone.utc) < expires_at:
                    self._token = cached["access_token"]
                    self._token_expires_at = expires_at
                    self.log("info", "캐시된 토큰 재사용 (파일)")
                    return self._token
            except Exception:
                pass  # 파일 손상 시 무시하고 새로 발급

        if not all([self._app_key, self._app_secret]):
            raise RuntimeError("KIS_APP_KEY 또는 KIS_APP_SECRET이 설정되지 않았습니다.")

        self.log("info", "KIS 토큰 발급 요청")

        url = f"{_KIS_BASE_URL}/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey":     self._app_key,
            "appsecret":  self._app_secret,
        }

        loop = asyncio.get_event_loop()

        def _request() -> requests.Response:
            return requests.post(url, json=body, timeout=10)

        try:
            resp = await loop.run_in_executor(None, _request)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(f"토큰 발급 HTTP 오류: {exc}") from exc

        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"토큰 발급 응답에 access_token 없음: {data}")

        expires_in = int(data.get("expires_in", 86400))
        self._token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)
        self._token = token

        # 파일에 캐시 저장
        try:
            self._token_cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._token_cache_path.write_text(
                json.dumps({"access_token": token, "expires_at": self._token_expires_at.isoformat()}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            self.log("warning", f"토큰 파일 캐시 저장 실패: {e}")

        self.log("info", f"토큰 발급 완료 (유효 {expires_in}초)")
        return self._token

    # ------------------------------------------------------------------
    # KIS 주문 실행
    # ------------------------------------------------------------------

    async def _place_order(
        self,
        token: str,
        code: str,
        name: str,
        action: str,
        quantity: int = 1,
    ) -> dict:
        """
        KIS 모의투자 API를 통해 시장가 주문을 실행한다.

        Args:
            token:    KIS 접근 토큰
            code:     종목코드 (예: "000660")
            name:     종목명 (예: "SK하이닉스")  — 로깅용
            action:   "BUY" | "SELL"
            quantity: 주문 수량 (기본 1주)

        Returns:
            {"status": "OK|ERROR", "order_no": str, "message": str}
        """
        if not self._account_no:
            return {"status": "ERROR", "order_no": "", "message": "KIS_ACCOUNT_NO 미설정"}

        qty = max(1, int(quantity))
        tr_id = _TR_BUY if action == "BUY" else _TR_SELL

        # 계좌번호 분리: 앞 8자리 / 뒤 2자리
        cano           = self._account_no[:8]
        acnt_prdt_cd   = self._account_no[8:]

        url = f"{_KIS_BASE_URL}/uapi/domestic-stock/v1/trading/order-cash"
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey":        self._app_key,
            "appsecret":     self._app_secret,
            "tr_id":         tr_id,
            "custtype":      "P",
        }
        body = {
            "CANO":         cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "PDNO":         code,
            "ORD_DVSN":     "01",   # 시장가
            "ORD_QTY":      str(qty),
            "ORD_UNPR":     "0",    # 시장가 시 0
        }

        self.log("info", f"{action} 주문 요청: {name}({code}) 시장가 {qty}주")

        loop = asyncio.get_event_loop()

        def _request() -> requests.Response:
            return requests.post(url, json=body, headers=headers, timeout=10)

        try:
            resp = await loop.run_in_executor(None, _request)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            msg = f"HTTP 요청 실패: {exc}"
            self.log("error", f"{name}({code}) {action} 주문 실패: {msg}")
            return {"status": "ERROR", "order_no": "", "message": msg}

        rt_cd = data.get("rt_cd", "")
        if rt_cd == "0":
            order_no = data.get("output", {}).get("ODNO", "")
            self.log("info", f"{name}({code}) {action} 주문 접수 — 주문번호: {order_no}")

            # 체결 확인 (시장가 주문은 대부분 즉시 체결)
            confirmed = await self._confirm_execution(token, order_no, code, name, qty)
            if confirmed:
                filled_qty = confirmed.get("filled_qty", qty)
                filled_price = confirmed.get("filled_price", 0)
                self.log("info",
                    f"{name}({code}) {action} 체결 확인: {filled_qty}주 @ {filled_price:,.0f}원")
                return {
                    "status": "OK", "order_no": order_no,
                    "message": "체결 완료",
                    "filled_qty": filled_qty,
                    "filled_price": filled_price,
                }
            else:
                # 체결 확인 API 실패해도 시장가 주문은 대부분 체결됨 → OK로 처리
                # 현재가를 체결가로 사용 (동기화에서 보정)
                self.log("warning",
                    f"{name}({code}) {action} 체결 확인 실패 → 주문접수 기준 OK 처리 (주문번호: {order_no})")
                return {
                    "status": "OK", "order_no": order_no,
                    "message": "주문 접수 (체결 확인 실패, 동기화에서 보정)",
                    "filled_qty": qty,
                    "filled_price": 0,  # 호출부에서 current_price로 폴백
                }
        else:
            msg = data.get("msg1", "알 수 없는 오류")
            self.log("error", f"{name}({code}) {action} 주문 실패: {msg}")
            return {"status": "ERROR", "order_no": "", "message": msg}

    async def _confirm_execution(
        self,
        token: str,
        order_no: str,
        code: str,
        name: str,
        expected_qty: int,
        max_retries: int = 5,
        interval_sec: float = 1.0,
    ) -> Optional[dict]:
        """
        KIS 체결 조회 API로 주문 체결 여부를 확인한다.
        최대 max_retries회 폴링하여 체결을 확인한다.

        Returns:
            {"filled_qty": int, "filled_price": float} | None (미체결)
        """
        if not self._account_no or not order_no:
            return None

        cano = self._account_no[:8]
        acnt_prdt_cd = self._account_no[8:]
        tr_id = "VTTC8001R" if self._is_mock else "TTTC8001R"

        from datetime import date as _date
        today_str = _date.today().strftime("%Y%m%d")

        url = f"{_KIS_BASE_URL}/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey":        self._app_key,
            "appsecret":     self._app_secret,
            "tr_id":         tr_id,
            "custtype":      "P",
        }
        params = {
            "CANO":            cano,
            "ACNT_PRDT_CD":    acnt_prdt_cd,
            "INQR_STRT_DT":   today_str,
            "INQR_END_DT":    today_str,
            "SLL_BUY_DVSN_CD": "00",
            "INQR_DVSN":      "00",
            "PDNO":            "",       # 전체 종목 조회 (종목 필터링은 코드에서)
            "CCLD_DVSN":       "00",     # 전체 (모의투자 호환)
            "ORD_GNO_BRNO":    "",
            "ODNO":            "",       # 빈 값 (모의투자에서 ODNO 필터 미지원)
            "INQR_DVSN_3":    "00",
            "INQR_DVSN_1":    "",
            "CTX_AREA_FK100":  "",
            "CTX_AREA_NK100":  "",
        }

        loop = asyncio.get_event_loop()

        for attempt in range(max_retries):
            if attempt > 0:
                await asyncio.sleep(interval_sec)

            try:
                def _req() -> requests.Response:
                    return requests.get(url, headers=headers, params=params, timeout=10)

                resp = await loop.run_in_executor(None, _req)
                data = resp.json()

                if data.get("rt_cd") != "0":
                    continue

                for item in (data.get("output1") or []):
                    odno = item.get("odno", "")
                    pdno = item.get("pdno", "")
                    # 주문번호 매칭 우선, 없으면 종목코드 매칭
                    if odno != order_no and pdno != code:
                        continue
                    if odno != order_no:
                        # 종목코드만 일치 — 최신 체결이 맞는지 확인
                        continue
                    filled_qty = int(item.get("tot_ccld_qty", "0") or "0")
                    filled_price = float(item.get("avg_prvs", "0") or "0")
                    if filled_qty > 0:
                        return {"filled_qty": filled_qty, "filled_price": filled_price}
            except Exception as exc:
                self.log("debug", f"[체결확인] {name}({code}) 조회 실패 (재시도 {attempt+1}): {exc}")

        return None

    # ------------------------------------------------------------------
    # 텔레그램 알림
    # ------------------------------------------------------------------

    async def _send_telegram(self, message: str) -> bool:
        """
        텔레그램 봇을 통해 메시지를 전송한다.
        설정이 없거나 전송 실패해도 예외를 전파하지 않는다.

        Args:
            message: 전송할 텍스트

        Returns:
            True (성공) | False (설정 없음 또는 전송 실패)
        """
        if not self._telegram_token or not self._telegram_chat_id:
            self.log("debug", "텔레그램 설정 없음 — 알림 건너뜀")
            return False

        url = f"{_TELEGRAM_BASE_URL}/bot{self._telegram_token}/sendMessage"
        body = {
            "chat_id": self._telegram_chat_id,
            "text":    message,
        }

        loop = asyncio.get_event_loop()

        def _request() -> requests.Response:
            return requests.post(url, json=body, timeout=10)

        try:
            resp = await loop.run_in_executor(None, _request)
            resp.raise_for_status()
            self.log("info", "텔레그램 알림 전송 완료")
            return True
        except Exception as exc:
            self.log("warning", f"텔레그램 알림 전송 실패: {exc}")
            return False

    # ------------------------------------------------------------------
    # 텔레그램 메시지 생성
    # ------------------------------------------------------------------

    def _build_telegram_message(
        self,
        results: list,
        phase: str,
        confidence: float,
        targets: list = None,
    ) -> str:
        """
        주문 결과를 텔레그램 메시지 문자열로 변환한다.

        Args:
            results:    주문 결과 리스트
            phase:      시장 국면
            confidence: 신뢰도
            targets:    매수 대상 종목 리스트 (시그널 출처 표시용)

        Returns:
            텔레그램 전송용 텍스트
        """
        # targets를 code → target dict로 매핑
        target_map = {}
        if targets:
            for t in targets:
                target_map[t.get("code", "")] = t

        lines = ["[매수 주문]"]
        for r in results:
            status_label = "체결" if r["status"] == "OK" else f"실패({r['message']})"
            lines.append(f"- {r['name']}({r['code']}): 시장가 1주")
            # 시그널 출처 표시
            t = target_map.get(r.get("code", ""))
            if t and t.get("signal_source") == "backtest_signal":
                conf = t.get("signal_confidence", "")
                trigger = t.get("signal_trigger", "")
                lines.append(f"  시그널: {conf} 백테스팅 ({trigger})")
            lines.append(f"  상태: {status_label}")

        lines.append(f"- 국면: {phase} (신뢰도 {confidence * 100:.0f}%)")
        # 투자 기간 및 청산 기준 안내
        hp = getattr(self, "_last_holding_period", "단기")
        tp, sl = self._horizon.get_tp_sl(hp)
        lines.append(f"- 투자기간: {hp} | 익절:{tp:+.1f}% / 손절:{sl:+.1f}%")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 손절/익절 자동 체크
    # ------------------------------------------------------------------

    async def _check_stop_take(self, token: Optional[str] = None, current_phase: str = "") -> None:
        """
        보유 포지션 전체에 대해 청산 조건을 확인하고 실행한다.

        HorizonManager를 통해 각 포지션의 holding_period에 맞는 조건 확인:
          - 손절/익절 (모든 기간)
          - 트레일링 스탑 (중기/장기)
          - 시간 청산 (초단기: 15:20 이후)
          - 최대 보유일 초과
          - 국면 전환 청산
        """
        try:
            open_positions = self._position_manager.get_open_positions()
            if not open_positions:
                return

            closed_count = 0

            # 토큰이 없으면 직접 발급 (HOLD 국면에서도 청산 가능하도록)
            if token is None:
                try:
                    token = await self._get_token()
                except Exception as exc:
                    msg = (
                        f"🚨 [KIS 토큰 오류] 청산 체크 중단\n"
                        f"보유 포지션 {len(open_positions)}종목의 손절/익절 체크 불가!\n"
                        f"원인: {exc}\n"
                        f"조치: KIS 앱키 상태 확인 필요"
                    )
                    self.log("critical", f"[청산체크] 토큰 발급 실패 — 청산 체크 건너뜀: {exc}")
                    await self._send_telegram(msg)
                    return closed_count

            now = datetime.now()
            for pos in open_positions:
                code        = pos.get("code", "")
                name        = pos.get("name", "")
                position_id = pos.get("id", "")
                hp          = pos.get("holding_period", "단기")
                quantity    = int(pos.get("quantity", 0))

                current_price = await self._position_manager.fetch_current_price(token, code)
                if current_price is None:
                    continue

                # 트레일링 스탑용 peak_price 갱신
                self._position_manager.update_peak_price(pos, current_price)

                avg_price = float(pos.get("avg_price", 0))
                if avg_price <= 0:
                    continue
                pnl_pct = (current_price - avg_price) / avg_price * 100

                # ── 매수 후 보호 시간 체크 (2시간) ──
                # 보호 시간 내에는 exit_plan/분할매도 발동 차단 (손절만 허용)
                entry_str = pos.get("entry_time", "")
                buy_protected = False
                if entry_str:
                    try:
                        entry_dt = datetime.fromisoformat(entry_str.replace("Z", "+00:00"))
                        hours_held = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600
                        if hours_held < 2.0:
                            buy_protected = True
                    except Exception:
                        pass

                if buy_protected:
                    # 보호 시간 내: 큰 손실(-3% 이하)만 긴급 손절, 나머지는 스킵
                    if pnl_pct <= -3.0:
                        self.log("warning",
                            f"[보호시간] {name}({code}) 긴급손절 발동: {pnl_pct:+.1f}%")
                        try:
                            sell_order = await self._place_order(token, code, name, "SELL", quantity)
                            if sell_order.get("status") == "OK":
                                filled_price = sell_order.get("filled_price", current_price)
                                filled_qty = sell_order.get("filled_qty", quantity)
                                result_pct = self._position_manager.calculate_result_pct(avg_price, filled_price)
                                self._position_manager.close_position(
                                    position_id, filled_price, "EMERGENCY_STOP_LOSS"
                                )
                                save_trade(
                                    {"order_id": sell_order.get("order_no", ""), "action": "SELL",
                                     "results": [{
                                         "code": code, "name": name, "status": "OK",
                                         "order_no": sell_order.get("order_no", ""),
                                         "quantity": filled_qty, "price": int(filled_price),
                                         "strategy_id": pos.get("strategy_id"),
                                         "result_pct": result_pct,
                                     }],
                                     "mode": "MOCK" if self._is_mock else "REAL"},
                                    {"phase": current_phase, "strategy_id": pos.get("strategy_id"),
                                     "sell_reason": "EMERGENCY_STOP_LOSS"},
                                )
                                closed_count += 1
                            else:
                                self.log("warning", f"[보호시간] {name}({code}) 긴급손절 미체결: {sell_order.get('message')}")
                        except Exception as exc:
                            self.log("error", f"[보호시간] 긴급손절 주문 실패: {exc}")
                        continue
                    else:
                        continue

                # ── exit_plan 기반 매도 체크 (forecast 기반, 최우선) ──
                plan_result = await self._check_exit_plan(
                    token, pos, current_price, pnl_pct, current_phase
                )
                if plan_result:
                    closed_count += 1
                    continue

                # ── 분할 익절 체크 (exit_plan 없을 때 fallback) ──
                if self._partial_tp_enabled and quantity >= 2:
                    partial_stage = int(pos.get("partial_tp_stage", 0))
                    partial_sold = await self._try_partial_take_profit(
                        token, pos, current_price, pnl_pct, partial_stage
                    )
                    if partial_sold:
                        closed_count += 1
                        continue

                # ── 동적 SL 적용 (exit_plan이 있으면 override) ──
                override_sl = None
                try:
                    from database.db import get_exit_plan
                    ep = get_exit_plan(position_id)
                    if ep:
                        dsl = ep.get("dynamic_sl", {})
                        if dsl.get("current_sl_price"):
                            override_sl = float(dsl["current_sl_price"])
                except Exception:
                    pass

                # ── 칼만 MA 하향 이탈 → SL 강화 (초단기 제외) ──
                holding_period = pos.get("holding_period", "단기")
                if holding_period != "초단기" and self._kalman_signals:
                    k_sig = self._kalman_signals.get(code)
                    if k_sig:
                        k_trend = k_sig.get("trend", "FLAT")
                        k_above = k_sig.get("price_above_kalman", True)
                        k_cross = k_sig.get("crossover")
                        if k_cross == "DOWN" or (k_trend == "DOWN" and not k_above):
                            # 수익권이면 현재가 -0.3%로 SL 강화 (수익 보전)
                            # 손실권이면 현재가 -1.0%로 SL 강화 (추가 손실 방지)
                            margin = 0.003 if pnl_pct >= 0 else 0.01
                            kalman_sl = current_price * (1 - margin)
                            if override_sl is None or kalman_sl > override_sl:
                                override_sl = kalman_sl
                                self.log("info",
                                    f"[칼만] {name}({code}) 하향이탈 → SL 강화: "
                                    f"{kalman_sl:,.0f}원 (손익={pnl_pct:+.1f}%)")

                exit_reason = self._position_manager.check_exit_condition(
                    pos, current_price, current_phase, override_sl_price=override_sl
                )
                if exit_reason is None:
                    continue

                # 전량 청산 시 수량 명시
                self.log(
                    "info",
                    f"[청산] {name}({code}) [{hp}] → {exit_reason} "
                    f"(현재가={current_price:,.0f}, {quantity}주)",
                )
                try:
                    sell_order = await self._place_order(token, code, name, "SELL", quantity)
                except Exception as exc:
                    self.log("error", f"[청산] {name}({code}) 매도 실패: {exc}")
                    continue

                if sell_order.get("status") == "OK":
                    filled_price = sell_order.get("filled_price", current_price)
                    filled_qty = sell_order.get("filled_qty", quantity)
                    result_pct = self._position_manager.calculate_result_pct(avg_price, filled_price)
                    self._position_manager.close_position_by_id(position_id, exit_reason, result_pct)
                    # SELL trades 레코드 생성
                    save_trade(
                        {"order_id": sell_order.get("order_no", ""), "action": "SELL",
                         "results": [{
                             "code": code, "name": name, "status": "OK",
                             "order_no": sell_order.get("order_no", ""),
                             "quantity": filled_qty, "price": int(filled_price),
                             "strategy_id": pos.get("strategy_id"),
                             "result_pct": result_pct,
                         }],
                         "mode": "MOCK" if self._is_mock else "REAL"},
                        {"phase": current_phase, "strategy_id": pos.get("strategy_id"),
                         "sell_reason": exit_reason},
                    )
                    self.log("info", f"[청산] {name}({code}) 종료 완료: {result_pct:+.2f}%")
                    closed_count += 1
        except Exception as exc:
            self.log("warning", f"_check_stop_take 오류 (무시): {exc}")
        return closed_count

    async def _check_pending_dca(self, token: Optional[str] = None) -> int:
        """
        대기 중인 DCA 2차 매수 조건을 확인하고, 조건 충족 시 추가 매수를 실행한다.
        만료된 DCA는 EXPIRED 처리한다.

        중복 실행 방지:
        - DB lock_pending_dca()로 PENDING → EXECUTING 원자적 전환
        - 장 마감(15:20) 이후 DCA 실행 차단

        Returns:
            int: 실행된 DCA 매수 건수
        """
        if not self._dca_enabled:
            return 0

        pending_list = get_pending_dca_list()
        if not pending_list:
            return 0

        if token is None:
            try:
                token = await self._get_token()
            except Exception as exc:
                self.log("warning", f"[DCA] 토큰 발급 실패: {exc}")
                return 0

        executed = 0
        now = datetime.now(timezone.utc)
        now_local = datetime.now()

        # 장 마감(15:20) 이후 DCA 실행 차단
        market_close_hhmm = 1520
        current_hhmm = now_local.hour * 100 + now_local.minute
        if current_hhmm >= market_close_hhmm:
            # 미실행 DCA 전부 만료 처리
            for dca in pending_list:
                update_pending_dca_status(dca.get("id", ""), "EXPIRED")
            if pending_list:
                self.log("info", f"[DCA] 장 마감 후 → 대기 DCA {len(pending_list)}건 전부 EXPIRED")
            return 0

        for dca in pending_list:
            dca_id         = dca.get("id", "")
            code           = dca.get("code", "")
            name           = dca.get("name", "")
            target_price   = float(dca.get("target_price", 0))
            quantity       = int(dca.get("quantity", 0))
            position_id    = dca.get("position_id", "")
            expires_at_str = dca.get("expires_at", "")

            # 만료 체크
            try:
                expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                if now >= expires_at:
                    update_pending_dca_status(dca_id, "EXPIRED")
                    self.log("info", f"[DCA] {name}({code}) 2차 매수 만료 → EXPIRED")
                    continue
            except Exception:
                update_pending_dca_status(dca_id, "EXPIRED")
                continue

            # 현재가 조회
            current_price = await self._position_manager.fetch_current_price(token, code)
            if current_price is None or current_price <= 0:
                continue

            # 조건 충족: 현재가 ≤ 목표가 (pullback 도달)
            if current_price <= target_price:
                # ── 중복 실행 방지: 원자적 잠금 ──
                if not lock_pending_dca(dca_id):
                    self.log("info", f"[DCA] {name}({code}) 이미 처리 중 → SKIP")
                    continue

                self.log(
                    "info",
                    f"[DCA] {name}({code}) 2차 매수 조건 충족: "
                    f"현재가={current_price:,.0f} ≤ 목표가={target_price:,.0f}",
                )
                try:
                    order_result = await self._place_order(token, code, name, "BUY", quantity)
                except Exception as exc:
                    self.log("error", f"[DCA] {name}({code}) 2차 매수 주문 실패: {exc}")
                    # 실패 시 다시 PENDING으로 복구 (다음 사이클에서 재시도)
                    update_pending_dca_status(dca_id, "PENDING")
                    continue

                if order_result.get("status") == "OK":
                    update_pending_dca_status(dca_id, "EXECUTED")
                    filled_price = order_result.get("filled_price", current_price)
                    filled_qty = order_result.get("filled_qty", quantity)
                    # 포지션 수량/평균가 업데이트 (체결가 기준)
                    self._update_position_after_dca(position_id, filled_qty, filled_price)
                    self.log(
                        "info",
                        f"[DCA] {name}({code}) 2차 매수 체결: {filled_qty}주 @ {filled_price:,.0f}원",
                    )
                    # 텔레그램 알림
                    await self._send_telegram(
                        f"[DCA 2차 매수]\n{name}({code})\n"
                        f"{quantity}주 @ {current_price:,.0f}원\n"
                        f"조건: 1차 매수가 대비 {self._dca_pullback_pct}% 하락"
                    )
                    executed += 1
                else:
                    # 주문 실패 시 PENDING 복구
                    update_pending_dca_status(dca_id, "PENDING")
                    self.log(
                        "warning",
                        f"[DCA] {name}({code}) 2차 매수 주문 실패: {order_result.get('message', '')}",
                    )

        return executed

    def _update_position_after_dca(
        self, position_id: str, add_qty: int, add_price: float
    ) -> None:
        """DCA 2차 매수 후 포지션 수량과 평균가를 업데이트한다."""
        from database.db import _get_client
        client = _get_client()
        if client is None or not position_id:
            return
        try:
            resp = client.table("positions").select("quantity, avg_price").eq("id", position_id).execute()
            if not resp.data:
                return
            old_qty   = int(resp.data[0].get("quantity", 0))
            old_price = float(resp.data[0].get("avg_price", 0))
            new_qty   = old_qty + add_qty
            new_avg   = ((old_price * old_qty) + (add_price * add_qty)) / new_qty if new_qty > 0 else old_price
            client.table("positions").update({
                "quantity":  new_qty,
                "avg_price": round(new_avg, 2),
            }).eq("id", position_id).execute()
            self.log("info", f"[DCA] 포지션 업데이트: {old_qty}→{new_qty}주, 평균가 {old_price:,.0f}→{new_avg:,.0f}원")
        except Exception as exc:
            self.log("warning", f"[DCA] 포지션 업데이트 실패: {exc}")

    async def _try_partial_take_profit(
        self,
        token: str,
        position: dict,
        current_price: float,
        pnl_pct: float,
        current_stage: int,
    ) -> bool:
        """
        분할 익절 조건을 확인하고, 조건 충족 시 부분 매도를 실행한다.

        partial_tp_levels = [
          {"pnl_pct": 1.5, "sell_ratio": 0.3},  # stage 1
          {"pnl_pct": 3.0, "sell_ratio": 0.3},  # stage 2
        ]

        Returns:
            True if partial sell was executed, False otherwise
        """
        if current_stage >= len(self._partial_tp_levels):
            return False

        level = self._partial_tp_levels[current_stage]
        threshold = float(level.get("pnl_pct", 0))
        sell_ratio = float(level.get("sell_ratio", 0.3))

        if pnl_pct < threshold:
            return False

        code        = position.get("code", "")
        name        = position.get("name", "")
        position_id = position.get("id", "")
        quantity    = int(position.get("quantity", 0))
        avg_price   = float(position.get("avg_price", 0))

        sell_qty = max(1, int(quantity * sell_ratio))
        # 최소 매도 수량: 보유량의 30% 이상
        min_sell = max(1, int(quantity * 0.3))
        sell_qty = max(sell_qty, min_sell)
        remaining = quantity - sell_qty

        if remaining < 1:
            # 1주밖에 안 남으면 분할 매도 의미 없음 → 전량 청산으로 넘김
            return False

        self.log(
            "info",
            f"[분할익절] {name}({code}) stage {current_stage + 1}: "
            f"수익률 {pnl_pct:+.2f}% ≥ {threshold}% → {sell_qty}주 매도 (잔여 {remaining}주)",
        )

        try:
            sell_order = await self._place_order(token, code, name, "SELL", sell_qty)
        except Exception as exc:
            self.log("error", f"[분할익절] {name}({code}) 매도 실패: {exc}")
            return False

        if sell_order.get("status") != "OK":
            self.log("warning", f"[분할익절] {name}({code}) 매도 미체결: {sell_order.get('message', '')}")
            return False

        # 체결가 기준으로 DB 업데이트
        filled_price = sell_order.get("filled_price", current_price)
        filled_qty = sell_order.get("filled_qty", sell_qty)
        actual_remaining = quantity - filled_qty

        new_stage = current_stage + 1
        if actual_remaining > 0:
            self._update_position_partial_sell(position_id, actual_remaining, new_stage)
        else:
            self._position_manager.close_position_by_id(
                position_id, f"PARTIAL_TP_STAGE_{new_stage}",
                self._position_manager.calculate_result_pct(avg_price, filled_price)
            )

        # trade 저장
        result_pct = self._position_manager.calculate_result_pct(avg_price, filled_price)
        r = {
            "code": code, "name": name, "status": "OK",
            "order_no": sell_order.get("order_no", ""),
            "quantity": filled_qty, "price": int(filled_price),
            "strategy_id": position.get("strategy_id"),
            "result_pct": result_pct,
        }
        save_trade(
            {"order_id": sell_order.get("order_no", ""), "action": "SELL",
             "results": [r], "mode": "MOCK" if self._is_mock else "REAL"},
            {"phase": "", "strategy_id": position.get("strategy_id"),
             "sell_reason": f"PARTIAL_TP_STAGE_{new_stage}"},
        )

        # 텔레그램 알림
        await self._send_telegram(
            f"[분할 익절 {new_stage}차]\n"
            f"{name}({code})\n"
            f"{filled_qty}주 매도 @ {filled_price:,.0f}원\n"
            f"수익률: {result_pct:+.2f}%\n"
            f"잔여: {remaining}주"
        )

        self.log("info", f"[분할익절] {name}({code}) stage {new_stage} 완료")
        return True

    def _update_position_partial_sell(
        self, position_id: str, new_quantity: int, new_stage: int
    ) -> None:
        """분할 매도 후 포지션 수량과 partial_tp_stage를 업데이트한다."""
        from database.db import _get_client
        client = _get_client()
        if client is None or not position_id:
            return
        try:
            client.table("positions").update({
                "quantity": new_quantity,
                "partial_tp_stage": new_stage,
            }).eq("id", position_id).execute()
            self.log("info", f"[분할익절] 포지션 업데이트: {new_quantity}주, stage={new_stage}")
        except Exception as exc:
            self.log("warning", f"[분할익절] 포지션 업데이트 실패: {exc}")

    # ------------------------------------------------------------------
    # exit_plan 기반 매도 (forecast 기반 지능형 매도)
    # ------------------------------------------------------------------

    async def _check_exit_plan(
        self, token: str, pos: dict, current_price: float,
        pnl_pct: float, current_phase: str
    ) -> bool:
        """
        exit_plan의 분할 매도 단계를 체크하고 조건 충족 시 매도.
        Returns: True if a sell was executed.
        """
        from database.db import get_exit_plan, update_exit_plan_stage
        position_id = pos.get("id", "")
        plan = get_exit_plan(position_id)
        if not plan:
            return False

        stages = plan.get("exit_stages", [])
        if not stages or not isinstance(stages, list):
            return False

        code = pos.get("code", "")
        name = pos.get("name", "")
        quantity = int(pos.get("quantity", 0))
        version = plan.get("plan_version", 1)

        for i, stage in enumerate(stages):
            if stage.get("status") != "PENDING":
                continue

            trigger_price = float(stage.get("trigger_price", 0))
            if trigger_price <= 0 or current_price < trigger_price:
                continue

            # 조건 충족 — 매도 실행
            sell_ratio = float(stage.get("sell_ratio", 0.3))
            if stage.get("type") == "FINAL_TP":
                sell_qty = quantity  # 잔량 전부
            else:
                sell_qty = max(1, int(quantity * sell_ratio))
                # 최소 매도 수량: 보유량의 30% 이상
                min_sell = max(1, int(quantity * 0.3))
                sell_qty = max(sell_qty, min_sell)
                if sell_qty >= quantity:
                    sell_qty = max(1, quantity - 1)  # 최소 1주 남김

            remaining = quantity - sell_qty

            self.log(
                "info",
                f"[EXIT_PLAN] {name}({code}) stage {i+1} 발동: "
                f"현재가 {current_price:,.0f} ≥ 목표가 {trigger_price:,.0f} → {sell_qty}주 매도",
            )

            try:
                sell_order = await self._place_order(token, code, name, "SELL", sell_qty)
            except Exception as exc:
                self.log("error", f"[EXIT_PLAN] 매도 실패: {exc}")
                return False

            if sell_order.get("status") != "OK":
                self.log("warning", f"[EXIT_PLAN] {name}({code}) 미체결: {sell_order.get('message', '')}")
                return False

            filled_price = sell_order.get("filled_price", current_price)
            filled_qty = sell_order.get("filled_qty", sell_qty)
            actual_remaining = quantity - filled_qty

            # 단계 상태 업데이트
            stages[i]["status"] = "EXECUTED"
            stages[i]["executed_price"] = filled_price
            update_exit_plan_stage(position_id, stages, version + 1)

            # 포지션 업데이트
            avg_price_val = float(pos.get("avg_price", 0))
            result_pct = self._position_manager.calculate_result_pct(avg_price_val, filled_price)
            if actual_remaining <= 0:
                # 전량 매도 → 포지션 종료
                self._position_manager.close_position_by_id(
                    position_id, f"EXIT_PLAN_STAGE_{i+1}", result_pct
                )
                # exit_plan 삭제
                from database.db import delete_exit_plan
                delete_exit_plan(position_id)
            else:
                self._update_position_partial_sell(position_id, actual_remaining, 0)

            # trade 저장
            save_trade(
                {"order_id": sell_order.get("order_no", ""), "action": "SELL",
                 "results": [{
                     "code": code, "name": name, "status": "OK",
                     "order_no": sell_order.get("order_no", ""),
                     "quantity": filled_qty, "price": int(filled_price),
                     "strategy_id": pos.get("strategy_id"),
                     "result_pct": result_pct,
                 }],
                 "mode": "MOCK" if self._is_mock else "REAL"},
                {"phase": current_phase, "strategy_id": pos.get("strategy_id"),
                 "sell_reason": f"EXIT_PLAN_STAGE_{i+1}"},
            )

            await self._send_telegram(
                f"[EXIT_PLAN 매도]\n{name}({code})\n"
                f"stage {i+1}: {filled_qty}주 @ {filled_price:,.0f}원\n"
                f"수익률: {result_pct:+.2f}%\n"
                f"잔여: {remaining}주"
            )
            return True

        # 시간 기반 타이트닝: 보유 5일 이상 횡보 시 SL 축소
        try:
            entry_str = pos.get("entry_time", "")
            if entry_str:
                entry_dt = datetime.fromisoformat(entry_str.replace("Z", "+00:00"))
                days_held = (datetime.now(timezone.utc) - entry_dt).days
                time_adj = plan.get("time_adjustments", {})
                threshold = time_adj.get("no_move_days_threshold", 5)
                if days_held >= threshold and abs(pnl_pct) < 1.0:
                    dsl = plan.get("dynamic_sl", {})
                    tighten_pct = time_adj.get("tighten_sl_to_pct", -1.0)
                    new_sl = float(pos.get("avg_price", 0)) * (1 + tighten_pct / 100)
                    if new_sl > float(dsl.get("current_sl_price", 0)):
                        dsl["current_sl_price"] = new_sl
                        from database.db import save_exit_plan
                        plan["dynamic_sl"] = dsl
                        save_exit_plan(plan)
                        self.log("info", f"[EXIT_PLAN] {name} SL 타이트닝: {days_held}일 횡보 → SL={new_sl:,.0f}")
        except Exception:
            pass

        return False

    @staticmethod
    def build_exit_plan(
        position_id: str, code: str, name: str,
        avg_price: float, quantity: int, holding_period: str,
        forecast: dict, current_phase: str,
    ) -> dict:
        """
        forecast 기반 exit_plan 생성.

        핵심 원칙:
        - 매입가 대비 수익/손실 상태를 먼저 판단
        - 예측이 매입가 이하면 추세를 DOWN으로 강제 (손실 최소화)
        - 수익 구간: 예측 목표가 기반 분할 익절
        - 손실 구간: 매입가 복귀 시 탈출 or 반등 매도
        """
        target_1w = forecast.get("target_1w", avg_price)
        target_1m = forecast.get("target_1m", avg_price)
        raw_trend = forecast.get("trend", "SIDEWAYS")
        confidence = forecast.get("confidence", 0.5)
        current_price = forecast.get("current_price", avg_price)

        # ── 핵심: 매입가 대비 상태 판단 ──
        pnl_pct = (current_price / avg_price - 1) * 100  # 현재 손익률
        forecast_vs_avg_1w = (target_1w / avg_price - 1) * 100  # 1주 예측 vs 매입가
        forecast_vs_avg_1m = (target_1m / avg_price - 1) * 100

        # 추세 재판정: 예측이 매입가 이하면 DOWN으로 강제
        if pnl_pct >= 0 and forecast_vs_avg_1w > pnl_pct:
            trend = "PROFIT_UP"  # 수익 중 + 추가 상승 예측
        elif pnl_pct >= 0 and forecast_vs_avg_1w > 0:
            trend = "PROFIT_FLAT"  # 수익 중 + 하락 예측 (but 매입가 이상 유지)
        elif pnl_pct >= 0:
            trend = "PROFIT_FLAT"  # 수익 중 + 매입가 이하로 하락 예측 → 빨리 확정
        elif forecast_vs_avg_1w < 0 and forecast_vs_avg_1m < 0:
            trend = "LOSS_ZONE"  # 손실 중 + 예측도 매입가 회복 불가
        elif pnl_pct < 0 and forecast_vs_avg_1w > 0:
            trend = "RECOVERING"  # 손실 중 + 매입가 회복 가능
        else:
            trend = "RECOVERING"  # 기타 손실 상태

        # ── 상태별 분할 매도 단계 생성 ──
        # 과거 유사 RSI 기반 상승여력 (forecast에 포함)
        upside_p75 = forecast.get("upside_p75", 4.0)  # 10일 상위 25%ile 기대 수익
        upside_p90 = forecast.get("upside_p90", 8.0)  # 10일 상위 10%ile 최대 기대

        if trend == "PROFIT_UP":
            # 수익 구간 + 상승 예측 → 과거 실제 상승폭 기반 3단계 분할
            s1 = max(avg_price * 1.02, current_price * (1 + upside_p75 * 0.3 / 100))  # 상승여력 30% 지점
            s2 = max(avg_price * 1.04, current_price * (1 + upside_p75 * 0.7 / 100))  # 상승여력 70% 지점
            s3 = max(avg_price * 1.06, current_price * (1 + upside_p90 * 0.8 / 100))  # 최대 기대의 80%
            stages = [
                {"stage": 1, "type": "PARTIAL_TP", "trigger_price": round(s1),
                 "sell_ratio": 0.30, "sell_qty": max(1, int(quantity * 0.3)),
                 "status": "PENDING", "rationale": f"수익 확보 1차 (매입+{(s1/avg_price-1)*100:.1f}%)"},
                {"stage": 2, "type": "PARTIAL_TP", "trigger_price": round(s2),
                 "sell_ratio": 0.30, "sell_qty": max(1, int(quantity * 0.3)),
                 "status": "PENDING", "rationale": f"수익 확대 2차 (매입+{(s2/avg_price-1)*100:.1f}%)"},
                {"stage": 3, "type": "FINAL_TP", "trigger_price": round(s3),
                 "sell_ratio": 1.0, "sell_qty": max(1, quantity - max(1, int(quantity * 0.3)) * 2),
                 "status": "PENDING", "rationale": f"잔량 청산 (매입+{(s3/avg_price-1)*100:.1f}%)"},
            ]

        elif trend == "PROFIT_FLAT":
            # 수익 중 + 횡보/하락 예측 → 빠르게 수익 확정
            s1 = max(avg_price * 1.005, current_price * 0.995)
            s2 = avg_price * 1.04
            stages = [
                {"stage": 1, "type": "PARTIAL_TP", "trigger_price": round(s1),
                 "sell_ratio": 0.50, "sell_qty": max(1, int(quantity * 0.5)),
                 "status": "PENDING", "rationale": f"수익 확정 ({(s1/avg_price-1)*100:.1f}%)"},
                {"stage": 2, "type": "FINAL_TP", "trigger_price": round(s2),
                 "sell_ratio": 1.0, "sell_qty": max(1, quantity - max(1, int(quantity * 0.5))),
                 "status": "PENDING", "rationale": f"잔량 확정 ({(s2/avg_price-1)*100:.1f}%)"},
            ]

        elif trend == "RECOVERING":
            # 손실 중 + 회복 가능성 → 매입가 +1% 이상에서 분할 매도
            s1 = avg_price * 1.01   # 매입가 +1% (수익 확인 후 매도)
            s2 = avg_price * 1.03   # 매입가 +3%
            stages = [
                {"stage": 1, "type": "PARTIAL_TP", "trigger_price": round(s1),
                 "sell_ratio": 0.50, "sell_qty": max(1, int(quantity * 0.5)),
                 "status": "PENDING", "rationale": f"수익 전환 후 탈출 ({(s1/avg_price-1)*100:.1f}%)"},
                {"stage": 2, "type": "FINAL_TP", "trigger_price": round(s2),
                 "sell_ratio": 1.0, "sell_qty": max(1, quantity - max(1, int(quantity * 0.5))),
                 "status": "PENDING", "rationale": f"추가 수익 후 전량 ({(s2/avg_price-1)*100:.1f}%)"},
            ]

        else:  # LOSS_ZONE - 예측상 매입가 회복 불가
            # 반등 시 손실 최소화 매도 — 최소 매입가 -1% 이상에서
            s1 = max(current_price * 1.02, avg_price * 0.99)
            stages = [
                {"stage": 1, "type": "FINAL_TP", "trigger_price": round(s1),
                 "sell_ratio": 1.0, "sell_qty": quantity,
                 "status": "PENDING",
                 "rationale": f"손실 최소화 탈출 (매입 대비 {(s1/avg_price-1)*100:+.1f}%)"},
            ]

        # ── 동적 손절 (상태별 차등) ──
        from agents.horizon_manager import HorizonManager
        hm = HorizonManager()
        _, base_sl = hm.get_tp_sl(holding_period)

        if trend == "LOSS_ZONE":
            sl_pct = base_sl * 0.6   # 매우 타이트
        elif trend == "RECOVERING":
            sl_pct = base_sl * 0.8
        elif trend == "PROFIT_FLAT":
            sl_pct = base_sl * 0.9
        elif confidence > 0.7:
            sl_pct = base_sl * 1.2   # 고신뢰 상승 → 여유
        else:
            sl_pct = base_sl

        sl_price = avg_price * (1 + sl_pct / 100)

        return {
            "position_id": position_id,
            "code": code,
            "name": name,
            "forecast_target_1w": target_1w,
            "forecast_target_1m": target_1m,
            "forecast_confidence": confidence,
            "forecast_trend": trend,
            "forecast_components": forecast.get("components", {}),
            "exit_stages": stages,
            "dynamic_sl": {
                "initial_sl_pct": round(sl_pct, 2),
                "current_sl_price": round(sl_price),
            },
            "time_adjustments": {
                "no_move_days_threshold": 5,
                "tighten_sl_to_pct": -1.0,
            },
            "plan_version": 1,
            "last_phase": current_phase,
            "current_price": current_price,
            "avg_price": avg_price,
            "quantity": quantity,
            "holding_period": holding_period,
        }

    # ------------------------------------------------------------------
    # 공개 인터페이스
    # ------------------------------------------------------------------

    async def execute(self, input_data: StandardMessage) -> StandardMessage:
        """
        SIGNAL 메시지를 받아 KIS API로 주문을 실행하고 ORDER 메시지를 반환한다.

        처리 흐름:
          1. SIGNAL 페이로드 파싱
          2. direction == "HOLD" | "SELL" → 모든 targets를 SKIP 처리
          3. direction == "BUY" → 토큰 발급 후 각 target에 대해 주문 실행
          4. 텔레그램 알림 전송
          5. ORDER 메시지 생성 및 반환

        주문 실패해도 ORDER 메시지는 반드시 반환하며, 예외를 전파하지 않는다.
        """
        self.log("info", "실행 에이전트 시작")

        payload         = input_data.body.get("payload", {})
        signal_id       = payload.get("signal_id",       "")
        direction       = payload.get("direction",       "HOLD")
        confidence      = float(payload.get("confidence", 0.0))
        phase           = payload.get("phase",           "알 수 없음")
        targets         = payload.get("targets",         [])
        sell_targets    = payload.get("sell_targets",    [])
        reason          = payload.get("reason",          "")
        strategy_id     = payload.get("strategy_id",     None)
        # 칼만 MA 신호 갱신 (청산 루프에서 사용)
        self._kalman_signals = payload.get("kalman_signals", {})

        # 투자 기간: SIGNAL에 포함되거나 국면 기본값으로 결정
        holding_period  = payload.get(
            "holding_period",
            self._horizon.default_horizon_for_phase(phase)
        )

        self.log(
            "info",
            f"SIGNAL 수신: {signal_id} / direction={direction} / "
            f"phase={phase} / targets={len(targets)}종목 / sell={len(sell_targets)}종목",
        )

        # ORDER 결과를 담을 리스트
        results: list = []

        # ── 토큰 (SELL 또는 BUY가 있을 때 발급) ──────────────────────────
        token: Optional[str] = None
        if sell_targets or direction == "BUY":
            try:
                token = await self._get_token()
            except Exception as exc:
                self.log("error", f"토큰 발급 실패: {exc}")

        # ── SELL 처리 (direction 무관, sell_targets가 있으면 실행) ────────
        sell_results: list = []
        if sell_targets:
            self.log("info", f"SELL 처리: {len(sell_targets)}종목")
            for st in sell_targets:
                code        = st.get("code", "")
                name        = st.get("name", "")
                position_id = st.get("position_id", "")
                avg_price   = float(st.get("avg_price", 0))
                sell_reason = st.get("sell_reason", "SIGNAL_EXIT")

                if token is None:
                    sell_results.append({
                        "code": code, "name": name,
                        "status": "ERROR", "order_no": "",
                        "message": "토큰 발급 실패로 매도 불가",
                        "result_pct": 0.0,
                    })
                    continue

                # 보유 수량 전량 매도
                sell_qty = int(st.get("quantity", 0))
                if sell_qty <= 0:
                    # quantity 누락 시 DB에서 조회
                    pos_record = self._position_manager.get_position_by_code(code)
                    sell_qty = int(pos_record.get("quantity", 1)) if pos_record else 1

                # 현재가 조회 (손절/익절 계산용)
                current_price = await self._position_manager.fetch_current_price(token, code)

                try:
                    sell_order = await self._place_order(token, code, name, "SELL", sell_qty)
                except Exception as exc:
                    sell_order = {"status": "ERROR", "order_no": "", "message": str(exc)}

                result_pct = 0.0
                if sell_order.get("status") == "OK":
                    filled_price = sell_order.get("filled_price", current_price or avg_price)
                    filled_qty = sell_order.get("filled_qty", sell_qty)
                    result_pct = self._position_manager.calculate_result_pct(avg_price, filled_price)
                    if position_id:
                        if sell_reason == "REDUCE_POSITION":
                            # 분할 축소: 포지션 OPEN 유지, 수량만 감소
                            pos_record = self._position_manager.get_position_by_code(code)
                            if pos_record:
                                total_qty = int(pos_record.get("quantity", 0))
                                remaining = total_qty - filled_qty
                                if remaining > 0:
                                    self._update_position_partial_sell(position_id, remaining, 0)
                                else:
                                    self._position_manager.close_position_by_id(
                                        position_id, sell_reason, result_pct
                                    )
                            else:
                                self._position_manager.close_position_by_id(
                                    position_id, sell_reason, result_pct
                                )
                        else:
                            self._position_manager.close_position_by_id(
                                position_id, sell_reason, result_pct
                            )
                    self.log(
                        "info",
                        f"SELL 체결: {name}({code}) {filled_qty}주 @ {filled_price:,.0f}원 {result_pct:+.2f}% [{sell_reason}]",
                    )
                    sell_r = {
                        "code":       code,
                        "name":       name,
                        "status":     "OK",
                        "order_no":   sell_order.get("order_no", ""),
                        "message":    "",
                        "quantity":   filled_qty,
                        "price":      int(filled_price),
                        "strategy_id": strategy_id,
                        "result_pct": result_pct,
                    }
                    save_trade(
                        {"order_id": sell_order.get("order_no", ""), "action": "SELL",
                         "results": [sell_r], "mode": "MOCK" if self._is_mock else "REAL"},
                        {"phase": phase, "strategy_id": strategy_id,
                         "sell_reason": sell_reason},
                    )

                sell_results.append({
                    "code":       code,
                    "name":       name,
                    "status":     sell_order.get("status", "ERROR"),
                    "order_no":   sell_order.get("order_no", ""),
                    "message":    sell_order.get("message", ""),
                    "result_pct": result_pct,
                    "sell_reason": sell_reason,
                })

        # 이번 사이클에서 매도한 종목은 재매수 방지
        sold_codes = {r["code"] for r in sell_results if r.get("status") == "OK"}

        # ── BUY / HOLD 처리 ───────────────────────────────────────────────
        if direction in ("HOLD", "SELL"):
            action = "SKIP"
            self.log("info", f"direction={direction} → BUY 주문 SKIP")

        else:
            # direction == "BUY"
            # 장 시간대 체크: 장 시작 변동성 구간이면 진입 보류
            entry_allowed, block_reason = self._risk_manager.is_entry_allowed_now()
            if not entry_allowed:
                action = "SKIP"
                self.log("warning", f"BUY 진입 보류: {block_reason}")
                targets = []  # 시간 보류 시 매수 대상도 비움
            else:
                action = "BUY"

            if not targets:
                self.log("info", "BUY이나 targets가 비어 있음 → 주문 없음")
            else:
                # ── 예수금 기반 종목당 매수 예산 계산 ──────────────────────
                weight_config  = payload.get("weight_config", {})
                cash_pct       = float(weight_config.get("cash_pct", 0.4))
                account_info   = await self.fetch_account_summary()
                available_cash = float(account_info.get("cash_amt", 0)) if account_info else 0.0
                total_assets   = float(account_info.get("tot_evlu_amt", 0)) if account_info else available_cash
                investable      = available_cash * (1.0 - cash_pct)
                # 회복 모드: 축소 비중 적용
                recovery_ratio = float(payload.get("_recovery_size_ratio", 1.0))
                if recovery_ratio < 1.0:
                    investable = investable * recovery_ratio
                    self.log("info", f"[회복모드] 매수 예산 축소: ×{recovery_ratio:.0%}")
                n_new_targets   = sum(
                    1 for t in targets
                    if not self._position_manager.is_already_held(t.get("code", ""))
                )
                per_stock_budget_equal = (investable / n_new_targets) if n_new_targets > 0 else 0.0
                # 단일 종목 최대 비중 캡 (총자산 × max_stock_weight_pct)
                max_per_stock  = total_assets * self._max_stock_weight_pct
                per_stock_budget = min(per_stock_budget_equal, max_per_stock)
                self.log(
                    "info",
                    f"매수 예산: 균등={per_stock_budget_equal:,.0f}원 / "
                    f"종목상한({self._max_stock_weight_pct*100:.0f}%)={max_per_stock:,.0f}원 → "
                    f"적용={per_stock_budget:,.0f}원"
                )

                for t in targets:
                    code = t.get("code", "")
                    name = t.get("name", "")
                    sector = t.get("sector", "")

                    # 섹터 감쇠 적용
                    held_sectors = [p.get("sector", "") for p in self._position_manager.get_open_positions()]
                    dampen = self._risk_manager.get_sector_dampen_factor(sector, held_sectors)
                    adjusted_budget = per_stock_budget * dampen
                    if dampen < 1.0:
                        self.log("info", f"{name}({code}) 섹터 감쇠 적용: {dampen:.1f}x → 예산 {adjusted_budget:,.0f}원")

                    # 중복 보유 방지
                    if self._position_manager.is_already_held(code):
                        self.log("info", f"{name}({code}) 이미 보유 중 → SKIP")
                        results.append({
                            "code": code, "name": name,
                            "status": "SKIP", "order_no": "",
                            "message": "이미 보유 중",
                        })
                        continue

                    # 같은 사이클에서 매도한 종목 재매수 방지
                    if code in sold_codes:
                        self.log("info", f"{name}({code}) 이번 사이클 매도 종목 → 재매수 SKIP")
                        results.append({
                            "code": code, "name": name,
                            "status": "SKIP", "order_no": "",
                            "message": "매도 직후 재매수 방지",
                        })
                        continue

                    # 재매수 쿨다운 (1시간) + 추격매수 방지 (+2%)
                    try:
                        from database.db import _get_client
                        _cooldown_client = _get_client()
                        if _cooldown_client:
                            recent_sell = (
                                _cooldown_client.table("trades")
                                .select("price,created_at,result_pct")
                                .eq("code", code)
                                .eq("action", "SELL")
                                .order("created_at", desc=True)
                                .limit(1)
                                .execute()
                            )
                            if recent_sell.data:
                                last_sell = recent_sell.data[0]
                                sell_time = datetime.fromisoformat(
                                    last_sell["created_at"].replace("Z", "+00:00")
                                )
                                hours_since_sell = (
                                    datetime.now(timezone.utc) - sell_time
                                ).total_seconds() / 3600
                                last_result_pct = float(last_sell.get("result_pct", 0) or 0)
                                cooldown_hours = 4.0 if last_result_pct < 0 else 1.0
                                if hours_since_sell < cooldown_hours:
                                    self.log("info",
                                        f"{name}({code}) 매도 후 {hours_since_sell*60:.0f}분 → 쿨다운 {cooldown_hours}h SKIP")
                                    results.append({
                                        "code": code, "name": name,
                                        "status": "SKIP", "order_no": "",
                                        "message": f"재매수 쿨다운 {cooldown_hours}h ({hours_since_sell*60:.0f}분 경과)",
                                    })
                                    continue

                                # 추격매수 방지: 마지막 매도가 대비 +2% 이상이면 SKIP
                                last_sell_price = float(last_sell.get("price", 0))
                                if last_sell_price > 0:
                                    cur_px = await self._position_manager.fetch_current_price(
                                        token, code
                                    )
                                    if cur_px and cur_px > last_sell_price * 1.02:
                                        self.log("info",
                                            f"{name}({code}) 추격매수 방지: "
                                            f"현재가 {cur_px:,.0f} > 매도가 {last_sell_price:,.0f}×1.02")
                                        results.append({
                                            "code": code, "name": name,
                                            "status": "SKIP", "order_no": "",
                                            "message": "추격매수 방지 (+2% 초과)",
                                        })
                                        continue
                    except Exception:
                        pass  # 쿨다운 체크 실패 시 무시하고 진행

                    if token is None:
                        results.append({
                            "code": code, "name": name,
                            "status": "ERROR", "order_no": "",
                            "message": "토큰 발급 실패로 주문 불가",
                        })
                        continue

                    # ── 수량 계산 ──────────────────────────────────────────
                    current_price_for_qty = await self._position_manager.fetch_current_price(
                        token, code
                    )
                    if current_price_for_qty and current_price_for_qty > 0 and adjusted_budget > 0:
                        total_quantity = max(1, int(adjusted_budget / current_price_for_qty))
                    else:
                        total_quantity = 1
                        self.log("warning", f"{name}({code}) 현재가 조회 실패 → 1주 주문")

                    # DCA 분할 매수: 1차 매수 수량 결정
                    if self._dca_enabled and total_quantity >= 2:
                        first_ratio = self._dca_split_ratio[0] if self._dca_split_ratio else 0.6
                        buy_quantity = max(1, int(total_quantity * first_ratio))
                        dca_remaining_qty = total_quantity - buy_quantity
                    else:
                        buy_quantity = total_quantity
                        dca_remaining_qty = 0

                    try:
                        order_result = await self._place_order(token, code, name, "BUY", buy_quantity)
                    except Exception as exc:
                        self.log("error", f"{name}({code}) 주문 예외: {exc}")
                        order_result = {"status": "ERROR", "order_no": "", "message": str(exc)}

                    r = {
                        "code":     code,
                        "name":     name,
                        "status":   order_result.get("status", "ERROR"),
                        "order_no": order_result.get("order_no", ""),
                        "message":  order_result.get("message", ""),
                    }
                    results.append(r)

                    # BUY 체결 확인 후 포지션 오픈 (체결가 기준)
                    if r["status"] == "OK":
                        avg_price = order_result.get("filled_price", current_price_for_qty or 0.0)
                        filled_qty = order_result.get("filled_qty", buy_quantity)
                        # trades 저장 후 position 연결
                        r["quantity"]    = filled_qty
                        r["price"]       = int(avg_price)
                        r["strategy_id"] = strategy_id
                        trade_payload = {
                            "order_id": r["order_no"],
                            "action":   "BUY",
                            "results":  [r],
                            "mode":     "MOCK" if self._is_mock else "REAL",
                        }
                        signal_payload = {
                            "phase": phase,
                            "strategy_id": strategy_id,
                            "signal_source": t.get("signal_source"),
                            "signal_confidence": t.get("signal_confidence"),
                            "signal_trigger": t.get("signal_trigger"),
                            "backtest_win_rate": t.get("win_rate"),
                            "backtest_expected_return": t.get("expected_return"),
                        }
                        trade_id = save_trade(trade_payload, signal_payload)
                        self._position_manager.open_position(
                            code=code,
                            name=name,
                            quantity=filled_qty,
                            avg_price=avg_price,
                            buy_order_id=r["order_no"],
                            buy_trade_id=trade_id,
                            phase=phase,
                            mode="MOCK" if self._is_mock else "REAL",
                            holding_period=holding_period,
                            signal_source=t.get("signal_source"),
                            signal_confidence=t.get("signal_confidence"),
                            signal_trigger=t.get("signal_trigger"),
                        )

                        # DCA 2차 매수 대기 등록
                        dca_remaining_qty = total_quantity - filled_qty
                        if dca_remaining_qty > 0 and avg_price > 0:
                            target_price = avg_price * (1 + self._dca_pullback_pct / 100.0)
                            expires_dt = (
                                datetime.now(timezone.utc)
                                + timedelta(hours=self._dca_max_wait_hours)
                            )
                            # 장 마감(15:20 KST) 이전으로 만료 시간 제한
                            now_local = datetime.now()
                            market_close = now_local.replace(
                                hour=15, minute=20, second=0, microsecond=0
                            )
                            market_close_utc = market_close - timedelta(hours=9)  # KST → UTC
                            market_close_utc = market_close_utc.replace(tzinfo=timezone.utc)
                            if expires_dt > market_close_utc:
                                expires_dt = market_close_utc
                            # position_id 조회
                            pos_record = self._position_manager.get_position_by_code(code)
                            pid = pos_record.get("id", "") if pos_record else ""
                            dca_budget = target_price * dca_remaining_qty
                            save_pending_dca(
                                position_id=pid,
                                code=code,
                                name=name,
                                stage=2,
                                target_price=target_price,
                                budget=dca_budget,
                                quantity=dca_remaining_qty,
                                expires_at=expires_dt.isoformat(),
                            )
                            self.log(
                                "info",
                                f"[DCA] {name}({code}) 2차 매수 대기: "
                                f"{dca_remaining_qty}주 @ ≤{target_price:,.0f}원 "
                                f"(만료: {self._dca_max_wait_hours}시간 후)",
                            )

                # 텔레그램 알림 (BUY 주문이 하나라도 있으면 전송)
                buy_results = [r for r in results if r["status"] in ("OK", "ERROR")]
                if buy_results:
                    self._last_holding_period = holding_period
                    tg_msg = self._build_telegram_message(results, phase, confidence, targets)
                    await self._send_telegram(tg_msg)

        # 청산 조건 자동 체크 (HOLD 포함 매 사이클마다 실행, 토큰 없으면 내부에서 발급)
        await self._check_stop_take(token, current_phase=phase)

        # DCA 2차 매수 조건 체크
        await self._check_pending_dca(token)

        # ORDER 메시지 생성
        # msg_id가 order_id가 된다
        order_msg = self.create_message(
            to="OR",
            data_type="ORDER",
            payload={},             # 임시 빈 payload — msg_id 생성 후 교체
            msg_type="ORDER",
            priority="HIGH" if action == "BUY" else "NORMAL",
        )
        order_id = order_msg.header.msg_id

        order_payload = {
            "order_id":    order_id,
            "signal_id":   signal_id,
            "action":      action,
            "results":     results,
            "sell_results": sell_results,
            "mode":        "MOCK" if self._is_mock else "REAL",
            "reason":      reason,
        }
        order_msg.body["payload"] = order_payload

        ok_count   = sum(1 for r in results if r["status"] == "OK")
        err_count  = sum(1 for r in results if r["status"] == "ERROR")
        skip_count = sum(1 for r in results if r["status"] == "SKIP")
        sell_ok    = sum(1 for r in sell_results if r["status"] == "OK")
        self.log(
            "info",
            f"ORDER 생성 완료: {order_id} / action={action} / "
            f"매수성공={ok_count} 실패={err_count} 건너뜀={skip_count} / 매도성공={sell_ok}",
        )
        return order_msg

    # ------------------------------------------------------------------
    # 계좌 잔고 조회
    # ------------------------------------------------------------------

    async def fetch_account_summary(self) -> Optional[dict]:
        """
        KIS 잔고 조회 API로 계좌 요약 정보를 반환한다.

        Returns
        -------
        dict | None
            {
              "cash_amt":       int,   예수금
              "stock_evlu_amt": int,   주식 평가금액
              "tot_evlu_amt":   int,   총 평가금액
              "pchs_amt":       int,   매수원가 합계
              "evlu_pfls_amt":  int,   평가손익
              "erng_rt":        float, 수익률
              "mode":           str,   MOCK|REAL
            }
            실패 시 None.
        """
        try:
            token = await self._get_token()
        except Exception as exc:
            self.log("warning", f"계좌 잔고 조회 토큰 실패: {exc}")
            return None

        if not self._account_no:
            return None

        cano         = self._account_no[:8]
        acnt_prdt_cd = self._account_no[8:]

        url = f"{_KIS_BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance"
        headers = {
            "authorization": f"Bearer {token}",
            "appkey":        self._app_key,
            "appsecret":     self._app_secret,
            "tr_id":         "VTTC8434R",
            "custtype":      "P",
        }
        params = {
            "CANO":                  cano,
            "ACNT_PRDT_CD":          acnt_prdt_cd,
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
            o2   = data.get("output2", [{}])
            if not o2:
                return None
            d = o2[0]
            # 빈 dict 응답 검증: tot_evlu_amt가 없으면 비정상 응답
            if not d or not d.get("tot_evlu_amt"):
                self.log("warning", "[계좌] KIS output2가 비어있음 → 저장 스킵")
                return None
            # KIS tot_evlu_amt = 현금 + 주식평가금액 (가장 신뢰할 수 있는 전체 자산)
            kis_tot_evlu = int(d.get("tot_evlu_amt", 0) or 0)

            # KIS 모의투자는 자체 기준가를 사용해 P&L이 실시간과 다름.
            # positions DB + KIS 실시간 시세로 직접 계산한다.
            positions = self._position_manager.get_open_positions()
            pchs_amt       = 0
            stock_evlu_amt = 0
            for pos in positions:
                qty = int(pos.get("quantity", 0))
                avg = float(pos.get("avg_price", 0))
                if qty <= 0 or avg <= 0:
                    continue
                cur = await self._position_manager.fetch_current_price(token, pos.get("code", ""))
                if cur and float(cur) > 0:
                    pchs_amt       += avg * qty
                    stock_evlu_amt += float(cur) * qty

            if pchs_amt > 0:
                evlu_pfls_amt = stock_evlu_amt - pchs_amt
                erng_rt       = evlu_pfls_amt / pchs_amt
                # 예수금 = 원금(dnca_tot_amt) - 실제 매수원가
                # KIS tot_evlu_amt는 KIS 자체 기준가로 이미 손익이 반영된 값이라 사용 불가.
                # dnca_tot_amt는 모의투자에서 원금(5천만원)으로 고정되어 신뢰할 수 있음.
                initial_capital = int(d.get("dnca_tot_amt", 0) or 0)
                cash_amt     = max(0, initial_capital - int(pchs_amt))
                tot_evlu_amt = cash_amt + int(stock_evlu_amt)
            else:
                # 포지션 없거나 현재가 조회 실패 → KIS 값 그대로 사용
                pchs_amt       = int(d.get("pchs_amt_smtl_amt",  0) or 0)
                stock_evlu_amt = int(d.get("scts_evlu_amt",      0) or 0)
                evlu_pfls_amt  = int(d.get("evlu_pfls_smtl_amt", 0) or 0)
                erng_rt        = evlu_pfls_amt / pchs_amt if pchs_amt else 0.0
                cash_amt       = int(d.get("dnca_tot_amt", 0) or 0)
                tot_evlu_amt   = kis_tot_evlu

            return {
                "cash_amt":       cash_amt,
                "stock_evlu_amt": int(stock_evlu_amt),
                "tot_evlu_amt":   tot_evlu_amt,
                "pchs_amt":       int(pchs_amt),
                "evlu_pfls_amt":  int(evlu_pfls_amt),
                "erng_rt":        round(erng_rt, 6),
                "mode":           "MOCK" if self._is_mock else "REAL",
            }
        except Exception as exc:
            self.log("warning", f"계좌 잔고 조회 실패: {exc}")
            return None

    async def fetch_kis_holdings(self) -> list:
        """
        KIS API에서 실제 보유종목 리스트를 반환한다.

        Returns: [{"code": "005930", "name": "삼성전자", "quantity": 10, "avg_price": 78000}, ...]
        """
        try:
            token = await self._get_token()
        except Exception:
            return []

        if not self._account_no:
            return []

        cano = self._account_no[:8]
        acnt_prdt_cd = self._account_no[8:]

        url = f"{_KIS_BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance"
        headers = {
            "authorization": f"Bearer {token}",
            "appkey": self._app_key,
            "appsecret": self._app_secret,
            "tr_id": "VTTC8434R",
            "custtype": "P",
        }
        params = {
            "CANO": cano, "ACNT_PRDT_CD": acnt_prdt_cd,
            "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02",
            "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
        }

        loop = asyncio.get_event_loop()
        try:
            resp = await loop.run_in_executor(
                None, lambda: requests.get(url, headers=headers, params=params, timeout=10)
            )
            data = resp.json()
            output1 = data.get("output1", [])
            holdings = []
            for item in output1:
                qty = int(item.get("hldg_qty", 0) or 0)
                if qty <= 0:
                    continue
                holdings.append({
                    "code": item.get("pdno", ""),
                    "name": item.get("prdt_name", ""),
                    "quantity": qty,
                    "avg_price": float(item.get("pchs_avg_pric", 0) or 0),
                })
            return holdings
        except Exception as exc:
            self.log("warning", f"KIS 보유종목 조회 실패: {exc}")
            return []
