"""
Preprocessor 단위 테스트
DataCollector의 출력을 mock으로 만들어 전처리 로직을 검증한다.
"""

import asyncio
import math
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from agents.preprocessor import Preprocessor
from protocol.protocol import (
    StandardMessage,
    USMarketPayload,
    KRMarketPayload,
    CommodityPayload,
    dataclass_to_dict,
)


# ---------------------------------------------------------------------------
# 테스트용 raw 데이터 팩토리
# ---------------------------------------------------------------------------

def make_raw_us(nasdaq_change=1.5, sox_change=2.0, sp500_change=1.0,
                vix_change=0.5, usd_krw_change=0.3, futures_dir="UP",
                nvda_change=3.0) -> dict:
    """테스트용 미국 시장 raw dict 생성."""
    return {
        "nasdaq":  {"value": 18000.0, "change_pct": nasdaq_change, "volume_ratio": 1.2},
        "sox":     {"value": 5000.0,  "change_pct": sox_change,    "volume_ratio": 1.1},
        "sp500":   {"value": 5200.0,  "change_pct": sp500_change,  "volume_ratio": 1.0},
        "vix":     {"value": 20.5,    "change_pct": vix_change},
        "usd_krw": {"value": 1350.0,  "change_pct": usd_krw_change},
        "futures": {"value": 18100.0, "direction":  futures_dir},
        "individual": {
            "NVDA": {"value": 850.0,  "change_pct": nvda_change},
            "AMD":  {"value": 160.0,  "change_pct": 1.5},
            "TSLA": {"value": 200.0,  "change_pct": -0.5},
        },
    }


def make_raw_kr(kospi_change=0.8, kosdaq_change=1.2) -> dict:
    """테스트용 한국 시장 raw dict 생성."""
    return {
        "kospi":           {"value": 2700.0, "change_pct": kospi_change,  "volume_ratio": 1.05},
        "kosdaq":          {"value": 880.0,  "change_pct": kosdaq_change, "volume_ratio": 0.95},
        "foreign_net":     500,
        "institution_net": -200,
        "stocks": {
            "005930": {"name": "삼성전자",        "price": 72000,  "change_pct": 1.4},
            "000660": {"name": "SK하이닉스",       "price": 185000, "change_pct": 2.1},
            "042700": {"name": "한미반도체",        "price": 95000,  "change_pct": -0.5},
            "373220": {"name": "LG에너지솔루션",    "price": 380000, "change_pct": 0.8},
        },
    }


def make_raw_commodities(wti_change=1.0, gold_change=-0.5) -> dict:
    """테스트용 원자재 raw dict 생성."""
    return {
        "wti":     {"value": 78.5,   "change_pct": wti_change},
        "gold":    {"value": 2050.0, "change_pct": gold_change},
        "copper":  {"value": 4.2,    "change_pct": 0.3},
        "lithium": {"value": 22.5,   "change_pct": -1.2},
    }


def make_raw_market_message(
    us_change=1.5, kr_change=0.8, wti_change=1.0
) -> StandardMessage:
    """DataCollector 출력을 흉내 낸 StandardMessage 생성."""
    payload = {
        "us_market":   make_raw_us(nasdaq_change=us_change),
        "kr_market":   make_raw_kr(kospi_change=kr_change),
        "commodities": make_raw_commodities(wti_change=wti_change),
    }
    return StandardMessage.create(
        from_agent="DC",
        to_agent="PP",
        data_type="RAW_MARKET_DATA",
        payload=payload,
    )


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture
def preprocessor():
    return Preprocessor()


# ---------------------------------------------------------------------------
# 1. raw us_market dict → USMarketPayload 변환
# ---------------------------------------------------------------------------

def test_to_us_market_payload(preprocessor):
    """raw us_market dict를 USMarketPayload로 올바르게 변환하는지 검증한다."""
    raw = make_raw_us()
    result = preprocessor._to_us_market(raw)

    assert isinstance(result, USMarketPayload)
    assert result.nasdaq["value"]      == pytest.approx(18000.0, abs=0.01)
    assert result.nasdaq["change_pct"] == pytest.approx(1.5,     abs=0.01)
    assert result.vix["value"]         == pytest.approx(20.5,    abs=0.01)
    assert result.futures["direction"] == "UP"


# ---------------------------------------------------------------------------
# 2. raw kr_market dict → KRMarketPayload 변환
# ---------------------------------------------------------------------------

def test_to_kr_market_payload(preprocessor):
    """raw kr_market dict를 KRMarketPayload로 올바르게 변환하는지 검증한다."""
    raw = make_raw_kr()
    result = preprocessor._to_kr_market(raw)

    assert isinstance(result, KRMarketPayload)
    assert result.kospi["value"]         == pytest.approx(2700.0, abs=0.01)
    assert result.kospi["change_pct"]    == pytest.approx(0.8,    abs=0.01)
    assert result.foreign_net            == 500
    assert result.institution_net        == -200
    assert "005930" in result.stocks
    assert result.stocks["005930"]["name"]  == "삼성전자"
    assert result.stocks["005930"]["price"] == 72000


# ---------------------------------------------------------------------------
# 3. raw commodities dict → CommodityPayload 변환
# ---------------------------------------------------------------------------

def test_to_commodity_payload(preprocessor):
    """raw commodities dict를 CommodityPayload로 올바르게 변환하는지 검증한다."""
    raw = make_raw_commodities()
    result = preprocessor._to_commodity(raw)

    assert isinstance(result, CommodityPayload)
    assert result.wti["value"]         == pytest.approx(78.5,   abs=0.01)
    assert result.gold["change_pct"]   == pytest.approx(-0.5,   abs=0.01)
    assert result.copper["value"]      == pytest.approx(4.2,    abs=0.01)
    assert result.lithium["value"]     == pytest.approx(22.5,   abs=0.01)


# ---------------------------------------------------------------------------
# 4. 정상 change_pct → 이상값 플래그 없음
# ---------------------------------------------------------------------------

def test_anomaly_detection_normal(preprocessor):
    """모든 change_pct 가 ±15% 이내이면 이상값 목록이 비어야 한다."""
    data = {
        "us_market":   make_raw_us(nasdaq_change=1.5),
        "kr_market":   make_raw_kr(kospi_change=0.8),
        "commodities": make_raw_commodities(wti_change=1.0),
    }
    anomalies = preprocessor._check_anomalies(data)
    assert len(anomalies) == 0


# ---------------------------------------------------------------------------
# 5. ±15% 초과 → 이상값 플래그 있음
# ---------------------------------------------------------------------------

def test_anomaly_detection_spike(preprocessor):
    """change_pct 가 ±15% 를 초과하면 anomaly 목록에 추가되어야 한다."""
    data = {
        "us_market":   make_raw_us(nasdaq_change=18.5),   # +18.5% → 초과
        "kr_market":   make_raw_kr(kospi_change=-16.0),   # -16.0% → 초과
        "commodities": make_raw_commodities(wti_change=1.0),
    }
    anomalies = preprocessor._check_anomalies(data)

    flagged_fields = [a["field"] for a in anomalies]
    assert "nasdaq.change_pct" in flagged_fields
    assert "kospi.change_pct"  in flagged_fields
    assert all(a["flagged"] for a in anomalies)


# ---------------------------------------------------------------------------
# 6. _handle_missing: None → 0.0
# ---------------------------------------------------------------------------

def test_handle_missing_none(preprocessor):
    """None 을 기본값 0.0으로 대체해야 한다."""
    assert preprocessor._handle_missing(None) == 0.0


# ---------------------------------------------------------------------------
# 7. _handle_missing: float('nan') → 0.0
# ---------------------------------------------------------------------------

def test_handle_missing_nan(preprocessor):
    """NaN 을 기본값 0.0으로 대체해야 한다."""
    assert preprocessor._handle_missing(float("nan")) == 0.0


# ---------------------------------------------------------------------------
# 8. _handle_missing: float('inf') → 0.0
# ---------------------------------------------------------------------------

def test_handle_missing_inf(preprocessor):
    """inf 를 기본값 0.0으로 대체해야 한다."""
    assert preprocessor._handle_missing(float("inf"))  == 0.0
    assert preprocessor._handle_missing(float("-inf")) == 0.0


# ---------------------------------------------------------------------------
# 9. execute() 전체 파이프라인 (DataCollector 출력 → Preprocessor → 3개 페이로드)
# ---------------------------------------------------------------------------

def test_execute_full_pipeline(preprocessor):
    """
    DataCollector 출력 형식의 StandardMessage 를 입력으로 받아
    us_market, kr_market, commodities 3개 페이로드가 생성되는지 검증한다.
    """
    input_msg = make_raw_market_message()
    result    = asyncio.run(preprocessor.execute(input_msg))

    assert isinstance(result, StandardMessage)
    payload = result.body["payload"]

    assert "us_market"   in payload
    assert "kr_market"   in payload
    assert "commodities" in payload
    assert "anomalies"   in payload

    # 각 페이로드 내부 키 검증
    assert "nasdaq" in payload["us_market"]
    assert "kospi"  in payload["kr_market"]
    assert "wti"    in payload["commodities"]


# ---------------------------------------------------------------------------
# 10. execute() 반환값이 StandardMessage 인지 확인
# ---------------------------------------------------------------------------

def test_execute_returns_standard_message(preprocessor):
    """execute()가 StandardMessage 인스턴스를 반환해야 한다."""
    input_msg = make_raw_market_message()
    result    = asyncio.run(preprocessor.execute(input_msg))

    assert isinstance(result, StandardMessage)
    assert result.body["data_type"] == "PREPROCESSED_DATA"
    assert result.status["code"]    == "OK"
