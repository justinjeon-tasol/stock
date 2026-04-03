"""
ClassificationLoader - 종목 분류 JSON 로더 및 역방향 인덱스 유틸리티

순수 유틸리티 클래스. BaseAgent 상속 없음.
"""

import json
import logging
from collections import defaultdict
from typing import Optional

logger = logging.getLogger(__name__)


class ClassificationLoader:
    """stock_classification.json을 로드하고 역방향 인덱스를 제공하는 유틸리티 클래스."""

    def __init__(self, config_path: str) -> None:
        self._stocks: dict = {}
        self._sector_definitions: dict = {}
        self._theme_definitions: dict = {}
        self._characteristic_definitions: dict = {}
        self._theme_momentum_sources: dict = {}

        self._sector_to_codes: dict[str, list[str]] = defaultdict(list)
        self._theme_to_codes: dict[str, list[str]] = defaultdict(list)
        self._char_to_codes: dict[str, list[str]] = defaultdict(list)

        self._load(config_path)

    # ------------------------------------------------------------------
    # 내부: 로드 및 인덱스 빌드
    # ------------------------------------------------------------------

    def _load(self, config_path: str) -> None:
        try:
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            logger.warning("stock_classification.json 파일을 찾을 수 없습니다: %s", config_path)
            return
        except json.JSONDecodeError as exc:
            logger.warning("stock_classification.json 파싱 오류: %s", exc)
            return

        self._stocks = data.get("stocks", {})
        self._sector_definitions = data.get("sector_definitions", {})
        self._theme_definitions = data.get("theme_definitions", {})
        self._characteristic_definitions = data.get("characteristic_definitions", {})
        self._theme_momentum_sources = data.get("theme_momentum_sources", {})

        self._build_indexes()

    def _build_indexes(self) -> None:
        for code, info in self._stocks.items():
            for sector in info.get("sector", []):
                self._sector_to_codes[sector].append(code)
            for theme in info.get("themes", []):
                self._theme_to_codes[theme].append(code)
            for char in info.get("characteristics", []):
                self._char_to_codes[char].append(code)

    # ------------------------------------------------------------------
    # 내부: 종목 정보 dict 생성 헬퍼
    # ------------------------------------------------------------------

    def _make_stock_entry(self, code: str) -> dict:
        info = self._stocks[code]
        return {
            "code": code,
            "name": info.get("name", ""),
            "sector": info.get("sector", []),
            "themes": info.get("themes", []),
            "characteristics": info.get("characteristics", []),
        }

    # ------------------------------------------------------------------
    # 공개 메서드
    # ------------------------------------------------------------------

    def get_stocks_by_sector(self, sector: str) -> list[dict]:
        """sector에 해당하는 종목 목록 반환."""
        codes = self._sector_to_codes.get(sector, [])
        return [self._make_stock_entry(c) for c in codes if c in self._stocks]

    def get_stocks_by_theme(self, theme: str) -> list[dict]:
        """theme에 해당하는 종목 목록 반환."""
        codes = self._theme_to_codes.get(theme, [])
        return [self._make_stock_entry(c) for c in codes if c in self._stocks]

    def get_stocks_by_characteristic(self, char: str) -> list[dict]:
        """특징으로 필터링한 종목 목록 반환."""
        codes = self._char_to_codes.get(char, [])
        return [self._make_stock_entry(c) for c in codes if c in self._stocks]

    def get_all_sectors_for_stock(self, code: str) -> list[str]:
        """종목코드 → 속한 섹터 목록."""
        if code not in self._stocks:
            return []
        return list(self._stocks[code].get("sector", []))

    def get_all_themes_for_stock(self, code: str) -> list[str]:
        """종목코드 → 속한 테마 목록."""
        if code not in self._stocks:
            return []
        return list(self._stocks[code].get("themes", []))

    def get_all_proxy_tickers(self) -> set[str]:
        """모든 테마의 proxy 티커 합집합 반환."""
        result: set[str] = set()
        for theme_info in self._theme_definitions.values():
            for ticker in theme_info.get("proxy_tickers", []):
                result.add(ticker)
        return result

    def get_theme_proxy_tickers(self, theme: str) -> list[str]:
        """특정 테마의 proxy 티커 목록."""
        theme_info = self._theme_definitions.get(theme, {})
        return list(theme_info.get("proxy_tickers", []))

    def get_theme_momentum_sources(self) -> dict:
        """theme_momentum_sources 전체 반환."""
        return dict(self._theme_momentum_sources)

    def build_legacy_stock_universe(self) -> dict:
        """기존 strategy_config.json의 stock_universe 포맷으로 변환.

        반환 예: {"반도체": [{"code": "005930", "name": "삼성전자"}, ...], ...}
        """
        universe: dict[str, list[dict]] = defaultdict(list)
        for code, info in self._stocks.items():
            entry = {"code": code, "name": info.get("name", "")}
            for sector in info.get("sector", []):
                universe[sector].append(entry)
        return dict(universe)

    def get_all_sectors(self) -> list[str]:
        """정의된 모든 섹터명 목록."""
        return list(self._sector_definitions.keys())

    def get_all_themes(self) -> list[str]:
        """정의된 모든 테마명 목록."""
        return list(self._theme_definitions.keys())

    def get_stock_info(self, code: str) -> Optional[dict]:
        """종목코드로 전체 정보 반환. 없으면 None."""
        if code not in self._stocks:
            return None
        info = dict(self._stocks[code])
        info["code"] = code
        return info

    def get_all_stocks(self) -> dict:
        """전체 종목 정보 dict 반환. {code: {name, market, sector, ...}}"""
        return dict(self._stocks)

    def get_stocks_by_indicator(self, signal_id: str) -> list[str]:
        """선행지표 signal_id에 직결된 종목코드 목록."""
        return [
            code for code, info in self._stocks.items()
            if signal_id in info.get("leading_indicators", [])
        ]

    def get_all_indicators_for_stock(self, code: str) -> list[str]:
        """종목코드 → 연결된 선행지표 목록."""
        if code not in self._stocks:
            return []
        return list(self._stocks[code].get("leading_indicators", []))
