"""
DataCollector 단위 테스트
실제 API 호출 없이 Mock을 사용하여 빠르고 안정적으로 검증한다.
yfinance / pykrx 미설치 환경에서도 동작하도록 sys.modules 에 mock을 주입한다.
"""

import asyncio
import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# yfinance / pykrx 미설치 환경 대비: sys.modules 에 mock 모듈 삽입
# ---------------------------------------------------------------------------

# yfinance mock 모듈 생성
_mock_yfinance = MagicMock()
sys.modules.setdefault("yfinance", _mock_yfinance)

# pykrx mock 모듈 생성
_mock_pykrx        = MagicMock()
_mock_pykrx_stock  = MagicMock()
sys.modules.setdefault("pykrx",       _mock_pykrx)
sys.modules.setdefault("pykrx.stock", _mock_pykrx_stock)
# pykrx.stock 을 pykrx.stock 속성으로도 접근 가능하게
_mock_pykrx.stock  = _mock_pykrx_stock

# data_collector 임포트는 mock 주입 이후에 수행해야 한다.
from agents.data_collector import DataCollector  # noqa: E402
from protocol.protocol import StandardMessage     # noqa: E402


# ---------------------------------------------------------------------------
# 테스트용 헬퍼
# ---------------------------------------------------------------------------

def make_mock_history(prices: list, volumes: list = None) -> pd.DataFrame:
    """테스트용 가짜 yfinance history DataFrame 생성."""
    dates = pd.date_range(end=pd.Timestamp.now(), periods=len(prices), freq="B")
    df = pd.DataFrame(
        {
            "Close":  prices,
            "Volume": volumes or [1_000_000] * len(prices),
            "Open":   prices,
            "High":   [p * 1.01 for p in prices],
            "Low":    [p * 0.99 for p in prices],
        },
        index=dates,
    )
    return df


def make_mock_kr_index(closes: list, volumes: list = None) -> pd.DataFrame:
    """테스트용 가짜 pykrx 지수 DataFrame 생성 (종가, 거래량 컬럼)."""
    dates = pd.date_range(end=pd.Timestamp.now(), periods=len(closes), freq="B")
    df = pd.DataFrame(
        {
            "종가":   closes,
            "거래량":  volumes or [500_000] * len(closes),
            "시가":   closes,
            "고가":   [c * 1.01 for c in closes],
            "저가":   [c * 0.99 for c in closes],
        },
        index=dates,
    )
    return df


def make_mock_kr_stock(closes: list) -> pd.DataFrame:
    """테스트용 가짜 pykrx 개별 종목 DataFrame 생성."""
    dates = pd.date_range(end=pd.Timestamp.now(), periods=len(closes), freq="B")
    df = pd.DataFrame(
        {
            "종가":   closes,
            "시가":   closes,
            "고가":   [c * 1.01 for c in closes],
            "저가":   [c * 0.99 for c in closes],
            "거래량":  [1_000_000] * len(closes),
        },
        index=dates,
    )
    return df


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture
def collector():
    return DataCollector()


# ---------------------------------------------------------------------------
# 헬퍼: yfinance Ticker mock을 설정하는 컨텍스트 매니저 대용
# ---------------------------------------------------------------------------

def _set_yf_ticker(mock_hist: pd.DataFrame):
    """sys.modules["yfinance"].Ticker 가 mock_hist 를 반환하도록 설정."""
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = mock_hist
    sys.modules["yfinance"].Ticker.return_value = mock_ticker
    return mock_ticker


def _set_kr_mocks(index_df: pd.DataFrame, stock_df: pd.DataFrame):
    """pykrx.stock 함수들이 지정 DataFrame을 반환하도록 설정."""
    sys.modules["pykrx.stock"].get_index_ohlcv_by_date.return_value  = index_df
    sys.modules["pykrx.stock"].get_market_ohlcv_by_date.return_value = stock_df
    # pykrx.stock 속성 경로도 동기화
    _mock_pykrx.stock.get_index_ohlcv_by_date.return_value  = index_df
    _mock_pykrx.stock.get_market_ohlcv_by_date.return_value = stock_df


# ---------------------------------------------------------------------------
# 1. 정상 미국 시장 수집
# ---------------------------------------------------------------------------

def test_collect_us_market_normal(collector):
    """정상 데이터가 주어졌을 때 us_market 구조가 올바른지 검증한다."""
    prices  = [100.0 + i for i in range(22)]
    volumes = [1_000_000 + i * 10_000 for i in range(22)]
    _set_yf_ticker(make_mock_history(prices, volumes))

    result = collector._collect_us_market_sync()

    assert "nasdaq"     in result
    assert "sox"        in result
    assert "sp500"      in result
    assert "vix"        in result
    assert "usd_krw"    in result
    assert "futures"    in result
    assert "individual" in result

    # 지수 필드 검증
    assert "value"        in result["nasdaq"]
    assert "change_pct"   in result["nasdaq"]
    assert "volume_ratio" in result["nasdaq"]

    # 개별 종목 필드 검증
    for ticker in ["NVDA", "AMD", "TSLA"]:
        assert ticker in result["individual"]
        assert "value"      in result["individual"][ticker]
        assert "change_pct" in result["individual"][ticker]


# ---------------------------------------------------------------------------
# 2. yfinance 예외 시 기본값 반환
# ---------------------------------------------------------------------------

def test_collect_us_market_yfinance_error(collector):
    """yfinance에서 예외가 발생해도 기본값 dict가 반환되어야 한다."""
    sys.modules["yfinance"].Ticker.side_effect = RuntimeError("네트워크 오류")

    result = collector._collect_us_market_sync()

    # side_effect 초기화 (다른 테스트에 영향 없도록)
    sys.modules["yfinance"].Ticker.side_effect = None

    assert "nasdaq"  in result
    assert "futures" in result
    assert result["nasdaq"]["value"] == 0.0


# ---------------------------------------------------------------------------
# 3. change_pct 계산 정확성
# ---------------------------------------------------------------------------

def test_us_change_pct_calculation(collector):
    """전일 종가 100 → 당일 종가 105 이면 change_pct = 5.0 이어야 한다."""
    _set_yf_ticker(make_mock_history([100.0, 105.0]))

    result = collector._collect_us_market_sync()

    assert result["nasdaq"]["change_pct"] == pytest.approx(5.0, abs=0.01)


# ---------------------------------------------------------------------------
# 4. volume_ratio 계산
# ---------------------------------------------------------------------------

def test_us_volume_ratio_calculation(collector):
    """당일 거래량=2_000_000, 이전 20일 평균=1_000_000 이면 ratio=2.0 이어야 한다."""
    prices  = [100.0] * 22
    volumes = [1_000_000] * 21 + [2_000_000]
    _set_yf_ticker(make_mock_history(prices, volumes))

    result = collector._collect_us_market_sync()

    assert result["nasdaq"]["volume_ratio"] == pytest.approx(2.0, abs=0.1)


# ---------------------------------------------------------------------------
# 5. futures direction = UP
# ---------------------------------------------------------------------------

def test_futures_direction_up(collector):
    """change_pct > 0.3 이면 direction = 'UP' 이어야 한다."""
    _set_yf_ticker(make_mock_history([100.0, 100.5]))  # +0.5%

    result = collector._collect_us_market_sync()

    assert result["futures"]["direction"] == "UP"


# ---------------------------------------------------------------------------
# 6. futures direction = DOWN
# ---------------------------------------------------------------------------

def test_futures_direction_down(collector):
    """change_pct < -0.3 이면 direction = 'DOWN' 이어야 한다."""
    _set_yf_ticker(make_mock_history([100.0, 99.5]))  # -0.5%

    result = collector._collect_us_market_sync()

    assert result["futures"]["direction"] == "DOWN"


# ---------------------------------------------------------------------------
# 7. futures direction = FLAT
# ---------------------------------------------------------------------------

def test_futures_direction_flat(collector):
    """change_pct 가 -0.3 ~ 0.3 사이이면 direction = 'FLAT' 이어야 한다."""
    _set_yf_ticker(make_mock_history([100.0, 100.2]))  # +0.2%

    result = collector._collect_us_market_sync()

    assert result["futures"]["direction"] == "FLAT"


# ---------------------------------------------------------------------------
# 8. 한국 시장 정상 수집 (pykrx mock)
# ---------------------------------------------------------------------------

def test_collect_kr_market_normal(collector):
    """pykrx mock을 사용하여 한국 시장 데이터 구조를 검증한다."""
    index_df = make_mock_kr_index([2500.0 + i for i in range(22)], [500_000] * 22)
    stock_df = make_mock_kr_stock([70000.0, 71000.0])
    _set_kr_mocks(index_df, stock_df)

    result = collector._collect_kr_market_sync()

    assert "kospi"           in result
    assert "kosdaq"          in result
    assert "foreign_net"     in result
    assert "institution_net" in result
    assert "stocks"          in result

    assert result["kospi"]["value"] > 0
    assert "005930" in result["stocks"]
    assert result["stocks"]["005930"]["name"] == "삼성전자"


# ---------------------------------------------------------------------------
# 9. 원자재 정상 수집
# ---------------------------------------------------------------------------

def test_collect_commodities_normal(collector):
    """원자재 데이터 구조와 값이 올바른지 검증한다."""
    _set_yf_ticker(make_mock_history([80.0, 81.0]))

    result = collector._collect_commodities_sync()

    for key in ["wti", "gold", "copper", "lithium"]:
        assert key in result
        assert "value"      in result[key]
        assert "change_pct" in result[key]
        assert result[key]["value"] == pytest.approx(81.0, abs=0.01)


# ---------------------------------------------------------------------------
# 10. execute() 반환값이 StandardMessage 인지 확인
# ---------------------------------------------------------------------------

def test_execute_returns_standard_message(collector):
    """execute()가 StandardMessage를 반환해야 한다."""
    _set_yf_ticker(make_mock_history([100.0] * 22, [1_000_000] * 22))
    _set_kr_mocks(
        make_mock_kr_index([2500.0] * 22),
        make_mock_kr_stock([70000.0, 71000.0]),
    )

    result = asyncio.run(collector.execute())

    assert isinstance(result, StandardMessage)


# ---------------------------------------------------------------------------
# 11. execute() payload 구조 검증
# ---------------------------------------------------------------------------

def test_execute_payload_structure(collector):
    """execute() 반환 payload에 us_market, kr_market, commodities 키가 있어야 한다."""
    _set_yf_ticker(make_mock_history([100.0] * 22, [1_000_000] * 22))
    _set_kr_mocks(
        make_mock_kr_index([2500.0] * 22),
        make_mock_kr_stock([70000.0, 71000.0]),
    )

    result  = asyncio.run(collector.execute())
    payload = result.body["payload"]

    assert "us_market"   in payload
    assert "kr_market"   in payload
    assert "commodities" in payload


# ---------------------------------------------------------------------------
# 12. _safe_change_pct 제로 나누기 방지
# ---------------------------------------------------------------------------

def test_safe_change_pct_zero_division(collector):
    """전일 종가가 0일 때 _safe_change_pct 는 0.0을 반환해야 한다."""
    assert collector._safe_change_pct(100.0, 0.0)  == 0.0
    assert collector._safe_change_pct(100.0, None) == 0.0
