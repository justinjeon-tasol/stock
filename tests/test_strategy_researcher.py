"""
전략연구 에이전트 단위 테스트.

실행: python -m pytest tests/test_strategy_researcher.py -v
"""

import unittest

from agents.strategy_researcher import StrategyResearcher


class TestStrategyResearcher(unittest.TestCase):
    """StrategyResearcher 단위 테스트 모음."""

    @classmethod
    def setUpClass(cls):
        """테스트 클래스 전체에서 공유하는 StrategyResearcher 인스턴스."""
        cls.sr = StrategyResearcher()

    # ------------------------------------------------------------------
    # 1. 라이브러리 로드
    # ------------------------------------------------------------------

    def test_load_library(self):
        """__init__ 후 _library에 STR_001~STR_007 중 최소 1개 이상 로드."""
        self.assertGreaterEqual(len(self.sr._library), 1)

    # ------------------------------------------------------------------
    # 2. list_strategies
    # ------------------------------------------------------------------

    def test_list_strategies_all(self):
        """list_strategies() → 전체 7개 반환."""
        result = self.sr.list_strategies()
        self.assertEqual(len(result), 7)

    def test_list_strategies_by_phase(self):
        """list_strategies("안정화") → STR_001, STR_002 포함."""
        result = self.sr.list_strategies("안정화")
        ids = [card["id"] for card in result]
        self.assertIn("STR_001", ids)
        self.assertIn("STR_002", ids)

    # ------------------------------------------------------------------
    # 3. load_strategy
    # ------------------------------------------------------------------

    def test_load_strategy(self):
        """load_strategy("STR_001") → id가 "STR_001"인 dict 반환."""
        card = self.sr.load_strategy("STR_001")
        self.assertIsNotNone(card)
        self.assertIsInstance(card, dict)
        self.assertEqual(card["id"], "STR_001")

    def test_load_strategy_missing(self):
        """load_strategy("NONEXISTENT") → None 반환."""
        result = self.sr.load_strategy("NONEXISTENT")
        self.assertIsNone(result)

    # ------------------------------------------------------------------
    # 4. _calc_mdd
    # ------------------------------------------------------------------

    def test_calc_mdd_empty(self):
        """_calc_mdd([]) → 0.0."""
        self.assertEqual(self.sr._calc_mdd([]), 0.0)

    def test_calc_mdd_monotone_up(self):
        """_calc_mdd([1.0, 2.0, 3.0]) → 0.0 (손실 없음)."""
        result = self.sr._calc_mdd([1.0, 2.0, 3.0])
        self.assertEqual(result, 0.0)

    def test_calc_mdd_with_loss(self):
        """_calc_mdd([5.0, -3.0, -3.0]) → 음수 float."""
        result = self.sr._calc_mdd([5.0, -3.0, -3.0])
        self.assertIsInstance(result, float)
        self.assertLess(result, 0.0)

    # ------------------------------------------------------------------
    # 5. _calc_period_metrics
    # ------------------------------------------------------------------

    def test_calc_period_metrics_empty(self):
        """_calc_period_metrics([]) → trade_count == 0."""
        result = self.sr._calc_period_metrics([])
        self.assertEqual(result["trade_count"], 0)

    def test_calc_period_metrics(self):
        """result_pct [3.0, -1.0, 2.0, 4.0, -1.0] → win_rate=0.6, trade_count=5."""
        trades = [
            {"result_pct": 3.0},
            {"result_pct": -1.0},
            {"result_pct": 2.0},
            {"result_pct": 4.0},
            {"result_pct": -1.0},
        ]
        result = self.sr._calc_period_metrics(trades)
        self.assertEqual(result["trade_count"], 5)
        self.assertAlmostEqual(result["win_rate"], 0.6, places=4)

    # ------------------------------------------------------------------
    # 6. _split_into_periods
    # ------------------------------------------------------------------

    def test_split_into_periods_small(self):
        """trades 10개 → 단일 구간 반환 (15개 미만이므로)."""
        trades = [{"result_pct": 1.0}] * 10
        periods = self.sr._split_into_periods(trades)
        self.assertEqual(len(periods), 1)
        self.assertEqual(len(periods[0]), 10)

    def test_split_into_periods_large(self):
        """trades 30개 → 3개 구간."""
        trades = [{"result_pct": 1.0}] * 30
        periods = self.sr._split_into_periods(trades)
        self.assertEqual(len(periods), 3)

    # ------------------------------------------------------------------
    # 7. _validate_anti_overfit
    # ------------------------------------------------------------------

    def test_validate_anti_overfit_pass(self):
        """3개 기간 모두 win_rate=0.6, mdd=-5.0, count=6 → (True, '')."""
        period_results = [
            {"win_rate": 0.6, "mdd": -5.0, "trade_count": 6},
            {"win_rate": 0.6, "mdd": -5.0, "trade_count": 6},
            {"win_rate": 0.6, "mdd": -5.0, "trade_count": 6},
        ]
        passed, reason = self.sr._validate_anti_overfit(period_results)
        self.assertTrue(passed)
        self.assertEqual(reason, "")

    def test_validate_anti_overfit_fail_winrate(self):
        """한 기간 win_rate=0.50 → (False, ...)."""
        period_results = [
            {"win_rate": 0.6,  "mdd": -5.0, "trade_count": 6},
            {"win_rate": 0.50, "mdd": -5.0, "trade_count": 6},
            {"win_rate": 0.6,  "mdd": -5.0, "trade_count": 6},
        ]
        passed, reason = self.sr._validate_anti_overfit(period_results)
        self.assertFalse(passed)
        self.assertIn("승률 미달", reason)

    def test_validate_anti_overfit_fail_mdd(self):
        """한 기간 mdd=-12.0 → (False, ...)."""
        period_results = [
            {"win_rate": 0.6, "mdd": -5.0,  "trade_count": 6},
            {"win_rate": 0.6, "mdd": -12.0, "trade_count": 6},
            {"win_rate": 0.6, "mdd": -5.0,  "trade_count": 6},
        ]
        passed, reason = self.sr._validate_anti_overfit(period_results)
        self.assertFalse(passed)
        self.assertIn("MDD 초과", reason)

    def test_validate_anti_overfit_fail_periods(self):
        """2개 기간만 → (False, ...)."""
        period_results = [
            {"win_rate": 0.6, "mdd": -5.0, "trade_count": 6},
            {"win_rate": 0.6, "mdd": -5.0, "trade_count": 6},
        ]
        passed, reason = self.sr._validate_anti_overfit(period_results)
        self.assertFalse(passed)
        self.assertIn("기간 수 부족", reason)

    # ------------------------------------------------------------------
    # 8. recommend_strategies
    # ------------------------------------------------------------------

    def test_recommend_strategies_empty(self):
        """
        모든 전략이 백테스팅중이어도 recommend_strategies는 빈 리스트가 아님.
        (백테스팅중 상태는 추천 대상에 포함됨)
        """
        # 안정화 국면에 STR_001, STR_002가 있고 모두 백테스팅중 상태이므로
        result = self.sr.recommend_strategies("안정화", top_n=3)
        # 백테스팅중 전략도 eligible → 빈 리스트가 아님
        self.assertGreater(len(result), 0)

    # ------------------------------------------------------------------
    # 9. _is_eligible
    # ------------------------------------------------------------------

    def test_is_eligible_active(self):
        """status='백테스팅중' → True."""
        card = {
            "id": "TEST_001",
            "phase": "안정화",
            "performance": {
                "backtest_win_rate": 0.0,
                "mdd": 0.0,
                "status": "백테스팅중",
            }
        }
        self.assertTrue(self.sr._is_eligible(card))

    def test_is_eligible_inactive(self):
        """status='비활성' → False."""
        card = {
            "id": "TEST_002",
            "phase": "안정화",
            "performance": {
                "backtest_win_rate": 0.8,
                "mdd": -3.0,
                "status": "비활성",
            }
        }
        self.assertFalse(self.sr._is_eligible(card))

    def test_is_eligible_fail_criteria(self):
        """status='검증완료', win_rate=0.40 → False."""
        card = {
            "id": "TEST_003",
            "phase": "안정화",
            "performance": {
                "backtest_win_rate": 0.40,
                "mdd": -5.0,
                "status": "검증완료",
            }
        }
        self.assertFalse(self.sr._is_eligible(card))


if __name__ == "__main__":
    unittest.main()
