"""
가중치조정 에이전트 모듈.
MarketAnalyzer의 MARKET_ANALYSIS 메시지를 받아
국면별 가중치와 종목 타겟을 결정하고 SIGNAL 메시지를 생성한다.
MVP: Executor(EX)로 직행.
"""

import json
import logging
import os
from typing import Optional

from agents.base_agent import BaseAgent
from agents.classification_loader import ClassificationLoader
from agents.position_manager import PositionManager
from agents.risk_manager import RiskManager
from protocol.protocol import StandardMessage, dataclass_to_dict
from services.signal_service import SignalService


# 하드코딩 fallback 가중치 (strategy_config.json 로드 실패 시 사용)
# 6단계 국면 시스템: 대상승장/상승장/일반장/변동폭큰/하락장/대폭락장
_FALLBACK_PHASE_WEIGHTS = {
    "대상승장": {"aggressive": 1.0, "defensive": 0.0, "cash": 0.0},
    "상승장":   {"aggressive": 0.8, "defensive": 0.0, "cash": 0.2},
    "일반장":   {"aggressive": 0.6, "defensive": 0.0, "cash": 0.4},
    "변동폭큰": {"aggressive": 0.2, "defensive": 0.2, "cash": 0.6},
    "하락장":   {"aggressive": 0.0, "defensive": 0.4, "cash": 0.6},
    "대폭락장": {"aggressive": 0.0, "defensive": 0.2, "cash": 0.8},
}

# 하드코딩 fallback 종목 유니버스 (strategy_config.json 로드 실패 시 사용)
_FALLBACK_STOCK_UNIVERSE = {
    "반도체":  [
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

# strategy_config.json 경로 (이 파일 기준 두 단계 위 → config/)
_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "strategy_config.json",
)

# stock_classification.json 경로
_CLASSIFICATION_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "stock_classification.json",
)

# HOLD 판단 대상 국면 (신규 매수 보류, 현금/방어 유지)
_HOLD_PHASES = {"하락장", "대폭락장", "변동폭큰"}

# targets 최대 종목 수
_MAX_TARGETS = 5

# strength 정규화 기준값 (MarketAnalyzer에서 strength = change_pct / threshold_pct)
_STRENGTH_NORMALIZE_BASE = 3.0


class WeightAdjuster(BaseAgent):
    """
    국면 + 선행지표 신호를 반영하여 전략 비중(가중치)과
    투자 대상 종목(targets)을 결정하는 에이전트.
    MARKET_ANALYSIS → SIGNAL
    """

    def __init__(self) -> None:
        super().__init__("WA", "가중치조정", timeout=15, max_retries=3)
        self._phase_weights: dict = {}
        self._stock_universe: dict = {}
        self._classification_rules: dict = {}
        self._load_config()
        self._classification = ClassificationLoader(_CLASSIFICATION_PATH)
        self._position_manager = PositionManager()
        self._risk_manager = RiskManager()
        self._signal_service = SignalService()

    # ------------------------------------------------------------------
    # 설정 로드
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        """
        strategy_config.json을 읽어 phase_weights와 stock_universe를 초기화한다.
        파일이 없거나 파싱 실패 시 하드코딩 fallback을 사용한다.
        """
        try:
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
            self._phase_weights        = cfg.get("phase_weights",        _FALLBACK_PHASE_WEIGHTS)
            self._stock_universe       = cfg.get("stock_universe",       _FALLBACK_STOCK_UNIVERSE)
            self._classification_rules = cfg.get("classification_rules", {})
            self.log("info", f"strategy_config.json 로드 완료: {_CONFIG_PATH}")
        except FileNotFoundError:
            self.log("warning", f"strategy_config.json 없음 ({_CONFIG_PATH}) → fallback 사용")
            self._phase_weights  = _FALLBACK_PHASE_WEIGHTS
            self._stock_universe = _FALLBACK_STOCK_UNIVERSE
        except (json.JSONDecodeError, Exception) as exc:
            self.log("warning", f"strategy_config.json 파싱 실패: {exc} → fallback 사용")
            self._phase_weights        = _FALLBACK_PHASE_WEIGHTS
            self._stock_universe       = _FALLBACK_STOCK_UNIVERSE
            self._classification_rules = {}

    # ------------------------------------------------------------------
    # 공개 인터페이스
    # ------------------------------------------------------------------

    async def execute(self, input_data: StandardMessage) -> StandardMessage:
        """
        MARKET_ANALYSIS → SIGNAL 변환.

        입력 페이로드:
            market_phase:   {"phase": str, "confidence": float, ...}
            active_signals: [{"signal_id": str, "direction": str,
                              "kr_sectors": list, "strength": float, "value": float, ...}]
            trend_reversal: {"reversal_up": {...}, "reversal_down": {...}}

        출력 페이로드 (SIGNAL):
            signal_id, direction, confidence, phase, issue_factor,
            targets, weight_config, reason
        """
        self.log("info", "가중치조정 시작")

        payload = input_data.body.get("payload", {})

        market_phase_data = payload.get("market_phase", {})
        active_signals    = payload.get("active_signals", [])
        theme_signals        = payload.get("theme_signals", [])
        trend_reversal       = payload.get("trend_reversal", {})
        rs_scores            = payload.get("rs_scores", {})           # A안
        stock_foreign_net    = payload.get("stock_foreign_net", {})   # C안
        stock_institution_net = payload.get("stock_institution_net", {})  # C안 기관
        oversold_candidates  = payload.get("oversold_candidates", []) # 대폭락장 반등
        trend_filter_results = payload.get("trend_filter_results", {})  # Filter 2
        kalman_signals       = payload.get("kalman_signals", {})        # 칼만 MA 신호

        phase      = market_phase_data.get("phase",      "일반장")
        confidence = market_phase_data.get("confidence", 0.5)

        # 이슈 데이터 (MA payload 내 issue_analysis에서 추출)
        issue_payload   = payload.get("issue_analysis", {})
        active_issues   = issue_payload.get("active_issues", [])
        issue_max_sev   = issue_payload.get("max_severity", "LOW")
        if active_issues:
            self.log("info", f"이슈 {len(active_issues)}건 수신 (최대 등급: {issue_max_sev})")

        self.log("info", f"입력 국면: {phase} (신뢰도: {confidence:.2f}), "
                         f"활성 신호: {len(active_signals)}개")

        # 1. direction 결정 — CRITICAL 이슈 시 강제 HOLD/SELL
        direction = self._decide_direction(phase, active_signals, oversold_candidates)
        if issue_max_sev == "CRITICAL":
            if direction == "BUY":
                direction = "HOLD"
                self.log("warning", "CRITICAL 이슈로 인해 BUY → HOLD 강제 전환")
        self.log("info", f"direction 결정: {direction}")

        # 2. weight_config 결정
        weight_config = self._decide_weight_config(phase)
        # 대폭락장 반등 포착 모드: 소규모 투자 (최대 15%)
        if phase == "대폭락장" and direction == "BUY":
            weight_config = {"aggressive_pct": 0.15, "defensive_pct": 0.0, "cash_pct": 0.85}
            self.log("info", "대폭락장 반등 포착 모드 — 최대 15% 투자")
        self.log("info", f"weight_config: {weight_config}")

        # 3. targets 결정
        targets = self._decide_targets(direction, active_signals, weight_config, theme_signals,
                                       rs_scores=rs_scores, stock_foreign_net=stock_foreign_net,
                                       stock_institution_net=stock_institution_net,
                                       oversold_candidates=oversold_candidates, phase=phase,
                                       trend_filter_results=trend_filter_results,
                                       kalman_signals=kalman_signals)
        self.log("info", f"targets: {len(targets)}종목")

        # 3-a. defensive 자산 선택 (defensive_pct > 0이면 방어ETF에서 종목 선택)
        defensive_targets = self._decide_defensive_targets(weight_config)
        if defensive_targets:
            self.log("info", f"방어 자산: {len(defensive_targets)}종목 "
                             f"({', '.join(t['name'] for t in defensive_targets)})")

        # 4. reason 텍스트 생성
        reason = self._build_reason(phase, direction, active_signals, weight_config)

        # 5. SIGNAL 페이로드 구성
        # msg_id를 signal_id로 재사용하기 위해 메시지를 먼저 생성
        msg = self.create_message(
            to="EX",
            data_type="SIGNAL",
            payload={},           # 임시 빈 payload
            msg_type="SIGNAL",
            priority="HIGH" if direction == "BUY" else "NORMAL",
        )
        signal_id = msg.header.msg_id

        # 5-a. 매도 대상 결정 (현재 포지션 기준)
        buy_codes   = {t["code"] for t in targets}
        sell_targets = self._position_manager.get_sell_targets_from_positions(buy_codes, phase)
        if sell_targets:
            self.log("info", f"매도 대상: {len(sell_targets)}종목")

        # ── 미국 하락 신호 기반 선제 매도 대상 추가 ──
        sell_signals = [s for s in active_signals if s.get("direction") == "SELL"]
        if sell_signals:
            preemptive_targets = self._get_preemptive_sell_targets(sell_signals)
            existing_codes = {t["code"] for t in sell_targets}
            for pt in preemptive_targets:
                if pt["code"] not in existing_codes:
                    sell_targets.append(pt)
                    existing_codes.add(pt["code"])
            if preemptive_targets:
                self.log("info", f"선제 매도 대상 추가: {len(preemptive_targets)}종목")

        # ── REDUCE 신호 기반 전체 포지션 축소 ──
        reduce_signals = [s for s in active_signals if s.get("direction") == "REDUCE"]
        if reduce_signals:
            reduce_pct = max(s.get("reduce_pct", 50) for s in reduce_signals)
            reduce_targets = self._get_reduce_targets(reduce_pct)
            existing_codes = {t["code"] for t in sell_targets}
            for rt in reduce_targets:
                if rt["code"] not in existing_codes:
                    sell_targets.append(rt)
                    existing_codes.add(rt["code"])
            if reduce_targets:
                self.log("warning", f"포지션 축소({reduce_pct}%): {len(reduce_targets)}종목")

        # ── 시그널 역전 매도 대상 합류 (Orchestrator Step 2-b2에서 주입) ─��
        reversal_sells = payload.get("signal_reversal_sells", [])
        if reversal_sells:
            existing_sell_codes = {t["code"] for t in sell_targets}
            for rs in reversal_sells:
                if rs["code"] not in existing_sell_codes:
                    sell_targets.append(rs)
                    existing_sell_codes.add(rs["code"])
            self.log("info", f"시그널 역전 매도: {len(reversal_sells)}종목 추가")

        # issue_factor: 활성 이슈 요약 (없으면 None)
        issue_factor = None
        if active_issues:
            issue_factor = {
                "count":        len(active_issues),
                "max_severity": issue_max_sev,
                "issues":       [
                    {"issue_id": i["issue_id"], "name": i["name"], "severity": i["severity"]}
                    for i in active_issues
                ],
                "summary": issue_payload.get("summary", ""),
            }

        signal_payload = {
            "signal_id":     signal_id,
            "direction":     direction,
            "confidence":    round(confidence, 2),
            "phase":             phase,
            "issue_factor":      issue_factor,
            "targets":           targets,
            "defensive_targets": defensive_targets,
            "sell_targets":      sell_targets,
            "weight_config":     weight_config,
            "reason":            reason,
            "kalman_signals":    kalman_signals,
        }

        # body의 payload를 완성된 값으로 교체
        msg.body["payload"] = signal_payload

        self.log("info", f"SIGNAL 생성 완료: {signal_id} / {direction}")
        return msg

    # ------------------------------------------------------------------
    # 공개 메서드 (테스트 및 외부 접근용)
    # ------------------------------------------------------------------

    def determine_direction(self, phase: str, active_signals: list) -> str:
        return self._decide_direction(phase, active_signals)

    def get_phase_weights(self, phase: str) -> dict:
        raw = self._phase_weights.get(phase, self._phase_weights.get("일반장", {}))
        return {
            "aggressive": float(raw.get("aggressive", 0.7)),
            "defensive":  float(raw.get("defensive",  0.0)),
            "cash":       float(raw.get("cash",       0.3)),
        }

    def select_targets(self, phase: str, active_signals: list, weight_config: dict,
                       theme_signals: list = None) -> list:
        direction = self._decide_direction(phase, active_signals)
        # get_phase_weights 반환 형식("aggressive") → 내부 형식("aggressive_pct") 변환
        if "aggressive" in weight_config and "aggressive_pct" not in weight_config:
            weight_config = {
                "aggressive_pct": weight_config["aggressive"],
                "defensive_pct":  weight_config["defensive"],
                "cash_pct":       weight_config["cash"],
            }
        return self._decide_targets(direction, active_signals, weight_config, theme_signals or [])

    def build_reason(self, phase: str, direction: str, active_signals: list, weight_config: dict) -> str:
        return self._build_reason(phase, direction, active_signals, weight_config)

    # ------------------------------------------------------------------
    # direction 결정
    # ------------------------------------------------------------------

    def _decide_direction(self, phase: str, active_signals: list,
                          oversold_candidates: list = None) -> str:
        """
        direction을 결정한다.

        - SELL 신호 존재 시 → SELL (해당 섹터 포지션 선제 청산)
        - REDUCE 신호 존재 시 → HOLD (포지션 축소는 별도 처리)
        - 대폭락장: 기본 HOLD. 낙폭과대 후보(score≥4) 있으면 소규모 BUY 허용
        - 변동폭큰 → 무조건 HOLD
        - 하락장 → AVOID 없고 강한 BUY(strength > 1.5)가 있을 때만 예외 BUY 허용 (B안)
        - 상승/일반장 → BUY 신호 있으면 BUY, AVOID 다수면 HOLD
        """
        buy_signals    = [s for s in active_signals if s.get("direction") == "BUY"]
        avoid_signals  = [s for s in active_signals if s.get("direction") == "AVOID"]
        sell_signals   = [s for s in active_signals if s.get("direction") == "SELL"]
        reduce_signals = [s for s in active_signals if s.get("direction") == "REDUCE"]

        # SELL 신호가 있으면 SELL (해당 섹터 포지션 선제 청산)
        if sell_signals:
            self.log("warning", f"미국 하락 신호 감지 → SELL ({len(sell_signals)}개: "
                     f"{', '.join(s['signal_id'] for s in sell_signals)})")
            return "SELL"

        # REDUCE 신호가 있으면 HOLD (포지션 축소는 별도 처리)
        if reduce_signals:
            self.log("warning", f"위험 신호 감지 → HOLD + 포지션 축소 ({len(reduce_signals)}개)")
            return "HOLD"

        # 변동폭큰: 무조건 HOLD
        if phase == "변동폭큰":
            return "HOLD"

        # 대폭락장: 낙폭과대 고점수(score≥4) 후보 있을 때만 소규모 BUY, 나머진 HOLD
        if phase == "대폭락장":
            if not avoid_signals and oversold_candidates:
                strong = [c for c in oversold_candidates if c.get("score", 0) >= 4]
                if strong:
                    return "BUY"
            return "HOLD"

        # 하락장: AVOID 없고 강한 선행지표(strength > 1.5) 시 예외 BUY
        if phase == "하락장":
            strong_buys = [s for s in buy_signals if s.get("strength", 0) > 1.5]
            if strong_buys and not avoid_signals:
                return "BUY"
            return "HOLD"

        if not buy_signals:
            # 한국 시장 모멘텀 BUY: 상승장/대상승장이면서 AVOID 신호가 없으면
            # 미국 선행지표 없이도 한국 시장 자체 모멘텀으로 매수 허용
            if phase in ("상승장", "대상승장") and not avoid_signals:
                self.log("info", f"미국 신호 없으나 한국 시장 모멘텀 BUY (국면={phase})")
                return "BUY"
            return "HOLD"

        # AVOID 신호가 BUY 신호보다 많으면 HOLD (위험 우선)
        if len(avoid_signals) >= len(buy_signals):
            return "HOLD"

        return "BUY"

    # ------------------------------------------------------------------
    # weight_config 결정
    # ------------------------------------------------------------------

    def _decide_weight_config(self, phase: str) -> dict:
        """
        phase에 따라 strategy_config.json의 phase_weights를 반환한다.
        알 수 없는 phase이면 일반장 기본값을 사용한다.

        연속 손실 감지 시 aggressive 비중을 감쇠한다.
        """
        weights = self._phase_weights.get(phase, self._phase_weights.get("일반장", {}))
        aggressive = float(weights.get("aggressive", 0.7))
        defensive  = float(weights.get("defensive",  0.0))
        cash       = float(weights.get("cash",       0.3))

        # 연속 손실 감지 → aggressive 비중 감쇠
        _, dampen = self._risk_manager.check_consecutive_losses()
        if dampen < 1.0:
            reduced = round(aggressive * dampen, 4)
            added_cash = round(aggressive - reduced, 4)
            self.log("warning",
                     f"연속 손실 감쇠 적용: aggressive {aggressive:.0%} → {reduced:.0%} "
                     f"(+cash {added_cash:.0%})")
            aggressive = reduced
            cash = round(cash + added_cash, 4)

        return {
            "aggressive_pct": aggressive,
            "defensive_pct":  defensive,
            "cash_pct":       cash,
        }

    # ------------------------------------------------------------------
    # targets 결정
    # ------------------------------------------------------------------

    def _decide_targets(
        self,
        direction: str,
        active_signals: list,
        weight_config: dict,
        theme_signals: list = None,
        rs_scores: dict = None,
        stock_foreign_net: dict = None,
        stock_institution_net: dict = None,
        oversold_candidates: list = None,
        phase: str = "",
        trend_filter_results: dict = None,
        kalman_signals: dict = None,
    ) -> list:
        """
        targets 종목 리스트를 결정한다.

        - direction == "HOLD" → 빈 리스트
        - 대폭락장 BUY → oversold_candidates 직접 사용 (섹터 신호 무시)
        - 일반 BUY → BUY 신호 섹터 종목 수집 + 테마/지표/RS/외국인 부스트 적용
        - 추세 필터(Filter 2): trend_score < threshold 종목 제외
        - 전체 weight 합이 aggressive_pct 초과 시 비례 정규화
        - 최대 _MAX_TARGETS 종목
        """
        if direction == "HOLD":
            return []

        aggressive_pct = weight_config["aggressive_pct"]

        # ── 대폭락장 반등 포착 경로 ─────────────────────────────────────
        # 섹터 신호 대신 낙폭과대 후보를 직접 targets로 변환
        if phase == "대폭락장" and oversold_candidates:
            top = [c for c in oversold_candidates if c.get("score", 0) >= 4][:3]
            if not top:
                return []
            per_weight = round(aggressive_pct / len(top), 4)
            return [
                {"code": c["code"], "name": c["name"], "weight": per_weight}
                for c in top
            ]

        aggressive_pct = weight_config["aggressive_pct"]

        # AVOID 섹터 수집
        avoid_sectors: set = set()
        for sig in active_signals:
            if sig.get("direction") == "AVOID":
                for sector in sig.get("kr_sectors", []):
                    avoid_sectors.add(sector)

        # ── 백테스팅 시그널 매트릭스 기반 종목 선정 (우선) ──────────────
        signal_candidates = self._get_signal_service_candidates(
            active_signals, avoid_sectors, aggressive_pct
        )
        if signal_candidates:
            self.log("info", f"시그널 매트릭스 기반 종목 {len(signal_candidates)}개 선정")

            # 최소 필터: 칼만 하향 이탈 종목 제외
            if kalman_signals:
                before = len(signal_candidates)
                signal_candidates = [
                    c for c in signal_candidates
                    if kalman_signals.get(c["code"], {}).get("trend") != "DOWN"
                    or kalman_signals.get(c["code"], {}).get("price_above_kalman", True)
                ]
                filtered = before - len(signal_candidates)
                if filtered > 0:
                    self.log("info", f"시그널 매트릭스: 칼만 하향 {filtered}개 제외")

            # 시그널 기반 후보를 기존 파이프라인(Step 8: 보유 중 제외 ~ 정규화)에 합류
            candidates = signal_candidates
            # Step 8 이후로 직접 점프 (테마/RS/외국인 부스트는 이미 백테스팅에서 반영됨)
            candidates = [
                c for c in candidates
                if not self._position_manager.is_already_held(c["code"])
            ]
            max_targets = self._risk_manager.get_max_positions(phase) if phase else _MAX_TARGETS
            current_positions = len(self._position_manager.get_open_positions())
            available_slots = max(0, max_targets - current_positions)
            candidates.sort(key=lambda x: x["weight"], reverse=True)
            candidates = candidates[:available_slots]

            total_weight = sum(c["weight"] for c in candidates)
            if total_weight > aggressive_pct and total_weight > 0:
                scale = aggressive_pct / total_weight
                for c in candidates:
                    c["weight"] = round(c["weight"] * scale, 4)

            return candidates

        # ── 폴백: 기존 섹터 매핑 기반 종목 선정 ──────────────────────────

        # BUY 신호에서 (섹터, 강도) 매핑 구축 — 같은 섹터가 여러 신호에 있으면 강도 누적
        sector_strength: dict = {}
        for sig in active_signals:
            if sig.get("direction") != "BUY":
                continue
            strength = float(sig.get("strength", 1.0))
            for sector in sig.get("kr_sectors", []):
                if sector in avoid_sectors:
                    continue
                if sector == "전반":
                    # "전반" 섹터는 모든 유니버스를 대상으로 하되 낮은 강도 적용
                    for s in self._stock_universe:
                        if s not in avoid_sectors:
                            sector_strength[s] = sector_strength.get(s, 0.0) + strength * 0.5
                else:
                    sector_strength[sector] = sector_strength.get(sector, 0.0) + strength

        if not sector_strength:
            # ── 한국 시장 모멘텀 폴백: RS STRONG 종목 기반 선정 ──────────
            # 미국 신호 없이 BUY 진입 시 (상승장/대상승장 모멘텀)
            # RS 분석에서 STRONG인 종목을 타겟으로 선정
            if direction == "BUY" and rs_scores:
                strong_stocks = [
                    code for code, rs in rs_scores.items()
                    if rs.get("signal") == "STRONG"
                ]
                if not strong_stocks:
                    # STRONG 없으면 NEUTRAL 중 rs_5d 상위 종목
                    neutral = [
                        (code, rs.get("rs_5d", 0) or 0)
                        for code, rs in rs_scores.items()
                        if rs.get("signal") == "NEUTRAL"
                    ]
                    neutral.sort(key=lambda x: x[1], reverse=True)
                    strong_stocks = [code for code, _ in neutral[:4]]

                if strong_stocks:
                    candidates = []
                    per_weight = round(aggressive_pct / len(strong_stocks), 4)
                    for code in strong_stocks:
                        name = ""
                        for sector_stocks in self._stock_universe.values():
                            for s in sector_stocks:
                                if s.get("code") == code:
                                    name = s.get("name", code)
                                    break
                            if name:
                                break
                        if not self._position_manager.is_already_held(code):
                            candidates.append({"code": code, "name": name or code, "weight": per_weight})

                    max_targets = self._risk_manager.get_max_positions(phase) if phase else _MAX_TARGETS
                    current_positions = len(self._position_manager.get_open_positions())
                    available_slots = max(0, max_targets - current_positions)
                    candidates = candidates[:available_slots]

                    total_weight = sum(c["weight"] for c in candidates)
                    if total_weight > aggressive_pct and total_weight > 0:
                        scale = aggressive_pct / total_weight
                        for c in candidates:
                            c["weight"] = round(c["weight"] * scale, 4)

                    # 칼만 필터 적용
                    candidates = self._apply_kalman_buy_filter(candidates, kalman_signals)

                    if candidates:
                        self.log("info", f"한국 모멘텀 BUY: RS+칼만 기반 {len(candidates)}종목 선정")
                        return candidates

            return []

        # 섹터별 종목 수집 및 raw weight 계산
        # raw_weight = aggressive_pct × (sector_strength / _STRENGTH_NORMALIZE_BASE)
        candidates: list = []
        seen_codes: set = set()

        for sector, total_strength in sector_strength.items():
            stocks = self._stock_universe.get(sector, [])
            raw_weight = aggressive_pct * (total_strength / _STRENGTH_NORMALIZE_BASE)
            # 같은 섹터 내 종목들은 동일한 raw_weight를 나눠 가짐
            per_stock_weight = raw_weight / max(len(stocks), 1)
            for stock in stocks:
                code = stock.get("code", "")
                if code in seen_codes:
                    # 중복 종목은 weight 누적
                    for c in candidates:
                        if c["code"] == code:
                            c["weight"] = round(c["weight"] + per_stock_weight, 4)
                            break
                    continue
                seen_codes.add(code)
                candidates.append({
                    "code":   code,
                    "name":   stock.get("name", ""),
                    "weight": round(per_stock_weight, 4),
                })

        if not candidates:
            return []

        # Step 2: 테마 시그널로 weight 부스트 (기존)
        candidates = self._apply_theme_boost(candidates, theme_signals or [])

        # Step 3: 선행지표 직결 종목 부스트 (B안)
        candidates = self._apply_leading_indicator_boost(candidates, active_signals)

        # Step 4: 외국인+기관 순매수 부스트 (C안)
        candidates = self._apply_foreign_net_boost(
            candidates, stock_foreign_net or {}, stock_institution_net or {})

        # Step 5: 상대강도 필터 (A안)
        candidates = self._apply_rs_filter(candidates, rs_scores or {})

        # Step 6: 섹터 분산 감쇠
        candidates.sort(key=lambda x: x["weight"], reverse=True)
        candidates = self._apply_sector_decay(candidates)

        # Step 6b: 포트폴리오 상관관계 감쇠 — 동일 섹터 보유 종목 있으면 weight 축소
        candidates = self._apply_portfolio_correlation(candidates)

        # Step 7: 추세 필터 (Filter 2) — trend_score 미달 종목 제외 + 비중 조정
        candidates = self._apply_trend_filter(candidates, trend_filter_results)

        # Step 7b: 진입 타이밍 필터 (Filter 3) — ENTER만 남기고 WAIT/BLOCKED 제외
        candidates = self._apply_entry_timing_filter(
            candidates, trend_filter_results, active_signals, phase,
            stock_foreign_net=stock_foreign_net,
            stock_institution_net=stock_institution_net)

        # Step 7c: 칼만 MA 매수 타이밍 필터 — 하향 추세 종목 제거
        candidates = self._apply_kalman_buy_filter(candidates, kalman_signals)

        # Step 8: 이미 보유 중인 종목 제외 → 신규 매수 가능 종목만 남김
        candidates = [
            c for c in candidates
            if not self._position_manager.is_already_held(c["code"])
        ]

        # Step 5: 정렬 후 상위 max_targets만 선택 (국면별 동적 제한)
        max_targets = self._risk_manager.get_max_positions(phase) if phase else _MAX_TARGETS
        # 이미 보유 포지션 수를 차감하여 신규 가능 수만 허용
        current_positions = len(self._position_manager.get_open_positions())
        available_slots = max(0, max_targets - current_positions)
        candidates.sort(key=lambda x: x["weight"], reverse=True)
        candidates = candidates[:available_slots]
        if available_slots < len(candidates):
            self.log("info",
                     f"포지션 제한: 최대 {max_targets}종목 - 보유 {current_positions}종목 "
                     f"= 신규 {available_slots}종목 허용")

        # 전체 weight 합이 aggressive_pct 초과 시 비례 정규화
        total_weight = sum(c["weight"] for c in candidates)
        if total_weight > aggressive_pct and total_weight > 0:
            scale = aggressive_pct / total_weight
            for c in candidates:
                c["weight"] = round(c["weight"] * scale, 4)

        return candidates

    # ------------------------------------------------------------------
    # 칼만 MA 매수 타이밍 필터
    # ------------------------------------------------------------------

    def _apply_kalman_buy_filter(self, candidates: list, kalman_signals: dict = None) -> list:
        """
        칼만 MA 하향 추세 종목을 제거하고 상향 돌파 종목에 부스트를 적용한다.

        - crossover == "UP" → weight × 1.15 부스트
        - trend == "UP" and price_above_kalman → 통과
        - trend == "DOWN" and not price_above_kalman → 제거
        - 칼만 데이터 없는 종목 → 통과 (Graceful Degradation)
        """
        if not kalman_signals or not candidates:
            return candidates

        filtered = []
        removed = []
        for c in candidates:
            sig = kalman_signals.get(c["code"])
            if not sig:
                filtered.append(c)
                continue

            trend = sig.get("trend", "FLAT")
            above = sig.get("price_above_kalman", True)
            cross = sig.get("crossover")

            if trend == "DOWN" and not above:
                removed.append(c["name"])
                continue

            if cross == "UP":
                c["weight"] = round(c["weight"] * 1.15, 4)

            filtered.append(c)

        if removed:
            self.log("info", f"칼만 필터 제거: {', '.join(removed)}")

        return filtered

    # ------------------------------------------------------------------
    # defensive 자산 선택
    # ------------------------------------------------------------------

    def _decide_defensive_targets(self, weight_config: dict) -> list:
        """
        defensive_pct > 0이면 방어ETF 섹터에서 종목을 선택한다.

        방어ETF 섹터가 stock_universe에 없으면 빈 리스트 반환.
        이미 보유 중인 방어 종목은 제외.

        반환: [{"code": ..., "name": ..., "weight": ..., "is_defensive": True}, ...]
        """
        defensive_pct = float(weight_config.get("defensive_pct", 0.0))
        if defensive_pct <= 0:
            return []

        defensive_stocks = self._stock_universe.get("방어ETF", [])
        if not defensive_stocks:
            return []

        # 이미 보유 중인 종목 제외
        candidates = [
            s for s in defensive_stocks
            if not self._position_manager.is_already_held(s.get("code", ""))
        ]
        if not candidates:
            return []

        # 균등 배분
        per_weight = round(defensive_pct / len(candidates), 4)
        return [
            {
                "code": s["code"],
                "name": s["name"],
                "weight": per_weight,
                "is_defensive": True,
            }
            for s in candidates
        ]

    # ------------------------------------------------------------------
    # 테마 부스트
    # ------------------------------------------------------------------

    def _apply_theme_boost(self, candidates: list, theme_signals: list) -> list:
        """
        활성 테마 신호가 있는 종목의 weight에 boost_multiplier를 곱한다.

        - strategy_config의 classification_rules.theme_boost_multiplier (기본 1.3)
        - ClassificationLoader로 각 종목의 테마 목록을 조회
        - 활성 테마(direction=BUY)에 속한 종목이면 weight × multiplier
        - 여러 테마에 속해도 한 번만 적용 (중복 방지)
        """
        if not theme_signals or not candidates:
            return candidates

        # 활성 BUY 테마 수집
        active_themes: set = set()
        for s in theme_signals:
            if s.get("direction") == "BUY":
                for theme in s.get("kr_themes", []):
                    if theme:
                        active_themes.add(theme)

        if not active_themes:
            return candidates

        # classification_rules에서 multiplier 읽기 (없으면 기본 1.3)
        multiplier = float(self._classification_rules.get("theme_boost_multiplier", 1.3))

        boosted = []
        for c in candidates:
            code = c["code"]
            stock_themes = set(self._classification.get_all_themes_for_stock(code))
            if stock_themes & active_themes:  # 교집합 있으면 부스트
                new_weight = round(c["weight"] * multiplier, 4)
                boosted.append({**c, "weight": new_weight})
            else:
                boosted.append(c)

        return boosted

    # ------------------------------------------------------------------
    # 섹터 분산 감쇠
    # ------------------------------------------------------------------

    def _apply_sector_decay(self, candidates: list) -> list:
        """
        같은 섹터에서 N번째 종목의 weight를 감쇠한다.

        감쇠 계수 (strategy_config의 classification_rules.sector_decay):
        1번째: 1.0, 2번째: 0.85, 3번째: 0.7, 4번째 이상: 0.55

        ClassificationLoader로 각 종목의 섹터를 조회하여 섹터별 등장 순서 추적.
        """
        # classification_rules에서 decay 설정 읽기
        cfg_decay = self._classification_rules.get("sector_decay", {})
        SECTOR_DECAY = {
            1: float(cfg_decay.get("1", 1.0)),
            2: float(cfg_decay.get("2", 0.85)),
            3: float(cfg_decay.get("3", 0.7)),
            4: float(cfg_decay.get("4", 0.55)),
        }
        DEFAULT_DECAY = float(cfg_decay.get("4", 0.55))

        sector_count: dict = {}  # sector → 등장 횟수
        decayed = []

        for c in candidates:
            code = c["code"]
            # 종목의 첫 번째 섹터만 기준으로 사용 (가장 대표 섹터)
            sectors = self._classification.get_all_sectors_for_stock(code)
            primary_sector = sectors[0] if sectors else "기타"

            sector_count[primary_sector] = sector_count.get(primary_sector, 0) + 1
            n = sector_count[primary_sector]
            decay = SECTOR_DECAY.get(n, DEFAULT_DECAY)

            decayed.append({**c, "weight": round(c["weight"] * decay, 4)})

        return decayed

    def _apply_portfolio_correlation(self, candidates: list) -> list:
        """
        보유 포지션과 동일 섹터인 매수 후보의 weight를 감쇠한다.

        risk_config.json의 sector_correlation.same_sector_dampen (기본 0.5) 적용.
        예: 삼성전자(반도체) 보유 중 + SK하이닉스(반도체) 매수 후보 → weight × 0.5
        """
        # risk_config에서 감쇠 계수 로드
        dampen = 0.5
        try:
            import json as _json
            risk_cfg_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "config", "risk_config.json",
            )
            with open(risk_cfg_path, encoding="utf-8") as f:
                risk_cfg = _json.load(f)
            dampen = float(risk_cfg.get("sector_correlation", {}).get("same_sector_dampen", 0.5))
        except Exception:
            pass

        # 보유 포지션의 섹터 수집
        open_positions = self._position_manager.get_open_positions()
        held_sectors: set = set()
        for pos in open_positions:
            code = pos.get("code", "")
            sectors = self._classification.get_all_sectors_for_stock(code)
            held_sectors.update(sectors)

        if not held_sectors:
            return candidates

        result = []
        for c in candidates:
            code = c["code"]
            sectors = self._classification.get_all_sectors_for_stock(code)
            if any(s in held_sectors for s in sectors):
                dampened_weight = round(c["weight"] * dampen, 4)
                result.append({**c, "weight": dampened_weight})
                self.log(
                    "debug",
                    f"[상관관계] {c['name']}({code}) 동일 섹터 보유 → "
                    f"weight {c['weight']}→{dampened_weight} (×{dampen})",
                )
            else:
                result.append(c)

        return result

    # ------------------------------------------------------------------
    # 선행지표 직결 부스트 (B안)
    # ------------------------------------------------------------------

    def _apply_leading_indicator_boost(self, candidates: list, active_signals: list) -> list:
        """
        활성 BUY 신호와 직결된 종목(stock_classification.json의 leading_indicators)의
        weight를 부스트한다.

        예: nvidia_surge 신호 → 000660(SK하이닉스), 042700(한미반도체) weight × 1.5
        """
        active_buy_ids = {s["signal_id"] for s in active_signals if s.get("direction") == "BUY"}
        if not active_buy_ids or not candidates:
            return candidates

        multiplier = float(self._classification_rules.get("leading_indicator_boost_multiplier", 1.5))
        result = []
        for c in candidates:
            stock_indicators = set(self._classification.get_all_indicators_for_stock(c["code"]))
            if stock_indicators & active_buy_ids:
                result.append({**c, "weight": round(c["weight"] * multiplier, 4)})
            else:
                result.append(c)
        return result

    # ------------------------------------------------------------------
    # 외국인+기관 수급 부스트 (C안)
    # ------------------------------------------------------------------

    def _apply_foreign_net_boost(self, candidates: list, stock_foreign_net: dict,
                                 stock_institution_net: dict = None) -> list:
        """
        외국인+기관 통합 수급으로 weight 조정.
          VERY_STRONG: 외국인+기관 동시 매수 → ×1.3
          STRONG:      외국인 매수 (기관 중립 이상) → ×1.2
          MODERATE:    기관만 매수 (외국인 중립 이상) → ×1.1
          WEAK:        외국인 매도 (기관 미지원) → ×0.8
          VERY_WEAK:   외국인+기관 동시 매도 → ×0.6
        기관 데이터 없으면 기존 외국인 단독 로직 fallback.
        """
        if not stock_foreign_net or not candidates:
            return candidates
        if stock_institution_net is None:
            stock_institution_net = {}

        result = []
        for c in candidates:
            code = c["code"]
            frgn = stock_foreign_net.get(code, 0) or 0
            inst = stock_institution_net.get(code, 0) or 0

            if inst != 0:
                # 기관 데이터 있음 → 통합 수급 판정
                fb = frgn > 0
                fs = frgn < 0
                ib = inst > 0
                is_ = inst < 0

                if fb and ib:
                    mult = 1.3   # VERY_STRONG
                elif fb and not is_:
                    mult = 1.2   # STRONG
                elif ib and not fs:
                    mult = 1.1   # MODERATE
                elif fs and is_:
                    mult = 0.6   # VERY_WEAK
                elif fs and not ib:
                    mult = 0.8   # WEAK
                elif is_ and not fb:
                    mult = 0.9   # MILD_WEAK
                else:
                    mult = 1.0   # MIXED
            else:
                # 기관 데이터 없음 → 기존 외국인 단독 로직
                if frgn > 0:
                    mult = 1.2
                elif frgn < -10_000_000_000:
                    mult = 0.7
                else:
                    mult = 1.0

            result.append({**c, "weight": round(c["weight"] * mult, 4)})
        return result

    # ------------------------------------------------------------------
    # 상대강도 필터 (A안)
    # ------------------------------------------------------------------

    def _apply_rs_filter(self, candidates: list, rs_scores: dict) -> list:
        """
        상대강도(RS) 기반 weight 조정.
          - STRONG (5일+20일 RS > 1.0): × 1.4 (하락장에서도 버티는 강한 종목)
          - WEAK   (5일+20일 RS < 0.5): × 0.5 (시장보다 더 빠지는 약한 종목)
          - NEUTRAL / UNKNOWN: 변경 없음
        """
        if not rs_scores or not candidates:
            return candidates

        result = []
        for c in candidates:
            rs = rs_scores.get(c["code"], {})
            signal = rs.get("signal", "UNKNOWN")
            if signal == "STRONG":
                new_w = round(c["weight"] * 1.4, 4)
            elif signal == "WEAK":
                new_w = round(c["weight"] * 0.5, 4)
            else:
                new_w = c["weight"]
            result.append({**c, "weight": new_w})
        return result

    # ------------------------------------------------------------------
    # 추세 필터 (Filter 2 연동)
    # ------------------------------------------------------------------

    def _apply_trend_filter(self, candidates: list, trend_filter_results: dict = None) -> list:
        """
        MA의 check_trend_batch() 결과를 이용하여:
          1) trend_score < threshold 종목을 제외한다.
          2) 통과 종목의 trend_score에 따라 비중을 미세 조정한다.
             - trend_score >= 0.8: ×1.2 (강한 추세 → 확신 배팅)
             - trend_score >= 0.6: ×1.0 (유지)
             - 그 외(threshold~0.6): ×0.8 (소극적 배팅)
        trend_filter_results가 없으면 아무것도 변경하지 않는다.
        """
        if not trend_filter_results or not candidates:
            return candidates

        # 통과 종목의 symbol → trend_score 매핑
        passed_map: dict = {}
        for r in trend_filter_results.get("passed", []):
            passed_map[r["symbol"]] = r["trend_score"]

        # 필터링된 종목 코드 셋
        filtered_symbols: set = {r["symbol"] for r in trend_filter_results.get("filtered_out", [])}

        before_count = len(candidates)
        result = []
        for c in candidates:
            code = c["code"]
            # 필터링 대상이면 제거
            if code in filtered_symbols:
                continue
            # 통과 종목이면 score 기반 비중 조정
            ts = passed_map.get(code)
            if ts is not None:
                if ts >= 0.8:
                    new_w = round(c["weight"] * 1.2, 4)
                elif ts >= 0.6:
                    new_w = c["weight"]
                else:
                    new_w = round(c["weight"] * 0.8, 4)
                result.append({**c, "weight": new_w, "trend_score": ts})
            else:
                # trend_filter에 데이터 없는 종목은 그대로 통과
                result.append(c)

        removed = before_count - len(result)
        if removed > 0:
            self.log("info", f"[추세 필터] {before_count}종목 → {len(result)}종목 "
                             f"(제거 {removed}종목)")

        return result

    def _apply_entry_timing_filter(self, candidates, trend_filter_results,
                                   active_signals, phase,
                                   stock_foreign_net=None,
                                   stock_institution_net=None):
        """
        Filter 3 적용: 각 후보 종목의 진입 타이밍을 평가하고
        ENTER만 남긴다 (WAIT/BLOCKED 제거).
        trend_filter_results가 없거나 후보가 없으면 그대로 통과.
        """
        if not candidates or not trend_filter_results:
            return candidates

        # trend_filter_results에서 종목별 trend_result와 history_symbol 매핑
        trend_map = {}
        for r in trend_filter_results.get("passed", []):
            trend_map[r["symbol"]] = r

        # price_data 로드 + batch 구성
        batch_input = []
        code_to_candidate = {}
        for c in candidates:
            code = c["code"]
            tr = trend_map.get(code)
            if tr is None:
                # trend 결과 없는 종목은 Filter 3 스킵 (그대로 통과)
                code_to_candidate[code] = c
                continue

            hist_sym = tr.get("history_symbol", "")
            pdata = self._load_entry_price_data(hist_sym) if hist_sym else None
            if pdata is None or len(pdata.get("closes", [])) < 50:
                code_to_candidate[code] = c
                continue

            batch_input.append({
                "symbol": code,
                "price_data": pdata,
                "trend_result": tr,
            })
            code_to_candidate[code] = c

        if not batch_input:
            return candidates

        entry_results = self.check_entry_timing_batch(
            batch_input,
            leading_indicators=active_signals,
            market_phase=phase,
            stock_foreign_net=stock_foreign_net,
            stock_institution_net=stock_institution_net,
        )

        s = entry_results["summary"]
        self.log("info",
                 f"[진입 필터] {s['total']}종목 → "
                 f"진입 {s['enter']}개, 대기 {s['wait']}개, 차단 {s['blocked']}개 "
                 f"(필요 신호 {s['required_signals']}개, 국면 {s['phase']})")

        for b in entry_results["blocked"]:
            self.log("warning", f"  [차단] {b['symbol']}: {b['reason']}")
        for w in entry_results["wait"]:
            self.log("debug", f"  [대기] {w['symbol']}: {w['reason']}")

        # ENTER 종목 코드 셋
        enter_codes = {r["symbol"] for r in entry_results["enter"]}
        # BLOCKED 종목 코드 셋 (확실히 제거)
        blocked_codes = {r["symbol"] for r in entry_results["blocked"]}

        # 결과: ENTER 종목 + Filter 3 평가 안 된 종목만 남김
        result = []
        for c in candidates:
            code = c["code"]
            if code in blocked_codes:
                continue
            if code in enter_codes:
                # ENTER 종목의 confidence를 weight에 반영
                er = next((r for r in entry_results["enter"]
                           if r["symbol"] == code), None)
                if er and er.get("signal_strength") == "very_strong":
                    c = {**c, "weight": round(c["weight"] * 1.15, 4)}
                result.append(c)
            elif code not in trend_map:
                # trend_filter에 없었던 종목 → 그대로 통과
                result.append(c)
            # else: WAIT 종목 → 이번 사이클에서 제외 (다음 사이클에서 재평가)

        return result

    # ------------------------------------------------------------------
    # Filter 3: 재무 데이터 헬퍼
    # ------------------------------------------------------------------

    _WA_SECTOR_MAP = {
        "005930": "반도체", "000660": "반도체", "042700": "반도체",
        "373220": "2차전지", "006400": "2차전지",
        "096770": "화학", "010950": "화학",
    }
    _WA_SECTOR_AVG_PBR = {
        "반도체": 1.5, "2차전지": 2.5, "화학": 0.9,
        "자동차": 0.7, "바이오": 3.0, "은행": 0.5,
        "방산": 1.8, "IT": 2.0, "철강": 0.6, "건설": 0.7,
    }
    _WA_SECTOR_AVG_PER = {
        "반도체": 15.0, "2차전지": 30.0, "화학": 10.0,
        "자동차": 8.0, "바이오": 50.0, "은행": 6.0,
        "방산": 20.0, "IT": 25.0, "철강": 8.0, "건설": 7.0,
    }

    def _get_financial_data_for_filter(self, symbol):
        """DB에서 재무 데이터 조회 (캐시)."""
        if not hasattr(self, "_wa_fin_cache"):
            self._wa_fin_cache = {}
        if symbol not in self._wa_fin_cache:
            try:
                from database.db import get_financial_indicators
                self._wa_fin_cache[symbol] = get_financial_indicators(symbol)
            except Exception:
                self._wa_fin_cache[symbol] = None
        return self._wa_fin_cache.get(symbol)

    def _get_sector_avg_per_wa(self, symbol):
        sector = self._WA_SECTOR_MAP.get(symbol, "")
        return self._WA_SECTOR_AVG_PER.get(sector, 15.0)

    def _get_sector_avg_pbr_wa(self, symbol):
        sector = self._WA_SECTOR_MAP.get(symbol, "")
        return self._WA_SECTOR_AVG_PBR.get(sector, 1.2)

    def _check_fundamental_value(self, symbol):
        """신호 6: PBR < 업종평균 × 0.7이면 저평가 신호."""
        fin = self._get_financial_data_for_filter(symbol)
        if not fin or not fin.get("pbr"):
            return {"name": "펀더멘탈 저평가", "triggered": False,
                    "reason": "재무 데이터 없음"}
        pbr = float(fin["pbr"])
        sector_avg = self._get_sector_avg_pbr_wa(symbol)
        undervalued = 0 < pbr < sector_avg * 0.7
        roe = float(fin.get("roe", 0) or 0)
        quality_ok = roe > 5 if roe else True
        triggered = undervalued and quality_ok
        discount = f"{(1 - pbr / sector_avg) * 100:.0f}%" if sector_avg > 0 else "N/A"
        return {
            "name": "펀더멘탈 저평가", "triggered": triggered, "weight": 1.3,
            "details": {"pbr": round(pbr, 2), "sector_avg_pbr": round(sector_avg, 2),
                        "roe": round(roe, 1) if roe else None, "discount": discount},
            "reason": (f"PBR {pbr:.2f} < 업종평균 {sector_avg:.2f}×0.7 (저평가 {discount})"
                       if triggered else f"PBR {pbr:.2f} (적정 범위)"),
        }

    def _check_supply_demand_signal(self, symbol, stock_foreign_net, stock_institution_net):
        """신호 7: 외국인+기관 동시 순매수."""
        frgn = (stock_foreign_net or {}).get(symbol, 0) or 0
        inst = (stock_institution_net or {}).get(symbol, 0) or 0
        both_buy = frgn > 0 and inst > 0
        return {
            "name": "수급 동반매수", "triggered": both_buy, "weight": 1.2,
            "details": {"foreign_net": frgn, "institution_net": inst},
            "reason": (f"외국인({frgn:+,}) + 기관({inst:+,}) 동반 매수"
                       if both_buy else
                       f"동반 매수 아님 (외국인:{frgn:+,}, 기관:{inst:+,})"),
        }

    # ------------------------------------------------------------------
    # Filter 3: 진입 타이밍 필터 (Entry Timing)
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_rsi_simple(closes, period=14):
        """간단한 RSI 계산."""
        if len(closes) < period + 1:
            return 50.0
        deltas = [closes[i] - closes[i - 1] for i in range(-period, 0)]
        gains = sum(d for d in deltas if d > 0)
        losses = sum(-d for d in deltas if d < 0)
        avg_gain = gains / period
        avg_loss = losses / period
        if avg_loss == 0:
            return 100.0
        return round(100 - 100 / (1 + avg_gain / avg_loss), 2)

    @staticmethod
    def _calc_macd_local(closes, fast=12, slow=26, signal=9):
        """MACD 로컬 계산."""
        if len(closes) < slow + signal:
            return {"histogram": 0.0, "histogram_prev": 0.0}

        def _ema(data, p):
            m = 2 / (p + 1)
            r = [sum(data[:p]) / p]
            for i in range(p, len(data)):
                r.append((data[i] - r[-1]) * m + r[-1])
            return r

        fe = _ema(closes, fast)
        se = _ema(closes, slow)
        off = len(fe) - len(se)
        ml = [fe[off + i] - se[i] for i in range(len(se))]
        if len(ml) < signal:
            return {"histogram": 0.0, "histogram_prev": 0.0}
        sv = _ema(ml, signal)
        so = len(ml) - len(sv)
        hists = [ml[so + i] - sv[i] for i in range(len(sv))]
        return {
            "histogram":      hists[-1] if hists else 0.0,
            "histogram_prev": hists[-2] if len(hists) >= 2 else 0.0,
        }

    def _check_entry_blockers(self, symbol, price_data, trend_result,
                              stock_foreign_net=None, stock_institution_net=None):
        """
        어떤 신호가 있든 절대 진입하면 안 되는 조건을 체크한다.
        하나라도 해당하면 즉시 BLOCKED.
        """
        closes  = price_data["closes"]
        volumes = price_data["volumes"]
        blockers = []

        # 차단 1: 극심한 과매수 (RSI > 75)
        rsi = self._calc_rsi_simple(closes, 14)
        if rsi > 75:
            blockers.append({
                "type": "OVERBOUGHT",
                "reason": f"RSI {rsi:.1f} > 75 (극심한 과매수)",
                "severity": "HIGH",
            })

        # 차단 2: 당일 급등 추격 금지 (+5% 이상)
        if len(closes) >= 2:
            chg = (closes[-1] - closes[-2]) / closes[-2] * 100
            if chg > 5.0:
                blockers.append({
                    "type": "CHASING",
                    "reason": f"당일 {chg:.1f}% 급등 (추격 매수 금지)",
                    "severity": "HIGH",
                })

        # 차단 3: 비정상 거래량 (평균의 5배 이상)
        if len(volumes) >= 20:
            vol_avg = sum(volumes[-20:]) / 20
            if vol_avg > 0:
                vr = volumes[-1] / vol_avg
                if vr > 5.0:
                    blockers.append({
                        "type": "ABNORMAL_VOLUME",
                        "reason": f"거래량 {vr:.1f}배 (비정상)",
                        "severity": "MEDIUM",
                    })

        # 차단 4: 갭하락 발생 (-3% 이상 갭)
        opens = price_data.get("opens", closes)
        if len(opens) >= 2 and len(closes) >= 2:
            gap = (opens[-1] - closes[-2]) / closes[-2] * 100
            if gap < -3.0:
                blockers.append({
                    "type": "GAP_DOWN",
                    "reason": f"갭하락 {gap:.1f}% (악재 가능성)",
                    "severity": "MEDIUM",
                })

        # 차단 5: 5일 연속 하락 (낙하 나이프)
        if len(closes) >= 6:
            if all(closes[-i] < closes[-i - 1] for i in range(1, 6)):
                drop = (closes[-1] - closes[-6]) / closes[-6] * 100
                blockers.append({
                    "type": "FALLING_KNIFE",
                    "reason": f"5일 연속 하락 ({drop:.1f}%)",
                    "severity": "HIGH",
                })

        # 차단 6~8: 펀더멘탈 기반 (재무 데이터 있을 때만)
        fin = self._get_financial_data_for_filter(symbol)
        if fin:
            # 차단 6: 극심한 고평가 (PER > 업종평균 × 3)
            per = fin.get("per", 0)
            if per and per > 0:
                sector_avg_per = self._get_sector_avg_per_wa(symbol)
                if sector_avg_per > 0 and per > sector_avg_per * 3:
                    blockers.append({
                        "type": "OVERVALUED_PER",
                        "reason": f"PER {per:.1f} > 업종평균({sector_avg_per:.1f})의 3배",
                        "severity": "MEDIUM",
                    })

            # 차단 7: 적자 기업 (ROE < 0)
            roe = fin.get("roe")
            if roe is not None and roe < 0:
                blockers.append({
                    "type": "NEGATIVE_ROE",
                    "reason": f"ROE {roe:.1f}% (적자 기업)",
                    "severity": "MEDIUM",
                })

            # 차단 8: 고부채 (부채비율 > 300%)
            debt = fin.get("debt_ratio")
            if debt is not None and debt > 300:
                blockers.append({
                    "type": "HIGH_DEBT",
                    "reason": f"부채비율 {debt:.0f}% > 300%",
                    "severity": "MEDIUM",
                })

        # 차단 9: 외국인+기관 동시 순매도
        frgn = (stock_foreign_net or {}).get(symbol, 0) or 0
        inst = (stock_institution_net or {}).get(symbol, 0) or 0
        if frgn < 0 and inst < 0:
            blockers.append({
                "type": "DUAL_SELLING",
                "reason": f"외국인({frgn:+,}) + 기관({inst:+,}) 동시 순매도",
                "severity": "MEDIUM",
            })

        return blockers

    def _check_rsi_bounce(self, closes):
        """신호 1: RSI가 과매도 영역(30~45)에서 반등 시작."""
        if len(closes) < 16:
            return {"name": "RSI 반등", "triggered": False, "reason": "데이터 부족"}
        rsi_now  = self._calc_rsi_simple(closes, 14)
        rsi_prev = self._calc_rsi_simple(closes[:-1], 14)
        triggered = (30 <= rsi_now <= 45) and (rsi_now > rsi_prev)
        return {
            "name": "RSI 반등", "triggered": triggered, "weight": 1.0,
            "details": {"rsi_current": round(rsi_now, 1),
                        "rsi_previous": round(rsi_prev, 1)},
            "reason": (f"RSI {rsi_now:.1f} (이전 {rsi_prev:.1f}에서 반등)"
                       if triggered else f"RSI {rsi_now:.1f} (조건 미충족)"),
        }

    def _check_ma_support(self, current_price, trend_result):
        """신호 2: 가격이 20MA 또는 50MA에 접근(±2%)한 상태."""
        ma_vals = (trend_result.get("details", {})
                   .get("ma_alignment", {}).get("values", {}))
        ma_20 = ma_vals.get("ma_20", 0)
        ma_50 = ma_vals.get("ma_50", 0)
        if ma_20 == 0:
            return {"name": "MA 지지", "triggered": False, "reason": "MA 데이터 없음"}
        dist_20 = (current_price - ma_20) / ma_20 * 100 if ma_20 > 0 else 999
        dist_50 = (current_price - ma_50) / ma_50 * 100 if ma_50 > 0 else 999
        near_20 = -2.0 <= dist_20 <= 1.5
        near_50 = -2.0 <= dist_50 <= 1.5
        triggered = near_20 or near_50
        lvl = "20MA" if near_20 else ("50MA" if near_50 else "없음")
        return {
            "name": "MA 지지", "triggered": triggered, "weight": 1.2,
            "details": {"dist_from_20ma_pct": round(dist_20, 2),
                        "dist_from_50ma_pct": round(dist_50, 2),
                        "support_level": lvl},
            "reason": (f"{lvl} 지지 접근 (거리 {min(abs(dist_20), abs(dist_50)):.1f}%)"
                       if triggered else
                       f"MA 지지선에서 먼 상태 (20MA: {dist_20:+.1f}%, 50MA: {dist_50:+.1f}%)"),
        }

    def _check_volume_candle(self, closes, opens, volumes):
        """신호 3: 오늘이 양봉 + 거래량 평균 1.3배 이상."""
        if len(closes) < 21 or len(volumes) < 21:
            return {"name": "거래량 양봉", "triggered": False, "reason": "데이터 부족"}
        cur_close = closes[-1]
        cur_open  = opens[-1] if opens else closes[-2]
        bullish   = cur_close > cur_open
        body_pct  = (cur_close - cur_open) / cur_open * 100 if cur_open > 0 else 0
        vol_avg   = sum(volumes[-21:-1]) / 20
        vr        = volumes[-1] / vol_avg if vol_avg > 0 else 1.0
        triggered = bullish and vr >= 1.3 and body_pct >= 0.3
        return {
            "name": "거래량 양봉", "triggered": triggered, "weight": 1.0,
            "details": {"candle": "양봉" if bullish else "음봉",
                        "body_pct": round(body_pct, 2), "volume_ratio": round(vr, 2)},
            "reason": (f"양봉(+{body_pct:.1f}%) + 거래량 {vr:.1f}배"
                       if triggered else
                       f"{'음봉' if not bullish else f'거래량 부족({vr:.1f}배)'}"),
        }

    def _check_macd_cross(self, closes):
        """신호 4: MACD 히스토그램 음→양 전환 또는 양수 확대."""
        if len(closes) < 35:
            return {"name": "MACD 크로스", "triggered": False, "reason": "데이터 부족"}
        macd      = self._calc_macd_local(closes)
        hist      = macd["histogram"]
        hist_prev = macd["histogram_prev"]
        golden    = hist > 0 and hist_prev <= 0
        mom_up    = hist > 0 and hist > hist_prev
        triggered = golden or mom_up
        sig_type  = "골든크로스" if golden else ("모멘텀 강화" if mom_up else "없음")
        return {
            "name": "MACD 크로스", "triggered": triggered,
            "weight": 1.0 if golden else 0.7,
            "details": {"histogram": round(hist, 4),
                        "histogram_prev": round(hist_prev, 4),
                        "signal_type": sig_type},
            "reason": (f"MACD {sig_type} (hist: {hist_prev:.3f}→{hist:.3f})"
                       if triggered else f"MACD 하락 모멘텀 (hist: {hist:.3f})"),
        }

    def _check_us_leading_signal(self, symbol, leading_indicators):
        """
        신호 5: 전일 밤 US 시장에서 관련 섹터 상승.
        leading_indicators = analyze_leading_indicators() 반환 리스트.
        """
        if not leading_indicators:
            return {"name": "US 선행신호", "triggered": False,
                    "weight": 0, "reason": "선행지표 데이터 없음"}

        # active_signals 리스트에서 US 시장 상태 추론
        buy_signals  = [s for s in leading_indicators if s.get("direction") == "BUY"]
        sell_signals = [s for s in leading_indicators
                        if s.get("direction") in ("SELL", "AVOID")]

        us_score = 0
        detail_parts = []

        # BUY 신호가 2개 이상이면 US 전반 양호 (+1)
        if len(buy_signals) >= 2:
            us_score += 1
            detail_parts.append(f"BUY신호 {len(buy_signals)}개")

        # SELL/AVOID 신호가 없으면 안전 (+1)
        if len(sell_signals) == 0:
            us_score += 1
            detail_parts.append("위험신호 없음")

        # 종목의 섹터와 관련된 BUY 신호 존재 (+1)
        # 종목코드 → 섹터 매핑 (stock_classification에서 가져옴)
        stock_sectors = set()
        try:
            stock_sectors = set(self._classification.get_sectors_for_stock(symbol))
        except Exception:
            pass
        sector_match = False
        for sig in buy_signals:
            sig_sectors = set(sig.get("kr_sectors", []))
            if sig_sectors & stock_sectors:
                sector_match = True
                break
        if sector_match:
            us_score += 1
            detail_parts.append("관련섹터 BUY")

        # 강한 BUY 신호(strength > 1.5) 존재 (+1)
        strong_buys = [s for s in buy_signals if s.get("strength", 0) > 1.5]
        if strong_buys:
            us_score += 1
            detail_parts.append(f"강력BUY {len(strong_buys)}개")

        triggered = us_score >= 2

        return {
            "name": "US 선행신호", "triggered": triggered, "weight": 1.1,
            "details": {"us_score": f"{us_score}/4",
                        "buy_signals": len(buy_signals),
                        "sell_signals": len(sell_signals),
                        "sector_match": sector_match},
            "reason": (f"US 양호 ({us_score}/4): {', '.join(detail_parts)}"
                       if triggered else
                       f"US 부진 ({us_score}/4)"),
        }

    @staticmethod
    def _get_required_signals(market_phase=None):
        """시장 국면에 따라 진입에 필요한 최소 신호 수를 조정한다."""
        required = {
            "대상승장": 1, "상승장": 2, "일반장": 2,
            "변동폭큰": 3, "하락장": 3, "대폭락장": 4,
        }
        return required.get(market_phase, 2)

    def check_entry_timing(self, symbol, price_data, trend_result,
                           leading_indicators=None, market_phase=None,
                           stock_foreign_net=None, stock_institution_net=None):
        """
        Filter 2를 통과한 종목에 대해 지금이 좋은 진입 시점인지 판단한다.
        반환: {symbol, entry_allowed, entry_decision, signal_count,
               signal_strength, signals, blockers, confidence, reason}
        """
        closes  = price_data["closes"]
        opens   = price_data.get("opens", closes)

        # 0단계: 진입 금지 조건 (최우선)
        blockers = self._check_entry_blockers(
            symbol, price_data, trend_result,
            stock_foreign_net=stock_foreign_net,
            stock_institution_net=stock_institution_net)
        if blockers:
            return {
                "symbol": symbol, "entry_allowed": False,
                "entry_decision": "BLOCKED", "signal_count": 0,
                "signal_strength": "none", "signals": [],
                "blockers": blockers, "confidence": 0.0,
                "reason": f"진입 금지: {blockers[0]['reason']}",
            }

        # 1단계: 7개 진입 신호 평가
        total_signals = 7
        signals = []
        for chk in [
            self._check_rsi_bounce(closes),
            self._check_ma_support(closes[-1], trend_result),
            self._check_volume_candle(closes, opens, price_data["volumes"]),
            self._check_macd_cross(closes),
            self._check_us_leading_signal(symbol, leading_indicators),
            self._check_fundamental_value(symbol),
            self._check_supply_demand_signal(symbol, stock_foreign_net, stock_institution_net),
        ]:
            if chk["triggered"]:
                signals.append(chk)

        # 2단계: 종합 판정
        sig_count = len(signals)
        required  = self._get_required_signals(market_phase)
        allowed   = sig_count >= required

        if sig_count >= 5:
            strength = "very_strong"
        elif sig_count >= 3:
            strength = "strong"
        elif sig_count >= required:
            strength = "normal"
        else:
            strength = "weak"

        trend_sc   = trend_result.get("trend_score", 0.5)
        confidence = round(trend_sc * 0.4 + (sig_count / total_signals) * 0.6, 3)

        if allowed:
            names = [s["name"] for s in signals]
            reason = (f"진입 허용: {sig_count}개 신호 "
                      f"({', '.join(names)}). 확신도 {confidence:.0%}")
            decision = "ENTER"
        else:
            reason = (f"대기: {sig_count}/{required}개 신호. "
                      f"다음 체크에서 재평가")
            decision = "WAIT"

        return {
            "symbol": symbol, "entry_allowed": allowed,
            "entry_decision": decision, "signal_count": sig_count,
            "signal_strength": strength, "signals": signals,
            "blockers": [], "confidence": confidence, "reason": reason,
        }

    def check_entry_timing_batch(self, trend_passed_stocks,
                                 leading_indicators=None,
                                 market_phase=None,
                                 stock_foreign_net=None,
                                 stock_institution_net=None):
        """
        Filter 2를 통과한 종목들에 대해 일괄 진입 타이밍 평가.
        반환: {enter: [...], wait: [...], blocked: [...], summary: {...}}
        """
        enter, wait, blocked = [], [], []

        for stock in trend_passed_stocks:
            r = self.check_entry_timing(
                symbol=stock["symbol"],
                price_data=stock["price_data"],
                trend_result=stock["trend_result"],
                leading_indicators=leading_indicators,
                market_phase=market_phase,
                stock_foreign_net=stock_foreign_net,
                stock_institution_net=stock_institution_net,
            )
            if r["entry_decision"] == "ENTER":
                enter.append(r)
            elif r["entry_decision"] == "BLOCKED":
                blocked.append(r)
            else:
                wait.append(r)

        enter.sort(key=lambda x: x["confidence"], reverse=True)
        total = len(enter) + len(wait) + len(blocked)

        return {
            "enter": enter, "wait": wait, "blocked": blocked,
            "summary": {
                "total": total, "enter": len(enter),
                "wait": len(wait), "blocked": len(blocked),
                "required_signals": self._get_required_signals(market_phase),
                "phase": market_phase or "기본",
            },
        }

    def _load_entry_price_data(self, history_symbol):
        """히스토리 CSV에서 OHLCV 로드 (Filter 3 진입 판단용)."""
        from data.history.history_loader import _SYMBOL_MAP
        import pandas as pd

        path = _SYMBOL_MAP.get(history_symbol)
        if path is None or not path.exists():
            return None
        try:
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            col_map = {}
            for c in df.columns:
                cl = c.lower().strip()
                if cl in ("시가", "open"):
                    col_map["open"] = c
                elif cl in ("고가", "high"):
                    col_map["high"] = c
                elif cl in ("저가", "low"):
                    col_map["low"] = c
                elif cl in ("종가", "close"):
                    col_map["close"] = c
                elif cl in ("거래량", "volume"):
                    col_map["volume"] = c
            needed = {"high", "low", "close", "volume"}
            if not needed.issubset(col_map):
                return None
            df = df.dropna(subset=[col_map[k] for k in needed])
            tail = df.tail(min(len(df), 250))
            result = {
                "closes":  tail[col_map["close"]].astype(float).tolist(),
                "highs":   tail[col_map["high"]].astype(float).tolist(),
                "lows":    tail[col_map["low"]].astype(float).tolist(),
                "volumes": tail[col_map["volume"]].astype(float).tolist(),
            }
            if "open" in col_map:
                result["opens"] = tail[col_map["open"]].astype(float).tolist()
            return result
        except Exception:
            return None

    # ------------------------------------------------------------------
    # 선제 매도 / 포지션 축소
    # ------------------------------------------------------------------

    def _get_preemptive_sell_targets(self, sell_signals: list) -> list:
        """
        미국 하락 SELL 신호에 해당하는 한국 섹터 보유 종목을 매도 대상으로 반환.

        sell_signals: [{"signal_id": "sox_crash", "kr_sectors": ["반도체"], "kr_themes": [...], ...}]
        """
        sell_sectors: set = set()
        sell_themes: set = set()
        for sig in sell_signals:
            for s in sig.get("kr_sectors", []):
                sell_sectors.add(s)
            for t in sig.get("kr_themes", []):
                sell_themes.add(t)

        if not sell_sectors and not sell_themes:
            return []

        # stock_classification.json에서 종목→섹터/테마 매핑 로드
        import json
        cls_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "stock_classification.json",
        )
        try:
            with open(cls_path, encoding="utf-8") as f:
                cls_data = json.load(f)
            stock_map = cls_data.get("stocks", {})
        except Exception:
            stock_map = {}

        open_positions = self._position_manager.get_open_positions()
        targets = []
        for pos in open_positions:
            code = pos.get("code", "")
            info = stock_map.get(code, {})
            stock_sector = info.get("sector", [])
            stock_themes = info.get("themes", [])

            sector_list = stock_sector if isinstance(stock_sector, list) else [stock_sector]
            theme_list  = stock_themes if isinstance(stock_themes, list) else [stock_themes]

            sector_match = bool(sell_sectors & set(sector_list))
            theme_match  = bool(sell_themes  & set(theme_list))

            if sector_match or theme_match:
                targets.append({
                    "code":        code,
                    "name":        pos.get("name", ""),
                    "position_id": pos.get("id", ""),
                    "avg_price":   float(pos.get("avg_price", 0)),
                    "quantity":    int(pos.get("quantity", 0)),
                    "sell_reason": "PREEMPTIVE_SELL",
                })

        return targets

    def _get_reduce_targets(self, reduce_pct: int) -> list:
        """
        전체 보유 포지션에서 reduce_pct% 만큼의 수량을 매도 대상으로 반환.
        전량 매도가 되는 케이스(sell_qty >= quantity)는 건너뜀.
        """
        open_positions = self._position_manager.get_open_positions()
        targets = []
        ratio = reduce_pct / 100.0
        for pos in open_positions:
            quantity = int(pos.get("quantity", 0))
            sell_qty = max(1, int(quantity * ratio))
            if sell_qty >= quantity:
                continue  # 전량 매도가 되면 REDUCE 아님
            targets.append({
                "code":        pos.get("code", ""),
                "name":        pos.get("name", ""),
                "position_id": pos.get("id", ""),
                "avg_price":   float(pos.get("avg_price", 0)),
                "quantity":    sell_qty,
                "sell_reason": "REDUCE_POSITION",
            })
        return targets

    # ------------------------------------------------------------------
    # 백테스팅 시그널 매트릭스 기반 종목 선정
    # ------------------------------------------------------------------

    def _get_signal_service_candidates(
        self,
        active_signals: list,
        avoid_sectors: set,
        aggressive_pct: float,
    ) -> list:
        """
        SignalService에서 종목별 시그널을 조회하여 candidates 리스트를 구성한다.
        시그널이 없거나 SignalService 장애 시 빈 리스트를 반환 (기존 섹터 매핑 폴백 유도).

        반환 형식은 기존 candidates와 동일 + 시그널 메타 필드:
        [{"code", "name", "weight", "sector",
          "signal_source", "signal_confidence", "signal_trigger",
          "size_factor", "win_rate", "expected_return"}, ...]
        """
        try:
            buy_signals = [s for s in active_signals if s.get("direction") == "BUY"]
            if not buy_signals:
                return []

            all_candidates: list = []
            seen_codes: set = set()

            self.log("info", f"시그널 매트릭스 조회 시작: BUY 신호 {len(buy_signals)}개")
            for sig in buy_signals:
                signal_id = sig.get("signal_id", "")
                parsed = SignalService.parse_signal_id(signal_id)
                if parsed is None:
                    self.log("info", f"시그널 매트릭스: {signal_id} 매핑 없음 → skip")
                    continue

                indicator_id, event_direction = parsed
                stock_signals = self._signal_service.get_signals_by_indicator(
                    indicator_id=indicator_id,
                    direction=event_direction,
                    min_confidence="★★",
                )
                self.log("info", f"시그널 매트릭스: {signal_id} → {indicator_id}/{event_direction} → {len(stock_signals)}종목")

                trigger_key = f"{indicator_id}_{event_direction}"
                for s in stock_signals:
                    code = s["stock_code"]
                    sector = s.get("sector", "")

                    # AVOID 섹터 필터
                    if sector in avoid_sectors:
                        continue

                    # 진입 불가 신뢰도 필터
                    if s["position_size_factor"] <= 0:
                        continue

                    if code in seen_codes:
                        # 중복 종목은 더 높은 size_factor 사용
                        for c in all_candidates:
                            if c["code"] == code:
                                if s["position_size_factor"] > c.get("size_factor", 0):
                                    c["size_factor"] = s["position_size_factor"]
                                    c["signal_confidence"] = s["confidence"]
                                    c["signal_trigger"] = trigger_key
                                break
                        continue

                    seen_codes.add(code)

                    # weight = aggressive_pct를 종목 수로 나눈 후 size_factor 적용
                    # (나중에 정규화하므로 여기서는 size_factor를 raw weight로 사용)
                    raw_weight = aggressive_pct * s["position_size_factor"]

                    all_candidates.append({
                        "code": code,
                        "name": s["stock_name"],
                        "weight": round(raw_weight, 4),
                        "sector": sector,
                        "signal_source": "backtest_signal",
                        "signal_confidence": s["confidence"],
                        "signal_trigger": trigger_key,
                        "size_factor": s["position_size_factor"],
                        "win_rate": s["win_rate"],
                        "expected_return": s["mean_excess_return"],
                    })

            if not all_candidates:
                return []

            # 충돌 시그널 제거: 같은 종목에 buy와 sell이 동시에 있으면 스킵
            all_candidates = self._resolve_signal_conflicts(all_candidates, active_signals)

            return all_candidates

        except Exception as exc:
            self.log("warning", f"시그널 매트릭스 조회 실패 (폴백): {exc}")
            return []

    def _resolve_signal_conflicts(self, candidates: list, active_signals: list) -> list:
        """같은 종목에 buy와 sell 시그널이 동시에 있으면 제거."""
        # SELL 신호가 있는 종목코드 수집
        sell_codes: set = set()
        sell_signals = [s for s in active_signals if s.get("direction") == "SELL"]
        for sig in sell_signals:
            signal_id = sig.get("signal_id", "")
            parsed = SignalService.parse_signal_id(signal_id)
            if parsed is None:
                continue
            indicator_id, event_direction = parsed
            sell_stock_signals = self._signal_service.get_signals_by_indicator(
                indicator_id=indicator_id,
                direction=event_direction,
                min_confidence="★★",
            )
            for s in sell_stock_signals:
                if s["signal_direction"] == "sell":
                    sell_codes.add(s["stock_code"])

        if not sell_codes:
            return candidates

        resolved = []
        for c in candidates:
            if c["code"] in sell_codes:
                self.log("warning",
                         f"시그널 충돌: {c['name']}({c['code']}) — buy/sell 동시 발생, 스킵")
                continue
            resolved.append(c)
        return resolved

    # ------------------------------------------------------------------
    # reason 텍스트 생성
    # ------------------------------------------------------------------

    def _build_reason(
        self,
        phase: str,
        direction: str,
        active_signals: list,
        weight_config: dict,
    ) -> str:
        """
        "[급등장] SOX 급등(+3.8%) → 반도체 BUY 신호. 공격 비중 100% 적용." 형식의
        reason 텍스트를 생성한다.
        """
        aggressive_pct = weight_config["aggressive_pct"]
        cash_pct       = weight_config["cash_pct"]

        buy_signals  = [s for s in active_signals if s.get("direction") == "BUY"]
        avoid_signals = [s for s in active_signals if s.get("direction") == "AVOID"]

        parts: list = [f"[{phase}]"]

        if direction == "HOLD":
            if phase in _HOLD_PHASES:
                parts.append(f"국면({phase}) → 매매 보류.")
            elif not buy_signals:
                parts.append("BUY 신호 없음 → 매매 보류.")
            else:
                parts.append(
                    f"AVOID 신호 우세({len(avoid_signals)}개) > BUY 신호({len(buy_signals)}개) → 매매 보류."
                )
            parts.append(f"현금 비중 {cash_pct * 100:.0f}% 유지.")
        else:
            # BUY direction
            signal_descs: list = []
            for sig in buy_signals[:3]:  # 최대 3개 신호 표기
                sig_id   = sig.get("signal_id", "")
                value    = sig.get("value", 0.0)
                sectors  = sig.get("kr_sectors", [])
                sector_str = "/".join(sectors) if sectors else "전반"
                signal_descs.append(
                    f"{sig_id}(+{value:.1f}%) → {sector_str} BUY 신호"
                )
            if signal_descs:
                parts.append(". ".join(signal_descs) + ".")
            parts.append(f"공격 비중 {aggressive_pct * 100:.0f}% 적용.")
            if cash_pct > 0:
                parts.append(f"현금 {cash_pct * 100:.0f}% 유보.")

        return " ".join(parts)
