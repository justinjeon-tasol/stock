"""
시스템관리 에이전트 모듈.
에이전트 오류 분석, 설정 패치, 시스템 상태 보고를 담당한다.
코드 직접 수정은 하지 않고, 설정(JSON) 파일 수준의 안전한 패치만 적용한다.

파이프라인 위치: 디버깅(DB)/오케스트레이터(OR) → SystemManager(SM)
"""

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from agents.base_agent import BaseAgent
from database.db import _get_client, save_agent_log
from protocol.protocol import StandardMessage

logger = logging.getLogger(__name__)

# 설정 파일 경로
_CONFIG_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
)
_STRATEGY_CONFIG_PATH = os.path.join(_CONFIG_ROOT, "strategy_config.json")

# 오류 분석 기간 (기본 24시간)
_DEFAULT_ANALYSIS_HOURS = 24

# 오류율 임계값: 한 에이전트가 이 비율 이상 오류면 "불안정" 판정
_ERROR_RATE_WARN_THRESHOLD  = 0.20   # 20%
_ERROR_RATE_CRIT_THRESHOLD  = 0.50   # 50%

# 허용되는 패치 키 목록 (안전한 설정만 수정 가능)
_PATCHABLE_KEYS = {
    "stop_loss_pct",
    "take_profit_pct",
    "cash_pct",
    "max_positions",
    "sector_concentration_max_pct",
    "theme_boost_multiplier",
}


class SystemManager(BaseAgent):
    """
    시스템 건강 분석, 설정 패치, 상태 보고 에이전트.
    SM 에이전트는 오케스트레이터 또는 디버깅 에이전트 요청으로 활성화된다.
    """

    def __init__(self) -> None:
        super().__init__("SM", "시스템관리", timeout=30, max_retries=2)
        self._strategy_config: dict = self._load_strategy_config()

    # ------------------------------------------------------------------
    # 설정 로드
    # ------------------------------------------------------------------

    def _load_strategy_config(self) -> dict:
        """strategy_config.json 로드. 실패 시 빈 dict."""
        try:
            with open(_STRATEGY_CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning("[시스템관리] strategy_config.json 로드 실패: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # BaseAgent 구현
    # ------------------------------------------------------------------

    async def execute(self, input_data: Optional[StandardMessage] = None) -> StandardMessage:
        """
        시스템 건강 분석을 실행한다.
        입력 없으면 기본 24시간 분석 수행.

        반환 payload (SYSTEM_REPORT):
        {
            "health":          "GOOD" | "WARN" | "CRITICAL",
            "agent_stats":     {agent_code: {total, error_count, error_rate, issues}},
            "top_errors":      [{agent, error_code, message, count}],
            "patch_applied":   [{key, old_value, new_value, reason}],
            "recommendations": [str],
            "report_period_hours": int,
            "generated_at":    str,
        }
        """
        self.log("info", "시스템 분석 시작")

        # 요청 파싱 (입력이 있으면 파라미터 추출)
        hours = _DEFAULT_ANALYSIS_HOURS
        patch_requests: list = []
        if input_data:
            req_payload = input_data.body.get("payload", {})
            hours = req_payload.get("analysis_hours", _DEFAULT_ANALYSIS_HOURS)
            patch_requests = req_payload.get("patches", [])

        # 1. Supabase 로그 수집
        since_iso = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        raw_logs  = self._fetch_logs(since_iso)

        # 2. 에이전트별 통계 분석
        agent_stats = self._analyze_logs(raw_logs)

        # 3. 전체 건강 판정
        health = self._evaluate_health(agent_stats)

        # 4. 상위 오류 집계
        top_errors = self._top_errors(raw_logs, top_n=5)

        # 5. 권고 생성
        recommendations = self._build_recommendations(agent_stats, health)

        # 6. 안전 패치 적용
        patch_results = self._apply_patches(patch_requests)

        self.log("info", f"시스템 분석 완료: 건강={health}, 에이전트={len(agent_stats)}개 분석")

        result_payload = {
            "health":              health,
            "agent_stats":         agent_stats,
            "top_errors":          top_errors,
            "patch_applied":       patch_results,
            "recommendations":     recommendations,
            "report_period_hours": hours,
            "generated_at":        datetime.now(timezone.utc).isoformat(),
        }

        msg = self.create_message(
            to="OR",
            data_type="SYSTEM_REPORT",
            payload=result_payload,
        )
        msg.status = {"code": "OK", "message": f"시스템 건강={health}"}
        return msg

    # ------------------------------------------------------------------
    # 1. 로그 수집
    # ------------------------------------------------------------------

    def _fetch_logs(self, since_iso: str) -> list:
        """
        Supabase agent_logs 테이블에서 since_iso 이후 로그 조회.
        미설정 또는 실패 시 빈 리스트.
        """
        client = _get_client()
        if client is None:
            logger.debug("[시스템관리] Supabase 미설정, 로그 조회 건너뜀")
            return []
        try:
            result = (
                client.table("agent_logs")
                .select("agent, level, message, error_code, timestamp")
                .gte("timestamp", since_iso)
                .order("timestamp", desc=False)
                .limit(2000)
                .execute()
            )
            return result.data or []
        except Exception as exc:
            logger.warning("[시스템관리] 로그 조회 실패: %s", exc)
            return []

    # ------------------------------------------------------------------
    # 2. 에이전트별 통계 분석
    # ------------------------------------------------------------------

    def _analyze_logs(self, logs: list) -> dict:
        """
        에이전트별 총 로그 수, 오류 수, 오류율, 대표 이슈를 집계한다.

        Returns
        -------
        dict
            {agent_code: {"total": int, "error_count": int, "error_rate": float, "issues": list}}
        """
        # 집계
        totals:  dict[str, int]  = defaultdict(int)
        errors:  dict[str, int]  = defaultdict(int)
        issues:  dict[str, list] = defaultdict(list)

        for log in logs:
            agent = log.get("agent", "UNKNOWN")
            level = log.get("level", "").upper()
            totals[agent] += 1
            if level in ("ERROR", "CRITICAL"):
                errors[agent] += 1
                msg = log.get("message", "")
                ec  = log.get("error_code", "")
                # 대표 이슈 최대 3개 저장 (중복 제거)
                key = ec or msg[:60]
                if key not in issues[agent] and len(issues[agent]) < 3:
                    issues[agent].append(key)

        stats: dict = {}
        for agent in set(list(totals.keys()) + list(errors.keys())):
            total       = totals[agent]
            error_count = errors[agent]
            error_rate  = round(error_count / total, 4) if total > 0 else 0.0
            stats[agent] = {
                "total":       total,
                "error_count": error_count,
                "error_rate":  error_rate,
                "issues":      issues[agent],
            }

        return stats

    # ------------------------------------------------------------------
    # 3. 전체 건강 판정
    # ------------------------------------------------------------------

    def _evaluate_health(self, agent_stats: dict) -> str:
        """
        에이전트 통계 기반 전체 시스템 건강 판정.

        Returns
        -------
        "GOOD" | "WARN" | "CRITICAL"
        """
        if not agent_stats:
            return "GOOD"

        max_error_rate = max(
            (s["error_rate"] for s in agent_stats.values()),
            default=0.0,
        )
        if max_error_rate >= _ERROR_RATE_CRIT_THRESHOLD:
            return "CRITICAL"
        if max_error_rate >= _ERROR_RATE_WARN_THRESHOLD:
            return "WARN"
        return "GOOD"

    # ------------------------------------------------------------------
    # 4. 상위 오류 집계
    # ------------------------------------------------------------------

    def _top_errors(self, logs: list, top_n: int = 5) -> list:
        """
        오류 메시지 빈도 기준 상위 N개 반환.

        Returns
        -------
        list[dict]
            [{"agent", "error_code", "message", "count"}, ...]
        """
        counter: dict[tuple, dict] = {}
        for log in logs:
            level = log.get("level", "").upper()
            if level not in ("ERROR", "CRITICAL"):
                continue
            agent = log.get("agent", "UNKNOWN")
            ec    = log.get("error_code", "")
            msg   = log.get("message", "")[:80]
            key   = (agent, ec, msg)
            if key not in counter:
                counter[key] = {"agent": agent, "error_code": ec, "message": msg, "count": 0}
            counter[key]["count"] += 1

        sorted_errors = sorted(counter.values(), key=lambda x: x["count"], reverse=True)
        return sorted_errors[:top_n]

    # ------------------------------------------------------------------
    # 5. 권고 생성
    # ------------------------------------------------------------------

    def _build_recommendations(self, agent_stats: dict, health: str) -> list:
        """
        분석 결과 기반 운영 권고 목록 생성.

        Returns
        -------
        list[str]
        """
        recs: list[str] = []

        if health == "GOOD":
            recs.append("시스템이 정상 동작 중입니다. 현재 설정 유지를 권장합니다.")
            return recs

        for agent, stats in agent_stats.items():
            rate = stats["error_rate"]
            if rate >= _ERROR_RATE_CRIT_THRESHOLD:
                recs.append(
                    f"{agent} 에이전트 오류율 {rate*100:.0f}% - "
                    f"즉시 점검 필요. 대표 이슈: {stats['issues'][:1]}"
                )
            elif rate >= _ERROR_RATE_WARN_THRESHOLD:
                recs.append(
                    f"{agent} 에이전트 오류율 {rate*100:.0f}% - "
                    f"모니터링 강화 권장."
                )

        if health == "CRITICAL":
            recs.append("CRITICAL 상태: 자동매매 일시 중단 및 수동 점검을 권장합니다.")

        return recs

    # ------------------------------------------------------------------
    # 6. 안전 패치 적용
    # ------------------------------------------------------------------

    def _apply_patches(self, patch_requests: list) -> list:
        """
        허용 목록(_PATCHABLE_KEYS)에 있는 설정 키만 패치한다.
        strategy_config.json을 직접 수정한다.

        Parameters
        ----------
        patch_requests : list[dict]
            [{"key": str, "value": Any, "reason": str, "section": str}, ...]
            section: 최상위 JSON 키 (예: "classification_rules")

        Returns
        -------
        list[dict]
            실제 적용된 패치 목록.
        """
        if not patch_requests:
            return []

        config = self._load_strategy_config()
        applied: list = []

        for req in patch_requests:
            key     = req.get("key", "")
            value   = req.get("value")
            reason  = req.get("reason", "")
            section = req.get("section", "")

            if key not in _PATCHABLE_KEYS:
                self.log("warning", f"패치 거부: '{key}'는 허용 목록에 없음")
                continue

            # 섹션 지정 시 section[key], 없으면 최상위 key
            target = config.get(section, {}) if section else config
            old_value = target.get(key)

            if old_value == value:
                continue  # 변경 불필요

            target[key] = value
            if section and section in config:
                config[section] = target

            applied.append({
                "key":       key,
                "section":   section,
                "old_value": old_value,
                "new_value": value,
                "reason":    reason,
            })
            self.log("info", f"패치 적용: [{section}.]{key} {old_value} -> {value} ({reason})")

        if applied:
            try:
                with open(_STRATEGY_CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
                self._strategy_config = config
                save_agent_log("SM", "INFO", f"설정 패치 {len(applied)}건 적용")
            except Exception as exc:
                self.log("warning", f"패치 저장 실패: {exc}")
                return []

        return applied

    # ------------------------------------------------------------------
    # 공개 유틸리티
    # ------------------------------------------------------------------

    def get_strategy_config(self) -> dict:
        """현재 로드된 strategy_config 반환."""
        return self._strategy_config

    def get_system_summary(self, hours: int = 24) -> dict:
        """
        빠른 시스템 요약 (동기, 경량).

        Returns
        -------
        dict
            {"health", "agent_count", "error_count", "period_hours"}
        """
        since_iso = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        logs      = self._fetch_logs(since_iso)
        stats     = self._analyze_logs(logs)
        health    = self._evaluate_health(stats)

        total_errors = sum(s["error_count"] for s in stats.values())
        return {
            "health":       health,
            "agent_count":  len(stats),
            "error_count":  total_errors,
            "period_hours": hours,
        }

    def describe_patchable_keys(self) -> list:
        """패치 가능한 설정 키 목록 반환."""
        return sorted(_PATCHABLE_KEYS)
