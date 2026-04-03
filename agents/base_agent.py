"""
모든 에이전트의 공통 기반 클래스.
재시도, 타임아웃, 에러 처리, 로깅 등 공통 인프라를 제공한다.
구체적인 에이전트는 execute() 메서드를 구현해야 한다.
"""

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional

from protocol.protocol import (
    StandardMessage,
    ErrorPayload,
    dataclass_to_dict,
)


class BaseAgent(ABC):
    """
    모든 에이전트의 추상 기반 클래스.

    에이전트 코드(agent_code)는 메시지 라우팅에 사용되며,
    로그 prefix로도 활용된다.
    """

    def __init__(
        self,
        agent_code: str,
        agent_name: str,
        timeout: int,
        max_retries: int = 3,
    ) -> None:
        """
        Args:
            agent_code:  에이전트 고유 코드 (예: "US_COLLECTOR")
            agent_name:  사람이 읽기 쉬운 이름 (예: "미국시장 수집 에이전트")
            timeout:     execute() 단일 실행 제한 시간 (초)
            max_retries: execute() 실패 시 최대 재시도 횟수
        """
        self.agent_code = agent_code
        self.agent_name = agent_name
        self.timeout = timeout
        self.max_retries = max_retries

        # 에이전트 전용 로거 설정
        # 핸들러는 추가하지 않고 main.py setup_logging()의 root logger에 위임한다.
        # propagate=True(기본값)를 유지하여 로그 중복 출력을 방지한다.
        self._logger = logging.getLogger(f"agent.{agent_code}")
        self._logger.setLevel(logging.DEBUG)

    # ------------------------------------------------------------------
    # 로깅 헬퍼
    # ------------------------------------------------------------------

    def _db_log(self, level: str, message: str, error_code: str = "") -> None:
        """실행 결과를 Supabase agent_logs에 저장한다. 실패해도 예외 전파 없음."""
        try:
            from database.db import save_agent_log
            save_agent_log(self.agent_code, level, f"[{self.agent_name}] {message}", error_code)
        except Exception:
            pass  # DB 저장 실패가 에이전트 동작을 멈춰선 안 됨

    def log(self, level: str, message: str) -> None:
        """
        에이전트명 prefix를 붙여 로그를 출력한다.

        Args:
            level:   로그 레벨 문자열 ("DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL")
            message: 로그 메시지
        """
        prefixed = f"[{self.agent_name}] {message}"
        log_fn = getattr(self._logger, level.lower(), self._logger.info)
        log_fn(prefixed)

    # ------------------------------------------------------------------
    # 메시지 생성 헬퍼
    # ------------------------------------------------------------------

    def create_message(
        self,
        to: str,
        data_type: str,
        payload: Any,
        priority: str = "NORMAL",
        msg_type: str = "DATA",
    ) -> StandardMessage:
        """
        이 에이전트를 발신자로 하는 StandardMessage를 생성한다.

        Args:
            to:        수신 에이전트 코드
            data_type: 페이로드 타입 식별자
            payload:   전송할 데이터 (dict 또는 dataclass)
            priority:  CRITICAL | HIGH | NORMAL | LOW
            msg_type:  DATA | SIGNAL | ORDER | RESPONSE | ERROR | HEARTBEAT | COMMAND | ALERT

        Returns:
            StandardMessage 인스턴스
        """
        return StandardMessage.create(
            from_agent=self.agent_code,
            to_agent=to,
            data_type=data_type,
            payload=payload,
            priority=priority,
            msg_type=msg_type,
        )

    def create_error(
        self,
        error_code: str,
        message: str,
        level: str = "MEDIUM",
        retry_count: int = 0,
        auto_fix: bool = False,
        action: str = "",
    ) -> StandardMessage:
        """
        에러 StandardMessage를 생성한다.

        Args:
            error_code:  에러 코드 (예: "NETWORK_TIMEOUT", "PARSE_ERROR")
            message:     상세 에러 메시지 (어떤 에이전트, 어떤 값이 문제인지 포함)
            level:       LOW | MEDIUM | HIGH | CRITICAL
            retry_count: 현재까지의 재시도 횟수
            auto_fix:    자동 복구 가능 여부
            action:      권장 조치 내용

        Returns:
            msg_type="ERROR"인 StandardMessage 인스턴스
        """
        error_id = str(uuid.uuid4())
        payload = ErrorPayload(
            error_id=error_id,
            level=level,
            from_agent=self.agent_code,
            error_code=error_code,
            message=f"[{self.agent_code}] {message}",
            retry_count=retry_count,
            auto_fix=auto_fix,
            action=action,
        )

        msg = StandardMessage.create(
            from_agent=self.agent_code,
            to_agent="OR",          # 오케스트레이터(OR)로 에러 보고
            data_type="ERROR",
            payload=dataclass_to_dict(payload),
            priority="HIGH" if level in ("HIGH", "CRITICAL") else "NORMAL",
            msg_type="ERROR",
        )
        msg.status = {"code": "ERROR", "message": message}
        return msg

    def send_heartbeat(self) -> StandardMessage:
        """
        오케스트레이터(OR)에게 생존 신호를 보내는 HEARTBEAT 메시지를 생성한다.

        Returns:
            msg_type="HEARTBEAT"인 StandardMessage 인스턴스
        """
        return StandardMessage.create(
            from_agent=self.agent_code,
            to_agent="OR",
            data_type="HEARTBEAT",
            payload={
                "agent_code": self.agent_code,
                "agent_name": self.agent_name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "ALIVE",
            },
            priority="LOW",
            msg_type="HEARTBEAT",
        )

    # ------------------------------------------------------------------
    # 실행 인터페이스
    # ------------------------------------------------------------------

    @abstractmethod
    async def execute(self, input_data: Optional[Any] = None) -> StandardMessage:
        """
        에이전트의 실제 비즈니스 로직을 구현하는 추상 메서드.
        하위 클래스에서 반드시 구현해야 한다.

        Args:
            input_data: 이전 에이전트로부터 받은 입력 데이터 (선택)

        Returns:
            처리 결과를 담은 StandardMessage
        """
        raise NotImplementedError(
            f"[{self.agent_code}] execute() 메서드가 구현되지 않았습니다."
        )

    async def run(self, input_data: Optional[Any] = None) -> StandardMessage:
        """
        execute()를 안전하게 실행한다.
        - asyncio.wait_for로 timeout 적용
        - 실패 시 max_retries까지 재시도
        - 모든 재시도 실패 시 ERROR 메시지 반환

        Args:
            input_data: execute()에 전달할 입력 데이터

        Returns:
            execute() 결과 또는 에러 StandardMessage
        """
        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                self.log("info", f"실행 시도 {attempt}/{self.max_retries}")
                result = await asyncio.wait_for(
                    self.execute(input_data),
                    timeout=self.timeout,
                )
                self.log("info", f"실행 완료 (시도 {attempt})")
                self._db_log("INFO", f"실행 완료 (시도 {attempt}/{self.max_retries})")
                return result

            except asyncio.TimeoutError:
                last_error = asyncio.TimeoutError(
                    f"execute() 타임아웃 ({self.timeout}초 초과) — 시도 {attempt}/{self.max_retries}"
                )
                self.log(
                    "warning",
                    f"타임아웃 발생 ({self.timeout}초) — 시도 {attempt}/{self.max_retries}",
                )
                self._db_log("WARNING", f"타임아웃 ({self.timeout}초) — 시도 {attempt}/{self.max_retries}")

            except Exception as exc:
                last_error = exc
                self.log(
                    "error",
                    f"실행 오류: {type(exc).__name__}: {exc} — 시도 {attempt}/{self.max_retries}",
                )
                self._db_log("ERROR", f"{type(exc).__name__}: {exc}", error_code=type(exc).__name__)

            # 마지막 시도가 아니면 잠시 대기 후 재시도
            if attempt < self.max_retries:
                await asyncio.sleep(0.5 * attempt)  # 점진적 대기 (0.5s, 1.0s, ...)

        # 모든 재시도 실패 → ERROR 메시지 반환
        error_message = str(last_error) if last_error else "알 수 없는 오류"
        error_type = type(last_error).__name__ if last_error else "UnknownError"

        self.log("error", f"모든 재시도 실패. 마지막 오류: {error_message}")
        self._db_log("ERROR", f"모든 재시도 실패: {error_message}", error_code=error_type)

        return self.create_error(
            error_code=error_type,
            message=f"최대 재시도 횟수({self.max_retries})를 초과했습니다. 마지막 오류: {error_message}",
            level="HIGH",
            retry_count=self.max_retries,
            auto_fix=False,
            action="로그를 확인하고 에이전트 상태를 점검하세요.",
        )
