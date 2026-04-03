"""
전처리 에이전트 모듈
DataCollector가 반환한 raw dict를 protocol.py의 표준 페이로드 dataclass로 변환한다.
이상값(anomaly) 탐지 및 결측값 처리를 함께 수행한다.
"""

import math

from agents.base_agent import BaseAgent
from protocol.protocol import (
    StandardMessage,
    USMarketPayload,
    KRMarketPayload,
    CommodityPayload,
    dataclass_to_dict,
)


class Preprocessor(BaseAgent):
    """DataCollector의 raw dict를 표준 페이로드로 변환하는 에이전트."""

    # 전일 대비 ±15% 초과 시 이상값 플래그
    ANOMALY_THRESHOLD = 15.0

    def __init__(self):
        super().__init__("PP", "전처리", timeout=1, max_retries=3)

    # ------------------------------------------------------------------
    # 공개 인터페이스
    # ------------------------------------------------------------------

    async def execute(self, input_data: StandardMessage) -> StandardMessage:
        """
        RAW_MARKET_DATA → PREPROCESSED_DATA 변환.
        body.payload = {
            "us_market":   USMarketPayload(...)를 dict로,
            "kr_market":   KRMarketPayload(...)를 dict로,
            "commodities": CommodityPayload(...)를 dict로,
            "anomalies":   [{"field": str, "value": float, "flagged": bool}, ...]
        }
        """
        self.log("info", "전처리 시작")

        raw_payload = input_data.body.get("payload", {})
        raw_us          = raw_payload.get("us_market",   {})
        raw_kr          = raw_payload.get("kr_market",   {})
        raw_commodities = raw_payload.get("commodities", {})

        # --- 페이로드 변환 ---
        us_payload   = self._to_us_market(raw_us)
        kr_payload   = self._to_kr_market(raw_kr)
        comm_payload = self._to_commodity(raw_commodities)

        # --- 이상값 탐지 ---
        anomalies = self._check_anomalies(raw_payload)

        payload = {
            "us_market":   dataclass_to_dict(us_payload),
            "kr_market":   dataclass_to_dict(kr_payload),
            "commodities": dataclass_to_dict(comm_payload),
            "anomalies":   anomalies,
        }

        self.log("info", f"전처리 완료 (이상값 {len(anomalies)}건)")
        return self.create_message(
            to="OR",
            data_type="PREPROCESSED_DATA",
            payload=payload,
        )

    # ------------------------------------------------------------------
    # 변환 메서드
    # ------------------------------------------------------------------

    def _to_us_market(self, raw: dict) -> USMarketPayload:
        """raw us_market dict → USMarketPayload"""
        def _index(key: str) -> dict:
            """지수 딕셔너리 안전 추출 (volume_ratio 포함)."""
            d = raw.get(key, {})
            return {
                "value":        self._round(d.get("value")),
                "change_pct":   self._round(d.get("change_pct")),
                "volume_ratio": self._round(d.get("volume_ratio", 1.0)),
            }

        def _simple(key: str) -> dict:
            """value + change_pct만 있는 딕셔너리 안전 추출."""
            d = raw.get(key, {})
            return {
                "value":      self._round(d.get("value")),
                "change_pct": self._round(d.get("change_pct")),
            }

        # 선물(futures): direction 필드 처리
        raw_futures = raw.get("futures", {})
        futures = {
            "value":     self._round(raw_futures.get("value")),
            "direction": raw_futures.get("direction", "FLAT"),
        }

        # 개별 종목
        raw_individual = raw.get("individual", {})
        individual = {}
        for ticker in ["NVDA", "AMD", "TSLA"]:
            d = raw_individual.get(ticker, {})
            individual[ticker] = {
                "value":      self._round(d.get("value")),
                "change_pct": self._round(d.get("change_pct")),
            }

        return USMarketPayload(
            nasdaq=_index("nasdaq"),
            sox=_index("sox"),
            sp500=_index("sp500"),
            vix=_simple("vix"),
            usd_krw=_simple("usd_krw"),
            futures=futures,
            individual=individual,
        )

    def _to_kr_market(self, raw: dict) -> KRMarketPayload:
        """raw kr_market dict → KRMarketPayload"""
        def _index(key: str) -> dict:
            d = raw.get(key, {})
            return {
                "value":        self._round(d.get("value")),
                "change_pct":   self._round(d.get("change_pct")),
                "volume_ratio": self._round(d.get("volume_ratio", 1.0)),
            }

        # 개별 종목 정리
        raw_stocks = raw.get("stocks", {})
        stocks = {}
        for code, info in raw_stocks.items():
            stocks[code] = {
                "name":       info.get("name", ""),
                "price":      int(self._handle_missing(info.get("price"), 0)),
                "change_pct": self._round(info.get("change_pct")),
            }

        return KRMarketPayload(
            kospi=_index("kospi"),
            kosdaq=_index("kosdaq"),
            foreign_net=int(self._handle_missing(raw.get("foreign_net"), 0)),
            institution_net=int(self._handle_missing(raw.get("institution_net"), 0)),
            stocks=stocks,
            stock_foreign_net=raw.get("stock_foreign_net", {}),
        )

    def _to_commodity(self, raw: dict) -> CommodityPayload:
        """raw commodities dict → CommodityPayload"""
        def _commodity(key: str) -> dict:
            d = raw.get(key, {})
            return {
                "value":      self._round(d.get("value")),
                "change_pct": self._round(d.get("change_pct")),
            }

        return CommodityPayload(
            wti=_commodity("wti"),
            gold=_commodity("gold"),
            copper=_commodity("copper"),
            lithium=_commodity("lithium"),
        )

    # ------------------------------------------------------------------
    # 이상값 탐지
    # ------------------------------------------------------------------

    def _check_anomalies(self, data: dict) -> list:
        """
        change_pct 값이 ±ANOMALY_THRESHOLD를 초과하면 anomaly 플래그를 설정한다.
        반환: [{"field": str, "value": float, "flagged": bool}]
        """
        anomalies = []

        # 탐지 대상 경로: (필드명, 딕셔너리 경로)
        checks = [
            ("nasdaq.change_pct",  ["us_market",   "nasdaq",  "change_pct"]),
            ("sox.change_pct",     ["us_market",   "sox",     "change_pct"]),
            ("sp500.change_pct",   ["us_market",   "sp500",   "change_pct"]),
            ("vix.change_pct",     ["us_market",   "vix",     "change_pct"]),
            ("usd_krw.change_pct", ["us_market",   "usd_krw", "change_pct"]),
            ("kospi.change_pct",   ["kr_market",   "kospi",   "change_pct"]),
            ("kosdaq.change_pct",  ["kr_market",   "kosdaq",  "change_pct"]),
            ("wti.change_pct",     ["commodities", "wti",     "change_pct"]),
            ("gold.change_pct",    ["commodities", "gold",    "change_pct"]),
            ("copper.change_pct",  ["commodities", "copper",  "change_pct"]),
            ("lithium.change_pct", ["commodities", "lithium", "change_pct"]),
        ]

        for field_name, path in checks:
            try:
                value = data
                for key in path:
                    value = value[key]
                value = float(self._handle_missing(value))
                flagged = abs(value) > self.ANOMALY_THRESHOLD
                if flagged:
                    anomalies.append({"field": field_name, "value": value, "flagged": True})
            except (KeyError, TypeError, ValueError):
                # 경로가 없으면 탐지 대상에서 제외
                pass

        return anomalies

    # ------------------------------------------------------------------
    # 유틸리티
    # ------------------------------------------------------------------

    def _handle_missing(self, value, default=0.0):
        """None, NaN, inf를 default 값으로 대체한다."""
        if value is None:
            return default
        try:
            f = float(value)
            if math.isnan(f) or math.isinf(f):
                return default
            return f
        except (TypeError, ValueError):
            return default

    def _round(self, value, digits: int = 2) -> float:
        """float 반올림. None/NaN/inf는 0.0으로 처리한다."""
        cleaned = self._handle_missing(value, 0.0)
        return round(float(cleaned), digits)
