"""
전략엔진 에이전트 (SR).
실시간 전략 적용 + 주기적 백테스팅 + 자동 비활성화를 통합한다.

듀얼 모드:
  - SIGNAL       → 실시간 전략 적용 (파이프라인, 기존 LA 로직)
  - BACKTEST_TRIGGER → 일일 백테스팅 (장 종료 후, 자동 비활성화)
  - None         → 전체 백테스팅 (독립 실행)

파이프라인 위치: WeightAdjuster(WA) → StrategyEngine(SR) → Executor(EX)
백테스팅 트리거: Orchestrator → StrategyEngine (AFTER_HOURS)
"""

import glob
import json
import os
from datetime import date, datetime
from typing import Optional

from agents.base_agent import BaseAgent
from protocol.protocol import StandardMessage

# 전략 라이브러리 루트
_LIBRARY_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "strategy_library"
)

# 국면 → 폴더명 매핑
_PHASE_TO_FOLDER = {
    "안정화":   "안정화구간",
    "급등장":   "급등구간",
    "급락장":   "급락구간",
    "변동폭큰": "변동큰구간",
}

# 백테스팅 채택 기준 (수수료 0.5% 감안, 실질 수익 보장)
_MIN_WIN_RATE          = 0.58    # 58% 이상
_MIN_AVG_RETURN        = 2.0    # 평균 수익 2% 이상
_MAX_MDD               = -10.0  # MDD -10% 이내
_MIN_PERIODS           = 3
_MIN_TRADES_PER_PERIOD = 5

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
    "시장국면":   [],
    "타이밍":     [],
    "데이터기반": [],
}

# 제외 조건 키워드 → issue_id 매핑
_EXCLUSION_ISSUE_MAP = {
    "금 강세":       "ISS_003",
    "VIX 25":       "ISS_001",
    "VIX 30":       "ISS_001",
    "달러 강세":     "ISS_002",
    "외국인 순매도": "ISS_006",
}


class StrategyEngine(BaseAgent):
    """
    통합 전략 엔진: 실시간 적용 + 백테스팅 + 자동 비활성화.
    """

    def __init__(self):
        super().__init__("SR", "전략엔진", timeout=60, max_retries=2)
        self._library: dict[str, dict] = {}
        self._load_library_from_disk()

    # ==================================================================
    # 라이브러리 로드
    # ==================================================================

    def _load_library_from_disk(self) -> None:
        pattern = os.path.join(_LIBRARY_ROOT, "**", "*.json")
        files = glob.glob(pattern, recursive=True)
        for filepath in files:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    card = json.load(f)
                strategy_id = card.get("id")
                if strategy_id:
                    self._library[strategy_id] = card
            except Exception as e:
                self.log("warning", f"전략 파일 파싱 실패 {filepath}: {e}")
        self.log("info", f"전략 라이브러리 로드: {len(self._library)}개")

    def _phase_to_folder(self, phase: str) -> str:
        return _PHASE_TO_FOLDER.get(phase, "안정화구간")

    # ==================================================================
    # 메인 디스패치
    # ==================================================================

    async def execute(self, input_data: Optional[StandardMessage] = None) -> StandardMessage:
        if input_data is None:
            return await self._run_full_backtest_cycle()

        data_type = input_data.body.get("data_type", "")

        if data_type == "SIGNAL":
            return await self._realtime_apply(input_data)
        elif data_type == "BACKTEST_TRIGGER":
            return await self._daily_backtest(input_data)
        else:
            self.log("warning", f"알 수 없는 data_type: {data_type} → passthrough")
            return self._passthrough(input_data.body.get("payload", {}))

    # ==================================================================
    # 실시간 전략 적용 (기존 LogicApplier 로직)
    # ==================================================================

    async def _realtime_apply(self, input_data: StandardMessage) -> StandardMessage:
        """파이프라인 모드: 전략 선택 + 제외 조건 + 타겟 정렬."""
        self.log("info", "전략적용 시작")

        payload   = input_data.body.get("payload", {})
        phase     = payload.get("phase", "일반장")
        direction = payload.get("direction", "HOLD")
        targets   = payload.get("targets", [])
        issue_factor = payload.get("issue_factor")

        strategy = self._select_strategy(phase)

        if strategy:
            sid   = strategy["id"]
            sname = strategy.get("description", "")
            sgrp  = strategy.get("group", "")
            self.log("info", f"전략 선택: {sid} ({sname[:30]}) [{sgrp}]")
        else:
            sid, sname, sgrp = None, "", ""
            self.log("info", f"'{phase}' 국면 적용 가능 전략 없음 → SIGNAL 원본 전달")

        if direction == "BUY" and strategy:
            excluded, exclude_reason = self._check_exclusions(strategy, issue_factor)
            if excluded:
                direction = "HOLD"
                targets   = []
                self.log("warning", f"전략 제외 조건 발동: {exclude_reason} → HOLD 전환")
            else:
                targets = self._prioritize_targets(targets, strategy)

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
            to="EX", data_type="SIGNAL", payload=refined,
            msg_type="SIGNAL",
            priority="HIGH" if direction == "BUY" else "NORMAL",
        )
        msg.status = {"code": "OK", "message": f"전략 적용: {sid or '없음'} / {direction}"}
        self.log("info", f"전략적용 완료: strategy={sid} direction={direction} targets={len(targets)}종목")
        return msg

    def _select_strategy(self, phase: str) -> Optional[dict]:
        """국면에 맞는 최적 전략 1개 선택 (상태 우선순위 + 승률)."""
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

    def _check_exclusions(self, strategy: dict, issue_factor) -> tuple:
        """전략 제외 조건을 이슈 팩터와 대조."""
        exclusion_text = strategy.get("conditions", {}).get("제외", "")
        if not exclusion_text or "해당 없음" in exclusion_text:
            return False, ""
        if issue_factor is None:
            return False, ""
        active_issue_ids = {
            i["issue_id"] for i in issue_factor.get("issues", [])
        }
        for keyword, issue_id in _EXCLUSION_ISSUE_MAP.items():
            if keyword in exclusion_text and issue_id in active_issue_ids:
                return True, f"'{keyword}' 제외 조건 & {issue_id} 활성"
        return False, ""

    def _prioritize_targets(self, targets: list, strategy: dict) -> list:
        """전략 그룹이 선호하는 섹터 종목을 앞으로 정렬."""
        group = strategy.get("group", "")
        preferred_secs = _GROUP_SECTOR_MAP.get(group, [])
        if not preferred_secs:
            return targets
        def _priority(t: dict) -> int:
            sector = t.get("sector", "")
            theme  = t.get("theme", "")
            return 0 if any(p in sector or p in theme for p in preferred_secs) else 1
        return sorted(targets, key=_priority)

    def _enrich_reason(self, original: str, strategy: Optional[dict], direction: str) -> str:
        if not strategy:
            return original
        perf = strategy.get("performance", {})
        addon = (
            f" | 전략 {strategy['id']}({strategy.get('description', '')[:40]}) "
            f"[{perf.get('status', '')}] "
            f"승률={perf.get('backtest_win_rate', 0)*100:.0f}% "
            f"수익률={perf.get('backtest_return_pct', 0):+.1f}%"
        )
        return original + addon

    def _passthrough(self, payload: dict, reason: str = "") -> StandardMessage:
        payload["strategy_id"]    = None
        payload["strategy_name"]  = ""
        payload["strategy_group"] = ""
        msg = self.create_message(
            to="EX", data_type="SIGNAL", payload=payload, msg_type="SIGNAL",
        )
        msg.status = {"code": "OK", "message": reason or "passthrough"}
        return msg

    # ==================================================================
    # 일일 백테스팅 (장 종료 후 자동 실행)
    # ==================================================================

    async def _daily_backtest(self, input_data=None) -> StandardMessage:
        """
        장 종료 후 전체 전략 백테스팅.
        성과 미달 전략은 자동 비활성화.
        """
        self.log("info", "=== 일일 백테스팅 시작 ===")

        results = {}
        deactivated = []
        passed_count = 0

        for sid, card in list(self._library.items()):
            bt_result = await self._run_single_backtest(card)
            results[sid] = bt_result

            if bt_result.get("passed"):
                passed_count += 1
            elif bt_result.get("status") not in ("no_data", "error"):
                # 데이터가 있는데 통과 못 한 경우만 비활성화 검토
                overall = bt_result.get("overall", {})
                wr = overall.get("win_rate", 1.0)
                avg_ret = overall.get("return_pct", 0.0)
                mdd = overall.get("mdd", 0.0)
                if wr < _MIN_WIN_RATE or avg_ret < _MIN_AVG_RETURN or mdd < _MAX_MDD:
                    self.deactivate_strategy(sid, f"승률={wr:.1%} 수익={avg_ret:+.2f}% MDD={mdd:.1f}%")
                    deactivated.append(sid)

        # 라이브러리 리로드 (비활성화 반영)
        if deactivated:
            self._load_library_from_disk()

        summary = (
            f"백테스팅 완료: {len(results)}개 전략 중 "
            f"{passed_count}개 통과, {len(deactivated)}개 비활성화"
        )
        self.log("info", f"=== {summary} ===")

        # 텔레그램 알림 (Executor 통해)
        try:
            from agents.executor import Executor
            ex = Executor()
            await ex._send_telegram(f"[전략 백테스팅]\n{summary}")
        except Exception:
            pass

        return self.create_message(
            to="OR", data_type="BACKTEST_REPORT",
            payload={
                "backtest_results": results,
                "deactivated": deactivated,
                "passed_count": passed_count,
                "summary": summary,
            },
            priority="LOW",
        )

    # ==================================================================
    # 백테스팅 엔진 (기존 SR 로직)
    # ==================================================================

    async def _run_full_backtest_cycle(self) -> StandardMessage:
        """전체 전략 라이브러리 백테스팅 (독립 실행)."""
        results = {}
        for strategy_id, card in self._library.items():
            results[strategy_id] = await self._run_single_backtest(card)
        self.log("info", f"전체 백테스팅 완료: {len(results)}개 전략")
        return self.create_message(
            to="OR", data_type="BACKTEST_REPORT",
            payload={"backtest_results": results}, priority="LOW",
        )

    async def _run_single_backtest(self, card: dict) -> dict:
        """단일 전략 백테스팅. 결과에 따라 카드 status 업데이트."""
        strategy_id = card["id"]
        phase = card.get("phase", "안정화")

        try:
            from database.db import get_trades_for_backtest
            trades = get_trades_for_backtest(phase, strategy_id)
        except Exception as e:
            self.log("warning", f"trades 조회 실패 {strategy_id}: {e}")
            return {"status": "error", "message": str(e)}

        if not trades:
            return {"status": "no_data", "trade_count": 0}

        periods = self._split_into_periods(trades)
        period_results = []

        for i, period_trades in enumerate(periods):
            metrics = self._calc_period_metrics(period_trades)
            period_results.append(metrics)

            if period_trades:
                start = period_trades[0].get("created_at", "")[:10]
                end = period_trades[-1].get("created_at", "")[:10]
                try:
                    from database.db import save_backtest_result
                    save_backtest_result(
                        strategy_id=strategy_id, phase=phase,
                        period_start=start, period_end=end,
                        win_rate=metrics["win_rate"],
                        return_pct=metrics["return_pct"],
                        mdd=metrics["mdd"],
                    )
                except Exception:
                    pass

        passed, reason = self._validate_anti_overfit(period_results)
        overall = self._calc_period_metrics(trades)

        new_status = "검증완료" if passed else "백테스팅중"
        card.setdefault("performance", {})
        card["performance"]["backtest_win_rate"]   = overall["win_rate"]
        card["performance"]["backtest_return_pct"] = overall["return_pct"]
        card["performance"]["mdd"]                 = overall["mdd"]
        card["performance"]["status"]              = new_status
        card["performance"]["backtest_trade_count"] = len(trades)
        self.save_strategy(card)

        self.log(
            "info",
            f"{strategy_id} 백테스팅: 승률={overall['win_rate']:.1%} "
            f"MDD={overall['mdd']:.1f}% {'통과' if passed else '미달: ' + reason}"
        )

        return {
            "status": new_status, "passed": passed, "reason": reason,
            "trade_count": len(trades), "period_results": period_results,
            "overall": overall,
        }

    def _split_into_periods(self, trades: list, n_periods: int = 3) -> list:
        if not trades:
            return []
        min_total = n_periods * _MIN_TRADES_PER_PERIOD
        if len(trades) < min_total:
            return [trades]
        size = len(trades) // n_periods
        return [trades[i * size: (i + 1) * size] for i in range(n_periods)]

    def _calc_period_metrics(self, trades: list) -> dict:
        result_pcts = [
            float(t.get("result_pct", 0.0))
            for t in trades if t.get("result_pct", 0.0) != 0.0
        ]
        if not result_pcts:
            return {"win_rate": 0.0, "return_pct": 0.0, "mdd": 0.0, "trade_count": 0}
        wins = sum(1 for r in result_pcts if r > 0)
        return {
            "win_rate":    round(wins / len(result_pcts), 4),
            "return_pct":  round(sum(result_pcts) / len(result_pcts), 4),
            "mdd":         self._calc_mdd(result_pcts),
            "trade_count": len(result_pcts),
        }

    def _calc_mdd(self, return_series: list) -> float:
        if not return_series:
            return 0.0
        cum = 1.0
        cum_series = []
        for r in return_series:
            cum *= (1 + r / 100)
            cum_series.append(cum)
        peak = cum_series[0]
        mdd = 0.0
        for val in cum_series:
            if val > peak:
                peak = val
            drawdown = (val - peak) / peak
            if drawdown < mdd:
                mdd = drawdown
        return round(mdd * 100, 2)

    def _validate_anti_overfit(self, period_results: list) -> tuple:
        if len(period_results) < _MIN_PERIODS:
            return (False, f"기간 수 부족: {len(period_results)} < {_MIN_PERIODS}")
        for i, pr in enumerate(period_results):
            if pr["trade_count"] < _MIN_TRADES_PER_PERIOD:
                return (False, f"기간 {i+1} 거래 수 부족: {pr['trade_count']}")
            if pr["win_rate"] < _MIN_WIN_RATE:
                return (False, f"기간 {i+1} 승률 미달: {pr['win_rate']:.1%} < {_MIN_WIN_RATE:.0%}")
            if pr["return_pct"] < _MIN_AVG_RETURN:
                return (False, f"기간 {i+1} 수익 미달: {pr['return_pct']:+.2f}% < {_MIN_AVG_RETURN}%")
            if pr["mdd"] < _MAX_MDD:
                return (False, f"기간 {i+1} MDD 초과: {pr['mdd']:.1f}%")
        return (True, "")

    # ==================================================================
    # CRUD
    # ==================================================================

    def list_strategies(self, phase: Optional[str] = None) -> list:
        cards = list(self._library.values())
        if phase is not None:
            cards = [c for c in cards if c.get("phase") == phase]
        return cards

    def load_strategy(self, strategy_id: str) -> Optional[dict]:
        return self._library.get(strategy_id)

    def save_strategy(self, card: dict) -> bool:
        if not card.get("id") or not card.get("phase"):
            return False
        card["updated_at"] = date.today().isoformat()
        folder = os.path.join(_LIBRARY_ROOT, self._phase_to_folder(card["phase"]))
        os.makedirs(folder, exist_ok=True)
        filepath = os.path.join(folder, f"{card['id']}.json")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(card, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log("warning", f"전략 파일 저장 실패: {e}")
            return False
        self._library[card["id"]] = card
        try:
            from database.db import upsert_strategy
            upsert_strategy(card)
        except Exception:
            pass
        return True

    def deactivate_strategy(self, strategy_id: str, reason: str = "") -> None:
        card = self._library.get(strategy_id)
        if card is None:
            return
        card.setdefault("performance", {})
        card["performance"]["status"] = "비활성"
        self.save_strategy(card)
        self.log("info", f"전략 비활성화: {strategy_id} — {reason}")

    def recommend_strategies(self, phase: str, top_n: int = 3) -> list:
        eligible = [
            card for card in self._library.values()
            if card.get("phase") == phase and self._is_eligible(card)
        ]
        eligible.sort(
            key=lambda c: c.get("performance", {}).get("backtest_win_rate", 0.0),
            reverse=True,
        )
        return eligible[:top_n]

    def _is_eligible(self, card: dict) -> bool:
        perf = card.get("performance", {})
        status = perf.get("status", "백테스팅중")
        if status == "비활성":
            return False
        if status in ("검증완료", "실전검증완료"):
            if perf.get("backtest_win_rate", 0) < _MIN_WIN_RATE:
                return False
            if perf.get("backtest_return_pct", 0) < _MIN_AVG_RETURN:
                return False
            if perf.get("mdd", 0) < _MAX_MDD:
                return False
        return True

    def reload_library(self) -> int:
        self._library.clear()
        self._load_library_from_disk()
        return len(self._library)


# ---------------------------------------------------------------------------
# 독립 실행 진입점
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio

    async def _main():
        engine = StrategyEngine()
        result = await engine.run(input_data=None)
        print(json.dumps(result.body.get("payload", {}), ensure_ascii=False, indent=2))

    asyncio.run(_main())
