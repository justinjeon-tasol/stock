"""
디버깅 에이전트 모듈.
모든 에이전트를 24시간 독립적으로 감시한다.
- 하트비트 미수신 시 단계별 경보 (30s WARNING, 60s HIGH, 90s CRITICAL)
- 에러 버퍼 수집 후 execute()에서 오케스트레이터로 보고
- CRITICAL 오류 발생 시 매매 중단 플래그 설정 + 텔레그램 알림
독립 원칙: 어떤 에이전트의 지시도 받지 않음, 오직 오케스트레이터에만 보고.
"""

import asyncio
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from dotenv import load_dotenv

from agents.base_agent import BaseAgent
from protocol.protocol import StandardMessage

# 텔레그램 API 베이스 URL
_TELEGRAM_BASE_URL = "https://api.telegram.org"

# 감시 대상 에이전트 코드 (7-agent 구조)
_MONITORED_AGENTS = ["DC", "MA", "WA", "SR", "EX"]

# ── 시스템 헬스 분석 (SystemManager 흡수) ──
_CONFIG_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config",
)
_STRATEGY_CONFIG_PATH = os.path.join(_CONFIG_ROOT, "strategy_config.json")
_DEFAULT_ANALYSIS_HOURS = 24
_ERROR_RATE_WARN_THRESHOLD = 0.20
_ERROR_RATE_CRIT_THRESHOLD = 0.50
_PATCHABLE_KEYS = {
    "stop_loss_pct", "take_profit_pct", "cash_pct",
    "max_positions", "sector_concentration_max_pct", "theme_boost_multiplier",
}

# 하트비트 타임아웃 임계값 (초)
_WARN_THRESHOLD = 30
_HIGH_THRESHOLD = 60
_CRITICAL_THRESHOLD = 90


class Debugger(BaseAgent):
    """
    24시간 독립 감시 에이전트.
    다른 에이전트의 지시를 받지 않고 오직 오케스트레이터에만 보고한다.
    """

    def __init__(self) -> None:
        load_dotenv(override=True)
        # 디버깅 에이전트: 타임아웃 즉시, 재시도 없음
        super().__init__("DB", "디버깅", timeout=10, max_retries=1)

        # 하트비트 추적: {에이전트코드: 마지막 수신 시각}
        self._heartbeats: dict[str, datetime] = {}

        # 에러 버퍼: receive_error()로 수집, execute() 후 초기화
        self._error_buffer: list[dict] = []

        # 매매 중단 플래그
        self._halt_trading: bool = False

        # 텔레그램 설정
        self._telegram_token: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
        self._telegram_chat_id: Optional[str] = os.getenv("TELEGRAM_CHAT_ID")

        # DB 마지막 폴링 시각 (ISO 8601)
        self._last_poll_time: str = datetime.now(timezone.utc).isoformat()

        self.log("info", "디버깅 에이전트 초기화 완료")

    # ------------------------------------------------------------------
    # 프로퍼티
    # ------------------------------------------------------------------

    @property
    def halt_trading(self) -> bool:
        """매매 중단 플래그. CRITICAL 오류 발생 시 True로 설정된다."""
        return self._halt_trading

    @halt_trading.setter
    def halt_trading(self, value: bool) -> None:
        self._halt_trading = value

    # ------------------------------------------------------------------
    # 외부 호출 API
    # ------------------------------------------------------------------

    def receive_heartbeat(self, agent_code: str) -> None:
        """
        다른 에이전트로부터 하트비트를 수신한다.

        Args:
            agent_code: 하트비트를 보낸 에이전트 코드 (예: "DC")
        """
        now = datetime.now(timezone.utc)
        self._heartbeats[agent_code] = now
        self.log("debug", f"하트비트 수신: {agent_code} ({now.isoformat()})")

    def receive_error(
        self,
        agent_code: str,
        level: str,
        message: str,
        error_code: str = "",
    ) -> None:
        """
        다른 에이전트로부터 오류를 수신한다.
        CRITICAL 레벨이면 즉시 매매 중단 플래그를 설정하고 텔레그램 알림을 전송한다.

        Args:
            agent_code: 오류를 보낸 에이전트 코드
            level:      오류 등급 (LOW | MEDIUM | HIGH | CRITICAL)
            message:    오류 메시지
            error_code: 오류 코드 (선택)
        """
        entry = {
            "agent_code": agent_code,
            "level": level,
            "message": message,
            "error_code": error_code,
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        self._error_buffer.append(entry)
        self.log("warning", f"오류 수신 [{level}] {agent_code}: {message}")

        if level == "CRITICAL":
            self._halt_trading = True
            self.log("critical", f"CRITICAL 오류로 매매 중단 플래그 설정: {agent_code} - {message}")
            # 텔레그램 알림: 비동기 컨텍스트 여부에 따라 처리
            alert_msg = f"[CRITICAL] 매매 중단\n에이전트: {agent_code}\n오류: {message}"
            try:
                # 이미 실행 중인 이벤트 루프가 있으면 태스크로 예약
                running_loop = asyncio.get_running_loop()
                running_loop.create_task(self._send_telegram_alert(alert_msg))
            except RuntimeError:
                # 실행 중인 루프가 없으면 새 루프로 즉시 실행
                try:
                    asyncio.run(self._send_telegram_alert(alert_msg))
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # 핵심 실행 메서드
    # ------------------------------------------------------------------

    async def execute(self, input_data=None) -> StandardMessage:
        """
        단일 감시 사이클을 실행한다.
        1. 하트비트 타임아웃 점검
        2. DB 로그 폴링 (Supabase 설정 시)
        3. 에러 버퍼 처리
        4. DEBUG_REPORT 메시지를 오케스트레이터(OR)로 반환

        Returns:
            StandardMessage: data_type="DEBUG_REPORT", to="OR"
        """
        self.log("info", "감시 사이클 시작")

        # 1. 하트비트 타임아웃 점검
        heartbeat_issues = self._check_heartbeats()

        # 2. DB 에러 로그 폴링
        now_iso = datetime.now(timezone.utc).isoformat()
        db_errors = self._poll_db_errors(self._last_poll_time)
        self._last_poll_time = now_iso

        # DB에서 가져온 CRITICAL 오류 처리
        for db_err in db_errors:
            if db_err.get("level") == "CRITICAL":
                self._halt_trading = True
                await self._send_telegram_alert(
                    f"[DB-CRITICAL] 매매 중단\n에이전트: {db_err.get('agent', '?')}\n"
                    f"오류: {db_err.get('message', '')}"
                )

        # 3. 에러 버퍼 스냅샷 후 초기화
        error_snapshot = list(self._error_buffer)
        self._error_buffer.clear()

        # CRITICAL 오류 목록 추출
        critical_errors = [
            e for e in error_snapshot if e.get("level") == "CRITICAL"
        ]
        # DB 폴링에서도 CRITICAL 추가
        for db_err in db_errors:
            if db_err.get("level") == "CRITICAL":
                critical_errors.append({
                    "agent_code": db_err.get("agent", "?"),
                    "level": "CRITICAL",
                    "message": db_err.get("message", ""),
                    "error_code": db_err.get("error_code", ""),
                })

        # 4. 에이전트 상태 요약 구성
        agent_health = self.get_agent_health()
        health_summary = {
            code: info["status"] for code, info in agent_health.items()
        }

        total_errors = len(error_snapshot) + len(db_errors)
        summary = "시스템 정상" if not self._halt_trading and total_errors == 0 else (
            "매매 중단 중" if self._halt_trading else f"오류 {total_errors}건 감지"
        )

        # ── 시스템 헬스 분석 (SystemManager 흡수) ──
        sys_logs = self._fetch_system_logs(
            (datetime.now(timezone.utc) - timedelta(hours=_DEFAULT_ANALYSIS_HOURS)).isoformat()
        )
        agent_stats = self._analyze_agent_stats(sys_logs)
        system_health = self._evaluate_system_health(agent_stats)
        top_errs = self._top_errors(sys_logs, top_n=5)
        recommendations = self._build_recommendations(agent_stats, system_health)

        payload = {
            "agent_health": health_summary,
            "error_count": total_errors,
            "halt_trading": self._halt_trading,
            "critical_errors": critical_errors,
            "summary": summary,
            "system_health": system_health,
            "agent_stats": agent_stats,
            "top_errors": top_errs,
            "recommendations": recommendations,
        }

        self.log("info", f"감시 사이클 완료: {summary}")

        priority = "CRITICAL" if self._halt_trading else (
            "HIGH" if total_errors > 0 else "NORMAL"
        )

        return self.create_message(
            to="OR",
            data_type="DEBUG_REPORT",
            payload=payload,
            priority=priority,
            msg_type="ALERT" if self._halt_trading else "DATA",
        )

    # ------------------------------------------------------------------
    # 백그라운드 모니터링
    # ------------------------------------------------------------------

    async def run_monitor(self, check_interval: int = 30) -> None:
        """
        주기적으로 execute()를 호출하는 백그라운드 감시 루프.

        Args:
            check_interval: 감시 주기 (초, 기본값 30)
        """
        self.log("info", f"백그라운드 감시 루프 시작 (주기: {check_interval}초)")
        while True:
            try:
                await self.execute()
            except Exception as exc:
                self.log("error", f"감시 사이클 오류: {exc}")
            await asyncio.sleep(check_interval)

    def start_background(self, check_interval: int = 30) -> asyncio.Task:
        """
        run_monitor()를 asyncio.Task로 실행한다.

        Args:
            check_interval: 감시 주기 (초, 기본값 30)

        Returns:
            asyncio.Task 인스턴스
        """
        self.log("info", "백그라운드 감시 태스크 등록")
        return asyncio.ensure_future(self.run_monitor(check_interval))

    # ------------------------------------------------------------------
    # 상태 조회
    # ------------------------------------------------------------------

    def get_agent_health(self) -> dict:
        """
        감시 대상 에이전트별 상태를 반환한다.

        Returns:
            {
                "DC": {"status": "ALIVE"|"WARNING"|"CRITICAL", "last_seen_secs": 15},
                ...
            }
        """
        now = datetime.now(timezone.utc)
        result = {}

        for code in _MONITORED_AGENTS:
            if code not in self._heartbeats:
                # 한 번도 하트비트를 받지 않은 에이전트
                result[code] = {"status": "WARNING", "last_seen_secs": -1}
                continue

            elapsed = (now - self._heartbeats[code]).total_seconds()
            if elapsed >= _CRITICAL_THRESHOLD:
                status = "CRITICAL"
            elif elapsed >= _HIGH_THRESHOLD:
                status = "HIGH"
            elif elapsed >= _WARN_THRESHOLD:
                status = "WARNING"
            else:
                status = "ALIVE"

            result[code] = {"status": status, "last_seen_secs": int(elapsed)}

        return result

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    def _check_heartbeats(self) -> list:
        """
        하트비트 타임아웃을 점검하고 문제가 있는 에이전트 목록을 반환한다.
        90초 초과 에이전트는 CRITICAL + halt_trading 설정.

        Returns:
            문제가 감지된 에이전트 정보 목록
        """
        now = datetime.now(timezone.utc)
        issues = []

        for code in _MONITORED_AGENTS:
            if code not in self._heartbeats:
                self.log("warning", f"하트비트 미수신 에이전트: {code}")
                issues.append({"agent": code, "issue": "하트비트 없음"})
                continue

            elapsed = (now - self._heartbeats[code]).total_seconds()

            if elapsed >= _CRITICAL_THRESHOLD:
                self.log("critical", f"[{code}] {elapsed:.0f}초 무응답 - 오케스트레이터 강제재시작 요청")
                self._halt_trading = True
                issues.append({"agent": code, "issue": "90초 무응답", "elapsed": elapsed})
            elif elapsed >= _HIGH_THRESHOLD:
                self.log("error", f"[{code}] {elapsed:.0f}초 무응답 - HIGH 오류")
                issues.append({"agent": code, "issue": "60초 무응답", "elapsed": elapsed})
            elif elapsed >= _WARN_THRESHOLD:
                self.log("warning", f"[{code}] {elapsed:.0f}초 무응답 - WARNING")
                issues.append({"agent": code, "issue": "30초 무응답", "elapsed": elapsed})

        return issues

    def _poll_db_errors(self, since_iso: str) -> list:
        """
        Supabase agent_logs 테이블에서 ERROR/CRITICAL 로그를 폴링한다.
        Supabase 미설정 시 빈 리스트를 반환한다.

        Args:
            since_iso: 이 시각 이후의 로그를 조회 (ISO 8601)

        Returns:
            오류 로그 목록
        """
        try:
            from database.db import _get_client
            client = _get_client()
            if client is None:
                return []
            result = (
                client.table("agent_logs")
                .select("agent, level, message, error_code, timestamp")
                .in_("level", ["ERROR", "CRITICAL"])
                .gte("timestamp", since_iso)
                .order("timestamp", desc=False)
                .execute()
            )
            return result.data or []
        except Exception as exc:
            self.log("debug", f"DB 폴링 실패 (무시): {exc}")
            return []

    async def _send_telegram_alert(self, message: str) -> None:
        """
        CRITICAL 오류 또는 매매 중단 시 텔레그램 알림을 전송한다.
        설정 미비 또는 전송 실패 시 예외를 전파하지 않는다.

        Args:
            message: 전송할 텍스트
        """
        if not self._telegram_token or not self._telegram_chat_id:
            self.log("debug", "텔레그램 설정 없음 - 알림 건너뜀")
            return

        url = f"{_TELEGRAM_BASE_URL}/bot{self._telegram_token}/sendMessage"
        body = {
            "chat_id": self._telegram_chat_id,
            "text": f"[디버깅 에이전트]\n{message}",
        }

        loop = asyncio.get_event_loop()

        def _request() -> requests.Response:
            return requests.post(url, json=body, timeout=10)

        try:
            resp = await loop.run_in_executor(None, _request)
            resp.raise_for_status()
            self.log("info", "텔레그램 알림 전송 완료")
        except Exception as exc:
            self.log("warning", f"텔레그램 알림 전송 실패: {exc}")

    # ------------------------------------------------------------------
    # 시스템 헬스 분석 (SystemManager 흡수)
    # ------------------------------------------------------------------

    def _load_strategy_config(self) -> dict:
        try:
            with open(_STRATEGY_CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _fetch_system_logs(self, since_iso: str) -> list:
        """Supabase agent_logs에서 로그 조회 (시스템 헬스 분석용)."""
        try:
            from database.db import _get_client
            client = _get_client()
            if client is None:
                return []
            result = (
                client.table("agent_logs")
                .select("agent, level, message, error_code, timestamp")
                .gte("timestamp", since_iso)
                .order("timestamp", desc=False)
                .limit(2000)
                .execute()
            )
            return result.data or []
        except Exception:
            return []

    def _analyze_agent_stats(self, logs: list) -> dict:
        """에이전트별 총 로그 수, 오류 수, 오류율, 대표 이슈 집계."""
        totals: dict[str, int] = defaultdict(int)
        errors: dict[str, int] = defaultdict(int)
        issues: dict[str, list] = defaultdict(list)
        for log in logs:
            agent = log.get("agent", "UNKNOWN")
            level = log.get("level", "").upper()
            totals[agent] += 1
            if level in ("ERROR", "CRITICAL"):
                errors[agent] += 1
                key = log.get("error_code", "") or log.get("message", "")[:60]
                if key not in issues[agent] and len(issues[agent]) < 3:
                    issues[agent].append(key)
        stats: dict = {}
        for agent in set(list(totals.keys()) + list(errors.keys())):
            total = totals[agent]
            error_count = errors[agent]
            stats[agent] = {
                "total": total, "error_count": error_count,
                "error_rate": round(error_count / total, 4) if total > 0 else 0.0,
                "issues": issues[agent],
            }
        return stats

    def _evaluate_system_health(self, agent_stats: dict) -> str:
        if not agent_stats:
            return "GOOD"
        max_rate = max((s["error_rate"] for s in agent_stats.values()), default=0.0)
        if max_rate >= _ERROR_RATE_CRIT_THRESHOLD:
            return "CRITICAL"
        if max_rate >= _ERROR_RATE_WARN_THRESHOLD:
            return "WARN"
        return "GOOD"

    def _top_errors(self, logs: list, top_n: int = 5) -> list:
        counter: dict[tuple, dict] = {}
        for log in logs:
            if log.get("level", "").upper() not in ("ERROR", "CRITICAL"):
                continue
            agent = log.get("agent", "UNKNOWN")
            ec = log.get("error_code", "")
            msg = log.get("message", "")[:80]
            key = (agent, ec, msg)
            if key not in counter:
                counter[key] = {"agent": agent, "error_code": ec, "message": msg, "count": 0}
            counter[key]["count"] += 1
        return sorted(counter.values(), key=lambda x: x["count"], reverse=True)[:top_n]

    def _build_recommendations(self, agent_stats: dict, health: str) -> list:
        recs: list[str] = []
        if health == "GOOD":
            recs.append("시스템이 정상 동작 중입니다.")
            return recs
        for agent, stats in agent_stats.items():
            rate = stats["error_rate"]
            if rate >= _ERROR_RATE_CRIT_THRESHOLD:
                recs.append(f"{agent} 오류율 {rate*100:.0f}% - 즉시 점검 필요")
            elif rate >= _ERROR_RATE_WARN_THRESHOLD:
                recs.append(f"{agent} 오류율 {rate*100:.0f}% - 모니터링 강화")
        if health == "CRITICAL":
            recs.append("CRITICAL 상태: 자동매매 일시 중단 권장")
        return recs

    def _apply_patches(self, patch_requests: list) -> list:
        if not patch_requests:
            return []
        config = self._load_strategy_config()
        applied: list = []
        for req in patch_requests:
            key = req.get("key", "")
            value = req.get("value")
            reason = req.get("reason", "")
            section = req.get("section", "")
            if key not in _PATCHABLE_KEYS:
                continue
            target = config.get(section, {}) if section else config
            old_value = target.get(key)
            if old_value == value:
                continue
            target[key] = value
            if section and section in config:
                config[section] = target
            applied.append({"key": key, "section": section, "old_value": old_value, "new_value": value, "reason": reason})
        if applied:
            try:
                with open(_STRATEGY_CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
            except Exception:
                return []
        return applied
