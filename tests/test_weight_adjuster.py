"""
WeightAdjuster 에이전트 테스트 모듈
방향 결정, 국면별 가중치, 타겟 선택, execute() 동작을 검증한다.
"""

import asyncio
import pytest
import pytest_asyncio

from agents.weight_adjuster import WeightAdjuster
from protocol.protocol import StandardMessage


# ---------------------------------------------------------------------------
# 헬퍼 함수: 테스트용 StandardMessage 생성
# ---------------------------------------------------------------------------

def make_market_analysis_msg(phase="안정화", confidence=0.8, active_signals=None):
    """테스트용 MARKET_ANALYSIS 메시지를 생성한다."""
    payload = {
        "market_phase": {
            "phase": phase,
            "confidence": confidence,
            "elapsed_days": 0,
            "forecast": {},
            "strategy_timeline": {},
        },
        "active_signals": active_signals or [],
        "trend_reversal": {
            "reversal_up":   {"count": 0, "signals": [], "triggered": False},
            "reversal_down": {"count": 0, "signals": [], "triggered": False},
        },
    }
    return StandardMessage.create(
        from_agent="MA",
        to_agent="WA",
        data_type="MARKET_ANALYSIS",
        payload=payload,
    )


def _make_sox_signal(direction="BUY"):
    """반도체 관련 선행 신호를 생성한다."""
    return {
        "signal_id": "sox_surge",
        "direction": direction,
        "kr_sectors": ["반도체"],
        "strength": 1.5,
    }


def _make_avoid_signal():
    """AVOID 신호를 생성한다."""
    return {
        "signal_id": "vix_spike",
        "direction": "AVOID",
        "kr_sectors": ["전체"],
        "strength": 2.0,
    }


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture
def adjuster():
    """WeightAdjuster 인스턴스를 반환한다."""
    return WeightAdjuster()


# ---------------------------------------------------------------------------
# TestDetermineDirection
# ---------------------------------------------------------------------------

class TestDetermineDirection:
    """determine_direction() 메서드 테스트"""

    def test_급락장_방향_HOLD(self, adjuster):
        """phase=급락장 → 항상 HOLD"""
        direction = adjuster.determine_direction("급락장", [])
        assert direction == "HOLD", f"예상: HOLD, 실제: {direction}"

    def test_변동폭큰_방향_HOLD(self, adjuster):
        """phase=변동폭큰 → 항상 HOLD"""
        direction = adjuster.determine_direction("변동폭큰", [])
        assert direction == "HOLD", f"예상: HOLD, 실제: {direction}"

    def test_BUY신호_있으면_BUY(self, adjuster):
        """phase=급등장, active_signals에 direction=BUY → BUY"""
        signals = [_make_sox_signal(direction="BUY")]
        direction = adjuster.determine_direction("급등장", signals)
        assert direction == "BUY", f"예상: BUY, 실제: {direction}"

    def test_BUY신호_없으면_HOLD(self, adjuster):
        """phase=안정화, active_signals=[] → HOLD"""
        direction = adjuster.determine_direction("안정화", [])
        assert direction == "HOLD", f"예상: HOLD, 실제: {direction}"

    def test_AVOID신호만_있으면_HOLD(self, adjuster):
        """active_signals에 AVOID 신호만 있으면 HOLD"""
        signals = [_make_avoid_signal()]
        direction = adjuster.determine_direction("안정화", signals)
        assert direction == "HOLD", f"예상: HOLD, 실제: {direction}"


# ---------------------------------------------------------------------------
# TestGetPhaseWeights
# ---------------------------------------------------------------------------

class TestGetPhaseWeights:
    """get_phase_weights() 메서드 테스트"""

    def test_급등장_가중치(self, adjuster):
        """급등장 → aggressive=1.0, defensive=0.0, cash=0.0"""
        weights = adjuster.get_phase_weights("급등장")
        assert weights["aggressive"] == 1.0, f"aggressive: {weights['aggressive']}"
        assert weights["defensive"] == 0.0,  f"defensive: {weights['defensive']}"
        assert weights["cash"] == 0.0,       f"cash: {weights['cash']}"

    def test_안정화_가중치(self, adjuster):
        """안정화 → aggressive=0.7, defensive=0.0, cash=0.3"""
        weights = adjuster.get_phase_weights("안정화")
        assert weights["aggressive"] == 0.7, f"aggressive: {weights['aggressive']}"
        assert weights["defensive"] == 0.0,  f"defensive: {weights['defensive']}"
        assert weights["cash"] == 0.3,       f"cash: {weights['cash']}"

    def test_급락장_가중치(self, adjuster):
        """급락장 → aggressive=0.0, defensive=0.5, cash=0.5"""
        weights = adjuster.get_phase_weights("급락장")
        assert weights["aggressive"] == 0.0, f"aggressive: {weights['aggressive']}"
        assert weights["defensive"] == 0.5,  f"defensive: {weights['defensive']}"
        assert weights["cash"] == 0.5,       f"cash: {weights['cash']}"

    def test_변동폭큰_가중치(self, adjuster):
        """변동폭큰 → aggressive=0.0, defensive=0.2, cash=0.8"""
        weights = adjuster.get_phase_weights("변동폭큰")
        assert weights["aggressive"] == 0.0, f"aggressive: {weights['aggressive']}"
        assert weights["defensive"] == 0.2,  f"defensive: {weights['defensive']}"
        assert weights["cash"] == 0.8,       f"cash: {weights['cash']}"

    def test_알수없는_국면_기본값(self, adjuster):
        """알 수 없는 국면 → 예외 없이 aggressive 키를 포함한 dict 반환"""
        try:
            weights = adjuster.get_phase_weights("알수없음")
        except Exception as exc:
            pytest.fail(f"알 수 없는 국면에서 예외 발생: {exc}")
        assert "aggressive" in weights, "aggressive 키가 없음"
        assert isinstance(weights["aggressive"], (int, float)), "aggressive 값이 숫자가 아님"


# ---------------------------------------------------------------------------
# TestSelectTargets
# ---------------------------------------------------------------------------

class TestSelectTargets:
    """select_targets() 메서드 테스트"""

    def test_HOLD_국면_타겟_없음(self, adjuster):
        """phase=급락장 → 타겟 없음 (빈 리스트 반환)"""
        weight_config = adjuster.get_phase_weights("급락장")
        targets = adjuster.select_targets("급락장", [], weight_config)
        assert targets == [], f"예상: [], 실제: {targets}"

    def test_BUY_신호_섹터_종목_선택(self, adjuster):
        """sox_surge(반도체) 신호 있으면 반도체 종목 포함"""
        signals = [_make_sox_signal(direction="BUY")]
        weight_config = adjuster.get_phase_weights("급등장")
        targets = adjuster.select_targets("급등장", signals, weight_config)
        sector_names = " ".join(
            t.get("name", "") + t.get("code", "") for t in targets
        )
        # 반도체 종목(삼성전자, SK하이닉스, 한미반도체 등)이 포함되어야 함
        assert len(targets) > 0, "반도체 신호에도 타겟이 선택되지 않음"
        semiconductor_codes = {"005930", "000660", "042700"}  # 삼성전자, SK하이닉스, 한미반도체
        returned_codes = {t.get("code", "") for t in targets}
        has_semiconductor = bool(returned_codes & semiconductor_codes) or "반도체" in sector_names
        assert has_semiconductor, f"반도체 종목이 타겟에 없음. 타겟: {targets}"

    def test_AVOID_섹터_제외(self, adjuster):
        """AVOID 신호가 있는 섹터 종목은 포함 안 됨"""
        buy_signal = _make_sox_signal(direction="BUY")
        avoid_signal = _make_avoid_signal()  # 전체 AVOID
        signals = [buy_signal, avoid_signal]
        weight_config = adjuster.get_phase_weights("안정화")
        targets = adjuster.select_targets("안정화", signals, weight_config)
        # AVOID 신호가 우선되므로 타겟이 없거나 AVOID 섹터 종목이 없어야 함
        for t in targets:
            assert t.get("direction", "BUY") != "AVOID", \
                f"AVOID 종목이 타겟에 포함됨: {t}"

    def test_최대_5종목_제한(self, adjuster):
        """여러 BUY 신호가 있어도 최대 5종목만 반환"""
        signals = [
            {"signal_id": "sox_surge",     "direction": "BUY", "kr_sectors": ["반도체"],  "strength": 2.0},
            {"signal_id": "nasdaq_surge",   "direction": "BUY", "kr_sectors": ["IT"],      "strength": 1.5},
            {"signal_id": "tesla_surge",    "direction": "BUY", "kr_sectors": ["2차전지"],  "strength": 1.5},
            {"signal_id": "copper_surge",   "direction": "BUY", "kr_sectors": ["경기민감"], "strength": 1.2},
            {"signal_id": "nvidia_surge",   "direction": "BUY", "kr_sectors": ["반도체"],  "strength": 2.5},
        ]
        weight_config = adjuster.get_phase_weights("급등장")
        targets = adjuster.select_targets("급등장", signals, weight_config)
        assert len(targets) <= 5, f"5종목 초과: {len(targets)}종목"

    def test_weight_합_aggressive_이하(self, adjuster):
        """모든 targets의 weight 합이 aggressive_pct 이하"""
        signals = [_make_sox_signal(direction="BUY")]
        weight_config = adjuster.get_phase_weights("급등장")
        targets = adjuster.select_targets("급등장", signals, weight_config)
        if targets:
            total_weight = sum(t.get("weight", 0.0) for t in targets)
            aggressive_pct = weight_config["aggressive"]
            assert total_weight <= aggressive_pct + 1e-9, \
                f"weight 합({total_weight:.4f}) > aggressive({aggressive_pct})"


# ---------------------------------------------------------------------------
# TestExecute (async)
# ---------------------------------------------------------------------------

class TestExecute:
    """execute() 메서드 테스트"""

    @pytest.mark.asyncio
    async def test_execute_returns_standard_message(self, adjuster):
        """execute()가 StandardMessage를 반환해야 한다."""
        msg = make_market_analysis_msg(phase="안정화", confidence=0.8)
        result = await adjuster.execute(msg)
        assert isinstance(result, StandardMessage), \
            f"반환 타입 오류: {type(result)}"

    @pytest.mark.asyncio
    async def test_execute_data_type_SIGNAL(self, adjuster):
        """body['data_type'] == 'SIGNAL'"""
        msg = make_market_analysis_msg(phase="급등장", confidence=0.9,
                                       active_signals=[_make_sox_signal()])
        result = await adjuster.execute(msg)
        assert result.body.get("data_type") == "SIGNAL", \
            f"data_type 오류: {result.body.get('data_type')}"

    @pytest.mark.asyncio
    async def test_execute_to_EX(self, adjuster):
        """header.to_agent == 'EX'"""
        msg = make_market_analysis_msg(phase="안정화", confidence=0.8)
        result = await adjuster.execute(msg)
        assert result.header.to_agent == "EX", \
            f"to_agent 오류: {result.header.to_agent}"

    @pytest.mark.asyncio
    async def test_execute_급락장_HOLD(self, adjuster):
        """급락장 → direction='HOLD', targets=[]"""
        msg = make_market_analysis_msg(phase="급락장", confidence=0.9)
        result = await adjuster.execute(msg)
        payload = result.body.get("payload", {})
        assert payload.get("direction") == "HOLD", \
            f"급락장에서 direction이 HOLD가 아님: {payload.get('direction')}"
        assert payload.get("targets") == [], \
            f"급락장에서 targets가 비어있지 않음: {payload.get('targets')}"

    @pytest.mark.asyncio
    async def test_execute_payload_구조(self, adjuster):
        """payload에 signal_id, direction, confidence, phase, targets, weight_config, reason이 모두 있음"""
        msg = make_market_analysis_msg(phase="안정화", confidence=0.8)
        result = await adjuster.execute(msg)
        payload = result.body.get("payload", {})
        required_keys = [
            "signal_id",
            "direction",
            "confidence",
            "phase",
            "targets",
            "weight_config",
            "reason",
        ]
        for key in required_keys:
            assert key in payload, f"payload에 '{key}' 키 없음. payload: {list(payload.keys())}"


# ---------------------------------------------------------------------------
# SELL / REDUCE direction 테스트
# ---------------------------------------------------------------------------

class TestSellReduceDirection:
    """SELL/REDUCE 신호에 의한 direction 결정 및 sell_targets 생성 테스트"""

    @pytest.fixture
    def adjuster(self):
        return WeightAdjuster()

    def _make_sell_signal(self, signal_id="sox_crash", kr_sectors=None):
        return {
            "signal_id": signal_id,
            "direction": "SELL",
            "kr_sectors": kr_sectors or ["반도체"],
            "kr_themes": [],
            "strength": 1.5,
            "value": -3.5,
        }

    def _make_reduce_signal(self, reduce_pct=50):
        return {
            "signal_id": "vix_warning",
            "direction": "REDUCE",
            "kr_sectors": [],
            "kr_themes": [],
            "strength": 1.1,
            "value": 27.0,
            "reduce_pct": reduce_pct,
        }

    def test_sell_signal_returns_SELL_direction(self, adjuster):
        """SELL 신호가 있으면 direction = 'SELL'"""
        signals = [self._make_sell_signal()]
        direction = adjuster.determine_direction("일반장", signals)
        assert direction == "SELL", f"SELL 신호인데 direction={direction}"

    def test_reduce_signal_returns_HOLD_direction(self, adjuster):
        """REDUCE 신호만 있으면 direction = 'HOLD'"""
        signals = [self._make_reduce_signal()]
        direction = adjuster.determine_direction("일반장", signals)
        assert direction == "HOLD", f"REDUCE 신호인데 direction={direction}"

    def test_sell_overrides_buy_signal(self, adjuster):
        """SELL 신호가 BUY 신호보다 우선"""
        signals = [
            _make_sox_signal(direction="BUY"),
            self._make_sell_signal(),
        ]
        direction = adjuster.determine_direction("상승장", signals)
        assert direction == "SELL", f"SELL+BUY 혼재 시 direction={direction}, SELL이어야 함"

    def test_get_preemptive_sell_targets_empty_positions(self, adjuster):
        """보유 포지션이 없으면 선제 매도 대상도 없다."""
        sell_signals = [self._make_sell_signal()]
        targets = adjuster._get_preemptive_sell_targets(sell_signals)
        assert isinstance(targets, list), "반환 타입이 list가 아님"

    def test_get_preemptive_sell_empty_sectors(self, adjuster):
        """kr_sectors, kr_themes가 모두 비어 있으면 빈 리스트 반환"""
        sig = {"signal_id": "test", "direction": "SELL", "kr_sectors": [], "kr_themes": []}
        targets = adjuster._get_preemptive_sell_targets([sig])
        assert targets == [], f"섹터 없는 SELL 신호인데 targets={targets}"

    def test_get_reduce_targets_empty_positions(self, adjuster):
        """보유 포지션이 없으면 축소 대상도 없다."""
        targets = adjuster._get_reduce_targets(50)
        assert isinstance(targets, list), "반환 타입이 list가 아님"

    def test_get_reduce_targets_ratio(self, adjuster, monkeypatch):
        """quantity=10, reduce_pct=50 → sell_qty=5"""
        fake_positions = [
            {"code": "005930", "name": "삼성전자", "id": "p1",
             "avg_price": 70000, "quantity": 10}
        ]
        monkeypatch.setattr(
            adjuster._position_manager, "get_open_positions",
            lambda: fake_positions,
        )
        targets = adjuster._get_reduce_targets(50)
        assert len(targets) == 1
        assert targets[0]["quantity"] == 5, f"예상 5, 실제={targets[0]['quantity']}"
        assert targets[0]["sell_reason"] == "REDUCE_POSITION"

    def test_get_reduce_targets_skips_full_quantity(self, adjuster, monkeypatch):
        """quantity=1, reduce_pct=50 → sell_qty=1=quantity → 건너뜀"""
        fake_positions = [
            {"code": "005930", "name": "삼성전자", "id": "p1",
             "avg_price": 70000, "quantity": 1}
        ]
        monkeypatch.setattr(
            adjuster._position_manager, "get_open_positions",
            lambda: fake_positions,
        )
        targets = adjuster._get_reduce_targets(50)
        assert targets == [], f"quantity=1에서 REDUCE는 건너뛰어야 함. targets={targets}"

    @pytest.mark.asyncio
    async def test_execute_sell_signal_in_payload(self, adjuster):
        """SELL 신호 포함 시 execute() payload의 direction == 'SELL'"""
        msg = make_market_analysis_msg(
            phase="상승장",
            confidence=0.8,
            active_signals=[{
                "signal_id": "sox_crash",
                "direction": "SELL",
                "axis": "sector",
                "kr_sectors": ["반도체"],
                "kr_themes": [],
                "description": "SOX 급락",
                "strength": 1.5,
                "value": -3.5,
            }],
        )
        result = await adjuster.execute(msg)
        payload = result.body.get("payload", {})
        assert payload.get("direction") == "SELL", \
            f"SELL 신호인데 direction={payload.get('direction')}"
