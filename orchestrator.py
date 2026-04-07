"""
오케스트레이터 모듈
전체 파이프라인을 제어한다:
DC(+PP) → MA(+IM) → WA → SR(+LA) → EX
"""

import asyncio
import logging
from datetime import datetime

from agents.data_collector import DataCollector
from agents.market_analyzer import MarketAnalyzer
from agents.weight_adjuster import WeightAdjuster
from agents.executor import Executor
from agents.debugger import Debugger
from agents.strategy_researcher import StrategyEngine
from agents.risk_manager import RiskManager
from database.db import save_trade, save_market_phase, save_agent_log, save_account_summary, save_market_snapshot, get_open_positions


class Orchestrator:
    """
    5단계 파이프라인을 순서대로 실행하는 오케스트레이터.
    DC(+PP) → MA(+IM) → WA → SR(+LA) → EX
    각 단계 실패 시에도 다음 단계를 최대한 진행한다 (graceful degradation).
    """

    def __init__(self):
        # 각 에이전트 인스턴스화
        self.data_collector  = DataCollector()
        self.market_analyzer = MarketAnalyzer()
        self.weight_adjuster = WeightAdjuster()
        self.executor        = Executor()
        self.debugger        = Debugger()
        self.strategy_engine  = StrategyEngine()
        self.risk_manager     = RiskManager()
        self._debug_task      = None   # 백그라운드 감시 태스크
        self._current_phase   = ""    # 청산루프와 공유하는 최신 국면 정보
        self._backtest_ran_today = False  # 일일 백테스팅 실행 여부

        # 오케스트레이터 전용 로거
        self._logger = logging.getLogger("orchestrator")

    # ------------------------------------------------------------------
    # 단일 실행
    # ------------------------------------------------------------------

    async def run_once(self) -> dict:
        """
        파이프라인을 1회 실행한다.

        반환:
        {
            "status":    "success" | "error",
            "phase":     str,   # 감지된 시장 국면
            "direction": str,   # BUY | HOLD
            "orders":    list,  # executor 결과 (targets별 주문 결과)
            "signal":    dict,  # WeightAdjuster가 만든 SIGNAL 페이로드
            "error":     str | None
        }
        각 단계 실패 시 이전 단계 결과로 최대한 진행 (graceful degradation).
        """
        result = {
            "status":    "success",
            "phase":     "",
            "direction": "",
            "orders":    [],
            "signal":    {},
            "error":     None,
        }

        # -----------------------------------------------------------------
        # Pre-check 0: KIS 토큰 상태 확인
        # -----------------------------------------------------------------
        try:
            await self.executor._get_token()
        except Exception as tok_exc:
            self._logger.critical("[Pre-check] KIS 토큰 발급 실패: %s", tok_exc)
            await self.executor._send_telegram(
                f"🚨 [KIS 토큰 오류] 파이프라인 실행 불가\n"
                f"원인: {tok_exc}\n"
                f"KIS 앱키/시크릿 유효성을 확인하세요.\n"
                f"(KIS 모의투자 토큰은 매일 재발급 필요)"
            )
            result["status"] = "error"
            result["error"] = f"KIS 토큰 발급 실패: {tok_exc}"
            return result

        # -----------------------------------------------------------------
        # Pre-check: Daily Stop Loss 확인
        # -----------------------------------------------------------------
        # 현재가 조회 (DSL mark-to-market용): OPEN 포지션 시세를 KIS로 조회
        current_prices = {}
        try:
            token = await self.executor._get_token()
            open_positions = self.executor._position_manager.get_open_positions()
            for pos in open_positions:
                code = pos.get("code", "")
                cur = await self.executor._position_manager.fetch_current_price(token, code)
                if cur and cur > 0:
                    current_prices[code] = cur
        except Exception:
            pass  # 시세 조회 실패해도 DSL 자체는 실현손익만으로 동작

        dsl_halted, today_pnl = self.risk_manager.check_daily_stop_loss(current_prices)
        # 주간 손절 한도도 체크
        wsl_halted, week_pnl = self.risk_manager.check_weekly_stop_loss()
        if dsl_halted or wsl_halted:
            reason = "DAILY" if dsl_halted else "WEEKLY"
            pnl_val = today_pnl if dsl_halted else week_pnl
            self._logger.critical(
                "[리스크] %s Stop Loss 발동 (손익: %+.2f%%) — 신규 매수 중단, 청산만 계속",
                reason, pnl_val,
            )
            result["status"] = "HALT"
            result["error"] = f"{reason}_STOP_LOSS: 손익 {pnl_val:+.2f}%"
            # 회복 모드 체크: 상승 국면이면 축소 매수 허용
            result["_recovery_mode"] = self.risk_manager.check_recovery_mode()
            if result["_recovery_mode"]:
                self._logger.info(
                    "[리스크] 회복 모드 활성화 — 축소 매수 허용 (비중 %.0f%%)",
                    self.risk_manager.get_recovery_size_ratio() * 100,
                )
            else:
                result["direction"] = "HOLD"

        # -----------------------------------------------------------------
        # Step 1: 데이터 수집
        # -----------------------------------------------------------------
        self._log_step("1/5", "데이터수집", "시작")
        step1_result = None
        try:
            step1_result = await self.data_collector.run()
            if step1_result.status.get("code") == "ERROR":
                self._logger.warning("[1/5] 데이터수집 에러 상태: %s", step1_result.status.get("message", ""))
            else:
                self._log_step("1/5", "데이터수집", "완료 ✓")
            # 수집 데이터 스냅샷 저장
            try:
                raw = step1_result.body.get("payload", {})
                save_market_snapshot(
                    us_market=raw.get("us_market", {}),
                    kr_market=raw.get("kr_market", {}),
                    commodities=raw.get("commodities", {}),
                )
            except Exception as snap_exc:
                self._logger.warning("시장 스냅샷 저장 실패 (무시): %s", snap_exc)
        except Exception as exc:
            self._logger.error("[1/5] 데이터수집 예외: %s", exc)
            result["status"] = "error"
            result["error"]  = f"Step1 DataCollector 실패: {exc}"
            return result

        # -----------------------------------------------------------------
        # Step 2: 시장분석 + 이슈감지 (MA가 내부에서 IM 호출)
        # -----------------------------------------------------------------
        self._log_step("2/5", "시장분석+이슈감지", "시작")
        step3_result = None
        try:
            step3_result = await self.market_analyzer.run(step1_result)
            if step3_result.status.get("code") == "ERROR":
                self._logger.warning("[2/5] 시장분석 에러 상태: %s", step3_result.status.get("message", ""))
            else:
                self._log_step("2/5", "시장분석+이슈감지", "완료 ✓")
        except Exception as exc:
            self._logger.error("[2/5] 시장분석+이슈감지 예외: %s", exc)
            result["status"] = "error"
            result["error"]  = f"Step2 MarketAnalyzer 실패: {exc}"
            return result

        # 칼만 신호를 market_snapshots에 추가 저장
        try:
            ma_payload_kalman = step3_result.body.get("payload", {})
            kalman_sigs = ma_payload_kalman.get("kalman_signals", {})
            if kalman_sigs:
                from database.db import _get_client
                client = _get_client()
                if client:
                    client.table("market_snapshots").update(
                        {"data": {"kalman_signals": kalman_sigs}}
                    ).order("created_at", desc=True).limit(1).execute()
        except Exception:
            pass  # 실패해도 무시

        # -----------------------------------------------------------------
        # Step 2-b: 포지션 기간 재평가 (holding_period 업그레이드/다운그레이드)
        # -----------------------------------------------------------------
        try:
            phase_for_review = step3_result.body.get("payload", {}).get(
                "market_phase", {}
            ).get("phase", "일반장")
            # 최신 종목 현재가 (kr_market.stocks 에서 추출)
            kr_stocks = step1_result.body.get("payload", {}).get(
                "kr_market", {}
            ).get("stocks", {})
            current_prices = {
                code: float(info.get("price", 0))
                for code, info in kr_stocks.items()
                if info.get("price", 0)
            }
            horizon_changes = self.weight_adjuster._position_manager.review_positions_for_horizon_change(
                phase_for_review, current_prices
            )
            if horizon_changes:
                self._logger.info(
                    "[3-b] 포지션 기간 변경: %d건 (%s)",
                    len(horizon_changes),
                    ", ".join(f"{c['name']} {c['old_horizon']}→{c['new_horizon']}" for c in horizon_changes),
                )
        except Exception as exc:
            self._logger.warning("[2-b] 포지션 기간 재평가 실패 (무시): %s", exc)

        # -----------------------------------------------------------------
        # Step 2-b2: 시그널 역전 체크 (보유 포지션의 매수 트리거 역전 감지)
        # -----------------------------------------------------------------
        try:
            ma_payload_2b2 = step3_result.body.get("payload", {})
            active_signals_2b2 = ma_payload_2b2.get("active_signals", [])
            if active_signals_2b2:
                from services.signal_service import SignalService
                open_positions_2b2 = get_open_positions()
                reversal_candidates = self._check_signal_reversals(
                    open_positions_2b2, active_signals_2b2
                )
                if reversal_candidates:
                    self._logger.warning(
                        "[2-b2] 시그널 역전 감지: %d건 (%s)",
                        len(reversal_candidates),
                        ", ".join(f"{c['name']}({c['reason']})" for c in reversal_candidates),
                    )
                    # sell_targets에 주입하기 위해 step3_result payload에 추가
                    existing_sell = ma_payload_2b2.get("signal_reversal_sells", [])
                    ma_payload_2b2["signal_reversal_sells"] = existing_sell + reversal_candidates
        except Exception as exc:
            self._logger.warning("[2-b2] 시그널 역전 체크 실패 (무시): %s", exc)

        # -----------------------------------------------------------------
        # Step 2-c: exit_plan 생성/갱신 (forecast 기반 매도 계획)
        # -----------------------------------------------------------------
        try:
            ma_payload = step3_result.body.get("payload", {})
            forecasts = ma_payload.get("price_forecasts", {})
            if forecasts:
                from database.db import get_open_positions, save_exit_plan
                from agents.executor import Executor
                open_positions = get_open_positions()
                phase_now = ma_payload.get("market_phase", {}).get("phase", "일반장")
                plan_count = 0
                for pos in open_positions:
                    code = pos.get("code", "")
                    fc = forecasts.get(code)
                    if not fc:
                        continue
                    plan = Executor.build_exit_plan(
                        position_id=pos["id"], code=code, name=pos.get("name", ""),
                        avg_price=float(pos.get("avg_price", 0)),
                        quantity=int(pos.get("quantity", 0)),
                        holding_period=pos.get("holding_period", "단기"),
                        forecast=fc, current_phase=phase_now,
                    )
                    save_exit_plan(plan)
                    plan_count += 1
                if plan_count:
                    self._logger.info("[2-c] exit_plan 갱신: %d종목 (forecast 기반)", plan_count)
        except Exception as exc:
            self._logger.warning("[2-c] exit_plan 갱신 실패 (무시): %s", exc)

        # -----------------------------------------------------------------
        # Step 3: 가중치조정 (시장분석 + 이슈 결과 전달)
        # -----------------------------------------------------------------
        self._log_step("3/5", "가중치조정", "시작")
        step4_result = None
        try:
            # WeightAdjuster는 MarketAnalyzer 결과를 받는다 (issue_analysis 포함)
            step4_result = await self.weight_adjuster.run(step3_result)
            if step4_result.status.get("code") == "ERROR":
                self._logger.warning("[3/5] 가중치조정 에러 상태: %s", step4_result.status.get("message", ""))
            else:
                self._log_step("3/5", "가중치조정", "완료 ✓")
        except Exception as exc:
            self._logger.error("[3/5] 가중치조정 예외: %s", exc)
            result["status"] = "error"
            result["error"]  = f"Step3 WeightAdjuster 실패: {exc}"
            return result

        # -----------------------------------------------------------------
        # Step 4: 전략적용 (전략 선택 + 진입 조건 정제)
        # -----------------------------------------------------------------
        self._log_step("4/5", "전략적용", "시작")
        step5_result = step4_result   # 실패 시 fallback
        try:
            step5_result = await self.strategy_engine.run(step4_result)
            if step5_result.status.get("code") == "ERROR":
                self._logger.warning("[4/5] 전략적용 에러 상태 (원본 SIGNAL 사용): %s",
                                     step5_result.status.get("message", ""))
                step5_result = step4_result   # 원본으로 복원
            else:
                la_payload = step5_result.body.get("payload", {})
                self._log_step(
                    "4/5", "전략적용",
                    f"완료 ✓ strategy={la_payload.get('strategy_id', '없음')}",
                )
        except Exception as exc:
            self._logger.warning("[4/5] 전략적용 예외 (원본 SIGNAL 사용): %s", exc)
            step5_result = step4_result   # 원본으로 복원

        # SIGNAL 페이로드 추출 (로직적용 결과 우선, 실패 시 WA 결과)
        signal_payload = step5_result.body.get("payload", {})
        result["signal"]    = signal_payload
        result["phase"]     = signal_payload.get("phase", "알 수 없음")
        if result.get("direction") != "HOLD":
            # Stop Loss에서 HOLD 강제 지정하지 않은 경우만 시그널 반영
            result["direction"] = signal_payload.get("direction", "HOLD")

        # 회복 모드: Stop Loss 발동이지만 상승 국면이면 축소 매수 허용
        if result.get("_recovery_mode") and result["direction"] == "HOLD":
            detected_phase = signal_payload.get("phase", "")
            recovery_cfg = self.risk_manager.get_recovery_config()
            if detected_phase in recovery_cfg.get("allowed_phases", []):
                result["direction"] = signal_payload.get("direction", "HOLD")
                # 축소 비중을 signal에 주입
                signal_payload["_recovery_size_ratio"] = recovery_cfg.get("position_size_ratio", 0.3)
                signal_payload["_recovery_max_positions"] = recovery_cfg.get("max_positions", 1)
                self._logger.info(
                    "[회복모드] 국면=%s → 축소 매수 허용 (비중 %.0f%%, 최대 %d종목)",
                    detected_phase,
                    signal_payload["_recovery_size_ratio"] * 100,
                    signal_payload["_recovery_max_positions"],
                )
            else:
                self._logger.info(
                    "[회복모드] 국면=%s → 허용 국면 아님, 매수 중단 유지", detected_phase
                )

        # -----------------------------------------------------------------
        # Step 5: 주문실행
        # -----------------------------------------------------------------
        self._log_step("5/5", "주문실행", "시작")
        try:
            step6_result = await self.executor.run(step5_result)
            if step5_result.status.get("code") == "ERROR":
                self._logger.warning("[5/5] 주문실행 에러 상태: %s", step5_result.status.get("message", ""))
            else:
                self._log_step("5/5", "주문실행", "완료 ✓")

            order_payload = step6_result.body.get("payload", {})
            result["orders"] = order_payload.get("results", [])

            # Supabase 저장 (save_trade는 Executor 내부에서 BUY 성공 시 처리)
            save_market_phase(signal_payload)
            save_agent_log("OR", "info", f"파이프라인 완료: {result['phase']} / {result['direction']}")

            # 신규 매수 종목 exit_plan 재생성 (체결가 기반)
            buy_orders = [
                o for o in result["orders"]
                if o.get("status") == "OK" and o.get("action") == "BUY"
            ]
            if buy_orders:
                try:
                    from database.db import get_open_positions, save_exit_plan
                    from agents.executor import Executor
                    open_positions = get_open_positions()
                    bought_codes = {o["code"] for o in buy_orders}
                    phase_now = signal_payload.get("phase", "일반장")
                    ma_payload_ep = step3_result.body.get("payload", {})
                    forecasts_ep = ma_payload_ep.get("price_forecasts", {})
                    ep_count = 0
                    for pos in open_positions:
                        code = pos.get("code", "")
                        if code not in bought_codes:
                            continue
                        avg_price = float(pos.get("avg_price", 0))
                        fc = forecasts_ep.get(code, {})
                        # 체결가 기반으로 forecast 보정: current_price를 avg_price로 설정
                        fc["current_price"] = avg_price
                        # target이 매입가 이하면 매입가 기준으로 재설정
                        for key in ("target_1w", "target_1m"):
                            if fc.get(key, 0) <= avg_price:
                                fc[key] = avg_price * 1.05  # 최소 +5% 목표
                        plan = Executor.build_exit_plan(
                            position_id=pos["id"], code=code,
                            name=pos.get("name", ""),
                            avg_price=avg_price,
                            quantity=int(pos.get("quantity", 0)),
                            holding_period=pos.get("holding_period", "단기"),
                            forecast=fc, current_phase=phase_now,
                        )
                        save_exit_plan(plan)
                        ep_count += 1
                    if ep_count:
                        self._logger.info(
                            "[5-b] 신규 매수 exit_plan 재생성: %d종목 (체결가 기반)", ep_count
                        )
                except Exception as exc:
                    self._logger.warning("[5-b] exit_plan 재생성 실패 (무시): %s", exc)

            # 계좌 잔고 스냅샷 저장
            try:
                acct = await self.executor.fetch_account_summary()
                if acct:
                    save_account_summary(**acct)
                    self._logger.info(
                        "계좌 스냅샷 저장: 현금=%s원 / 주식=%s원 / 손익=%+d원",
                        f"{acct['cash_amt']:,}",
                        f"{acct['stock_evlu_amt']:,}",
                        acct['evlu_pfls_amt'],
                    )
            except Exception as exc:
                self._logger.warning("계좌 스냅샷 저장 실패 (무시): %s", exc)

            # 주문 결과 콘솔 요약 출력
            print(f"\n[주문 결과] {result['phase']} / {result['direction']}")
            for order in result["orders"]:
                name     = order.get("name", "")
                code     = order.get("code", "")
                status   = order.get("status", "")
                order_no = order.get("order_no", "")
                print(f"  - {name}({code}): {status} (주문번호: {order_no})")

        except Exception as exc:
            self._logger.error("[5/5] 주문실행 예외: %s", exc)
            # 주문실행 실패는 전체 실패로 처리하지 않음 (degradation)
            result["error"] = f"Step5 Executor 실패: {exc}"

        return result

    # ------------------------------------------------------------------
    # 스케줄 반복 실행
    # ------------------------------------------------------------------

    async def _update_history_if_needed(self, last_update_date: str) -> str:
        """
        날짜가 바뀌었으면 history 데이터를 백그라운드로 최신화한다.
        반환: 오늘 날짜 문자열 (YYYY-MM-DD)
        """
        import subprocess, sys, os
        today = datetime.now().strftime("%Y-%m-%d")
        if today == last_update_date:
            return today

        self._logger.info("[히스토리] 날짜 변경 감지 (%s → %s) — 자동 업데이트 시작", last_update_date, today)
        script = os.path.join(os.path.dirname(__file__), "data", "history", "fetch_history.py")
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, script, "--update",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=120)
            self._logger.info("[히스토리] 자동 업데이트 완료")
        except asyncio.TimeoutError:
            self._logger.warning("[히스토리] 자동 업데이트 120초 초과 — 다음 주기에 재시도")
        except Exception as exc:
            self._logger.warning("[히스토리] 자동 업데이트 실패 (무시): %s", exc)
        return today

    # 변동성 높은 국면: 1분 체크
    _FAST_CHECK_PHASES = {"변동폭큰", "하락장", "대폭락장"}

    # ------------------------------------------------------------------
    # 시간대별 파이프라인 모드
    # ------------------------------------------------------------------

    @staticmethod
    def _get_session_mode() -> str:
        """
        현재 시각 기반 장 세션 모드 반환.

        시간대 구분:
          06:00~08:30  → PRE_ANALYSIS  (사전분석: 미국 마감 데이터 기반)
          08:30~09:05  → MARKET_OPEN_WAIT (동시호가/장 시작 대기, 분석만)
          09:05~09:30  → ENTRY_READY   (장 시작 후 안정화 확인)
          09:30~15:10  → NORMAL        (정상 매매)
          15:10~15:30  → CLOSING       (장 마감 정리, 초단기 청산)
          15:30~06:00  → AFTER_HOURS   (장외, 파이프라인 실행 불필요)
        """
        now = datetime.now()
        h, m = now.hour, now.minute
        t = h * 60 + m  # 분 단위 환산

        if 360 <= t < 510:     # 06:00~08:30
            return "PRE_ANALYSIS"
        if 510 <= t < 545:     # 08:30~09:05
            return "MARKET_OPEN_WAIT"
        if 545 <= t < 570:     # 09:05~09:30
            return "ENTRY_READY"
        if 570 <= t < 910:     # 09:30~15:10
            return "NORMAL"
        if 910 <= t < 930:     # 15:10~15:30
            return "CLOSING"
        return "AFTER_HOURS"   # 15:30~06:00

    async def _stop_take_loop(self) -> None:
        """
        파이프라인과 독립적으로 보유 포지션의 손절/익절/청산 조건을 체크한다.
        - 변동폭큰 / 하락장 / 대폭락장: 1분 주기
        - 그 외 (안정장): 3분 주기
        """
        self._logger.info("[청산루프] 독립 청산 체크 시작 (국면별 1분/3분 가변)")
        token_fail_count = 0
        _TOKEN_FAIL_HALT = 3  # 연속 N회 토큰 실패 시 매매 중단
        while True:
            try:
                interval = 60 if self._current_phase in self._FAST_CHECK_PHASES else 180
                await asyncio.sleep(interval)
                if self.debugger.halt_trading:
                    break
                self._logger.debug("[청산루프] 청산 조건 체크 중... (국면=%s, 주기=%ds)", self._current_phase or "미확인", interval)

                # 토큰 상태 사전 체크
                try:
                    await self.executor._get_token()
                    token_fail_count = 0  # 성공 시 카운트 초기화
                except Exception as tok_exc:
                    token_fail_count += 1
                    self._logger.critical(
                        "[청산루프] KIS 토큰 발급 실패 (%d/%d회): %s",
                        token_fail_count, _TOKEN_FAIL_HALT, tok_exc
                    )
                    if token_fail_count >= _TOKEN_FAIL_HALT:
                        self._logger.critical(
                            "[청산루프] 토큰 %d회 연속 실패 → 자동매매 중단 (halt_trading=True)",
                            token_fail_count
                        )
                        self.debugger.halt_trading = True
                        await self.executor._send_telegram(
                            f"🚨 [시스템 중단] KIS 토큰 {token_fail_count}회 연속 실패\n"
                            f"자동매매가 중단되었습니다.\n"
                            f"KIS 앱키 상태 확인 후 프로그램을 재시작하세요."
                        )
                        break
                    continue

                closed = await self.executor._check_stop_take(current_phase=self._current_phase)
                # DCA 2차 매수 조건 체크
                dca_executed = await self.executor._check_pending_dca()
                if dca_executed:
                    self._logger.info("[청산루프] DCA 2차 매수 %d건 실행", dca_executed)
                # 청산이 발생하면 account_summary 즉시 재저장
                if closed or dca_executed:
                    try:
                        acct = await self.executor.fetch_account_summary()
                        if acct:
                            save_account_summary(**acct)
                            self._logger.info(
                                "[청산루프] 계좌 스냅샷 갱신: 현금=%s원 / 주식=%s원 (청산 %d건)",
                                f"{acct['cash_amt']:,}", f"{acct['stock_evlu_amt']:,}", closed
                            )
                    except Exception as e:
                        self._logger.warning("[청산루프] 계좌 스냅샷 갱신 실패: %s", e)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._logger.warning("[청산루프] 오류 (무시, 재시도): %s", exc)

    async def run_scheduled(self, interval_minutes: int = 30) -> None:
        """
        스케줄 기반 반복 실행.
        interval_minutes 주기로 run_once()를 반복 호출한다.
        Ctrl+C로 중단 가능.

        Args:
            interval_minutes: 반복 주기 (분 단위, 기본 30분)
        """
        self._logger.info(
            "스케줄 실행 시작 (주기: %d분) - Ctrl+C로 중단", interval_minutes
        )
        interval_sec    = interval_minutes * 60
        run_count       = 0
        last_history_date = ""  # history 마지막 업데이트 날짜 추적

        # 디버깅 에이전트 백그라운드 감시 시작
        self._debug_task = self.debugger.start_background(check_interval=30)
        self._logger.info("[디버깅] 백그라운드 감시 시작 (30초 주기)")

        # 독립 청산 체크 루프 시작 (국면별 1분/3분, 파이프라인과 별도)
        stop_take_task = asyncio.create_task(self._stop_take_loop())
        self._logger.info("[청산루프] 독립 청산 체크 태스크 시작 (국면별 1분/3분)")

        while True:
            run_start = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            session_mode = self._get_session_mode()
            self._logger.info("=== 파이프라인 실행 시작: %s [세션=%s] ===", run_start, session_mode)
            run_count += 1

            # 장외 시간: 파이프라인 실행 건너뜀 (청산 루프는 계속)
            if session_mode == "AFTER_HOURS":
                # 일일 백테스팅 트리거 (장 종료 후 1회)
                if not self._backtest_ran_today:
                    self._backtest_ran_today = True
                    try:
                        trigger = self.strategy_engine.create_message(
                            to="SR", data_type="BACKTEST_TRIGGER",
                            payload={"phase": self._current_phase, "mode": "daily"},
                        )
                        bt_result = await self.strategy_engine.run(trigger)
                        bt_payload = bt_result.body.get("payload", {})
                        self._logger.info("[백테스팅] %s", bt_payload.get("summary", ""))

                        # 전략 리포트 자동 생성
                        try:
                            import subprocess, sys
                            report_script = str(Path(__file__).parent / "scripts" / "generate_strategy_report.py")
                            subprocess.run(
                                [sys.executable, report_script, "--days", "30"],
                                timeout=60, capture_output=True,
                            )
                            self._logger.info("[리포트] 전략 리포트 갱신 완료")
                        except Exception as rpt_exc:
                            self._logger.warning("[리포트] 생성 실패: %s", rpt_exc)
                    except Exception as bt_exc:
                        self._logger.warning("[백테스팅] 실패: %s", bt_exc)

                self._logger.info("장외 시간 — 파이프라인 건너뜀 (%d분 후 재확인)", interval_minutes)
                try:
                    await asyncio.sleep(interval_sec)
                except (asyncio.CancelledError, KeyboardInterrupt):
                    break
                continue

            # 동시호가/장 시작 대기: 분석만 실행, 매수 보류
            if session_mode == "MARKET_OPEN_WAIT":
                self._logger.info("동시호가 구간 — 분석만 실행, 매수 보류")

            # 날짜 변경 시 history 자동 업데이트 + 백테스팅 플래그 리셋
            new_date = await self._update_history_if_needed(last_history_date)
            if new_date != last_history_date:
                self._backtest_ran_today = False
            last_history_date = new_date

            try:
                result = await self.run_once()
                status  = result.get("status", "unknown")
                err_msg = result.get("error", "")

                if status == "success":
                    # 최신 국면 정보 갱신 (청산루프가 참조)
                    self._current_phase = result.get("phase", self._current_phase)
                    self._logger.info(
                        "파이프라인 완료: status=%s, phase=%s, direction=%s, orders=%d건",
                        status,
                        self._current_phase,
                        result.get("direction", ""),
                        len(result.get("orders", [])),
                    )
                else:
                    self._logger.warning("파이프라인 오류: status=%s, error=%s", status, err_msg)

            except KeyboardInterrupt:
                # Ctrl+C 처리
                self._logger.info("스케줄 실행 중단 (Ctrl+C)")
                break
            except Exception as exc:
                self._logger.error("파이프라인 예외 발생: %s - 다음 주기에 재시도합니다.", exc)

            # 디버깅 에이전트 halt_trading 플래그 확인
            if self.debugger.halt_trading:
                self._logger.critical("[디버깅] halt_trading 플래그 감지 - 자동매매 중단")
                break

            # 다음 실행까지 대기 (세션 모드별 주기 조정)
            if session_mode == "CLOSING":
                wait_sec = 60  # 장 마감 정리: 1분 주기
            elif session_mode in ("PRE_ANALYSIS", "MARKET_OPEN_WAIT", "ENTRY_READY"):
                wait_sec = 300  # 사전분석/대기: 5분 주기
            else:
                wait_sec = interval_sec  # NORMAL: 기본 주기
            wait_min = wait_sec / 60
            self._logger.info("%.0f분 후 다음 실행... [세션=%s]", wait_min, session_mode)
            try:
                await asyncio.sleep(wait_sec)
            except asyncio.CancelledError:
                self._logger.info("스케줄 실행 취소됨")
                break

        # 청산 루프 및 디버깅 백그라운드 태스크 정리
        stop_take_task.cancel()
        if self._debug_task and not self._debug_task.done():
            self._debug_task.cancel()
            self._logger.info("[디버깅] 백그라운드 감시 종료")

    # ------------------------------------------------------------------
    # 시그널 역전 체크
    # ------------------------------------------------------------------

    @staticmethod
    def _check_signal_reversals(
        open_positions: list,
        active_signals: list,
    ) -> list:
        """
        보유 중인 포지션의 매수 트리거가 역전되었는지 확인한다.

        예: SOX 급등으로 SK하이��스 매수(signal_trigger="sox_up") 후
            이번 실행에서 SOX 급락(sox_crash) 감지 → 청산 후보

        Returns: [{"code", "name", "position_id", "avg_price", "quantity",
                   "sell_reason", "holding_period", "reason"}, ...]
        """
        from services.signal_service import SignalService

        # active_signals에서 indicator별 방향 수집
        current_directions: dict = {}  # {indicator_id: set(event_direction)}
        for sig in active_signals:
            signal_id = sig.get("signal_id", "")
            parsed = SignalService.parse_signal_id(signal_id)
            if parsed:
                ind_id, evt_dir = parsed
                current_directions.setdefault(ind_id, set()).add(evt_dir)

        exit_candidates = []
        for pos in open_positions:
            trigger = pos.get("signal_trigger", "")
            if not trigger or "_" not in trigger:
                continue

            parts = trigger.split("_", 1)
            if len(parts) != 2:
                continue
            indicator_id, original_dir = parts

            # 반대 방향 확인
            opposite = "down" if original_dir == "up" else "up"
            dirs = current_directions.get(indicator_id, set())
            if opposite in dirs:
                exit_candidates.append({
                    "code": pos.get("code", ""),
                    "name": pos.get("name", ""),
                    "position_id": pos.get("id", ""),
                    "avg_price": float(pos.get("avg_price", 0)),
                    "quantity": int(pos.get("quantity", 0)),
                    "sell_reason": "SIGNAL_REVERSAL",
                    "holding_period": pos.get("holding_period", ""),
                    "reason": f"{indicator_id} 방향 역전: {original_dir} → {opposite}",
                })

        return exit_candidates

    # ------------------------------------------------------------------
    # 로깅 헬퍼
    # ------------------------------------------------------------------

    def _log_step(self, step: str, name: str, detail: str = "") -> None:
        """
        [1/5] 데이터수집 ✓ 형식으로 진행 상황을 로깅한다.

        Args:
            step:   단계 번호 문자열 (예: "1/5")
            name:   단계명 (예: "데이터수집")
            detail: 추가 상세 정보 (선택)
        """
        if detail:
            self._logger.info("[%s] %s — %s", step, name, detail)
        else:
            self._logger.info("[%s] %s", step, name)


