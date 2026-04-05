"""
signal_service.py — 백테스팅 시그널 매트릭스 조회 서비스

Supabase의 indicator_stock_correlations 테이블에서
종목별 시그널 정보를 조회한다.

기존 에이전트(WA, SR)가 이 서비스를 호출하여
섹터 매핑 대신 종목 레벨 의사결정 + 신뢰도 기반 포지션 사이징을 수행한다.

장애 시 모든 메서드가 빈 리스트/기본값을 반환하여 기존 로직(폴백)이 작동한다.
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# 신뢰도 → 포지션 사이즈 팩터
_CONFIDENCE_SIZE_MAP = {
    "★★★": 1.0,
    "★★": 0.5,
    "★": 0.0,
}

# 시그널 유효기간 (일)
_SIGNAL_MAX_AGE_DAYS = 90

# MA signal_id → (indicator_id, event_direction) 매핑
# MA의 signal_id 패턴: "indicator_event" (예: "sox_surge", "wti_surge", "nasdaq_crash")
_SIGNAL_ID_TO_INDICATOR = {
    "nasdaq_surge":  ("nasdaq", "up"),
    "nasdaq_crash":  ("nasdaq", "down"),
    "sox_surge":     ("sox", "up"),
    "sox_crash":     ("sox", "down"),
    "nvidia_surge":  ("nvidia", "up"),
    "amd_surge":     ("amd", "up"),
    "tesla_strong":  ("tesla", "up"),
    "tesla_crash":   ("tesla", "down"),
    "wti_surge":     ("wti", "up"),
    "copper_strong": ("copper", "up"),
    "gold_strong":   ("gold", "up"),
    "vix_spike":     ("vix", "up"),
    "vix_warning":   ("vix", "up"),
    "dollar_strong": ("dollar", "up"),
}


class SignalService:
    """Supabase indicator_stock_correlations 테이블 조회 서비스."""

    def __init__(self):
        self._cache: dict = {}
        self._cache_ts: dict = {}
        self._cache_ttl = 3600  # 1시간 캐시

    def _get_client(self):
        """Supabase 클라이언트를 가져온다. 실패 시 None."""
        try:
            from database.db import _get_client
            return _get_client()
        except Exception:
            return None

    def _is_cache_valid(self, key: str) -> bool:
        ts = self._cache_ts.get(key, 0)
        return (time.time() - ts) < self._cache_ttl

    @staticmethod
    def parse_signal_id(signal_id: str) -> Optional[tuple]:
        """
        MA의 signal_id를 (indicator_id, event_direction) 튜플로 변환한다.
        매핑에 없으면 None 반환.
        """
        return _SIGNAL_ID_TO_INDICATOR.get(signal_id)

    def get_signals_by_indicator(
        self,
        indicator_id: str,
        direction: str,
        min_confidence: str = "★★",
        min_lag: int = 1,
        max_lag: int = 5,
    ) -> list:
        """
        특정 선행지표 트리거 발생 시 매매해야 할 종목 리스트 반환.

        Returns: [
            {
                "stock_code": "010950",
                "stock_name": "S-Oil",
                "sector": "정유",
                "signal_direction": "buy",
                "mean_excess_return": 2.1,
                "win_rate": 0.68,
                "confidence": "★★★",
                "lag_days": 1,
                "sample_count": 23,
                "position_size_factor": 1.0
            },
            ...
        ]
        정렬: confidence DESC → abs(mean_excess_return) DESC
        """
        cache_key = f"indicator_{indicator_id}_{direction}"
        if self._is_cache_valid(cache_key):
            return self._cache.get(cache_key, [])

        try:
            client = self._get_client()
            if client is None:
                return []

            # 신뢰도 필터: min_confidence 이상
            confidence_levels = self._get_confidence_levels(min_confidence)
            if not confidence_levels:
                return []

            # 시그널 유효기간 필터
            cutoff = (datetime.now(timezone.utc) - timedelta(days=_SIGNAL_MAX_AGE_DAYS)).isoformat()

            query = (
                client.table("indicator_stock_correlations")
                .select("*")
                .eq("indicator_id", indicator_id)
                .eq("event_direction", direction)
                .in_("confidence", confidence_levels)
                .gte("lag_days", min_lag)
                .lte("lag_days", max_lag)
                .gte("updated_at", cutoff)
                .neq("signal_direction", "neutral")
                .execute()
            )

            rows = query.data or []

            # 같은 종목에 여러 lag가 있을 수 있으므로 가장 짧은 lag만 사용
            best_by_stock: dict = {}
            for row in rows:
                code = row.get("stock_code", "")
                existing = best_by_stock.get(code)
                if existing is None or row.get("lag_days", 99) < existing.get("lag_days", 99):
                    best_by_stock[code] = row

            results = []
            for row in best_by_stock.values():
                conf = row.get("confidence", "★")
                results.append({
                    "stock_code": row.get("stock_code", ""),
                    "stock_name": row.get("stock_name", ""),
                    "sector": row.get("sector", ""),
                    "signal_direction": row.get("signal_direction", ""),
                    "mean_excess_return": float(row.get("mean_excess_return", 0)),
                    "win_rate": float(row.get("win_rate", 0)),
                    "confidence": conf,
                    "lag_days": int(row.get("lag_days", 1)),
                    "sample_count": int(row.get("sample_count", 0)),
                    "position_size_factor": self._apply_position_size(conf),
                })

            # 정렬: confidence DESC → abs(mean_excess_return) DESC
            conf_order = {"★★★": 0, "★★": 1, "★": 2}
            results.sort(key=lambda x: (
                conf_order.get(x["confidence"], 9),
                -abs(x["mean_excess_return"]),
            ))

            self._cache[cache_key] = results
            self._cache_ts[cache_key] = time.time()
            return results

        except Exception as exc:
            logger.warning("[SignalService] get_signals_by_indicator 실패: %s", exc)
            return []

    def get_drivers_for_stock(
        self,
        stock_code: str,
        min_confidence: str = "★★",
    ) -> list:
        """
        특정 종목에 영향을 주는 선행지표 리스트 반환.
        (보유 포지션 검토 시 사용)
        """
        cache_key = f"drivers_{stock_code}"
        if self._is_cache_valid(cache_key):
            return self._cache.get(cache_key, [])

        try:
            client = self._get_client()
            if client is None:
                return []

            confidence_levels = self._get_confidence_levels(min_confidence)
            if not confidence_levels:
                return []

            cutoff = (datetime.now(timezone.utc) - timedelta(days=_SIGNAL_MAX_AGE_DAYS)).isoformat()

            query = (
                client.table("indicator_stock_correlations")
                .select("indicator_id,event_direction,signal_direction,mean_excess_return,confidence,lag_days")
                .eq("stock_code", stock_code)
                .in_("confidence", confidence_levels)
                .gte("updated_at", cutoff)
                .neq("signal_direction", "neutral")
                .execute()
            )

            results = [
                {
                    "indicator_id": row.get("indicator_id", ""),
                    "event_direction": row.get("event_direction", ""),
                    "signal_direction": row.get("signal_direction", ""),
                    "mean_excess_return": float(row.get("mean_excess_return", 0)),
                    "confidence": row.get("confidence", "★"),
                    "lag_days": int(row.get("lag_days", 1)),
                }
                for row in (query.data or [])
            ]

            self._cache[cache_key] = results
            self._cache_ts[cache_key] = time.time()
            return results

        except Exception as exc:
            logger.warning("[SignalService] get_drivers_for_stock 실패: %s", exc)
            return []

    def get_position_size_factor(
        self,
        indicator_id: str,
        direction: str,
        stock_code: str,
    ) -> float:
        """
        신뢰도 기반 포지션 사이즈 팩터 반환.

        ★★★ → 1.0 (풀 사이즈)
        ★★  → 0.5 (하프 사이즈)
        ★   → 0.0 (진입 불가)
        시그널 없음 → 0.3 (기존 섹터 매핑 폴백)
        """
        signals = self.get_signals_by_indicator(indicator_id, direction)
        for s in signals:
            if s["stock_code"] == stock_code:
                return s["position_size_factor"]
        return 0.3  # 시그널 없음 → 폴백 사이즈

    def check_conflicting_signals(
        self,
        stock_code: str,
        active_triggers: list,
    ) -> dict:
        """
        복수 지표가 동시에 트리거되었을 때 충돌 여부 확인.

        Parameters:
            stock_code: 종목코드
            active_triggers: [{"indicator_id": "sox", "direction": "up"}, ...]

        Returns: {
            "has_conflict": True/False,
            "buy_signals": [...],
            "sell_signals": [...],
            "recommendation": "hold" | "buy" | "sell"
        }
        """
        buy_signals = []
        sell_signals = []

        for trigger in active_triggers:
            ind_id = trigger.get("indicator_id", "")
            direction = trigger.get("direction", "")
            signals = self.get_signals_by_indicator(ind_id, direction, min_confidence="★★")
            for s in signals:
                if s["stock_code"] == stock_code:
                    if s["signal_direction"] == "buy":
                        buy_signals.append(s)
                    elif s["signal_direction"] == "sell":
                        sell_signals.append(s)

        has_conflict = bool(buy_signals) and bool(sell_signals)

        if has_conflict:
            recommendation = "hold"
        elif buy_signals:
            recommendation = "buy"
        elif sell_signals:
            recommendation = "sell"
        else:
            recommendation = "hold"

        return {
            "has_conflict": has_conflict,
            "buy_signals": buy_signals,
            "sell_signals": sell_signals,
            "recommendation": recommendation,
        }

    def clear_cache(self) -> None:
        """캐시 초기화 (테스트용)."""
        self._cache.clear()
        self._cache_ts.clear()

    @staticmethod
    def _apply_position_size(confidence: str) -> float:
        """신뢰도 → 포지션 사이즈 매핑."""
        return _CONFIDENCE_SIZE_MAP.get(confidence, 0.3)

    @staticmethod
    def _get_confidence_levels(min_confidence: str) -> list:
        """min_confidence 이상인 신뢰도 레벨 리스트 반환."""
        levels = ["★★★", "★★", "★"]
        try:
            idx = levels.index(min_confidence)
            return levels[:idx + 1]
        except ValueError:
            return levels
