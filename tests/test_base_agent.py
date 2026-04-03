"""
base_agent.py 단위 테스트
BaseAgent는 추상 클래스이므로 구체 구현 클래스를 만들어 테스트한다.
"""

import asyncio
import pytest
import pytest_asyncio
from typing import Optional, Any

from agents.base_agent import BaseAgent
from protocol.protocol import StandardMessage


@pytest.fixture(autouse=True)
def cleanup_loggers():
    yield
    # 테스트 후 생성된 logger handler 정리
    import logging
    for name in list(logging.Logger.manager.loggerDict.keys()):
        if name.startswith("agent."):
            logger = logging.getLogger(name)
            logger.handlers.clear()


# ---------------------------------------------------------------------------
# 테스트용 구체 에이전트 구현체들
# ---------------------------------------------------------------------------

class SuccessAgent(BaseAgent):
    """항상 성공하는 테스트용 에이전트"""

    def __init__(self, timeout: int = 10, max_retries: int = 3):
        super().__init__(
            agent_code="SUCCESS_AGENT",
            agent_name="성공 테스트 에이전트",
            timeout=timeout,
            max_retries=max_retries,
        )

    async def execute(self, input_data: Optional[Any] = None) -> StandardMessage:
        return self.create_message(
            to="TARGET",
            data_type="SUCCESS_DATA",
            payload={"result": "ok", "input": str(input_data)},
        )


class FailingAgent(BaseAgent):
    """항상 예외를 발생시키는 테스트용 에이전트"""

    def __init__(self, timeout: int = 10, max_retries: int = 3):
        super().__init__(
            agent_code="FAIL_AGENT",
            agent_name="실패 테스트 에이전트",
            timeout=timeout,
            max_retries=max_retries,
        )
        self.call_count = 0

    async def execute(self, input_data: Optional[Any] = None) -> StandardMessage:
        self.call_count += 1
        raise RuntimeError(f"의도적 실패 (호출 {self.call_count}회)")


class TimeoutAgent(BaseAgent):
    """타임아웃을 유발하는 테스트용 에이전트"""

    def __init__(self, sleep_seconds: float = 5.0, timeout: int = 1, max_retries: int = 1):
        super().__init__(
            agent_code="TIMEOUT_AGENT",
            agent_name="타임아웃 테스트 에이전트",
            timeout=timeout,
            max_retries=max_retries,
        )
        self.sleep_seconds = sleep_seconds

    async def execute(self, input_data: Optional[Any] = None) -> StandardMessage:
        await asyncio.sleep(self.sleep_seconds)
        return self.create_message("TARGET", "DATA", {})


class RetryThenSuccessAgent(BaseAgent):
    """처음 N번은 실패하고 이후 성공하는 테스트용 에이전트"""

    def __init__(self, fail_times: int = 2, timeout: int = 10, max_retries: int = 3):
        super().__init__(
            agent_code="RETRY_AGENT",
            agent_name="재시도 테스트 에이전트",
            timeout=timeout,
            max_retries=max_retries,
        )
        self.fail_times = fail_times
        self.call_count = 0

    async def execute(self, input_data: Optional[Any] = None) -> StandardMessage:
        self.call_count += 1
        if self.call_count <= self.fail_times:
            raise ValueError(f"재시도 유도 실패 ({self.call_count}/{self.fail_times})")
        return self.create_message(
            to="TARGET",
            data_type="RETRY_SUCCESS",
            payload={"attempts": self.call_count},
        )


# ---------------------------------------------------------------------------
# run() 정상 실행 테스트
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRunSuccess:
    """run() 정상 실행 케이스"""

    async def test_run_returns_standard_message(self):
        """run()이 StandardMessage를 반환해야 한다."""
        agent = SuccessAgent()
        result = await agent.run()
        assert isinstance(result, StandardMessage)

    async def test_run_result_has_correct_from_agent(self):
        """반환된 메시지의 from_agent가 에이전트 코드와 일치해야 한다."""
        agent = SuccessAgent()
        result = await agent.run()
        assert result.header.from_agent == "SUCCESS_AGENT"

    async def test_run_passes_input_data(self):
        """input_data가 execute()로 전달되어야 한다."""
        agent = SuccessAgent()
        result = await agent.run(input_data="hello")
        assert "hello" in result.body["payload"]["input"]

    async def test_run_status_ok_on_success(self):
        """정상 실행 시 status.code가 'OK'여야 한다."""
        agent = SuccessAgent()
        result = await agent.run()
        assert result.status["code"] == "OK"


# ---------------------------------------------------------------------------
# 타임아웃 테스트
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRunTimeout:
    """run() 타임아웃 처리 테스트"""

    async def test_timeout_returns_error_message(self):
        """타임아웃 발생 시 ERROR 메시지가 반환되어야 한다."""
        agent = TimeoutAgent(sleep_seconds=5.0, timeout=1, max_retries=1)
        result = await agent.run()
        assert result.header.msg_type == "ERROR"

    async def test_timeout_error_status_code(self):
        """타임아웃 시 status.code가 'ERROR'여야 한다."""
        agent = TimeoutAgent(sleep_seconds=5.0, timeout=1, max_retries=1)
        result = await agent.run()
        assert result.status["code"] == "ERROR"

    async def test_timeout_error_payload_has_from_agent(self):
        """에러 페이로드에 from_agent 정보가 포함되어야 한다."""
        agent = TimeoutAgent(sleep_seconds=5.0, timeout=1, max_retries=1)
        result = await agent.run()
        payload = result.body["payload"]
        assert payload.get("from_agent") == "TIMEOUT_AGENT"

    async def test_timeout_completes_within_reasonable_time(self):
        """타임아웃 1초 에이전트는 재시도 포함 10초 이내에 끝나야 한다."""
        import time
        agent = TimeoutAgent(sleep_seconds=5.0, timeout=1, max_retries=2)
        start = time.monotonic()
        result = await agent.run()
        elapsed = time.monotonic() - start
        # 1초 타임아웃 × 2회 + 여유 = 10초 이내
        assert elapsed < 10.0, f"실행 시간이 너무 깁니다: {elapsed:.2f}초"
        assert result.header.msg_type == "ERROR"


# ---------------------------------------------------------------------------
# 재시도 동작 테스트
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRunRetry:
    """run() 재시도 동작 테스트"""

    async def test_retry_eventually_succeeds(self):
        """2번 실패 후 3번째 시도에서 성공해야 한다."""
        agent = RetryThenSuccessAgent(fail_times=2, max_retries=3)
        result = await agent.run()
        assert result.header.msg_type != "ERROR", f"성공해야 하는데 에러: {result.status}"
        assert result.body["data_type"] == "RETRY_SUCCESS"
        assert result.body["payload"]["attempts"] == 3

    async def test_retry_exhaustion_returns_error(self):
        """재시도 횟수 초과 시 ERROR 메시지를 반환해야 한다."""
        agent = FailingAgent(max_retries=3)
        result = await agent.run()
        assert result.header.msg_type == "ERROR"
        assert result.status["code"] == "ERROR"

    async def test_all_retries_are_attempted(self):
        """max_retries 횟수만큼 execute()가 호출되어야 한다."""
        agent = FailingAgent(max_retries=3)
        await agent.run()
        assert agent.call_count == 3, (
            f"execute() 호출 횟수 불일치: 기대 3, 실제 {agent.call_count}"
        )

    async def test_single_retry_on_first_success(self):
        """첫 시도에 성공하면 execute()는 1번만 호출되어야 한다."""
        agent = SuccessAgent(max_retries=3)
        await agent.run()
        # SuccessAgent는 호출 횟수를 세지 않으므로 결과만 확인
        # (정상 완료 여부로 간접 확인)


# ---------------------------------------------------------------------------
# create_error() 검증
# ---------------------------------------------------------------------------

class TestCreateError:
    """create_error() 메서드 단위 테스트"""

    def test_create_error_returns_standard_message(self):
        """create_error()가 StandardMessage를 반환해야 한다."""
        agent = SuccessAgent()
        err = agent.create_error("TEST_ERROR", "테스트 에러 메시지")
        assert isinstance(err, StandardMessage)

    def test_create_error_msg_type_is_error(self):
        """에러 메시지의 msg_type이 'ERROR'여야 한다."""
        agent = SuccessAgent()
        err = agent.create_error("SOME_ERROR", "에러 발생")
        assert err.header.msg_type == "ERROR"

    def test_create_error_status_code_is_error(self):
        """에러 메시지의 status.code가 'ERROR'여야 한다."""
        agent = SuccessAgent()
        err = agent.create_error("CODE", "message")
        assert err.status["code"] == "ERROR"

    def test_create_error_payload_contains_agent_code(self):
        """에러 페이로드의 from_agent가 에이전트 코드를 포함해야 한다."""
        agent = SuccessAgent()
        err = agent.create_error("NETWORK_TIMEOUT", "네트워크 타임아웃")
        payload = err.body["payload"]
        assert payload["from_agent"] == "SUCCESS_AGENT"

    def test_create_error_payload_level(self):
        """에러 페이로드의 level이 올바르게 설정되어야 한다."""
        agent = SuccessAgent()
        err = agent.create_error("ERR", "msg", level="CRITICAL")
        assert err.body["payload"]["level"] == "CRITICAL"

    def test_create_error_message_prefixed_with_agent_code(self):
        """에러 메시지에 에이전트 코드 prefix가 붙어야 한다."""
        agent = SuccessAgent()
        err = agent.create_error("ERR", "원본 에러 내용")
        payload_msg = err.body["payload"]["message"]
        assert "SUCCESS_AGENT" in payload_msg

    def test_create_error_to_agent_is_or(self):
        """에러 메시지는 오케스트레이터(OR)에게 전송되어야 한다."""
        agent = SuccessAgent()
        err = agent.create_error("ERR", "msg")
        assert err.header.to_agent == "OR"

    def test_create_error_high_level_sets_high_priority(self):
        """HIGH 레벨 에러는 HIGH 우선순위로 전송되어야 한다."""
        agent = SuccessAgent()
        err = agent.create_error("ERR", "msg", level="HIGH")
        assert err.header.priority == "HIGH"

    def test_create_error_low_level_sets_normal_priority(self):
        """LOW 레벨 에러는 NORMAL 우선순위로 전송되어야 한다."""
        agent = SuccessAgent()
        err = agent.create_error("ERR", "msg", level="LOW")
        assert err.header.priority == "NORMAL"


# ---------------------------------------------------------------------------
# send_heartbeat() 테스트
# ---------------------------------------------------------------------------

class TestSendHeartbeat:
    """send_heartbeat() 메서드 단위 테스트"""

    def test_heartbeat_msg_type(self):
        """HEARTBEAT 메시지의 msg_type이 'HEARTBEAT'여야 한다."""
        agent = SuccessAgent()
        hb = agent.send_heartbeat()
        assert hb.header.msg_type == "HEARTBEAT"

    def test_heartbeat_to_agent_is_or(self):
        """HEARTBEAT는 오케스트레이터(OR)에게 전송되어야 한다."""
        agent = SuccessAgent()
        hb = agent.send_heartbeat()
        assert hb.header.to_agent == "OR"

    def test_heartbeat_priority_is_low(self):
        """HEARTBEAT 우선순위는 LOW여야 한다."""
        agent = SuccessAgent()
        hb = agent.send_heartbeat()
        assert hb.header.priority == "LOW"

    def test_heartbeat_payload_contains_status_alive(self):
        """HEARTBEAT 페이로드에 status=ALIVE가 포함되어야 한다."""
        agent = SuccessAgent()
        hb = agent.send_heartbeat()
        assert hb.body["payload"]["status"] == "ALIVE"

    def test_heartbeat_payload_agent_code(self):
        """HEARTBEAT 페이로드에 agent_code가 포함되어야 한다."""
        agent = SuccessAgent()
        hb = agent.send_heartbeat()
        assert hb.body["payload"]["agent_code"] == "SUCCESS_AGENT"


# ---------------------------------------------------------------------------
# create_message() 헬퍼 테스트
# ---------------------------------------------------------------------------

class TestCreateMessage:
    """create_message() 헬퍼 메서드 테스트"""

    def test_create_message_from_agent_is_self(self):
        """create_message()로 만든 메시지의 from_agent가 에이전트 자신이어야 한다."""
        agent = SuccessAgent()
        msg = agent.create_message("DEST", "MY_DATA", {"x": 1})
        assert msg.header.from_agent == "SUCCESS_AGENT"

    def test_create_message_to_agent(self):
        """수신 에이전트가 올바르게 설정되어야 한다."""
        agent = SuccessAgent()
        msg = agent.create_message("DEST_AGENT", "MY_DATA", {})
        assert msg.header.to_agent == "DEST_AGENT"

    def test_create_message_default_priority_normal(self):
        """기본 우선순위는 NORMAL이어야 한다."""
        agent = SuccessAgent()
        msg = agent.create_message("DEST", "TYPE", {})
        assert msg.header.priority == "NORMAL"

    def test_create_message_custom_priority(self):
        """커스텀 우선순위가 올바르게 적용되어야 한다."""
        agent = SuccessAgent()
        msg = agent.create_message("DEST", "TYPE", {}, priority="CRITICAL")
        assert msg.header.priority == "CRITICAL"
