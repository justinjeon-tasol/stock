"""
Orchestrator 단위 테스트 (Mock 기반)

대상: Orchestrator 클래스 (orchestrator.py)
파이프라인: DataCollector → Preprocessor → MarketAnalyzer → WeightAdjuster → Executor
"""

import os
import sys
import asyncio
import logging
from unittest.mock import AsyncMock, patch, MagicMock, call

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protocol.protocol import StandardMessage


# ---------------------------------------------------------------------------
# 헬퍼 함수: 각 파이프라인 단계별 Mock 메시지 생성
# ---------------------------------------------------------------------------

def make_raw_msg():
    """DataCollector 출력 모킹"""
    return StandardMessage.create("DC", "PP", "RAW_MARKET_DATA", {
        "us_market": {"nasdaq": {"value": 18000, "change_pct": 2.0, "volume_ratio": 1.8}},
        "kr_market": {"kospi": {"value": 2600, "change_pct": 1.6, "volume_ratio": 1.6}},
        "commodities": {}
    })


def make_preprocessed_msg():
    """Preprocessor 출력 모킹"""
    return StandardMessage.create("PP", "MA", "PREPROCESSED_DATA", {
        "us_market": {
            "nasdaq":  {"value": 18000, "change_pct": 2.0, "volume_ratio": 1.8},
            "vix":     {"value": 18.0, "change_pct": -1.0},
            "usd_krw": {"value": 1320, "change_pct": -0.2},
            "sox":     {"value": 3200, "change_pct": 2.5, "volume_ratio": 1.9},
            "sp500":   {"value": 5000, "change_pct": 1.2, "volume_ratio": 1.5},
            "futures": {"value": 18050, "direction": "UP"},
            "individual": {},
        },
        "kr_market": {
            "kospi":          {"value": 2600, "change_pct": 1.6, "volume_ratio": 1.6},
            "kosdaq":         {"value": 850, "change_pct": 1.2, "volume_ratio": 1.4},
            "foreign_net":    500,
            "institution_net": 200,
            "stocks":         {},
        },
        "commodities": {
            "wti":     {"value": 80, "change_pct": 0.5},
            "gold":    {"value": 2000, "change_pct": 0.2},
            "copper":  {"value": 4.0, "change_pct": 0.3},
            "lithium": {"value": 20, "change_pct": 0.1},
        },
    })


def make_market_analysis_msg():
    """MarketAnalyzer 출력 모킹"""
    return StandardMessage.create("MA", "WA", "MARKET_ANALYSIS", {
        "market_phase": {
            "phase": "급등장",
            "confidence": 0.9,
            "elapsed_days": 1,
            "forecast": {},
            "strategy_timeline": {},
        },
        "active_signals": [
            {
                "signal_id": "sox_surge",
                "direction": "BUY",
                "kr_sectors": ["반도체"],
                "strength": 1.5,
                "value": 2.5,
            }
        ],
        "trend_reversal": {
            "reversal_up":   {"count": 0, "signals": [], "triggered": False},
            "reversal_down": {"count": 0, "signals": [], "triggered": False},
        },
    })


def make_signal_msg():
    """WeightAdjuster 출력 모킹"""
    return StandardMessage.create("WA", "EX", "SIGNAL", {
        "signal_id":    "WA_TEST_0001",
        "direction":    "BUY",
        "confidence":   0.9,
        "phase":        "급등장",
        "issue_factor": None,
        "targets": [
            {"code": "000660", "name": "SK하이닉스", "weight": 0.3}
        ],
        "weight_config": {
            "aggressive_pct": 1.0,
            "defensive_pct":  0.0,
            "cash_pct":       0.0,
        },
        "reason": "테스트 신호",
    }, msg_type="SIGNAL")


def make_order_msg():
    """Executor 출력 모킹"""
    return StandardMessage.create("EX", "OR", "ORDER", {
        "order_id":  "EX_TEST_0001",
        "signal_id": "WA_TEST_0001",
        "action":    "BUY",
        "results": [
            {
                "code":     "000660",
                "name":     "SK하이닉스",
                "status":   "OK",
                "order_no": "12345",
                "message":  "주문 성공",
            }
        ],
        "mode":   "MOCK",
        "reason": "테스트",
    })


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture
def orchestrator():
    """
    각 에이전트의 __init__을 패치하여 실제 초기화 없이
    Orchestrator 인스턴스를 생성한다.
    """
    with patch("agents.data_collector.DataCollector.__init__", return_value=None), \
         patch("agents.preprocessor.Preprocessor.__init__", return_value=None), \
         patch("agents.market_analyzer.MarketAnalyzer.__init__", return_value=None), \
         patch("agents.weight_adjuster.WeightAdjuster.__init__", return_value=None), \
         patch("agents.executor.Executor.__init__", return_value=None):
        from orchestrator import Orchestrator
        orc = Orchestrator.__new__(Orchestrator)
        orc.data_collector  = MagicMock()
        orc.preprocessor    = MagicMock()
        orc.market_analyzer = MagicMock()
        orc.weight_adjuster = MagicMock()
        orc.executor        = MagicMock()
        orc._logger = logging.getLogger("test_orchestrator")
        return orc


def _setup_all_mocks(orc):
    """모든 에이전트를 정상 반환값으로 세팅하는 편의 함수."""
    orc.data_collector.run  = AsyncMock(return_value=make_raw_msg())
    orc.preprocessor.run    = AsyncMock(return_value=make_preprocessed_msg())
    orc.market_analyzer.run = AsyncMock(return_value=make_market_analysis_msg())
    orc.weight_adjuster.run = AsyncMock(return_value=make_signal_msg())
    orc.executor.run        = AsyncMock(return_value=make_order_msg())


# ---------------------------------------------------------------------------
# TestRunOnce — 정상 흐름
# ---------------------------------------------------------------------------

class TestRunOnce:
    """run_once() 정상 흐름 및 실패 시나리오 테스트"""

    # 1. 전체 mock → result["status"] == "success"
    @pytest.mark.asyncio
    async def test_run_once_성공_status(self, orchestrator):
        """모든 에이전트가 정상 실행되면 status='success'를 반환해야 한다."""
        _setup_all_mocks(orchestrator)

        result = await orchestrator.run_once()

        assert result["status"] == "success", (
            f"status가 'success'여야 한다. 실제: {result.get('status')}"
        )

    # 2. result["phase"] == "급등장"
    @pytest.mark.asyncio
    async def test_run_once_phase_추출(self, orchestrator):
        """result['phase']가 MarketAnalyzer 출력에서 추출한 '급등장'이어야 한다."""
        _setup_all_mocks(orchestrator)

        result = await orchestrator.run_once()

        assert result.get("phase") == "급등장", (
            f"phase가 '급등장'이어야 한다. 실제: {result.get('phase')}"
        )

    # 3. result["direction"] == "BUY"
    @pytest.mark.asyncio
    async def test_run_once_direction_추출(self, orchestrator):
        """result['direction']이 WeightAdjuster 신호의 'BUY'여야 한다."""
        _setup_all_mocks(orchestrator)

        result = await orchestrator.run_once()

        assert result.get("direction") == "BUY", (
            f"direction이 'BUY'여야 한다. 실제: {result.get('direction')}"
        )

    # 4. result["orders"]가 list이고 len > 0
    @pytest.mark.asyncio
    async def test_run_once_orders_추출(self, orchestrator):
        """result['orders']가 비어있지 않은 list여야 한다."""
        _setup_all_mocks(orchestrator)

        result = await orchestrator.run_once()

        orders = result.get("orders")
        assert isinstance(orders, list), (
            f"orders가 list여야 한다. 실제 타입: {type(orders)}"
        )
        assert len(orders) > 0, "orders가 비어있으면 안 된다."

    # 5. result["signal"]이 dict이고 "direction" 키 포함
    @pytest.mark.asyncio
    async def test_run_once_signal_추출(self, orchestrator):
        """result['signal']이 dict이고 'direction' 키를 포함해야 한다."""
        _setup_all_mocks(orchestrator)

        result = await orchestrator.run_once()

        signal = result.get("signal")
        assert isinstance(signal, dict), (
            f"signal이 dict여야 한다. 실제 타입: {type(signal)}"
        )
        assert "direction" in signal, (
            f"signal에 'direction' 키가 없다. 키 목록: {list(signal.keys())}"
        )

    # 6. DataCollector 예외 → status=="error", error에 "Step1" 포함
    @pytest.mark.asyncio
    async def test_step1_실패_즉시반환(self, orchestrator):
        """DataCollector.run이 예외를 던지면 status='error', error에 'Step1' 포함."""
        _setup_all_mocks(orchestrator)
        orchestrator.data_collector.run = AsyncMock(
            side_effect=RuntimeError("네트워크 오류")
        )

        result = await orchestrator.run_once()

        assert result["status"] == "error", (
            f"DataCollector 실패 시 status='error'여야 한다. 실제: {result.get('status')}"
        )
        assert result.get("error") is not None, "error 필드가 None이면 안 된다."
        assert "Step1" in result["error"], (
            f"error 메시지에 'Step1'이 포함되어야 한다. 실제: {result['error']}"
        )

    # 7. Preprocessor 예외 → status=="error", error에 "Step2" 포함
    @pytest.mark.asyncio
    async def test_step2_실패_즉시반환(self, orchestrator):
        """Preprocessor.run이 예외를 던지면 status='error', error에 'Step2' 포함."""
        _setup_all_mocks(orchestrator)
        orchestrator.preprocessor.run = AsyncMock(
            side_effect=ValueError("전처리 오류")
        )

        result = await orchestrator.run_once()

        assert result["status"] == "error", (
            f"Preprocessor 실패 시 status='error'여야 한다. 실제: {result.get('status')}"
        )
        assert result.get("error") is not None, "error 필드가 None이면 안 된다."
        assert "Step2" in result["error"], (
            f"error 메시지에 'Step2'가 포함되어야 한다. 실제: {result['error']}"
        )

    # 8. MarketAnalyzer 예외 → status=="error", error에 "Step3" 포함
    @pytest.mark.asyncio
    async def test_step3_실패_즉시반환(self, orchestrator):
        """MarketAnalyzer.run이 예외를 던지면 status='error', error에 'Step3' 포함."""
        _setup_all_mocks(orchestrator)
        orchestrator.market_analyzer.run = AsyncMock(
            side_effect=TimeoutError("분석 타임아웃")
        )

        result = await orchestrator.run_once()

        assert result["status"] == "error", (
            f"MarketAnalyzer 실패 시 status='error'여야 한다. 실제: {result.get('status')}"
        )
        assert result.get("error") is not None, "error 필드가 None이면 안 된다."
        assert "Step3" in result["error"], (
            f"error 메시지에 'Step3'이 포함되어야 한다. 실제: {result['error']}"
        )

    # 9. WeightAdjuster 예외 → status=="error", error에 "Step4" 포함
    @pytest.mark.asyncio
    async def test_step4_실패_즉시반환(self, orchestrator):
        """WeightAdjuster.run이 예외를 던지면 status='error', error에 'Step4' 포함."""
        _setup_all_mocks(orchestrator)
        orchestrator.weight_adjuster.run = AsyncMock(
            side_effect=RuntimeError("가중치 계산 오류")
        )

        result = await orchestrator.run_once()

        assert result["status"] == "error", (
            f"WeightAdjuster 실패 시 status='error'여야 한다. 실제: {result.get('status')}"
        )
        assert result.get("error") is not None, "error 필드가 None이면 안 된다."
        assert "Step4" in result["error"], (
            f"error 메시지에 'Step4'가 포함되어야 한다. 실제: {result['error']}"
        )

    # 10. Executor 예외 → result dict 반환 (None 아님), error 필드에 "Step5" 포함
    @pytest.mark.asyncio
    async def test_step5_실패해도_결과반환(self, orchestrator):
        """
        Executor.run이 예외를 던져도 result dict를 반환해야 한다 (None 아님).
        Step5는 graceful degradation — status가 'success'이더라도
        result['error']에 'Step5'가 포함되어야 한다.
        """
        _setup_all_mocks(orchestrator)
        orchestrator.executor.run = AsyncMock(
            side_effect=ConnectionError("주문 서버 연결 실패")
        )

        result = await orchestrator.run_once()

        assert result is not None, "Executor 실패 시에도 result가 None이면 안 된다."
        assert isinstance(result, dict), (
            f"result가 dict여야 한다. 실제 타입: {type(result)}"
        )
        # Step5는 graceful degradation: status가 아닌 error 필드로 실패를 전달
        assert result.get("error") is not None, (
            "Executor 실패 시 result['error']에 오류 메시지가 담겨야 한다."
        )
        assert "Step5" in result["error"], (
            f"result['error']에 'Step5'가 포함되어야 한다. 실제: {result['error']}"
        )


# ---------------------------------------------------------------------------
# TestPipelineFlow — 단계 연결
# ---------------------------------------------------------------------------

class TestPipelineFlow:
    """파이프라인 단계 간 연결 검증"""

    # 11. 정상 흐름에서 각 에이전트 run()이 정확히 1회 호출됨
    @pytest.mark.asyncio
    async def test_각_에이전트_1회_호출(self, orchestrator):
        """정상 흐름에서 각 에이전트의 run()이 정확히 1회씩 호출되어야 한다."""
        _setup_all_mocks(orchestrator)

        await orchestrator.run_once()

        orchestrator.data_collector.run.assert_called_once()
        orchestrator.preprocessor.run.assert_called_once()
        orchestrator.market_analyzer.run.assert_called_once()
        orchestrator.weight_adjuster.run.assert_called_once()
        orchestrator.executor.run.assert_called_once()

    # 12. preprocessor.run에 전달된 인자가 data_collector.run()의 반환값
    @pytest.mark.asyncio
    async def test_step2_입력이_step1_출력(self, orchestrator):
        """preprocessor.run에 전달된 인자가 data_collector.run()의 반환값과 동일해야 한다."""
        step1_msg = make_raw_msg()
        orchestrator.data_collector.run  = AsyncMock(return_value=step1_msg)
        orchestrator.preprocessor.run    = AsyncMock(return_value=make_preprocessed_msg())
        orchestrator.market_analyzer.run = AsyncMock(return_value=make_market_analysis_msg())
        orchestrator.weight_adjuster.run = AsyncMock(return_value=make_signal_msg())
        orchestrator.executor.run        = AsyncMock(return_value=make_order_msg())

        await orchestrator.run_once()

        args, kwargs = orchestrator.preprocessor.run.call_args
        passed_arg = args[0] if args else kwargs.get("input_data") or kwargs.get("msg")
        assert passed_arg is step1_msg, (
            "preprocessor.run에 data_collector.run()의 반환값이 그대로 전달되어야 한다."
        )

    # 13. weight_adjuster.run에 전달된 인자가 market_analyzer.run()의 반환값
    @pytest.mark.asyncio
    async def test_step4_입력이_step3_출력(self, orchestrator):
        """weight_adjuster.run에 전달된 인자가 market_analyzer.run()의 반환값과 동일해야 한다."""
        step3_msg = make_market_analysis_msg()
        orchestrator.data_collector.run  = AsyncMock(return_value=make_raw_msg())
        orchestrator.preprocessor.run    = AsyncMock(return_value=make_preprocessed_msg())
        orchestrator.market_analyzer.run = AsyncMock(return_value=step3_msg)
        orchestrator.weight_adjuster.run = AsyncMock(return_value=make_signal_msg())
        orchestrator.executor.run        = AsyncMock(return_value=make_order_msg())

        await orchestrator.run_once()

        args, kwargs = orchestrator.weight_adjuster.run.call_args
        passed_arg = args[0] if args else kwargs.get("input_data") or kwargs.get("msg")
        assert passed_arg is step3_msg, (
            "weight_adjuster.run에 market_analyzer.run()의 반환값이 그대로 전달되어야 한다."
        )

    # 14. executor.run에 전달된 인자가 weight_adjuster.run()의 반환값
    @pytest.mark.asyncio
    async def test_step5_입력이_step4_출력(self, orchestrator):
        """executor.run에 전달된 인자가 weight_adjuster.run()의 반환값과 동일해야 한다."""
        step4_msg = make_signal_msg()
        orchestrator.data_collector.run  = AsyncMock(return_value=make_raw_msg())
        orchestrator.preprocessor.run    = AsyncMock(return_value=make_preprocessed_msg())
        orchestrator.market_analyzer.run = AsyncMock(return_value=make_market_analysis_msg())
        orchestrator.weight_adjuster.run = AsyncMock(return_value=step4_msg)
        orchestrator.executor.run        = AsyncMock(return_value=make_order_msg())

        await orchestrator.run_once()

        args, kwargs = orchestrator.executor.run.call_args
        passed_arg = args[0] if args else kwargs.get("input_data") or kwargs.get("msg")
        assert passed_arg is step4_msg, (
            "executor.run에 weight_adjuster.run()의 반환값이 그대로 전달되어야 한다."
        )


# ---------------------------------------------------------------------------
# TestRunScheduled
# ---------------------------------------------------------------------------

class TestRunScheduled:
    """run_scheduled() 스케줄 반복 실행 테스트"""

    # 15. asyncio.sleep mock으로 즉시 CancelledError → run_once 1회 호출 확인
    @pytest.mark.asyncio
    async def test_run_scheduled_1회_실행_후_취소(self, orchestrator):
        """
        asyncio.sleep을 즉시 CancelledError로 대체하면
        run_once()가 정확히 1회 호출된 후 스케줄이 종료되어야 한다.
        """
        _setup_all_mocks(orchestrator)

        run_once_call_count = 0
        original_run_once = orchestrator.run_once

        async def mock_run_once():
            nonlocal run_once_call_count
            run_once_call_count += 1
            return await original_run_once()

        orchestrator.run_once = mock_run_once

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            mock_sleep.side_effect = asyncio.CancelledError()

            try:
                await orchestrator.run_scheduled(interval_minutes=1)
            except asyncio.CancelledError:
                pass  # CancelledError가 밖으로 전파되는 경우도 허용

        assert run_once_call_count == 1, (
            f"run_once()가 정확히 1회 호출되어야 한다. 실제: {run_once_call_count}회"
        )
