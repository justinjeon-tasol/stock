"""
ClassificationLoader 단위 테스트
"""

import unittest
import sys
import os

# 프로젝트 루트를 경로에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.classification_loader import ClassificationLoader

CONFIG_PATH = r"C:\Users\justi\Desktop\P\config\stock_classification.json"


class TestClassificationLoader(unittest.TestCase):

    def setUp(self):
        self.loader = ClassificationLoader(CONFIG_PATH)

    # 1. JSON 로드 성공
    def test_load_success(self):
        stocks = self.loader._stocks
        self.assertIsInstance(stocks, dict)
        self.assertGreater(len(stocks), 0, "stocks가 비어있지 않아야 함")

    # 2. 섹터로 종목 조회
    def test_get_stocks_by_sector(self):
        result = self.loader.get_stocks_by_sector("반도체")
        codes = [s["code"] for s in result]
        self.assertIn("005930", codes)
        self.assertIn("000660", codes)
        self.assertIn("042700", codes)

    # 3. 없는 섹터 → 빈 리스트
    def test_get_stocks_by_sector_missing(self):
        result = self.loader.get_stocks_by_sector("존재하지않는섹터")
        self.assertEqual(result, [])

    # 4. 테마로 종목 조회
    def test_get_stocks_by_theme(self):
        result = self.loader.get_stocks_by_theme("AI/HBM")
        codes = [s["code"] for s in result]
        self.assertIn("005930", codes)
        self.assertIn("000660", codes)
        self.assertIn("042700", codes)

    # 5. 없는 테마 → 빈 리스트
    def test_get_stocks_by_theme_missing(self):
        result = self.loader.get_stocks_by_theme("존재하지않는테마")
        self.assertEqual(result, [])

    # 6. 특징으로 조회
    def test_get_stocks_by_characteristic(self):
        result = self.loader.get_stocks_by_characteristic("대형우량주")
        codes = [s["code"] for s in result]
        self.assertIn("005930", codes, "삼성전자는 대형우량주에 포함되어야 함")

    # 7. 종목코드 → 섹터
    def test_get_all_sectors_for_stock(self):
        sectors = self.loader.get_all_sectors_for_stock("005930")
        self.assertIn("반도체", sectors)

    # 8. 종목코드 → 테마
    def test_get_all_themes_for_stock(self):
        themes = self.loader.get_all_themes_for_stock("005930")
        self.assertIn("AI/HBM", themes)
        self.assertIn("반도체장비", themes)

    # 9. 전체 proxy 티커 합집합
    def test_get_all_proxy_tickers(self):
        tickers = self.loader.get_all_proxy_tickers()
        self.assertIsInstance(tickers, set)
        self.assertIn("NVDA", tickers)
        self.assertIn("AMD", tickers)
        self.assertIn("LMT", tickers)

    # 10. 특정 테마 proxy 티커
    def test_get_theme_proxy_tickers(self):
        tickers = self.loader.get_theme_proxy_tickers("AI/HBM")
        self.assertIn("NVDA", tickers)
        self.assertIn("AMD", tickers)

    # 11. 레거시 stock_universe 포맷 변환
    def test_build_legacy_stock_universe(self):
        universe = self.loader.build_legacy_stock_universe()
        self.assertIn("반도체", universe)
        sector_list = universe["반도체"]
        self.assertIsInstance(sector_list, list)
        self.assertGreater(len(sector_list), 0)
        first = sector_list[0]
        self.assertIn("code", first)
        self.assertIn("name", first)

    # 12. 모든 섹터명 목록
    def test_get_all_sectors(self):
        sectors = self.loader.get_all_sectors()
        self.assertIn("반도체", sectors)
        self.assertIn("2차전지", sectors)
        self.assertIn("바이오", sectors)
        self.assertIn("방산", sectors)

    # 13. 모든 테마명 목록
    def test_get_all_themes(self):
        themes = self.loader.get_all_themes()
        self.assertIn("AI/HBM", themes)
        self.assertIn("방산", themes)
        self.assertIn("원전", themes)

    # 14. 종목코드로 전체 정보 조회
    def test_get_stock_info(self):
        info = self.loader.get_stock_info("000660")
        self.assertIsNotNone(info)
        self.assertEqual(info["name"], "SK하이닉스")

    # 15. 없는 종목코드 → None
    def test_get_stock_info_missing(self):
        info = self.loader.get_stock_info("999999")
        self.assertIsNone(info)

    # 16. 없는 파일 경로로 초기화해도 예외 없음
    def test_missing_file(self):
        loader = ClassificationLoader("/nonexistent/path/stock_classification.json")
        result = loader.get_all_sectors()
        self.assertEqual(result, [])

    # 17. 005930이 AI/HBM과 반도체장비 두 테마에 모두 나타남
    def test_stock_in_multiple_themes(self):
        aihbm_codes = [s["code"] for s in self.loader.get_stocks_by_theme("AI/HBM")]
        equip_codes = [s["code"] for s in self.loader.get_stocks_by_theme("반도체장비")]
        self.assertIn("005930", aihbm_codes, "005930은 AI/HBM 테마에 있어야 함")
        self.assertIn("005930", equip_codes, "005930은 반도체장비 테마에 있어야 함")


if __name__ == "__main__":
    unittest.main()
