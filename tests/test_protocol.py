"""
protocol.py 단위 테스트
StandardMessage 생성, 직렬화, 순번 증가, 페이로드 dataclass 등을 검증한다.
"""

import re
import pytest
from protocol.protocol import (
    StandardMessage,
    MessageHeader,
    USMarketPayload,
    KRMarketPayload,
    CommodityPayload,
    MarketPhasePayload,
    StockRecommendation,
    RecommendationPayload,
    ErrorPayload,
    dataclass_to_dict,
)


@pytest.fixture(autouse=True)
def reset_protocol_counter():
    import protocol.protocol as proto
    proto._counter = 0
    yield
    proto._counter = 0


# ---------------------------------------------------------------------------
# StandardMessage.create() 기본 동작
# ---------------------------------------------------------------------------

class TestStandardMessageCreate:
    """StandardMessage.create() 정상 동작 테스트"""

    def test_create_returns_standard_message(self):
        """create()가 StandardMessage 인스턴스를 반환해야 한다."""
        msg = StandardMessage.create(
            from_agent="TEST_AGENT",
            to_agent="TARGET_AGENT",
            data_type="TEST_DATA",
            payload={"key": "value"},
        )
        assert isinstance(msg, StandardMessage)

    def test_create_header_fields(self):
        """헤더의 from_agent, to_agent, priority, msg_type이 올바르게 설정된다."""
        msg = StandardMessage.create(
            from_agent="SENDER",
            to_agent="RECEIVER",
            data_type="MY_TYPE",
            payload={},
            priority="HIGH",
            msg_type="SIGNAL",
        )
        assert msg.header.from_agent == "SENDER"
        assert msg.header.to_agent == "RECEIVER"
        assert msg.header.priority == "HIGH"
        assert msg.header.msg_type == "SIGNAL"
        assert msg.header.version == "1.0"

    def test_create_body_structure(self):
        """body에 data_type과 payload 키가 존재해야 한다."""
        payload = {"amount": 100}
        msg = StandardMessage.create(
            from_agent="A",
            to_agent="B",
            data_type="ORDER_DATA",
            payload=payload,
        )
        assert "data_type" in msg.body
        assert "payload" in msg.body
        assert msg.body["data_type"] == "ORDER_DATA"
        assert msg.body["payload"]["amount"] == 100

    def test_create_status_default_ok(self):
        """생성 직후 status.code는 'OK'여야 한다."""
        msg = StandardMessage.create("A", "B", "TYPE", {})
        assert msg.status["code"] == "OK"

    def test_create_with_dataclass_payload(self):
        """dataclass 페이로드도 dict로 직렬화되어 저장되어야 한다."""
        payload = USMarketPayload(
            nasdaq={"value": 18000.0, "change_pct": 0.5, "volume_ratio": 1.2},
            sox={"value": 5000.0, "change_pct": -0.3, "volume_ratio": 0.9},
            sp500={"value": 5800.0, "change_pct": 0.2, "volume_ratio": 1.0},
            vix={"value": 16.5, "change_pct": -2.0},
            usd_krw={"value": 1330.0, "change_pct": 0.1},
            futures={"value": 18010.0, "direction": "UP"},
        )
        msg = StandardMessage.create("US_COLLECTOR", "KR_ANALYZER", "US_MARKET_DATA", payload)
        # payload가 dict 형태로 변환되어야 함
        p = msg.body["payload"]
        assert isinstance(p, dict)
        assert "nasdaq" in p
        assert p["vix"]["value"] == 16.5


# ---------------------------------------------------------------------------
# msg_id 형식 검증
# ---------------------------------------------------------------------------

class TestMsgIdFormat:
    """msg_id 자동 생성 형식 검증"""

    MSG_ID_PATTERN = re.compile(r"^\w+_\d{8}_\d{6}_\d{4}$")

    def test_msg_id_matches_pattern(self):
        """msg_id가 {agent_code}_{YYYYMMDD}_{HHMMSS}_{순번:04d} 형식이어야 한다."""
        msg = StandardMessage.create("MY_AGENT", "OTHER", "DATA", {})
        assert self.MSG_ID_PATTERN.match(msg.header.msg_id), (
            f"msg_id 형식 불일치: {msg.header.msg_id}"
        )

    def test_msg_id_starts_with_agent_code(self):
        """msg_id 앞부분이 from_agent 코드로 시작해야 한다."""
        msg = StandardMessage.create("AGENT_XYZ", "OTHER", "DATA", {})
        assert msg.header.msg_id.startswith("AGENT_XYZ_")

    def test_timestamp_is_iso8601(self):
        """timestamp가 ISO 8601 형식이어야 한다 ('+' 또는 'Z' 포함)."""
        msg = StandardMessage.create("A", "B", "T", {})
        ts = msg.header.timestamp
        # ISO 8601: 날짜T시간+오프셋 형식 확인
        assert "T" in ts, f"타임스탬프 ISO 8601 형식 불일치: {ts}"


# ---------------------------------------------------------------------------
# to_dict() / from_dict() 왕복 변환
# ---------------------------------------------------------------------------

class TestSerialization:
    """직렬화/역직렬화 왕복 테스트"""

    def _make_msg(self) -> StandardMessage:
        return StandardMessage.create(
            from_agent="SERIALIZER",
            to_agent="DESERIALIZER",
            data_type="ROUND_TRIP",
            payload={"items": [1, 2, 3], "meta": {"ok": True}},
            priority="LOW",
            msg_type="RESPONSE",
        )

    def test_to_dict_returns_dict(self):
        """to_dict()가 dict를 반환해야 한다."""
        msg = self._make_msg()
        d = msg.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_has_required_keys(self):
        """직렬화된 dict에 header, body, status 키가 있어야 한다."""
        d = self._make_msg().to_dict()
        assert "header" in d
        assert "body" in d
        assert "status" in d

    def test_from_dict_reconstructs_message(self):
        """from_dict()로 복원한 메시지의 필드가 원본과 일치해야 한다."""
        original = self._make_msg()
        d = original.to_dict()
        restored = StandardMessage.from_dict(d)

        assert restored.header.from_agent == original.header.from_agent
        assert restored.header.to_agent == original.header.to_agent
        assert restored.header.msg_id == original.header.msg_id
        assert restored.header.timestamp == original.header.timestamp
        assert restored.header.priority == original.header.priority
        assert restored.header.msg_type == original.header.msg_type
        assert restored.body == original.body
        assert restored.status == original.status

    def test_round_trip_preserves_payload(self):
        """왕복 변환 후 payload 내용이 보존되어야 한다."""
        original = self._make_msg()
        restored = StandardMessage.from_dict(original.to_dict())
        assert restored.body["payload"]["items"] == [1, 2, 3]
        assert restored.body["payload"]["meta"]["ok"] is True


# ---------------------------------------------------------------------------
# 순번 자동 증가
# ---------------------------------------------------------------------------

class TestCounterIncrement:
    """msg_id 순번 자동 증가 테스트"""

    def test_sequential_messages_have_increasing_counter(self):
        """연속 생성된 메시지의 순번이 순차적으로 증가해야 한다."""
        msgs = [
            StandardMessage.create("COUNTER_AGENT", "OTHER", "DATA", {})
            for _ in range(5)
        ]
        # msg_id에서 순번(마지막 4자리 숫자) 추출
        counters = [int(m.header.msg_id.split("_")[-1]) for m in msgs]
        # 순번이 순차적으로 증가해야 함 (연속이 아닐 수 있으나 단조 증가는 보장)
        for i in range(1, len(counters)):
            assert counters[i] > counters[i - 1], (
                f"순번이 감소했습니다: {counters[i-1]} -> {counters[i]}"
            )

    def test_counter_is_four_digits_zero_padded(self):
        """순번은 4자리 0-패딩이어야 한다."""
        msg = StandardMessage.create("PAD_AGENT", "X", "Y", {})
        counter_part = msg.header.msg_id.split("_")[-1]
        assert len(counter_part) == 4, f"순번 자릿수 불일치: {counter_part}"
        assert counter_part.isdigit(), f"순번이 숫자가 아닙니다: {counter_part}"


# ---------------------------------------------------------------------------
# 페이로드 dataclass 생성 테스트
# ---------------------------------------------------------------------------

class TestPayloadDataclasses:
    """각 페이로드 dataclass 생성 및 기본 필드 확인"""

    def test_us_market_payload(self):
        """USMarketPayload 정상 생성"""
        p = USMarketPayload(
            nasdaq={"value": 18000.0, "change_pct": 0.5, "volume_ratio": 1.2},
            sox={"value": 4900.0, "change_pct": -1.0, "volume_ratio": 0.8},
            sp500={"value": 5700.0, "change_pct": 0.1, "volume_ratio": 1.0},
            vix={"value": 20.0, "change_pct": 5.0},
            usd_krw={"value": 1350.0, "change_pct": 0.3},
            futures={"value": 18050.0, "direction": "UP"},
        )
        assert p.nasdaq["value"] == 18000.0
        assert p.futures["direction"] == "UP"

    def test_kr_market_payload_defaults(self):
        """KRMarketPayload 기본값 확인"""
        p = KRMarketPayload(
            kospi={"value": 2600.0, "change_pct": 0.5},
            kosdaq={"value": 850.0, "change_pct": -0.2},
        )
        assert p.foreign_net == 0
        assert p.institution_net == 0
        assert p.stocks == {}

    def test_commodity_payload(self):
        """CommodityPayload 정상 생성"""
        p = CommodityPayload(
            wti={"value": 80.5, "change_pct": -1.2},
            gold={"value": 2300.0, "change_pct": 0.8},
            copper={"value": 4.5, "change_pct": 0.3},
            lithium={"value": 15000.0, "change_pct": -2.0},
        )
        assert p.wti["value"] == 80.5
        assert p.gold["value"] == 2300.0

    def test_market_phase_payload_defaults(self):
        """MarketPhasePayload 기본값 확인"""
        p = MarketPhasePayload(phase="안정화", confidence=0.85)
        assert p.elapsed_days == 0
        assert p.forecast == {}
        assert p.strategy_timeline == {}

    def test_stock_recommendation(self):
        """StockRecommendation 생성 및 기본값 확인"""
        rec = StockRecommendation(
            code="005930",
            name="삼성전자",
            direction="BUY",
            weight=0.3,
            reasons=["반도체 업황 개선", "낮은 밸류에이션"],
        )
        assert rec.code == "005930"
        assert rec.direction == "BUY"
        assert len(rec.reasons) == 2
        assert rec.leading_indicators == []
        assert rec.risk_factors == []

    def test_recommendation_payload(self):
        """RecommendationPayload 생성"""
        from datetime import datetime, timezone
        rec = StockRecommendation(
            code="000660", name="SK하이닉스", direction="BUY", weight=0.25
        )
        p = RecommendationPayload(
            phase="급등장",
            phase_confidence=0.78,
            recommendations=[rec],
            market_summary="반도체 섹터 강세",
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        assert p.phase == "급등장"
        assert len(p.recommendations) == 1

    def test_error_payload_defaults(self):
        """ErrorPayload 기본값 확인"""
        p = ErrorPayload(
            error_id="err-001",
            level="MEDIUM",
            from_agent="TEST_AGENT",
            error_code="TIMEOUT",
            message="연결 시간 초과",
        )
        assert p.retry_count == 0
        assert p.auto_fix is False
        assert p.action == ""

    def test_dataclass_to_dict_nested(self):
        """dataclass_to_dict()가 중첩 dataclass를 올바르게 처리해야 한다."""
        rec = StockRecommendation(
            code="035720", name="카카오", direction="HOLD", weight=0.1
        )
        p = RecommendationPayload(
            phase="변동폭큰",
            phase_confidence=0.6,
            recommendations=[rec],
            market_summary="불확실성 확대",
            generated_at="2026-03-28T00:00:00+00:00",
        )
        result = dataclass_to_dict(p)
        assert isinstance(result, dict)
        assert result["phase"] == "변동폭큰"
        # recommendations 내부도 dict로 변환되어야 함
        assert isinstance(result["recommendations"][0], dict)
        assert result["recommendations"][0]["code"] == "035720"
