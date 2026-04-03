"""
Recommender 에이전트 테스트 모듈
종목 선정, 비중 계산, 이유 생성, 시장 요약, execute() 동작을 검증한다.
"""

import asyncio
import pytest

from agents.recommender import Recommender, STOCK_UNIVERSE, PHASE_WEIGHTS
from protocol.protocol import StandardMessage, RecommendationPayload


# ---------------------------------------------------------------------------
# 헬퍼 함수: 테스트용 StandardMessage 생성
# ---------------------------------------------------------------------------

def _make_market_analysis_message(
    phase: str = "안정화",
    confidence: float = 0.8,
    active_signals: list = None,
    us_market: dict = None,
    kr_market: dict = None,
) -> StandardMessage:
    """테스트용 MARKET_ANALYSIS 메시지를 생성한다."""
    if active_signals is None:
        active_signals = []
    if us_market is None:
        us_market = {
            "vix":     {"value": 18.0,  "change_pct": 0.5},
            "usd_krw": {"value": 1320.0, "change_pct": 0.1},
        }
    if kr_market is None:
        kr_market = {
            "kospi":  {"value": 2600.0, "change_pct": 0.3, "volume_ratio": 1.0},
            "kosdaq": {"value": 850.0,  "change_pct": 0.2, "volume_ratio": 0.9},
        }

    payload = {
        "market_phase": {
            "phase":            phase,
            "confidence":       confidence,
            "elapsed_days":     0,
            "forecast":         {},
            "strategy_timeline": {},
        },
        "active_signals": active_signals,
        "trend_reversal": {
            "reversal_up":   {"count": 0, "signals": [], "triggered": False},
            "reversal_down": {"count": 0, "signals": [], "triggered": False},
        },
        "us_market": us_market,
        "kr_market":  kr_market,
    }
    return StandardMessage.create(
        from_agent="MA",
        to_agent="RC",
        data_type="MARKET_ANALYSIS",
        payload=payload,
    )


def _make_sox_surge_signal() -> dict:
    """SOX 급등 BUY 신호를 반환한다."""
    return {
        "signal_id":   "sox_surge",
        "direction":   "BUY",
        "kr_sectors":  ["반도체"],
        "description": "SOX 급등 → 반도체 수혜",
        "strength":    1.9,
        "value":       3.8,
    }


def _make_nvidia_surge_signal() -> dict:
    """엔비디아 급등 BUY 신호를 반환한다."""
    return {
        "signal_id":   "nvidia_surge",
        "direction":   "BUY",
        "kr_sectors":  ["반도체"],
        "description": "엔비디아 급등 → HBM/AI 반도체",
        "strength":    1.73,
        "value":       5.2,
    }


def _make_vix_spike_signal(value: float = 32.0) -> dict:
    """VIX 급등 AVOID 신호를 반환한다."""
    return {
        "signal_id":   "vix_spike",
        "direction":   "AVOID",
        "kr_sectors":  [],
        "description": "VIX 30 돌파 → 외국인 대량 매도 예고",
        "strength":    value / 30.0,
        "value":       value,
    }


def _make_gold_strong_signal() -> dict:
    """금 강세 AVOID 신호를 반환한다."""
    return {
        "signal_id":   "gold_strong",
        "direction":   "AVOID",
        "kr_sectors":  [],
        "description": "금 강세 → 안전자산 선호, 위험자산 하락",
        "strength":    1.33,
        "value":       2.0,
    }


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture
def recommender():
    """Recommender 인스턴스를 반환한다."""
    return Recommender()


# ---------------------------------------------------------------------------
# 종목 선정 테스트
# ---------------------------------------------------------------------------

class TestSelectStocks:
    """select_stocks() 메서드 테스트"""

    def test_급등장_반도체_신호_추천(self, recommender):
        """급등장 + sox_surge/nvidia_surge → 반도체 섹터(삼성전자/SK하이닉스 등) 추천"""
        signals = [_make_sox_surge_signal(), _make_nvidia_surge_signal()]
        recs = recommender.select_stocks("급등장", signals, 0.9)

        assert len(recs) > 0, "추천 종목이 없음"

        # 반도체 섹터 종목 코드
        semiconductor_codes = {s["code"] for s in STOCK_UNIVERSE.get("반도체", [])}
        rec_codes = {r.code for r in recs}

        assert rec_codes & semiconductor_codes, \
            f"반도체 종목이 추천되지 않음. 추천: {rec_codes}"

    def test_급락장_추천없음(self, recommender):
        """급락장 → 추천 종목 없음 (현금 보유)"""
        signals = [_make_sox_surge_signal()]  # BUY 신호가 있어도
        recs = recommender.select_stocks("급락장", signals, 0.9)
        assert len(recs) == 0, f"급락장에서 추천이 있으면 안 됨: {[r.code for r in recs]}"

    def test_변동폭큰_추천없음(self, recommender):
        """변동폭큰 → 추천 종목 없음 (현금 비중 최대)"""
        signals = [_make_nvidia_surge_signal()]
        recs = recommender.select_stocks("변동폭큰", signals, 0.7)
        assert len(recs) == 0, f"변동폭큰에서 추천이 있으면 안 됨: {[r.code for r in recs]}"

    def test_avoid_신호_섹터_제외(self, recommender):
        """gold_strong AVOID 신호 → 관련 없는 섹터만 추천 (반도체는 추천될 수 있음)"""
        signals = [
            _make_gold_strong_signal(),   # AVOID (kr_sectors=[])
            _make_sox_surge_signal(),     # BUY 반도체
        ]
        recs = recommender.select_stocks("급등장", signals, 0.85)
        # gold_strong은 kr_sectors=[]이므로 직접 제외 섹터 없음
        # 하지만 반도체 BUY 신호가 있으므로 반도체 추천
        semiconductor_codes = {s["code"] for s in STOCK_UNIVERSE.get("반도체", [])}
        rec_codes = {r.code for r in recs}
        if recs:
            assert rec_codes & semiconductor_codes, "BUY 신호 있는 섹터 종목이 없음"

    def test_max_추천수(self, recommender):
        """추천 종목 수는 MAX_RECOMMENDATIONS 이하여야 한다."""
        # 여러 BUY 신호 생성
        signals = [
            _make_sox_surge_signal(),
            _make_nvidia_surge_signal(),
            {
                "signal_id":   "tesla_strong",
                "direction":   "BUY",
                "kr_sectors":  ["2차전지"],
                "description": "테슬라 강세 → 2차전지 수혜",
                "strength":    1.5,
                "value":       3.0,
            },
            {
                "signal_id":   "wti_surge",
                "direction":   "BUY",
                "kr_sectors":  ["정유"],
                "description": "WTI 급등 → 정유주 수혜",
                "strength":    1.2,
                "value":       3.6,
            },
            {
                "signal_id":   "nasdaq_surge",
                "direction":   "BUY",
                "kr_sectors":  ["지수ETF"],
                "description": "나스닥100 급등 → 코스닥 추종",
                "strength":    1.3,
                "value":       2.0,
            },
        ]
        recs = recommender.select_stocks("급등장", signals, 0.9)
        assert len(recs) <= Recommender.MAX_RECOMMENDATIONS, \
            f"추천 종목 수 초과: {len(recs)} > {Recommender.MAX_RECOMMENDATIONS}"

    def test_안정화_buy신호없으면_추천없음(self, recommender):
        """안정화 국면에서 BUY 신호 없으면 추천 없음"""
        recs = recommender.select_stocks("안정화", [], 0.8)
        assert len(recs) == 0, "BUY 신호 없는 안정화에서 추천 없어야 함"


# ---------------------------------------------------------------------------
# 비중 계산 테스트
# ---------------------------------------------------------------------------

class TestCalculateWeight:
    """calculate_weight() 및 추천 비중 합 테스트"""

    def test_weight_합계(self, recommender):
        """모든 추천 종목 weight 합은 1.0 이하여야 한다."""
        signals = [_make_sox_surge_signal(), _make_nvidia_surge_signal()]
        recs = recommender.select_stocks("급등장", signals, 0.9)
        if recs:
            total = sum(r.weight for r in recs)
            assert total <= 1.0 + 1e-6, \
                f"weight 합이 1.0 초과: {total:.4f}"

    def test_급락장_weight_0(self, recommender):
        """급락장에서 calculate_weight는 0.0을 반환해야 한다."""
        weight = recommender.calculate_weight("005930", "반도체", [], "급락장")
        assert weight == 0.0, f"급락장 weight: {weight}"

    def test_변동폭큰_weight_0(self, recommender):
        """변동폭큰에서 calculate_weight는 0.0을 반환해야 한다."""
        weight = recommender.calculate_weight("000660", "반도체", [], "변동폭큰")
        assert weight == 0.0, f"변동폭큰 weight: {weight}"

    def test_급등장_weight_positive(self, recommender):
        """급등장 + BUY 신호 있으면 weight > 0이어야 한다."""
        signals = [_make_sox_surge_signal()]
        weight = recommender.calculate_weight("000660", "반도체", signals, "급등장")
        assert weight > 0.0, f"급등장 weight가 0임: {weight}"


# ---------------------------------------------------------------------------
# 추천 이유 생성 테스트
# ---------------------------------------------------------------------------

class TestGenerateReasons:
    """generate_reasons() 메서드 테스트"""

    def test_이유_생성(self, recommender):
        """reasons 리스트가 비어있지 않아야 한다."""
        signals = [_make_sox_surge_signal()]
        reasons, leading, risks = recommender.generate_reasons(
            "000660", "SK하이닉스", signals, "급등장"
        )
        assert len(reasons) > 0, "reasons가 비어있음"

    def test_이유_내용_확인(self, recommender):
        """SOX 신호가 있으면 reasons에 관련 내용이 포함돼야 한다."""
        signals = [_make_sox_surge_signal()]
        reasons, leading, risks = recommender.generate_reasons(
            "000660", "SK하이닉스", signals, "급등장"
        )
        # reasons 중 하나가 SOX 관련이어야 함
        reason_text = " ".join(reasons)
        assert "SOX" in reason_text or "반도체" in reason_text, \
            f"SOX/반도체 관련 이유 없음: {reasons}"

    def test_리스크_vix_spike(self, recommender):
        """vix_spike AVOID 신호 있을 때 risk_factors에 포함돼야 한다."""
        signals = [_make_vix_spike_signal(32.0), _make_sox_surge_signal()]
        _, _, risks = recommender.generate_reasons(
            "000660", "SK하이닉스", signals, "급등장"
        )
        risk_text = " ".join(risks)
        assert "VIX" in risk_text or "외국인" in risk_text, \
            f"VIX spike 리스크 없음: {risks}"

    def test_leading_indicators_생성(self, recommender):
        """BUY 신호가 있으면 leading_indicators에 포함돼야 한다."""
        signals = [_make_nvidia_surge_signal()]
        _, leading, _ = recommender.generate_reasons(
            "000660", "SK하이닉스", signals, "급등장"
        )
        assert len(leading) > 0, "leading_indicators가 비어있음"


# ---------------------------------------------------------------------------
# 시장 요약 생성 테스트
# ---------------------------------------------------------------------------

class TestGenerateMarketSummary:
    """generate_market_summary() 메서드 테스트"""

    def test_market_summary_생성(self, recommender):
        """summary 문자열이 비어있지 않아야 한다."""
        us = {"vix": {"value": 18.0, "change_pct": 0.5}, "usd_krw": {"value": 1320.0, "change_pct": -0.3}}
        kr = {"kospi": {"value": 2600.0, "change_pct": 0.5, "volume_ratio": 1.1}}
        summary = recommender.generate_market_summary(
            "안정화", 0.8, [], us, kr
        )
        assert isinstance(summary, str), "summary가 문자열이 아님"
        assert len(summary) > 0, "summary가 비어있음"

    def test_market_summary_국면_포함(self, recommender):
        """summary에 국면명이 포함돼야 한다."""
        us = {"vix": {"value": 16.0, "change_pct": -1.0}, "usd_krw": {"value": 1310.0, "change_pct": -0.2}}
        kr = {"kospi": {"value": 2700.0, "change_pct": 2.0, "volume_ratio": 1.8}}
        summary = recommender.generate_market_summary(
            "급등장", 0.9, [_make_sox_surge_signal()], us, kr
        )
        assert "급등장" in summary, f"summary에 국면명 없음: {summary}"

    def test_market_summary_vix_포함(self, recommender):
        """VIX 값이 있으면 summary에 VIX 언급이 있어야 한다."""
        us = {"vix": {"value": 32.0, "change_pct": 10.0}, "usd_krw": {"value": 1360.0, "change_pct": 1.0}}
        kr = {"kospi": {"value": 2450.0, "change_pct": -2.5, "volume_ratio": 2.5}}
        summary = recommender.generate_market_summary(
            "급락장", 0.85, [_make_vix_spike_signal(32.0)], us, kr
        )
        assert "VIX" in summary, f"summary에 VIX 없음: {summary}"


# ---------------------------------------------------------------------------
# execute() 테스트
# ---------------------------------------------------------------------------

class TestExecute:
    """execute() 메서드 테스트"""

    def test_execute_returns_standard_message(self, recommender):
        """execute()가 StandardMessage를 반환해야 한다."""
        msg = _make_market_analysis_message(
            phase="급등장",
            confidence=0.9,
            active_signals=[_make_sox_surge_signal()],
        )
        result = asyncio.run(recommender.execute(msg))
        assert isinstance(result, StandardMessage), \
            f"반환 타입 오류: {type(result)}"

    def test_execute_payload_recommendation_payload(self, recommender):
        """payload가 RecommendationPayload 구조를 만족해야 한다."""
        msg = _make_market_analysis_message(
            phase="급등장",
            confidence=0.85,
            active_signals=[_make_nvidia_surge_signal()],
        )
        result = asyncio.run(recommender.execute(msg))
        payload = result.body.get("payload", {})

        # RecommendationPayload 필드 검증
        assert "phase"            in payload, "phase 키 없음"
        assert "phase_confidence" in payload, "phase_confidence 키 없음"
        assert "recommendations"  in payload, "recommendations 키 없음"
        assert "market_summary"   in payload, "market_summary 키 없음"
        assert "generated_at"     in payload, "generated_at 키 없음"

        # 타입 검증
        assert isinstance(payload["recommendations"], list)
        assert isinstance(payload["market_summary"],  str)
        assert isinstance(payload["phase_confidence"], float)

    def test_execute_data_type(self, recommender):
        """data_type이 RECOMMENDATION이어야 한다."""
        msg = _make_market_analysis_message()
        result = asyncio.run(recommender.execute(msg))
        assert result.body.get("data_type") == "RECOMMENDATION"

    def test_execute_from_agent(self, recommender):
        """from_agent가 RC여야 한다."""
        msg = _make_market_analysis_message()
        result = asyncio.run(recommender.execute(msg))
        assert result.header.from_agent == "RC"

    def test_execute_급락장_빈_추천(self, recommender):
        """급락장에서 execute() 실행 시 recommendations가 빈 리스트여야 한다."""
        msg = _make_market_analysis_message(
            phase="급락장",
            confidence=0.9,
            active_signals=[],
        )
        result = asyncio.run(recommender.execute(msg))
        payload = result.body.get("payload", {})
        assert payload.get("recommendations") == [], \
            f"급락장에서 추천이 있으면 안 됨: {payload.get('recommendations')}"

    def test_execute_recommendations_structure(self, recommender):
        """recommendations 각 항목이 StockRecommendation 구조여야 한다."""
        msg = _make_market_analysis_message(
            phase="급등장",
            confidence=0.9,
            active_signals=[_make_sox_surge_signal()],
        )
        result = asyncio.run(recommender.execute(msg))
        payload = result.body.get("payload", {})
        recs = payload.get("recommendations", [])

        for rec in recs:
            assert "code"               in rec, f"code 키 없음: {rec}"
            assert "name"               in rec, f"name 키 없음: {rec}"
            assert "direction"          in rec, f"direction 키 없음: {rec}"
            assert "weight"             in rec, f"weight 키 없음: {rec}"
            assert "reasons"            in rec, f"reasons 키 없음: {rec}"
            assert "leading_indicators" in rec, f"leading_indicators 키 없음: {rec}"
            assert "risk_factors"       in rec, f"risk_factors 키 없음: {rec}"
            assert 0.0 <= rec["weight"] <= 1.0, f"weight 범위 초과: {rec['weight']}"


# ---------------------------------------------------------------------------
# 신호 강도 / 신뢰도 / 이유 수치 추가 테스트
# ---------------------------------------------------------------------------

class TestSignalStrengthAndConfidence:
    """신호 강도 weight 반영, 신뢰도별 추천 수 차이, 이유 수치 포함 검증"""

    def test_신호_강도_weight_반영(self, recommender):
        """strength가 높은 신호일수록 calculate_weight가 높아야 한다."""
        # strength=1.0 인 sox_surge 신호
        low_signal = {
            "signal_id":   "sox_surge",
            "direction":   "BUY",
            "kr_sectors":  ["반도체"],
            "description": "SOX 급등 → 반도체 수혜",
            "strength":    1.0,
            "value":       2.0,
        }
        # strength=3.0 인 sox_surge 신호
        high_signal = {
            "signal_id":   "sox_surge",
            "direction":   "BUY",
            "kr_sectors":  ["반도체"],
            "description": "SOX 급등 → 반도체 수혜",
            "strength":    3.0,
            "value":       6.0,
        }
        weight_low  = recommender.calculate_weight("000660", "반도체", [low_signal],  "급등장")
        weight_high = recommender.calculate_weight("000660", "반도체", [high_signal], "급등장")

        assert weight_low  > 0.0, f"strength=1.0 weight가 0임: {weight_low}"
        assert weight_high > 0.0, f"strength=3.0 weight가 0임: {weight_high}"
        assert weight_high >= weight_low, \
            f"strength 높을수록 weight가 크거나 같아야 함. low={weight_low}, high={weight_high}"

    def test_confidence_낮을때_추천수_제한(self, recommender):
        """confidence=0.4 → 추천 수가 confidence=0.9보다 적거나 같아야 한다."""
        signals = [
            _make_sox_surge_signal(),
            _make_nvidia_surge_signal(),
            {
                "signal_id":   "tesla_strong",
                "direction":   "BUY",
                "kr_sectors":  ["2차전지"],
                "description": "테슬라 강세 → 2차전지 수혜",
                "strength":    1.5,
                "value":       3.0,
            },
            {
                "signal_id":   "wti_surge",
                "direction":   "BUY",
                "kr_sectors":  ["정유"],
                "description": "WTI 급등 → 정유주 수혜",
                "strength":    1.2,
                "value":       3.6,
            },
        ]
        recs_low_conf  = recommender.select_stocks("급등장", signals, 0.4)
        recs_high_conf = recommender.select_stocks("급등장", signals, 0.9)

        assert len(recs_low_conf) <= len(recs_high_conf), \
            f"낮은 confidence 시 추천 수가 많으면 안 됨. low={len(recs_low_conf)}, high={len(recs_high_conf)}"

    def test_reasons_수치_포함(self, recommender):
        """generate_reasons 결과에 실제 변동률 수치(%)가 포함되어야 한다."""
        # value가 0이 아닌 sox_surge 신호 (반도체 섹터 종목에 적용)
        signal = {
            "signal_id":   "sox_surge",
            "direction":   "BUY",
            "kr_sectors":  ["반도체"],
            "description": "SOX 급등 → 반도체 수혜",
            "strength":    1.9,
            "value":       3.8,  # 0이 아닌 실제 수치
        }
        reasons, leading, risks = recommender.generate_reasons(
            "000660", "SK하이닉스", [signal], "급등장"
        )
        reason_text = " ".join(reasons)
        # value=3.8 이 포함된 수치가 이유에 있어야 함 (변동률: +3.8%)
        assert "%" in reason_text, f"reasons에 % 수치가 없음: {reasons}"
        # 숫자가 포함돼 있어야 함
        has_number = any(char.isdigit() for char in reason_text)
        assert has_number, f"reasons에 숫자가 없음: {reasons}"
