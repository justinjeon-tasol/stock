"""
로직적용 에이전트 모듈.
WeightAdjuster의 SIGNAL을 받아 전략 라이브러리의 검증된 전략을 적용한다.
전략 선택, 진입 조건 정제, 제외 조건 적용, strategy_id 태깅을 담당한다.

파이프라인 위치: WeightAdjuster(WA) → LogicApplier(LA) → Executor(EX)
"""

import glob
import json
import logging
import os
from typing import Optional

from agents.base_agent import BaseAgent
from protocol.protocol import StandardMessage

logger = logging.getLogger(__name__)

# 전략 라이브러리 루트
_LIBRARY_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "strategy_library",
)

# 전략 상태 우선순위 (높을수록 우선 선택)
_STATUS_PRIORITY = {
    "실전검증완료": 4,
    "검증완료":    3,
    "백테스팅중":  2,
    "비활성":     0,
}

# 전략 그룹 → 선호 섹터/테마 매핑
_GROUP_SECTOR_MAP = {
    "미국지수":   ["지수ETF", "코스닥ETF"],
    "환율매크로": ["수출주", "반도체", "자동차"],
    "섹터연계":   ["반도체", "AI/HBM", "2차전지"],
    "시장국면":   [],   # 국면 전략은 섹터 무관
    "타이밍":     [],
}

# 제외 조건 키워드 → issue_id 매핑 (이슈 감지 시 전략 제외)
_EXCLUSION_ISSUE_MAP = {
    "금 강세":   "ISS_003",   # 지정학 (금+WTI 동반 급등)
    "VIX 25":   "ISS_001",   # VIX 이슈
    "VIX 30":   "ISS_001",
    "달러 강세": "ISS_002",
    "외국인 순매도": "ISS_006",
}


class LogicApplier(BaseAgent):
    """
    검증된 전략을 실전에 적용하는 에이전트.
    SIGNAL → 전략 선택/정제 → SIGNAL (to EX)
    """

    def __init__(self) -> None:
        super().__init__("LA", "로직적용", timeout=2, max_retries=3)
        self._library: dict[str, dict] = {}
        self._load_library()

    # ------------------------------------------------------------------
    # 라이브러리 로드
    # ------------------------------------------------------------------

    def _load_library(self) -> None:
        """전략 라이브러리 전체 로드."""
        pattern = os.path.join(_LIBRARY_ROOT, "**", "*.json")
        files   = glob.glob(pattern, recursive=True)
        for fp in files:
            try:
                with open(fp, encoding="utf-8") as f:
                    card = json.load(f)
                sid = card.get("id")
                if sid:
                    self._library[sid] = card
            except Exception as exc:
                logger.warning("[로직적용] 전략 로드 실패 %s: %s", fp, exc)
        self.log("info", f"전략 라이브러리 로드: {len(self._library)}개")

    # ------------------------------------------------------------------
    # BaseAgent 구현
    # ------------------------------------------------------------------

    async def execute(self, input_data: Optional[StandardMessage] = None) -> StandardMessage:
        """
        SIGNAL을 받아 전략을 적용한 뒤 정제된 SIGNAL을 반환한다.

        입력 (WeightAdjuster SIGNAL payload):
            phase, direction, targets, sell_targets, confidence,
            issue_factor, weight_config, reason

        출력 (refined SIGNAL payload):
            - 동일 구조 유지
            - strategy_id, strategy_name, strategy_group 추가
            - targets: 제외 조건 통과 + 전략 우선순위 정렬
            - reason: 전략 적용 근거 보완
        """
        self.log("info", "로직적용 시작")

        if input_data is None:
            return self._passthrough({}, reason="입력 없음")

        payload   = input_data.body.get("payload", {})
        phase     = payload.get("phase", "일반장")
        direction = payload.get("direction", "HOLD")
        targets   = payload.get("targets", [])
        issue_factor = payload.get("issue_factor")

        # 1. 현재 국면에 맞는 전략 선택
        strategy = self._select_strategy(phase)

        if strategy:
            sid   = strategy["id"]
            sname = strategy.get("description", "")
            sgrp  = strategy.get("group", "")
            self.log("info", f"전략 선택: {sid} ({sname[:30]}) [{sgrp}]")
        else:
            sid, sname, sgrp = None, "", ""
            self.log("info", f"'{phase}' 국면 적용 가능 전략 없음 - SIGNAL 원본 전달")

        # 2. BUY 방향일 때만 전략 조건 적용
        if direction == "BUY" and strategy:
            # 2a. 제외 조건 확인 (issue_factor 기반)
            excluded, exclude_reason = self._check_exclusions(strategy, issue_factor)
            if excluded:
                # 제외 조건 발동 시 방향을 HOLD로 전환
                direction = "HOLD"
                targets   = []
                self.log("warning", f"전략 제외 조건 발동: {exclude_reason} → HOLD 전환")
            else:
                # 2b. 전략 선호 섹터 기반 타겟 정렬
                targets = self._prioritize_targets(targets, strategy)

        # 3. 전략 정보 페이로드에 추가
        refined = dict(payload)
        refined["direction"]      = direction
        refined["targets"]        = targets
        refined["strategy_id"]    = sid
        refined["strategy_name"]  = sname
        refined["strategy_group"] = sgrp
        refined["reason"]         = self._enrich_reason(
            payload.get("reason", ""), strategy, direction
        )

        msg = self.create_message(
            to="EX",
            data_type="SIGNAL",
            payload=refined,
            msg_type="SIGNAL",
            priority="HIGH" if direction == "BUY" else "NORMAL",
        )
        msg.status = {"code": "OK", "message": f"전략 적용: {sid or '없음'} / {direction}"}
        self.log("info", f"로직적용 완료: strategy={sid} direction={direction} targets={len(targets)}종목")
        return msg

    # ------------------------------------------------------------------
    # 전략 선택
    # ------------------------------------------------------------------

    def _select_strategy(self, phase: str) -> Optional[dict]:
        """
        현재 국면에서 가장 적합한 전략 하나를 선택한다.

        선택 기준:
        1. phase 일치
        2. 상태 우선순위 (실전검증완료 > 검증완료 > 백테스팅중)
        3. 동 순위면 backtest_win_rate 높은 순
        """
        candidates = [
            c for c in self._library.values()
            if c.get("phase") == phase
            and _STATUS_PRIORITY.get(c.get("performance", {}).get("status", ""), 0) > 0
        ]
        if not candidates:
            return None

        candidates.sort(
            key=lambda c: (
                _STATUS_PRIORITY.get(c.get("performance", {}).get("status", ""), 0),
                c.get("performance", {}).get("backtest_win_rate", 0.0),
            ),
            reverse=True,
        )
        return candidates[0]

    # ------------------------------------------------------------------
    # 제외 조건 체크
    # ------------------------------------------------------------------

    def _check_exclusions(
        self, strategy: dict, issue_factor: Optional[dict]
    ) -> tuple[bool, str]:
        """
        전략 제외 조건을 이슈 팩터와 대조한다.

        Returns
        -------
        (excluded: bool, reason: str)
        """
        exclusion_text = strategy.get("conditions", {}).get("제외", "")
        if not exclusion_text or "해당 없음" in exclusion_text:
            return False, ""

        if issue_factor is None:
            return False, ""

        active_issue_ids = {
            i["issue_id"]
            for i in issue_factor.get("issues", [])
        }

        for keyword, issue_id in _EXCLUSION_ISSUE_MAP.items():
            if keyword in exclusion_text and issue_id in active_issue_ids:
                return True, f"'{keyword}' 제외 조건 & {issue_id} 활성"

        return False, ""

    # ------------------------------------------------------------------
    # 타겟 우선순위 정렬
    # ------------------------------------------------------------------

    def _prioritize_targets(self, targets: list, strategy: dict) -> list:
        """
        전략 그룹이 선호하는 섹터/테마 종목을 앞으로 정렬.
        weight는 변경하지 않고 순서만 조정.
        """
        group          = strategy.get("group", "")
        preferred_secs = _GROUP_SECTOR_MAP.get(group, [])

        if not preferred_secs:
            return targets

        def _priority(t: dict) -> int:
            sector = t.get("sector", "")
            theme  = t.get("theme", "")
            for pref in preferred_secs:
                if pref in sector or pref in theme:
                    return 0   # 선호 섹터 → 앞
            return 1

        return sorted(targets, key=_priority)

    # ------------------------------------------------------------------
    # reason 보강
    # ------------------------------------------------------------------

    def _enrich_reason(
        self, original_reason: str, strategy: Optional[dict], direction: str
    ) -> str:
        """원본 reason에 전략 적용 근거를 추가한다."""
        if not strategy:
            return original_reason

        sid   = strategy["id"]
        sname = strategy.get("description", "")[:40]
        perf  = strategy.get("performance", {})
        status     = perf.get("status", "")
        win_rate   = perf.get("backtest_win_rate", 0.0)
        return_pct = perf.get("backtest_return_pct", 0.0)

        addon = (
            f" | 전략 {sid}({sname}) [{status}]"
            f" 승률={win_rate*100:.0f}% 수익률={return_pct:+.1f}%"
        )
        return original_reason + addon

    # ------------------------------------------------------------------
    # 원본 전달 (전략 없을 때)
    # ------------------------------------------------------------------

    def _passthrough(self, payload: dict, reason: str = "") -> StandardMessage:
        """전략 적용 없이 SIGNAL을 그대로 EX로 전달."""
        payload["strategy_id"]    = None
        payload["strategy_name"]  = ""
        payload["strategy_group"] = ""
        msg = self.create_message(
            to="EX", data_type="SIGNAL", payload=payload, msg_type="SIGNAL",
        )
        msg.status = {"code": "OK", "message": reason or "passthrough"}
        return msg

    # ------------------------------------------------------------------
    # 공개 유틸리티
    # ------------------------------------------------------------------

    def list_strategies_for_phase(self, phase: str) -> list:
        """특정 국면의 전략 목록 반환 (상태 우선순위 정렬)."""
        candidates = [
            c for c in self._library.values() if c.get("phase") == phase
        ]
        candidates.sort(
            key=lambda c: (
                _STATUS_PRIORITY.get(c.get("performance", {}).get("status", ""), 0),
                c.get("performance", {}).get("backtest_win_rate", 0.0),
            ),
            reverse=True,
        )
        return candidates

    def get_strategy(self, strategy_id: str) -> Optional[dict]:
        """전략 카드 단건 조회."""
        return self._library.get(strategy_id)

    def reload_library(self) -> int:
        """전략 라이브러리를 디스크에서 다시 로드한다."""
        self._library.clear()
        self._load_library()
        return len(self._library)
