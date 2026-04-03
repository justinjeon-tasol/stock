"""
추천 에이전트 모듈
MarketAnalyzer의 MARKET_ANALYSIS 결과를 받아
한국 주식 추천 목록과 추천 이유 텍스트를 생성한다.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from agents.base_agent import BaseAgent
from protocol.protocol import (
    StandardMessage,
    StockRecommendation,
    RecommendationPayload,
    dataclass_to_dict,
)


# ---------------------------------------------------------------------------
# 종목 풀 (strategy_config.json에서 로드하지만 fallback으로 하드코딩)
# ---------------------------------------------------------------------------
STOCK_UNIVERSE = {
    "반도체": [
        {"code": "005930", "name": "삼성전자"},
        {"code": "000660", "name": "SK하이닉스"},
        {"code": "042700", "name": "한미반도체"},
    ],
    "2차전지": [
        {"code": "373220", "name": "LG에너지솔루션"},
        {"code": "006400", "name": "삼성SDI"},
    ],
    "정유": [
        {"code": "096770", "name": "SK이노베이션"},
        {"code": "010950", "name": "S-Oil"},
    ],
    "지수ETF": [
        {"code": "069500", "name": "KODEX 200"},
        {"code": "229200", "name": "KODEX 코스닥150"},
    ],
}

# 국면별 기본 가중치
PHASE_WEIGHTS = {
    "급등장":   {"aggressive": 1.0, "defensive": 0.0, "cash": 0.0},
    "안정화":   {"aggressive": 0.7, "defensive": 0.0, "cash": 0.3},
    "급락장":   {"aggressive": 0.0, "defensive": 0.5, "cash": 0.5},
    "변동폭큰": {"aggressive": 0.0, "defensive": 0.2, "cash": 0.8},
}


class Recommender(BaseAgent):
    """
    시장 분석 결과를 기반으로 한국 주식 추천을 생성하는 에이전트.
    MARKET_ANALYSIS → RECOMMENDATION
    """

    MAX_RECOMMENDATIONS = 5   # 최대 추천 종목 수
    MIN_CONFIDENCE      = 0.5  # 이 이하 신뢰도면 추천 최소화

    def __init__(self):
        super().__init__("RC", "추천엔진", timeout=5, max_retries=3)
        # strategy_config.json 로드 시도, 실패 시 하드코딩 사용
        self.stock_universe = self._load_stock_universe()

    # ------------------------------------------------------------------
    # 종목 풀 로드
    # ------------------------------------------------------------------

    def _load_stock_universe(self) -> dict:
        """
        strategy_config.json에서 종목 풀을 로드한다.
        파일이 없거나 파싱 실패 시 하드코딩된 STOCK_UNIVERSE를 반환한다.
        """
        config_paths = [
            # 1순위: 프로젝트 루트의 config/ 폴더 (agents/ 기준 상위 폴더의 config/)
            Path(__file__).parent.parent / "config" / "strategy_config.json",
            # 2순위: 프로젝트 루트 직접
            Path(__file__).parent.parent / "strategy_config.json",
            # 3순위: 현재 작업 디렉토리의 config/
            Path("config") / "strategy_config.json",
            # 4순위: 현재 작업 디렉토리 직접
            Path("strategy_config.json"),
        ]
        for path in config_paths:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    if "stock_universe" in config:
                        self.log("info", f"strategy_config.json 로드 성공: {path.resolve()}")
                        return config["stock_universe"]
            except (FileNotFoundError, json.JSONDecodeError, KeyError):
                continue

        self.log("info", "strategy_config.json 없음 → 하드코딩 종목 풀 사용")
        return STOCK_UNIVERSE

    # ------------------------------------------------------------------
    # 공개 인터페이스
    # ------------------------------------------------------------------

    async def execute(self, input_data: StandardMessage) -> StandardMessage:
        """
        MARKET_ANALYSIS → RECOMMENDATION 변환.
        RecommendationPayload를 dict로 변환하여 반환한다.
        """
        self.log("info", "추천 생성 시작")

        raw_payload    = input_data.body.get("payload", {})
        market_phase   = raw_payload.get("market_phase",   {})
        active_signals = raw_payload.get("active_signals", [])

        phase      = market_phase.get("phase",      "안정화")
        confidence = market_phase.get("confidence", 0.0)

        # 원본 us/kr 데이터는 market_phase 페이로드에는 없으므로
        # 요약 생성에 필요한 경우 active_signals에서 재구성
        us = raw_payload.get("us_market", {})
        kr = raw_payload.get("kr_market", {})

        # 종목 선정
        recommendations = self.select_stocks(phase, active_signals, confidence)
        self.log("info", f"추천 종목: {len(recommendations)}개")

        # 시장 요약 생성
        market_summary = self.generate_market_summary(
            phase, confidence, active_signals, us, kr
        )

        payload = RecommendationPayload(
            phase=phase,
            phase_confidence=confidence,
            recommendations=[dataclass_to_dict(r) for r in recommendations],
            market_summary=market_summary,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

        self.log("info", "추천 생성 완료")
        return self.create_message(
            to="OR",
            data_type="RECOMMENDATION",
            payload=dataclass_to_dict(payload),
        )

    # ------------------------------------------------------------------
    # 종목 선정
    # ------------------------------------------------------------------

    def select_stocks(self, phase: str, active_signals: list, confidence: float) -> list:
        """
        국면 + 활성 신호 기반 종목 선정.

        로직:
        1. AVOID 신호 있으면 → 해당 섹터 제외
        2. BUY 신호 있으면 → 해당 섹터 종목 후보에 추가
        3. 급락장/변동폭큰 → 모든 공격 종목 제외, 현금 비중 최대
        4. 안정화 → BUY 신호 있는 섹터만 추천
        5. 급등장 → BUY 신호 섹터 우선, 없으면 지수ETF

        반환: List[StockRecommendation]
        """
        # 급락장/변동폭큰 → 추천 없음 (현금 보유)
        if phase in ("급락장", "변동폭큰"):
            self.log("info", f"국면 {phase} → 추천 없음 (현금 비중 최대)")
            return []

        # AVOID 신호 섹터 수집
        avoid_sectors = set()
        for sig in active_signals:
            if sig.get("direction") == "AVOID":
                for sector in sig.get("kr_sectors", []):
                    avoid_sectors.add(sector)

        # BUY 신호 섹터 수집 (섹터별 신호 강도 합산)
        buy_sector_strength: dict = {}
        for sig in active_signals:
            if sig.get("direction") == "BUY":
                strength = sig.get("strength", 1.0)
                for sector in sig.get("kr_sectors", []):
                    if sector not in avoid_sectors:
                        buy_sector_strength[sector] = buy_sector_strength.get(sector, 0.0) + strength

        # 후보 종목 수집
        candidates = []  # (sector, stock_dict, total_strength)

        if buy_sector_strength:
            # BUY 신호 섹터 우선
            for sector, strength in buy_sector_strength.items():
                for stock in self.stock_universe.get(sector, []):
                    candidates.append((sector, stock, strength))
        elif phase == "급등장":
            # BUY 신호 없는 급등장 → 지수ETF 추천
            for stock in self.stock_universe.get("지수ETF", []):
                candidates.append(("지수ETF", stock, 1.0))

        # 안정화: BUY 신호 없으면 추천 없음
        if not candidates:
            self.log("info", "활성 BUY 신호 없음 → 추천 없음")
            return []

        # 신뢰도가 낮으면 후보 절반으로 제한
        if confidence < self.MIN_CONFIDENCE:
            candidates = candidates[: max(1, len(candidates) // 2)]

        # MAX_RECOMMENDATIONS 초과 시 강도 상위 종목만 선택
        candidates.sort(key=lambda x: x[2], reverse=True)
        candidates = candidates[: self.MAX_RECOMMENDATIONS]

        # StockRecommendation 생성
        result = []
        for sector, stock, _ in candidates:
            code = stock["code"]
            name = stock["name"]
            weight = self.calculate_weight(code, sector, active_signals, phase)
            reasons, leading_indicators, risk_factors = self.generate_reasons(
                code, name, active_signals, phase
            )
            rec = StockRecommendation(
                code=code,
                name=name,
                direction="BUY",
                weight=weight,
                reasons=reasons,
                leading_indicators=leading_indicators,
                risk_factors=risk_factors,
            )
            result.append(rec)

        # 전체 weight 합이 1.0을 초과하면 정규화
        total_weight = sum(r.weight for r in result)
        if total_weight > 1.0:
            for r in result:
                r.weight = round(r.weight / total_weight, 4)

        return result

    # ------------------------------------------------------------------
    # 추천 이유 생성
    # ------------------------------------------------------------------

    def generate_reasons(
        self,
        stock_code: str,
        stock_name: str,
        active_signals: list,
        phase: str,
    ) -> tuple:
        """
        추천 이유, 선행지표, 리스크 생성.

        반환: (reasons: list[str], leading_indicators: list[str], risk_factors: list[str])
        """
        reasons:            list = []
        leading_indicators: list = []
        risk_factors:       list = []

        # 섹터 코드 → 섹터명 역매핑
        code_to_sector: dict = {}
        for sector, stocks in self.stock_universe.items():
            for s in stocks:
                code_to_sector[s["code"]] = sector
        stock_sector = code_to_sector.get(stock_code, "")

        # 활성 신호 기반 이유 생성
        for sig in active_signals:
            direction   = sig.get("direction", "")
            kr_sectors  = sig.get("kr_sectors", [])
            description = sig.get("description", "")
            value       = sig.get("value", 0.0)
            signal_id   = sig.get("signal_id", "")

            if direction == "BUY" and stock_sector in kr_sectors:
                # 신호 설명에 실제 수치 추가
                if value != 0.0:
                    reasons.append(
                        f"{description} (변동률: {value:+.1f}%)"
                    )
                else:
                    reasons.append(description)
                leading_indicators.append(
                    f"{signal_id}: {value:+.1f}%"
                )

            elif direction == "AVOID":
                # AVOID 신호는 리스크 요인으로
                risk_factors.append(
                    f"{description} ({value:+.1f}%)"
                )

        # 국면 기반 이유 추가
        phase_weights = PHASE_WEIGHTS.get(phase, {})
        aggressive = phase_weights.get("aggressive", 0.0)
        if aggressive > 0:
            reasons.append(
                f"현재 국면({phase})에서 {stock_sector} 섹터 공격 비중 {int(aggressive * 100)}% 적용"
            )

        # 이유가 없으면 기본 이유 추가
        if not reasons:
            reasons.append(f"{phase} 국면에서 {stock_name} 추천")

        return reasons, leading_indicators, risk_factors

    # ------------------------------------------------------------------
    # 시장 요약 생성
    # ------------------------------------------------------------------

    def generate_market_summary(
        self,
        phase: str,
        confidence: float,
        active_signals: list,
        us: dict,
        kr: dict,
    ) -> str:
        """
        전체 시장 요약 텍스트 생성 (사람이 읽을 수 있는 형식).

        예시:
        "미국 반도체 지수(SOX)가 +3.8% 급등하며 기술주 강세를 이끌었습니다.
         VIX 18.2로 안정적이며 달러 약세(-0.3%)로 외국인 매수 유입이 기대됩니다."
        """
        parts = []

        # 국면 요약
        phase_desc = {
            "급등장":   "시장이 강세 흐름을 보이고 있습니다",
            "급락장":   "시장이 급락 중으로 위험 관리가 필요합니다",
            "변동폭큰": "변동성이 확대되어 주의가 필요합니다",
            "안정화":   "시장이 안정적인 흐름을 유지하고 있습니다",
        }
        parts.append(
            f"현재 시장 국면은 [{phase}]으로 판단됩니다 (신뢰도: {confidence:.0%}). "
            f"{phase_desc.get(phase, '')}"
        )

        # VIX 정보
        vix_val = us.get("vix", {}).get("value", 0.0) if us else 0.0
        if vix_val > 0:
            if vix_val >= 30:
                parts.append(f"VIX {vix_val:.1f}로 극도의 공포 구간입니다.")
            elif vix_val >= 25:
                parts.append(f"VIX {vix_val:.1f}로 변동성이 높습니다.")
            elif vix_val <= 20:
                parts.append(f"VIX {vix_val:.1f}로 안정적입니다.")

        # 달러/원화 정보
        usd_chg = us.get("usd_krw", {}).get("change_pct", 0.0) if us else 0.0
        if abs(usd_chg) >= 0.3:
            if usd_chg > 0:
                parts.append(f"달러 강세({usd_chg:+.1f}%)로 외국인 순매도 압력이 예상됩니다.")
            else:
                parts.append(f"달러 약세({usd_chg:+.1f}%)로 외국인 매수 유입이 기대됩니다.")

        # 주요 활성 신호 요약 (최대 2개)
        buy_signals  = [s for s in active_signals if s.get("direction") == "BUY"]
        avoid_signals = [s for s in active_signals if s.get("direction") == "AVOID"]

        for sig in buy_signals[:2]:
            desc  = sig.get("description", "")
            value = sig.get("value", 0.0)
            if desc:
                parts.append(f"{desc} (변동률: {value:+.1f}%).")

        for sig in avoid_signals[:1]:
            desc  = sig.get("description", "")
            value = sig.get("value", 0.0)
            if desc:
                parts.append(f"주의: {desc} (값: {value:.1f}).")

        return " ".join(parts)

    # ------------------------------------------------------------------
    # 비중 계산
    # ------------------------------------------------------------------

    def calculate_weight(
        self,
        stock_code: str,
        sector: str,
        active_signals: list,
        phase: str,
    ) -> float:
        """
        종목별 추천 비중(0.0~1.0) 계산.
        - 같은 섹터 신호 수 기반
        - 전체 합이 1.0 이하가 되도록 정규화 (select_stocks에서 처리)
        - 급락장/변동폭큰 시 모두 0.0
        """
        # 위험 국면 → 비중 0
        if phase in ("급락장", "변동폭큰"):
            return 0.0

        # 해당 섹터의 BUY 신호 강도 합산
        sector_strength = 0.0
        for sig in active_signals:
            if sig.get("direction") == "BUY" and sector in sig.get("kr_sectors", []):
                sector_strength += sig.get("strength", 1.0)

        # 기본 비중 = 국면 공격 비중 × (섹터 강도 / 최대 강도 3.0)
        phase_weights   = PHASE_WEIGHTS.get(phase, {"aggressive": 0.5})
        aggressive_base = phase_weights.get("aggressive", 0.5)

        # 섹터 강도 정규화 (최대 3.0 기준)
        normalized_strength = min(sector_strength / 3.0, 1.0) if sector_strength > 0 else 0.3

        weight = round(aggressive_base * normalized_strength, 4)
        return max(0.0, min(1.0, weight))  # 0~1 범위 보장
